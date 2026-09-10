'use client'

import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties } from 'react'
import {
  BaselineSeries,
  CandlestickSeries,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { feedSelectors, useDashboardSelector } from '@/dashboard'
import type { DashboardFeedState } from '@/dashboard/types'
import { LiquidGlassRail, type RailAccent } from './OracleArgusPrime01C'
import {
  BubblesPrimitive,
  HeatmapPrimitive,
  type DepthSnapshot,
  type VisualFlowEvent,
} from './FlowMapPrimitives'

import styles from './OracleFuturesVwapChart.module.css'

type JsonRecord = Record<string, unknown>

export interface OracleFuturesCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
  vwap?: number
}

interface SessionProfileBin {
  price: number
  relativeVolume: number
  isPoc: boolean
}

interface SessionProfile {
  status: 'AVAILABLE' | 'PROFILE_DEGRADED'
  reason: string | null
  poc: number | null
  vah: number | null
  val: number | null
  bins: SessionProfileBin[]
}

interface FuturesForecast {
  identity: string
  revision: number
  mode: string
  sourceTimestamp: string
  status: string
  kronosSourceTimestamp: string | null
  chronosSourceTimestamp: string | null
  ghost: OracleFuturesCandle[]
  p10: Array<{ time: number; value: number }>
  p50: Array<{ time: number; value: number }>
  p90: Array<{ time: number; value: number }>
  tirexState: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
  tirexStatus: string
}

type HudHeroState = 'SELLING_STRONG' | 'SELLING_EXHAUSTED' | 'REVERSAL_BUILDING' | 'BUYING_BUILDING' | 'BUYING_STRONG' | 'NO_EDGE' | 'DATA_LOCKED'

interface DecisionHudSide {
  contract: string
  flowState: string
  flowStrength: number
  oiState: string
  oiStrength: number
  controlState: string
  explanation: string
  action: 'WAIT' | 'READY' | 'READY+' | 'GO'
  heroState: HudHeroState
}

interface DecisionHudProjection {
  revision: number
  rawRevision: number
  displayRevision: number
  focusStrike: number | null
  sourceTimestamp: string | null
  dataQuality: string
  relationshipState: string
  controlEventId: string | null
  call: DecisionHudSide
  put: DecisionHudSide
}

type DecisionHudSideSemantic = Omit<DecisionHudSide, 'flowStrength' | 'oiStrength'>

interface DecisionHudSemanticProjection {
  displayRevision: number
  dataQuality: string
  call: DecisionHudSideSemantic
  put: DecisionHudSideSemantic
}

const IST_OFFSET_SECONDS = 5 * 60 * 60 + 30 * 60
const SESSION_OPEN_MINUTE = 9 * 60 + 15
const SESSION_CLOSE_MINUTE = 15 * 60 + 30
const TIMEFRAMES = ['1m', '3m', '5m', '15m'] as const
type ChartTimeframe = typeof TIMEFRAMES[number]

const record = (value: unknown): JsonRecord =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonRecord
    : {}

const number = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const oiDisplayState = (source: JsonRecord): string => {
  if (source.oi_state === 'DATA LOCKED') return 'DATA LOCKED'
  const probableFlow = String(record(source.oi_evidence).probable_flow ?? '').toUpperCase()
  if (probableFlow.endsWith('_SHORT_COVERING')) return 'SHORT COVERING'
  if (probableFlow.endsWith('_LONG_UNWINDING')) return 'LONG UNWINDING'
  if (probableFlow.endsWith('_WRITING')) return 'SHORT BUILDUP'
  if (probableFlow.endsWith('_BUYING')) return 'LONG BUILDUP'
  if (/STALE|UNAVAILABLE|INCONSISTENT/.test(probableFlow)) return probableFlow.replaceAll('_', ' ')
  if (probableFlow) return 'MIXED'
  return typeof source.oi_display_state === 'string'
    ? source.oi_display_state
    : typeof source.oi_state === 'string'
      ? source.oi_state
      : typeof source.display_structure_state === 'string'
        ? source.display_structure_state
        : typeof source.structure_state === 'string' ? source.structure_state : 'DATA LOCKED'
}

const hudSide = (value: unknown, suffix: 'CE' | 'PE'): DecisionHudSide => {
  const source = record(value)
  const action = source.action === 'GO' || source.action === 'READY+' || source.action === 'READY' ? source.action : 'WAIT'
  const allowedHero: HudHeroState[] = ['SELLING_STRONG', 'SELLING_EXHAUSTED', 'REVERSAL_BUILDING', 'BUYING_BUILDING', 'BUYING_STRONG', 'NO_EDGE', 'DATA_LOCKED']
  const heroState = allowedHero.includes(source.hero_state as HudHeroState) ? source.hero_state as HudHeroState : 'DATA_LOCKED'
  return {
    contract: typeof source.contract === 'string' ? source.contract : `— ${suffix}`,
    flowState: typeof source.flow_state === 'string'
      ? source.flow_state
      : typeof source.display_edge_state === 'string'
      ? source.display_edge_state
      : typeof source.edge_state === 'string' ? source.edge_state : 'DATA LOCKED',
    flowStrength: Math.max(0, Math.min(100, number(source.flow_strength) ?? number(source.edge_strength) ?? 0)),
    oiState: oiDisplayState(source),
    oiStrength: Math.max(0, Math.min(100, number(source.oi_strength) ?? number(source.structure_strength) ?? 0)),
    controlState: typeof source.control_state === 'string' ? source.control_state : 'BALANCED',
    explanation: typeof source.explanation === 'string' ? source.explanation : 'Canonical Flow and OI evidence unavailable.',
    action,
    heroState,
  }
}

export const normalizeDecisionHud = (value: unknown): DecisionHudProjection => {
  const source = record(value)
  const revision = number(source.revision) ?? 0
  return {
    revision,
    rawRevision: number(source.raw_revision) ?? revision,
    displayRevision: number(source.display_revision) ?? revision,
    focusStrike: number(source.focus_strike),
    sourceTimestamp: typeof source.source_timestamp === 'string' ? source.source_timestamp : null,
    dataQuality: typeof source.data_quality === 'string' ? source.data_quality : 'LOCKED',
    relationshipState: typeof source.relationship_state === 'string' ? source.relationship_state : 'DATA LOCKED',
    controlEventId: typeof source.control_event_id === 'string' ? source.control_event_id : null,
    call: hudSide(source.call, 'CE'),
    put: hudSide(source.put, 'PE'),
  }
}

const railAccent = (side: Pick<DecisionHudSide, 'flowState' | 'oiState'>, rail: 'flow' | 'oi'): RailAccent => {
  const state = rail === 'flow' ? side.flowState : side.oiState
  if (/BUYING|BUY STRONG|BUY BUILDING/.test(state)) return 'green'
  if (/LONG BUILDUP|SHORT COVERING/.test(state)) return 'green'
  if (/REVERSAL|TURNING/.test(state)) return 'amber'
  if (/SELLING|SELL STRONG/.test(state)) return 'red'
  if (/SHORT BUILDUP|LONG UNWINDING/.test(state)) return 'red'
  if (/MIXED|CONFLICT|INCONSISTENT/.test(state)) return 'amber'
  if (/FADING/.test(state)) return 'amber'
  return 'slate'
}

const DecisionHeader = memo(function DecisionHeader({ value }: { value: DecisionHudSideSemantic }) {
  return <div className={styles.heroLine}>
    <strong>{value.contract}</strong>
    <em>{value.controlState}</em>
  </div>
})

const DecisionRailLabel = memo(function DecisionRailLabel({ label, state }: { label: 'FLOW' | 'OI'; state: string }) {
  return <div><span>{label}</span><b>{state}</b></div>
})

function DecisionSide({ label, semantic, flowStrength, oiStrength }: {
  label: 'CE' | 'PE'
  semantic: DecisionHudSideSemantic
  flowStrength: number
  oiStrength: number
}) {
  const railState = semantic.heroState === 'DATA_LOCKED' ? 'UNAVAILABLE' : 'LIVE'
  return (
    <article className={styles.decisionSide} data-side={label.toLowerCase()} data-hero-state={semantic.heroState} data-control-state={semantic.controlState} title={semantic.explanation}>
      <span className={styles.decisionLabel}>FOCUS {label}</span>
      <DecisionHeader value={semantic} />
      <div className={styles.decisionRail}>
        <DecisionRailLabel label="FLOW" state={semantic.flowState} />
        <LiquidGlassRail position={flowStrength} state={railState} accent={railAccent(semantic, 'flow')} animationMode="frozen" ariaLabel={`${label} FLOW ${semantic.flowState}`} />
      </div>
      <div className={styles.decisionRail}>
        <DecisionRailLabel label="OI" state={semantic.oiState} />
        <LiquidGlassRail position={oiStrength} state={railState} accent={railAccent(semantic, 'oi')} animationMode="frozen" ariaLabel={`${label} OI ${semantic.oiState}`} />
      </div>
      <p className={styles.controlExplanation}>{semantic.explanation}</p>
    </article>
  )
}

const epochSeconds = (value: number): number => Math.trunc(value > 100_000_000_000 ? value / 1000 : value)

export const isRegularNseSessionTimestamp = (timestamp: number): boolean => {
  const date = new Date((timestamp + IST_OFFSET_SECONDS) * 1000)
  const weekday = date.getUTCDay()
  const minute = date.getUTCHours() * 60 + date.getUTCMinutes()
  return weekday >= 1 && weekday <= 5 && minute >= SESSION_OPEN_MINUTE && minute < SESSION_CLOSE_MINUTE
}

export const normalizeOracleFuturesCandles = (value: unknown): OracleFuturesCandle[] => {
  const rows = Array.isArray(record(value).candles) ? record(value).candles as unknown[] : []
  const deduplicated = new Map<number, OracleFuturesCandle>()
  for (const row of rows) {
    const item = record(row)
    const rawTime = number(item.time)
    const open = number(item.open)
    const high = number(item.high)
    const low = number(item.low)
    const close = number(item.close)
    const vwap = number(item.vwap)
    if (rawTime === null || open === null || high === null || low === null || close === null) continue
    const time = epochSeconds(rawTime)
    if (!isRegularNseSessionTimestamp(time)) continue
    if (high < Math.max(open, close) || low > Math.min(open, close) || low > high) continue
    deduplicated.set(time, { time, open, high, low, close, ...(vwap === null ? {} : { vwap }) })
  }
  return [...deduplicated.values()].sort((left, right) => left.time - right.time)
}

const formatIst = (timestamp: number, includeDate = false): string => new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata',
  ...(includeDate ? { day: '2-digit', month: 'short' } : {}),
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
}).format(new Date(timestamp * 1000))

const candleBar = (candle: OracleFuturesCandle) => ({
  time: candle.time as UTCTimestamp,
  open: candle.open,
  high: candle.high,
  low: candle.low,
  close: candle.close,
})

const vwapBar = (candle: OracleFuturesCandle) => candle.vwap === undefined
  ? null
  : { time: candle.time as UTCTimestamp, value: candle.vwap }

const normalizeSessionProfile = (value: unknown): SessionProfile => {
  const source = record(value)
  const bins = (Array.isArray(source.bins) ? source.bins : []).flatMap((item) => {
    const row = record(item)
    const price = number(row.price)
    const relativeVolume = number(row.relative_volume)
    if (price === null || relativeVolume === null || relativeVolume < 0 || relativeVolume > 1) return []
    return [{ price, relativeVolume, isPoc: row.is_poc === true }]
  })
  const available = source.status === 'AVAILABLE' && bins.length > 0
  return {
    status: available ? 'AVAILABLE' : 'PROFILE_DEGRADED',
    reason: typeof source.reason === 'string' ? source.reason : null,
    poc: available ? number(source.poc) : null,
    vah: available ? number(source.vah) : null,
    val: available ? number(source.val) : null,
    bins,
  }
}

export const normalizeFuturesForecast = (
  value: unknown,
  expected: { contract: string; securityId: string; expiry: string; timeframe: string },
): FuturesForecast | null => {
  const source = record(value)
  const instrument = record(source.instrument)
  const revision = number(source.forecast_revision)
  const sourceTimestamp = typeof source.source_bar_timestamp === 'string' ? source.source_bar_timestamp : null
  const timeframe = typeof source.timeframe === 'string' ? source.timeframe : ''
  const actual = [instrument.contract, instrument.security_id, instrument.expiry, timeframe].map(String).join('|')
  const identity = [expected.contract, expected.securityId, expected.expiry, expected.timeframe].join('|')
  if (revision === null || sourceTimestamp === null || actual !== identity || expected.timeframe !== '5m') return null
  const sourceEpoch = Math.trunc(new Date(sourceTimestamp).getTime() / 1000)
  if (!Number.isFinite(sourceEpoch)) return null

  const kronos = record(source.kronos)
  const chronos = record(source.chronos)
  const tirex = record(source.tirex)
  const ghost = (kronos.status === 'READY' && Array.isArray(kronos.ghost_ohlc) ? kronos.ghost_ohlc : []).flatMap((raw) => {
    const row = record(raw)
    const time = typeof row.timestamp === 'string' ? Math.trunc(new Date(row.timestamp).getTime() / 1000) : NaN
    const open = number(row.open); const high = number(row.high); const low = number(row.low); const close = number(row.close)
    if (!Number.isFinite(time) || time <= sourceEpoch || !isRegularNseSessionTimestamp(time)
        || open === null || high === null || low === null || close === null
        || high < Math.max(open, close) || low > Math.min(open, close)) return []
    return [{ time, open, high, low, close }]
  })
  const rows = chronos.status === 'READY' && Array.isArray(chronos.forecast_rows) ? chronos.forecast_rows : []
  const quantiles = rows.flatMap((raw) => {
    const row = record(raw)
    const time = typeof row.timestamp === 'string' ? Math.trunc(new Date(row.timestamp).getTime() / 1000) : NaN
    const p10 = number(row.p10); const p50 = number(row.p50); const p90 = number(row.p90)
    if (!Number.isFinite(time) || time <= sourceEpoch || !isRegularNseSessionTimestamp(time)
        || p10 === null || p50 === null || p90 === null || p10 > p50 || p50 > p90) return []
    return [{ time, p10, p50, p90 }]
  })
  const tirexState = tirex.state === 'BULLISH' || tirex.state === 'BEARISH' ? tirex.state : 'NEUTRAL'
  return {
    identity,
    revision,
    mode: typeof source.mode === 'string' ? source.mode : 'UNAVAILABLE',
    sourceTimestamp,
    status: typeof source.status === 'string' ? source.status : 'UNAVAILABLE',
    kronosSourceTimestamp: typeof kronos.source_bar_timestamp === 'string' ? kronos.source_bar_timestamp : null,
    chronosSourceTimestamp: typeof chronos.source_bar_timestamp === 'string' ? chronos.source_bar_timestamp : null,
    ghost: ghost.sort((left, right) => left.time - right.time),
    p10: quantiles.map((row) => ({ time: row.time, value: row.p10 })),
    p50: quantiles.map((row) => ({ time: row.time, value: row.p50 })),
    p90: quantiles.map((row) => ({ time: row.time, value: row.p90 })),
    tirexState,
    tirexStatus: typeof tirex.status === 'string' ? tirex.status : 'UNAVAILABLE',
  }
}

export const shouldAcceptForecast = (previous: FuturesForecast | null, next: FuturesForecast): boolean =>
  previous === null || next.identity !== previous.identity
    || (next.revision >= previous.revision && new Date(next.sourceTimestamp).getTime() >= new Date(previous.sourceTimestamp).getTime())

const subscribeStaticLocation = () => () => undefined

export const OracleFuturesVwapChart = memo(function OracleFuturesVwapChart({ feed }: {
  feed: DashboardFeedState<unknown>
}) {
  const [selectedTimeframe, setSelectedTimeframe] = useState<ChartTimeframe>('5m')
  const [flowMapActive, setFlowMapActive] = useState<boolean>(false)
  const visualLiveFixture = useSyncExternalStore(
    subscribeStaticLocation,
    () => process.env.NODE_ENV !== 'production'
      && new URLSearchParams(window.location.search).get('chartLiveFixture') === 'true',
    () => false,
  )
  const hudAuditCollector = useSyncExternalStore(
    subscribeStaticLocation,
    () => new URLSearchParams(window.location.search).get('hudAuditCollector') === 'true',
    () => false,
  )
  const hudAuditCollectorPort = useSyncExternalStore(
    subscribeStaticLocation,
    () => new URLSearchParams(window.location.search).get('hudAuditCollectorPort') || '8110',
    () => '8110',
  )
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const vwapSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const ghostSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const p10SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const p50SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const p90SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const cvdSeriesRef = useRef<ISeriesApi<'Baseline'> | null>(null)
  const bubblesPrimitiveRef = useRef<BubblesPrimitive | null>(null)
  const heatmapPrimitiveRef = useRef<HeatmapPrimitive | null>(null)
  const profilePriceLinesRef = useRef<IPriceLine[]>([])
  const overlayRef = useRef<HTMLDivElement>(null)
  const liveDotRef = useRef<HTMLSpanElement>(null)
  const livePriceRef = useRef<HTMLSpanElement>(null)
  const nowDividerRef = useRef<HTMLSpanElement>(null)
  const currentPriceRef = useRef<number | null>(null)
  const syncOverlayRef = useRef<() => void>(() => undefined)
  const initializedIdentityRef = useRef<string | null>(null)
  const lastCandleRef = useRef<OracleFuturesCandle | null>(null)
  const lastForecastRef = useRef<FuturesForecast | null>(null)
  const forecastFitIdentityRef = useRef<string | null>(null)
  const prevFlowMapActiveRef = useRef<boolean>(false)
  const lastCvdLengthRef = useRef<number>(0)
  const lastCvdPointRef = useRef<{ time: UTCTimestamp; value: number } | null>(null)
  const orderFlowFeed = useDashboardSelector(feedSelectors.orderFlow) as DashboardFeedState<unknown>
  const rootData = useMemo(() => record(feed.data), [feed.data])
  const data = useMemo(() => {
    const root = rootData
    const selected = record(record(root.timeframes)[selectedTimeframe])
    return Object.keys(selected).length > 0
      ? selected
      : root.timeframe === selectedTimeframe
        ? root
        : {}
  }, [rootData, selectedTimeframe])
  const decisionHud = useMemo(() => normalizeDecisionHud(rootData.decision_hud), [rootData.decision_hud])
  const decisionHudSemantic = useMemo<DecisionHudSemanticProjection>(() => ({
    displayRevision: decisionHud.displayRevision,
    dataQuality: decisionHud.dataQuality,
    call: {
      contract: decisionHud.call.contract,
      flowState: decisionHud.call.flowState,
      oiState: decisionHud.call.oiState,
      controlState: decisionHud.call.controlState,
      explanation: decisionHud.call.explanation,
      action: decisionHud.call.action,
      heroState: decisionHud.call.heroState,
    },
    put: {
      contract: decisionHud.put.contract,
      flowState: decisionHud.put.flowState,
      oiState: decisionHud.put.oiState,
      controlState: decisionHud.put.controlState,
      explanation: decisionHud.put.explanation,
      action: decisionHud.put.action,
      heroState: decisionHud.put.heroState,
    },
  }), [
    decisionHud.call.action, decisionHud.call.contract, decisionHud.call.controlState,
    decisionHud.call.explanation, decisionHud.call.flowState, decisionHud.call.heroState,
    decisionHud.call.oiState,
    decisionHud.dataQuality, decisionHud.displayRevision,
    decisionHud.put.action, decisionHud.put.contract, decisionHud.put.controlState,
    decisionHud.put.explanation, decisionHud.put.flowState, decisionHud.put.heroState,
    decisionHud.put.oiState,
  ])
  const frontendTransport = record(rootData.frontend_transport)
  useLayoutEffect(() => {
    if (!hudAuditCollector || decisionHudSemantic.displayRevision <= 0) return
    const payload = {
      commit_epoch_ms: Date.now(),
      browser_receive_epoch_ms: number(frontendTransport.browser_receive_epoch_ms),
      published_at: typeof frontendTransport.published_at === 'string' ? frontendTransport.published_at : null,
      raw_revision: decisionHud.rawRevision,
      display_revision: decisionHudSemantic.displayRevision,
      focus_strike: decisionHud.focusStrike,
      source_timestamp: decisionHud.sourceTimestamp,
      data_quality: decisionHud.dataQuality,
      call: {
        contract: decisionHudSemantic.call.contract,
        flow: decisionHudSemantic.call.flowState,
        flow_color: railAccent(decisionHudSemantic.call, 'flow'),
        oi: decisionHudSemantic.call.oiState,
        oi_color: railAccent(decisionHudSemantic.call, 'oi'),
      },
      put: {
        contract: decisionHudSemantic.put.contract,
        flow: decisionHudSemantic.put.flowState,
        flow_color: railAccent(decisionHudSemantic.put, 'flow'),
        oi: decisionHudSemantic.put.oiState,
        oi_color: railAccent(decisionHudSemantic.put, 'oi'),
      },
      relationship_state: decisionHud.relationshipState,
      control_event_id: decisionHud.controlEventId,
    }
    void fetch(`http://127.0.0.1:${hudAuditCollectorPort}/dom-transition`, {
      method: 'POST', body: JSON.stringify(payload), keepalive: true,
    }).catch(() => { /* collector is deliberately optional outside certification */ })
    window.dispatchEvent(new CustomEvent('citadel:oracle-dom-commit', { detail: {
      surface: 'CE_PE_HUD', raw_revision: decisionHud.rawRevision,
      display_revision: decisionHudSemantic.displayRevision,
      data_quality: decisionHud.dataQuality, focus_strike: decisionHud.focusStrike,
      call_flow: decisionHudSemantic.call.flowState,
      call_oi: decisionHudSemantic.call.oiState,
      put_flow: decisionHudSemantic.put.flowState,
      put_oi: decisionHudSemantic.put.oiState,
      relationship_state: decisionHud.relationshipState,
      control_event_id: decisionHud.controlEventId,
      source_timestamp: decisionHud.sourceTimestamp, dom_commit_epoch_ms: Date.now(),
    } }))
  }, [
    decisionHud.controlEventId, decisionHud.dataQuality, decisionHud.focusStrike, decisionHud.rawRevision,
    decisionHud.relationshipState,
    decisionHud.sourceTimestamp, decisionHudSemantic.call, decisionHudSemantic.displayRevision,
    decisionHudSemantic.put, frontendTransport.browser_receive_epoch_ms,
    frontendTransport.published_at, hudAuditCollector, hudAuditCollectorPort,
  ])
  const candles = useMemo(() => normalizeOracleFuturesCandles(data), [data])
  const profile = useMemo(() => normalizeSessionProfile(data.session_profile), [data])
  const sourceTimestamp = typeof data.source_timestamp === 'string' ? data.source_timestamp : null
  const contract = typeof data.contract === 'string' && data.contract ? data.contract : 'NIFTY FUTURES'
  const freshness = typeof data.freshness === 'string' ? data.freshness : 'UNAVAILABLE'
  const age = number(data.age_seconds)
  const currentPrice = number(data.current_price) ?? candles.at(-1)?.close ?? null
  const isFresh = freshness === 'FRESH' || visualLiveFixture
  const seriesIdentity = [data.security_id, data.expiry, selectedTimeframe].map(String).join('|')
  const forecast = useMemo(() => normalizeFuturesForecast(data.forecast, {
    contract,
    securityId: String(data.security_id ?? ''),
    expiry: String(data.expiry ?? ''),
    timeframe: selectedTimeframe,
  }), [contract, data.expiry, data.forecast, data.security_id, selectedTimeframe])
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight || 348,
      layout: {
        background: { color: '#030508' },
        textColor: '#8f8589',
        fontFamily: 'var(--font-oracle-data, "JetBrains Mono", monospace)',
        fontSize: 10,
      },
      localization: { timeFormatter: (time: Time) => typeof time === 'number' ? formatIst(time, true) : '' },
      grid: {
        vertLines: { color: 'rgba(255,255,255,.025)' },
        horzLines: { color: 'rgba(255,255,255,.035)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: 'rgba(47,240,216,.28)', style: LineStyle.Dashed, width: 1 },
        horzLine: { color: 'rgba(255,255,255,.18)', style: LineStyle.Dashed, width: 1 },
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,.08)', scaleMargins: { top: .08, bottom: .08 } },
      timeScale: {
        borderColor: 'rgba(255,255,255,.08)',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 9,
        barSpacing: 8.5,
        tickMarkFormatter: (time: Time) => typeof time === 'number' ? formatIst(time) : '',
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: { mouseWheel: true, pinch: true },
    })
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#1f7a4d',
      downColor: '#ff3b54',
      borderUpColor: '#1f7a4d',
      borderDownColor: '#ff3b54',
      wickUpColor: '#1f7a4d',
      wickDownColor: '#ff3b54',
    })
    const vwapSeries = chart.addSeries(LineSeries, {
      color: '#ffc93c',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      title: '',
    })
    const ghostSeries = chart.addSeries(CandlestickSeries, {
      upColor: 'rgba(31,122,77,.34)', downColor: 'rgba(255,59,84,.32)',
      borderUpColor: 'rgba(49,152,100,.72)', borderDownColor: 'rgba(255,92,108,.7)',
      wickUpColor: 'rgba(49,152,100,.55)', wickDownColor: 'rgba(255,92,108,.55)',
      priceLineVisible: false, lastValueVisible: false, title: '',
    })
    const p10Series = chart.addSeries(LineSeries, {
      color: 'rgba(255,201,60,.48)', lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false, title: '',
    })
    const p50Series = chart.addSeries(LineSeries, {
      color: '#d9a3ff', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, title: '',
    })
    const p90Series = chart.addSeries(LineSeries, {
      color: 'rgba(47,240,216,.5)', lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false, title: '',
    })
    const bubblesPrimitive = new BubblesPrimitive({ showBubbles: flowMapActive })
    const heatmapPrimitive = new HeatmapPrimitive({ showHeatmap: flowMapActive })
    candleSeries.attachPrimitive(heatmapPrimitive)
    candleSeries.attachPrimitive(bubblesPrimitive)
    bubblesPrimitiveRef.current = bubblesPrimitive
    heatmapPrimitiveRef.current = heatmapPrimitive

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    vwapSeriesRef.current = vwapSeries
    ghostSeriesRef.current = ghostSeries
    p10SeriesRef.current = p10Series
    p50SeriesRef.current = p50Series
    p90SeriesRef.current = p90Series
    const syncOverlay = () => requestAnimationFrame(() => {
      const series = candleSeriesRef.current
      const overlay = overlayRef.current
      if (!series || !overlay) return
      overlay.querySelectorAll<HTMLElement>('[data-profile-price]').forEach((bar) => {
        const price = Number(bar.dataset.profilePrice)
        const coordinate = series.priceToCoordinate(price)
        bar.style.top = coordinate === null ? '-100px' : `${coordinate}px`
      })
      const last = lastCandleRef.current
      const dot = liveDotRef.current
      const price = currentPriceRef.current
      const pricePill = livePriceRef.current
      if (last && dot && typeof price === 'number') {
        const x = chart.timeScale().timeToCoordinate(last.time as UTCTimestamp)
        const y = series.priceToCoordinate(price)
        dot.style.opacity = x === null || y === null ? '0' : '1'
        if (x !== null) dot.style.left = `${x}px`
        if (y !== null) dot.style.top = `${y}px`
        if (pricePill) {
          pricePill.style.opacity = y === null ? '0' : '1'
          if (y !== null) pricePill.style.top = `${y}px`
        }
      }
      const divider = nowDividerRef.current
      const activeForecast = lastForecastRef.current
      if (divider && activeForecast?.ghost.length) {
        const x = chart.timeScale().timeToCoordinate(activeForecast.ghost[0].time as UTCTimestamp)
        divider.style.opacity = x === null ? '0' : '1'
        if (x !== null) divider.style.left = `${x}px`
      } else if (divider) divider.style.opacity = '0'
      if (bubblesPrimitiveRef.current) bubblesPrimitiveRef.current.requestUpdate()
      if (heatmapPrimitiveRef.current) heatmapPrimitiveRef.current.requestUpdate()
    })
    syncOverlayRef.current = syncOverlay
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncOverlay)
    const observer = new ResizeObserver(([entry]) => {
      if (entry?.contentRect.width) {
        chart.applyOptions({ width: entry.contentRect.width, height: entry.contentRect.height })
        syncOverlay()
      }
    })
    observer.observe(container)
    return () => {
      observer.disconnect()
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(syncOverlay)
      chart.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      vwapSeriesRef.current = null
      ghostSeriesRef.current = null
      p10SeriesRef.current = null
      p50SeriesRef.current = null
      p90SeriesRef.current = null
      cvdSeriesRef.current = null
      lastCvdLengthRef.current = 0
      lastCvdPointRef.current = null
      bubblesPrimitiveRef.current = null
      heatmapPrimitiveRef.current = null
      initializedIdentityRef.current = null
      lastCandleRef.current = null
      lastForecastRef.current = null
      forecastFitIdentityRef.current = null
      profilePriceLinesRef.current = []
      syncOverlayRef.current = () => undefined
    }
  }, [])

  const orderFlowData = useMemo(() => record(orderFlowFeed?.data), [orderFlowFeed?.data])
  const visualEvents = useMemo<VisualFlowEvent[]>(() => {
    return Array.isArray(orderFlowData.visual_events)
      ? (orderFlowData.visual_events as VisualFlowEvent[])
      : []
  }, [orderFlowData.visual_events])
  const depthSnapshots = useMemo<DepthSnapshot[]>(() => {
    return Array.isArray(orderFlowData.depth_snapshots)
      ? (orderFlowData.depth_snapshots as DepthSnapshot[])
      : []
  }, [orderFlowData.depth_snapshots])
  const cvdSeriesData = useMemo<Array<{ time: number; cvd: number }>>(() => {
    return Array.isArray(orderFlowData.cvd_series)
      ? (orderFlowData.cvd_series as Array<{ time: number; cvd: number }>)
      : []
  }, [orderFlowData.cvd_series])
  const candleTimes = useMemo(() => candles.map((c) => c.time), [candles])

  useEffect(() => {
    const bubbles = bubblesPrimitiveRef.current
    const heatmap = heatmapPrimitiveRef.current
    if (bubbles) {
      bubbles.setOptions({ showBubbles: flowMapActive })
      bubbles.setCandleTimes(candleTimes)
      bubbles.setEvents(flowMapActive ? visualEvents : [])
    }
    if (heatmap) {
      heatmap.setOptions({ showHeatmap: flowMapActive })
      heatmap.setCandleTimes(candleTimes)
      heatmap.setDepthSnapshots(flowMapActive ? depthSnapshots : [])
    }

    const chart = chartRef.current
    if (!chart) return

    if (flowMapActive) {
      if (!cvdSeriesRef.current) {
        try {
          const cvdPane = chart.addPane()
          const cvdSeries = cvdPane.addSeries(BaselineSeries, {
            baseValue: { type: 'price', price: 0 },
            topFillColor1: 'rgba(38, 166, 154, 0.28)',
            topFillColor2: 'rgba(38, 166, 154, 0.04)',
            topLineColor: '#26a69a',
            bottomFillColor1: 'rgba(239, 83, 80, 0.04)',
            bottomFillColor2: 'rgba(239, 83, 80, 0.28)',
            bottomLineColor: '#ef5350',
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: true,
            title: 'CVD',
          })
          cvdPane.setStretchFactor(0.20)
          if (chart.panes().length > 0) {
            chart.panes()[0].setStretchFactor(0.80)
          }
          cvdSeriesRef.current = cvdSeries
        } catch {}
      }

      // Default to focused recent 28-candle window on toggle ON to preserve normal candle density
      if (!prevFlowMapActiveRef.current && candles.length > 0) {
        try {
          const fromLogical = Math.max(0, candles.length - 28)
          const toLogical = candles.length + 3
          chart.timeScale().setVisibleLogicalRange({
            from: fromLogical,
            to: toLogical,
          })
        } catch {}
      }

      if (cvdSeriesRef.current && candles.length > 0) {
        const canonicalCvd = number(orderFlowData.cvd) ?? 0
        let lastKnownCvd = 0
        const cvdData = candles.map((c, i) => {
          if (cvdSeriesData.length > 0) {
            for (let j = cvdSeriesData.length - 1; j >= 0; j--) {
              if (cvdSeriesData[j].time <= c.time + 300) {
                lastKnownCvd = cvdSeriesData[j].cvd
                break
              }
            }
          } else if (i === candles.length - 1 && canonicalCvd !== 0) {
            lastKnownCvd = canonicalCvd
          }
          return { time: c.time as UTCTimestamp, value: lastKnownCvd }
        })

        const lastPoint = cvdData[cvdData.length - 1]
        if (
          lastCvdLengthRef.current > 0 &&
          (candles.length === lastCvdLengthRef.current || candles.length === lastCvdLengthRef.current + 1)
        ) {
          if (
            !lastCvdPointRef.current ||
            lastCvdPointRef.current.time !== lastPoint.time ||
            lastCvdPointRef.current.value !== lastPoint.value
          ) {
            cvdSeriesRef.current.update(lastPoint)
            lastCvdPointRef.current = lastPoint
            lastCvdLengthRef.current = candles.length
          }
        } else {
          cvdSeriesRef.current.setData(cvdData)
          lastCvdPointRef.current = lastPoint
          lastCvdLengthRef.current = candles.length
        }
      }
    } else {
      if (cvdSeriesRef.current) {
        try {
          if (chart.panes().length > 1) {
            chart.removePane(1)
          }
          if (chart.panes().length > 0) {
            chart.panes()[0].setStretchFactor(1)
          }
        } catch {}
        cvdSeriesRef.current = null
        lastCvdLengthRef.current = 0
        lastCvdPointRef.current = null
      }
      if (prevFlowMapActiveRef.current) {
        try {
          chart.timeScale().fitContent()
        } catch {}
      }
    }
    prevFlowMapActiveRef.current = flowMapActive
  }, [flowMapActive, visualEvents, depthSnapshots, cvdSeriesData, candleTimes, candles, orderFlowData])

  useEffect(() => {
    const candleSeries = candleSeriesRef.current
    const vwapSeries = vwapSeriesRef.current
    if (!candleSeries || !vwapSeries || candles.length === 0) return

    if (initializedIdentityRef.current !== seriesIdentity) {
      candleSeries.setData(candles.map(candleBar))
      vwapSeries.setData(candles.flatMap((candle) => {
        const value = vwapBar(candle)
        return value === null ? [] : [value]
      }))
      chartRef.current?.timeScale().fitContent()
      initializedIdentityRef.current = seriesIdentity
      lastCandleRef.current = candles.at(-1) ?? null
      syncOverlayRef.current()
      return
    }

    if (lastCandleRef.current === null) return
    for (const candle of candles) {
      const previous = lastCandleRef.current
      if (previous === null || candle.time < previous.time) continue
      if (
        candle.time === previous.time
        && candle.open === previous.open
        && candle.high === previous.high
        && candle.low === previous.low
        && candle.close === previous.close
        && candle.vwap === previous.vwap
      ) continue
      candleSeries.update(candleBar(candle))
      const value = vwapBar(candle)
      if (value !== null) vwapSeries.update(value)
      lastCandleRef.current = candle
    }
    syncOverlayRef.current()
  }, [candles, seriesIdentity])

  useEffect(() => {
    const ghostSeries = ghostSeriesRef.current
    const p10Series = p10SeriesRef.current
    const p50Series = p50SeriesRef.current
    const p90Series = p90SeriesRef.current
    if (!ghostSeries || !p10Series || !p50Series || !p90Series) return
    if (forecast === null) {
      ghostSeries.setData([]); p10Series.setData([]); p50Series.setData([]); p90Series.setData([])
      lastForecastRef.current = null
      syncOverlayRef.current()
      return
    }
    if (!shouldAcceptForecast(lastForecastRef.current, forecast)) return
    ghostSeries.setData(forecast.ghost.map(candleBar))
    p10Series.setData(forecast.p10.map((row) => ({ time: row.time as UTCTimestamp, value: row.value })))
    p50Series.setData(forecast.p50.map((row) => ({ time: row.time as UTCTimestamp, value: row.value })))
    p90Series.setData(forecast.p90.map((row) => ({ time: row.time as UTCTimestamp, value: row.value })))
    lastForecastRef.current = forecast
    if (forecastFitIdentityRef.current !== forecast.identity && (forecast.ghost.length || forecast.p50.length)) {
      forecastFitIdentityRef.current = forecast.identity
      chartRef.current?.timeScale().fitContent()
    }
    syncOverlayRef.current()
  }, [forecast])

  useEffect(() => {
    const series = candleSeriesRef.current
    if (!series) return
    for (const line of profilePriceLinesRef.current) series.removePriceLine(line)
    profilePriceLinesRef.current = []
    if (profile.status === 'AVAILABLE') {
      const levels = [{ title: 'POC', price: profile.poc, color: '#ff1447', style: LineStyle.Solid }]
      for (const level of levels) {
        if (level.price === null) continue
        profilePriceLinesRef.current.push(series.createPriceLine({
          price: level.price,
          color: level.color,
          lineWidth: level.title === 'POC' ? 2 : 1,
          lineStyle: level.style,
          axisLabelVisible: false,
          title: '',
        }))
      }
    }
    syncOverlayRef.current()
  }, [profile])

  useEffect(() => {
    currentPriceRef.current = currentPrice
    syncOverlayRef.current()
  }, [currentPrice, isFresh])

  const unavailable = data.status !== 'AVAILABLE' || candles.length === 0
  const unavailableReason = typeof data.reason === 'string'
    ? data.reason
    : candles.length === 0
      ? feed.error ?? 'Canonical candle cache is not ready'
      : null
  return (
    <section
      className={styles.shell}
      aria-label="NIFTY Futures live chart with VWAP"
      data-oracle-futures-chart
      data-source-timestamp={sourceTimestamp ?? 'UNAVAILABLE'}
      data-freshness={freshness}
      data-candle-count={candles.length}
      data-profile-status={profile.status}
      data-timezone="Asia/Kolkata"
      data-session="09:15-15:30"
      data-selected-timeframe={selectedTimeframe}
      data-live-fixture={visualLiveFixture ? 'true' : 'false'}
      data-forecast-revision={forecast?.revision ?? 'UNAVAILABLE'}
      data-forecast-mode={forecast?.mode ?? 'UNAVAILABLE'}
      data-tirex-state={forecast?.tirexState ?? 'NEUTRAL'}
      data-hud-revision={decisionHud.revision}
      data-hud-raw-revision={decisionHud.rawRevision}
      data-hud-display-revision={decisionHudSemantic.displayRevision}
      data-hud-quality={decisionHud.dataQuality}
      data-hud-focus-strike={decisionHud.focusStrike ?? 'UNAVAILABLE'}
      data-hud-relationship={decisionHud.relationshipState}
      data-hud-control-event={decisionHud.controlEventId ?? 'UNAVAILABLE'}
      data-hud-audit-collector={hudAuditCollector ? 'true' : 'false'}
    >
      <i className={styles.corner} aria-hidden="true" />
      <header className={styles.header}>
        <div className={styles.titleBlock}>
          <span className={styles.eyebrow}>Oracle market context · canonical cache</span>
          <h2>NIFTY FUT LIVE</h2>
        </div>
        <div className={styles.headerRight}>
          <button
            type="button"
            className={styles.flowMapToggle}
            aria-pressed={flowMapActive}
            onClick={() => setFlowMapActive((prev) => !prev)}
            aria-label="Toggle Flow Map order flow visualization"
          >
            [ FLOW MAP ]
          </button>
          <div className={styles.timeframes} role="group" aria-label="Futures chart timeframe">
            {TIMEFRAMES.map((timeframe) => (
              <button
                key={timeframe}
                type="button"
                aria-pressed={selectedTimeframe === timeframe}
                onClick={() => setSelectedTimeframe(timeframe)}
              >
                {timeframe.toUpperCase()}
              </button>
            ))}
          </div>
          <div className={styles.meta}>
            <strong>{contract}</strong>
            <span>{selectedTimeframe.toUpperCase()} · CANDLES + VWAP · IST</span>
            {freshness !== 'LAST_GOOD' && (
              <em data-state={freshness}>{freshness} · {age === null ? 'AGE —' : `AGE ${age.toFixed(1)}s`}</em>
            )}
          </div>
        </div>
      </header>
      <div className={styles.decisionHud} aria-label="Focus CE TiRex Focus PE universal live control bars">
        <DecisionSide label="CE" semantic={decisionHudSemantic.call} flowStrength={decisionHud.call.flowStrength} oiStrength={decisionHud.call.oiStrength} />
        <div className={styles.controlCenter}>
          <span
            className={styles.tirexPill}
            data-state={forecast?.tirexState ?? 'NEUTRAL'}
            data-status={forecast?.tirexStatus ?? 'UNAVAILABLE'}
            aria-label={`TiRex ${forecast?.tirexState ?? 'NEUTRAL'}`}
          ><i aria-hidden="true" /><small>PREMIUM CONTEXT</small><b>TiRex</b><strong>{forecast?.tirexState ?? 'NEUTRAL'}</strong></span>
          <span className={styles.relationshipState} data-state={decisionHud.relationshipState}>{decisionHud.relationshipState}</span>
        </div>
        <DecisionSide label="PE" semantic={decisionHudSemantic.put} flowStrength={decisionHud.put.flowStrength} oiStrength={decisionHud.put.oiStrength} />
      </div>
      <div className={flowMapActive ? styles.chartFrameFlowMap : styles.chartFrame}>
        <div ref={containerRef} className={styles.chart} />
        <div ref={overlayRef} className={styles.profile} data-status={profile.status} aria-label="Canonical session volume profile">
          {profile.status === 'AVAILABLE' ? profile.bins.map((bin) => (
            <i
              key={bin.price}
              data-profile-price={bin.price}
              data-poc={bin.isPoc ? 'true' : 'false'}
              style={{ '--profile-width': `${Math.max(4, bin.relativeVolume * 100)}%` } as CSSProperties}
            />
          )) : <span>PROFILE DEGRADED · {profile.reason ?? 'UNAVAILABLE'}</span>}
          {profile.status === 'AVAILABLE' && profile.poc !== null && (
            <b className={styles.pocPill} data-profile-price={profile.poc}>POC <strong>[ {profile.poc.toLocaleString('en-IN')} ]</strong></b>
          )}
        </div>
        <span ref={nowDividerRef} className={styles.nowDivider} aria-hidden="true"><i>NOW</i></span>
        <span ref={liveDotRef} className={styles.liveDot} data-live={isFresh ? 'true' : 'false'} aria-hidden="true" />
        {currentPrice !== null && <span ref={livePriceRef} className={styles.liveLegend} data-live={isFresh ? 'true' : 'false'}>{visualLiveFixture ? '● TEST LIVE ' : isFresh ? '● LIVE ' : ''}{currentPrice.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>}
        {unavailable && (
          <div className={styles.unavailable} role="status">
            <strong>FUTURES CHART UNAVAILABLE</strong>
            <span>{unavailableReason}</span>
          </div>
        )}
      </div>
      <footer>
        <span>UPSTOX FUTURES · FINALIZED HISTORY + LIVE FORMING BAR</span>
        <span>VWAP · SESSION RESET</span>
        <span>{profile.status === 'AVAILABLE' ? 'PROFILE · POC' : 'PROFILE DEGRADED'}</span>
        <span>KRONOS GHOST · CHRONOS P10 / P50 / P90</span>
        {forecast?.mode === 'HISTORICAL_REPLAY' && <span>FORECAST · HISTORICAL REPLAY</span>}
        <span>{sourceTimestamp ?? 'SOURCE TIME UNAVAILABLE'}</span>
      </footer>
    </section>
  )
})
