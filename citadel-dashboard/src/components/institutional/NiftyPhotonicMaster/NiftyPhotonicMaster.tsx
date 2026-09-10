'use client'

import React, { memo, useEffect, useRef } from 'react'
import styles from './NiftyPhotonicMaster.module.css'
import { usePhotonicCanonicalState } from './hooks/usePhotonicCanonicalState'
import { useOracleStore, type OracleTradeRecord } from '@/dashboard/store/oracleStore'
import {
  acceptSemanticEvent,
  horsepowerAlert,
  readBooleanPreference,
  trackATradeAlert,
  type AlertKind,
  type TrackATradeFrame,
} from '../vobPresentation'
import { PhotonicHeroHeader, type PhotonicHeroHeaderProps } from './components/PhotonicHeroHeader'
import { PhotonicResolverStrip, type PhotonicResolverStripProps } from './components/PhotonicResolverStrip'
import { PhotonicCallCard, type PhotonicCallCardProps } from './components/PhotonicCallCard'
import { PhotonicOracleHeroWheel, type PhotonicOracleHeroWheelProps } from './components/PhotonicOracleHeroWheel'
import { PhotonicPutCard, type PhotonicPutCardProps } from './components/PhotonicPutCard'
import { PhotonicOptionBuyerIntelligence } from './components/PhotonicOptionBuyerIntelligence'
import { PhotonicOptionIntelligence } from './components/PhotonicOptionIntelligence'
import { PhotonicSuddenOiSharedContext, PhotonicSuddenOiSideCard, suddenOiAlertFrames } from './components/PhotonicSuddenOiIntelligence'
import { PhotonicMarketStoryStrip, type PhotonicMarketStoryStripProps } from './components/PhotonicMarketStoryStrip'
import { PhotonicRecoveryRail, type PhotonicRecoveryRailProps } from './components/PhotonicRecoveryRail'
import { PhotonicArgusSupport, type PhotonicArgusSupportProps } from './components/PhotonicArgusSupport'
import { PhotonicEvidenceChannels, type PhotonicEvidenceChannelsProps } from './components/PhotonicEvidenceChannels'
import { PhotonicMatchedPnlCard, type PhotonicMatchedPnlCardProps } from './components/PhotonicMatchedPnlCard'
import { PhotonicVobLevelsMatrix, type PhotonicVobLevelsMatrixProps } from './components/PhotonicVobLevelsMatrix'
import { PhotonicTradeLedger, type PhotonicTradeLedgerProps } from './components/PhotonicTradeLedger'
import { PhotonicLifecycleStepper, type PhotonicLifecycleStepperProps } from './components/PhotonicLifecycleStepper'
import { PhotonicScoreboard, type PhotonicScoreboardProps } from './components/PhotonicScoreboard'

export interface NiftyPhotonicMasterProps {
  headerProps?: PhotonicHeroHeaderProps
  resolverProps?: PhotonicResolverStripProps
  callCardProps?: PhotonicCallCardProps
  heroWheelProps?: PhotonicOracleHeroWheelProps
  putCardProps?: PhotonicPutCardProps
  marketStoryProps?: PhotonicMarketStoryStripProps
  recoveryProps?: PhotonicRecoveryRailProps
  argusProps?: PhotonicArgusSupportProps
  evidenceProps?: PhotonicEvidenceChannelsProps
  matchedPnlProps?: PhotonicMatchedPnlCardProps
  vobLevelsProps?: PhotonicVobLevelsMatrixProps
  tradeLedgerProps?: PhotonicTradeLedgerProps
  lifecycleProps?: PhotonicLifecycleStepperProps
  scoreboardProps?: PhotonicScoreboardProps
  /** Set true if using purely passed props without reading live oracle store */
  isolated?: boolean
}

export const NiftyPhotonicMaster = memo(function NiftyPhotonicMaster({
  headerProps,
  resolverProps,
  callCardProps,
  heroWheelProps,
  putCardProps,
  marketStoryProps,
  recoveryProps,
  argusProps,
  evidenceProps,
  matchedPnlProps,
  vobLevelsProps,
  tradeLedgerProps,
  lifecycleProps,
  scoreboardProps,
  isolated = false,
}: NiftyPhotonicMasterProps) {
  // Read canonical state from Zustand oracleStore
  const canonical = usePhotonicCanonicalState()

  // Attach pointer tracking for the universal cursor hover light pool
  useEffect(() => {
    const handlePointerMove = (e: PointerEvent) => {
      const target = (e.target as HTMLElement)?.closest(`.${styles.card}`) as HTMLElement | null
      if (target) {
        const rect = target.getBoundingClientRect()
        target.style.setProperty('--mouse-x', `${e.clientX - rect.left}px`)
        target.style.setProperty('--mouse-y', `${e.clientY - rect.top}px`)
      }
    }
    const container = document.getElementById('nifty-photonic-master-suite')
    if (container) {
      container.addEventListener('pointermove', handlePointerMove)
      return () => container.removeEventListener('pointermove', handlePointerMove)
    }
  }, [])

  return (
    <div className={styles.photonicContainer} id="nifty-photonic-master-suite">
      <PhotonicVobTransitionAlerts />
      <PhotonicHorsepowerTransitionAlerts />
      <PhotonicSuddenOiAlerts />
      <div className={styles.dashboardGrid}>
        {/* Tile 01: Refractive Photonic Glass Capsule Hero Header */}
        <PhotonicHeroHeader
          {...(isolated ? headerProps : { ...canonical.header, ...headerProps })}
        />

        {/* Tile 02: Real-time ITM-1 Strike Resolver Strip */}
        <PhotonicResolverStrip
          {...(isolated ? resolverProps : { ...canonical.resolver, ...resolverProps })}
        />

        <div className={styles.oracleThreeColumns}>
          <div className={styles.oracleColumn}>
            <PhotonicCallCard key="photonic-call-card" {...(isolated ? callCardProps : { ...canonical.callCard, ...callCardProps })} />
            <PhotonicSuddenOiSideCard key="photonic-sudden-call" side="CALL" intelligence={isolated ? null : canonical.heroWheel.intelligence} />
          </div>
          <div className={styles.oracleColumn}>
            <PhotonicOracleHeroWheel key="photonic-vob-hero-wheel" {...(isolated ? heroWheelProps : { ...canonical.heroWheel, ...heroWheelProps })} />
            <PhotonicOracleHeroWheel key="photonic-straddle-wheel" presentation="STRADDLE" intelligence={isolated ? null : canonical.heroWheel.intelligence} />
            <PhotonicOracleHeroWheel key="photonic-fit-wheel" presentation="FIT" intelligence={isolated ? null : canonical.heroWheel.intelligence} callHorsepower={isolated ? null : canonical.heroWheel.callHorsepower} putHorsepower={isolated ? null : canonical.heroWheel.putHorsepower} />
          </div>
          <div className={styles.oracleColumn}>
            <PhotonicPutCard key="photonic-put-card" {...(isolated ? putCardProps : { ...canonical.putCard, ...putCardProps })} />
            <PhotonicSuddenOiSideCard key="photonic-sudden-put" side="PUT" intelligence={isolated ? null : canonical.heroWheel.intelligence} />
          </div>
        </div>

        <PhotonicSuddenOiSharedContext
          key="photonic-sudden-oi-context"
          intelligence={isolated ? null : canonical.heroWheel.intelligence}
        />

        {/* Tile 04: Pure Model-Derived Option Intelligence (GEX, Skew, HAR-RV, Gamma/Theta Quality) */}
        <PhotonicOptionIntelligence
          key="photonic-option-intelligence"
          intelligence={isolated ? null : canonical.heroWheel.intelligence}
        />

      </div>
    </div>
  )
})

export const PhotonicOptionBuyerIntelligenceBottom = memo(function PhotonicOptionBuyerIntelligenceBottom() {
  const intelligence = useOracleStore((state) => state.market.buyerIntelligence)
  return (
    <section className={styles.photonicContainer} aria-label="Final Option Buyer Intelligence detail section">
      <div className={styles.optionBuyerBottomGrid}>
        <PhotonicOptionBuyerIntelligence key="photonic-call-obi" side="CE" intelligence={intelligence} />
        <PhotonicOptionBuyerIntelligence key="photonic-put-obi" side="PE" intelligence={intelligence} />
      </div>
    </section>
  )
})

const ALERTS_KEY = 'citadel.vob.alerts'
const SOUND_KEY = 'citadel.vob.sound'

/**
 * Non-visual alert bridge for the default Photonic surface. It observes only
 * exact-current-contract Track-A records and is deliberately primed on mount,
 * so a refresh cannot replay historical entries or exits.
 */
const PhotonicVobTransitionAlerts = memo(function PhotonicVobTransitionAlerts() {
  const trades = useOracleStore((state) => state.trade.activeTrades)
  const ceSecurityId = useOracleStore((state) => state.market.currentItmCall.contract.securityId)
  const peSecurityId = useOracleStore((state) => state.market.currentItmPut.contract.securityId)
  const previous = useRef(new Map<string, TrackATradeFrame>())
  const seen = useRef(new Set<string>())

  useEffect(() => {
    const current = new Map<string, TrackATradeFrame>()
    for (const trade of trades) {
      if (trade.variant !== 'VOB_ONLY' || !isCurrentContract(trade, ceSecurityId, peSecurityId)) continue
      const frame: TrackATradeFrame = {
        tradeId: trade.tradeId,
        contract: trade.contract.tradingSymbol ?? trade.contract.securityId ?? 'CURRENT ITM-1',
        timeframe: trade.timeframe ?? '—',
        entryTime: trade.entryTime,
        exitTime: trade.exitTime,
        exitReason: trade.exitReason,
        pnl: trade.pnl,
      }
      current.set(frame.tradeId, frame)
    }

    for (const [tradeId, frame] of current) {
      const prior = previous.current.get(tradeId)
      if (!prior) continue
      const event = trackATradeAlert(prior, frame)
      if (!acceptSemanticEvent(seen.current, event) || !event) continue
      const alerts = readPreference(ALERTS_KEY, true)
      const sound = readPreference(SOUND_KEY, true)
      if (alerts && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification(`CITADEL VOB · ${event.title}`, { body: [event.detail, event.reason].filter(Boolean).join('\n'), tag: event.key, silent: true })
      }
      if (sound && !prefersReducedMotion()) void playTransitionTone(event.kind)
    }
    previous.current = current
  }, [ceSecurityId, peSecurityId, trades])

  return null
})

const PhotonicHorsepowerTransitionAlerts = memo(function PhotonicHorsepowerTransitionAlerts() {
  const call = useOracleStore((state) => state.market.currentItmCall.horsepower)
  const put = useOracleStore((state) => state.market.currentItmPut.horsepower)
  const nifty = useOracleStore((state) => state.vob.underlyingHorsepower)
  const seen = useRef<Set<string> | null>(null)

  useEffect(() => {
    const events = [call, put, nifty].flatMap((projection) => projection?.events ?? [])
    if (seen.current === null) {
      seen.current = new Set(events.map((event) => event.eventId))
      return
    }
    for (const frame of events) {
      if (!frame.notificationEligible || seen.current.has(frame.eventId)) continue
      const event = horsepowerAlert(frame)
      if (!acceptSemanticEvent(seen.current, event)) continue
      const alerts = readPreference(ALERTS_KEY, true)
      const sound = readPreference(SOUND_KEY, true)
      if (alerts && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification(`CITADEL VOB · ${event.title}`, {
          body: [event.detail, event.reason].filter(Boolean).join('\n'),
          tag: event.key,
          silent: true,
        })
      }
      if (sound && !prefersReducedMotion()) void playTransitionTone(event.kind)
    }
  }, [call, nifty, put])

  return null
})

const PhotonicSuddenOiAlerts = memo(function PhotonicSuddenOiAlerts() {
  const intelligence = useOracleStore((state) => state.market.buyerIntelligence)
  const seen = useRef<Set<string> | null>(null)

  useEffect(() => {
    const events = suddenOiAlertFrames(intelligence).map((frame) => {
      const kind: AlertKind = frame.eventType === 'WRITER_SQUEEZE' ? 'ENTRY' : 'READY'
      return [{
        kind,
        key: frame.eventId,
        title: frame.title,
        detail: frame.detail,
        reason: 'Finalized closed-5M OI evidence',
        tone: frame.side === 'PE' ? 'negative' as const : 'positive' as const,
      }]
    }).flat()
    if (seen.current === null) {
      seen.current = new Set(events.map((event) => event.key))
      return
    }
    for (const event of events) {
      if (!acceptSemanticEvent(seen.current, event)) continue
      const alerts = readPreference(ALERTS_KEY, true)
      const sound = readPreference(SOUND_KEY, true)
      if (alerts && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification(`CITADEL OI · ${event.title}`, { body: event.detail, tag: event.key, silent: true })
      }
      if (sound && !prefersReducedMotion()) void playTransitionTone(event.kind)
    }
  }, [intelligence])

  return null
})

function isCurrentContract(trade: OracleTradeRecord, ceSecurityId: string | null, peSecurityId: string | null): boolean {
  return trade.contract.securityId !== null && (trade.contract.securityId === ceSecurityId || trade.contract.securityId === peSecurityId)
}

function readPreference(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return false
  return readBooleanPreference(window.localStorage, key, fallback)
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

async function playTransitionTone(kind: AlertKind): Promise<void> {
  if (typeof window === 'undefined') return
  const Context = window.AudioContext ?? window.webkitAudioContext
  if (!Context) return
  try {
    const context = new Context()
    if (context.state === 'suspended') await context.resume()
    const [first, second] = kind === 'TARGET' ? [659, 880] : kind === 'STOP' || kind === 'BROKEN' ? [330, 220] : kind === 'EXIT' ? [659, 440] : [587, 784]
    const now = context.currentTime
    for (const [frequency, offset] of [[first, 0], [second, .11]] as const) {
      const oscillator = context.createOscillator()
      const gain = context.createGain()
      oscillator.type = 'sine'
      oscillator.frequency.value = frequency
      gain.gain.setValueAtTime(.0001, now + offset)
      gain.gain.exponentialRampToValueAtTime(.045, now + offset + .012)
      gain.gain.exponentialRampToValueAtTime(.0001, now + offset + .15)
      oscillator.connect(gain).connect(context.destination)
      oscillator.start(now + offset)
      oscillator.stop(now + offset + .17)
    }
    window.setTimeout(() => void context.close(), 480)
  } catch { /* Browser audio permission/autoplay fallback is intentionally silent. */ }
}

declare global { interface Window { webkitAudioContext?: typeof AudioContext } }
