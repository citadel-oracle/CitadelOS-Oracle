'use client'

import React, { useEffect, useRef, memo } from 'react'
import styles from './LivingMarketForcesViewport.module.css'

export type LivingMarketState =
  | 'NO_TRADE'
  | 'WAIT'
  | 'CALL_DEVELOPING'
  | 'CALL'
  | 'PUT_DEVELOPING'
  | 'PUT'
  | 'REVERSAL_WATCH'
  | 'ANALYZING'
  | 'STALE'
  | 'UNAVAILABLE'
  | 'SESSION_LAST'

export interface LivingMarketForcesViewportProps {
  marketState: LivingMarketState | string | null
  operationalStatus?: string // 'HEALTHY' | 'UNAVAILABLE' | 'DEGRADED' | 'OFF_MARKET' | 'SUSPENDED' | 'SESSION_LAST'
  lastKnown?: boolean
  spotPrice?: number | null
  basis?: number | null
  cognitiveState?: string | null
  isSessionLast?: boolean
}

const CONFIG: Record<string, {
  badge: string;
  badgeClass: string;
  sublabel: string;
  headerText: string;
  targetId: string;
  startTime: number;
  loopStart?: number;
  loopEnd?: number;
  theme: 'balanced' | 'call' | 'put';
}> = {
  NO_TRADE: {
    badge: 'NO TRADE',
    badgeClass: styles.badgeBalanced,
    sublabel: 'BALANCED',
    headerText: 'NO TRADE',
    targetId: 'vidBalanced',
    startTime: 0,
    theme: 'balanced'
  },
  WAIT: {
    badge: 'WAIT',
    badgeClass: styles.badgeBalanced,
    sublabel: 'BALANCED',
    headerText: 'WAIT',
    targetId: 'vidBalanced',
    startTime: 0,
    theme: 'balanced'
  },
  CALL_DEVELOPING: {
    badge: 'CALL DEVELOPING',
    badgeClass: styles.badgeCallDeveloping,
    sublabel: 'BULL PRESSURE',
    headerText: 'CALL DEVELOPING',
    targetId: 'vidBullPressure',
    startTime: 11.80,
    loopStart: 26.50,
    loopEnd: 30.00,
    theme: 'call'
  },
  CALL: {
    badge: 'CALL',
    badgeClass: styles.badgeCall,
    sublabel: 'BULL DOMINANT',
    headerText: 'CALL',
    targetId: 'vidBullDominant',
    startTime: 0,
    loopStart: 8.50,
    loopEnd: 10.00,
    theme: 'call'
  },
  PUT_DEVELOPING: {
    badge: 'PUT DEVELOPING',
    badgeClass: styles.badgePutDeveloping,
    sublabel: 'BEAR PRESSURE',
    headerText: 'PUT DEVELOPING',
    targetId: 'vidBearPressure',
    startTime: 11.00,
    loopStart: 18.50,
    loopEnd: 20.00,
    theme: 'put'
  },
  PUT: {
    badge: 'PUT',
    badgeClass: styles.badgePut,
    sublabel: 'BEAR DOMINANT',
    headerText: 'PUT',
    targetId: 'vidBearDominant',
    startTime: 0,
    loopStart: 8.50,
    loopEnd: 10.00,
    theme: 'put'
  },
  REVERSAL_WATCH: {
    badge: 'REVERSAL WATCH',
    badgeClass: styles.badgeReversalWatch,
    sublabel: 'CONTESTED FORCES',
    headerText: 'REVERSAL WATCH',
    targetId: 'vidBalanced',
    startTime: 0,
    theme: 'balanced'
  },
  ANALYZING: {
    badge: 'ANALYZING',
    badgeClass: styles.badgeAnalyzing,
    sublabel: 'SCANNING FORCES',
    headerText: 'ANALYZING',
    targetId: 'vidBalanced',
    startTime: 0,
    theme: 'balanced'
  },
  STALE: {
    badge: 'LAST KNOWN',
    badgeClass: styles.badgeStale,
    sublabel: 'NOT CURRENT',
    headerText: 'LAST KNOWN',
    targetId: 'vidBalanced',
    startTime: 0,
    theme: 'balanced'
  },
  UNAVAILABLE: {
    badge: 'UNAVAILABLE',
    badgeClass: styles.badgeUnavailable,
    sublabel: 'DATA PENDING',
    headerText: 'UNAVAILABLE',
    targetId: 'vidBalanced',
    startTime: 0,
    theme: 'balanced'
  },
  SESSION_LAST: {
    badge: 'CALL DEVELOPING',
    badgeClass: styles.badgeSessionLast,
    sublabel: '· SESSION LAST · MARKET CLOSED ·',
    headerText: 'SESSION LAST',
    targetId: 'vidBullPressure',
    startTime: 26.50,
    loopStart: 26.50,
    loopEnd: 30.00,
    theme: 'call'
  }
}

export const VIDEO_IDS = [
  'vidBalanced',
  'vidBullPressure',
  'vidBullDominant',
  'vidBearPressure',
  'vidBearDominant',
] as const

export function getVideoPlaybackPlan(
  marketState: LivingMarketState | string | null,
  operationalStatus = 'HEALTHY',
  isSessionLast = false,
): { targetId: string; startTime: number; semanticState: LivingMarketState | null } {
  if (isSessionLast || operationalStatus === 'SESSION_LAST' || marketState === 'SESSION_LAST') {
    const isCall = marketState?.startsWith('CALL') || marketState === 'SESSION_LAST'
    const isPut = marketState?.startsWith('PUT')
    if (isCall) {
      return { targetId: 'vidBullPressure', startTime: 26.50, semanticState: 'CALL_DEVELOPING' }
    }
    if (isPut) {
      return { targetId: 'vidBearPressure', startTime: 18.50, semanticState: 'PUT_DEVELOPING' }
    }
    return { targetId: 'vidBalanced', startTime: 0, semanticState: 'NO_TRADE' }
  }

  if (!marketState || (operationalStatus !== 'HEALTHY' && operationalStatus !== 'LIVE')) {
    return { targetId: 'vidBalanced', startTime: 0, semanticState: null }
  }

  const normalized = marketState === 'WAIT' ? 'NO_TRADE' : marketState
  const cfg = (CONFIG as Record<string, any>)[normalized] || CONFIG.NO_TRADE
  return { targetId: cfg.targetId, startTime: cfg.startTime, semanticState: normalized as LivingMarketState }
}

export interface MarketVideoController {
  currentTime: number
  pause: () => void
  play: () => Promise<void> | void
  classList: {
    add: (token: string) => void
    remove: (token: string) => void
    toggle: (token: string, force?: boolean) => boolean
  }
}

export async function guardVideoPlayTransition(
  playPromise: Promise<void>,
  targetVideo: MarketVideoController,
  transitionId: number,
  currentTransitionId: () => number,
  activeClass: string,
): Promise<void> {
  try {
    await playPromise
    if (currentTransitionId() === transitionId) return
    targetVideo.pause()
    targetVideo.currentTime = 0
    targetVideo.classList.remove(activeClass)
  } catch {
    // The truthful state remains visible even if autoplay is denied.
    if (currentTransitionId() !== transitionId) return
    targetVideo.classList.add(activeClass)
  }
}

export function synchronizeMarketVideos(
  videos: Record<string, MarketVideoController | null>,
  targetId: string,
  startTime: number,
  activeClass: string,
): MarketVideoController | null {
  const target = videos[targetId]
  if (!target) return null
  Object.entries(videos).forEach(([videoId, video]) => {
    if (!video) return
    const isTarget = videoId === targetId
    video.classList.toggle(activeClass, isTarget)
    if (!isTarget) {
      video.pause()
      if (video.currentTime !== 0) video.currentTime = 0
    }
  })
  target.currentTime = startTime
  return target
}

const OPERATIONAL_LABELS: Record<string, string> = {
  UNAVAILABLE: 'SYSTEM UNAVAILABLE',
  SYSTEM_UNAVAILABLE: 'SYSTEM UNAVAILABLE',
  TRANSPORT_UNAVAILABLE: 'CONNECTION LOST',
  OFF_MARKET: 'MARKET CLOSED',
  SYSTEM_OFF_MARKET: 'MARKET CLOSED',
  REASONING_UNAVAILABLE: 'ANALYSIS UNAVAILABLE',
  PROVIDER_UNAVAILABLE: 'ANALYSIS UNAVAILABLE',
  OUTPUT_INVALID: 'ANALYSIS UNAVAILABLE',
  DATA_DEGRADED: 'DATA LIMITED',
  DATA_LINEAGE_CONTAMINATION: 'DATA NOT VERIFIED',
  FAIL_CLOSED_SYSTEM_STATUS: 'SAFE MODE',
}

export const LivingMarketForcesViewport = memo(function LivingMarketForcesViewport({
  marketState = null,
  operationalStatus = 'HEALTHY',
  lastKnown = false,
  spotPrice,
  basis,
  cognitiveState = null,
  isSessionLast = false,
}: LivingMarketForcesViewportProps) {
  const effectiveState = cognitiveState || marketState
  const effectiveSessionLast = isSessionLast || operationalStatus === 'SESSION_LAST' || effectiveState === 'SESSION_LAST'
  const isOperationalUnavailable = !effectiveSessionLast && (effectiveState === null || (operationalStatus !== 'HEALTHY' && operationalStatus !== 'LIVE'))

  const safeState: LivingMarketState = effectiveSessionLast
    ? 'SESSION_LAST'
    : effectiveState && CONFIG[effectiveState]
    ? (effectiveState as LivingMarketState)
    : 'NO_TRADE'
  const cfg = CONFIG[safeState] || CONFIG.NO_TRADE

  const isStale = !effectiveSessionLast && (operationalStatus === 'STALE' || effectiveState === 'STALE')

  const activeBadgeText = effectiveSessionLast
    ? (effectiveState && effectiveState !== 'SESSION_LAST' && CONFIG[effectiveState] ? CONFIG[effectiveState].badge : 'SESSION LAST')
    : isStale
    ? 'LAST KNOWN'
    : isOperationalUnavailable
    ? (OPERATIONAL_LABELS[operationalStatus] || operationalStatus.replaceAll('_', ' '))
    : cfg.badge
  const activeBadgeClass = effectiveSessionLast
    ? styles.badgeSessionLast
    : isStale
    ? styles.badgeStale
    : isOperationalUnavailable
    ? styles.badgeUnavailable
    : cfg.badgeClass
  const activeSublabel = effectiveSessionLast
    ? '· SESSION LAST · MARKET CLOSED ·'
    : isStale
    ? 'NOT CURRENT'
    : isOperationalUnavailable
    ? (lastKnown ? 'LAST KNOWN · LIVE ANALYSIS PAUSED' : 'LIVE ANALYSIS PAUSED')
    : cfg.sublabel

  const stageMode = effectiveSessionLast
    ? 'SESSION_LAST'
    : isOperationalUnavailable
    ? (operationalStatus === 'STALE' ? 'STALE' : 'UNAVAILABLE')
    : safeState

  const playbackPlan = getVideoPlaybackPlan(effectiveState, operationalStatus, effectiveSessionLast)
  const activeTargetId = playbackPlan.targetId
  const targetStartTime = playbackPlan.startTime

  const rayCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const particleCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const videoRefs = useRef<{ [key: string]: HTMLVideoElement | null }>({})
  const videoTransitionRef = useRef(0)
  const stateRef = useRef<LivingMarketState>(safeState)
  stateRef.current = safeState
  const activeTargetIdRef = useRef<string>(activeTargetId)
  activeTargetIdRef.current = activeTargetId

  // Ray state variables
  const rayTargetBullRef = useRef<number>(0.10)
  const rayCurrentBullRef = useRef<number>(0.10)
  const rayTargetBearRef = useRef<number>(0.10)
  const rayCurrentBearRef = useRef<number>(0.10)
  const rayPulseBullRef = useRef<number>(1.0)
  const rayPulseBearRef = useRef<number>(1.0)

  // 1. Video Playback & Transition Engine (Clean lifecycle without premature return)
  useEffect(() => {
    const transitionId = ++videoTransitionRef.current
    const targetVid = synchronizeMarketVideos(
      videoRefs.current,
      activeTargetId,
      targetStartTime,
      styles.actorVideoActive,
    )
    if (!targetVid) return

    let pulseTimer: NodeJS.Timeout | null = null

    // Set Ray Alphas based on audited state
    if (effectiveSessionLast || safeState === 'SESSION_LAST') {
      if (effectiveState?.startsWith('CALL')) {
        rayTargetBullRef.current = 0.20
        rayTargetBearRef.current = 0.04
      } else if (effectiveState?.startsWith('PUT')) {
        rayTargetBullRef.current = 0.04
        rayTargetBearRef.current = 0.20
      } else {
        rayTargetBullRef.current = 0.10
        rayTargetBearRef.current = 0.10
      }
    } else if (isOperationalUnavailable || safeState === 'UNAVAILABLE') {
      rayTargetBullRef.current = 0.02
      rayTargetBearRef.current = 0.02
    } else if (safeState === 'STALE') {
      rayTargetBullRef.current = 0.05
      rayTargetBearRef.current = 0.05
    } else if (safeState === 'ANALYZING') {
      rayTargetBullRef.current = 0.08
      rayTargetBearRef.current = 0.08
    } else if (safeState === 'REVERSAL_WATCH') {
      rayTargetBullRef.current = 0.22
      rayTargetBearRef.current = 0.22
    } else if (safeState === 'NO_TRADE' || safeState === 'WAIT') {
      rayTargetBullRef.current = 0.10
      rayTargetBearRef.current = 0.10
    } else if (safeState === 'CALL_DEVELOPING') {
      rayTargetBullRef.current = 0.28
      rayTargetBearRef.current = 0.04
      rayPulseBullRef.current = 1.3
      pulseTimer = setTimeout(() => { rayPulseBullRef.current = 1.0 }, 1200)
    } else if (safeState === 'CALL') {
      rayTargetBullRef.current = 0.24
      rayTargetBearRef.current = 0.02
    } else if (safeState === 'PUT_DEVELOPING') {
      rayTargetBullRef.current = 0.03
      rayTargetBearRef.current = 0.32
      rayPulseBearRef.current = 1.3
      pulseTimer = setTimeout(() => { rayPulseBearRef.current = 1.0 }, 1400)
    } else if (safeState === 'PUT') {
      rayTargetBullRef.current = 0.02
      rayTargetBearRef.current = 0.26
    }

    const playPromise = targetVid.play()
    if (playPromise !== undefined) {
      void guardVideoPlayTransition(
        playPromise,
        targetVid,
        transitionId,
        () => videoTransitionRef.current,
        styles.actorVideoActive,
      )
    }

    return () => {
      if (pulseTimer) clearTimeout(pulseTimer)
    }
  }, [activeTargetId, targetStartTime, effectiveState, operationalStatus, effectiveSessionLast, safeState, isOperationalUnavailable])

  // 2. Loop Enforcers on Active Videos
  useEffect(() => {
    const bullPres = videoRefs.current.vidBullPressure
    const bullDom = videoRefs.current.vidBullDominant
    const bearPres = videoRefs.current.vidBearPressure
    const bearDom = videoRefs.current.vidBearDominant

    const onBullPresUpdate = () => {
      if (activeTargetIdRef.current === 'vidBullPressure' && bullPres && bullPres.currentTime >= 30.00) {
        bullPres.currentTime = 26.50
      }
    }
    const onBullDomUpdate = () => {
      if (activeTargetIdRef.current === 'vidBullDominant' && bullDom && bullDom.currentTime >= 10.00) {
        bullDom.currentTime = 8.50
      }
    }
    const onBearPresUpdate = () => {
      if (activeTargetIdRef.current === 'vidBearPressure' && bearPres && bearPres.currentTime >= 20.00) {
        bearPres.currentTime = 18.50
      }
    }
    const onBearDomUpdate = () => {
      if (activeTargetIdRef.current === 'vidBearDominant' && bearDom && bearDom.currentTime >= 10.00) {
        bearDom.currentTime = 8.50
      }
    }
    const replayFrom = (video: HTMLVideoElement | null, targetId: string, start: number) => () => {
      if (activeTargetIdRef.current !== targetId || !video) return
      video.currentTime = start
      video.play().catch(() => undefined)
    }
    const onBullPresEnded = replayFrom(bullPres, 'vidBullPressure', 26.50)
    const onBullDomEnded = replayFrom(bullDom, 'vidBullDominant', 8.50)
    const onBearPresEnded = replayFrom(bearPres, 'vidBearPressure', 18.50)
    const onBearDomEnded = replayFrom(bearDom, 'vidBearDominant', 8.50)

    bullPres?.addEventListener('timeupdate', onBullPresUpdate)
    bullDom?.addEventListener('timeupdate', onBullDomUpdate)
    bearPres?.addEventListener('timeupdate', onBearPresUpdate)
    bearDom?.addEventListener('timeupdate', onBearDomUpdate)
    bullPres?.addEventListener('ended', onBullPresEnded)
    bullDom?.addEventListener('ended', onBullDomEnded)
    bearPres?.addEventListener('ended', onBearPresEnded)
    bearDom?.addEventListener('ended', onBearDomEnded)

    return () => {
      bullPres?.removeEventListener('timeupdate', onBullPresUpdate)
      bullDom?.removeEventListener('timeupdate', onBullDomUpdate)
      bearPres?.removeEventListener('timeupdate', onBearPresUpdate)
      bearDom?.removeEventListener('timeupdate', onBearDomUpdate)
      bullPres?.removeEventListener('ended', onBullPresEnded)
      bullDom?.removeEventListener('ended', onBullDomEnded)
      bearPres?.removeEventListener('ended', onBearPresEnded)
      bearDom?.removeEventListener('ended', onBearDomEnded)
    }
  }, [])

  // 3. Volumetric Ray Canvas Engine (Behind Video Occluder)
  useEffect(() => {
    const canvas = rayCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    let animId: number

    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      if (rect.width > 0 && rect.height > 0) {
        if (canvas.width !== Math.round(rect.width) || canvas.height !== Math.round(rect.height)) {
          canvas.width = Math.round(rect.width)
          canvas.height = Math.round(rect.height)
        }
      }
    }
    resize()
    window.addEventListener('resize', resize)

    const bullRays = [
      { baseAngle: -150, length: 380, widthStart: 12, widthEnd: 140, speed: 0.0006, phase: 0 },
      { baseAngle: -125, length: 420, widthStart: 10, widthEnd: 160, speed: 0.0008, phase: 1.2 },
      { baseAngle: -95,  length: 460, widthStart: 14, widthEnd: 170, speed: 0.0005, phase: 2.4 },
      { baseAngle: -70,  length: 400, widthStart: 12, widthEnd: 150, speed: 0.0007, phase: 3.8 },
      { baseAngle: -40,  length: 360, widthStart: 8,  widthEnd: 130, speed: 0.0009, phase: 4.6 },
      { baseAngle: -170, length: 320, widthStart: 10, widthEnd: 120, speed: 0.0006, phase: 5.2 }
    ]

    const bearRays = [
      { baseAngle: -10,  length: 360, widthStart: 12, widthEnd: 130, speed: 0.0006, phase: 0.5 },
      { baseAngle: -45,  length: 400, widthStart: 10, widthEnd: 150, speed: 0.0007, phase: 1.8 },
      { baseAngle: -85,  length: 440, widthStart: 14, widthEnd: 160, speed: 0.0005, phase: 3.1 },
      { baseAngle: -115, length: 380, widthStart: 10, widthEnd: 140, speed: 0.0008, phase: 4.2 },
      { baseAngle: -140, length: 340, widthStart: 8,  widthEnd: 125, speed: 0.0009, phase: 4.8 },
      { baseAngle: 10,   length: 310, widthStart: 8,  widthEnd: 110, speed: 0.0006, phase: 5.4 }
    ]

    const drawShaft = (
      originX: number,
      originY: number,
      angleDeg: number,
      length: number,
      startW: number,
      endW: number,
      colorStops: Array<{ stop: number; r: number; g: number; b: number; a: number }>,
      alpha: number
    ) => {
      if (alpha <= 0.01) return

      const rad = (angleDeg * Math.PI) / 180
      const perp = rad + Math.PI / 2

      const cos = Math.cos(rad)
      const sin = Math.sin(rad)
      const pCos = Math.cos(perp)
      const pSin = Math.sin(perp)

      const targetX = originX + cos * length
      const targetY = originY + sin * length

      const hwStart = startW / 2
      const hwEnd = endW / 2

      const x0 = originX - pCos * hwStart
      const y0 = originY - pSin * hwStart
      const x1 = originX + pCos * hwStart
      const y1 = originY + pSin * hwStart
      const x2 = targetX + pCos * hwEnd
      const y2 = targetY + pSin * hwEnd
      const x3 = targetX - pCos * hwEnd
      const y3 = targetY - pSin * hwEnd

      const grad = ctx.createLinearGradient(originX, originY, targetX, targetY)
      colorStops.forEach(cs => {
        grad.addColorStop(cs.stop, `rgba(${cs.r}, ${cs.g}, ${cs.b}, ${cs.a * alpha})`)
      })

      ctx.save()
      ctx.beginPath()
      ctx.moveTo(x0, y0)
      ctx.lineTo(x1, y1)
      ctx.lineTo(x2, y2)
      ctx.lineTo(x3, y3)
      ctx.closePath()
      ctx.fillStyle = grad
      ctx.fill()
      ctx.restore()
    }

    const render = (timestamp: number) => {
      if (document.hidden) return

      ctx.clearRect(0, 0, canvas.width, canvas.height)
      const w = canvas.width
      const h = canvas.height

      // Smooth Alpha Interpolation
      rayCurrentBullRef.current += (rayTargetBullRef.current * rayPulseBullRef.current - rayCurrentBullRef.current) * 0.05
      rayCurrentBearRef.current += (rayTargetBearRef.current * rayPulseBearRef.current - rayCurrentBearRef.current) * 0.05

      const bullOriginX = w * 0.27
      const bullOriginY = h * 0.35

      const bearOriginX = w * 0.73
      const bearOriginY = h * 0.37

      const bullColors = [
        { stop: 0.0, r: 0, g: 230, b: 118, a: 0.75 },
        { stop: 0.35, r: 0, g: 240, b: 255, a: 0.4 },
        { stop: 0.75, r: 0, g: 230, b: 118, a: 0.15 },
        { stop: 1.0, r: 0, g: 230, b: 118, a: 0.0 }
      ]

      const bearColors = [
        { stop: 0.0, r: 255, g: 42, b: 85, a: 0.85 },
        { stop: 0.4, r: 230, g: 0, b: 57, a: 0.5 },
        { stop: 0.8, r: 255, g: 42, b: 85, a: 0.15 },
        { stop: 1.0, r: 255, g: 42, b: 85, a: 0.0 }
      ]

      bullRays.forEach(ray => {
        const angle = ray.baseAngle + Math.sin(timestamp * ray.speed + ray.phase) * 4.5
        const breatheAlpha = rayCurrentBullRef.current * (0.85 + 0.15 * Math.sin(timestamp * 0.0015 + ray.phase))
        drawShaft(bullOriginX, bullOriginY, angle, ray.length, ray.widthStart, ray.widthEnd, bullColors, breatheAlpha)
      })

      bearRays.forEach(ray => {
        const angle = ray.baseAngle + Math.sin(timestamp * ray.speed + ray.phase) * 4.0
        const breatheAlpha = rayCurrentBearRef.current * (0.85 + 0.15 * Math.sin(timestamp * 0.0012 + ray.phase))
        drawShaft(bearOriginX, bearOriginY, angle, ray.length, ray.widthStart, ray.widthEnd, bearColors, breatheAlpha)
      })

      if (!reduceMotion) animId = requestAnimationFrame(render)
    }

    const handleVisibility = () => {
      cancelAnimationFrame(animId)
      if (!document.hidden && !reduceMotion) animId = requestAnimationFrame(render)
    }
    animId = requestAnimationFrame(render)
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      window.removeEventListener('resize', resize)
      document.removeEventListener('visibilitychange', handleVisibility)
      cancelAnimationFrame(animId)
    }
  }, [])

  // 4. Living Micro-Mote Particle Engine (Above Video)
  useEffect(() => {
    const canvas = particleCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    let animId: number

    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      if (rect.width > 0 && rect.height > 0) {
        const rw = Math.round(rect.width)
        const rh = Math.round(rect.height)
        if (canvas.width !== rw || canvas.height !== rh) {
          canvas.width = rw
          canvas.height = rh
        }
      }
    }
    resize()
    window.addEventListener('resize', resize)

    class MarketMote {
      side: 'call' | 'put'
      x: number = 0
      y: number = 0
      vx: number = 0
      vy: number = 0
      color: string = ''
      radius: number = 1
      baseAlpha: number = 0.3
      alpha: number = 0.3

      constructor(side: 'call' | 'put') {
        this.side = side
        this.reset(true)
      }

      reset(init: boolean = false) {
        const w = canvas?.width || 1280
        const h = canvas?.height || 560

        if (this.side === 'call') {
          this.x = init ? Math.random() * (w * 0.45) : Math.random() * (w * 0.38)
          this.y = init ? Math.random() * h : h + 10
          this.vx = (Math.random() - 0.3) * 0.3
          this.vy = -(0.2 + Math.random() * 0.4)
          this.color = Math.random() > 0.4 ? 'rgba(0, 240, 255,' : 'rgba(0, 230, 118,'
        } else {
          this.x = init ? (w * 0.55) + Math.random() * (w * 0.45) : (w * 0.6) + Math.random() * (w * 0.4)
          this.y = init ? Math.random() * h : h + 10
          this.vx = (Math.random() - 0.7) * 0.3
          this.vy = -(0.2 + Math.random() * 0.45)
          this.color = Math.random() > 0.35 ? 'rgba(255, 42, 85,' : 'rgba(230, 0, 57,'
        }

        this.radius = 0.75 + Math.random() * 1.2
        this.baseAlpha = 0.2 + Math.random() * 0.35
        this.alpha = this.baseAlpha
      }

      update() {
        const w = canvas?.width || 1280
        const curState = stateRef.current

        if (curState === 'CALL_DEVELOPING' || curState === 'SESSION_LAST') {
          if (this.side === 'call') {
            this.vx += 0.008
            this.alpha = Math.min(0.75, this.baseAlpha * 1.3)
          } else {
            this.alpha = this.baseAlpha * 0.35
          }
        } else if (curState === 'CALL') {
          if (this.side === 'call') {
            this.vx += 0.015
            this.alpha = Math.min(0.7, this.baseAlpha * 1.3)
          } else {
            this.alpha = this.baseAlpha * 0.2
          }
        } else if (curState === 'PUT_DEVELOPING') {
          if (this.side === 'put') {
            this.vx -= 0.008
            this.vy -= 0.005
            this.alpha = Math.min(0.8, this.baseAlpha * 1.4)
          } else {
            this.alpha = this.baseAlpha * 0.35
          }
        } else if (curState === 'PUT') {
          if (this.side === 'put') {
            this.vx -= 0.015
            this.vy -= 0.005
            this.alpha = Math.min(0.75, this.baseAlpha * 1.3)
          } else {
            this.alpha = this.baseAlpha * 0.2
          }
        } else if (curState === 'REVERSAL_WATCH') {
          this.vx += (Math.random() - 0.5) * 0.02
          this.alpha = Math.min(0.7, this.baseAlpha * 1.2)
        } else if (curState === 'STALE') {
          this.vx *= 0.5
          this.vy *= 0.5
          this.alpha = this.baseAlpha * 0.35
        } else if (curState === 'UNAVAILABLE') {
          this.alpha = this.baseAlpha * 0.15
        } else {
          this.alpha = this.baseAlpha
        }

        this.x += this.vx
        this.y += this.vy

        if (this.y < -10 || this.x < -20 || this.x > w + 20) {
          this.reset()
        }
      }

      draw() {
        if (!ctx) return
        ctx.beginPath()
        ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2)
        ctx.fillStyle = `${this.color}${this.alpha})`
        ctx.fill()
      }
    }

    const motes: MarketMote[] = []
    for (let i = 0; i < 23; i++) {
      motes.push(new MarketMote('call'))
      motes.push(new MarketMote('put'))
    }

    const render = () => {
      if (document.hidden) return
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      motes.forEach(m => {
        m.update()
        m.draw()
      })
      if (!reduceMotion) animId = requestAnimationFrame(render)
    }

    const handleVisibility = () => {
      cancelAnimationFrame(animId)
      if (!document.hidden && !reduceMotion) animId = requestAnimationFrame(render)
    }
    animId = requestAnimationFrame(render)
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      window.removeEventListener('resize', resize)
      document.removeEventListener('visibilitychange', handleVisibility)
      cancelAnimationFrame(animId)
    }
  }, [])

  const isBullDominant =
    !isOperationalUnavailable &&
    (safeState === 'CALL' ||
      safeState === 'CALL_DEVELOPING' ||
      (effectiveSessionLast && Boolean(effectiveState?.startsWith('CALL'))))

  const isBearDominant =
    !isOperationalUnavailable &&
    (safeState === 'PUT' ||
      safeState === 'PUT_DEVELOPING' ||
      (effectiveSessionLast && Boolean(effectiveState?.startsWith('PUT'))))

  const isContested = !isOperationalUnavailable && safeState === 'REVERSAL_WATCH'

  return (
    <div
      className={styles.marketPanel}
      aria-label="Living Market Forces Actor Viewport"
      data-active-market-state={isOperationalUnavailable ? 'NONE' : safeState}
      data-operational-status={operationalStatus}
      data-stage-mode={stageMode}
    >
      {/* LAYER 1 (BEHIND VIDEO): Volumetric Light Rays */}
      <canvas ref={rayCanvasRef} className={styles.volumetricRayCanvas} />

      {/* LAYER 2 (MIDDLE): Multi-Layer Video Stack (Natural Ray Occluder) */}
      <div className={styles.videoStage}>
        <video
          ref={el => { videoRefs.current.vidBalanced = el }}
          className={`${styles.actorVideo} ${activeTargetId === 'vidBalanced' ? styles.actorVideoActive : ''}`}
          playsInline
          muted
          loop
          preload="auto"
          src="/market_forces/dual-01-balanced-sideways.mp4"
        />
        <video
          ref={el => { videoRefs.current.vidBullPressure = el }}
          className={`${styles.actorVideo} ${activeTargetId === 'vidBullPressure' ? styles.actorVideoActive : ''}`}
          playsInline
          muted
          preload={activeTargetId === 'vidBullPressure' ? 'auto' : 'metadata'}
          src="/market_forces/bull-02-pressure-advance.mp4"
        />
        <video
          ref={el => { videoRefs.current.vidBullDominant = el }}
          className={`${styles.actorVideo} ${activeTargetId === 'vidBullDominant' ? styles.actorVideoActive : ''}`}
          playsInline
          muted
          preload={activeTargetId === 'vidBullDominant' ? 'auto' : 'metadata'}
          src="/market_forces/bull-03-full-dominance.mp4"
        />
        <video
          ref={el => { videoRefs.current.vidBearPressure = el }}
          className={`${styles.actorVideo} ${activeTargetId === 'vidBearPressure' ? styles.actorVideoActive : ''}`}
          playsInline
          muted
          preload={activeTargetId === 'vidBearPressure' ? 'auto' : 'metadata'}
          src="/market_forces/bear-02-pressure-advance.mp4"
        />
        <video
          ref={el => { videoRefs.current.vidBearDominant = el }}
          className={`${styles.actorVideo} ${styles.bearDominantFlipped} ${activeTargetId === 'vidBearDominant' ? styles.actorVideoActive : ''}`}
          playsInline
          muted
          preload={activeTargetId === 'vidBearDominant' ? 'auto' : 'metadata'}
          src="/market_forces/bear-03-full-dominance.mp4"
        />
      </div>

      {/* LAYER 3 (ABOVE VIDEO): Atmospheric Floating Micro-Motes */}
      <canvas ref={particleCanvasRef} className={styles.particleCanvas} />

      {/* LAYER 4: Obsidian Radial Vignette */}
      <div className={styles.vignetteOverlay} />

      {/* LAYER 5: Minimal Institutional HUD */}
      <div className={styles.hudOverlay}>
        <div className={styles.hudHeaderGrid}>
          {/* Left: CALL FORCE */}
          <div className={`${styles.actorTag} ${styles.actorTagCall} ${isBullDominant ? styles.actorTagDominant : isContested ? styles.actorTagContested : ''}`}>
            <span className={`${styles.tagLabel} ${styles.tagLabelCall}`}>CALL FORCE</span>
            <span className={`${styles.tagTitle} ${styles.tagTitleCall}`}>BULL</span>
          </div>

          {/* Center: MARKET CORE / NIFTY */}
          <div className={styles.centerMarketCore}>
            <span className={styles.niftyLabel}>NIFTY MARKET VIEW</span>
            <div className={`${styles.marketStateBadge} ${activeBadgeClass}`}>
              {activeBadgeText}
            </div>
            <span className={styles.actorSublabel}>{activeSublabel}</span>
          </div>

          {/* Right: PUT FORCE */}
          <div className={`${styles.actorTag} ${styles.actorTagPut} ${isBearDominant ? styles.actorTagDominant : isContested ? styles.actorTagContested : ''}`}>
            <span className={`${styles.tagLabel} ${styles.tagLabelPut}`}>PUT FORCE</span>
            <span className={`${styles.tagTitle} ${styles.tagTitlePut}`}>BEAR</span>
          </div>
        </div>

        <div className={styles.hudFooterGrid}>
          <div className={styles.hudChip}>
            <span>SPOT:</span>
            <strong style={{ color: '#f0f4fc' }}>
              {Number.isFinite(spotPrice) ? (spotPrice as number).toFixed(2) : '—'}
            </strong>
          </div>
          <div className={styles.hudChip}>
            <span>FUT BASIS:</span>
            <strong style={{
              color: Number.isFinite(basis)
                ? ((basis as number) > 0 ? '#00f0ff' : (basis as number) < 0 ? '#ff2a55' : '#cbd5e1')
                : '#64748b'
            }}>
              {Number.isFinite(basis)
                ? `${(basis as number) > 0 ? '+' : ''}${(basis as number).toFixed(2)}`
                : '—'}
            </strong>
          </div>
        </div>
      </div>
    </div>
  )
})
