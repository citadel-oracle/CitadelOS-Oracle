'use client'

import { memo, useEffect, useRef, useState, type CSSProperties } from 'react'
import { motion, useReducedMotion } from 'framer-motion'

import {
  useOracleStore,
  type OracleEvidenceObservation,
  type OracleOptionDisplay,
  type OracleShadowVariant,
  type OracleVobEpisode,
  type OracleVobLevel,
  type VobTimeframe,
} from '@/dashboard/store/oracleStore'

import styles from './VobPullbackCommand.module.css'
import {
  acceptSemanticEvent,
  auraTone,
  magnetGeometry,
  pnlTone,
  proximityLabel,
  readBooleanPreference,
  semanticAlert,
  writeBooleanPreference,
  type AlertKind,
  type SemanticFrame,
} from './vobPresentation'

const UNKNOWN = 'UNKNOWN'
const ALERTS_KEY = 'citadel.vob.alerts'
const SOUND_KEY = 'citadel.vob.sound'
const NOTIFICATION_ASKED_KEY = 'citadel.vob.notification-asked'
const PREFERENCE_EVENT = 'citadel-vob-preference'
const UNKNOWN_OBSERVATION: OracleEvidenceObservation = Object.freeze({
  state: UNKNOWN,
  revision: '0',
  eventTime: null,
  receiveTime: null,
  persistence: null,
  persistenceState: UNKNOWN,
  quality: UNKNOWN,
  known: false,
})

export const VobPullbackCommand = memo(function VobPullbackCommand() {
  return (
    <section className={styles.command} aria-label="CITADEL VOB Pullback Command" data-vob-pullback-command>
      <AuraLayer />
      <VobAlertController />
      <span className={styles.cornerTop} aria-hidden="true" />
      <span className={styles.cornerBottom} aria-hidden="true" />
      <CommandHeader />
      <HistoricalReplayBanner />
      <RuntimeStrip />
      <ContractTruthStrip />
      <TopCommandDeck />
      <MarketStory />
      <div className={styles.decisionDeck}>
        <div className={styles.decisionColumn}><RecoveryEngine /><EvidenceStory /></div>
        <ArgusConfirmation />
      </div>
      <div className={styles.structureDeck}><VobLevels /><MatchedComparison /></div>
      <div className={styles.closureDeck}><Lifecycle /><ExperimentScoreboard /></div>
      <footer className={styles.footer}>
        <span>RESEARCH ONLY · PAPER ONLY · EXECUTION INFLUENCE ZERO</span>
        <span>ENTRY / SL / TARGET AUTHORITY · PULLBACK MASTER</span>
      </footer>
    </section>
  )
})

const HistoricalReplayBanner = memo(function HistoricalReplayBanner() {
  const replay = useOracleStore((state) => state.replay)
  const step = useOracleStore((state) => state.stepHistoricalReplay)
  const exit = useOracleStore((state) => state.exitHistoricalReplay)
  if (replay.mode !== 'HISTORICAL_REPLAY' || replay.index < 0) return null
  const frame = replay.frames[replay.index]
  if (!frame) return null
  return (
    <aside className={styles.replayBanner} aria-label="Historical replay controls" data-historical-replay>
      <div><strong>HISTORICAL REPLAY</strong><span>{replay.index + 1} / {replay.frames.length} · {formatTime(frame.timestamp)}</span></div>
      <dl>
        <div><dt>DATE</dt><dd>{frame.date}</dd></div>
        <div><dt>CONTRACT</dt><dd>{frame.contract}</dd></div>
        <div><dt>TIMEFRAME</dt><dd>{frame.timeframe}</dd></div>
        <div><dt>EPISODE ID</dt><dd>{frame.episodeId}</dd></div>
      </dl>
      <nav aria-label="Replay stepping">
        <button type="button" onClick={() => step(replay.index - 1)} disabled={replay.index === 0}>PREV</button>
        <button type="button" onClick={() => step(replay.index + 1)} disabled={replay.index === replay.frames.length - 1}>NEXT</button>
        <button type="button" onClick={exit}>EXIT REPLAY</button>
      </nav>
    </aside>
  )
})

const CommandHeader = memo(function CommandHeader() {
  const episodeId = useOracleStore((state) => state.vob.episode?.episodeId ?? null)
  const revision = useOracleStore((state) => state.runtime.revision)
  const receiveTimestamp = useOracleStore((state) => state.runtime.receiveTimestamp)
  const replayMode = useOracleStore((state) => state.replay.mode)
  return (
    <header className={styles.header}>
      <div><span>OPTION-PREMIUM VOB · FAILED AGGRESSION · MATCHED RESEARCH</span><h2>CITADEL · VOB PULLBACK COMMAND</h2></div>
      <div className={styles.headerTruth} title={episodeId ? `Episode ${episodeId}` : 'No canonical VOB episode reported'}>
        <b>{replayMode === 'HISTORICAL_REPLAY' ? 'HISTORICAL REPLAY' : episodeId ? 'CANONICAL EPISODE' : 'EPISODE WAIT'}</b>
        <span>REV {revision >= 0 ? revision : '—'} · RECEIVED {formatTime(receiveTimestamp)}</span>
      </div>
    </header>
  )
})

const RuntimeStrip = memo(function RuntimeStrip() {
  const market = useOracleStore((state) => state.market)
  const runtime = useOracleStore((state) => state.runtime)
  const historical = useOracleStore((state) => state.replay.mode === 'HISTORICAL_REPLAY')
  return (
    <div className={styles.runtimeStrip} aria-label="VOB runtime and market state">
      <RuntimeItem label="NIFTY" value={formatNumber(market.underlying)} />
      <RuntimeItem label="MARKET" value={market.marketStatus} />
      <RuntimeItem label="DATA" value={historical ? 'HISTORICAL' : market.dataFreshness} title={`VOB ${runtime.vobFreshness} · REVERSAL ${runtime.reversalFreshness} · DECISION ${runtime.decisionFreshness}`} />
      <RuntimeItem label="RUNTIME" value={runtime.latencyMs === null ? UNKNOWN : `${formatNumber(runtime.latencyMs)} MS`} />
      <AlertControls />
    </div>
  )
})

const ContractTruthStrip = memo(function ContractTruthStrip() {
  const referencePrice = useOracleStore((state) => state.market.underlying)
  const atmStrike = useOracleStore((state) => state.market.canonicalAtmStrike)
  const strikeInterval = useOracleStore((state) => state.market.strikeInterval)
  const historical = useOracleStore((state) => state.replay.mode === 'HISTORICAL_REPLAY')
  return (
    <section className={styles.contractTruthStrip} aria-label="Current canonical ITM-1 contract authority" data-current-itm1-authority>
      <CurrentItmQuote optionType="CE" side="CALL" />
      <CurrentItmQuote optionType="PE" side="PUT" />
      <ContractTruthItem label="ATM" value={formatNumber(atmStrike)} title="Canonical ARGUS/Upstox option-chain ATM" />
      <ContractTruthItem label="REF PRICE" value={formatNumber(referencePrice)} />
      <ContractTruthItem label="STRIKE STEP" value={formatNumber(strikeInterval)} />
      {historical
        ? <p><b>REPLAY ITM-1</b> = resolver pair at this replay timestamp. <span>FROZEN</span> = contracts captured when this VOB episode was created.</p>
        : <p><b>CURRENT ITM-1</b> = live resolver pair right now. <span>FROZEN</span> = contracts captured when this VOB episode was created.</p>}
    </section>
  )
})

const CurrentItmQuote = memo(function CurrentItmQuote({ optionType, side }: { optionType: 'CE' | 'PE'; side: 'CALL' | 'PUT' }) {
  const option = useOracleStore((state) => optionType === 'CE' ? state.market.currentItmCall : state.market.currentItmPut)
  const historical = useOracleStore((state) => state.replay.mode === 'HISTORICAL_REPLAY')
  const previousPrice = useRef<number | null>(null)
  const [tick, setTick] = useState<'up' | 'down' | 'flat'>('flat')

  useEffect(() => {
    if (option.premium === null) return
    const previous = previousPrice.current
    previousPrice.current = option.premium
    if (previous === null || previous === option.premium) return
    setTick(option.premium > previous ? 'up' : 'down')
    const timer = window.setTimeout(() => setTick('flat'), 520)
    return () => window.clearTimeout(timer)
  }, [option.premium])

  return (
    <article
      className={styles.currentItmQuote}
      data-option={optionType}
      data-contract-security-id={option.contract.securityId ?? 'UNKNOWN'}
      data-quote-security-id={option.quoteSecurityId ?? 'UNKNOWN'}
      data-vob-security-id={option.vobSecurityId ?? 'NONE'}
      data-testid={`current-itm1-${optionType.toLowerCase()}-quote`}
      title={option.contract.securityId ?? undefined}
    >
      <header><span>{historical ? 'REPLAY' : 'CURRENT'} ITM-1 {side}</span><b>{contractLabel(option.contract.strike, option.contract.optionType)}</b></header>
      <strong data-tick={tick} data-price-role="current-itm1" data-option={optionType}>{formatMoney(option.premium)}</strong>
      <dl><div><dt>BID</dt><dd>{formatMoney(option.bid)}</dd></div><div><dt>ASK</dt><dd>{formatMoney(option.ask)}</dd></div></dl>
      <small>QUOTE ID {option.quoteSecurityId ?? 'UNKNOWN'} · {formatTime(option.quoteTimestamp)}</small>
      <em>CURRENT CONTRACT VOB · {option.vobSecurityId === null ? 'UNKNOWN' : formatRange(option.zoneBottom, option.zoneTop)}</em>
    </article>
  )
})

function ContractTruthItem({ label, value, title }: { label: string; value: string; title?: string }) {
  return <div title={title}><span>{label}</span><strong>{value}</strong></div>
}

function RuntimeItem({ label, value, title }: { label: string; value: string; title?: string }) {
  return <div title={title}><span>{label}</span><b data-truth={truthTone(value)}>{value}</b></div>
}

const AlertControls = memo(function AlertControls() {
  const [alerts, setAlerts] = useBooleanPreference(ALERTS_KEY)
  const [sound, setSound] = useBooleanPreference(SOUND_KEY)
  const toggleAlerts = async () => {
    const next = !alerts
    setAlerts(next)
    const alreadyAsked = readBooleanPreference(window.localStorage, NOTIFICATION_ASKED_KEY)
    if (next && !alreadyAsked && typeof Notification !== 'undefined' && Notification.permission === 'default') {
      writeBooleanPreference(window.localStorage, NOTIFICATION_ASKED_KEY, true)
      try { await Notification.requestPermission() } catch { /* in-app alerts remain authoritative */ }
    }
  }
  const toggleSound = () => {
    const next = !sound
    setSound(next)
    if (next) void playAlertTone('READY', true)
  }
  return (
    <div className={styles.alertControls} aria-label="VOB alert controls">
      <button type="button" aria-pressed={alerts} onClick={() => void toggleAlerts()}><span>ALERTS</span><b>{alerts ? 'ON' : 'OFF'}</b></button>
      <button type="button" aria-pressed={sound} onClick={toggleSound}><span>🔊 SOUND</span><b>{sound ? 'ON' : 'OFF'}</b></button>
    </div>
  )
})

const AuraLayer = memo(function AuraLayer() {
  const frame = useSemanticFrame()
  return <div className={styles.aura} data-aura={auraTone(frame)} aria-hidden="true"><i /><i /><i /><i /></div>
})

const VobAlertController = memo(function VobAlertController() {
  const frame = useSemanticFrame()
  const [alerts] = useBooleanPreference(ALERTS_KEY)
  const [sound] = useBooleanPreference(SOUND_KEY)
  const historical = useOracleStore((state) => state.replay.mode === 'HISTORICAL_REPLAY')
  const [toast, setToast] = useState<ReturnType<typeof semanticAlert>>(null)
  const previous = useRef<SemanticFrame | null>(null)
  const seen = useRef(new Set<string>())

  useEffect(() => {
    const prior = previous.current
    previous.current = frame
    if (!prior || historical) return
    const event = semanticAlert(prior, frame)
    if (!acceptSemanticEvent(seen.current, event) || !event) return
    setToast(event)
    window.setTimeout(() => setToast((current) => current?.key === event.key ? null : current), 4400)
    if (alerts && typeof Notification !== 'undefined' && Notification.permission === 'granted' && (document.hidden || !document.hasFocus())) {
      new Notification(event.title, { body: [event.detail, event.reason].filter(Boolean).join('\n'), tag: event.key, silent: sound })
    }
    if (sound) void playAlertTone(event.kind)
  }, [alerts, frame, historical, sound])

  if (!toast) return null
  return (
    <aside className={styles.toast} data-tone={toast.tone} role="status" aria-live="polite">
      <i aria-hidden="true" /><div><strong>{toast.title}</strong><span>{toast.detail}</span><small>{toast.reason}</small></div>
    </aside>
  )
})

function useSemanticFrame(): SemanticFrame {
  const episodeId = useOracleStore((state) => state.vob.episode?.episodeId ?? null)
  const timeframe = useOracleStore((state) => state.vob.episode?.timeframe ?? null)
  const revision = useOracleStore((state) => state.runtime.revision)
  const reversalState = useOracleStore((state) => state.reversal.state)
  const vobState = useOracleStore((state) => state.reversal.vobState)
  const direction = useOracleStore((state) => state.reversal.direction)
  const option = useOracleStore((state) => direction === 'PUT' ? state.market.currentItmPut : state.market.currentItmCall)
  const variant = useOracleStore((state) => state.trade.variants.CONFIRMED_REVERSAL ?? state.trade.variants.VOB_ONLY ?? null)
  return {
    episodeId, revision, reversalState, vobState, direction,
    contract: contractLabel(option.contract.strike, option.contract.optionType),
    premium: option.premium, timeframe,
    entryTime: variant?.entryTime ?? null,
    exitTime: variant?.exitTime ?? null,
    exitReason: variant?.exitReason ?? null,
    pnl: variant?.pnl ?? null,
  }
}

function useBooleanPreference(key: string): [boolean, (value: boolean) => void] {
  const [value, setValue] = useState(() => typeof window === 'undefined' ? false : readBooleanPreference(window.localStorage, key))
  useEffect(() => {
    const sync = () => setValue(readBooleanPreference(window.localStorage, key))
    window.addEventListener(PREFERENCE_EVENT, sync)
    window.addEventListener('storage', sync)
    return () => { window.removeEventListener(PREFERENCE_EVENT, sync); window.removeEventListener('storage', sync) }
  }, [key])
  return [value, (next) => {
    writeBooleanPreference(window.localStorage, key, next)
    setValue(next)
    window.dispatchEvent(new Event(PREFERENCE_EVENT))
  }]
}

async function playAlertTone(kind: AlertKind, preview = false): Promise<void> {
  if (typeof window === 'undefined' || !window.AudioContext) return
  const context = new window.AudioContext()
  if (context.state === 'suspended') await context.resume()
  const patterns: Record<AlertKind, readonly [number, number][]> = {
    READY: [[523, 0], [659, .12]], ENTRY: [[587, 0], [784, .1]],
    EXIT: [[659, 0], [440, .1]], TARGET: [[659, 0], [880, .1]],
    STOP: [[330, 0], [220, .12]], BROKEN: [[294, 0], [196, .12]],
  }
  const now = context.currentTime
  patterns[kind].forEach(([frequency, delay]) => {
    const oscillator = context.createOscillator()
    const gain = context.createGain()
    oscillator.type = 'sine'
    oscillator.frequency.value = frequency
    gain.gain.setValueAtTime(0.0001, now + delay)
    gain.gain.exponentialRampToValueAtTime(preview ? .025 : .045, now + delay + .012)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + delay + .15)
    oscillator.connect(gain).connect(context.destination)
    oscillator.start(now + delay)
    oscillator.stop(now + delay + .17)
  })
  window.setTimeout(() => void context.close(), 520)
}

const TopCommandDeck = memo(function TopCommandDeck() {
  const direction = useOracleStore((state) => state.reversal.direction)
  const historical = useOracleStore((state) => state.replay.mode === 'HISTORICAL_REPLAY')
  return (
    <section className={styles.topDeck} aria-label={historical ? 'Historical replay VOB command deck' : 'Live VOB command deck'}>
      <LiveOptionCard side="CALL" optionType="CE" target={direction === 'CALL'} />
      <Hero />
      <LiveOptionCard side="PUT" optionType="PE" target={direction === 'PUT'} />
    </section>
  )
})

const LiveOptionCard = memo(function LiveOptionCard({ side, optionType, target }: { side: 'CALL' | 'PUT'; optionType: 'CE' | 'PE'; target: boolean }) {
  const option = useOracleStore((state) => optionType === 'CE' ? state.market.currentItmCall : state.market.currentItmPut)
  const currentItm1 = useOracleStore((state) => optionType === 'CE' ? state.market.activeCe : state.market.activePe)
  const historical = useOracleStore((state) => state.replay.mode === 'HISTORICAL_REPLAY')
  const reducedMotion = useReducedMotion()
  const previousPrice = useRef<number | null>(null)
  const [tick, setTick] = useState<'up' | 'down' | 'flat'>('flat')
  const geometry = magnetGeometry(option)
  const contract = contractLabel(option.contract.strike, option.contract.optionType)
  const frozen = option.contractStatus === 'FROZEN_EPISODE'
  const currentDiffers = frozen && option.contract.securityId !== currentItm1.securityId
  const roleLabel = frozen ? `FROZEN EPISODE ${optionType}` : option.contractStatus === 'CURRENT_ITM1' ? `CURRENT ITM-1 ${optionType}` : `${side} CONTRACT`
  const distance = proximityLabel(option)

  useEffect(() => {
    if (option.premium === null) return
    const previous = previousPrice.current
    previousPrice.current = option.premium
    if (previous === null || previous === option.premium) return
    setTick(option.premium > previous ? 'up' : 'down')
    const timer = window.setTimeout(() => setTick('flat'), 520)
    return () => window.clearTimeout(timer)
  }, [option.premium])

  return (
    <article className={styles.optionCard} data-option={optionType} data-target={target} data-contract-status={frozen ? 'frozen' : 'current'} data-contract-security-id={option.contract.securityId ?? 'UNKNOWN'} data-quote-security-id={option.quoteSecurityId ?? 'UNKNOWN'} data-vob-security-id={option.vobSecurityId ?? 'NONE'} data-testid={`itm1-${optionType.toLowerCase()}-card`}>
      <header>
        <div><span>{roleLabel}</span><h3>{contract}</h3></div>
        <b data-status={frozen ? 'frozen' : 'current'}>{frozen ? 'FROZEN EPISODE CONTRACT' : option.contractStatus.replaceAll('_', ' ')}</b>
      </header>
      <div className={styles.currentItmReference} title={currentItm1.securityId ?? undefined} data-mismatch={currentDiffers}>
          {historical ? <span>REPLAY ITM-1 {optionType}</span> : <span>CURRENT ITM-1 {optionType}</span>}
          <b>{contractLabel(currentItm1.strike, currentItm1.optionType)}</b>
          <em>{currentDiffers ? 'CURRENT != FROZEN' : 'CURRENT = DISPLAYED'}</em>
      </div>
      <p className={styles.contractBinding} data-contract-binding={frozen ? 'frozen' : 'current'}>
        QUOTE · VOB · DISTANCE → {frozen ? `FROZEN ${optionType} ${contract}` : `CURRENT ITM-1 ${optionType}`}
      </p>
      <span className={styles.frozenQuoteLabel}>{historical ? 'HISTORICAL CONTRACT PREMIUM' : frozen ? 'FROZEN CONTRACT LIVE PREMIUM' : 'CURRENT CONTRACT LIVE PREMIUM'}</span>
      <div className={styles.optionQuote}>
        <strong data-tick={tick} data-price-role="frozen-episode" data-option={optionType}>{formatMoney(option.premium)}</strong>
        <dl><div><dt>BID</dt><dd>{formatMoney(option.bid)}</dd></div><div><dt>ASK</dt><dd>{formatMoney(option.ask)}</dd></div></dl>
      </div>
      <div className={styles.optionTruth}>
        <span data-truth={truthTone(option.freshness)}>{option.freshness}</span>
        <time>{formatTime(option.quoteTimestamp)}</time>
        <span title={option.quoteSource ?? undefined}>{option.contract.securityId ?? 'NO SECURITY ID'}</span>
      </div>
      <div className={styles.optionZone}>
        <span>{option.vobTimeframe ?? '—'} VOB · {option.zoneRole}</span>
        <b>{formatRange(option.zoneBottom, option.zoneTop)}</b>
        <em data-inside={option.insideZone === true}>{distance}{option.distancePct === null ? '' : ` · ${option.distancePct.toFixed(2)}%`}</em>
      </div>
      <MagnetRail option={option} geometry={geometry} reducedMotion={Boolean(reducedMotion)} historical={historical} />
    </article>
  )
})

function MagnetRail({ option, geometry, reducedMotion, historical }: { option: OracleOptionDisplay; geometry: ReturnType<typeof magnetGeometry>; reducedMotion: boolean; historical: boolean }) {
  return (
    <div className={styles.magnetRail} data-ready={geometry !== null} aria-label={`Premium proximity ${proximityLabel(option)}`}>
      <span>{historical ? 'HISTORICAL PREMIUM' : option.contractStatus === 'FROZEN_EPISODE' ? 'FROZEN LIVE PREMIUM' : 'CURRENT LIVE PREMIUM'}</span><span>VOB MAGNET</span>
      <i className={styles.magnetLine}>
        {geometry && <b className={styles.magnetZone} style={{ left: `${geometry.zoneStartPct}%`, width: `${Math.max(3, geometry.zoneEndPct - geometry.zoneStartPct)}%` }} />}
        {geometry && <motion.em className={styles.magnetOrb} initial={false} animate={{ left: `${geometry.pricePct}%` }} transition={reducedMotion ? { duration: 0 } : { type: 'spring', stiffness: 170, damping: 24, mass: .65 }} />}
      </i>
      <small>{option.nearestZoneBoundary === null ? 'BOUNDARY —' : `NEAREST ${formatMoney(option.nearestZoneBoundary)}`}</small>
    </div>
  )
}

const Hero = memo(function Hero() {
  const state = useOracleStore((store) => store.reversal.state)
  const direction = useOracleStore((store) => store.reversal.direction)
  const quality = useOracleStore((store) => store.reversal.quality)
  const vobState = useOracleStore((store) => store.reversal.vobState)
  const scores = useOracleStore((store) => store.reversal.displayScores)
  const argus = useOracleStore((store) => store.reversal.evidence.argus_confirmation?.state ?? UNKNOWN)
  const action = actionLabel(state, direction, vobState)
  return (
    <div className={styles.hero}>
      <span className={styles.heroEyebrow}>ACTIVE OPPORTUNITY</span>
      <div className={styles.heroCore}>
        <div className={styles.wheelColumn}>
          <div className={styles.wheel} data-state={state}>
            <div><span>{quality}</span><strong>{scores.overall === null ? '—' : Math.round(scores.overall)}</strong><b>{action}</b></div>
          </div>
          <small>BACKEND STATE · SCORE DISPLAY ONLY</small>
        </div>
        <div className={styles.heroReadout}>
          <span>REVERSAL COMMAND</span>
          <h3>{action}</h3>
          <p>{heroCopy(state, direction)}</p>
        </div>
      </div>
      <div className={styles.heroBars}>
        <HolographicBar label="VOB SETUP" value={vobState} score={scores.vobSetup} />
        <HolographicBar label="TURN STRENGTH" value={friendlyState(state)} score={scores.turnStrength} />
        <HolographicBar label="MARKET SUPPORT" value={friendlyArgus(argus)} score={scores.marketSupport} />
      </div>
      <PriceRail />
    </div>
  )
})

function HolographicBar({ label, value, score }: { label: string; value: string; score: number | null }) {
  const width = score === null ? '0%' : `${Math.max(0, Math.min(100, score))}%`
  return (
    <div className={styles.holoMetric} data-known={score !== null}>
      <div><span>{label}</span><b>{value}</b></div>
      <div className={styles.holoTrack} role={score === null ? undefined : 'meter'} aria-label={`${label} ${value}`} aria-valuenow={score ?? undefined} aria-valuemin={score === null ? undefined : 0} aria-valuemax={score === null ? undefined : 100}>
        <i style={{ '--metric-width': width } as CSSProperties} />
      </div>
    </div>
  )
}

const MarketStory = memo(function MarketStory() {
  const episode = useOracleStore((state) => state.vob.episode)
  const evidence = useOracleStore((state) => state.reversal.evidence)
  const direction = useOracleStore((state) => state.reversal.direction)
  const turnStrength = useOracleStore((state) => state.reversal.displayScores.turnStrength)
  const reducedMotion = useReducedMotion()
  const story = buildStory(episode?.timeframe ?? null, episode?.touchAt ?? null, direction, evidence)
  const controlPosition = turnStrength === null ? 50 : Math.max(4, Math.min(96, turnStrength))
  return (
    <section className={styles.story} aria-label="Simple market story">
      <span>MARKET STORY</span>
      <div>{story.map((item, index) => <span key={`${item}-${index}`} data-ignited={item !== 'WAITING FOR CANONICAL EVIDENCE'} data-kind={item.includes('VOB TOUCHED') ? 'touch' : 'evidence'}><b>{item}</b>{index < story.length - 1 && <i>→</i>}</span>)}</div>
      <div className={styles.transferTrail} data-known={turnStrength !== null}><small>SELLERS</small><i><motion.b initial={false} animate={{ left: `${controlPosition}%` }} transition={reducedMotion ? { duration: 0 } : { type: 'spring', stiffness: 145, damping: 25 }} /></i><small>BUYERS</small></div>
    </section>
  )
})

const PriceRail = memo(function PriceRail() {
  const trade = useOracleStore((state) => state.trade)
  const values = [trade.slRef, trade.entryRef, trade.currentRef, trade.targetRef].filter((value): value is number => value !== null)
  const ready = values.length >= 2
  return (
    <section className={styles.priceRail} data-levels-locked={ready}>
      <header><span>PRICE RAIL · {trade.authority}</span><b>{ready ? 'CANONICAL LEVELS LOCKED' : 'NO LEVELS LOCKED'}</b></header>
      <div className={styles.railCanvas}>
        <i className={styles.railLine} />
        <RailMarker label="SL" value={trade.slRef} values={values} tone="stop" />
        <RailMarker label="BUY / ENTRY" value={trade.entryRef} values={values} tone="entry" />
        <RailMarker label="NOW" value={trade.currentRef} values={values} tone="now" />
        <RailMarker label="TARGET" value={trade.targetRef} values={values} tone="target" />
      </div>
      <div className={styles.railFooter}><span>RR</span><b>{formatR(trade.rr)}</b><span>CONTRACT</span><b>{trade.contract.securityId ?? 'NOT FROZEN'}</b></div>
    </section>
  )
})

function RailMarker({ label, value, values, tone }: { label: string; value: number | null; values: number[]; tone: string }) {
  const reducedMotion = useReducedMotion()
  if (value === null) return null
  return <motion.i className={styles.railMarker} data-tone={tone} initial={false} animate={{ left: railPosition(value, values) }} transition={reducedMotion ? { duration: 0 } : { type: 'spring', stiffness: 145, damping: 24 }}><b>{label}</b><span>{formatNumber(value)}</span></motion.i>
}

const RecoveryEngine = memo(function RecoveryEngine() {
  const evidence = useOracleStore((state) => state.reversal.evidence)
  const direction = useOracleStore((state) => state.reversal.direction)
  const state = useOracleStore((store) => store.reversal.state)
  const control = controlLabel(direction, state)
  const failed = observation(evidence, 'failed_aggression')
  const flow = observation(evidence, 'order_flow_rotation')
  const futures = observation(evidence, 'futures_response')
  const turnStrength = useOracleStore((store) => store.reversal.displayScores.turnStrength)
  const reducedMotion = useReducedMotion()
  return (
    <section className={styles.recovery}>
      <header><div><span>RECOVERY ENGINE · SELLER ↔ BUYER CONTROL</span><h3>{control}</h3></div><b>CANONICAL EVIDENCE</b></header>
      <div className={styles.controlMeter} data-known={turnStrength !== null}>
        <span>SELLERS</span><i><span className={styles.sellerLiquid} /><span className={styles.buyerLiquid} /><motion.b initial={false} animate={{ left: `${turnStrength === null ? 50 : Math.max(4, Math.min(96, turnStrength))}%` }} transition={reducedMotion ? { duration: 0 } : { type: 'spring', stiffness: state === 'REVERSAL_READY' ? 190 : 125, damping: 22 }} /></i><span>BUYERS</span>
        <em>{control}{turnStrength === null ? ' · MAGNITUDE NOT REPORTED' : ` · ${Math.round(turnStrength)}`}</em>
      </div>
      <div className={styles.headlineDiagnostics}>
        <Diagnostic label="SELLER PRESSURE" value={failed.state} known={failed.known} />
        <Diagnostic label="BUYER SUPPORT" value={flow.state} known={flow.known} />
        <Diagnostic label="FUTURES" value={futures.state} known={futures.known} />
      </div>
      <details className={styles.flowDetails}>
        <summary>FLOW DETAILS <span>CANONICAL EVIDENCE ▾</span></summary>
        <div>
          <EvidenceBar label="Seller Pressure" technical="signed aggression / response quality" value={failed} />
          <EvidenceBar label="Bid Support" technical="book pressure / refill" value={flow} />
          <EvidenceBar label="Sell-side Depth" technical="depletion / depth behavior" value={flow} />
          <EvidenceBar label="Price Turn" technical="microprice / response" value={flow} />
          <EvidenceBar label="Futures Turn" technical="futures response" value={futures} />
          <EvidenceBar label="Option Response" technical="CE / PE confirmation" value={observation(evidence, 'target_option_wakeup')} />
        </div>
      </details>
    </section>
  )
})

function Diagnostic({ label, value, known }: { label: string; value: string; known: boolean }) {
  return <div><span>{label}</span><b data-known={known}>{known ? value : UNKNOWN}</b></div>
}

function EvidenceBar({ label, technical, value }: { label: string; technical: string; value: OracleEvidenceObservation }) {
  return (
    <div className={styles.evidenceBar} data-known={value.known} title={`${technical} · revision ${value.revision}`}>
      <div><span>{label}</span><small>{technical}</small></div><b>{value.known ? value.state : UNKNOWN}</b><i><em /></i>
    </div>
  )
}

const EvidenceStory = memo(function EvidenceStory() {
  const evidence = useOracleStore((state) => state.reversal.evidence)
  const direction = useOracleStore((state) => state.reversal.direction)
  const rows = evidenceStory(direction, evidence)
  return (
    <section className={styles.evidenceStory}>
      <header><span>FAILED AGGRESSION + OPTIONS</span><b>PARALLEL EVIDENCE</b></header>
      <div>{rows.map((row) => <div key={row.label} data-ignited={row.known}><span>{row.label}</span><b data-known={row.known}>{row.value}</b></div>)}</div>
    </section>
  )
})

const ArgusConfirmation = memo(function ArgusConfirmation() {
  const argus = useOracleStore((state) => observation(state.reversal.evidence, 'argus_confirmation'))
  const flow = useOracleStore((state) => observation(state.reversal.evidence, 'order_flow_rotation'))
  const oi = useOracleStore((state) => observation(state.reversal.evidence, 'oi_context'))
  const futures = useOracleStore((state) => observation(state.reversal.evidence, 'futures_response'))
  const support = useOracleStore((state) => state.reversal.displayScores.marketSupport)
  const supportPosition = `${support === null ? 50 : Math.max(0, Math.min(100, support))}%`
  return (
    <section className={styles.argus}>
      <div>
        <span>MARKET SUPPORT</span>
        <div className={styles.contextMeter} data-known={support !== null}><i style={{ '--support-position': supportPosition } as CSSProperties}><b /></i></div>
        <div className={styles.contextLabels}><small>AGAINST TRADE</small><small>SUPPORTING TRADE</small></div>
        <span>ARGUS SUPPORT</span><h3>{argus.known ? friendlyArgus(argus.state) : UNKNOWN}</h3><p>QUALITY / CONTEXT CONFIRMATION · NOT A HARD GATE</p>
      </div>
      <details><summary>WHY <span>▾</span></summary><ul>
        <li><span>Pressure → Price</span><b>{flow.known ? flow.state : UNKNOWN}</b></li>
        <li><span>Futures Confirmation</span><b>{futures.known ? futures.state : UNKNOWN}</b></li>
        <li><span>OI Migration / Structural Shift</span><b>{oi.known ? oi.state : UNKNOWN}</b></li>
        <li><span>ARGUS Flow confirmation</span><b>{argus.known ? argus.state : UNKNOWN}</b></li>
      </ul></details>
    </section>
  )
})

const VobLevels = memo(function VobLevels() {
  const levels = useOracleStore((state) => state.vob.levels)
  const episodeId = useOracleStore((state) => state.vob.episode?.episodeId ?? null)
  return (
    <section className={styles.levels}>
      <header><span>VOB LEVELS</span><b>{episodeId ? `EPISODE ${episodeId.slice(-8)}` : 'NO PRIMARY EPISODE'}</b></header>
      <div>{levels.map((row) => <VobLevelRow key={row.timeframe} row={row} />)}</div>
    </section>
  )
})

function VobLevelRow({ row }: { row: OracleVobLevel }) {
  const sourceTitle = `${row.timeframe} lineage: ${row.sourceLineage.join(' / ')} · reported: ${row.reportedSource ?? UNKNOWN} · alignment: ${row.alignment}`
  return (
    <div className={styles.levelRow} data-primary={row.primary} title={sourceTitle}>
      <strong>{row.timeframe}</strong><span>{formatRange(row.zoneBottom, row.zoneTop)}</span><b>{row.state}</b><time>{formatTime(row.touchAt)}</time><em>{row.primary ? `${row.role} · PRIMARY ★` : row.role}</em>
    </div>
  )
}

const MatchedComparison = memo(function MatchedComparison() {
  const baseline = useOracleStore((state) => state.trade.variants.VOB_ONLY ?? null)
  const early = useOracleStore((state) => state.trade.variants.EARLY_REVERSAL ?? null)
  const confirmed = useOracleStore((state) => state.trade.variants.CONFIRMED_REVERSAL ?? null)
  return (
    <section className={styles.comparison}>
      <header><span>MATCHED COMPARISON</span><b>SAME EPISODE · SAME FROZEN CONTRACT</b></header>
      <div><ComparisonCard title="VOB ENTRY" subtitle="Entered at VOB" variant={baseline} /><ComparisonCard title="CONFIRMED ENTRY" subtitle="Oracle confirmed" variant={confirmed} /></div>
      <details><summary>EARLY REVERSAL RESEARCH <span>▾</span></summary><ComparisonCard title="EARLY REVERSAL" subtitle="Research only" variant={early} /></details>
    </section>
  )
})

function ComparisonCard({ title, subtitle, variant }: { title: string; subtitle: string; variant: OracleShadowVariant | null }) {
  const tone = pnlTone(variant?.pnl)
  const rTone = pnlTone(variant?.r)
  return (
    <article className={styles.comparisonCard} data-available={variant !== null}>
      <header><div><span>{title}</span><small>{subtitle}</small></div><b data-pnl-tone={tone}>{variant?.pnl === null || variant?.pnl === undefined ? 'P&L NOT REPORTED' : formatMoney(variant.pnl)}</b></header>
      <dl><div><dt>R</dt><dd data-pnl-tone={rTone}>{formatR(variant?.r ?? null)}</dd></div><div><dt>ENTRY</dt><dd>{formatMoney(variant?.entryAsk ?? null)}</dd></div><div><dt>CURRENT BID</dt><dd>{formatMoney(variant?.currentBid ?? null)}</dd></div><div><dt>CONTRACT</dt><dd>{variant?.contractSecurityId ?? 'UNKNOWN'}</dd></div></dl>
      <div className={styles.excursion}><span>MFE <b>{formatNumber(variant?.mfe ?? null)}</b></span><i data-tone="mfe" /><span>MAE <b>{formatNumber(variant?.mae ?? null)}</b></span><i data-tone="mae" /></div>
    </article>
  )
}

const Lifecycle = memo(function Lifecycle() {
  const episode = useOracleStore((state) => state.vob.episode)
  const reversalState = useOracleStore((state) => state.reversal.state)
  const historical = useOracleStore((state) => state.replay.mode === 'HISTORICAL_REPLAY')
  const steps = lifecycleSteps(episode, reversalState, historical)
  return (
    <section className={styles.lifecycle}>
      <header><span>LIFECYCLE</span><b>BACKEND SEMANTIC STATE</b></header>
      <div>{steps.map((step, index) => <div key={step.label} data-state={step.state}><i>{index + 1}</i><b>{step.label}</b><time>{formatTime(step.time)}</time></div>)}</div>
    </section>
  )
})

const ExperimentScoreboard = memo(function ExperimentScoreboard() {
  const research = useOracleStore((state) => state.research)
  return (
    <section className={styles.scoreboard}>
      <header><div><span>EXPERIMENT SCOREBOARD</span><b>{research.status}</b></div><strong>STATIC RESEARCH · MATCHED EPISODES</strong></header>
      <div><Metric label="VOB AVG R" value={formatR(research.vobAverageR)} /><Metric label="CONFIRMED AVG R" value={formatR(research.confirmedAverageR)} /><Metric label="Δ EXPECTANCY" value={formatR(research.expectancyDelta)} /><Metric label="MATCHED VOBS" value={research.matchedVobs?.toString() ?? '—'} /></div>
      <p>WIN RATE · PROFIT FACTOR · MEDIAN R · MFE · MAE · WINNERS MISSED · LOSERS AVOIDED · CONFIRMATION DELAY · MAX DRAWDOWN — NOT REPORTED</p>
    </section>
  )
})

function Metric({ label, value }: { label: string; value: string }) { return <span><small>{label}</small><b>{value}</b></span> }

function observation(evidence: Readonly<Record<string, OracleEvidenceObservation>>, name: string): OracleEvidenceObservation {
  return evidence[name] ?? UNKNOWN_OBSERVATION
}

function actionLabel(state: string, direction: string, vobState: string): string {
  if (vobState === 'BROKEN') return 'VOB BROKEN'
  if (state === 'REVERSAL_READY') return 'REVERSAL READY'
  if (state === 'REVERSAL_BUILDING') return 'REVERSAL BUILDING'
  if (state === 'REVERSAL_FAILED') return 'REVERSAL FAILED'
  if (state === 'WATCHING') return direction === 'CALL' ? 'WATCH CALL TURN' : direction === 'PUT' ? 'WATCH PUT TURN' : 'WATCH'
  return state === 'UNAVAILABLE' || state === UNKNOWN ? 'DATA WAIT' : friendlyState(state)
}

function heroCopy(state: string, direction: string): string {
  if (state === 'REVERSAL_READY') return `${direction} reversal evidence is ready. Pullback Master remains the entry authority.`
  if (state === 'REVERSAL_BUILDING') return `${direction} control rotation is developing across parallel evidence.`
  if (state === 'REVERSAL_FAILED') return 'The prospective turn did not hold. No frontend override is applied.'
  if (state === 'WATCHING') return 'The VOB episode is valid. Oracle is watching the turn without forcing a signal.'
  return 'Waiting for a canonical backend VOB reversal episode.'
}

function buildStory(timeframeValue: VobTimeframe | null, touchAt: string | null, direction: string, evidence: Readonly<Record<string, OracleEvidenceObservation>>): string[] {
  const result: string[] = []
  if (timeframeValue && touchAt) result.push(`${timeframeValue} VOB TOUCHED`)
  const failed = observation(evidence, 'failed_aggression')
  if (failed.known && failed.state === 'PRESENT') result.push(direction === 'PUT' ? 'BUYING NOT WORKING' : 'SELLING NOT WORKING')
  const opposing = observation(evidence, 'opposing_option_failure')
  if (opposing.known && opposing.state === 'FAILING') result.push(direction === 'PUT' ? 'CE LOSING POWER' : 'PE LOSING POWER')
  const target = observation(evidence, 'target_option_wakeup')
  if (target.known && target.state === 'WAKEUP') result.push(direction === 'PUT' ? 'PE WAKING UP' : 'CE WAKING UP')
  const argus = observation(evidence, 'argus_confirmation')
  if (argus.known && argus.state === 'CONFIRMS_TARGET') result.push('ARGUS CONFIRMED')
  return result.slice(0, 5).length ? result.slice(0, 5) : ['WAITING FOR CANONICAL EVIDENCE']
}

function evidenceStory(direction: string, evidence: Readonly<Record<string, OracleEvidenceObservation>>) {
  const failed = observation(evidence, 'failed_aggression')
  const opposing = observation(evidence, 'opposing_option_failure')
  const target = observation(evidence, 'target_option_wakeup')
  const futures = observation(evidence, 'futures_response')
  return [
    { label: 'FAILED AGGRESSION', value: failed.known ? failed.state === 'PRESENT' ? (direction === 'PUT' ? 'BUYING NOT WORKING' : 'SELLING NOT WORKING') : failed.state : UNKNOWN, known: failed.known },
    { label: 'OPPOSING OPTION', value: opposing.known ? opposing.state === 'FAILING' ? (direction === 'PUT' ? 'CE LOSING POWER' : 'PE LOSING POWER') : opposing.state : UNKNOWN, known: opposing.known },
    { label: 'TARGET OPTION', value: target.known ? target.state === 'WAKEUP' ? (direction === 'PUT' ? 'PE WAKING UP' : 'CE WAKING UP') : target.state : UNKNOWN, known: target.known },
    { label: 'FUTURES RESPONSE', value: futures.known ? futures.state : UNKNOWN, known: futures.known },
  ]
}

function lifecycleSteps(episode: OracleVobEpisode | null, reversalState: string, historical = false) {
  return [
    { label: 'VOB READY', state: episode ? 'complete' : 'pending', time: episode?.createdAt ?? null },
    { label: 'APPROACHING', state: episode?.approachAt ? 'complete' : 'pending', time: episode?.approachAt ?? null },
    { label: 'TOUCHED', state: episode?.touchAt ? 'complete' : 'pending', time: episode?.touchAt ?? null },
    { label: 'WATCHING TURN', state: reversalState === 'WATCHING' ? 'active' : ['REVERSAL_BUILDING', 'REVERSAL_READY'].includes(reversalState) ? 'complete' : 'pending', time: null },
    { label: 'REVERSAL BUILDING', state: reversalState === 'REVERSAL_BUILDING' ? 'active' : reversalState === 'REVERSAL_READY' ? 'complete' : 'pending', time: null },
    { label: 'REVERSAL READY', state: reversalState === 'REVERSAL_READY' ? 'active' : reversalState === 'REVERSAL_FAILED' ? 'failed' : 'pending', time: null },
    { label: historical ? 'TRADE ACTIVE' : 'TRADE LIVE', state: 'pending', time: null },
    { label: 'EXIT', state: episode?.vobState === 'BROKEN' ? 'failed' : 'pending', time: null },
  ]
}

function controlLabel(direction: string, state: string): string {
  if (state === 'REVERSAL_READY') return direction === 'PUT' ? 'SELLERS IN CONTROL' : 'BUYERS IN CONTROL'
  if (state === 'REVERSAL_BUILDING') return direction === 'PUT' ? 'SELLERS RETURNING' : 'BUYERS RETURNING'
  if (state === 'REVERSAL_FAILED') return 'CONTROL ROTATION FAILED'
  return 'CONTROL UNKNOWN'
}
function friendlyState(value: string): string { return value.replaceAll('_', ' ') }
function friendlyArgus(value: string): string {
  if (value === 'CONFIRMS_TARGET') return 'SUPPORTIVE'
  if (value === 'INCUMBENT_DETERIORATING') return 'IMPROVING'
  if (value === 'ADVERSE') return 'HOSTILE'
  return value === 'UNKNOWN' ? UNKNOWN : friendlyState(value)
}
function truthTone(value: string): string { const upper = value.toUpperCase(); return upper.includes('FRESH') || upper.includes('OPEN') || upper.includes('AVAILABLE') ? 'fresh' : upper.includes('STALE') || upper.includes('FAILED') || upper.includes('BROKEN') ? 'bad' : 'neutral' }
function contractLabel(strike: number | null, side: string | null): string { return strike === null || side === null ? UNKNOWN : `${formatNumber(strike)} ${side}` }
function formatNumber(value: number | null): string { return value === null ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: 2 }) }
function formatMoney(value: number | null): string { return value === null ? '—' : `₹${formatNumber(value)}` }
function formatR(value: number | null): string { return value === null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}R` }
function formatRange(low: number | null, high: number | null): string { return low === null || high === null ? 'NOT REPORTED' : `${formatNumber(low)}–${formatNumber(high)}` }
function formatTime(value: string | null): string { if (!value) return '—'; const parsed = new Date(value); return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleTimeString('en-IN', { hour12: false, timeZone: 'Asia/Kolkata' }) }
function railPosition(value: number, values: number[]): string { if (values.length < 2) return '50%'; const low = Math.min(...values); const high = Math.max(...values); return high <= low ? '50%' : `${8 + ((value - low) / (high - low)) * 84}%` }
