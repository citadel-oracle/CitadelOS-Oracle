'use client'

import {
  Activity,
  Bell,
  ChevronDown,
  Crosshair,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
  Volume2,
  Waves,
} from 'lucide-react'
import { memo, useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'

import type { DashboardFeedState } from '@/dashboard/types'

import styles from './ArgusFusionShadowPanel.module.css'

type JsonRecord = Record<string, unknown>

const record = (value: unknown): JsonRecord => value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {}
const rows = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const text = (value: unknown, fallback = 'UNKNOWN'): string => typeof value === 'string' && value.trim() ? value : fallback
const finite = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null
const timestamp = (value: unknown): string => {
  if (typeof value !== 'string') return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleTimeString('en-IN', { hour12: false, timeZone: 'Asia/Kolkata' })
}
const price = (value: unknown): string => finite(value) === null ? '—' : `₹${finite(value)!.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const points = (value: unknown): string => finite(value) === null ? '—' : finite(value)!.toLocaleString('en-IN', { maximumFractionDigits: 2 })
const percent = (value: unknown): string => finite(value) === null ? '—' : `${finite(value)! >= 0 ? '+' : ''}${finite(value)!.toFixed(1)}%`

const railStates = ['WAIT', 'WATCH', 'SETUP', 'TRIGGER', 'RUNNER'] as const

const semanticTone = (state: string): 'bull' | 'bear' | 'warn' | 'locked' | 'neutral' => {
  const value = state.toUpperCase()
  if (value.includes('LOCK') || value.includes('INVALID')) return 'locked'
  if (value.includes('BULL') || value.includes('CE') || value.includes('↑')) return 'bull'
  if (value.includes('BEAR') || value.includes('PE') || value.includes('↓')) return 'bear'
  if (value.includes('SETUP') || value.includes('WATCH') || value.includes('VOLATILE')) return 'warn'
  return 'neutral'
}

const transitionTone = (state: string): [number, number, OscillatorType] => {
  if (state === 'TRIGGER') return [660, 0.22, 'sine']
  if (state === 'RUNNER') return [520, 0.15, 'sine']
  if (state === 'SETUP') return [440, 0.16, 'triangle']
  if (state === 'WATCH') return [330, 0.08, 'sine']
  if (state === 'DATA_LOCKED' || state === 'INVALIDATED') return [170, 0.24, 'sawtooth']
  return [250, 0.1, 'sine']
}

const transitionLabel = (state: string): string => {
  if (state === 'TRIGGER') return 'SHADOW TRIGGER'
  if (state === 'RUNNER') return 'RUNNER CONFIRMED'
  if (state === 'SETUP') return 'SETUP FORMING'
  if (state === 'WATCH') return 'MARKET STATE CHANGED'
  if (state === 'DATA_LOCKED') return 'DATA LOCKED'
  if (state === 'INVALIDATED') return 'THESIS INVALIDATED'
  return 'MARKET STATE UPDATED'
}

interface ToastState { eventId: string; title: string; message: string; tone: string }

export interface ArgusFusionShadowPanelProps { fusion: DashboardFeedState<unknown> }

export const ArgusFusionShadowPanel = memo(function ArgusFusionShadowPanel({ fusion: feed }: ArgusFusionShadowPanelProps) {
  const data = record(feed.data)
  const hero = record(data.hero)
  const fusion = record(data.fusion)
  const quality = record(data.data_quality)
  const tracker = record(data.premium_tracker)
  const playbooks = record(data.playbooks)
  const history = record(data.history_summary)
  const tradeRows = rows(data.today_shadow_trades).map(record)
  const newestTrade = tradeRows.at(-1) ?? null
  const state = text(fusion.state, 'WAIT')
  const heroState = text(hero.state, 'SIDEWAYS · NO TREND')
  const marketClosed = data.market_closed === true || text(data.market_session, '') === 'CLOSED' || text(quality.state, '') === 'MARKET_CLOSED'
  const lastValid = record(data.last_valid_market_state)
  const displayedHeroState = marketClosed ? 'MARKET CLOSED' : heroState
  const direction = text(fusion.direction, '')
  const stateEventId = typeof data.state_event_id === 'string' ? data.state_event_id : null
  const tone = semanticTone(marketClosed ? text(lastValid.hero_state, 'NEUTRAL') : state === 'WAIT' ? heroState : `${state} ${direction}`)
  const railIndex = Math.max(0, railStates.indexOf(state as typeof railStates[number]))
  const [toast, setToast] = useState<ToastState | null>(null)
  const [soundArmed, setSoundArmed] = useState(false)
  const [soundLevel, setSoundLevel] = useState<'LOW' | 'MED' | 'HIGH'>('MED')
  const [reducedMotion, setReducedMotion] = useState(false)
  const seenTransitions = useRef(new Set<string>())
  const transitionStreamInitialized = useRef(false)
  const audioContext = useRef<AudioContext | null>(null)

  const playTone = useCallback((nextState: string) => {
    const context = audioContext.current
    if (!context || context.state !== 'running') return
    const [frequency, duration, waveform] = transitionTone(nextState)
    const gain = context.createGain()
    const oscillator = context.createOscillator()
    const volume = soundLevel === 'HIGH' ? 0.105 : soundLevel === 'LOW' ? 0.028 : 0.06
    oscillator.type = waveform
    oscillator.frequency.setValueAtTime(frequency, context.currentTime)
    if (nextState === 'SETUP' || nextState === 'TRIGGER') oscillator.frequency.exponentialRampToValueAtTime(frequency * 1.34, context.currentTime + duration)
    gain.gain.setValueAtTime(0.0001, context.currentTime)
    gain.gain.exponentialRampToValueAtTime(volume, context.currentTime + 0.012)
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + duration)
    oscillator.connect(gain).connect(context.destination)
    oscillator.start()
    oscillator.stop(context.currentTime + duration + 0.025)
  }, [soundLevel])

  const armAudio = useCallback(() => {
    if (typeof window === 'undefined') return
    const Context = window.AudioContext ?? window.webkitAudioContext
    if (!Context) return
    const context = audioContext.current ?? new Context()
    audioContext.current = context
    void context.resume().then(() => setSoundArmed(true))
  }, [])

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReducedMotion(query.matches)
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    if (!stateEventId || seenTransitions.current.has(stateEventId)) return
    seenTransitions.current.add(stateEventId)
    // A REST/SSE bootstrap is a snapshot, not a new browser-side transition.
    // Prime deduplication first so refreshes cannot replay popup or sound.
    if (!transitionStreamInitialized.current) {
      transitionStreamInitialized.current = true
      return
    }
    setToast({ eventId: stateEventId, title: transitionLabel(state), message: text(fusion.plain_language, 'State transition received.'), tone })
    if (soundArmed && !reducedMotion) playTone(state)
    const timer = window.setTimeout(() => setToast((current) => current?.eventId === stateEventId ? null : current), state === 'DATA_LOCKED' ? 9_000 : 5_500)
    return () => window.clearTimeout(timer)
  }, [fusion.plain_language, playTone, reducedMotion, soundArmed, state, stateEventId, tone])

  const evidence = record(fusion.evidence)
  const priceEvidence = record(evidence.price_futures)
  const flowEvidence = record(evidence.flow)
  const optionsEvidence = record(evidence.options)
  const nextProof = text(fusion.next_proof, 'Awaiting a meaningful temporal transition.')
  const action = text(fusion.action, 'WAIT')
  const locked = !marketClosed && (text(quality.state, '') === 'LOCKED' || state === 'DATA_LOCKED')
  const expected = finite(quality.expected_instruments)
  const fresh = finite(quality.fresh_instruments)
  const tracks = ['WATCH', 'SETUP', 'TRIGGER'].map((name) => [name, record(tracker[name])] as const).filter(([, value]) => Object.keys(value).length > 0)
  const activePlaybooks = Object.values(playbooks).map(record)

  return (
    <section className={styles.surface} data-tone={tone} data-reduced={reducedMotion ? 'true' : 'false'} aria-label="ARGUS Fusion Shadow research surface">
      <div className={styles.ambient} aria-hidden="true" />
      {toast && (
        <aside className={styles.toast} data-tone={toast.tone} role="status">
          <Sparkles size={15} aria-hidden="true" />
          <div><b>{toast.title}</b><span>{toast.message}</span></div>
        </aside>
      )}

      <header className={styles.topline}>
        <div className={styles.identity}>
          <span className={styles.liveDot} />
          <span>ARGUS MARKET STATE</span>
          <em>SHADOW · ZERO EXECUTION INFLUENCE</em>
        </div>
        <div className={styles.controls}>
          <span className={styles.dataHealth} data-locked={locked ? 'true' : 'false'}>{marketClosed || locked ? <LockKeyhole size={13} /> : <Activity size={13} />}{marketClosed ? 'MARKET CLOSED' : locked ? 'DATA LOCKED' : `DATA ${fresh ?? '—'}/${expected ?? '—'} LIVE`}</span>
          <button type="button" className={styles.soundButton} onClick={soundArmed ? () => setSoundArmed(false) : armAudio} aria-pressed={soundArmed}>
            {soundArmed ? <Volume2 size={14} /> : <Bell size={14} />} {soundArmed ? `ALERTS ARMED · ${soundLevel}` : 'ARM ALERTS'}
          </button>
          {soundArmed && <div className={styles.soundLevels} aria-label="Alert sound level">
            {(['LOW', 'MED', 'HIGH'] as const).map((level) => <button type="button" onClick={() => setSoundLevel(level)} data-active={soundLevel === level ? 'true' : 'false'} key={level}>{level}</button>)}
          </div>}
          <time>{timestamp(data.calculation_timestamp)}</time>
        </div>
      </header>

      <div className={styles.heroGrid}>
        <article className={styles.heroCard} data-state={state} key={stateEventId ?? 'initial'}>
          <span className={styles.kicker}>LIVE MARKET CHARACTER</span>
          <h1>{displayedHeroState}</h1>
          <p>{marketClosed ? `LAST VALID STATE · ${text(lastValid.hero_state, 'NOT AVAILABLE')} · LAST VALID AT ${timestamp(lastValid.source_timestamp ?? lastValid.calculation_timestamp)}` : text(hero.plain_language, 'Waiting for current canonical market evidence.')}</p>
          <div className={styles.oldNew}>
            <div><small>OLD STATE</small><b>{text(hero.previous_state, 'ESTABLISHING')}</b></div>
            <div className={styles.stateRail} style={{ '--rail-index': railIndex } as CSSProperties} aria-label={`Fusion state ${state}`}>
              <span className={styles.railSweep} /><span className={styles.railThumb} />
              {railStates.map((step, index) => <i key={step} data-active={index <= railIndex ? 'true' : 'false'}>{step}</i>)}
            </div>
            <div><small>NEW STATE</small><b>{state} {direction === 'BULLISH' ? '↑' : direction === 'BEARISH' ? '↓' : ''}</b></div>
          </div>
          <div className={styles.heroEvidence}>
            <EvidenceChip label="PRICE / FUTURES" value={priceEvidence.expansion === true ? 'EXPANDING' : priceEvidence.reclaim === true ? 'RECLAIMING' : priceEvidence.structural_hold === true ? 'HOLDING' : 'UNKNOWN'} />
            <EvidenceChip label="FLOW" value={text(flowEvidence.availability) === 'UNKNOWN' ? 'UNKNOWN' : flowEvidence.sellers_fading === true ? 'SELLERS FADING' : flowEvidence.buyers_fading === true ? 'BUYERS FADING' : 'NEUTRAL'} />
            <EvidenceChip label="OPTIONS" value={text(optionsEvidence.state)} />
            <EvidenceChip label="OSE" value={text(record(record(evidence.secondary_context).ose).state)} />
          </div>
        </article>

        <article className={styles.fusionCard}>
          <div className={styles.cardHead}><div><span>ARGUS FUSION · SHADOW</span><h2>{state} {direction === 'BULLISH' ? '↑' : direction === 'BEARISH' ? '↓' : ''}</h2></div><ShieldCheck size={22} aria-hidden="true" /></div>
          <p className={styles.fusionNarrative}>{text(fusion.plain_language, 'Waiting for independent temporal evidence.')}</p>
          <div className={styles.flowLine} data-direction={direction || 'NEUTRAL'} aria-label="Flow visual only">
            <Waves size={16} aria-hidden="true" />
            <span>{Array.from({ length: 10 }, (_, index) => <i key={index} style={{ '--particle-delay': `${index * 0.22}s` } as CSSProperties} />)}</span>
          </div>
          <div className={styles.progress} aria-label={`Fusion progress at ${state}`}>
            {railStates.map((step, index) => <div key={step} data-current={state === step ? 'true' : 'false'} data-passed={railIndex > index ? 'true' : 'false'}><i>{index < railIndex ? '✓' : index + 1}</i><span>{step}</span></div>)}
          </div>
          <div className={styles.nextProof}><Crosshair size={16} aria-hidden="true" /><div><span>NEXT PROOF</span><b>{nextProof}</b></div></div>
          <div className={styles.shadowAction}><span>ACTION</span><strong>{action}</strong><small>Research visualization only · no execution authority</small></div>
        </article>
      </div>

      <section className={styles.premiumSection} aria-label="Premium since state">
        <header><div><span>PREMIUM SINCE STATE</span><h2>State first. Outcome afterward.</h2></div><small>ASK at hypothetical entry · BID for live research exit</small></header>
        <div className={styles.premiumGrid}>
          {tracks.length ? tracks.map(([name, track]) => <PremiumState key={name} state={name} track={track} />) : <div className={styles.emptyPremium}>No WATCH / SETUP / TRIGGER snapshot exists yet. Fusion will never backfill one from a later premium move.</div>}
        </div>
      </section>

      <section className={styles.playbookSection}>
        <LiveLadder trade={newestTrade} />
        <details className={styles.quantDesk}>
          <summary><span>QUANT DESK · SHADOW</span><ChevronDown size={16} /></summary>
          <div className={styles.quantDeskBody}>
            <section><h3>PLAYBOOKS</h3>
            {activePlaybooks.map((playbook) => <article className={styles.playbook} key={text(playbook.family)}><div><b>{text(playbook.family).replaceAll('_', ' ')}</b><span data-state={text(playbook.lifecycle)}>{text(playbook.lifecycle)}</span></div><p>{text(playbook.reason)}</p><small>{text(playbook.direction, 'NO DIRECTION')} · {text(playbook.data_quality, 'QUALITY UNKNOWN')}</small></article>)}
            </section>
            <section><h3>TODAY&apos;S SHADOW TRADES <em>{tradeRows.length}</em></h3>
            {tradeRows.length ? tradeRows.map((trade) => <ShadowTrade key={text(trade.trade_id)} trade={trade} />) : <p className={styles.emptyDrawer}>No shadow trigger has opened a trade record. WATCH and SETUP are not trades.</p>}
            </section>
            <section><h3>EVIDENCE / FLOW LAB</h3><div className={styles.evidenceGrid}>
            <EvidenceDetail title="PRICE / FUTURES" evidence={priceEvidence} />
            <EvidenceDetail title="FLOW" evidence={flowEvidence} />
            <EvidenceDetail title="OPTIONS" evidence={optionsEvidence} />
            <EvidenceDetail title="SECONDARY" evidence={record(evidence.secondary_context)} />
            </div></section>
          </div>
        </details>
      </section>
      <footer className={styles.footer}><span>{FUSION_VERSION_LABEL}</span><span>{text(data.source_timestamp, 'SOURCE TIME UNKNOWN')}</span><span>{rows(history.recent_events).length} retained transitions · append-only shadow ledger</span></footer>
    </section>
  )
})

const FUSION_VERSION_LABEL = 'ARGUS_FUSION_SHADOW_V0_2 · PROSPECTIVE RESEARCH'

function EvidenceChip({ label, value }: { label: string; value: string }) {
  return <div className={styles.evidenceChip} data-tone={semanticTone(value)}><span>{label}</span><b>{value}</b></div>
}

function PremiumState({ state, track }: { state: string; track: JsonRecord }) {
  const event = record(track.state_event)
  const live = record(track.live)
  const entries = Object.values(record(live.entries)).map(record)
  return <article className={styles.premiumCard} data-state={state}>
    <header><span>SINCE {state}</span><time>{timestamp(event.state_timestamp)}</time></header>
    {entries.length ? entries.map((entry) => <div className={styles.premiumRow} key={text(entry.security_id)} data-side={text(entry.side)}><div><b>{text(entry.side)} {points(record(event.state_snapshot).focus_strike)}</b><small>{text(entry.security_id)} · ASK {price(entry.start_ask)}</small></div><div><strong>{price(entry.live_bid)}</strong><em>{percent(entry.premium_since_state_percent)}</em></div><div><small>MAX</small><b>{percent(entry.max_favorable_percent)}</b><small>MAE {percent(entry.max_adverse_percent)}</small></div></div>) : <p>No executable focus quote was frozen.</p>}
  </article>
}

function LiveLadder({ trade }: { trade: JsonRecord | null }) {
  const entry = record(trade?.entry)
  const targets = record(trade?.targets)
  const invalidation = finite(trade?.structural_invalidation)
  const entryFutures = finite(trade?.futures_trigger)
  const current = finite(trade?.live_futures) ?? entryFutures
  const targetValues = [invalidation, entryFutures, current, finite(targets.t1), finite(targets.t2), finite(targets.t3)].filter((value): value is number => value !== null)
  return <article className={styles.ladder} data-active={trade ? 'true' : 'false'}>
    <header><div><span>LIVE PRICE LADDER</span><h2>{trade ? `${text(trade.setup_family).replaceAll('_', ' ')} · ${text(trade.option_side)}` : 'NO LEVELS LOCKED'}</h2></div><span className={styles.ladderTruth}>{trade ? text(trade.status) : 'UNVALIDATED'}</span></header>
    {trade ? <><div className={styles.ladderLine}><LevelMarker label="INVALID" value={invalidation} values={targetValues} kind="invalid" /><LevelMarker label="ENTRY" value={entryFutures} values={targetValues} kind="entry" /><LevelMarker label="T1" value={finite(targets.t1)} values={targetValues} kind="target" /><LevelMarker label="T2" value={finite(targets.t2)} values={targetValues} kind="target" /><LevelMarker label="LIVE" value={current} values={targetValues} kind="current" /></div><div className={styles.ladderNotes}><span>OPTION ASK {price(entry.ask)}</span><span>LIVE BID {price(trade.live_bid)}</span><span>P&amp;L {finite(trade.shadow_pnl_rupees) === null ? 'UNAVAILABLE' : price(trade.shadow_pnl_rupees)}</span><span>R {finite(trade.current_r)?.toFixed(2) ?? 'UNVALIDATED'}</span><span>MFE {percent(trade.mfe_percent)} · MAE {percent(trade.mae_percent)}</span></div></> : <p>Structural invalidation and targets only appear when already supplied by an authoritative existing structure. Fusion does not invent them.</p>}
  </article>
}

function LevelMarker({ label, value, values, kind }: { label: string; value: number | null; values: number[]; kind: string }) {
  const minimum = values.length ? Math.min(...values) : 0
  const maximum = values.length ? Math.max(...values) : 1
  const position = value === null || maximum === minimum ? 50 : 8 + ((value - minimum) / (maximum - minimum)) * 84
  return <div className={styles.levelMarker} data-kind={kind} style={{ left: `${position}%` }}><i /><span>{label}</span><b>{points(value)}</b></div>
}

function ShadowTrade({ trade }: { trade: JsonRecord }) {
  const entry = record(trade.entry)
  const targets = record(trade.targets)
  return <article className={styles.trade}><header><span>{timestamp(trade.trigger_time)}</span><b>{text(trade.option_side)} {points(trade.strike)} · {text(trade.setup_family).replaceAll('_', ' ')}</b><em>{text(trade.status)}</em></header><div><Metric label="ENTRY ASK" value={price(entry.ask)} /><Metric label="LIVE BID" value={price(trade.live_bid)} /><Metric label="P&L ₹" value={finite(trade.shadow_pnl_rupees) === null ? 'UNAVAILABLE' : price(trade.shadow_pnl_rupees)} /><Metric label="INVALID" value={points(trade.structural_invalidation)} /><Metric label="T1 / T2" value={`${points(targets.t1)} / ${points(targets.t2)}`} /><Metric label="MFE / MAE" value={`${percent(trade.mfe_percent)} / ${percent(trade.mae_percent)}`} /><Metric label="R" value={finite(trade.current_r)?.toFixed(2) ?? 'UNVALIDATED'} /></div></article>
}

function Metric({ label, value }: { label: string; value: string }) { return <span><small>{label}</small><b>{value}</b></span> }

function EvidenceDetail({ title, evidence }: { title: string; evidence: JsonRecord }) {
  const entries = Object.entries(evidence).filter(([, value]) => typeof value !== 'object')
  return <article><h3>{title}</h3>{entries.length ? entries.map(([key, value]) => <p key={key}><span>{key.replaceAll('_', ' ')}</span><b>{typeof value === 'boolean' ? value ? 'OBSERVED' : 'NOT OBSERVED' : text(value)}</b></p>) : <p><span>status</span><b>UNKNOWN</b></p>}</article>
}

declare global { interface Window { webkitAudioContext?: typeof AudioContext } }
