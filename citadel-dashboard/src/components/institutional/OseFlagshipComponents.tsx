'use client'

import type { CSSProperties } from 'react'
import { useId } from 'react'
import styles from './OptionsStructurePanel.module.css'
import {
  energyDashOffset,
  precisionArcPath,
  precisionTick,
  precisionWheelNeedle,
  trendInstrumentNeedle,
  wheelPosition,
  type OseWheelState,
} from './oseVisualGeometry'

type DirectionState = OseWheelState

const stateClass = (state: string) => {
  const value = state.toUpperCase()
  if (value.includes('BULLISH') || value.includes('LIVE') || value.includes('ROOM')) return styles.positive
  if (value.includes('BEARISH') || value.includes('CONFLICT') || value.includes('POOR')) return styles.negative
  if (value.includes('STALE') || value.includes('NEAR') || value.includes('TRANSITION')) return styles.warning
  return styles.neutral
}

const formatTime = (value: string | null | undefined) => value
  ? new Date(value).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' }).toUpperCase()
  : 'Not reported'

const instrumentSegments = [
  { range: [3, 18], state: 'ULTRA BEARISH', className: styles.wheelUltraBear },
  { range: [22, 39], state: 'BEARISH', className: styles.wheelBear },
  { range: [43, 57], state: 'NEUTRAL', className: styles.wheelNeutral },
  { range: [61, 78], state: 'BULLISH', className: styles.wheelBull },
  { range: [82, 97], state: 'ULTRA BULLISH', className: styles.wheelUltraBull },
]

interface InstrumentProps {
  state: DirectionState
  score: number | null
  reason: string
  evaluated?: string | null
  live: boolean
}

export function VobPrecisionWheel({ state, score, reason, evaluated, live }: InstrumentProps) {
  const instance = useId().replaceAll(':', '')
  const glowId = `ose-vob-glow-${instance}`
  const gradientId = `ose-vob-structure-${instance}`
  const needle = precisionWheelNeedle(state)
  const position = wheelPosition(state)
  const active = instrumentSegments.find((segment) => position >= segment.range[0] && position <= segment.range[1])
  return <section className={`${styles.instrument} ${styles.vobInstrument} ${live ? styles.instrumentLive : styles.instrumentStale}`} data-wheel-kind="VOB" data-state={state} data-wheel-position={position} data-animation-state="STATIC">
    <header><span>VOB STRUCTURE</span><small>{formatTime(evaluated)}</small></header>
    <svg className={styles.vobSvg} viewBox="0 0 240 150" preserveAspectRatio="xMidYMid meet" role="img" aria-label={`VOB Structure: ${state}, structural score ${score ?? 'not reported'}`}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#7257ff" /><stop offset=".5" stopColor="#4f83d8" /><stop offset="1" stopColor="#37c99a" />
        </linearGradient>
        <filter id={glowId} x="-40%" y="-50%" width="180%" height="220%">
          <feGaussianBlur stdDeviation="3.2" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <path className={styles.vobVignette} d="M15 126 Q120 54 225 126 L225 145 L15 145 Z" />
      <path data-arc-layer="outer" className={styles.vobDepthOuter} d={precisionArcPath(1, 99, 106)} stroke={`url(#${gradientId})`} />
      <path data-arc-layer="tracking" className={styles.vobDepthTracking} d={precisionArcPath(3, 97, 91)} stroke={`url(#${gradientId})`} />
      <path data-arc-layer="reference" className={styles.vobDepthReference} d={precisionArcPath(5, 95, 76)} stroke={`url(#${gradientId})`} />
      {Array.from({ length: 21 }, (_, index) => index * 5).map((tick) => {
        const point = precisionTick(tick, tick % 25 === 0)
        return <line key={tick} className={`${styles.vobTick} ${tick % 25 === 0 ? styles.vobTickMajor : ''}`} x1={point.x1} y1={point.y1} x2={point.x2} y2={point.y2} />
      })}
      {instrumentSegments.map((segment) => <path key={segment.state} className={`${styles.vobStateArc} ${segment.className}`} d={precisionArcPath(segment.range[0], segment.range[1], 101)} />)}
      {active ? <>
        <path className={`${styles.vobActiveHalo} ${active.className}`} d={precisionArcPath(active.range[0], active.range[1], 101)} filter={`url(#${glowId})`} />
        <path className={`${styles.vobActiveArc} ${active.className}`} d={precisionArcPath(active.range[0], active.range[1], 101)} />
      </> : null}
      <line className={styles.instrumentNeedle} x1="120" y1="124" x2={needle.x} y2={needle.y} />
      <circle className={styles.instrumentHubHalo} cx="120" cy="124" r="8" />
      <circle className={styles.instrumentHub} cx="120" cy="124" r="5" />
      <text className={styles.instrumentScore} x="120" y="96">{score ?? '—'}</text>
      <text className={styles.instrumentState} x="120" y="111">{state}</text>
      <circle className={styles.instrumentStateDot} cx="120" cy="117" r="1.7" />
    </svg>
    <div className={styles.instrumentReason}><strong className={stateClass(state)}>{state}</strong><span>{reason}</span></div>
  </section>
}

export function TrendEnergyRing({ state, score, reason, evaluated, live }: InstrumentProps) {
  const instance = useId().replaceAll(':', '')
  const gradientId = `ose-energy-gradient-${instance}`
  const glowId = `ose-energy-glow-${instance}`
  const textureId = `ose-energy-texture-${instance}`
  const needle = trendInstrumentNeedle(state)
  const position = wheelPosition(state)
  const displayScore = score ?? position
  const stateTone = state === 'ULTRA BULLISH' ? styles.energyUltraBull : state === 'BULLISH' ? styles.energyBull : state === 'ULTRA BEARISH' ? styles.energyUltraBear : state === 'BEARISH' ? styles.energyBear : styles.energyNeutral
  const animated = live && state !== 'INSUFFICIENT HISTORY'
  const style = { '--energy-offset': `${energyDashOffset(state)}` } as CSSProperties
  return <section className={`${styles.instrument} ${styles.trendInstrument} ${live ? styles.instrumentLive : styles.instrumentStale}`} data-wheel-kind="TREND" data-state={state} data-wheel-position={position} data-animation-state={animated ? 'ACTIVE' : 'STATIC'}>
    <header><span>TREND ENGINE</span><small>{formatTime(evaluated)}</small></header>
    <svg className={styles.trendSvg} viewBox="0 0 210 176" preserveAspectRatio="xMidYMid meet" role="img" aria-label={`Trend Engine: ${state}, trend instrument index ${displayScore}`}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#ee5362" /><stop offset=".42" stopColor="#8768ff" /><stop offset=".62" stopColor="#6677e8" /><stop offset="1" stopColor="#32d49d" />
        </linearGradient>
        <filter id={glowId} x="-70%" y="-70%" width="240%" height="240%">
          <feGaussianBlur stdDeviation="4" result="halo" /><feMerge><feMergeNode in="halo" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <filter id={textureId} x="-45%" y="-45%" width="190%" height="190%">
          <feTurbulence type="fractalNoise" baseFrequency=".028 .12" numOctaves="2" seed="17" result="noise" />
          <feDisplacementMap in="SourceGraphic" in2="noise" scale="5" xChannelSelector="R" yChannelSelector="B" />
          <feGaussianBlur stdDeviation=".35" />
        </filter>
      </defs>
      <circle className={styles.energyInterior} cx="105" cy="82" r="58" />
      <circle className={styles.energyHaloRing} cx="105" cy="82" r="64" stroke={`url(#${gradientId})`} filter={`url(#${glowId})`} />
      <circle data-energy-layer="base" className={styles.energyContinuous} cx="105" cy="82" r="61" stroke={`url(#${gradientId})`} />
      <circle data-energy-layer="texture" className={styles.energyTexture} cx="105" cy="82" r="66" stroke={`url(#${gradientId})`} filter={`url(#${textureId})`} />
      <circle data-energy-layer="trace" className={styles.energyTrace} cx="105" cy="82" r="68" stroke={`url(#${gradientId})`} />
      <circle className={`${styles.energyDirectional} ${stateTone} ${animated ? styles.energyAnimated : ''}`} cx="105" cy="82" r="70" pathLength="100" style={style} />
      <circle className={`${styles.energySpark} ${stateTone} ${animated ? styles.energySparkAnimated : ''}`} cx="105" cy="82" r="70" pathLength="100" style={style} />
      <line className={styles.instrumentNeedle} x1="105" y1="82" x2={needle.x} y2={needle.y} />
      <circle className={styles.instrumentHubHalo} cx="105" cy="82" r="8" />
      <circle className={styles.instrumentHub} cx="105" cy="82" r="5" />
      <text className={styles.energyInstrumentScore} x="105" y="112">{displayScore}</text>
      <text className={styles.energyInstrumentState} x="105" y="127">{state}</text>
      <circle className={styles.instrumentStateDot} cx="105" cy="135" r="1.8" />
    </svg>
    <div className={styles.instrumentReason}><strong className={stateClass(state)}>{state}</strong><span>{reason}</span></div>
  </section>
}

interface SsiBreakdownRow { key: string; label: string; points: number; maximum: number }
export interface SsiProjection { score: number; maximum: 100; band: string; meaning: string; breakdown: SsiBreakdownRow[] }

export function ScoreBreakdown({ ssi }: { ssi: SsiProjection }) {
  return <details className={styles.ssiDetails}>
    <summary>WHY {ssi.score}?</summary>
    <div className={styles.ssiBreakdown}>
      {ssi.breakdown.map((row) => <div key={row.key}><span>{row.label}</span><strong>{row.points.toFixed(row.points % 1 ? 2 : 0)} / {row.maximum}</strong></div>)}
      <div className={styles.ssiTotal}><span>Total SSI</span><strong>{ssi.score} / {ssi.maximum}</strong></div>
    </div>
  </details>
}

export function StructuralStrengthIndex({ ssi, compact = false }: { ssi?: SsiProjection; compact?: boolean }) {
  if (!ssi) return <div className={`${styles.ssi} ${compact ? styles.ssiCompact : ''}`} aria-label="Structural Strength Index not reported">
    <div><span>SSI</span><strong>— <small>/ 100</small></strong><b>NOT REPORTED</b></div>
  </div>
  return <div className={`${styles.ssi} ${compact ? styles.ssiCompact : ''}`} aria-label={`Structural Strength Index ${ssi.score} of 100, ${ssi.band}`}>
    <div><span>SSI</span><strong>{ssi.score} <small>/ 100</small></strong><b>{ssi.band}</b></div>
    <ScoreBreakdown ssi={ssi} />
  </div>
}

interface FlowSide {
  score: number | null
  activity: string
  quality_band?: string
  surrounding_confirmation?: number | null
}
interface FlowProjection {
  state: string
  status: string
  call: FlowSide
  put: FlowSide
  balance_marker: number
  evaluated_at: string
  source_timestamp: string | null
  age_seconds?: number | null
  prior_snapshot_available?: boolean
  edge?: { label?: string; delta?: number | null; band?: string; summary?: string; last_authoritative_state?: string | null }
  executionInfluence: 'ZERO'
}

const FlowMiniCard = ({ label, side, stale }: { label: string; side: FlowSide; stale: boolean }) => <div className={styles.flowMiniCard}>
  <span>{label}</span><strong>{side.score ?? '—'} <small>/ 100</small></strong>
  <b>{side.activity}</b><em>{side.quality_band ?? 'QUALITY NOT REPORTED'}</em>
  {stale ? <small>LAST SNAPSHOT SCORE</small> : null}
</div>

export function ArgusFlowEdge({ flow }: { flow: FlowProjection }) {
  const stale = flow.status !== 'LIVE'
  const marker = Number.isFinite(flow.balance_marker) ? flow.balance_marker : 50
  const delta = flow.edge?.delta ?? null
  const edgeLabel = stale ? 'DATA STALE' : flow.edge?.label ?? 'UNAVAILABLE'
  const prior = flow.edge?.last_authoritative_state ?? null
  const confirmation = Math.max(flow.call.surrounding_confirmation ?? 0, flow.put.surrounding_confirmation ?? 0)
  return <section className={`${styles.argusFlow} ${stale ? styles.argusFlowStale : styles.argusFlowLive}`} aria-label="ARGUS Live Option Flow Edge" data-flow-state={flow.state} data-flow-marker={marker.toFixed(4)}>
    <header><span>ARGUS LIVE OPTION FLOW</span><b className={stateClass(edgeLabel)}>{flow.status}</b></header>
    <div className={styles.argusFlowBody}>
      <FlowMiniCard label="CALL FLOW" side={flow.call} stale={stale} />
      <div className={styles.flowEdgeInstrument}>
        <span>FLOW EDGE</span><strong className={stateClass(edgeLabel)}>{edgeLabel}</strong>
        <b>{delta == null || delta === 0 ? 'BALANCED' : `${delta > 0 ? 'PUT' : 'CALL'} +${Math.abs(delta)}`}</b>
        <small>{stale ? `Last snapshot: ${prior ?? 'Not reported'}` : flow.edge?.summary ?? 'Edge explanation unavailable'}</small>
        <div className={styles.flowEnergyRail} style={{ '--flow-position': `${marker}%` } as CSSProperties}>
          <span>CALL</span><i className={styles.flowDeadZone} /><b /><span>PUT</span>
        </div>
      </div>
      <FlowMiniCard label="PUT FLOW" side={flow.put} stale={stale} />
    </div>
    <footer>
      <span>Quality <strong>{stale ? 'LAST AUTHORITATIVE SNAPSHOT' : flow.edge?.band ?? 'NOT REPORTED'}</strong></span>
      <span>Nearby <strong>{Math.round(confirmation * 100)}%</strong></span>
      <span>Evaluated <strong>{formatTime(flow.evaluated_at)}</strong></span>
      <span>Source <strong>{formatTime(flow.source_timestamp)}</strong></span>
      <span>Age <strong>{flow.age_seconds == null ? 'Not reported' : `${Math.round(flow.age_seconds)}s`}</strong></span>
      <span>Prior snapshot <strong>{flow.prior_snapshot_available ? 'AVAILABLE' : 'NOT REPORTED'}</strong></span>
      <span>Advisory · Influence <strong>{flow.executionInfluence}</strong></span>
    </footer>
  </section>
}

interface AgreementSide {
  state: string
  qualifier: string
  vob: { state: string }
  trend: { state: string }
  flow: { state: string }
}

export function EngineAgreement({ agreements }: { agreements?: Record<'CE' | 'PE', AgreementSide> }) {
  if (!agreements?.CE || !agreements?.PE) return <section className={styles.engineAgreement} aria-label="Three-engine agreement">
    <header><span>3-ENGINE AGREEMENT</span><small>VOB · TREND · FLOW</small></header>
    {(['CE', 'PE'] as const).map((side) => <div key={side}><b>{side}</b><span>VOB <strong>NOT REPORTED</strong></span><span>TREND <strong>NOT REPORTED</strong></span><span>FLOW <strong>NOT REPORTED</strong></span><em>DATA STALE · CANONICAL AGREEMENT UNAVAILABLE</em></div>)}
  </section>
  return <section className={styles.engineAgreement} aria-label="Three-engine agreement">
    <header><span>3-ENGINE AGREEMENT</span><small>VOB · TREND · FLOW</small></header>
    {(['CE', 'PE'] as const).map((side) => <div key={side}><b>{side}</b><span>VOB <strong>{agreements[side].vob.state}</strong></span><span>TREND <strong>{agreements[side].trend.state}</strong></span><span>FLOW <strong>{agreements[side].flow.state}</strong></span><em>{agreements[side].state} · {agreements[side].qualifier}</em></div>)}
  </section>
}

export function DecisionWindow({ value }: { value?: { state: string; explanation: string; distance_points?: number | null } | null }) {
  if (!value) return <div className={styles.contextUnavailable}>DECISION WINDOW · NOT REPORTED</div>
  return <div className={styles.decisionWindow}><span>DECISION WINDOW</span><strong className={stateClass(value.state)}>{value.state}</strong><small>{value.explanation}</small></div>
}

export function LatestStateChange({ value }: { value?: { previous_state: string; current_state: string; previous_score: number; current_score: number; reason: string; evaluated_through: string | null } | null }) {
  if (!value) return <div className={styles.latestState}><span>LAST CHANGE</span><strong>No transition recorded</strong><small>Awaiting an authoritative persisted state change</small></div>
  return <div className={styles.latestState}><span>LAST CHANGE · {formatTime(value.evaluated_through)}</span><strong>{value.previous_state} → {value.current_state}</strong><small>{value.reason} · SSI {value.previous_score} → {value.current_score}</small></div>
}
