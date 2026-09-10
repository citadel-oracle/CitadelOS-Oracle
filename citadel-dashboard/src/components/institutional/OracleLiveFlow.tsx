'use client'

import { memo, type CSSProperties, type ReactNode } from 'react'
import type { DashboardFeedState } from '@/dashboard/types'
import { buildOracleLiveFlowFixture } from './OracleLiveFlow.fixture'
import styles from './OracleLiveFlow.module.css'

type JsonRecord = Record<string, unknown>
type FlowTone = 'call' | 'put' | 'wait' | 'protect' | 'locked'

const record = (value: unknown): JsonRecord =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonRecord
    : {}
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const text = (value: unknown, fallback = 'UNAVAILABLE'): string =>
  typeof value === 'string' && value.trim() ? value.trim() : fallback
const finite = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null
const numberText = (value: unknown, digits = 1): string => {
  const number = finite(value)
  return number === null ? '—' : number.toLocaleString('en-IN', { maximumFractionDigits: digits })
}
const money = (value: unknown): string => {
  const number = finite(value)
  return number === null ? '—' : `₹${number.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}
const percentage = (value: unknown): string => {
  const number = finite(value)
  return number === null ? '—' : `${Math.round(number * 100)}%`
}
const label = (value: unknown): string => text(value).replaceAll('_', ' ')
const clamp = (value: number, low = 0, high = 100): number => Math.max(low, Math.min(high, value))

type VisualStyle = CSSProperties & Record<`--${string}`, string | number>

const particleMeta = (percent: number) => {
  const count = percent >= 70 ? 4 : percent >= 40 ? 3 : 2
  const duration = Math.max(1.3, 3.6 - (percent / 100) * 2.3)
  return { count, duration, stop: `${Math.max(0, percent - 3)}%` }
}

function ParticleStream({ percent, side }: { percent: number; side: 'call' | 'put' }) {
  const { count, duration, stop } = particleMeta(percent)
  return (
    <span className={styles.particleLayer} data-side={side} aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <i
          key={index}
          style={{
            '--particle-duration': `${duration.toFixed(2)}s`,
            '--particle-delay': `${((duration / count) * index).toFixed(2)}s`,
            '--particle-stop': stop,
          } as VisualStyle}
        />
      ))}
    </span>
  )
}

function LadderMarker({ children, className, left, style }: {
  children?: ReactNode
  className: string
  left: string
  style?: VisualStyle
}) {
  return <i className={className} style={{ left, ...style }}>{children}</i>
}

const toneOf = (action: string): FlowTone => {
  if (action === 'BUY CALL') return 'call'
  if (action === 'BUY PUT') return 'put'
  if (action === 'PROTECT / EXIT') return 'protect'
  if (action === 'NO TRADE') return 'locked'
  return 'wait'
}

const trendGlyph = (state: string): string => {
  if (state.includes('STRENGTHENING')) return '▲'
  if (state.includes('WEAKENING')) return '▼'
  return '—'
}

const directionGlyph = (state: unknown): string => {
  const value = text(state, '').toUpperCase()
  if (value.includes('BUY') || value.includes('BULL') || value.includes('CALL')) return '↑'
  if (value.includes('SELL') || value.includes('BEAR') || value.includes('PUT')) return '↓'
  return '→'
}

const locationPercent = (state: unknown): number => {
  const value = text(state, '').toUpperCase()
  if (value.includes('ABOVE') || value.includes('VAH_ACCEPTED')) return 88
  if (value.includes('VAH')) return 82
  if (value.includes('BELOW') || value.includes('VAL_BROKEN') || value.includes('BREAKDOWN')) return 12
  if (value.includes('VAL')) return 18
  return 50
}

const riskPercent = (risk: unknown): number => ({
  LOW: 18,
  RISING: 42,
  HIGH: 68,
  CONFIRMED: 95,
}[text(risk)] ?? 0)

const cvdPoints = (state: unknown, divergence: unknown): string => {
  const conflict = text(divergence, 'NONE') !== 'NONE'
  if (conflict) return '0,4 10,5 20,4 31,6 46,5'
  if (text(state) === 'RISING') return '0,14 10,12 20,8 31,9 46,3'
  if (text(state) === 'FALLING') return '0,3 10,5 20,9 31,10 46,15'
  return '0,9 10,9 20,8 31,9 46,9'
}

function ResearchValue({ value }: { value: unknown }) {
  return <strong>{value === null || value === undefined ? 'NOT YET AVAILABLE' : label(value)}</strong>
}

export const OracleLiveFlow = memo(function OracleLiveFlow({
  feed,
  visualFixture = null,
  initialLabOpen = false,
}: {
  feed: DashboardFeedState<unknown>
  visualFixture?: string | null
  initialLabOpen?: boolean
}) {
  const fixture = buildOracleLiveFlowFixture(visualFixture)
  const projection = record(fixture ?? feed.data)
  const decision = record(projection.decision)
  const family = record(projection.family_values)
  const profile = record(family.LOCATION)
  const response = record(family.RESPONSE_QUALITY)
  const book = record(family.BOOK_PRESSURE)
  const futures = record(family.FUTURES_PRESSURE)
  const option = record(family.OPTION_CONFIRMATION)
  const research = record(projection.research)
  const currentEpisode = record(research.current_episode)
  const today = record(research.today)
  const edgeHealth = record(research.edge_health)
  const shadowPnl = record(research.shadow_pnl)
  const contract = record(decision.contract)
  const action = text(decision.action, 'NO TRADE')
  const tone = toneOf(action)
  const callStrength = finite(projection.call_strength)
  const putStrength = finite(projection.put_strength)
  const dataQuality = text(projection.data_quality, 'UNUSABLE')
  const profileAvailable = profile.status === 'AVAILABLE'
  const locks = list(projection.action_lock_reasons).map((item) => label(item))
  const isLive = projection.projection_state === 'LIVE' && dataQuality === 'GOOD' && locks.length === 0
  const sourceAge = finite(projection.snapshot_age_seconds)
  const entryLow = finite(decision.entry_low)
  const entryHigh = finite(decision.entry_high)
  const invalidation = finite(decision.invalidation)
  const target1 = finite(decision.target_1)
  const target2 = finite(decision.target_2)
  const currentPremium = finite(contract.current_premium)
  const levelsAvailable = decision.levels_status === 'AVAILABLE'
  const hasEntryZone = entryLow !== null && entryHigh !== null
  const callPercent = clamp(callStrength ?? 0)
  const putPercent = clamp(putStrength ?? 0)
  const flowState = text(decision.flow_state)
  const entryQuality = text(decision.entry_quality)
  const reversalRisk = text(decision.reversal_risk)
  const locationState = text(profile.location_state)
  const divergence = text(profile.divergence_state, 'NONE')
  const footprint = text(profile.footprint_state)
  const stackCount = Math.max(1, Math.min(5, Math.round(finite(profile.stacked_levels) ?? 1)))
  const imbalanceDirection = footprint.startsWith('SELL') ? 'SELL' : footprint.startsWith('BUY') ? 'BUY' : 'MIXED'
  const imbalanceGlyph = imbalanceDirection === 'SELL' ? '▼'.repeat(stackCount) : imbalanceDirection === 'BUY' ? '▲'.repeat(stackCount) : '◆'
  const responseState = text(response.state)
  const responseAbsorbed = responseState.includes('ABSORBED') || footprint.includes('ABSORBED')
  const confirmed = decision.confirmed === true && (action === 'BUY CALL' || action === 'BUY PUT')
  const alert = action === 'PROTECT / EXIT'
  const style = {
    '--flow-call': `${callPercent}%`,
    '--flow-put': `${putPercent}%`,
    '--flow-risk': `${riskPercent(reversalRisk)}%`,
    '--flow-location': `${locationPercent(locationState)}%`,
  } as CSSProperties
  const ladderValues = [invalidation, entryLow, entryHigh, target1, target2, currentPremium]
    .filter((value): value is number => value !== null)
  const ladderMin = ladderValues.length ? Math.min(...ladderValues) : 0
  const ladderMax = ladderValues.length ? Math.max(...ladderValues) : 1
  const ladderPosition = (value: number | null): string => {
    if (value === null || ladderMax === ladderMin) return '50%'
    return `${8 + clamp((value - ladderMin) / (ladderMax - ladderMin), 0, 1) * 84}%`
  }
  const entryLeft = ladderPosition(entryLow)
  const entryRight = ladderPosition(entryHigh)
  const currentMarkerTone = alert ? 'protect' : decision.do_not_chase === true ? 'chase' : 'confirmed'
  const scoreBands = list(research.score_edge).map(record)
  const reversalLog = list(research.reversal_log).map(record)
  const timeline = list(research.event_timeline).map(record)
  const familyConfig = record(research.best_combination)
  const greeksUnavailable = text(option.greeks_mode, '') === 'RAW_QUOTE_AWARE'
  const cvdState = text(profile.cvd_state)
  const cvdConflict = divergence !== 'NONE'

  return (
    <section
      className={`${styles.surface} ${styles[`tone_${tone}`]} ${alert ? styles.alert : ''}`}
      aria-label="CITADEL Oracle Live Flow"
      data-oracle-live-flow
      data-action={action}
      data-quality={dataQuality}
      data-snapshot-id={text(projection.snapshot_id)}
      data-fixture={fixture ? 'TEST' : 'PRODUCTION'}
      data-confirmed={confirmed ? 'true' : 'false'}
      style={style}
    >
      <i className={styles.cornerTl} aria-hidden="true" />
      <i className={styles.cornerBr} aria-hidden="true" />

      <header className={styles.header}>
        <span className={styles.eyebrow}><i aria-hidden="true" data-live={isLive ? 'true' : 'false'} /> Citadel Oracle · Live Flow</span>
        <div className={styles.statusCluster}>
          {fixture && <b className={styles.testBadge}>TEST FIXTURE</b>}
          <b data-quality={dataQuality}>{dataQuality}</b>
          <small>{sourceAge === null ? 'AGE —' : `${sourceAge.toFixed(2)}s`}</small>
          <span className={styles.shadowLabel}>SHADOW · LIVE VALIDATION PENDING</span>
        </div>
      </header>

      <div className={styles.splitLabels}>
        <strong>CALL BUYING <b>{numberText(callStrength, 0)}</b></strong>
        <strong>PUT BUYING <b>{numberText(putStrength, 0)}</b></strong>
      </div>
      <div className={styles.splitRail} aria-label={`Call flow ${numberText(callStrength, 0)}, Put flow ${numberText(putStrength, 0)}`}>
        <i className={styles.callBar} /><i className={styles.putBar} />
        <ParticleStream percent={callPercent} side="call" />
        <ParticleStream percent={putPercent} side="put" />
      </div>

      <div className={styles.actionRow}>
        <h3>{action}</h3>
        {confirmed && <span key={`${action}-confirmed`} className={styles.confirmRing} aria-label="Fully aligned canonical decision">✓</span>}
      </div>
      <div className={styles.flowChip} data-flow={flowState}>
        {trendGlyph(flowState)} FLOW {label(flowState)}
      </div>

      <div className={styles.contractRow}>
        <strong>{text(contract.trading_symbol, 'NO AUTHORIZED CONTRACT')}</strong>
        <span>{finite(decision.rr_1) === null ? 'RR —' : `RR 1:${numberText(decision.rr_1)} / 1:${numberText(decision.rr_2)}`}</span>
      </div>

      <div className={styles.ladder} data-available={levelsAvailable ? 'true' : 'false'} data-entry={hasEntryZone ? 'true' : 'false'}>
        <div className={styles.ladderTrack} />
        {levelsAvailable ? <>
          <LadderMarker className={styles.tickInvalid} left={ladderPosition(invalidation)} />
          <i className={styles.entryBand} style={{ left: entryLeft, right: `calc(100% - ${entryRight})` }}>
            {[0, 1, 2].map((index) => <b key={index} style={{ '--bubble-delay': `${(index * .7).toFixed(1)}s` } as VisualStyle} />)}
          </i>
          <LadderMarker className={styles.tickTarget} left={ladderPosition(target1)} style={{ '--target-delay': '0s' }}><b /></LadderMarker>
          <LadderMarker className={styles.tickTarget} left={ladderPosition(target2)} style={{ '--target-delay': '.9s' }}><b /></LadderMarker>
          {currentPremium !== null && (
            <LadderMarker className={`${styles.currentMarker} ${styles[`current_${currentMarkerTone}`]}`} left={ladderPosition(currentPremium)}>
              <b /><em>LIVE {money(currentPremium)}</em>
            </LadderMarker>
          )}
        </> : hasEntryZone ? (
          <i className={`${styles.entryBand} ${styles.formingBand}`}>
            {[0, 1, 2].map((index) => <b key={index} style={{ '--bubble-delay': `${(index * .7).toFixed(1)}s` } as VisualStyle} />)}
          </i>
        ) : <span className={styles.noLevels}>NO LEVELS LOCKED</span>}
      </div>
      <div className={styles.ladderLabels}>
        <span>INVALID <b>{levelsAvailable ? money(invalidation) : '—'}</b></span>
        <span>ENTRY <b>{levelsAvailable ? `${money(entryLow)}–${money(entryHigh)}` : '—'}</b></span>
        <span>T1 <b>{levelsAvailable ? money(target1) : '—'}</b></span>
        <span>T2 <b>{levelsAvailable ? money(target2) : '—'}</b></span>
      </div>
      {!levelsAvailable && <p className={styles.levelReason}>WAIT — LEVELS UNAVAILABLE · {label(decision.levels_reason)}</p>}

      <div className={styles.qualityGrid}>
        <div>
          <span className={styles.eyebrow}>Entry quality</span>
          <div className={styles.segmented} data-active={entryQuality}>
            {['HIGH', 'MEDIUM', 'POOR', "MISSED / DON'T CHASE"].map((item) => <b key={item}>{item === "MISSED / DON'T CHASE" ? 'MISSED' : item}</b>)}
          </div>
        </div>
        <div>
          <span className={styles.eyebrow}>Reversal risk</span>
          <div className={styles.riskRail}><i /></div>
          <strong>{label(reversalRisk)}</strong>
        </div>
      </div>

      <div className={styles.location} data-available={profileAvailable ? 'true' : 'false'}>
        <span className={styles.eyebrow}>Location</span>
        {profileAvailable ? <>
          <div className={styles.locationRail}>
            <i className={styles.locationMarker} />
          </div>
          <div className={styles.locationLabels}>
            <span>VAL {numberText(profile.val)}</span><span>POC {numberText(profile.poc)}</span><span>VAH {numberText(profile.vah)}</span>
          </div>
          <strong>{label(locationState)}</strong>
        </> : <p>PROFILE DEGRADED · POC / VAH / VAL UNAVAILABLE</p>}
      </div>

      <div className={styles.confirmationStrip} data-absorbed={responseAbsorbed ? 'true' : 'false'}>
        <div className={styles.cvd}>
          <span className={styles.eyebrow}>CVD</span>
          <svg width="46" height="18" viewBox="0 0 46 18" aria-hidden="true"><polyline points={cvdPoints(cvdState, divergence)} /></svg>
          <strong>{cvdConflict ? `${label(cvdState)} · ${label(divergence)}` : label(cvdState)}</strong>
        </div>
        <div className={styles.imbalance}>
          <b data-side={imbalanceDirection}>{imbalanceGlyph}</b>
          <span>{label(footprint)}</span>
        </div>
        <div className={styles.confirmationFooter}>
          <div className={styles.triad}>
            <span>FUT {directionGlyph(futures.state)}</span>
            <span>BOOK {directionGlyph(book.state)}</span>
            <span>{text(contract.option_type, 'OPT')} {directionGlyph(option.status)}</span>
          </div>
          <b className={styles.responsePill}>{responseAbsorbed ? 'RESPONSE ABSORBED' : responseState.includes('CLEAN') ? 'RESPONSE CLEAN' : label(responseState)}</b>
        </div>
      </div>

      {(locks.length > 0 || dataQuality !== 'GOOD') && (
        <div className={styles.qualityNotice} role="status">
          <strong>DATA QUALITY · {dataQuality}</strong>
          <span>{locks.join(' · ') || 'No lock reason reported'}</span>
          <small>SIGNED {percentage(projection.signed_flow_coverage)} · PROFILE {percentage(projection.profile_coverage)}</small>
        </div>
      )}

      <details className={styles.flowLab} open={initialLabOpen ? true : undefined} data-flow-lab>
        <summary><span>FLOW LAB</span><b>Research · not probability</b></summary>
        <div className={styles.labGrid}>
          <section>
            <h4>Current episode</h4>
            <dl>
              <div><dt>Direction / contract</dt><dd>{label(currentEpisode.direction)} · {text(currentEpisode.contract)}</dd></div>
              <div><dt>Started / episode</dt><dd>{text(currentEpisode.started_at)} · {text(currentEpisode.episode_id)}</dd></div>
              <div><dt>Trigger / current premium</dt><dd>{money(currentEpisode.trigger_option_price)} · {money(currentEpisode.current_option_price)}</dd></div>
              <div><dt>Trigger score / edge captured</dt><dd><ResearchValue value={currentEpisode.trigger_score} /> · <ResearchValue value={currentEpisode.edge_captured} /></dd></div>
              <div><dt>Current / peak score</dt><dd>{numberText(currentEpisode.current_score, 0)} · {numberText(currentEpisode.peak_score, 0)}</dd></div>
              <div><dt>Underlying MFE / MAE</dt><dd>{numberText(currentEpisode.mfe)} · {numberText(currentEpisode.mae)}</dd></div>
              <div><dt>Flow / reversal state</dt><dd><ResearchValue value={currentEpisode.flow_state} /> · <ResearchValue value={currentEpisode.reversal_state} /></dd></div>
              <div><dt>Data quality</dt><dd>{label(currentEpisode.data_quality)}</dd></div>
            </dl>
          </section>
          <section>
            <h4>Today</h4>
            <dl>
              <div><dt>CALL / PUT episodes</dt><dd>{numberText(today.call_episodes, 0)} / {numberText(today.put_episodes, 0)}</dd></div>
              <div><dt>Completed</dt><dd>{numberText(today.completed, 0)}</dd></div>
              <div><dt>Successful / failed</dt><dd><ResearchValue value={today.successful} /> / <ResearchValue value={today.failed} /></dd></div>
              <div><dt>Reversals</dt><dd>{numberText(today.reversals, 0)}</dd></div>
              <div><dt>Clean / false reversal</dt><dd><ResearchValue value={today.clean_reversals} /> / <ResearchValue value={today.false_signals} /></dd></div>
              <div><dt>Median reversal lead</dt><dd><ResearchValue value={today.median_reversal_lead_ms} /></dd></div>
              <div><dt>Data-quality coverage</dt><dd>{percentage(today.data_quality_coverage)}</dd></div>
            </dl>
          </section>
          <section className={styles.wide}>
            <h4>Score edge · researching</h4>
            <div className={styles.bandGrid}>
              {scoreBands.length ? scoreBands.map((band) => (
                <div key={text(band.band)}><span>{text(band.band)}</span><strong>N {numberText(band.sample_count, 0)}</strong><small>{text(band.status)} · OUTCOME RATE —</small></div>
              )) : <p>Insufficient independent episodes. No percentage claim.</p>}
            </div>
          </section>
          <section><h4>Best combination</h4><p>{list(familyConfig.families).map(label).join(' + ') || 'RESEARCHING'}</p><small>Incremental observed evidence: NOT YET AVAILABLE</small></section>
          <section><h4>Shadow P&amp;L / drawdown</h4><p>{label(shadowPnl.status)}</p><small>{text(shadowPnl.reason, 'No executable outcome contract')}</small></section>
          <section><h4>Edge health</h4><p>N {numberText(edgeHealth.sample_count, 0)} · {label(edgeHealth.edge_stability)} · {label(edgeHealth.maturity)}</p><small>Recent / long-window expectancy: NOT YET AVAILABLE</small></section>
          <section><h4>Reversal log</h4>{reversalLog.length ? reversalLog.slice(-4).map((row) => <p key={text(row.episode_id)}>{label(row.direction)} · {label(record(row.latest).state)} · ACTUAL REVERSAL NOT YET AVAILABLE</p>) : <p>No recorded reversal evidence.</p>}</section>
          <section><h4>Event timeline</h4>{timeline.length ? timeline.slice(-5).map((row, index) => <p key={`${text(row.timestamp)}-${index}`}>{text(row.timestamp)} · {label(row.event)} · {label(row.direction)}</p>) : <p>No episode events recorded.</p>}</section>
          <section className={styles.wide}><h4>Provenance</h4><p>{text(projection.formula_version)} · SNAPSHOT {text(projection.snapshot_id)} · REV {numberText(projection.revision, 0)}</p><small>BOOK 45% · RESPONSE 35% · OPTION 20% · ENGINEERING DEFAULTS, NOT VALIDATED · SCORE IS NOT PROBABILITY · {greeksUnavailable ? 'GREEKS UNAVAILABLE · ' : ''}EXECUTION INFLUENCE ZERO</small></section>
        </div>
      </details>
    </section>
  )
})
