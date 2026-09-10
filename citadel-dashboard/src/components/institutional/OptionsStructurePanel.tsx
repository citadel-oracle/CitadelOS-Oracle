'use client'

import { Badge, Card, SectionHeader as DesignSectionHeader } from '@/design-system'
import type { CSSProperties, ReactNode } from 'react'
import { useEffect, useState } from 'react'
import styles from './OptionsStructurePanel.module.css'
import {
  ArgusFlowEdge,
  DecisionWindow,
  EngineAgreement,
  LatestStateChange,
  StructuralStrengthIndex,
  TrendEnergyRing,
  VobPrecisionWheel,
  type SsiProjection,
} from './OseFlagshipComponents'
import { duelMarkerPosition, latestLifecycleSummary } from './oseVisualGeometry'

type DirectionState = 'ULTRA BULLISH' | 'BULLISH' | 'NEUTRAL' | 'NEUTRAL / MIXED' | 'BEARISH' | 'ULTRA BEARISH' | 'INSUFFICIENT HISTORY'

interface OseZone {
  zone_id: string
  role: 'SUPPORT' | 'RESISTANCE'
  zone_low: number
  zone_high: number
  touch_count: number
  status: string
  freshness: string
  distance_points: number
  strength_score: number
  broken_at?: string | null
}

interface OseStructure {
  timeframe: string
  state: string
  reason: string
  premium: number | null
  demand: OseZone | null
  supply: OseZone | null
  recently_broken: OseZone[]
  supply_break: boolean
  demand_break: boolean
  bullish_retest: boolean
  bearish_retest: boolean
  evaluated_through: string | null
  completed_bucket: boolean
}

interface OseContractState {
  contract: {
    security_id: string
    option_type: 'CE' | 'PE'
    strike: number
    expiry: string
    lot_size: number
    trading_symbol: string
  }
  premium: number | null
  score: number
  composite: { state: string; vob_direction: string; trend_direction: string; explanation?: string[] }
  vob: { state: DirectionState; strength: number; reasons: string[]; evaluated_through: string | null }
  trend: {
    state: DirectionState
    close: number | null
    ema_50: number | null
    above_ema_50: boolean | null
    supertrend_value: number | null
    supertrend_direction: 'POSITIVE' | 'NEGATIVE' | null
    strength?: number | null
    evaluated_through: string | null
    reason: string
  }
  structures: Record<'3m' | '5m', OseStructure>
  score_breakdown: Record<string, { weight: number; input: number; contribution: number }>
  ssi?: SsiProjection
  decision_window?: { state: string; explanation: string; distance_points?: number | null }
  engine_agreement?: {
    state: string
    qualifier: string
    vob: { state: string; direction: string }
    trend: { state: string; direction: string }
    flow: { state: string; direction: string }
  }
  latest_state_change?: {
    previous_state: string
    current_state: string
    previous_score: number
    current_score: number
    reason: string
    evaluated_through: string | null
  } | null
  quality: {
    status: string
    freshness: string
    stale_age_seconds: number | null
    data_gap_count: number
    latest_completed_1m: string | null
  }
  candle_buffer_size: number
}

interface OseFlowSide {
  side: 'CE' | 'PE'
  score: number | null
  activity: string
  status: string
  reasons: string[]
  surrounding_confirmation?: number | null
  surrounding_sample_size?: number
  quality_band?: string
  components: Record<string, { weight: number; input: number; contribution: number }>
}

interface OseOptionFlow {
  state: string
  status: string
  call: OseFlowSide
  put: OseFlowSide
  balance_marker: number
  dominant_side: string
  evaluated_at: string
  source_timestamp: string | null
  source: string
  age_seconds?: number | null
  prior_snapshot_available?: boolean
  edge?: {
    label?: string
    delta?: number | null
    band?: string
    summary?: string
    last_authoritative_state?: string | null
  }
  executionInfluence: 'ZERO'
  execution_influence: 0
  strategy_influence: 0
  order_influence: 0
  performance?: { calculation_ms?: number; serialized_bytes?: number }
}

export interface OptionsStructureData {
  module: string
  status: string
  runtime_status: string
  reason?: string | null
  symbol: string
  spot: number
  anchor: number
  expiry: string
  pair_status: string
  rollover: {
    state: string
    upper_boundary: number
    lower_boundary: number
    next_up: number
    next_down: number
    last_rollover: string | null
    audit: Array<Record<string, unknown>>
  }
  contracts: { CE?: OseContractState; PE?: OseContractState }
  duel?: { ce_score: number; pe_score: number; delta: number; state: string; label: string } | null
  option_flow?: OseOptionFlow | null
  engine_agreement?: Record<'CE' | 'PE', NonNullable<OseContractState['engine_agreement']>>
  structural_read?: { headline: string; lines: string[]; advisory_only: boolean; execution_influence: 0 }
  recent_lifecycle_events?: Array<{ side: string; timeframe: string; event: string; role: string; timestamp: string | null }>
  data_quality?: { status: string; source: string; data_gap_count: number; canonical_state: string; render_contract: string }
  score_weights?: Record<string, number>
  calculated_at?: string
  source_timestamp?: string
  source_age_seconds?: number
  executionInfluence?: 'ZERO'
  execution_influence?: number
  advisory_only?: boolean
  paper_only?: boolean
  live_trading_enabled?: boolean
  broker_submission?: boolean
  performance?: {
    calculation_ms?: number
    api_serialization_ms?: number
    ingestion_ms?: number
    serialized_bytes?: number
  }
  canonical_digest?: string
}

const formatPrice = (value: number | null | undefined) => value == null
  ? 'Unavailable'
  : value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const formatTime = (value: string | null | undefined) => value
  ? new Date(value).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' }).toUpperCase()
  : 'Unavailable'

const formatDate = (value: string | null | undefined) => value
  ? new Date(`${value}T00:00:00+05:30`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' }).toUpperCase()
  : 'Unavailable'

const tone = (state: string) => {
  const normalized = state.toUpperCase()
  if (normalized.includes('BULLISH') || normalized.includes('CALL ADVANTAGE') || normalized === 'LIVE' || normalized === 'FRESH' || normalized === 'POSITIVE') return styles.positive
  if (normalized.includes('BEARISH') || normalized.includes('PUT ADVANTAGE') || normalized === 'NEGATIVE' || normalized.includes('GAP')) return styles.negative
  if (normalized.includes('CONFLICT') || normalized.includes('TRANSITION') || normalized.includes('STALE') || normalized.includes('WARM')) return styles.warning
  return styles.neutral
}

function StructureAxis({ structure, primary }: { structure: OseStructure; primary?: boolean }) {
  const demand = structure.demand
  const supply = structure.supply
  const premium = structure.premium
  const values = [demand?.zone_low, demand?.zone_high, premium, supply?.zone_low, supply?.zone_high].filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const minimum = values.length ? Math.min(...values) : 0
  const maximum = values.length ? Math.max(...values) : 1
  const padding = Math.max((maximum - minimum) * 0.14, 1)
  const low = minimum - padding
  const high = maximum + padding
  const position = (value: number) => Math.max(2, Math.min(98, ((value - low) / (high - low || 1)) * 100))
  const demandStart = demand ? position(demand.zone_low) : 0
  const demandEnd = demand ? position(demand.zone_high) : 0
  const supplyStart = supply ? position(supply.zone_low) : 100
  const supplyEnd = supply ? position(supply.zone_high) : 100
  const latestBroken = (role: OseZone['role']) => [...(structure.recently_broken ?? [])]
    .filter((zone) => zone.role === role && zone.broken_at)
    .sort((left, right) => new Date(right.broken_at ?? 0).getTime() - new Date(left.broken_at ?? 0).getTime())[0]
  const brokenDemand = latestBroken('SUPPORT')
  const brokenSupply = latestBroken('RESISTANCE')
  const breakPosition = (zone: OseZone) => position((zone.zone_low + zone.zone_high) / 2)
  const latestSummary = latestLifecycleSummary(structure)
  const retestZone = structure.bullish_retest ? brokenSupply : structure.bearish_retest ? brokenDemand : undefined
  return (
    <div className={`${styles.structureAxis} ${primary ? styles.primaryAxis : styles.earlyAxis}`} data-timeframe={structure.timeframe} data-timeframe-role={primary ? 'PRIMARY_CONFIRMATION' : 'EARLY_STRUCTURE'}>
      <header><strong>{structure.timeframe.toUpperCase()} <span>{primary ? 'PRIMARY CONFIRMATION' : 'EARLY STRUCTURE'}</span></strong><Badge unstyled className={tone(structure.state)}>{structure.state}</Badge><span>{structure.completed_bucket ? 'COMPLETED' : 'UNAVAILABLE'}</span></header>
      <div className={styles.axisValues}>
        <span><small>Demand</small><strong>{demand ? `${formatPrice(demand.zone_low)}–${formatPrice(demand.zone_high)}` : 'Unavailable'}</strong></span>
        <span><small>Premium</small><strong>{formatPrice(premium)}</strong></span>
        <span><small>Supply</small><strong>{supply ? `${formatPrice(supply.zone_low)}–${formatPrice(supply.zone_high)}` : 'Unavailable'}</strong></span>
      </div>
      {values.length >= 3 ? <div className={styles.axisTrack}>
        {demand ? <i className={styles.demandBand} style={{ left: `${demandStart}%`, width: `${Math.max(2, demandEnd - demandStart)}%` }} /> : null}
        {supply ? <i className={styles.supplyBand} style={{ left: `${supplyStart}%`, width: `${Math.max(2, supplyEnd - supplyStart)}%` }} /> : null}
        {premium != null ? <b className={styles.premiumMarker} style={{ left: `${position(premium)}%` }} title={`Premium ${formatPrice(premium)}`} /> : null}
        {demand?.touch_count ? <em className={`${styles.eventMarker} ${styles.touchMarker}`} data-event-type="TOUCH" style={{ left: `${position((demand.zone_low + demand.zone_high) / 2)}%` }} title={`Demand touched ${demand.touch_count} times`}><span>T</span></em> : null}
        {supply?.touch_count ? <em className={`${styles.eventMarker} ${styles.touchMarker}`} data-event-type="TOUCH" style={{ left: `${position((supply.zone_low + supply.zone_high) / 2)}%` }} title={`Supply touched ${supply.touch_count} times`}><span>T</span></em> : null}
        {structure.demand_break && brokenDemand ? <em className={`${styles.eventMarker} ${styles.breakMarker} ${retestZone ? '' : styles.latestEvent}`} data-event-type="BREAK" style={{ left: `${breakPosition(brokenDemand)}%` }} title="Authoritative demand break"><span>B</span></em> : null}
        {structure.supply_break && brokenSupply ? <em className={`${styles.eventMarker} ${styles.breakMarker} ${retestZone ? '' : styles.latestEvent}`} data-event-type="BREAK" style={{ left: `${breakPosition(brokenSupply)}%` }} title="Authoritative supply break"><span>B</span></em> : null}
        {retestZone ? <em className={`${styles.eventMarker} ${styles.retestMarker} ${styles.latestEvent}`} data-event-type="RETEST" style={{ left: `${breakPosition(retestZone)}%` }} title={latestSummary}><span>R</span></em> : null}
      </div> : <div className={styles.axisUnavailable}>Structure unavailable</div>}
      <footer>
        <span>Demand distance <strong>{demand ? `${Math.abs(demand.distance_points).toFixed(2)} pts` : '—'}</strong></span>
        <span>Supply distance <strong>{supply ? `${Math.abs(supply.distance_points).toFixed(2)} pts` : '—'}</strong></span>
        <span>Lifecycle <strong>{demand?.status ?? supply?.status ?? 'UNAVAILABLE'}</strong></span>
        <span>Evaluated <strong>{formatTime(structure.evaluated_through)}</strong></span>
      </footer>
      <p className={styles.lifecycleSummary}>{latestSummary}</p>
    </div>
  )
}

function ContractColumn({ side, state }: { side: 'CE' | 'PE'; state: OseContractState }) {
  const five = state.structures['5m']
  const indicatorRead = state.trend.above_ema_50 == null
    ? 'EMA unavailable'
    : `${state.trend.above_ema_50 ? 'Above' : 'Below'} EMA · Supertrend ${state.trend.supertrend_direction ? state.trend.supertrend_direction.toLowerCase() : 'unavailable'}`
  const compositeExplanation = state.composite.explanation?.join(' · ') ?? 'Composite explanation unavailable'
  return (
    <article className={`${styles.contractColumn} ${side === 'CE' ? styles.callColumn : styles.putColumn}`} aria-label={`${side} structure intelligence`}>
      <header className={styles.contractHeader}>
        <div><span>{side === 'CE' ? '100PT ITM CALL' : '100PT ITM PUT'}</span><strong>{state.contract.strike} {side}</strong><small>{state.contract.trading_symbol} · {state.contract.security_id}</small></div>
        <div className={styles.contractPrice}><span>Live Premium</span><strong>₹{formatPrice(state.premium)}</strong><small>{indicatorRead}</small><Badge unstyled className={tone(state.quality.status)}>{state.quality.status}</Badge></div>
      </header>
      <div className={styles.compositeStrip}>
        <span>Structural Strength Index</span>
        <StructuralStrengthIndex ssi={state.ssi} compact />
        <strong className={tone(state.composite.state)}>{state.composite.state}</strong>
        <small>{compositeExplanation}</small>
      </div>
      <div className={styles.wheelGrid}>
        <VobPrecisionWheel state={state.vob.state} score={state.vob.strength} reason={state.vob.reasons.join(' · ')} evaluated={state.vob.evaluated_through} live={state.quality.status === 'LIVE' && state.quality.freshness === 'FRESH'} />
        <TrendEnergyRing state={state.trend.state} score={state.trend.strength ?? null} reason={state.trend.reason} evaluated={state.trend.evaluated_through} live={state.quality.status === 'LIVE' && state.quality.freshness === 'FRESH'} />
      </div>
      <div className={styles.contextStrip}><DecisionWindow value={state.decision_window} /><LatestStateChange value={state.latest_state_change} /></div>
      <div className={styles.axes}>
        <StructureAxis structure={state.structures['3m']} />
        <StructureAxis structure={five} primary />
      </div>
      <div className={styles.rawMetrics}>
        <div><span>EMA 50</span><strong>{formatPrice(state.trend.ema_50)}</strong><small className={tone(state.trend.above_ema_50 ? 'BULLISH' : 'BEARISH')}>{state.trend.above_ema_50 == null ? 'Unavailable' : state.trend.above_ema_50 ? 'Premium above' : 'Premium below'}</small></div>
        <div><span>Supertrend 10, 3.4</span><strong>{formatPrice(state.trend.supertrend_value)}</strong><small className={tone(state.trend.supertrend_direction ?? '')}>{state.trend.supertrend_direction ?? 'Unavailable'}</small></div>
        <div><span>VOB state index</span><strong>{state.vob.strength}</strong><small>Deterministic wheel position</small></div>
        <div><span>Freshness</span><strong className={tone(state.quality.freshness)}>{state.quality.freshness}</strong><small>{state.quality.stale_age_seconds == null ? 'Age unavailable' : `${state.quality.stale_age_seconds.toFixed(0)}s age`}</small></div>
      </div>
      <details className={styles.details}>
        <summary>Raw score inputs and reasons</summary>
        <div className={styles.scoreBreakdown}>
          {Object.entries(state.score_breakdown).map(([name, item]) => <div key={name}><span>{name.replaceAll('_', ' ')}</span><strong>{item.contribution >= 0 ? '+' : ''}{item.contribution.toFixed(2)}</strong><small>Weight {item.weight}</small></div>)}
        </div>
      </details>
    </article>
  )
}

export function OptionsStructurePanel({ data, argusWriter, tacticalEdge }: {
  data?: OptionsStructureData | null
  argusWriter?: ReactNode
  tacticalEdge?: ReactNode
}) {
  const [renderDuration, setRenderDuration] = useState<number | null>(null)
  useEffect(() => {
    const started = performance.now()
    const frame = requestAnimationFrame(() => setRenderDuration(performance.now() - started))
    return () => cancelAnimationFrame(frame)
  }, [data?.canonical_digest])
  const ce = data?.contracts?.CE
  const pe = data?.contracts?.PE
  const runtime = data?.runtime_status ?? data?.status ?? 'UNAVAILABLE'
  const duel = data?.duel
  const duelPosition = duel ? duelMarkerPosition(duel.ce_score, duel.pe_score) : 50
  return (
    <Card as="section" unstyled className={`panel workspace-unified-section ${styles.panel}`} aria-label="Options Structure Engine" data-canonical-digest={data?.canonical_digest}>
      <DesignSectionHeader
        as="div"
        unstyled
        className="section-heading"
        eyebrowClassName="section-eyebrow"
        eyebrow={<>01C / Trading Workspace<span className={`status-dot ${runtime === 'LIVE' ? 'live' : ''}`} title={`OSE runtime: ${runtime}`} /></>}
        title="Options Structure Engine"
        asideClassName="section-aside"
        aside={<div className={styles.commandAside}><span>NIFTY <strong>{formatPrice(data?.spot)}</strong></span><i /><span>Anchor <strong>{data?.anchor ?? '—'}</strong></span><i /><span>Expiry <strong>{formatDate(data?.expiry)}</strong></span><Badge unstyled className={tone(runtime)}>{runtime}</Badge></div>}
      />

      <div className={styles.commandStrip}>
        <span>Pair <strong>{data?.pair_status ?? 'UNAVAILABLE'}</strong></span>
        <span>Rollover <strong className={tone(data?.rollover?.state ?? '')}>{data?.rollover?.state ?? 'UNAVAILABLE'}</strong></span>
        <span>Next down <strong>{data?.rollover?.next_down ?? '—'}</strong></span>
        <span>Boundary <strong>{data?.rollover ? `${data.rollover.lower_boundary} / ${data.rollover.upper_boundary}` : '—'}</strong></span>
        <span>Next up <strong>{data?.rollover?.next_up ?? '—'}</strong></span>
        <span>Source <strong>{formatTime(data?.source_timestamp)}</strong></span>
        <span>Age <strong>{data?.source_age_seconds == null ? '—' : `${data.source_age_seconds.toFixed(1)}s`}</strong></span>
        <span>Security IDs <strong>{ce?.contract.security_id ?? '—'} / {pe?.contract.security_id ?? '—'}</strong></span>
        <span className={styles.safety}>Advisory only · Execution influence {data?.executionInfluence ?? 'ZERO'}</span>
      </div>

      {duel ? <div className={styles.duel} aria-label="CE versus PE structural duel">
        <div className={`${styles.duelScore} ${styles.duelCall}`}><span>{ce?.contract.strike} CE</span>{ce ? <StructuralStrengthIndex ssi={ce.ssi} compact /> : null}<small>{ce?.composite.state}</small></div>
        <div className={styles.duelCentre}><span>CE VS PE</span><strong className={tone(duel.state)}>{duel.state}</strong><b>{duel.label}</b><i data-duel-position={duelPosition.toFixed(4)} style={{ '--duel-position': `${duelPosition}%` } as CSSProperties} /></div>
        <div className={`${styles.duelScore} ${styles.duelPut}`}><span>{pe?.contract.strike} PE</span>{pe ? <StructuralStrengthIndex ssi={pe.ssi} compact /> : null}<small>{pe?.composite.state}</small></div>
      </div> : <div className={styles.unavailable} role="status">{data?.reason ?? 'Waiting for the authoritative option pair'}</div>}

      {data?.option_flow ? <ArgusFlowEdge flow={data.option_flow} /> : <div className={styles.flowUnavailable}>ARGUS option flow unavailable</div>}
      {argusWriter}
      {tacticalEdge}
      <EngineAgreement agreements={data?.engine_agreement} />

      {ce && pe ? <div className={styles.contractGrid}><ContractColumn side="CE" state={ce} /><ContractColumn side="PE" state={pe} /></div> : null}

      {ce && pe && duel ? <div className={styles.structuralRead} aria-label="Current structural read">
        <header><span>Current structural read</span><Badge unstyled>Advisory only</Badge></header>
        <div><strong className={tone(data?.structural_read?.headline ?? 'UNAVAILABLE')}>{data?.structural_read?.headline ?? 'STRUCTURAL READ NOT REPORTED'}</strong><b>{duel.label}</b></div>
        <div className={styles.structuralLines}>{data?.structural_read?.lines?.length ? data.structural_read.lines.slice(0, 3).map((line) => <p key={line}>{line}</p>) : <p>Awaiting the canonical backend synthesis.</p>}</div>
      </div> : null}

      <div className={styles.bottomGrid}>
        <div><span>Cross-contract alignment</span><strong>{duel?.state ?? 'UNAVAILABLE'}</strong><small>{duel ? `Directional agreement delta ${duel.delta >= 0 ? '+' : ''}${duel.delta}` : 'Pair not ready'}</small></div>
        <div><span>Lifecycle events</span><strong>{data?.recent_lifecycle_events?.length ?? 0}</strong><small>{data?.recent_lifecycle_events?.[0] ? `${data.recent_lifecycle_events[0].side} ${data.recent_lifecycle_events[0].timeframe.toUpperCase()} ${data.recent_lifecycle_events[0].event}` : 'No recent structural event'}</small></div>
        <div><span>Rollover audit</span><strong>{data?.rollover?.audit?.length ?? 0}</strong><small>Last {formatTime(data?.rollover?.last_rollover)}</small></div>
        <div><span>Data quality</span><strong className={tone(data?.data_quality?.status ?? runtime)}>{data?.data_quality?.status ?? runtime}</strong><small>{data?.data_quality?.data_gap_count ?? 0} gaps · Canonical source</small></div>
        <div><span>Canonical / API / Render</span><strong>{data?.data_quality?.render_contract ?? 'UNAVAILABLE'}</strong><small>Backend classifications rendered verbatim</small></div>
        <div><span>Calculation / Render</span><strong>{data?.performance?.calculation_ms == null ? '—' : `${data.performance.calculation_ms.toFixed(2)}ms`}</strong><small>{renderDuration == null ? 'Render pending' : `${renderDuration.toFixed(2)}ms render`} · {data?.performance?.serialized_bytes?.toLocaleString('en-IN') ?? '—'} bytes</small></div>
      </div>
    </Card>
  )
}
