'use client'

import { useEffect, useId, useRef, useState, type CSSProperties } from 'react'
import type { ArgusProviderProjection } from './oracleArgusProjection'
import { buildOracleArgusPrime01CVisualFixture } from './OracleArgusPrime01C.fixture'
import styles from './OracleArgusPrime01C.module.css'

type JsonRecord = Record<string, unknown>
type SignalTone = 'red' | 'green' | 'cyan' | 'amber' | 'slate'
export type RailAccent = 'cyan' | 'amber' | 'violet' | 'magenta' | 'red' | 'green' | 'slate'
export type RailState = 'LIVE' | 'HELD' | 'STALE' | 'UNAVAILABLE'

export interface OracleArgusPrime01CProps {
  tactical: unknown
  optionsStructure: unknown
  vob: unknown
  provider: ArgusProviderProjection
  marketState?: unknown
  marketClosedAt?: unknown
  dominance?: unknown
  participationVerdict?: unknown
  marketSentiment?: unknown
  marketBias?: unknown
  visualFixture?: string | null
}

const record = (value: unknown): JsonRecord =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonRecord
    : {}

const list = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const text = (value: unknown, fallback = 'UNAVAILABLE'): string =>
  typeof value === 'string' && value.trim() ? value.trim() : fallback
const finite = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null
const bounded = (value: unknown): number | null => {
  const number = finite(value)
  return number === null ? null : Math.max(0, Math.min(100, number))
}
const scoreText = (value: unknown): string => {
  const number = finite(value)
  return number === null ? '—' : Math.round(number).toString()
}
const numberText = (value: unknown, digits = 2): string => {
  const number = finite(value)
  return number === null ? 'UNAVAILABLE' : number.toLocaleString('en-IN', { maximumFractionDigits: digits })
}
const oiMetricText = (value: unknown, digits = 0): string => {
  const number = finite(value)
  if (number === null) return 'UNAVAILABLE'
  if (number === 0) return 'FLAT'
  return number.toLocaleString('en-IN', { maximumFractionDigits: digits })
}
const timeText = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim()) return 'UNAVAILABLE'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Kolkata' })
}
const istTimeText = (value: unknown): string | null => {
  if (typeof value !== 'string' || !value.trim()) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? null
    : `${date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })} IST`
}
const upper = (value: unknown, fallback = 'UNAVAILABLE'): string => text(value, fallback).toUpperCase()

const toneFor = (value: unknown): SignalTone => {
  const state = upper(value)
  if (/CALL|BULL|SUPPORT|BUYING|COVERING|WRITING/.test(state) && !/PUT BUYING|CALL WRITING/.test(state)) return 'green'
  if (/PUT|BEAR|RESISTANCE|BREAK|RISK|FAILED/.test(state)) return 'red'
  if (/LIVE|FRESH|AVAILABLE|CONFIRM/.test(state)) return 'cyan'
  if (/HOLD|WAIT|MIXED|BALANCED|BUILDING|LOADING|PIN/.test(state)) return 'amber'
  return 'slate'
}

const primeToneFor = (direction: unknown, fresh: boolean): SignalTone => {
  if (!fresh) return 'slate'
  const state = upper(direction, 'HOLD')
  if (/CALL|BULL/.test(state)) return 'green'
  if (/PUT|BEAR/.test(state)) return 'red'
  return 'amber'
}

const directionArrow = (value: unknown): string => {
  const state = upper(value)
  if (/RISING|UP|CALL|BULL|ACCEL/.test(state)) return '↑'
  if (/FALLING|DOWN|PUT|BEAR|UNWIND/.test(state)) return '↓'
  return '→'
}

function Panel({
  title,
  eyebrow,
  children,
  className = '',
  tone = 'red',
}: {
  title: string
  eyebrow?: string
  children: React.ReactNode
  className?: string
  tone?: SignalTone
}) {
  return (
    <section className={`${styles.panel} ${styles[`tone_${tone}`]} ${className}`} tabIndex={0}>
      <i className={styles.cornerTl} aria-hidden="true" />
      <i className={styles.cornerBr} aria-hidden="true" />
      <header className={styles.panelHeader}>
        <div>{eyebrow && <span>{eyebrow}</span>}<h3>{title}</h3></div>
        <b aria-hidden="true" />
      </header>
      {children}
    </section>
  )
}

function SsiDial({ side, contract, fresh }: { side: 'CE' | 'PE'; contract: JsonRecord; fresh: boolean }) {
  const ssi = record(contract.ssi)
  const contractInfo = record(contract.contract)
  const score = bounded(ssi.score)
  const id = useId().replaceAll(':', '')
  const needleAngle = Math.PI + ((score ?? 0) / 100) * Math.PI
  const needleX = 65 + Math.cos(needleAngle) * 53
  const needleY = 70 + Math.sin(needleAngle) * 53
  const ticks = [[15,70,10,60],[20,55,15,47],[30,40,26,33],[45,28,43,20],[65,22,65,13],[85,28,87,20],[100,40,104,33],[110,55,115,47],[115,70,120,60]]
  return (
    <article className={`${styles.ssiCard} ${side === 'CE' ? styles.ssiCe : styles.ssiPe}`} data-score-state={fresh ? 'live' : 'retained'}>
      <div className={styles.ssiDial}>
        <svg viewBox="0 0 130 76" role="img" aria-label={`${side} Structural Strength Index ${scoreText(score)} of 100`}>
          <defs>
            <linearGradient id={`ssi-gradient-${id}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={side === 'CE' ? '#2ff0d8' : '#ffc93c'} />
              <stop offset="100%" stopColor="#ff5c82" />
            </linearGradient>
            <filter id={`ssi-glow-${id}`} x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="3.5" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          <path className={styles.dialTrack} d="M12 70 A53 53 0 0 1 118 70" pathLength="166" />
          {ticks.map(([x1,y1,x2,y2], index) => <line key={index} className={index === 4 ? styles.dialTickMajor : styles.dialTick} x1={x1} y1={y1} x2={x2} y2={y2} />)}
          <path
            className={styles.dialValue}
            d="M12 70 A53 53 0 0 1 118 70"
            pathLength="166"
            strokeDasharray="166"
            strokeDashoffset={166 - ((score ?? 0) / 100) * 166}
            stroke={`url(#ssi-gradient-${id})`}
            filter={`url(#ssi-glow-${id})`}
          />
          {score !== null && <circle className={styles.dialTip} cx={needleX} cy={needleY} r="4.5" filter={`url(#ssi-glow-${id})`} />}
        </svg>
        <div className={styles.dialCenter}><strong>{scoreText(score)}</strong><small>/100</small></div>
      </div>
      <div className={styles.ssiCopy}>
        <span>{side} STRUCTURAL STRENGTH</span>
        <strong>{upper(ssi.band)}</strong>
        <p>{text(contractInfo.trading_symbol, `${side} CONTRACT UNAVAILABLE`)}</p>
      </div>
    </article>
  )
}

function FlowMeter({ label, data }: { label: string; data: JsonRecord }) {
  const score = bounded(data.score)
  const full = score === null ? 0 : Math.floor(score / 10)
  const remainder = score === null ? 0 : score % 10
  const hazard = /LONG UNWINDING/.test(upper(data.activity))
  const channel = label.startsWith('CALL') ? styles.flowCall : styles.flowPut
  return (
    <div className={`${styles.flowMeter} ${channel}`} tabIndex={0}>
      <div><span>{label}</span><strong>{scoreText(score)}</strong></div>
      <div className={`${styles.segmentMeter} ${hazard ? styles.segmentHazard : ''}`} aria-label={`${label} ${scoreText(score)} of 100`}>
        {Array.from({ length: 10 }, (_, index) => {
          const state = index < full ? 'full' : index === full && remainder > 0 ? 'partial' : 'off'
          return <i key={index} data-fill={state} style={state === 'partial' ? { '--partial': `${remainder * 10}%` } as CSSProperties : undefined} />
        })}
      </div>
      <p>{upper(data.activity)} · {upper(data.quality_band)}</p>
    </div>
  )
}

/** Presentation-only geometry for canonical values; all decision math stays upstream. */
export function LiquidGlassRail({
  position,
  state,
  accent,
  bipolar = false,
  priorPosition,
  sweepDuration = '3.4s',
  sweepDelay = '0s',
  animationMode = 'liquid',
  staleMotion = 'static',
  ariaLabel,
}: {
  position: number | null
  state: RailState
  accent: RailAccent
  bipolar?: boolean
  priorPosition?: number | null
  sweepDuration?: string
  sweepDelay?: string
  animationMode?: 'liquid' | 'frozen'
  staleMotion?: 'static' | 'ping'
  ariaLabel: string
}) {
  const marker = position === null ? 50 : Math.max(4, Math.min(96, position))
  const active = state === 'LIVE' && position !== null
  const searching = state === 'STALE' || state === 'HELD'
  const fillStart = bipolar ? Math.min(50, marker) : 0
  const fillWidth = bipolar ? Math.abs(marker - 50) : marker
  const style = {
    '--rail-marker': `${marker}%`,
    '--rail-fill-start': `${fillStart}%`,
    '--rail-fill-width': `${fillWidth}%`,
    '--rail-sweep-duration': sweepDuration,
    '--rail-sweep-delay': sweepDelay,
  } as CSSProperties

  return (
    <div
      className={`${styles.glassTrack} ${styles[`railAccent_${accent}`]}`}
      data-rail-state={state}
      data-rail-bipolar={bipolar ? 'true' : 'false'}
      data-rail-motion={animationMode}
      data-rail-stale-motion={staleMotion}
      style={style}
      role="img"
      aria-label={ariaLabel}
    >
      {bipolar && <i className={styles.centerGutter} aria-hidden="true" />}
      {priorPosition !== null && priorPosition !== undefined && <i className={styles.priorMarker} style={{ '--prior-marker': `${Math.max(4, Math.min(96, priorPosition))}%` } as CSSProperties} aria-hidden="true" />}
      {active && <span className={styles.railFill} aria-hidden="true" />}
      {state !== 'UNAVAILABLE' && <i className={styles.refractSweep} aria-hidden="true" />}
      {searching && position !== null
        ? <span className={styles.frozenNode} aria-hidden="true">{staleMotion === 'ping' && <><i className={styles.pingRing} /><i className={styles.pingRing} /><i className={styles.pingRing} /></>}</span>
        : active && animationMode === 'liquid' && <i className={styles.liquidThumb} aria-hidden="true" />}
    </div>
  )
}

function CapacityMeter({ label, score, state, fresh = true }: { label: string; score: unknown; state: unknown; fresh?: boolean }) {
  const value = bounded(score)
  const tone = fresh ? toneFor(state) : 'slate'
  const railState: RailState = fresh && value !== null ? 'LIVE' : value === null ? 'UNAVAILABLE' : 'STALE'
  const accent: RailAccent = tone === 'cyan' || tone === 'amber' || tone === 'green' || tone === 'red' ? tone : 'violet'
  return (
    <div className={`${styles.capacity} ${styles[`tone_${tone}`]}`} tabIndex={0}>
      <span>{label}</span><strong className={railState === 'LIVE' ? styles.kineticValue : ''}>{scoreText(value)}</strong>
      <LiquidGlassRail position={value} state={railState} accent={accent} ariaLabel={`${label} ${scoreText(value)} of 100`} />
      <small>{upper(state)}</small>
    </div>
  )
}

function PrimeGlowRing({
  value,
  label,
  caption,
  state,
  variant,
  signal = false,
  toneClass,
  children,
}: {
  value: unknown
  label: string
  caption: string
  state?: string
  variant: 'main' | 'mini'
  signal?: boolean
  toneClass?: string
  children?: React.ReactNode
}) {
  return (
    <div
      className={`${styles.primeGlowRing} ${variant === 'main' ? styles.primeGlowMain : styles.primeGlowMini} ${signal ? styles.primeGlowSignal : ''} ${toneClass ?? ''}`}
      data-prime-glow-ring={variant}
    >
      <div className={styles.primeGlowRipples} aria-hidden="true"><i /><i /><i /></div>
      <div className={styles.primeGlowCore}>
        {children}
        <span>{label}</span>
        <strong>{scoreText(value)}</strong>
        {caption && <small>{caption}</small>}
        {state && <b>{state}</b>}
      </div>
    </div>
  )
}

function PrimeHub({ prime, fixtureScore, flipToken, flipCount, fresh, tone }: { prime: JsonRecord; fixtureScore: number | null; flipToken: number; flipCount: number; fresh: boolean; tone: SignalTone }) {
  const canonicalScore = bounded(prime.display_score ?? prime.argus_prime_score)
  const score = fixtureScore ?? canonicalScore
  return (
    <div className={`${styles.hubSystem} ${styles[`tone_${tone}`]}`} data-signal-flip-count={flipCount} data-hub-freshness={fresh ? 'LIVE' : 'LAST_GOOD'} data-prime-tone={tone}>
      <div className={styles.neuralRing} aria-hidden="true" />
      <div className={styles.neuralRingTwo} aria-hidden="true" />
      <PrimeGlowRing
        value={score}
        label="ARGUS PRIME"
        caption="EDGE / READINESS · NOT PROBABILITY"
        state={upper(prime.hero_state ?? prime.display_state)}
        variant="main"
        toneClass={styles[`tone_${tone}`]}
      >
        {flipToken > 0 && <><i key={`flash-${flipToken}`} className={styles.signalFlourish} aria-hidden="true" /><i key={`ripple-${flipToken}`} className={styles.signalFlourishLarge} aria-hidden="true" /></>}
      </PrimeGlowRing>
    </div>
  )
}

function OseStructureReadout({ timeframe, structure }: { timeframe: '3m' | '5m'; structure: JsonRecord }) {
  const demand = record(structure.demand)
  const supply = record(structure.supply)
  return (
    <div className={styles.oseStructure}>
      <div><span>{timeframe.toUpperCase()} STRUCTURE</span><strong>{upper(structure.state)}</strong><small>{structure.completed_bucket === false ? 'FORMING · EXCLUDED' : 'COMPLETED BUCKET'}</small></div>
      <dl>
        <div><dt>Demand</dt><dd>{numberText(demand.zone_low)}–{numberText(demand.zone_high)} · {upper(demand.status)} · T{numberText(demand.touch_count, 0)}</dd></div>
        <div><dt>Premium</dt><dd>{numberText(structure.premium)}</dd></div>
        <div><dt>Supply</dt><dd>{numberText(supply.zone_low)}–{numberText(supply.zone_high)} · {upper(supply.status)} · T{numberText(supply.touch_count, 0)}</dd></div>
        <div><dt>Lifecycle</dt><dd>D {structure.demand_break ? 'BREAK' : 'HELD'} · S {structure.supply_break ? 'BREAK' : 'HELD'} · {structure.bullish_retest || structure.bearish_retest ? 'RETEST' : 'NO RETEST'}</dd></div>
        <div><dt>Evaluated</dt><dd>{timeText(structure.evaluated_through)}</dd></div>
      </dl>
    </div>
  )
}

function OseContractDetail({ side, contract }: { side: 'CE' | 'PE'; contract: JsonRecord }) {
  const identity = record(contract.contract)
  const composite = record(contract.composite)
  const structures = record(contract.structures)
  const trend = record(contract.trend)
  const window = record(contract.decision_window)
  const transition = record(contract.latest_state_change)
  const agreement = record(contract.engine_agreement)
  const ssi = record(contract.ssi)
  const vob = record(contract.vob)
  const quality = record(contract.quality)
  return (
    <article className={`${styles.oseContract} ${side === 'CE' ? styles.oseCe : styles.osePe}`}>
      <header><div><span>{side} CONTRACT</span><strong>{text(identity.trading_symbol, `${side} IDENTITY UNAVAILABLE`)}</strong><small>{text(identity.security_id, 'SECURITY ID UNAVAILABLE')} · EXP {text(identity.expiry)}</small></div><b>{numberText(contract.premium)}<small> PREMIUM</small></b></header>
      <div className={styles.oseSummary}>
        <span>SSI <b>{scoreText(ssi.score)} / 100 · {upper(ssi.band)}</b></span>
        <span>COMPOSITE <b>{upper(composite.state)}</b></span>
        <span>DECISION WINDOW <b>{upper(window.state)}</b></span>
        <span>ENGINE AGREEMENT <b>{upper(agreement.result ?? agreement.state)}</b></span>
        <span>VOB STRUCTURE <b>{upper(vob.state)} · {numberText(vob.strength, 0)}</b></span>
        <span>TREND ENGINE <b>{upper(trend.state)} · {numberText(trend.strength, 0)}</b></span>
        <span>FRESHNESS <b>{upper(quality.freshness ?? quality.status)}</b></span>
        <span>DATA QUALITY <b>{upper(quality.status)}</b></span>
      </div>
      <div className={styles.oseAxes}><OseStructureReadout timeframe="3m" structure={record(structures['3m'])} /><OseStructureReadout timeframe="5m" structure={record(structures['5m'])} /></div>
      <div className={styles.oseTrend}>
        <span>EMA50 <b>{numberText(trend.ema_50)}</b></span><span>SUPERTREND 10 / 3.4 <b>{numberText(trend.supertrend_value)} · {upper(trend.supertrend_direction)}</b></span><span>TREND ENGINE <b>{upper(trend.state)}</b></span>
      </div>
      <div className={styles.oseTransition}><span>LATEST STATE CHANGE</span><b>{text(transition.summary ?? transition.reason, 'NO TRANSITION RECORDED')}</b><small>{timeText(transition.evaluated_through ?? transition.timestamp)}</small></div>
      <p className={styles.oseCanonicalRead}>{text(vob.reason, 'VOB REASON UNAVAILABLE')} · {text(trend.reason, 'TREND REASON UNAVAILABLE')}</p>
      <details className={styles.oseBreakdown}><summary>SSI contribution lineage</summary><div>{Object.entries(record(contract.score_breakdown)).map(([name, item]) => <span key={name}>{name.replaceAll('_', ' ')} <b>{numberText(record(item).contribution, 2)}</b></span>)}</div></details>
    </article>
  )
}

function OutcomeTile({ label, data, fresh }: { label: string; data: JsonRecord; fresh: boolean }) {
  const score = bounded(data.display_score ?? data.score)
  const toneClass = {
    CALL: styles.outcomeCall,
    PUT: styles.outcomePut,
    HOLD: styles.outcomeHold,
    DECAY: styles.outcomeDecay,
    'BIG MOVE': styles.outcomeBigMove,
    'GAMMA BLAST': styles.outcomeGamma,
    REVERSAL: styles.outcomeReversal,
  }[label]
  return (
    <article className={styles.outcomeTile} data-outcome-freshness={fresh ? 'LIVE' : 'LAST_GOOD'} tabIndex={0}>
      <PrimeGlowRing
        value={score}
        label={label}
        caption=""
        variant="mini"
        toneClass={toneClass}
      />
    </article>
  )
}

function canonicalOiState(leg: JsonRecord): string | null {
  const quadrant = upper(leg.flow_quadrant ?? leg.probable_flow).replaceAll(' ', '_')
  if (/UNAVAILABLE|STALE|INCONSISTENT|MIXED|WEAK|CONTRADICT/.test(quadrant)) return null
  if (/SHORT_COVERING/.test(quadrant)) return 'SHORT COVERING'
  if (/LONG_UNWINDING/.test(quadrant)) return 'LONG UNWINDING'
  if (/LONG_BUILDUP|BUYING/.test(quadrant)) return 'LONG BUILDUP'
  if (/SHORT_BUILDUP|WRITING/.test(quadrant)) return 'SHORT BUILDUP'
  return null
}

function canonicalOiTone(state: string, side: 'CE' | 'PE') {
  const bullish = side === 'CE'
    ? state === 'LONG BUILDUP' || state === 'SHORT COVERING'
    : state === 'LONG UNWINDING' || state === 'SHORT BUILDUP'
  return bullish ? 'green' : 'red'
}

function StrikeFlowPill({ state, side }: { state: string | null; side: 'CE' | 'PE' }) {
  const tone = state ? canonicalOiTone(state, side) : 'slate'
  return <strong className={`${styles.flowPill} ${styles[`flow_${tone}`]}`}>{state ?? 'OI STATE UNKNOWN'}</strong>
}

function ProbableFlowHelper({ value, arrow }: { value: unknown; arrow: unknown }) {
  const flow = upper(value).replaceAll('_', ' ')
  const unavailable = /UNAVAILABLE|STALE|INCONSISTENT|MIXED|WEAK|CONTRADICT/.test(flow)
  return (
    <small className={styles.probableFlowHelper}>
      <span>{text(arrow, '→')} · PROBABLE FLOW:</span>
      <b data-unavailable={unavailable ? 'true' : 'false'}>{flow}</b>
    </small>
  )
}

function DecisionRails({
  duel,
  flow,
  participation,
  marketState,
  marketClosedAt,
  fresh,
  marketSentiment,
  marketBias,
  dominance,
  participationVerdict,
}: {
  duel: JsonRecord
  flow: JsonRecord
  participation: JsonRecord
  marketState: unknown
  marketClosedAt: unknown
  fresh: boolean
  marketSentiment: unknown
  marketBias: unknown
  dominance: unknown
  participationVerdict: unknown
}) {
  const delta = finite(duel.delta)
  const structureMarker = delta === null ? 50 : Math.max(4, Math.min(96, 50 + delta / 2))
  const canonicalFlowMarker = finite(flow.balance_marker)
  const flowMarker = Math.max(4, Math.min(96, canonicalFlowMarker ?? 50))
  const edge = record(flow.edge)
  const priorAvailable = flow.prior_snapshot_available === true
  const baseline = record(flow.baseline)
  const canonicalDominance = record(participation.values)
  const fallbackDominance = record(dominance)
  const dominanceValues = Object.keys(canonicalDominance).length
    ? canonicalDominance
    : fallbackDominance
  const writerShare = bounded(dominanceValues.writer_dominance_percentage)
  const buyerShare = bounded(dominanceValues.buyer_dominance_percentage)
  const structureState: RailState = fresh && delta !== null ? 'LIVE' : delta === null ? 'UNAVAILABLE' : 'HELD'
  const flowStatus = upper(flow.status)
  const participationStatus = upper(participation.status)
  // This is an official-session presentation state only. Per-engine source
  // freshness remains the sole live-market status authority.
  const marketClosed = upper(marketState) === 'CLOSED'
  const flowState: RailState = marketClosed && canonicalFlowMarker !== null
    ? 'HELD'
    : canonicalFlowMarker !== null && /LIVE|FRESH|AVAILABLE/.test(flowStatus)
    ? 'LIVE'
    : canonicalFlowMarker === null ? 'UNAVAILABLE' : 'STALE'
  // OSE exposes baseline provenance, not an authoritative baseline score. Never draw a made-up fill.
  const baselineAvailable = writerShare !== null && buyerShare !== null
  const baselineReason = baselineAvailable
    ? 'CANONICAL ATM±5 DOMINANCE'
    : /UNAVAILABLE/.test(upper(baseline.open_interest_change))
      ? 'WAITING FOR SESSION BASELINE'
      : 'SOURCE UNAVAILABLE'
  const participationLabel = baselineAvailable
    ? upper(participationVerdict, 'PARTICIPATION VERDICT UNAVAILABLE').replaceAll('_', ' ')
    : baselineReason
  const flowDelta = finite(edge.delta)
  const flowDifferential = flowDelta === null
    ? 'FLOW DIFFERENTIAL UNAVAILABLE'
    : flowDelta === 0
      ? 'BALANCED'
      : `${upper(edge.side)} +${Math.abs(flowDelta)}`
  const baselineState: RailState = marketClosed && baselineAvailable
    ? 'HELD'
    : baselineAvailable && /LIVE|FRESH|AVAILABLE/.test(participationStatus)
      ? 'LIVE'
      : baselineAvailable ? 'STALE' : 'UNAVAILABLE'
  const flowLastValid = istTimeText(flow.source_timestamp ?? flow.evaluated_at ?? flow.calculated_at ?? marketClosedAt)
  const baselineLastValid = istTimeText(participation.source_timestamp ?? participation.receipt_timestamp ?? participation.calculated_at ?? marketClosedAt)
  const flowStatusLabel = marketClosed && canonicalFlowMarker !== null
    ? `MARKET CLOSED · LAST VALID ${flowLastValid ?? 'SNAPSHOT'}`
    : flowStatus
  const baselineStatusLabel = marketClosed && baselineAvailable
    ? `MARKET CLOSED · LAST VALID ${baselineLastValid ?? 'SNAPSHOT'}`
    : participationStatus
  const sentiment = upper(marketSentiment)
  const bias = upper(marketBias)
  return (
    <Panel title="Canonical Decision Rails" eyebrow="Structure · live flow · baseline truth">
      <div className={styles.decisionRails}>
        <div className={`${styles.decisionRail} ${styles.rowCard}`} tabIndex={0}>
          <header><span>OPTIONS STRUCTURE</span><strong className={structureState === 'LIVE' ? styles.kineticValue : ''}>{upper(duel.state)}</strong><b>{text(duel.label)}</b></header>
          <LiquidGlassRail position={delta === null ? null : structureMarker} state={structureState} accent={structureMarker >= 50 ? 'cyan' : 'amber'} bipolar ariaLabel={`Options Structure ${upper(duel.state)}`} />
          <footer><span>PUT STRUCTURE</span><span>PE {scoreText(duel.pe_score)} · CE {scoreText(duel.ce_score)}</span><span>CALL STRUCTURE</span></footer>
        </div>
        <div className={`${styles.decisionRail} ${styles.rowCard}`} tabIndex={0}>
          <header><span>ARGUS LIVE OPTION FLOW</span><strong>{marketClosed ? flowStatusLabel : text(edge.label ?? edge.state)}</strong><b>{flowDifferential}</b></header>
          <LiquidGlassRail position={canonicalFlowMarker === null ? null : flowMarker} state={flowState} accent={flowState === 'LIVE' ? (flowMarker <= 50 ? 'cyan' : 'amber') : 'magenta'} bipolar sweepDuration="4.4s" sweepDelay="1.2s" animationMode="frozen" staleMotion="ping" ariaLabel={`Argus Live Option Flow ${flowStatusLabel}`} />
          <footer><span>CALL FLOW {scoreText(record(flow.call).score)}</span><span>{flowStatusLabel}</span><span>PUT FLOW {scoreText(record(flow.put).score)}</span></footer>
        </div>
        <div className={`${styles.decisionRail} ${styles.rowCard} ${styles.rowCardBaseline}`} tabIndex={0}>
          <header><span>INTRADAY BASELINE</span><strong className={baselineState === 'LIVE' ? styles.kineticValue : ''}>{baselineAvailable ? `BUYERS ${numberText(buyerShare, 0)}% · WRITERS ${numberText(writerShare, 0)}%` : baselineReason}</strong><b>{participationLabel}</b></header>
          <div className={styles.baselineMeta}><span>MARKET SENTIMENT <b>{sentiment}</b></span><span>MARKET BIAS <b>{bias}</b></span></div>
          <LiquidGlassRail position={buyerShare} priorPosition={priorAvailable ? buyerShare : null} state={baselineState} accent="violet" sweepDuration="2.1s" ariaLabel={`Intraday Baseline buyers ${numberText(buyerShare, 0)} percent; writers ${numberText(writerShare, 0)} percent; market sentiment ${sentiment}; market bias ${bias}`} />
          <footer><span>OI · {upper(baseline.open_interest_change)}</span><span>{baselineStatusLabel}</span><span>VOLUME · {upper(baseline.volume_acceleration)}</span></footer>
        </div>
      </div>
    </Panel>
  )
}

function Lifecycle({ contract, label }: { contract: JsonRecord; label: string }) {
  const structures = record(contract.structures)
  const structure = record(structures['3m'])
  const demand = record(structure.demand)
  const supply = record(structure.supply)
  const lifecycleText = `${upper(demand.status, '')} ${upper(supply.status, '')}`
  const nodes = [
    ['TOUCH', /TEST|TOUCH/.test(lifecycleText)],
    ['BREAK', /BROKEN/.test(lifecycleText)],
    ['RETEST', Boolean(structure.bullish_retest || structure.bearish_retest)],
  ] as const
  return (
    <div className={styles.lifecycle}>
      <div><span>{label}</span><strong>{upper(contract.composite && record(contract.composite).state)}</strong></div>
      <ol>{nodes.map(([name, active]) => <li key={name} className={active ? styles.lifecycleActive : ''}><i />{name}</li>)}</ol>
    </div>
  )
}

function Radar({ scores }: { scores: [string, number | null][] }) {
  const complete = scores.every(([, value]) => value !== null)
  const points = complete
    ? scores.map(([, value], index) => {
        const angle = (-Math.PI / 2) + index * (Math.PI * 2 / scores.length)
        const radius = 18 + (value ?? 0) * 0.54
        return `${75 + Math.cos(angle) * radius},${75 + Math.sin(angle) * radius}`
      }).join(' ')
    : ''
  return (
    <div className={styles.radar}>
      <svg viewBox="0 0 150 150" role="img" aria-label={complete ? 'Canonical risk shape' : 'Risk shape unavailable due to missing dimensions'}>
        {[24, 42, 60].map((radius) => <circle key={radius} cx="75" cy="75" r={radius} />)}
        {scores.map(([,], index) => {
          const angle = (-Math.PI / 2) + index * (Math.PI * 2 / scores.length)
          return <line key={index} x1="75" y1="75" x2={75 + Math.cos(angle) * 60} y2={75 + Math.sin(angle) * 60} />
        })}
        {complete && <polygon points={points} />}
      </svg>
      {!complete && <span>INCOMPLETE EVIDENCE · NO ZERO IMPUTATION</span>}
    </div>
  )
}

function Spine({ rows, selectedStrike }: { rows: unknown[]; selectedStrike: number | null }) {
  return (
    <div className={styles.spine} role="table" aria-label="ARGUS enhanced strike spine">
      <div className={styles.spineHeader} role="row"><span>CE probable flow</span><span>OI rate / accel / load</span><span>Strike</span><span>OI rate / accel / load</span><span>PE probable flow</span></div>
      {rows.map((item, index) => {
        const row = record(item)
        const ce = record(row.CE)
        const pe = record(row.PE)
        const strike = finite(row.strike)
        const selected = strike !== null && strike === selectedStrike
        const ceHeat = list(ce.heat_history).map(finite).filter((value): value is number => value !== null).slice(-5)
        const peHeat = list(pe.heat_history).map(finite).filter((value): value is number => value !== null).slice(-5)
        const ceOiState = canonicalOiState(ce)
        const peOiState = canonicalOiState(pe)
        const heatCells = (values: number[], side: 'CE' | 'PE') => Array.from({ length: 5 }, (_, cell) => {
          const value = values[cell]
          const max = values.length ? Math.max(...values.map(Math.abs), 1) : 1
          return <i key={`${side}-${cell}`} data-filled={value === undefined ? 'false' : 'true'} style={value === undefined ? undefined : { '--heat': Math.max(.22, Math.abs(value) / max) } as CSSProperties} />
        })
        const loadBlocks = (value: unknown, side: 'CE' | 'PE') => {
          const normalized = bounded(value)
          const lit = normalized === null ? 0 : Math.round(normalized / 10)
          return <div className={`${styles.spineLoad} ${side === 'CE' ? styles.spineLoadCe : styles.spineLoadPe}`}>{Array.from({ length: 10 }, (_, cell) => <i key={`${side}-load-${cell}`} data-lit={cell < lit ? 'true' : 'false'} />)}</div>
        }
        return (
          <div key={`${strike ?? 'unknown'}-${index}`} className={`${styles.spineRow} ${selected ? styles.spineSelected : ''}`} role="row" tabIndex={0}>
            <div><div className={styles.flowMetaLine}><StrikeFlowPill state={ceOiState} side="CE" /><ProbableFlowHelper arrow={ce.velocity_arrow} value={ce.probable_flow} /></div><div className={`${styles.heatHistory} ${styles.heatCe}`} aria-label={ceHeat.length ? 'CE authoritative heat history' : 'CE heat history unavailable'}>{heatCells(ceHeat, 'CE')}</div></div>
            <div className={styles.ceMetrics}><b title="OI rate">{oiMetricText(ce.oi_velocity, 0)}</b><span title="OI acceleration">{oiMetricText(ce.oi_acceleration, 0)}</span><em title="Structural load">{oiMetricText(ce.load_intensity, 0)}</em>{loadBlocks(ce.load_intensity, 'CE')}</div>
            <div className={styles.strikeCell}>{selected && <small>FOCUS</small>}<strong>{numberText(strike, 0)}</strong><span>{upper(row.structural_role ?? row.wall_role, 'OBSERVATION')}</span></div>
            <div className={styles.peMetrics}><b title="OI rate">{oiMetricText(pe.oi_velocity, 0)}</b><span title="OI acceleration">{oiMetricText(pe.oi_acceleration, 0)}</span><em title="Structural load">{oiMetricText(pe.load_intensity, 0)}</em>{loadBlocks(pe.load_intensity, 'PE')}</div>
            <div><div className={styles.flowMetaLine}><StrikeFlowPill state={peOiState} side="PE" /><ProbableFlowHelper arrow={pe.velocity_arrow} value={pe.probable_flow} /></div><div className={`${styles.heatHistory} ${styles.heatPe}`} aria-label={peHeat.length ? 'PE authoritative heat history' : 'PE heat history unavailable'}>{heatCells(peHeat, 'PE')}</div></div>
          </div>
        )
      })}
    </div>
  )
}

export function OracleArgusPrime01C({ tactical, optionsStructure, vob, provider, marketState, marketClosedAt, marketSentiment, marketBias, dominance, participationVerdict, visualFixture }: OracleArgusPrime01CProps) {
  const fixtureEnabled = process.env.NODE_ENV !== 'production' && Boolean(visualFixture)
  const fixture = fixtureEnabled ? buildOracleArgusPrime01CVisualFixture(visualFixture ?? 'red') : null
  const activeProvider = fixture?.provider ?? provider
  const tacticalData = record(fixture?.tactical ?? tactical)
  const prime = record(tacticalData.argus_prime)
  const truth = record(prime.data_truth)
  const outcomes = record(prime.outcome_engines)
  const structureData = record(fixture?.optionsStructure ?? optionsStructure)
  const flow = structureData.option_flow ? record(structureData.option_flow) : {}
  const duel = record(structureData.duel)
  const contracts = record(structureData.contracts)
  const ce = record(contracts.CE)
  const pe = record(contracts.PE)
  const rollover = record(structureData.rollover)
  const oseQuality = record(structureData.data_quality)
  const structuralRead = record(structureData.structural_read)
  const participation = record(structureData.participation_baseline)
  const stack = record(prime.best_strike_stack)
  const pcr = record(prime.live_pcr)
  const wall = record(prime.wall_outcome)
  const gamma = record(prime.gamma_regime)
  const futures = record(prime.futures_confirmation)
  const blast = record(prime.expiry_gamma_blast)
  const tacticalSummary = record(prime.tactical_summary)
  const smartFlow = record(prime.smart_money_flow)
  const pressurePrice = record(prime.pressure_to_price)
  const rawScore = finite(prime.raw_score)
  const smoothedScore = finite(prime.smoothed_score)
  const displayedScore = bounded(prime.display_score ?? prime.argus_prime_score)
  const initialFixtureScore = visualFixture === '49' ? 49 : visualFixture === '50' ? 50 : visualFixture === 'green' || visualFixture === 'reduced' || visualFixture === 'stale' ? 72 : visualFixture === 'unavailable' ? null : fixtureEnabled ? 29 : null
  const [fixtureScore, setFixtureScore] = useState<number | null>(initialFixtureScore)
  const score = fixtureEnabled ? (fixtureScore ?? displayedScore) : displayedScore
  const priorScore = useRef<number | null>(null)
  const [flipToken, setFlipToken] = useState(0)
  const [flipCount, setFlipCount] = useState(0)
  useEffect(() => {
    if (priorScore.current !== null && score !== null && priorScore.current < 50 && score >= 50) {
      setFlipToken((value) => value + 1)
      setFlipCount((value) => value + 1)
    }
    priorScore.current = score
  }, [score])

  const chainSummary = list(prime.chain_summary).map((item) => text(item, '')).filter(Boolean)
  const why = list(prime.why).map((item) => text(item, '')).filter(Boolean)
  const summaryReasons = list(tacticalSummary.reasons).map((item) => text(item, '')).filter(Boolean)
  const spineRows = list(prime.strike_spine)
  const freshnessState = upper(truth.state ?? activeProvider.state)
  const unavailableFixture = fixtureEnabled && visualFixture === 'unavailable'
  const selectedStrike = unavailableFixture ? null : finite(stack.strongest_structural_strike ?? stack.strike)
  const sourceAge = finite(truth.age_seconds ?? prime.source_age_seconds)
  const fixtureLabel = fixtureEnabled ? `TEST FIXTURE · ${upper(visualFixture)}` : null
  const riskScores: [string, number | null][] = [
    ['Decay', bounded(record(outcomes.decay_risk).display_score)],
    ['Reversal', bounded(record(outcomes.reversal).display_score)],
    ['Gamma', bounded(record(outcomes.gamma_blast).display_score)],
    ['Move', bounded(record(outcomes.big_move).display_score)],
    ['Flow', bounded(smartFlow.score)],
    ['Pressure', bounded(pressurePrice.score)],
  ]
  const callFlow = record(flow.call)
  const putFlow = record(flow.put)
  const officialMarketClosed = upper(structureData.market_state ?? marketState) === 'CLOSED'
  const hasFlowSnapshot = bounded(callFlow.score) !== null || bounded(putFlow.score) !== null
  const flowLastValid = istTimeText(flow.source_timestamp ?? flow.evaluated_at ?? flow.calculated_at ?? marketClosedAt)
  const flowPresentationLabel = officialMarketClosed && hasFlowSnapshot
    ? `MARKET CLOSED · LAST VALID ${flowLastValid ?? 'SNAPSHOT'}`
    : upper(record(flow.edge).label ?? record(flow.edge).state)
  const flowPresentationSummary = officialMarketClosed && hasFlowSnapshot
    ? 'Last valid market-session participation snapshot retained'
    : text(record(flow.edge).summary)
  const vobData = record(fixture?.vob ?? vob)
  const nearestSupport = record(vobData.nearest_support)
  const nearestResistance = record(vobData.nearest_resistance)
  const sourceTimestamp = truth.source_timestamp ?? prime.source_timestamp ?? activeProvider.sourceTimestamp
  const freshnessPill = freshnessState === 'LIVE' || freshnessState === 'FRESH'
    ? 'LIVE'
    : freshnessState === 'LAST_GOOD' || freshnessState === 'HELD'
      ? 'HELD'
      : freshnessState === 'NO_DATA' || freshnessState === 'UNAVAILABLE'
        ? 'NO_DATA'
        : 'STALE'
  const isFresh = freshnessPill === 'LIVE'
  const reducedMotionFixture = fixtureEnabled && visualFixture === 'reduced'
  const canonicalDirection = upper(tacticalSummary.directional_posture ?? prime.direction, 'HOLD')
  const primeTone = primeToneFor(canonicalDirection, isFresh)

  return (
    <section className={`${styles.deck} ${styles[`tone_${primeTone}`]}`} data-oracle-argus-01c data-snapshot-id={text(truth.snapshot_id ?? prime.snapshot_id ?? activeProvider.snapshotId)} data-freshness-active={isFresh ? 'true' : 'false'} data-prime-direction={canonicalDirection} data-prime-tone={primeTone} data-reduced-motion-test={reducedMotionFixture ? 'true' : 'false'}>
      <div className={styles.scanline} aria-hidden="true" />
      <svg className={styles.deckBackdrop} viewBox="0 0 380 380" aria-hidden="true">
        <circle cx="190" cy="190" r="180" />
        <circle cx="190" cy="190" r="138" />
      </svg>
      <header className={styles.deckHeader}>
        <div><span>01C / ORACLE SHARED CANONICAL SURFACE</span><h2>ARGUS PRIME</h2><p>Exact shared projection · presentation only · execution influence zero</p></div>
        <div className={styles.truthCluster}>
          {fixtureLabel && <b className={styles.testBadge}>{fixtureLabel}</b>}
          <div className={styles.statePills}>{['NO_DATA', 'HELD', 'LIVE', 'STALE'].map((state) => <span key={state} data-active={freshnessPill === state ? 'true' : 'false'}>{state}</span>)}</div>
          <b>{freshnessState}</b><span>{sourceAge === null ? 'AGE UNAVAILABLE' : `AGE ${numberText(sourceAge, 1)}S`}</span><small>SNAPSHOT {text(truth.snapshot_id ?? prime.snapshot_id ?? activeProvider.snapshotId)}</small>
        </div>
      </header>

      <div className={styles.instrumentStrip}>
        <div><span>UNDERLYING</span><strong>{upper(tacticalData.symbol ?? activeProvider.underlying)}</strong></div>
        <div><span>EXPIRY</span><strong>{text(tacticalData.expiry ?? activeProvider.expiry)}</strong></div>
        <div><span>OBSERVED</span><strong>{timeText(sourceTimestamp)}</strong></div>
        <div><span>FORMULA</span><strong>{text(truth.formula_version ?? prime.score_formula_version)}</strong></div>
        <div><span>EVIDENCE</span><strong>{numberText(truth.evidence_coverage ?? prime.evidence_coverage, 0)}%</strong></div>
      </div>

      <div className={styles.structureGrid}>
        <Panel title="Options Structure" eyebrow="CE / PE SSI · canonical OSE" className={styles.structurePanel}>
          <div className={styles.ssiGrid}><SsiDial side="CE" contract={ce} fresh={isFresh} /><SsiDial side="PE" contract={pe} fresh={isFresh} /></div>
        </Panel>
        <Panel title="ARGUS Live Option Flow" eyebrow="Participation quality · not direction alone" tone="cyan">
          <div className={styles.flowGrid}><FlowMeter label="CALL FLOW" data={callFlow} /><FlowMeter label="PUT FLOW" data={putFlow} /></div>
          <div className={styles.flowVerdict}><strong>{flowPresentationLabel}</strong><span>{flowPresentationSummary}</span></div>
        </Panel>
      </div>

      <DecisionRails duel={duel} flow={flow} participation={participation} marketState={structureData.market_state ?? marketState} marketClosedAt={marketClosedAt} fresh={isFresh} marketSentiment={marketSentiment} marketBias={marketBias} dominance={dominance} participationVerdict={participationVerdict} />

      <Panel title="Enhanced Strike Spine" eyebrow="Probable flow · velocity · acceleration · structural load">
        <Spine rows={spineRows} selectedStrike={selectedStrike} />
      </Panel>

      <div className={styles.commandGrid}>
        <Panel title="Tactical Summary" eyebrow="One canonical interpretation" tone={isFresh ? toneFor(tacticalSummary.directional_posture) : 'slate'}>
          <div className={styles.verdict}><span>{upper(tacticalSummary.state)}</span><strong>{upper(tacticalSummary.title ?? prime.hero_state)}</strong><p>{text(prime.action)}</p></div>
          <ul className={styles.reasonList}>{summaryReasons.slice(0, 5).map((reason) => <li key={reason}>{reason}</li>)}</ul>
          <div className={styles.chainSummary}><span>UPSTOX OPTION CHAIN</span>{chainSummary.slice(0, 5).map((line) => <p key={line}>{line}</p>)}</div>
        </Panel>
        <Panel title="Prime Decision Hub" eyebrow="Raw → smoothed → displayed" className={styles.hubPanel} tone={primeTone}>
          <PrimeHub prime={prime} fixtureScore={fixtureEnabled ? fixtureScore : null} flipToken={flipToken} flipCount={flipCount} fresh={isFresh} tone={primeTone} />
          <div className={styles.pipeline}><span>RAW <b>{scoreText(rawScore)}</b></span><i /><span>SMOOTHED <b>{scoreText(smoothedScore)}</b></span><i /><span>DISPLAY <b>{scoreText(score)}</b></span></div>
          {fixtureEnabled && <div className={styles.fixtureControls}><button onClick={() => setFixtureScore(49)}>49</button><button onClick={() => setFixtureScore(50)}>50</button><button onClick={() => setFixtureScore(51)}>51</button></div>}
        </Panel>
      </div>

      <Panel title="Outcome Intelligence" eyebrow="Seven canonical edge / readiness engines">
        <div className={styles.outcomeGrid}>
          {[
            ['CALL', 'call_edge'], ['PUT', 'put_edge'], ['HOLD', 'hold_edge'], ['DECAY', 'decay_risk'],
            ['BIG MOVE', 'big_move'], ['GAMMA BLAST', 'gamma_blast'], ['REVERSAL', 'reversal'],
          ].map(([label, key]) => <OutcomeTile key={key} label={label} data={record(outcomes[key])} fresh={isFresh} />)}
        </div>
      </Panel>

      <div className={styles.engineGrid}>
        <Panel title="Money / Wall / Gamma" eyebrow="Canonical engine outcomes">
          <div className={styles.capacityGrid}>
            <CapacityMeter label="SMART FLOW" score={smartFlow.score} state={smartFlow.label} fresh={isFresh} />
            <CapacityMeter label="PRESSURE → PRICE" score={pressurePrice.score} state={pressurePrice.state} fresh={isFresh} />
            <CapacityMeter label="WALL" score={wall.score} state={wall.outcome} fresh={isFresh} />
            <CapacityMeter label="GAMMA" score={gamma.score} state={gamma.state} fresh={isFresh} />
            <CapacityMeter label="FUTURES CONFIRMATION" score={futures.score} state={futures.state} fresh={isFresh} />
          </div>
        </Panel>
        <Panel title="Live PCR" eyebrow="Direction of change · never a trade signal" tone={isFresh ? toneFor(pcr.trend) : 'slate'}>
          <div className={styles.pcrReadout}><strong>{numberText(pcr.oi_pcr, 3)}</strong><span>{directionArrow(pcr.trend)} {upper(pcr.trend)}</span></div>
          <LiquidGlassRail position={finite(pcr.oi_pcr) === null ? null : Math.max(0, Math.min(100, (finite(pcr.oi_pcr) ?? 0) * 100))} state={isFresh && finite(pcr.oi_pcr) !== null ? 'LIVE' : finite(pcr.oi_pcr) === null ? 'UNAVAILABLE' : 'STALE'} accent="violet" ariaLabel={`OI PCR ${numberText(pcr.oi_pcr, 3)}`} />
          <dl className={styles.definitionList}>
            <div><dt>1 minute</dt><dd>{pcr.change_1m_state === 'AVAILABLE' ? numberText(pcr.change_1m, 4) : upper(pcr.change_1m_state)}</dd></div>
            <div><dt>5 minute</dt><dd>{pcr.change_5m_state === 'AVAILABLE' ? numberText(pcr.change_5m, 4) : upper(pcr.change_5m_state)}</dd></div>
            <div><dt>Percentile</dt><dd>{pcr.session_percentile_state === 'AVAILABLE' ? `${numberText(pcr.session_percentile, 0)}%` : upper(pcr.session_percentile_state)}</dd></div>
            <div><dt>Freshness</dt><dd>{upper(pcr.freshness)} · {numberText(pcr.source_age_seconds, 1)}S</dd></div>
          </dl>
        </Panel>
      </div>

      <Panel title="Strongest Structural Strike" eyebrow="Focus is not an authorized best strike" tone={isFresh ? toneFor(stack.direction) : 'slate'}>
        <div className={styles.stackHeader}><div><span>{stack.authorized_contract ? 'AUTHORIZED BEST STRIKE' : 'STRUCTURAL FOCUS'}</span><strong>{selectedStrike === null ? 'NO STRIKE AUTHORIZED' : numberText(selectedStrike, 0)}</strong><p>{upper(stack.state)} · {text(stack.authorization_reason)}</p></div><div className={styles.stackScore}><strong>{scoreText(stack.score)}</strong><span>/100 STRUCTURAL</span></div></div>
        <div className={styles.stackFlows}>
          {[['PRIMARY FLOW', record(stack.primary_flow)], ['DEFENCE FLOW', record(stack.defence_flow)]].map(([label, payload]) => {
            const data = payload as JsonRecord
            return <div key={label as string}><span>{label as string}</span><strong>{upper(data.label)}</strong><p>{text(data.arrow, '→')} {numberText(data.acceleration, 0)} ACCEL · {numberText(data.load, 0)} LOAD</p></div>
          })}
          <div><span>OI MIGRATION</span><strong>{upper(record(stack.migration).state)}</strong><p>{text(record(stack.migration).label)} · {list(record(stack.migration).path).map((value) => numberText(value, 0)).join(' → ') || 'NO CLEAN MIGRATION'}</p></div>
        </div>
        <details className={styles.lineage}><summary>Stack contribution lineage</summary><div>{Object.entries(record(stack.score_contributions)).map(([key, value]) => <p key={key}><span>{key.replaceAll('_', ' ')}</span><b>{numberText(record(value).contribution, 2)} / {numberText((finite(record(value).weight) ?? 0) * 100, 0)}</b></p>)}</div></details>
      </Panel>

      <Panel title="Expiry Gamma Blast" eyebrow="Specialist overlay · not a normal-trade gate" tone={isFresh ? 'amber' : 'slate'}>
        <div className={styles.blastGrid}>
          <div className={styles.blastState}><span>{upper(blast.phase)}</span><strong>{scoreText(blast.score)}</strong><p>{upper(blast.direction)} · CHASE RISK {upper(blast.chase_risk)}</p></div>
          <div className={styles.blastMeters}>{Object.entries(record(blast.components)).map(([key, value]) => <CapacityMeter key={key} label={key.replaceAll('_', ' ').toUpperCase()} score={value} state={finite(value) === null ? 'UNAVAILABLE' : 'AVAILABLE'} fresh={isFresh} />)}</div>
        </div>
      </Panel>

      <div className={styles.evidenceGrid}>
        <Panel title="VOB / Trend Lifecycle" eyebrow="Touch · break · retest" tone={isFresh ? 'cyan' : 'slate'}><Lifecycle contract={ce} label="CE STRUCTURE" /><Lifecycle contract={pe} label="PE STRUCTURE" /><div className={styles.vobLevels}><span>SPOT VOB SUPPORT <b>{numberText(nearestSupport.zone_low)}–{numberText(nearestSupport.zone_high)}</b></span><span>SPOT VOB RESISTANCE <b>{numberText(nearestResistance.zone_low)}–{numberText(nearestResistance.zone_high)}</b></span></div></Panel>
        <Panel title="Risk Shape" eyebrow="Missing dimensions stay unavailable"><Radar scores={riskScores} /></Panel>
        <Panel title="Why / Canonical Read" eyebrow="Backend-provided explanation"><ul className={styles.reasonList}>{why.slice(0, 6).map((reason) => <li key={reason}>{reason}</li>)}</ul><p className={styles.canonicalRead}>{text(activeProvider.canonicalRead)}</p><dl className={styles.definitionList}><div><dt>Trigger</dt><dd>{text(prime.trigger)}</dd></div><div><dt>Invalidation</dt><dd>{text(prime.invalidation_text ?? prime.invalidation)}</dd></div><div><dt>Contract</dt><dd>{text(prime.recommended_contract, 'NO AUTHORIZED CONTRACT')}</dd></div><div><dt>Retest</dt><dd>{upper(prime.retest_status)}</dd></div></dl></Panel>
      </div>

      <details className={styles.quantDrawer}><summary>Full Quant Evidence</summary><pre>{JSON.stringify({ score_breakdown: prime.score_breakdown, stack: stack.score_contributions, data_truth: truth }, null, 2)}</pre></details>

      <Panel title="Options Structure Engine" eyebrow="Full canonical CE / PE contract intelligence">
        <div className={styles.oseCommandStrip}>
          <span>NIFTY <b>{numberText(structureData.spot)}</b></span>
          <span>ANCHOR <b>{numberText(structureData.anchor, 0)}</b></span>
          <span>EXPIRY <b>{text(structureData.expiry)}</b></span>
          <span>RUNTIME <b>{upper(structureData.runtime ?? structureData.status)}</b></span>
          <span>ROLLOVER <b>{upper(rollover.state)}</b></span>
          <span>QUALITY <b>{upper(oseQuality.status ?? structureData.source_freshness)}</b></span>
        </div>
        <div className={styles.oseStructuralRead}><strong>{text(structuralRead.headline, 'STRUCTURAL READ UNAVAILABLE')}</strong><span>{list(structuralRead.lines).slice(0, 2).map((line) => text(line)).join(' · ') || text(structureData.reason)}</span></div>
        <div className={styles.oseContractGrid}><OseContractDetail side="CE" contract={ce} /><OseContractDetail side="PE" contract={pe} /></div>
      </Panel>
    </section>
  )
}
