'use client'

import React, { useEffect, useState, useCallback, useTransition, useRef } from 'react'

// Web Audio API Sound Synthesizer for Live Microstructure Events
function playLiveIslandTone(type: 'bull' | 'bear' | 'gex') {
  if (typeof window === 'undefined') return
  try {
    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
    if (!AudioCtx) return
    const ctx = new AudioCtx()
    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => {})
    }
    const now = ctx.currentTime

    if (type === 'gex') {
      // Double tone for GEX flip (523.25 Hz then 659.25 Hz chime)
      const osc1 = ctx.createOscillator()
      const gain1 = ctx.createGain()
      osc1.type = 'triangle'
      osc1.frequency.setValueAtTime(523.25, now)
      gain1.gain.setValueAtTime(0.001, now)
      gain1.gain.linearRampToValueAtTime(0.12, now + 0.03)
      gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.12)
      osc1.connect(gain1)
      gain1.connect(ctx.destination)
      osc1.start(now)
      osc1.stop(now + 0.12)

      const osc2 = ctx.createOscillator()
      const gain2 = ctx.createGain()
      osc2.type = 'triangle'
      osc2.frequency.setValueAtTime(659.25, now + 0.10)
      gain2.gain.setValueAtTime(0.001, now + 0.10)
      gain2.gain.linearRampToValueAtTime(0.12, now + 0.13)
      gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.25)
      osc2.connect(gain2)
      gain2.connect(ctx.destination)
      osc2.start(now + 0.10)
      osc2.stop(now + 0.25)
    } else if (type === 'bull') {
      // Rising tone for Bull / Call (440Hz -> 880Hz)
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.setValueAtTime(440, now)
      osc.frequency.exponentialRampToValueAtTime(880, now + 0.18)
      gain.gain.setValueAtTime(0.001, now)
      gain.gain.linearRampToValueAtTime(0.10, now + 0.04)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(now)
      osc.stop(now + 0.18)
    } else if (type === 'bear') {
      // Falling tone for Bear / Put (880Hz -> 440Hz)
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.setValueAtTime(880, now)
      osc.frequency.exponentialRampToValueAtTime(440, now + 0.18)
      gain.gain.setValueAtTime(0.001, now)
      gain.gain.linearRampToValueAtTime(0.10, now + 0.04)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(now)
      osc.stop(now + 0.18)
    }
  } catch {
    // Non-critical audio failure fails silently
  }
}

export interface LiveIslandEvent {
  id: string
  type: string
  family?: string
  title: string
  shortTitle: string
  currentValue: string
  previousValue?: string | null
  secondaryValue?: string | null
  numericTrend: 'UP' | 'DOWN' | 'FLAT'
  eventBias: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | 'RISK' | 'UNCLASSIFIED'
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  phase: 'IMPACT' | 'SETTLED' | 'MEMORY'
  archetype: 'scalar' | 'polarity' | 'dual_sided' | 'level' | 'impulse'
  archetypeData?: Record<string, any>
  acceleration?: number | null
  age?: number
  timestamp?: number
}

export interface LiveIslandState {
  spineBias: 'bear' | 'bull'
  activeEvents: LiveIslandEvent[]
  memoryEvents: LiveIslandEvent[]
  burstCount: number
  activeCapacity?: number
  memoryCapacity?: number
  lastSequenceId?: number
  updatedAt?: number
}

const DEFAULT_STATE: LiveIslandState = {
  spineBias: 'bear',
  activeEvents: [],
  memoryEvents: [],
  burstCount: 0,
}

function getBiasClass(bias?: string): string {
  switch ((bias || '').toUpperCase()) {
    case 'BEARISH': return 'bias-bearish'
    case 'BULLISH': return 'bias-bullish'
    case 'NEUTRAL': return 'bias-neutral'
    case 'RISK': return 'bias-risk'
    default: return 'bias-neutral'
  }
}

function getOrbClass(bias?: string): string {
  switch ((bias || '').toUpperCase()) {
    case 'BEARISH': return 'orb-bearish'
    case 'BULLISH': return 'orb-bullish'
    case 'NEUTRAL': return 'orb-neutral'
    case 'RISK': return 'orb-risk'
    default: return 'orb-neutral'
  }
}

function renderArchetype(event: LiveIslandEvent) {
  const bClass = getBiasClass(event.eventBias)
  const data = event.archetypeData || {}

  switch (event.archetype) {
    case 'scalar':
      return (
        <div className="scalar-stage">
          <span className="scalar-old-val">{data.oldVal || event.previousValue || '—'}</span>
          <span className="scalar-arrow">
            {event.numericTrend === 'UP' ? '↑' : (event.numericTrend === 'DOWN' ? '↓' : '→')}
          </span>
          <span className={`scalar-new-val ${bClass}`}>{event.currentValue}</span>
          {data.change && (
            <span className={`scalar-rate-badge ${bClass}`}>{data.change}</span>
          )}
        </div>
      )

    case 'polarity':
      return (
        <div className="polarity-stage">
          <div className="polarity-pole pole-prev">
            <span className="pole-label">{data.prevPole || '+GEX'}</span>
            <span className="pole-val" style={{ color: 'var(--live-island-text-lo)' }}>
              {data.prevVal || event.previousValue || '0'}
            </span>
          </div>
          <div className="polarity-crossing-track">
            <div className="polarity-track-line" />
            <div className="polarity-zero-pip">0</div>
          </div>
          <div className="polarity-pole pole-curr">
            <span className="pole-label">{data.currPole || '-GEX'}</span>
            <span className={`pole-val ${bClass}`}>{data.currVal || event.currentValue}</span>
          </div>
        </div>
      )

    case 'dual_sided': {
      const isRightDominant = data.dominantSide !== 'left'
      return (
        <div className="dual-sided-stage">
          <div className={`dual-side-box ${!isRightDominant ? 'is-dominant' : ''}`}>
            <span style={{ fontSize: '8px', color: 'var(--live-island-text-lo)' }}>
              {data.leftSide || 'CALL ΔOI'}
            </span>
            <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--live-island-ivory)' }}>
              {data.leftVal || '—'}
            </span>
          </div>
          <div className="dual-flow-bridge">→</div>
          <div className={`dual-side-box ${isRightDominant ? 'is-dominant' : ''}`}>
            <span style={{ fontSize: '8px', color: 'var(--live-island-text-lo)' }}>
              {data.rightSide || 'PUT ΔOI'}
            </span>
            <span className={bClass} style={{ fontSize: '12px', fontWeight: 700 }}>
              {data.rightVal || '—'}
            </span>
          </div>
        </div>
      )
    }

    case 'level':
      return (
        <div className="level-stage">
          <span className="level-old-strike">{data.oldStrike || event.previousValue || '—'}</span>
          <span className="level-pin-icon">⚲</span>
          <span className={`level-new-strike ${bClass}`}>{data.newStrike || event.currentValue}</span>
        </div>
      )

    case 'impulse':
      return (
        <div className="impulse-stage">
          <span style={{ fontSize: '10px', color: 'var(--live-island-text-lo)' }}>BURST</span>
          <span className={bClass} style={{ fontSize: '17px', fontWeight: 700 }}>
            {data.blastIntensity || event.currentValue}
          </span>
          <span style={{
            fontSize: '10px',
            padding: '1px 5px',
            borderRadius: '4px',
            background: 'rgba(0,240,255,0.12)',
            color: 'var(--live-island-cyan)',
            border: '1px solid rgba(0,240,255,0.3)'
          }}>
            IMPULSE
          </span>
        </div>
      )

    default:
      return (
        <div className="scalar-stage">
          <span className={`scalar-new-val ${bClass}`}>{event.currentValue}</span>
        </div>
      )
  }
}

export interface CitadelLiveIslandProps {
  initialState?: LiveIslandState
  streamUrl?: string
  stateUrl?: string
  overrideSpineBias?: 'bear' | 'bull'
}

export const CitadelLiveIsland: React.FC<CitadelLiveIslandProps> = ({
  initialState,
  streamUrl = 'http://127.0.0.1:8000/v1/oracle/live-island/stream',
  stateUrl = 'http://127.0.0.1:8000/v1/oracle/live-island/state',
  overrideSpineBias,
}) => {
  const [state, setState] = useState<LiveIslandState>(initialState || DEFAULT_STATE)
  const [, startTransition] = useTransition()

  // Real backend SSE data stream connection
  useEffect(() => {
    let sse: EventSource | null = null
    let isMounted = true

    const fetchCurrentState = async () => {
      try {
        const res = await fetch(stateUrl)
        if (res.ok && isMounted) {
          const data: LiveIslandState = await res.json()
          startTransition(() => {
            setState(data)
          })
        }
      } catch {
        // Handled silently
      }
    }

    fetchCurrentState()

    try {
      sse = new EventSource(streamUrl)
      sse.addEventListener('live_island_state', (evt) => {
        try {
          const payload: LiveIslandState = JSON.parse(evt.data)
          if (isMounted) {
            startTransition(() => {
              setState(payload)
            })
          }
        } catch (err) {
          console.warn('[CitadelLiveIsland] State parse error:', err)
        }
      })

      sse.onerror = () => {
        // Fallback: poll state periodically if SSE drops
      }
    } catch (err) {
      console.warn('[CitadelLiveIsland] EventSource init error:', err)
    }

    return () => {
      isMounted = false
      sse?.close()
    }
  }, [streamUrl, stateUrl])

  // Interactive elevation: Promote companion to Hero
  const handlePromoteCompanion = useCallback((id: string) => {
    setState(prev => {
      const idx = prev.activeEvents.findIndex(e => e.id === id)
      if (idx === -1) return prev
      const newActive = [...prev.activeEvents]
      const promoted = { ...newActive.splice(idx, 1)[0], phase: 'IMPACT' as const, timestamp: Date.now() }
      newActive.unshift(promoted)
      return { ...prev, activeEvents: newActive }
    })
  }, [])

  // Interactive reawakening: Reawaken memory footprint
  const handleReawakenMemory = useCallback((id: string) => {
    setState(prev => {
      const idx = prev.memoryEvents.findIndex(e => e.id === id)
      if (idx === -1) return prev
      const newMemory = [...prev.memoryEvents]
      const reawakened = { ...newMemory.splice(idx, 1)[0], phase: 'IMPACT' as const, timestamp: Date.now() }
      const newActive = [reawakened, ...prev.activeEvents]
      return {
        ...prev,
        activeEvents: newActive.slice(0, 4),
        memoryEvents: newMemory,
      }
    })
  }, [])

  const [alertsEnabled, setAlertsEnabled] = useState(true)
  const lastSoundKeyRef = useRef<string>('')
  const lastSoundTimeRef = useRef<number>(0)

  const toggleAlerts = useCallback(() => {
    setAlertsEnabled((prev) => !prev)
  }, [])

  useEffect(() => {
    if (!alertsEnabled) return
    const hero = state.activeEvents?.[0]
    if (!hero) return

    const soundKey = `${hero.id}:${hero.currentValue}:${hero.eventBias}`
    if (soundKey === lastSoundKeyRef.current) {
      return
    }
    lastSoundKeyRef.current = soundKey
    lastSoundTimeRef.current = Date.now()

    if (hero.phase !== 'IMPACT') {
      return
    }

    if (hero.id === 'gex' || hero.archetype === 'polarity') {
      playLiveIslandTone('gex')
    } else if (hero.eventBias === 'BULLISH') {
      playLiveIslandTone('bull')
    } else if (hero.eventBias === 'BEARISH') {
      playLiveIslandTone('bear')
    }
  }, [alertsEnabled, state.activeEvents])

  const effectiveSpine = overrideSpineBias || state.spineBias || 'bear'
  const isSpineBull = effectiveSpine === 'bull'
  const heroEvent = state.activeEvents?.[0] || null
  const satelliteEvents = state.activeEvents?.slice(1, 4) || []
  const memoryEvents = state.memoryEvents?.slice(0, 3) || []

  const isParticipantRead = Boolean(
    heroEvent &&
      (heroEvent.family === 'dominance' ||
        heroEvent.id === 'buyers_writers' ||
        heroEvent.title?.includes('Dominance') ||
        heroEvent.title?.includes('Buyers') ||
        heroEvent.title?.includes('Writers'))
  )

  // Dynamic kinetic sweep calculation
  const absAccel = Math.max(0.12, Math.abs(heroEvent?.acceleration || 0.5))
  const sweepDurationMs = Math.round(1400 / absAccel)
  const isReverse = heroEvent?.numericTrend === 'DOWN' || (heroEvent?.acceleration != null && heroEvent.acceleration < 0)
  const sweepDirection = isReverse ? 'reverse' : 'normal'
  const rateKeyword = heroEvent?.archetypeData?.rateText || (heroEvent?.phase === 'IMPACT' ? 'ACCELERATING' : 'SETTLED')

  const isOpposingSpine = heroEvent && (
    (isSpineBull && heroEvent.eventBias === 'BEARISH') ||
    (!isSpineBull && heroEvent.eventBias === 'BULLISH')
  )

  return (
    <div
      className={`island-stage spine-${effectiveSpine}`}
      data-spine={effectiveSpine}
      data-testid="citadel-live-island"
      aria-label="Citadel Live Island Sensor"
    >
      <div className="island-interactive-zone">
        <div id="island-cluster" className="island-cluster">
          {/* 1. Hero Pill */}
          {!heroEvent ? (
            <div
              className="oracle-island-pill oracle-island-hero"
              style={{ minWidth: '320px', justifyContent: 'center', gap: '10px' }}
            >
              <div className="spine-bias-pip" />
              <span
                style={{
                  fontFamily: 'var(--font-oracle-display, sans-serif)',
                  fontSize: '12px',
                  fontWeight: 600,
                  color: 'var(--live-island-text-mid)',
                  letterSpacing: '0.04em',
                }}
              >
                CITADEL ORACLE · ALL REGIMES NOMINAL
              </span>
            </div>
          ) : (
            <div
              className={`oracle-island-pill oracle-island-hero ${
                heroEvent.archetype === 'impulse' ? 'is-impulse-active' : ''
              }`}
              style={{
                '--rate-energy-duration': `${sweepDurationMs}ms`,
                '--rate-energy-direction': sweepDirection,
              } as React.CSSProperties}
            >
              <div className="hero-content">
                <div className="hero-left-cluster">
                  <div className="spine-bias-pip" title="Master Spike Spine Bias" />
                  <div
                    className={`event-bias-orb ${getOrbClass(heroEvent.eventBias)}`}
                    title={`Event Bias: ${heroEvent.eventBias}`}
                  />
                  <div className="hero-titles">
                    <div className="hero-headline-row">
                      <span className="hero-main-title">{heroEvent.title}</span>
                      {isParticipantRead && (
                        <span
                          className="heuristic-participant-badge"
                          title="Heuristic read inferred from premium & OI. Not direct trade flow causality."
                        >
                          HEURISTIC
                        </span>
                      )}
                      {isOpposingSpine && (
                        <span
                          className="split-bias-notch"
                          title="Opposes current Spike Spine bias"
                        />
                      )}
                      {state.burstCount > 1 && (
                        <span className="burst-counter-badge">+{state.burstCount} BURST</span>
                      )}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span className="hero-state-short">{heroEvent.secondaryValue || ''}</span>
                      <span style={{ fontSize: '9px', color: 'var(--live-island-text-lo)' }}>·</span>
                      <span className="semantic-rate-kw" style={{ fontSize: '10px' }}>
                        {rateKeyword}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="hero-right-visuals">
                  {renderArchetype(heroEvent)}
                </div>
              </div>
            </div>
          )}

          {/* 2. Satellite Companions */}
          {satelliteEvents.length > 0 && (
            <div className="island-satellites-cluster">
              {satelliteEvents.map((sat) => {
                const satOpposing =
                  (isSpineBull && sat.eventBias === 'BEARISH') ||
                  (!isSpineBull && sat.eventBias === 'BULLISH')
                const bClass = getBiasClass(sat.eventBias)
                const orbClass = getOrbClass(sat.eventBias)
                const phaseClass = sat.phase === 'IMPACT' ? 'phase-hot' : 'phase-settled'

                return (
                  <div
                    key={sat.id}
                    className={`oracle-island-pill oracle-island-companion ${phaseClass}`}
                    onClick={() => handlePromoteCompanion(sat.id)}
                    title={`Click to elevate to Hero | Bias: ${sat.eventBias}`}
                  >
                    <div className={`event-bias-orb ${orbClass}`} />
                    <span className="satellite-title">{sat.shortTitle}</span>
                    <span className={`satellite-val ${bClass}`}>{sat.currentValue}</span>
                    {satOpposing && <span className="split-bias-notch" />}
                  </div>
                )
              })}
            </div>
          )}

          {/* 3. Memory Plane */}
          {memoryEvents.length > 0 && (
            <div className="island-memory-plane">
              {memoryEvents.map((mem) => (
                <div
                  key={mem.id}
                  className="temporal-memory-footprint"
                  onClick={() => handleReawakenMemory(mem.id)}
                  title={`Memory Echo: click to reawaken (${mem.title})`}
                >
                  <span className="footprint-title">{mem.shortTitle}</span>
                  <span className="footprint-val">{mem.currentValue}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
