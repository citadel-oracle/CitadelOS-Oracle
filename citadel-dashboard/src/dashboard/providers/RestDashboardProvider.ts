import { DASHBOARD_SCHEMA_VERSION, DEFAULT_SYMBOL, MOCK_EMISSION_INTERVAL_MS } from '../constants'
import type { DashboardDataProvider } from '../contracts'
import { ingestOracleDashboardSnapshot } from '../store/oracleStore'
import { DASHBOARD_FEED_KEYS, type DashboardFeedKey, type DashboardFeedMeta, type DashboardSourceSnapshot } from '../types'

type BackendFeed = { ok: boolean; data: unknown; error: { code?: string; message?: string } | null; meta: DashboardFeedMeta }
type BackendDashboard = {
  trace_id: string
  generated_at: string
  revision?: number
  runtime_instance_id?: string
  symbol?: string
  feeds: Record<string, BackendFeed>
  polling?: { recommended_interval_ms?: number; served_from_cache?: boolean; projection_age_ms?: number }
}
type OracleLiveEvent = {
  event_id: string
  event_type: string
  published_at: string
  state_hash: string
  delivery_mode?: 'INITIAL_STATE' | 'REPLAY' | 'LIVE'
  projection: Record<string, unknown>
}
type OracleFastLaneEvent = {
  event_id: string
  event_type: 'ORACLE_FAST_LANE_UPDATED' | 'FLOW_PULSE_ACTION' | 'FLOW_PULSE_METERS'
  published_at: string
  trace_id: string
  generated_at: string
  symbol: string
  feeds?: Record<string, BackendFeed>
  flow_pulse?: Record<string, unknown>
  full: boolean
  global_revision?: number
  runtime_instance_id?: string
}

export const ORACLE_BACKEND_BASE_URL = process.env.NEXT_PUBLIC_CITADEL_API_URL ?? 'http://127.0.0.1:8000'
const API_URL = ORACLE_BACKEND_BASE_URL
const ORACLE_FAST_LANE_PATH = '/v1/oracle/fast-lane'
const ORACLE_FAST_LANE_STREAM_PATH = '/v1/oracle/fast-lane/stream'
const REQUEST_TIMEOUT_MS = 15_000
const auditConfig = () => {
  if (typeof window === 'undefined') return null
  const query = new URLSearchParams(window.location.search)
  if (query.get('hudAuditCollector') !== 'true') return null
  return `http://127.0.0.1:${query.get('hudAuditCollectorPort') || '8110'}/browser-event`
}
const auditBrowser = (event: Record<string, unknown>) => {
  const endpoint = auditConfig()
  if (!endpoint) return
  const body = JSON.stringify({ ...event, browser_epoch_ms: Date.now(), origin: window.location.origin })
  if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
    navigator.sendBeacon(endpoint, body)
  }
}
const isoUtc = (value: string | undefined) => {
  const parsed = value ? new Date(value) : new Date()
  return Number.isNaN(parsed.getTime()) ? new Date().toISOString() : parsed.toISOString()
}

export interface FastLaneRevisionCursor {
  activeRuntimeInstanceId: string | null
  retiredRuntimeInstanceIds: ReadonlySet<string>
  lastAppliedRevision: number
}

export function advanceFastLaneRevision(
  cursor: FastLaneRevisionCursor,
  runtimeInstanceId?: string,
  revision?: number,
): FastLaneRevisionCursor | null {
  const runtime = runtimeInstanceId || 'LEGACY_RUNTIME'
  if (!Number.isInteger(revision) || (revision as number) < 0) return null
  if (cursor.retiredRuntimeInstanceIds.has(runtime)) return null
  if (cursor.activeRuntimeInstanceId === runtime) {
    if ((revision as number) <= cursor.lastAppliedRevision) return null
    return { ...cursor, lastAppliedRevision: revision as number }
  }
  const retired = new Set(cursor.retiredRuntimeInstanceIds)
  if (cursor.activeRuntimeInstanceId) retired.add(cursor.activeRuntimeInstanceId)
  return {
    activeRuntimeInstanceId: runtime,
    retiredRuntimeInstanceIds: retired,
    lastAppliedRevision: revision as number,
  }
}

export class RestDashboardProvider implements DashboardDataProvider {
  readonly kind = 'rest' as const
  private listeners = new Set<(snapshot: DashboardSourceSnapshot) => void>()
  private timer: ReturnType<typeof setTimeout> | null = null
  private controller: AbortController | null = null
  private eventSource: EventSource | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private symbol = DEFAULT_SYMBOL
  private intervalMs = MOCK_EMISSION_INTERVAL_MS
  private running = false
  private inFlight = false
  private lastSnapshot: DashboardSourceSnapshot | null = null
  private lastLiveHash: string | null = null
  private lastSseEventId: string | null = null
  private fastLaneRevisionCursor: FastLaneRevisionCursor = {
    activeRuntimeInstanceId: null,
    retiredRuntimeInstanceIds: new Set<string>(),
    lastAppliedRevision: -1,
  }
  private pendingOracleEvent: OracleLiveEvent | null = null
  private pendingFastLaneEvents: OracleFastLaneEvent[] = []
  private sseConnected = false
  private lastSseEventAt = 0
  private readonly domAuditListener = (raw: Event) => {
    const detail = raw instanceof CustomEvent && typeof raw.detail === 'object' && raw.detail !== null
      ? raw.detail as Record<string, unknown> : {}
    auditBrowser({ event_type: 'DOM_SEMANTIC_COMMIT', ...detail })
  }

  constructor(private readonly oracleFastLane = false) {}

  start() {
    if (this.running) return
    this.running = true
    if (typeof window !== 'undefined') window.addEventListener('citadel:oracle-dom-commit', this.domAuditListener)
    auditBrowser({
      event_type: 'BACKEND_CONTRACT', backend_base_url: API_URL,
      fast_lane_url: `${API_URL}${ORACLE_FAST_LANE_PATH}`,
      eventsource_url: `${API_URL}${ORACLE_FAST_LANE_STREAM_PATH}`,
    })
    void this.load(); this.connectSse()
  }
  stop() {
    this.running = false
    if (this.timer) clearTimeout(this.timer)
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.timer = null; this.reconnectTimer = null
    this.controller?.abort(); this.controller = null
    this.eventSource?.close(); this.eventSource = null; this.sseConnected = false
    if (typeof window !== 'undefined') window.removeEventListener('citadel:oracle-dom-commit', this.domAuditListener)
  }
  setSymbol(symbol: string) { this.symbol = symbol; if (this.running) void this.load(true) }
  refresh() { if (this.running) void this.load(true) }
  subscribe(listener: (snapshot: DashboardSourceSnapshot) => void) { this.listeners.add(listener); return () => this.listeners.delete(listener) }

  private schedule() {
    if (!this.running) return
    if (this.timer) clearTimeout(this.timer)
    const pushHealthy = this.sseConnected && Date.now() - this.lastSseEventAt < 12_000
    if (this.sseConnected && !pushHealthy) this.reconnectSse()
    this.timer = setTimeout(() => void this.load(), pushHealthy ? Math.max(10_000, this.intervalMs) : this.intervalMs)
  }

  private async load(force = false) {
    if (!this.running) return
    if (this.inFlight) { if (force) this.controller?.abort(); return }
    this.inFlight = true
    const controller = new AbortController()
    this.controller = controller
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
    try {
      const path = this.oracleFastLane
        ? `${API_URL}${ORACLE_FAST_LANE_PATH}`
        : `${API_URL}/v2/dashboard?symbol=${encodeURIComponent(this.symbol)}`
      const response = await fetch(path, { cache: 'no-store', signal: controller.signal })
      if (!response.ok) throw new Error(`Dashboard projection HTTP ${response.status}`)
      auditBrowser({ event_type: 'FETCH_OK', url: path, status: response.status })
      const backend = await response.json() as BackendDashboard
      if (this.oracleFastLane && !this.acceptFastLaneRevision(
        backend.runtime_instance_id,
        backend.revision,
      )) return
      this.intervalMs = Math.max(1_000, backend.polling?.recommended_interval_ms ?? MOCK_EMISSION_INTERVAL_MS)
      const generatedAt = isoUtc(backend.generated_at)
      const feeds = Object.fromEntries(DASHBOARD_FEED_KEYS.map((key) => [key, backend.feeds[key]?.data ?? null])) as Record<DashboardFeedKey, unknown>
      const oracle = feeds.oracle
      if (typeof oracle === 'object' && oracle !== null) {
        const live = (oracle as Record<string, unknown>).live_workspace
        if (typeof live === 'object' && live !== null) {
          const projection = live as Record<string, unknown>
          const contentHash = typeof projection.content_hash === 'string' ? projection.content_hash : null
          const previousOracle = this.lastSnapshot?.feeds.oracle
          const previousLive = typeof previousOracle === 'object' && previousOracle !== null
            ? (previousOracle as Record<string, unknown>).live_workspace : null
          const previousTransport = typeof previousLive === 'object' && previousLive !== null
            ? (previousLive as Record<string, unknown>).frontend_transport : null
          const preservePushTransport = contentHash !== null && contentHash === this.lastLiveHash
            && typeof previousTransport === 'object' && previousTransport !== null
            && (previousTransport as Record<string, unknown>).transport === 'SSE'
          feeds.oracle = { ...oracle, live_workspace: { ...projection, frontend_transport: {
            ...(preservePushTransport ? previousTransport : {}),
            transport: preservePushTransport ? 'SSE' : 'POLLING_FALLBACK',
            received_at_epoch_ms: preservePushTransport
              ? (previousTransport as Record<string, unknown>).received_at_epoch_ms : Date.now(),
            event_receipt_ms: preservePushTransport
              ? (previousTransport as Record<string, unknown>).event_receipt_ms : null,
          } } }
          if (contentHash) this.lastLiveHash = contentHash
        }
      }
      const cachedProjectionStale = backend.polling?.served_from_cache === true && (backend.polling.projection_age_ms ?? 0) > REQUEST_TIMEOUT_MS
      const feedMeta = Object.fromEntries(DASHBOARD_FEED_KEYS.map((key) => {
        const meta = backend.feeds[key]?.meta ?? this.unavailableMeta(generatedAt)
        return [key, cachedProjectionStale
          ? { ...meta, health: 'STALE', readiness: 'DEGRADED', stale_reason: `CACHED_PROJECTION_AGE_${Math.round(backend.polling?.projection_age_ms ?? 0)}MS` }
          : meta] as const
      })) as Record<DashboardFeedKey, DashboardFeedMeta>
      this.lastSnapshot = {
        schemaVersion: DASHBOARD_SCHEMA_VERSION,
        provider: this.kind,
        traceId: backend.trace_id || `rest-${generatedAt}`,
        generatedAt,
        sourceRevision: backend.revision,
        runtimeInstanceId: backend.runtime_instance_id,
        selectedSymbol: backend.symbol || this.symbol,
        feeds,
        feedMeta,
      }
      this.publish(this.lastSnapshot)
      if (this.pendingOracleEvent) {
        const pending = this.pendingOracleEvent
        this.pendingOracleEvent = null
        this.applyOracleEvent(pending)
      }
      if (this.pendingFastLaneEvents.length) {
        const pending = this.pendingFastLaneEvents.splice(0)
        pending.forEach((event) => this.applyFastLaneEvent(event))
      }
    } catch (error) {
      const path = this.oracleFastLane
        ? `${API_URL}${ORACLE_FAST_LANE_PATH}`
        : `${API_URL}/v2/dashboard?symbol=${encodeURIComponent(this.symbol)}`
      auditBrowser({
        event_type: 'FETCH_FAILED', url: path,
        error_class: error instanceof Error ? error.name : 'UNKNOWN_ERROR',
        error_message: error instanceof Error ? error.message : String(error),
      })
      if (controller.signal.aborted && !this.running) return
      const generatedAt = this.lastSnapshot?.generatedAt ?? new Date().toISOString()
      const stale = this.lastSnapshot
        ? { ...this.lastSnapshot, feedMeta: Object.fromEntries(DASHBOARD_FEED_KEYS.map((key) => [key, { ...this.lastSnapshot!.feedMeta[key], health: 'STALE', readiness: 'DEGRADED' }])) as Record<DashboardFeedKey, DashboardFeedMeta> }
        : { schemaVersion: DASHBOARD_SCHEMA_VERSION, provider: this.kind, traceId: `rest-unavailable-${generatedAt}`, generatedAt, selectedSymbol: this.symbol, feeds: Object.fromEntries(DASHBOARD_FEED_KEYS.map((key) => [key, null])) as Record<DashboardFeedKey, unknown>, feedMeta: Object.fromEntries(DASHBOARD_FEED_KEYS.map((key) => [key, this.unavailableMeta(generatedAt)])) as Record<DashboardFeedKey, DashboardFeedMeta> }
      this.publish(stale)
    } finally {
      clearTimeout(timeout)
      if (this.controller === controller) this.controller = null
      this.inFlight = false
      this.schedule()
    }
  }

  private connectSse() {
    if (!this.running || this.eventSource || typeof EventSource === 'undefined') return
    const replay = this.lastSseEventId ? `?after_event_id=${encodeURIComponent(this.lastSseEventId)}` : ''
    const streamPath = this.oracleFastLane
      ? `${API_URL}${ORACLE_FAST_LANE_STREAM_PATH}${replay}`
      : `${API_URL}/v1/oracle/live-workspace/stream${replay}`
    const source = new EventSource(streamPath)
    this.eventSource = source
    source.onopen = () => {
      this.sseConnected = true; this.lastSseEventAt = Date.now()
      auditBrowser({ event_type: 'EVENTSOURCE_CONNECTED', url: streamPath })
    }
    source.addEventListener('oracle_heartbeat', () => { this.sseConnected = true; this.lastSseEventAt = Date.now() })
    source.addEventListener('oracle_projection', (raw) => {
      this.sseConnected = true
      this.lastSseEventAt = Date.now()
      try { this.applyOracleEvent(JSON.parse((raw as MessageEvent<string>).data) as OracleLiveEvent) } catch { /* polling remains authoritative fallback */ }
    })
    source.addEventListener('oracle_fast_lane', (raw) => {
      this.sseConnected = true
      this.lastSseEventAt = Date.now()
      try { this.applyFastLaneEvent(JSON.parse((raw as MessageEvent<string>).data) as OracleFastLaneEvent) } catch { /* cached GET remains recovery fallback */ }
    })
    source.addEventListener('oracle_fast_heartbeat', () => { this.sseConnected = true; this.lastSseEventAt = Date.now() })
    source.onerror = () => {
      this.sseConnected = false
      auditBrowser({ event_type: 'EVENTSOURCE_DISCONNECTED', url: streamPath, error_class: 'EVENTSOURCE_ERROR' })
      this.reconnectSse(); if (this.running) void this.load(true)
    }
  }

  private reconnectSse() {
    this.eventSource?.close(); this.eventSource = null; this.sseConnected = false
    if (!this.running || this.reconnectTimer) return
    this.reconnectTimer = setTimeout(() => { this.reconnectTimer = null; this.connectSse() }, 1_500)
  }

  private applyOracleEvent(event: OracleLiveEvent) {
    this.lastSseEventId = event.event_id
    if (!this.lastSnapshot) { this.pendingOracleEvent = event; return }
    if (!event.projection) return
    const oracle = this.lastSnapshot.feeds.oracle
    if (typeof oracle !== 'object' || oracle === null) return
    const currentLive = (oracle as Record<string, unknown>).live_workspace
    const currentTransport = typeof currentLive === 'object' && currentLive !== null
      ? (currentLive as Record<string, unknown>).frontend_transport : null
    if (event.state_hash === this.lastLiveHash && typeof currentTransport === 'object' && currentTransport !== null
        && (currentTransport as Record<string, unknown>).transport === 'SSE') return
    const receivedAt = Date.now()
    const publishedAt = new Date(event.published_at).getTime()
    const eventReceiptMs = event.delivery_mode === 'LIVE' && Number.isFinite(publishedAt)
      ? Math.max(0, receivedAt - publishedAt) : null
    const projection = { ...event.projection, frontend_transport: {
      transport: 'SSE', event_id: event.event_id, event_type: event.event_type,
      delivery_mode: event.delivery_mode,
      received_at_epoch_ms: receivedAt, event_receipt_ms: eventReceiptMs,
    } }
    let futuresChart = this.lastSnapshot.feeds.futures_chart
    const forecast = event.projection.futures_forecast
    if (typeof forecast === 'object' && forecast !== null
        && typeof futuresChart === 'object' && futuresChart !== null) {
      const chart = futuresChart as Record<string, unknown>
      const lanes = typeof chart.timeframes === 'object' && chart.timeframes !== null
        ? chart.timeframes as Record<string, unknown> : {}
      const fiveMinute = typeof lanes['5m'] === 'object' && lanes['5m'] !== null
        ? lanes['5m'] as Record<string, unknown> : null
      futuresChart = {
        ...chart,
        forecast,
        timeframes: fiveMinute ? { ...lanes, '5m': { ...fiveMinute, forecast } } : lanes,
      }
    }
    const feeds = {
      ...this.lastSnapshot.feeds,
      futures_chart: futuresChart,
      oracle: { ...oracle, live_workspace: projection },
    }
    const feedMeta = { ...this.lastSnapshot.feedMeta, oracle: {
      ...this.lastSnapshot.feedMeta.oracle, health: 'HEALTHY', readiness: 'READY',
      last_updated: new Date(receivedAt).toISOString(),
    } }
    this.lastLiveHash = event.state_hash
    this.lastSnapshot = { ...this.lastSnapshot, traceId: event.event_id,
      generatedAt: isoUtc(String(event.projection.generated_timestamp ?? event.published_at)), feeds, feedMeta }
    this.publish(this.lastSnapshot)
  }

  private applyFastLaneEvent(event: OracleFastLaneEvent) {
    this.lastSseEventId = event.event_id
    auditBrowser({ event_type: 'SSE_REVISION', revision: event.event_id, event_kind: event.event_type })
    if (!this.lastSnapshot) {
      this.pendingFastLaneEvents.push(event)
      if (this.pendingFastLaneEvents.length > 32) this.pendingFastLaneEvents.shift()
      return
    }
    if ((event.event_type === 'FLOW_PULSE_ACTION' || event.event_type === 'FLOW_PULSE_METERS') && event.flow_pulse) {
      this.applyFlowPulseEvent(event)
      return
    }
    if (!this.acceptFastLaneRevision(event.runtime_instance_id, event.global_revision)) return
    const feeds = { ...this.lastSnapshot.feeds }
    const feedMeta = { ...this.lastSnapshot.feedMeta }
    const receivedAt = Date.now()
    const publishedAt = new Date(event.published_at).getTime()
    const receiptMs = Number.isFinite(publishedAt) ? Math.max(0, receivedAt - publishedAt) : null
    for (const key of DASHBOARD_FEED_KEYS) {
      const incoming = event.feeds?.[key]
      if (!incoming) continue
      if (key === 'futures_chart' && incoming.ok && typeof incoming.data === 'object' && incoming.data !== null) {
        feeds[key] = { ...incoming.data, frontend_transport: {
          transport: 'SSE', event_id: event.event_id, event_type: event.event_type,
          browser_receive_epoch_ms: receivedAt, event_receipt_ms: receiptMs,
          published_at: event.published_at,
        } }
      } else {
        feeds[key] = incoming.ok ? incoming.data : null
      }
      feedMeta[key] = incoming.meta ?? this.unavailableMeta(event.generated_at)
    }
    this.lastSnapshot = {
      ...this.lastSnapshot,
      traceId: event.trace_id,
      generatedAt: isoUtc(event.generated_at),
      sourceRevision: event.global_revision,
      runtimeInstanceId: event.runtime_instance_id,
      selectedSymbol: event.symbol || this.symbol,
      feeds,
      feedMeta,
    }
    this.publish(this.lastSnapshot)
  }

  private applyFlowPulseEvent(event: OracleFastLaneEvent) {
    if (!this.lastSnapshot || !event.flow_pulse) return
    const currentOrderFlow = this.lastSnapshot.feeds.order_flow
    if (typeof currentOrderFlow !== 'object' || currentOrderFlow === null) return
    const orderFlow = currentOrderFlow as Record<string, unknown>
    const currentPulse = typeof orderFlow.flow_pulse === 'object' && orderFlow.flow_pulse !== null
      ? orderFlow.flow_pulse as Record<string, unknown> : {}
    const receivedAt = Date.now()
    const publishedAt = new Date(event.published_at).getTime()
    const receiptMs = Number.isFinite(publishedAt) ? Math.max(0, receivedAt - publishedAt) : null
    let pulse: Record<string, unknown>
    if (event.event_type === 'FLOW_PULSE_ACTION') {
      const action = event.flow_pulse
      const currentFutures = typeof currentPulse.futures === 'object' && currentPulse.futures !== null
        ? currentPulse.futures as Record<string, unknown> : {}
      const option = typeof action.option === 'object' && action.option !== null
        ? action.option as Record<string, unknown> : null
      pulse = {
        ...currentPulse,
        action_revision: action.revision,
        semantic_revision: action.semantic_revision,
        headline: action.headline,
        model: action.model,
        story: action.story,
        key_level: action.key_level,
        area: typeof action.key_level === 'object' && action.key_level !== null
          ? (action.key_level as Record<string, unknown>).label : currentPulse.area,
        state: action.episode_state,
        side: option?.option_type ?? currentPulse.side,
        option: action.option,
        source_timestamp: action.source_timestamp,
        packet_receive_ns: action.packet_receive_ns,
        futures: {
          ...currentFutures,
          trigger: action.trigger,
          invalidation: action.stop,
          target_1: action.target_1,
          target_2: action.target_2,
        },
      }
    } else {
      pulse = { ...currentPulse, ...event.flow_pulse }
    }
    pulse.frontend_transport = {
      transport: 'SSE', event_id: event.event_id, event_type: event.event_type,
      browser_receive_epoch_ms: receivedAt, event_receipt_ms: receiptMs,
    }
    const feeds = {
      ...this.lastSnapshot.feeds,
      order_flow: { ...orderFlow, flow_pulse: pulse },
    }
    const feedMeta = {
      ...this.lastSnapshot.feedMeta,
      order_flow: {
        ...this.lastSnapshot.feedMeta.order_flow,
        health: 'HEALTHY', readiness: 'READY', last_updated: new Date(receivedAt).toISOString(),
      },
    }
    this.lastSnapshot = {
      ...this.lastSnapshot,
      traceId: event.trace_id,
      generatedAt: isoUtc(event.generated_at),
      feeds,
      feedMeta,
    }
    this.publish(this.lastSnapshot)
  }

  private publish(snapshot: DashboardSourceSnapshot) {
    ingestOracleDashboardSnapshot(snapshot)
    this.listeners.forEach((listener) => listener(snapshot))
  }
  private acceptFastLaneRevision(runtimeInstanceId?: string, revision?: number) {
    const next = advanceFastLaneRevision(this.fastLaneRevisionCursor, runtimeInstanceId, revision)
    if (!next) return false
    this.fastLaneRevisionCursor = next
    return true
  }
  private unavailableMeta(timestamp: string): DashboardFeedMeta { return { health: 'OFFLINE', readiness: 'UNAVAILABLE', latency_ms: 0, last_updated: timestamp, source_last_updated: null } }
}
