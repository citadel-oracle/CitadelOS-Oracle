'use client'

import React, { useEffect, useMemo, useRef, useState, memo } from 'react'
import type { DashboardFeedMeta, DashboardFeedState } from '@/dashboard/types'
import { LivingMarketForcesViewport, LivingMarketState } from './LivingMarketForcesViewport'
import {
  formatSensorAsOf,
  selectOracleDeterministicSensors,
  type DeterministicSensorReading,
} from './oracleDeterministicSensors'
import styles from './GeminiMarketBrainSection.module.css'
import { CognitiveDecisionCore, CognitiveDrawer, type CockpitWorldContext } from './CognitiveDecisionCore'
import { CitadelLiveIsland } from './CitadelLiveIsland'

interface SolBeaconState {
  system_status: string
  reasoning_status: string
  market_verdict: string | null
  developing_state: string
  why_bullets: string[]
  main_contradiction: string
  what_changed: string
  thesis_timestamp_ist: string
  feed_age_ms: number | null
  configured_model: string
  actually_invoked_model: string
  replay_mode?: boolean
  canonical_market_state?: LivingMarketState | null
  state_revision?: number
  runtime_instance_id?: string
}

interface SolThesisState {
  thesis_id: string
  created_at_utc?: string
  what_changed?: string
  core_narrative: string
  positioning_story: string
  oi_story: string
  flow_story: string
  option_response_story: string
  call_case: string
  put_case: string
  no_trade_case: string
  strongest_contradiction: string
  active_expectations?: Array<{
    expectation_id: string
    expected_condition: string
    invalidation_condition: string
  }>
  evaluation_history?: Array<{
    evaluation_id: string
    expectation_id: string
    result: string
    evaluation_notes: string
  }>
  data_gaps?: string[]
  evidence_references?: string[]
  state?: string
  entry_window?: string
  why_now?: string[]
  market_story?: string
  reversal_analysis?: string
  reversal_watch?: string
  reversal_watch_data?: Record<string, any>
  option_buyer_side?: string
  option_buyer_view?: string
  premium_confirmation?: string
  five_hypotheses?: Record<string, any>
  qwen_observation?: Record<string, any>
  gemini_review?: Record<string, any>
  latency_ms?: number
}

interface SolSnapshotState {
  snapshot_id: string
  spot_ltp: number | null
  futures_ltp: number | null
  futures_basis: number | null
  atm_iv: number | null
  skew_25d: number | null
  skew_10d: number | null
  expected_move_pts: number | null
  zero_gamma_level: number | null
  mlofi_5l?: number | null
  current_flow_x?: number | null
  availability_matrix?: Record<string, string>
  atm_strike?: number | null
  ce_pricing?: Record<string, any>
  pe_pricing?: Record<string, any>
}

export interface ExternalFactItem {
  fact_id: string
  title: string
  factual_summary: string
  status?: string
  event_time_utc?: string | null
  event_time_ist?: string | null
  observed_or_published_at?: string | null
  source_name?: string
  source_url?: string | null
  source_timestamp?: string | null
  relevance_note?: string | null
  upstream_verification_status?: string
  verification_status: string
  authoritative_source?: string | null
  authoritative_value?: string | null
  conflict_detail?: Record<string, unknown> | null
  validation_notes?: string | null
}

interface SolExternalContextState {
  status: string
  source_verification_status?: string
  external_context_id?: string
  market_session_date?: string
  last_received_ist?: string
  last_source_time_ist?: string
  total_items?: number
  verified_items_count?: number
  unverified_items_count?: number
  conflicted_items_count?: number
  verified_sources_count?: number
  data_gaps_count?: number
  provider?: string
  is_test_fixture?: boolean
  summary_titles?: string[]
  conflicted_items?: Array<{
    fact_id: string
    title: string
    spark_claim: string
    authoritative_source?: string | null
    authoritative_value?: string | null
    conflict_detail?: Record<string, unknown> | null
  }>
  scheduled_events?: ExternalFactItem[]
  breaking_events?: ExternalFactItem[]
  overnight_context?: ExternalFactItem[]
  index_specific_events?: ExternalFactItem[]
  global_context?: ExternalFactItem[]
  data_gaps?: string[]
  sources?: Array<{ source_name: string; reliability_tier?: string }>
  reading_status?: 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE'
  unavailable_reason?: string | null
  radar?: SolExternalRadarProjection
}

export interface SolExternalRadarFact {
  fact_id: string
  title?: string
  factual_summary?: string
  source_name: string
  verification_status: string
  time_classification?: string
  display_time_ist?: string | null
  instrument_label?: string | null
  instrument_kind?: string | null
  value?: string
}

interface SolExternalRadarProjection {
  status: string
  reading_status: 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE'
  reason: string
  session_date: string
  source_check: 'CONNECTED' | 'NOT_CONNECTED'
  last_scan_ist: string
  market_sections: Array<{
    key: string
    label: string
    items: SolExternalRadarFact[]
  }>
  today_news: SolExternalRadarFact[]
  timestamp_unknown_items: SolExternalRadarFact[]
  stale_items_count: number
  future_items_count: number
}

interface SolHealthStripState {
  data_stream: string
  brain_worker: string
  ai_provider: string
  reasoning_state: string
  model_name: string
  last_event_time: string
  last_analysis_time: string
  last_latency_ms: number | null
  pending_events_count: number
  successful_ai_calls: number
}

interface SolReadingDomainState {
  status: 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE'
  fields?: Record<string, string>
  option_quotes?: string
  closed_5m_oi?: string
  closed_15m_oi?: string
  total_oi?: string
  pcr_oi?: string
  sudden_oi?: string
}

export function canonicalReadingDomainStatus(
  domain: SolReadingDomainState | undefined,
): 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE' {
  return domain?.status || 'UNAVAILABLE'
}

export function getNewsCategoryTag(item: SolExternalRadarFact): string {
  const title = (item.title || '').toUpperCase()
  const summary = (item.factual_summary || '').toUpperCase()
  const text = `${title} ${summary}`
  
  const tagMatch = title.match(/^\[([A-Z\s/-]+)\]/)
  if (tagMatch) return tagMatch[1]

  if (/RBI|FED|INFLATION|CPI|GDP|YIELD|MOSPI|INTEREST RATE|POWELL|MONETARY/.test(text)) return 'MACRO'
  if (/BANK|HDFC|ICICI|SBI|KOTAK|AXIS|NBFC|FINANCIAL/.test(text)) return 'BANKING'
  if (/GEOPOLITICAL|WAR|MIDDLE EAST|SANCTION|TARIFF|HORMUZ|STRAIT|RED SEA|CONFLICT/.test(text)) return 'GEO'
  if (/CRUDE|OIL|OPEC|ENERGY|BRENT|WTI|GAS/.test(text)) return 'ENERGY'
  if (/INDIA|NIFTY|SENSEX|NSE|BSE|SEBI|GIFT|FII|DII/.test(text)) return 'INDIA'
  if (/INDEX|REBALANCING|MSCI|FTSE/.test(text)) return 'INDEX'
  return 'GLOBAL'
}

const OPERATIONAL_COPY: Record<string, string> = {
  OFF_MARKET: 'Market is closed. Live Gemini analysis is paused.',
  SYSTEM_OFF_MARKET: 'Market is closed. Live Gemini analysis is paused.',
  UNAVAILABLE: 'Live market data is not available.',
  TRANSPORT_UNAVAILABLE: 'The live data connection is down. Showing the last known view.',
  REASONING_UNAVAILABLE: 'Gemini analysis is temporarily unavailable.',
  PROVIDER_UNAVAILABLE: 'Gemini analysis is temporarily unavailable.',
  OUTPUT_INVALID: 'Gemini returned an unusable response. No current view is shown.',
  DATA_DEGRADED: 'Some market data is missing. Live analysis is paused.',
  DATA_LINEAGE_CONTAMINATION: 'Some market data cannot be fully trusted. Live analysis is paused.',
  SYSTEM_UNAVAILABLE: 'Live system data is not available.',
  ENGINE_INITIALIZING: 'Gemini Market Brain is starting.',
  FAIL_CLOSED_SYSTEM_STATUS: 'Live analysis is paused for safety.',
  DEGRADED_ADVISORY: 'Gemini analysis is temporarily unavailable.',
  QUOTA_EXHAUSTED: 'Gemini analysis is temporarily unavailable.',
  UNKNOWN_429: 'Gemini is temporarily busy. Analysis is unavailable.',
  TIMEOUT: 'Gemini did not respond in time. Analysis is unavailable.',
  PROVIDER_CAPACITY: 'Gemini is temporarily busy. Analysis is unavailable.',
}

const STATUS_LABELS: Record<string, string> = {
  OFF_MARKET: 'MARKET CLOSED',
  SYSTEM_OFF_MARKET: 'MARKET CLOSED',
  TRANSPORT_UNAVAILABLE: 'CONNECTION LOST',
  REASONING_UNAVAILABLE: 'ANALYSIS UNAVAILABLE',
  PROVIDER_UNAVAILABLE: 'ANALYSIS UNAVAILABLE',
  OUTPUT_INVALID: 'ANALYSIS UNAVAILABLE',
  DATA_DEGRADED: 'DATA LIMITED',
  DATA_LINEAGE_CONTAMINATION: 'DATA NOT VERIFIED',
  SYSTEM_UNAVAILABLE: 'UNAVAILABLE',
  ENGINE_INITIALIZING: 'STARTING',
  FAIL_CLOSED_SYSTEM_STATUS: 'SAFE MODE',
  DEGRADED_ADVISORY: 'LIMITED',
}

export function plainStatusLabel(value: string | null | undefined): string {
  if (!value) return 'UNAVAILABLE'
  const normalized = value.toUpperCase()
  return STATUS_LABELS[normalized] || normalized.replaceAll('_', ' ')
}

export function plainCanonicalText(value: string | null | undefined, fallback = 'Unavailable'): string {
  if (!value || value === 'None' || value === 'NONE_OBSERVED') return fallback
  const systemState = value.match(/^System State:\s*(\S+)$/i)
  if (systemState) return OPERATIONAL_COPY[systemState[1].toUpperCase()] || value
  const exactCopy: Record<string, string> = {
    'Feed disconnected or market session closed': 'Live market data is not active right now.',
    'Market thesis suspended': 'Live Gemini analysis is paused.',
    'System data availability state change.': 'Market data availability changed.',
    'Directional conviction is lacking.': 'Direction is still unclear.',
    'No coherent directional thesis.': 'Direction is still unclear.',
    OK: 'No new issue was reported.',
  }
  return (OPERATIONAL_COPY[value] || exactCopy[value] || value)
    .replace(
      /Spot breaks and sustains above Zero Gamma Level \(([+-]?\d+(?:\.\d+)?)\) with CE pricing IV expansion and positive mlofi acceleration above ([+-]?\d+(?:\.\d+)?)/gi,
      'Call side gets stronger if spot holds above Zero Gamma ($1) and call premiums rise. Order flow must stay above $2',
    )
    .replace(
      /Spot falls below ([+-]?\d+(?:\.\d+)?) ATM strike with basis compression below ([+-]?\d+(?:\.\d+)?)/gi,
      'This view weakens if spot falls below $1 and futures basis drops below $2',
    )
    .replace(/MLOFI order flow flipped polarity/gi, 'Order flow changed direction')
    .replace(/order flow flipped polarity/gi, 'Order flow changed direction')
    .replace(/Zero Gamma Level/gi, 'Zero Gamma')
    .replace(/CE pricing IV expansion/gi, 'call premiums and IV are rising')
    .replace(/PE pricing IV expansion/gi, 'put premiums and IV are rising')
    .replace(/\bmlofi\b/gi, 'Order flow')
    .replace(/basis compression/gi, 'futures basis weakening')
    .replace(/data lineage contamination/gi, 'some market data cannot be fully trusted')
    .replace(/fail.closed system status/gi, 'analysis paused for safety')
    .replace(/system off.market/gi, 'market closed')
    .replace(/degraded advisory/gi, 'limited analysis')
    .replace(/\bprovenance\b/gi, 'source')
    .replace(/\bcanonical\b/gi, 'confirmed')
    .replace(/\btransaction\b/gi, 'update')
    .replace(/\bpolarity\b/gi, 'direction')
    .replace(/\bthesis\b/gi, 'view')
    .replace(/\bregime\b/gi, 'market state')
}

export function compactDisplayBullets(value: string | null | undefined, maxItems = 4): string[] {
  if (!value || value === 'None') return []
  const parts = value
    .replace(/\r/g, '')
    .split(/\n+|\s*[•▪]\s*|;\s+/)
    .map(part => part.trim())
    .filter(Boolean)
  return (parts.length > 0 ? parts : [value]).slice(0, maxItems)
}

export function canonicalBiasLabel(marketState: LivingMarketState | null): 'CALL' | 'PUT' | 'WAIT' | 'UNAVAILABLE' {
  if (marketState === 'CALL' || marketState === 'CALL_DEVELOPING') return 'CALL'
  if (marketState === 'PUT' || marketState === 'PUT_DEVELOPING') return 'PUT'
  if (marketState === 'NO_TRADE') return 'WAIT'
  return 'UNAVAILABLE'
}

const PlainBulletList = memo(function PlainBulletList({
  text,
  fallback = 'Unavailable',
  tone = 'neutral',
  maxItems = 4,
}: {
  text?: string | null
  fallback?: string
  tone?: 'call' | 'put' | 'caution' | 'neutral'
  maxItems?: number
}) {
  const bullets = compactDisplayBullets(text, maxItems)
  if (bullets.length === 0) return <span className={styles.mutedCopy}>{fallback}</span>
  return (
    <ul className={`${styles.plainBulletList} ${styles[`plainBulletList_${tone}`]}`}>
      {bullets.map((bullet, index) => <li key={`${index}-${bullet}`}>{plainCanonicalText(bullet)}</li>)}
    </ul>
  )
})

interface SolThesisHistoryItem {
  thesis_id: string
  created_at_utc: string
  market_verdict: string | null
  developing_state: string
  what_changed: string
  core_narrative: string
  strongest_contradiction: string
  actually_invoked_model: string
}

interface SolStateResponse {
  service?: string
  vob_free_verified?: string
  canonical_market_state?: LivingMarketState | null
  state_revision?: number
  runtime_instance_id?: string
  beacon?: SolBeaconState
  thesis?: SolThesisState
  thesis_history?: SolThesisHistoryItem[]
  snapshot?: SolSnapshotState
  external_context?: SolExternalContextState
  health_strip?: SolHealthStripState
  reading_domains?: {
    futures?: SolReadingDomainState
    options_oi?: SolReadingDomainState
    flow?: SolReadingDomainState
    volatility?: SolReadingDomainState
    external?: SolReadingDomainState
  }
  worker?: {
    worker_name?: string
    alive?: boolean
    heartbeat_age_s?: number
    healthy?: boolean
  }
  model_configured?: boolean
  api_key_present?: boolean
  local_brain?: {
    mode: string
    shadow_status: string
    provider?: string
    governor_verdict?: string
    active_thesis?: {
      thesis_id: string
      state: string
      what_changed: string
      call_case: string
      put_case: string
      no_trade_case: string
      supporting_evidence_ids: string[]
      contradicting_evidence_ids: string[]
      watch_next: string[]
      model: string
      status: string
    } | null
    last_telemetry?: Record<string, unknown>
  }
  world_context?: {
    cockpit?: CockpitWorldContext['cockpit']
    quotes: Array<{
      symbol: string
      display_name: string
      exact_or_proxy: string
      price: number
      change: number
      change_percent: number
      market_status: string
      data_age: string
      provider_timestamp?: string
      notes?: string
      cluster?: string
      proxy_for?: string
      provider?: string
    }>
    events: Array<{
      event_id: string
      source_name: string
      provider?: string
      headline: string
      summary: string
      verification_tier: string
      published_at: string
    }>
    health?: Record<string, unknown>
    unavailable_context?: Array<{
      target: string
      cluster: string
      reason: string
      status: string
    }>
  }
  cognitive_models?: Record<string, any>
}

export const SOL_STATE_POLL_INTERVAL_MS = 3000
export const SOL_TRANSPORT_LOSS_GRACE_MS = SOL_STATE_POLL_INTERVAL_MS * 2
export const SOL_STATE_ENRICHMENT_INTERVAL_MS = 30000
export const SOL_COGNITIVE_POLL_INTERVAL_MS = 10000

export function dataStreamStatusFromBeacon(systemStatus: string | null | undefined): string {
  switch ((systemStatus || '').toUpperCase()) {
    case 'HEALTHY': return 'LIVE'
    case 'OFF_MARKET':
    case 'SYSTEM_OFF_MARKET': return 'OFF_MARKET'
    case 'DATA_DEGRADED': return 'DEGRADED'
    default: return 'UNAVAILABLE'
  }
}

export interface SolTransportHealth {
  pollAvailable: boolean
  sseAvailable: boolean
  lastCanonicalReceiptAtMs: number | null
  nowMs: number
}

export interface CanonicalRevisionCursor {
  activeRuntimeInstanceId: string | null
  retiredRuntimeInstanceIds: ReadonlySet<string>
  lastAppliedRevision: number
}

export function advanceCanonicalRevision(
  cursor: CanonicalRevisionCursor,
  runtimeInstanceId?: string,
  revision?: number,
): CanonicalRevisionCursor | null {
  if (!runtimeInstanceId || !Number.isFinite(revision)) return null
  if (cursor.retiredRuntimeInstanceIds.has(runtimeInstanceId)) return null
  if (cursor.activeRuntimeInstanceId === runtimeInstanceId) {
    if ((revision as number) < cursor.lastAppliedRevision) return null
    return { ...cursor, lastAppliedRevision: revision as number }
  }
  const retired = new Set(cursor.retiredRuntimeInstanceIds)
  if (cursor.activeRuntimeInstanceId) retired.add(cursor.activeRuntimeInstanceId)
  return {
    activeRuntimeInstanceId: runtimeInstanceId,
    retiredRuntimeInstanceIds: retired,
    lastAppliedRevision: revision as number,
  }
}

export function isCanonicalTransportUnavailable(health: SolTransportHealth): boolean {
  if (health.pollAvailable || health.sseAvailable) return false
  if (health.lastCanonicalReceiptAtMs === null) return true
  return health.nowMs - health.lastCanonicalReceiptAtMs >= SOL_TRANSPORT_LOSS_GRACE_MS
}

export interface CanonicalMarketPresentation {
  marketState: LivingMarketState | null
  operationalStatus: string
}

export function resolveCanonicalMarketPresentation(
  beacon: SolBeaconState | undefined,
  transportUnavailable: boolean,
  overrideState: LivingMarketState | null = null,
): CanonicalMarketPresentation {
  if (overrideState) {
    return { marketState: overrideState, operationalStatus: 'HEALTHY' }
  }
  if (transportUnavailable) {
    return { marketState: null, operationalStatus: 'TRANSPORT_UNAVAILABLE' }
  }
  if (!beacon) {
    return { marketState: null, operationalStatus: 'UNAVAILABLE' }
  }
  
  // Market state lives independently from reasoning completeness
  const liveState = overrideState || beacon.canonical_market_state || null;
  
  if (beacon.system_status !== 'HEALTHY') {
    return { marketState: liveState, operationalStatus: beacon.system_status || 'UNAVAILABLE' }
  }
  if (!beacon.market_verdict) {
    return {
      marketState: liveState,
      operationalStatus: (
        !beacon.reasoning_status || beacon.reasoning_status === 'ACTIVE_REASONING'
          ? 'REASONING_UNAVAILABLE'
          : beacon.reasoning_status
      ),
    }
  }
  
  if (liveState) {
    return { marketState: liveState, operationalStatus: 'HEALTHY' }
  }
  
  return { marketState: null, operationalStatus: 'OUTPUT_INVALID' }
}

export interface GeminiMarketBrainSectionProps {
  initialStateOverride?: LivingMarketState
  dataOverride?: SolStateResponse | null
  argusFeed?: DashboardFeedState<unknown>
  futuresFeed?: DashboardFeedState<unknown>
  optionBuyerFeed?: DashboardFeedState<unknown>
  orderFlowFeed?: DashboardFeedState<unknown>
  marketInfoFeed?: DashboardFeedState<unknown>
  sensorFeedMeta?: {
    argus?: DashboardFeedMeta
    futuresChart?: DashboardFeedMeta
    optionBuyerIntelligence?: DashboardFeedMeta
    orderFlow?: DashboardFeedMeta
    marketInfo?: DashboardFeedMeta
  }
  dashboardRevision?: number
}

const SENSOR_ORDER = [
  'nifty_spot',
  'nifty_futures',
  'futures_basis',
  'pcr_oi',
  'straddle',
  'straddle_change',
  'atm_iv',
  'skew_25d',
  'skew_10d',
  'net_gex',
  'zero_gamma',
  'call_put_wall',
  'total_oi',
  'delta_oi',
  'atm_ce_pe',
  'atm_ce_book',
  'atm_pe_book',
  'active_spread',
  'oi_buildup',
  'order_flow',
  'mlofi',
  'cvd',
  'net_delta',
  'book_pressure',
  'call_put_fit',
  'expected_move',
] as const

const DeterministicSensorCard = memo(function DeterministicSensorCard({
  reading,
}: {
  reading: DeterministicSensorReading
}) {
  const basisValue = reading.id === 'futures_basis' && typeof reading.value === 'number'
    ? reading.value
    : null
  const valueColor = reading.status === 'UNAVAILABLE' || reading.status === 'NOT_IMPLEMENTED'
    ? '#64748b'
    : basisValue !== null
      ? basisValue > 0 ? '#00f0ff' : basisValue < 0 ? '#ff2a55' : '#cbd5e1'
      : '#ffffff'
  const statusColor = reading.status === 'LIVE'
    ? '#00e676'
    : reading.status === 'SESSION_LAST' || reading.status === 'WARMING'
      ? '#fbbf24'
      : '#64748b'
  return (
    <div
      className={styles.domesticMetricCard}
      data-sensor-id={reading.id}
      data-sensor-source={reading.source ?? 'UNAVAILABLE'}
      data-sensor-path={reading.backendPath}
      data-sensor-session={reading.session ?? 'UNAVAILABLE'}
      data-sensor-wiring={reading.wiring}
    >
      <span className={styles.domesticMetricLabel}>{reading.label}</span>
      <span
        data-citadel-field={`sensor.${reading.id}`}
        data-citadel-value={reading.value ?? undefined}
        data-citadel-status={reading.status}
        data-citadel-revision={reading.revision ?? undefined}
        className={styles.domesticMetricVal}
        style={{ color: valueColor }}
      >
        {reading.display}
      </span>
      <span className={styles.domesticMetricMeta} style={{ color: statusColor }}>
        {formatSensorAsOf(reading)}
      </span>
    </div>
  )
})

export const GeminiMarketBrainSection = memo(function GeminiMarketBrainSection({
  initialStateOverride,
  dataOverride,
  argusFeed,
  futuresFeed,
  optionBuyerFeed,
  orderFlowFeed,
  marketInfoFeed,
  sensorFeedMeta,
  dashboardRevision,
}: GeminiMarketBrainSectionProps) {
  const [data, setData] = useState<SolStateResponse | null>(dataOverride ?? null)
  const [cognitiveLive, setCognitiveLive] = useState<any>(null)
  const [cognitiveAvailable, setCognitiveAvailable] = useState(false)
  const [showEvidence, setShowEvidence] = useState(false)
  const [showCases, setShowCases] = useState(true)
  const [showStories, setShowStories] = useState(true)
  const [transportHealth, setTransportHealth] = useState<SolTransportHealth>({
    pollAvailable: false,
    sseAvailable: false,
    lastCanonicalReceiptAtMs: null,
    nowMs: Date.now(),
  })
  const revisionCursorRef = useRef<CanonicalRevisionCursor>({
    activeRuntimeInstanceId: null,
    retiredRuntimeInstanceIds: new Set(),
    lastAppliedRevision: -1,
  })
  
  // State override isolated strictly to explicit dev/test props
  const [overrideState] = useState<LivingMarketState | null>(
    process.env.NODE_ENV !== 'production' && initialStateOverride ? initialStateOverride : null
  )

  // 1. Fetch live Sol state and subscribe to updates
  useEffect(() => {
    let isMounted = true
    let beaconInFlight = false
    let stateInFlight = false
    let cognitiveInFlight = false
    const activeControllers = new Set<AbortController>()

    const acceptCanonicalRevision = (runtimeInstanceId?: string, revision?: number): boolean => {
      const next = advanceCanonicalRevision(
        revisionCursorRef.current,
        runtimeInstanceId,
        revision,
      )
      if (!next) return false
      revisionCursorRef.current = next
      return true
    }

    const fetchBeacon = async () => {
      if (beaconInFlight) return
      beaconInFlight = true
      const controller = new AbortController()
      activeControllers.add(controller)
      const requestTimeout = setTimeout(() => controller.abort(), 15000)
      try {
        const res = await fetch('http://127.0.0.1:8000/v1/oracle/sol/beacon', {
          signal: controller.signal,
        })
        if (res.ok && isMounted) {
          const beacon: SolBeaconState = await res.json()
          const receiptAtMs = Date.now()
          if (acceptCanonicalRevision(beacon.runtime_instance_id, beacon.state_revision)) {
            setData(prev => ({
              ...(prev ?? {}),
              beacon,
              state_revision: beacon.state_revision,
              runtime_instance_id: beacon.runtime_instance_id,
            }))
            setTransportHealth(prev => ({
              ...prev,
              pollAvailable: true,
              lastCanonicalReceiptAtMs: receiptAtMs,
              nowMs: receiptAtMs,
            }))
          }
        } else if (isMounted) {
          setTransportHealth(prev => ({ ...prev, pollAvailable: false, nowMs: Date.now() }))
        }
      } catch {
        if (isMounted) {
          setTransportHealth(prev => ({ ...prev, pollAvailable: false, nowMs: Date.now() }))
        }
      } finally {
        clearTimeout(requestTimeout)
        activeControllers.delete(controller)
        beaconInFlight = false
      }
    }

    const fetchState = async () => {
      if (stateInFlight) return
      stateInFlight = true
      const controller = new AbortController()
      activeControllers.add(controller)
      const requestTimeout = setTimeout(() => controller.abort(), SOL_STATE_ENRICHMENT_INTERVAL_MS)
      try {
        const res = await fetch('http://127.0.0.1:8000/v1/oracle/sol/state', {
          signal: controller.signal,
        })
        if (res.ok && isMounted) {
          const json: SolStateResponse = await res.json()
          const revision = json.state_revision ?? json.beacon?.state_revision
          const runtimeInstanceId = json.runtime_instance_id ?? json.beacon?.runtime_instance_id
          if (acceptCanonicalRevision(runtimeInstanceId, revision)) setData(json)
        }
      } catch {
        // The compact beacon owns transport health; enrichment is best-effort.
      } finally {
        clearTimeout(requestTimeout)
        activeControllers.delete(controller)
        stateInFlight = false
      }
    }

    const fetchCognitiveDecision = async () => {
      if (cognitiveInFlight) return
      cognitiveInFlight = true
      const controller = new AbortController()
      activeControllers.add(controller)
      const requestTimeout = setTimeout(() => controller.abort(), 15000)
      try {
        const cogRes = await fetch('http://127.0.0.1:8000/v1/oracle/sol/cognitive-decision', {
          signal: controller.signal,
        })
        if (cogRes.ok && isMounted) {
          const cogJson = await cogRes.json()
          if (cogJson && cogJson.cognitive_live) {
            setCognitiveLive((previous: typeof cognitiveLive) => {
              const incoming = cogJson.cognitive_live
              const incomingTime = Date.parse(incoming.response_observed_at || '')
              const previousTime = Date.parse(previous?.response_observed_at || '')
              return Number.isFinite(previousTime) && (!Number.isFinite(incomingTime) || incomingTime < previousTime)
                ? previous : incoming
            })
            setCognitiveAvailable(true)
          } else {
            setCognitiveAvailable(false)
          }
        } else if (isMounted) {
          setCognitiveAvailable(false)
        }
      } catch {
        if (isMounted) setCognitiveAvailable(false)
      } finally {
        clearTimeout(requestTimeout)
        activeControllers.delete(controller)
        cognitiveInFlight = false
      }
    }

    fetchBeacon()
    fetchState()
    fetchCognitiveDecision()
    const beaconInterval = setInterval(fetchBeacon, SOL_STATE_POLL_INTERVAL_MS)
    const stateInterval = setInterval(fetchState, SOL_STATE_ENRICHMENT_INTERVAL_MS)
    const cognitiveInterval = setInterval(fetchCognitiveDecision, SOL_COGNITIVE_POLL_INTERVAL_MS)

    // Optional SSE stream listener
    let sse: EventSource | null = null
    try {
      sse = new EventSource('http://127.0.0.1:8000/v1/oracle/sol/stream')
      sse.onopen = () => {
        if (isMounted) {
          setTransportHealth(prev => ({ ...prev, sseAvailable: true, nowMs: Date.now() }))
        }
      }
      sse.onerror = () => {
        if (isMounted) {
          setTransportHealth(prev => ({ ...prev, sseAvailable: false, nowMs: Date.now() }))
        }
      }
      sse.addEventListener('beacon_state', (evt) => {
        try {
          const beacon: SolBeaconState = JSON.parse(evt.data)
          if (isMounted && acceptCanonicalRevision(beacon.runtime_instance_id, beacon.state_revision)) {
            const receiptAtMs = Date.now()
            setData(prev => prev ? { ...prev, beacon } : { beacon })
            setTransportHealth(prev => ({
              ...prev,
              sseAvailable: true,
              lastCanonicalReceiptAtMs: receiptAtMs,
              nowMs: receiptAtMs,
            }))
          }
        } catch {
          // Ignored
        }
      })
    } catch {
      // Ignored
    }

    return () => {
      isMounted = false
      clearInterval(beaconInterval)
      clearInterval(stateInterval)
      clearInterval(cognitiveInterval)
      activeControllers.forEach(controller => controller.abort())
      activeControllers.clear()
      sse?.close()
    }
  }, [])

  useEffect(() => {
    if (transportHealth.pollAvailable || transportHealth.sseAvailable) return
    if (transportHealth.lastCanonicalReceiptAtMs === null) return
    const elapsed = Date.now() - transportHealth.lastCanonicalReceiptAtMs
    const remaining = Math.max(0, SOL_TRANSPORT_LOSS_GRACE_MS - elapsed)
    const timer = window.setTimeout(() => {
      setTransportHealth(prev => ({ ...prev, nowMs: Date.now() }))
    }, remaining)
    return () => window.clearTimeout(timer)
  }, [
    transportHealth.pollAvailable,
    transportHealth.sseAvailable,
    transportHealth.lastCanonicalReceiptAtMs,
  ])

  // 2. Canonical Telemetry & State Decomposition
  const beacon = data?.beacon
  const thesis = data?.thesis
  const snapshot = data?.snapshot
  const extCtx = data?.external_context
  const health = data?.health_strip
  const history = data?.thesis_history || []
  const deterministicSensors = useMemo(
    () => selectOracleDeterministicSensors({
      argus: argusFeed?.data,
      futuresChart: futuresFeed?.data,
      optionBuyerIntelligence: optionBuyerFeed?.data,
      orderFlow: orderFlowFeed?.data,
      marketInfo: marketInfoFeed?.data,
      argusMeta: sensorFeedMeta?.argus,
      futuresMeta: sensorFeedMeta?.futuresChart,
      optionBuyerMeta: sensorFeedMeta?.optionBuyerIntelligence,
      orderFlowMeta: sensorFeedMeta?.orderFlow,
      marketInfoMeta: sensorFeedMeta?.marketInfo,
      revision: dashboardRevision,
    }),
    [
      argusFeed?.data,
      futuresFeed?.data,
      optionBuyerFeed?.data,
      orderFlowFeed?.data,
      marketInfoFeed?.data,
      sensorFeedMeta?.argus,
      sensorFeedMeta?.futuresChart,
      sensorFeedMeta?.optionBuyerIntelligence,
      sensorFeedMeta?.orderFlow,
      sensorFeedMeta?.marketInfo,
      dashboardRevision,
    ],
  )

  const transportUnavailable = isCanonicalTransportUnavailable(transportHealth)
  const queryOverride = typeof window !== 'undefined'
    ? (new URLSearchParams(window.location.search).get('marketState') as LivingMarketState) || null
    : null
  const presentation = resolveCanonicalMarketPresentation(
    beacon,
    queryOverride ? false : transportUnavailable,
    overrideState || queryOverride
  )
  const isSystemUnavailable = presentation.marketState === null
  const operationalStatus = presentation.operationalStatus
  const derivedState = presentation.marketState

  const dataStreamStatus = transportUnavailable
    ? 'UNAVAILABLE'
    : (health?.data_stream || dataStreamStatusFromBeacon(beacon?.system_status))
  const brainStatus = transportUnavailable ? 'UNAVAILABLE' : (health?.brain_worker || 'UNAVAILABLE')
  const reasoningState = transportUnavailable ? 'UNAVAILABLE' : (health?.reasoning_state || 'UNAVAILABLE')
  const modelName = health?.model_name || 'UNAVAILABLE'
  const providerStatus = transportUnavailable ? 'UNAVAILABLE' : (health?.ai_provider || 'UNAVAILABLE')

  // Stale thesis protection
  const isReasoningUnavailable = isSystemUnavailable || beacon?.reasoning_status === 'NOT_INVOKED' || beacon?.reasoning_status === 'DAILY_QUOTA_USED' || beacon?.reasoning_status === 'REASONING_UNAVAILABLE';
  const isThesisStale = Boolean(
    (isReasoningUnavailable || dataStreamStatus !== 'LIVE') &&
    thesis?.thesis_id
  )

  const activeExp = thesis?.active_expectations?.[0]

  // 3. Backend-owned evidence availability for "GEMINI IS READING" Strip
  const readingFutures = canonicalReadingDomainStatus(data?.reading_domains?.futures)
  const readingOptionsOi = canonicalReadingDomainStatus(data?.reading_domains?.options_oi)
  const readingFlow = canonicalReadingDomainStatus(data?.reading_domains?.flow)
  const readingVolatility = canonicalReadingDomainStatus(data?.reading_domains?.volatility)
  const readingExternal = canonicalReadingDomainStatus(data?.reading_domains?.external)
  const newEventsCount = health?.pending_events_count ?? (data?.thesis ? 0 : 0)

  // 4. Backend-owned External Radar and presentation-only plain-language summary
  const radar = extCtx?.radar
  const biasLabel = canonicalBiasLabel(derivedState)
  const strongestReason = beacon?.why_bullets?.find(item => !item.startsWith('System State:'))
    || beacon?.why_bullets?.[0]
    || thesis?.core_narrative
  const strongestRisk = beacon?.main_contradiction || thesis?.strongest_contradiction

  const currentReadSummary = isSystemUnavailable
    ? `Live analysis unavailable. ${plainCanonicalText(operationalStatus)}`
    : isThesisStale
      ? `Last known ${biasLabel} view · not current`
      : `${biasLabel} · ${plainCanonicalText(strongestReason, 'Analysis is available.')}`

  return (
    <section className={styles.container} aria-label="Gemini Live Market Brain & Living Market Forces">
      {/* 1. Hero Viewport: Living Market Forces (Directly below chart) */}
      <div className={styles.viewportWrapper}>
        <LivingMarketForcesViewport
          marketState={cognitiveLive?.retained_validation?.status === 'VALID' ? cognitiveLive?.primary_decision?.state || 'UNAVAILABLE' : 'UNAVAILABLE'}
          operationalStatus={
            cognitiveLive?.primary_decision?.state && cognitiveLive?.retained_validation?.status === 'VALID'
              ? (cognitiveLive?.market_status || 'HEALTHY')
              : operationalStatus
          }
          cognitiveState={cognitiveLive?.primary_decision?.state}
          isSessionLast={cognitiveLive?.market_status === 'SESSION_LAST' || Boolean(cognitiveLive?.primary_decision && cognitiveLive?.market_status === 'OFF_MARKET')}
          lastKnown={Boolean(isThesisStale && !cognitiveLive?.primary_decision?.state)}
          spotPrice={typeof deterministicSensors.readings.nifty_spot.value === 'number'
            ? deterministicSensors.readings.nifty_spot.value
            : snapshot?.spot_ltp}
          basis={typeof deterministicSensors.readings.futures_basis.value === 'number'
            ? deterministicSensors.readings.futures_basis.value
            : snapshot?.futures_basis}
        />
      </div>

      <div className={styles.cognitivePatch}>
        <CognitiveDecisionCore
          acceptedInputReceipt={cognitiveLive?.accepted_input_receipt}
          deterministicSensors={deterministicSensors}
          snapshot={snapshot}
          retainedValidation={cognitiveLive?.retained_validation}
          rejectedHistory={cognitiveLive?.historical_rejected_thesis}
          revision={cognitiveLive?.revision}
          marketStatus={cognitiveLive?.market_status || dataStreamStatus}
          marketDataUnavailable={deterministicSensors.status === 'UNAVAILABLE'}
          transportUnavailable={transportUnavailable || !cognitiveAvailable}
          state={cognitiveLive?.primary_decision?.state}
          entryWindow={cognitiveLive?.primary_decision?.entry_window}
          whyNow={cognitiveLive?.primary_decision?.why_now}
          reversalWatch={cognitiveLive?.primary_decision?.reversal_watch}
          optionBuyerSide={cognitiveLive?.primary_decision?.option_buyer_side}
          premiumConfirmation={cognitiveLive?.primary_decision?.premium_confirmation}
          modelTension={cognitiveLive?.primary_decision?.model_tension}
          agreementStatus={cognitiveLive?.primary_decision?.agreement_status}
          previousState={cognitiveLive?.primary_decision?.previous_state}
          setupFamily={cognitiveLive?.primary_decision?.setup_family}
          watchNext={cognitiveLive?.primary_decision?.watch_next}
          viewBreaksIf={cognitiveLive?.primary_decision?.view_breaks_if}
          missingConfirmation={cognitiveLive?.primary_decision?.missing_confirmation}
          thesisEvolution={cognitiveLive?.primary_decision?.thesis_evolution}
          opportunityMaturity={cognitiveLive?.primary_decision?.opportunity_maturity}
          worldContext={data?.world_context}
          callContract={snapshot?.atm_strike != null && snapshot?.ce_pricing?.security_id ? {
            strike: snapshot.atm_strike,
            securityId: snapshot.ce_pricing.security_id,
            ltp: snapshot.ce_pricing.ltp,
            spread: snapshot.ce_pricing.spread,
            iv: snapshot.ce_pricing.iv,
          } : undefined}
          putContract={snapshot?.atm_strike != null && snapshot?.pe_pricing?.security_id ? {
            strike: snapshot.atm_strike,
            securityId: snapshot.pe_pricing.security_id,
            ltp: snapshot.pe_pricing.ltp,
            spread: snapshot.pe_pricing.spread,
            iv: snapshot.pe_pricing.iv,
          } : undefined}
          fiveHypotheses={cognitiveLive?.five_hypotheses}
          qwenStatus={cognitiveLive?.qwen ? {
            ...cognitiveLive.qwen,
            updated_at: cognitiveLive.qwen.last_success,
            continuation_status: cognitiveLive.qwen.output?.continuation_status,
            earliest_contradiction: cognitiveLive.qwen.output?.earliest_contradiction?.summary,
            interpretation: cognitiveLive.qwen.output?.strongest_new_relationship || cognitiveLive.qwen.output?.what_changed,
            tokens: cognitiveLive.qwen.telemetry?.total_tokens,
            latency_ms: cognitiveLive.qwen.telemetry?.latency_ms,
          } : undefined}
          gptStatus={cognitiveLive?.gpt ? {
            ...cognitiveLive.gpt,
            updated_at: cognitiveLive.gpt.last_success,
            interpretation: cognitiveLive.gpt.output?.why_now?.[0] || cognitiveLive.gpt.output?.market_story,
            tokens: cognitiveLive.gpt.telemetry?.total_tokens,
            latency_ms: cognitiveLive.gpt.telemetry?.latency_ms,
          } : undefined}
          geminiStatus={cognitiveLive?.gemini ? {
            ...cognitiveLive.gemini,
            updated_at: cognitiveLive.gemini.last_success,
            interpretation: cognitiveLive.gemini.output?.interpretation,
            challenge: cognitiveLive.gemini.output?.strongest_disagreement || cognitiveLive.gemini.output?.relationship_primary_may_have_missed,
            reversal_risk: cognitiveLive.gemini.output?.reversal_risk,
          } : undefined}
          geminiScout={cognitiveLive?.gemini_scout}
          solSpecialist={cognitiveLive?.sol_option_specialist}
          unseenEventsCount={newEventsCount}
          whatChanged={cognitiveLive?.primary_decision?.what_changed}
          evidenceReferences={cognitiveLive?.gpt?.output?.supporting_evidence_ids || []}
        />
      </div>

      <div className={styles.srOnly} aria-hidden="true">
        <span>{currentReadSummary}</span>
        {SENSOR_ORDER.map((id) => {
          const reading = deterministicSensors.readings[id]
          return reading ? <DeterministicSensorCard key={id} reading={reading} /> : null
        })}
      </div>
    </section>
  )
})
