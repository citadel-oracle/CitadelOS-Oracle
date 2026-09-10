'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import {
  formatNumber,
  type PhotonicArgusVobViewModel,
  UNKNOWN,
} from '../photonicPresentationHelpers'

export interface PhotonicDisplayScores {
  vobSetup?: number | null
  turnStrength?: number | null
  marketSupport?: number | null
  overall?: number | null
  [key: string]: any
}

export interface PhotonicOracleHeroWheelProps {
  presentation?: 'VOB' | 'STRADDLE' | 'FIT'
  state?: string
  direction?: string
  quality?: string
  vobState?: string
  scores?: PhotonicDisplayScores | null
  action?: string
  heroDescription?: string
  argusState?: string
  viewModel?: PhotonicArgusVobViewModel | null
  proximity?: string
  intelligence?: Readonly<Record<string, unknown>> | null
}

function positioningTone(positioning: string | null | undefined): string {
  if (!positioning || positioning === UNKNOWN) return 'var(--text-lo)'
  const upper = positioning.toUpperCase()
  if (upper.includes('LONG BUILD') || upper.includes('BUY') || upper.includes('LONG') || upper.includes('SUPPORT')) {
    return 'var(--mint)'
  }
  if (upper.includes('WRIT') || upper.includes('SHORT BUILD') || upper.includes('SELL') || upper.includes('BEAR')) {
    return 'var(--algory-red)'
  }
  if (upper.includes('SHORT COVER') || upper.includes('COVER')) {
    return 'var(--cyan)'
  }
  if (upper.includes('UNWIND') || upper.includes('MIXED')) {
    return 'var(--amber)'
  }
  return 'var(--text-white)'
}

export const PhotonicOracleHeroWheel = memo(function PhotonicOracleHeroWheel({
  presentation = 'VOB',
  state = 'WATCHING',
  direction = 'CALL',
  quality = 'PRIME',
  vobState = 'ACTIVE',
  scores = null,
  action = 'WATCH CALL TURN',
  heroDescription = 'The VOB episode is valid. Oracle is watching the turn without forcing a signal.',
  argusState = 'UNKNOWN',
  viewModel = null,
  proximity = '',
  intelligence = null,
}: PhotonicOracleHeroWheelProps) {
  if (presentation !== 'VOB') return <PhotonicSecondaryWheel presentation={presentation} intelligence={intelligence} />
  const activeDirection = viewModel?.bias && viewModel.bias !== 'UNKNOWN' ? viewModel.bias : direction
  const isCall = activeDirection === 'CALL'
  const isPut = activeDirection === 'PUT'
  const isRange = activeDirection === 'RANGE BOUND' || activeDirection === 'BALANCED'

  // LINE 1: CALL, PUT, RANGE BOUND, or BALANCED
  const biasLine = isCall || isPut || isRange ? activeDirection : 'ORACLE VECTOR'
  const biasColor = isCall ? 'var(--mint)' : isPut ? 'var(--algory-red)' : isRange ? 'var(--amber)' : 'var(--cyan)'

  // LINE 2: Canonical ARGUS Prime Positioning
  const positioningLine = viewModel?.positioning && viewModel.positioning !== 'UNKNOWN'
    ? viewModel.positioning
    : action

  // Participation Dominance Percentages (Hero Metric)
  const buyPctText = viewModel?.buyPct !== null && viewModel?.buyPct !== undefined ? `${viewModel.buyPct.toFixed(0)}%` : '—'
  const writePctText = viewModel?.writePct !== null && viewModel?.writePct !== undefined ? `${viewModel.writePct.toFixed(0)}%` : '—'

  // Strike Spine & Focus Strike
  const focusStrike = viewModel?.focusStrike ?? null
  const focusStrikeLabel = viewModel?.focusStrikeLabel ?? (focusStrike !== null ? 'FOCUS STRIKE' : 'STRIKE UNKNOWN')
  const cePositioning = viewModel?.focusStrikeCePositioning ?? 'UNKNOWN'
  const pePositioning = viewModel?.focusStrikePePositioning ?? 'UNKNOWN'
  const ceToneColor = positioningTone(cePositioning)
  const peToneColor = positioningTone(pePositioning)

  // Price Rail calculations
  const nifty = viewModel?.nifty ?? null
  const supportVob = viewModel?.bullishVob ?? null
  const resistanceVob = viewModel?.bearishVob ?? null

  const lowerBound = supportVob !== null && resistanceVob !== null ? Math.min(supportVob, resistanceVob) : (supportVob ?? resistanceVob)
  const upperBound = supportVob !== null && resistanceVob !== null ? Math.max(supportVob, resistanceVob) : (resistanceVob ?? supportVob)

  let niftyRailPct = 50
  if (nifty !== null && lowerBound !== null && upperBound !== null && upperBound > lowerBound) {
    niftyRailPct = Math.min(100, Math.max(0, ((nifty - lowerBound) / (upperBound - lowerBound)) * 100))
  }

  let locationText = proximity || 'CANONICAL PROXIMITY'
  if (viewModel?.location === 'IN_ZONE') locationText = proximity ? `IN ZONE · ${proximity}` : 'IN VOB ZONE'
  else if (viewModel?.location === 'BELOW') locationText = proximity ? `BELOW · ${proximity}` : 'BELOW VOB ZONE'
  else if (viewModel?.location === 'ABOVE') locationText = proximity ? `ABOVE · ${proximity}` : 'ABOVE VOB ZONE'

  return (
    <div
      className={`${styles.card} ${styles.cardWheel} ${isCall ? styles.wheelGlowCall : styles.wheelGlowPut}`}
      aria-label="Active Opportunity Vector Chromatic Plasma Orb"
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '14px' }}>
        <div className={styles.monoLabel} style={{ color: 'var(--cyan)' }}>
          HERO ACTIVE OPPORTUNITY VECTOR
        </div>
        <div className={`${styles.pill} ${isCall ? styles.pillMint : styles.pillAmber}`}>
          ● {state}
        </div>
      </div>

      {/* Center Plasma Orb + Orbiting Satellites — ONLY TWO ITEMS INSIDE THE WHEEL */}
      <div className={styles.plasmaSphereContainer} style={{ margin: '0 auto 12px' }}>
        {/* Orbital Resonance Ring 1 */}
        <div className={styles.orbitFlareRing1}>
          <div className={styles.orbitSatellite1} />
        </div>

        {/* Orbital Resonance Ring 2 */}
        <div className={styles.orbitFlareRing2}>
          <div className={styles.orbitSatellite2} />
        </div>

        {/* Liquid Chromatic Core Orb */}
        <div className={styles.liquidColorCore} />

        {/* Inner Glass Center Badge — ONLY TWO ITEMS: 1. BIAS (CALL/PUT/RANGE), 2. ARGUS POSITIONING */}
        <div className={styles.coreGlassBadge} style={{ minWidth: '96px', padding: '6px 10px', textAlign: 'center' }}>
          <span style={{ color: biasColor, fontSize: '12.5px', fontWeight: 800, letterSpacing: '0.08em', lineHeight: 1.1 }}>
            {biasLine}
          </span>
          <b style={{ color: 'var(--text-white)', fontSize: '8.5px', fontWeight: 700, marginTop: '3px', whiteSpace: 'nowrap' }}>
            {positioningLine !== 'UNKNOWN' ? positioningLine : 'ARGUS PRIME'}
          </b>
        </div>
      </div>

      {/* Hero-like Participation Dominance Metric (BUY XX% · WRITE YY%) */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          gap: '24px',
          marginBottom: '12px',
          padding: '8px 14px',
          background: 'rgba(0, 0, 0, 0.45)',
          borderRadius: '8px',
          border: '1px solid var(--line-dim)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
          <span className={styles.monoLabel} style={{ color: 'var(--text-mid)', fontSize: '10px', fontWeight: 600 }}>BUY</span>
          <span className={styles.monoLabel} style={{ color: 'var(--mint)', fontSize: '14.5px', fontWeight: 800, textShadow: '0 0 10px rgba(0,255,157,0.35)' }}>
            {buyPctText}
          </span>
        </div>
        <div style={{ width: '1px', height: '14px', background: 'var(--line-dim)' }} />
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
          <span className={styles.monoLabel} style={{ color: 'var(--text-mid)', fontSize: '10px', fontWeight: 600 }}>WRITE</span>
          <span className={styles.monoLabel} style={{ color: 'var(--algory-red)', fontSize: '14.5px', fontWeight: 800, textShadow: '0 0 10px rgba(255,30,75,0.35)' }}>
            {writePctText}
          </span>
        </div>
      </div>

      {/* Compact Strike Spine: Left (CE Positioning) ── Center (Focus Strike) ── Right (PE Positioning) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr auto 1fr',
          alignItems: 'center',
          gap: '10px',
          marginBottom: '14px',
          padding: '10px 12px',
          background: 'rgba(0, 0, 0, 0.3)',
          borderRadius: '8px',
          border: '1px solid var(--line-dim)',
        }}
      >
        {/* Left: CE Positioning */}
        <div style={{ textAlign: 'left' }}>
          <div className={styles.monoLabel} style={{ color: 'var(--cyan)', fontSize: '9px', fontWeight: 700, marginBottom: '2px' }}>
            CE
          </div>
          <div className={styles.monoLabel} style={{ color: ceToneColor, fontSize: '11px', fontWeight: 700 }}>
            {cePositioning}
          </div>
        </div>

        {/* Center: Focus Strike */}
        <div style={{ textAlign: 'center', padding: '0 12px', borderLeft: '1px solid var(--line-dim)', borderRight: '1px solid var(--line-dim)' }}>
          <div className={styles.title} style={{ fontSize: '16px', fontWeight: 800, color: 'var(--text-white)', letterSpacing: '0.04em' }}>
            {formatNumber(focusStrike)}
          </div>
          <div className={styles.monoLabel} style={{ color: 'var(--text-lo)', fontSize: '8px', fontWeight: 600, letterSpacing: '0.08em', marginTop: '1px' }}>
            {focusStrikeLabel}
          </div>
        </div>

        {/* Right: PE Positioning */}
        <div style={{ textAlign: 'right' }}>
          <div className={styles.monoLabel} style={{ color: 'var(--amber)', fontSize: '9px', fontWeight: 700, marginBottom: '2px' }}>
            PE
          </div>
          <div className={styles.monoLabel} style={{ color: peToneColor, fontSize: '11px', fontWeight: 700 }}>
            {pePositioning}
          </div>
        </div>
      </div>

      {/* Bottom price rail summary: Live NIFTY relative to Canonical VOB Structure */}
      <div style={{ borderTop: '1px solid var(--line-dim)', paddingTop: '10px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
          <span className={styles.monoLabel}>SUPPORT VOB {formatNumber(supportVob)}</span>
          <span className={styles.monoLabel} style={{ color: isCall ? 'var(--mint)' : 'var(--algory-red)', fontWeight: 700 }}>
            NIFTY {formatNumber(nifty)}
          </span>
          <span className={styles.monoLabel}>RESISTANCE VOB {formatNumber(resistanceVob)}</span>
        </div>
        <div className={styles.teslaTrack} style={{ height: '4px', marginBottom: '10px' }}>
          <div className={`${styles.teslaFill} ${styles.teslaFillMint}`} style={{ width: `${niftyRailPct}%` }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span className={styles.monoLabel}>CANONICAL VOB ENVELOPE</span>
          <span className={styles.monoLabel} style={{ color: 'var(--text-white)' }}>{locationText}</span>
        </div>
      </div>
    </div>
  )
})

function SecondaryWheelRow({ label, value, primary = false, tone }: { label: string; value: string; primary?: boolean; tone?: string }) {
  return (
    <div className={`${styles.secondaryWheelRow} ${primary ? styles.secondaryWheelRowPrimary : ''}`}>
      <span>{label}</span>
      <strong style={{ color: tone ?? 'var(--text-white)' }}>{value}</strong>
    </div>
  )
}

const PhotonicSecondaryWheel = memo(function PhotonicSecondaryWheel({
  presentation,
  intelligence,
}: Pick<PhotonicOracleHeroWheelProps, 'presentation' | 'intelligence'>) {
  const root: Readonly<Record<string, unknown>> = intelligence && typeof intelligence === 'object' ? intelligence : {}
  const straddle = root.straddle && typeof root.straddle === 'object' ? root.straddle as Record<string, unknown> : {}
  const fit = root.fit && typeof root.fit === 'object' ? root.fit as Record<string, unknown> : {}
  const isStraddle = presentation === 'STRADDLE'
  const straddleNow = typeof straddle.now === 'number' && Number.isFinite(straddle.now) ? straddle.now : null
  const straddleHolding = typeof straddle.premium_holding === 'number' && Number.isFinite(straddle.premium_holding) ? straddle.premium_holding : null
  const state = isStraddle ? (straddleNow === null ? '—' : String(straddle.state ?? '—')) : String(fit.state ?? 'NO CLEAN FIT')
  const call = fit.call_evidence ?? '—'
  const put = fit.put_evidence ?? '—'
  const money = (value: unknown, signed = false) => typeof value === 'number' && Number.isFinite(value) ? `${signed && value > 0 ? '+' : ''}₹${value.toFixed(2)}` : '—'
  const points = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? `~${value.toFixed(2)} pts` : '—'
  const driver = straddleNow === null ? '—' : String(straddle.premium_driver ?? 'MIXED')
  const holding = straddleHolding === null ? '—' : `${money(Math.abs(straddleHolding))} ${straddleHolding >= 0 ? 'STRONGER' : 'WEAKER'}`

  return (
    <div
      className={`${styles.card} ${styles.cardWheel} ${styles.cardOracleHero} ${styles.secondaryWheel}`}
      aria-label={isStraddle ? 'Straddle state wheel' : 'Call put evidence fit wheel'}
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />
      <div style={{ position: 'relative', zIndex: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px' }}>
        <div className={styles.monoLabel} style={{ color: 'var(--cyan)' }}>
          {isStraddle ? 'STRADDLE STATE' : 'CALL / PUT EVIDENCE / FIT'}
        </div>
        <div className={`${styles.pill} ${styles.pillAmber}`}>● {state}</div>
      </div>
      <div className={styles.plasmaSphereContainer} style={{ margin: '0 auto 12px' }}>
        <div className={styles.orbitFlareRing1}>
          <div className={styles.orbitSatellite1} />
        </div>
        <div className={styles.orbitFlareRing2}>
          <div className={styles.orbitSatellite2} />
        </div>
        <div className={styles.liquidColorCore} />
        <div className={styles.coreGlassBadge} style={{ minWidth: '96px', padding: '6px 10px', textAlign: 'center' }}>
          <span style={{ color: 'var(--cyan)', fontSize: '12px', fontWeight: 800, letterSpacing: '.08em' }}>
            {isStraddle ? 'STRADDLE' : 'NO CLEAN FIT'}
          </span>
          <b style={{ color: 'var(--text-white)', fontSize: '9px', display: 'block', marginTop: '3px' }}>{state}</b>
        </div>
      </div>
      <div className={styles.secondaryWheelRows}>
        {isStraddle ? (
          <>
            <SecondaryWheelRow label="NOW" value={money(straddleNow)} primary={straddleNow !== null} />
            <SecondaryWheelRow label="PREMIUM TODAY" value={money(straddle.premium_today, true)} />
            <SecondaryWheelRow label="MARKET STILL PRICES" value={points(straddle.market_still_prices)} />
            <SecondaryWheelRow label="TIME LOSS EXPECTED" value={money(straddle.time_loss_expected, true)} />
            <SecondaryWheelRow label="ACTUAL CHANGE" value={money(straddle.actual_change, true)} />
            <SecondaryWheelRow
              label="PREMIUM HOLDING"
              value={holding}
              primary={straddleHolding !== null}
              tone={straddleHolding === null ? undefined : straddleHolding >= 0 ? 'var(--mint)' : 'var(--algory-red)'}
            />
            <SecondaryWheelRow label="PREMIUM DRIVER" value={driver} />
            <SecondaryWheelRow label="CALL" value={money(straddle.call_change, true)} />
            <SecondaryWheelRow label="PUT" value={money(straddle.put_change, true)} />
            <SecondaryWheelRow label="VWAP" value="—" />
            <SecondaryWheelRow label="PREMIUM EXPANSION" value="—" />
          </>
        ) : (
          <>
            <SecondaryWheelRow label="CALL EVIDENCE" value={call === '—' ? '— / 5' : `${call} / 5`} />
            <SecondaryWheelRow label="PUT EVIDENCE" value={put === '—' ? '— / 5' : `${put} / 5`} />
            <SecondaryWheelRow label="PRICE" value="—" />
            <SecondaryWheelRow label="FLOW" value="—" />
            <SecondaryWheelRow label="TIME" value="—" />
            <SecondaryWheelRow label="BOOK" value="—" />
            <SecondaryWheelRow label="ENTRY" value="—" />
            <SecondaryWheelRow label="CURRENT LEAN" value="—" />
          </>
        )}
      </div>
    </div>
  )
})

