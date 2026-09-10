'use client'

import React, { memo, useRef, useEffect, useState } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'

type Data = Readonly<Record<string, unknown>>
const asData = (value: unknown): Data => (value && typeof value === 'object' ? (value as Data) : {})
const number = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const moneyCr = (value: unknown, signed = false): string => {
  const parsed = number(value)
  if (parsed === null) return '—'
  return `${signed && parsed > 0 ? '+' : ''}₹${parsed.toFixed(2)} Cr`
}

const pct = (value: unknown, signed = false): string => {
  const parsed = number(value)
  if (parsed === null) return '—'
  return `${signed && parsed > 0 ? '+' : ''}${parsed.toFixed(2)}%`
}

const num = (value: unknown): string => {
  const parsed = number(value)
  return parsed === null ? '—' : parsed.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

function Row({
  label,
  value,
  subtext,
  tone,
  primary = false,
}: {
  label: string
  value: string
  subtext?: string
  tone?: string
  primary?: boolean
}) {
  return (
    <div className={`${styles.intelligenceRow} ${primary ? styles.intelligenceRowPrimary : ''}`}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
        <span>{label}</span>
        {subtext && <em style={{ color: 'var(--text-lo)', fontSize: '8px', fontStyle: 'normal' }}>{subtext}</em>}
      </div>
      <strong style={{ color: tone ?? 'var(--text-white)' }}>{value}</strong>
    </div>
  )
}

function VobRail({
  left,
  leftValue,
  right,
  rightValue,
  tone = 'mint',
  height = 7,
}: {
  left: string
  leftValue: number
  right: string
  rightValue: number
  tone?: 'mint' | 'red' | 'cyan' | 'amber'
  height?: number
}) {
  const total = Math.abs(leftValue) + Math.abs(rightValue)
  const leftPct = total > 0 ? Math.max(5, Math.min(95, (Math.abs(leftValue) / total) * 100)) : 50
  return (
    <div className={styles.intelligenceRail} aria-label={`${left} versus ${right}`} data-oi-rail>
      <div className={styles.intelligenceRailLabels}>
        <span>{left}</span>
        <span>{right}</span>
      </div>
      <div className={`${styles.teslaTrack} ${styles.vobRailTrack}`} style={{ height: `${height}px` }}>
        <div
          className={`${styles.teslaFill} ${
            tone === 'mint'
              ? styles.teslaFillMint
              : tone === 'red'
              ? styles.teslaFillRed
              : tone === 'cyan'
              ? styles.teslaFillCyan
              : ''
          }`}
          style={{ width: `${leftPct}%`, transition: 'width 0.5s cubic-bezier(0.16, 1, 0.3, 1)' }}
        />
        <div
          className={`${styles.teslaHead} ${
            tone === 'red' ? styles.headRed : tone === 'cyan' ? styles.headCyan : ''
          }`}
          style={{ left: `calc(${leftPct}% - 8px)` }}
        />
      </div>
    </div>
  )
}

function MiniVelocityCard({
  title,
  currentVal,
  delta5m,
  delta15m,
  tone = 'cyan',
  stateLabel = 'STABLE',
  trend = 'STABLE',
}: {
  title: string
  currentVal: string
  delta5m?: string | null
  delta15m?: string | null
  tone?: 'mint' | 'red' | 'cyan' | 'amber'
  stateLabel?: string
  trend?: 'RISING' | 'COOLING' | 'STABLE'
}) {
  const trendIcon = trend === 'RISING' ? '↑' : trend === 'COOLING' ? '↓' : '→'
  const trendColor = trend === 'RISING' ? 'var(--mint)' : trend === 'COOLING' ? 'var(--cyan)' : 'var(--text-lo)'

  return (
    <div
      style={{
        background: 'rgba(0,0,0,0.35)',
        border: '1px solid var(--line-dim)',
        borderRadius: '8px',
        padding: '9px 11px',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span className={styles.monoLabel} style={{ fontSize: '7.5px' }}>{title}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
          <span style={{ fontSize: '9px', color: trendColor, fontWeight: 800 }}>{trendIcon}</span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '7.5px',
              fontWeight: 700,
              color: tone === 'mint' ? 'var(--mint)' : tone === 'red' ? 'var(--algory-red)' : 'var(--text-mid)',
            }}
          >
            {stateLabel}
          </span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginTop: '2px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13.5px', fontWeight: 800, color: 'var(--text-white)' }}>
          {currentVal}
        </span>
        <div style={{ display: 'flex', gap: '6px', fontSize: '8px', fontFamily: 'var(--font-mono)' }}>
          <span style={{ color: 'var(--text-lo)' }}>5m: <strong style={{ color: delta5m ? 'var(--text-mid)' : 'var(--text-lo)' }}>{delta5m ?? 'UNAVAILABLE'}</strong></span>
          <span style={{ color: 'var(--text-lo)' }}>15m: <strong style={{ color: delta15m ? 'var(--text-mid)' : 'var(--text-lo)' }}>{delta15m ?? 'UNAVAILABLE'}</strong></span>
        </div>
      </div>
    </div>
  )
}

export interface PhotonicOptionIntelligenceProps {
  intelligence?: Data | null
}

export const PhotonicOptionIntelligence = memo(function PhotonicOptionIntelligence({
  intelligence,
}: PhotonicOptionIntelligenceProps) {
  const root = asData(intelligence)
  const rawOi = asData(root.option_intelligence)
  const isAvailable = rawOi.status === 'LIVE'

  const gex = asData(rawOi.gex)
  const skew = asData(rawOi.iv_skew)
  const quality = asData(rawOi.gamma_theta_quality)
  const vol = asData(rawOi.volatility_opportunity)

  // 1. Volatility Opportunity Data
  const atmIv = number(vol.atm_iv)
  const intradayRv = number(vol.intraday_rv_annualized)
  const harRvForecast = number(vol.har_rv_forecast_annualized)
  const ivRvSpread = number(vol.iv_rv_spread)
  const volRegime = String(vol.vol_premium_regime ?? 'STANDBY')

  // 2. Gamma / Theta Quality Data
  const atmCeQuality = asData(quality.atm_ce)
  const atmPeQuality = asData(quality.atm_pe)

  // 3. GEX Profile Data
  const netGexCr = number(gex.total_net_gex_inr_cr)
  const callGexCr = number(gex.total_call_gex_inr_cr)
  const putGexCr = number(gex.total_put_gex_inr_cr)
  const zeroGammaStrike = number(gex.zero_gamma_strike)
  const spotDistanceToZero = number(gex.spot_distance_to_zero_gamma)

  // 4. Skew Data (25Δ and 10Δ)
  const skew25dSpread = number(skew.skew_25d_spread)
  const skew10dSpread = number(skew.skew_10d_spread)
  const call25d = asData(skew.call_25d)
  const put25d = asData(skew.put_25d)
  const call10d = asData(skew.call_10d)
  const put10d = asData(skew.put_10d)

  // Rolling client buffer for live IV velocity calculation
  const [ivHistory, setIvHistory] = useState<Array<{ time: number; iv: number; c25: number | null; p25: number | null; c10: number | null; p10: number | null }>>([])

  useEffect(() => {
    if (!isAvailable || atmIv === null) return
    const now = Date.now()
    setIvHistory((prev) => {
      const updated = [...prev, {
        time: now,
        iv: atmIv,
        c25: number(call25d.iv),
        p25: number(put25d.iv),
        c10: number(call10d.iv),
        p10: number(put10d.iv),
      }]
      return updated.filter((p) => now - p.time <= 20 * 60 * 1000)
    })
  }, [atmIv, isAvailable, call25d.iv, put25d.iv, call10d.iv, put10d.iv])

  const getDeltas = (key: 'iv' | 'c25' | 'p25' | 'c10' | 'p10'): { d5: string | null; d15: string | null; trend: 'RISING' | 'COOLING' | 'STABLE' } => {
    if (ivHistory.length < 2) return { d5: null, d15: null, trend: 'STABLE' }
    const now = Date.now()
    const pNow = ivHistory[ivHistory.length - 1][key]
    const p5 = ivHistory.find((p) => now - p.time >= 4.5 * 60 * 1000 && now - p.time <= 6 * 60 * 1000)?.[key]
    const p15 = ivHistory.find((p) => now - p.time >= 14 * 60 * 1000 && now - p.time <= 16.5 * 60 * 1000)?.[key]
    const trend: 'RISING' | 'COOLING' | 'STABLE' =
      pNow !== null && p5 != null ? (pNow > p5 + 0.1 ? 'RISING' : pNow < p5 - 0.1 ? 'COOLING' : 'STABLE') : 'STABLE'
    return {
      d5: pNow !== null && p5 != null ? pct(pNow - p5, true) : null,
      d15: pNow !== null && p15 != null ? pct(pNow - p15, true) : null,
      trend,
    }
  }

  const atmDeltas = getDeltas('iv')
  const c25Deltas = getDeltas('c25')
  const p25Deltas = getDeltas('p25')
  const c10Deltas = getDeltas('c10')
  const p10Deltas = getDeltas('p10')

  // Affordability / IV-RV Pricing Classification
  const isCheap = isAvailable && (volRegime === 'UNDERPRICED_PREMIUM' || (ivRvSpread !== null && ivRvSpread < -0.8))
  const isExpensive = isAvailable && (volRegime === 'OVERPRICED_PREMIUM' || (ivRvSpread !== null && ivRvSpread > 2.0))
  const isFair = isAvailable && !isCheap && !isExpensive

  // Convexity / Option Quality Values
  const ceRatio = number(atmCeQuality.quality_ratio)
  const peRatio = number(atmPeQuality.quality_ratio)

  // MOVE RESPONSE: FAST ⚡ / NORMAL / SLOW
  const ceQualityRating =
    atmCeQuality.rating === 'PRIME' || (ceRatio !== null && ceRatio >= 2.0)
      ? 'FAST ⚡'
      : atmCeQuality.rating === 'ACCEPTABLE' || (ceRatio !== null && ceRatio >= 1.0)
      ? 'NORMAL'
      : 'SLOW'
  const peQualityRating =
    atmPeQuality.rating === 'PRIME' || (peRatio !== null && peRatio >= 2.0)
      ? 'FAST ⚡'
      : atmPeQuality.rating === 'ACCEPTABLE' || (peRatio !== null && peRatio >= 1.0)
      ? 'NORMAL'
      : 'SLOW'

  // TIME DECAY: LOW / MEDIUM / HIGH
  const ceDecayRisk =
    number(atmCeQuality.theta_daily) !== null && Math.abs(number(atmCeQuality.theta_daily)!) > 20
      ? 'HIGH'
      : Math.abs(number(atmCeQuality.theta_daily) ?? 0) > 10
      ? 'MEDIUM'
      : 'LOW'
  const peDecayRisk =
    number(atmPeQuality.theta_daily) !== null && Math.abs(number(atmPeQuality.theta_daily)!) > 20
      ? 'HIGH'
      : Math.abs(number(atmPeQuality.theta_daily) ?? 0) > 10
      ? 'MEDIUM'
      : 'LOW'

  // Final quality badge: GOOD FOR BUYING vs WEAK FOR BUYING
  const ceResult = ceRatio !== null && ceRatio >= 1.5 ? 'GOOD FOR BUYING' : 'WEAK FOR BUYING'
  const peResult = peRatio !== null && peRatio >= 1.5 ? 'GOOD FOR BUYING' : 'WEAK FOR BUYING'

  // Directional Bias Derivation (Hedge Demand & Wings)
  const putWingBid =
    (skew25dSpread !== null && skew25dSpread > 0.6) ||
    (number(put25d.iv) !== null && number(call25d.iv) !== null && number(put25d.iv)! > number(call25d.iv)! + 0.6)
  const callWingBid =
    (skew25dSpread !== null && skew25dSpread < -0.5) ||
    (number(call25d.iv) !== null && number(put25d.iv) !== null && number(call25d.iv)! > number(put25d.iv)! + 0.6)

  // Structural Context (GEX / Zero Gamma)
  const isAbsorbingGex = netGexCr !== null && netGexCr >= 0
  const isAboveZeroGamma = netGexCr !== null ? netGexCr >= 0 : true

  // MAIN HERO + MAIN WHEEL: Exactly ONE trader-facing state combining (Premium condition, IV demand, Option quality, GEX)
  let heroMainState: 'PUT FRIENDLY' | 'CALL FRIENDLY' | 'SIDEWAYS / SELECTIVE' | 'NO OPTION EDGE' | 'AWAITING FEED' = 'SIDEWAYS / SELECTIVE'
  let heroStateTone = 'var(--amber)'
  let breatheClass = styles.breatheAmber
  let orbMotionClass = styles.orbSlowOrbit
  let wheelCenterTitle = 'SIDEWAYS'
  let wheelCenterSub = 'SELECTIVE'
  let secondaryContextLabel = 'Fair Premium / Selective'
  let secondaryContextTone = 'var(--amber)'
  let plainLanguageExplanation = 'Market balance me hai — dono taraf symmetrical demand hai.'
  let finalDecisionConclusion = 'Sideways / selective — balanced premium demand and no clear directional edge.'

  if (!isAvailable) {
    heroMainState = 'AWAITING FEED'
    heroStateTone = 'var(--text-lo)'
    breatheClass = styles.breatheStandby
    orbMotionClass = styles.orbSlowOrbit
    wheelCenterTitle = 'STANDBY'
    wheelCenterSub = 'OFFLINE'
    secondaryContextLabel = 'Awaiting Option Chain Feed'
    secondaryContextTone = 'var(--text-lo)'
    plainLanguageExplanation = 'Quantitative option surface will hydrate when live stream connects.'
    finalDecisionConclusion = 'Standby — awaiting live option stream connection.'
  } else if (isExpensive && ceResult === 'WEAK FOR BUYING' && peResult === 'WEAK FOR BUYING') {
    heroMainState = 'NO OPTION EDGE'
    heroStateTone = 'var(--algory-red)'
    breatheClass = styles.breatheRed
    orbMotionClass = styles.orbRiskPulse
    wheelCenterTitle = 'NO EDGE'
    wheelCenterSub = 'THETA RISK'
    secondaryContextLabel = 'Premium Expensive / Theta Risk'
    secondaryContextTone = 'var(--algory-red)'
    plainLanguageExplanation = 'Option premium mehnga hai, isliye move sahi hone par bhi decay risk zyada hai.'
    finalDecisionConclusion = 'No option edge — time decay risk dominating without directional momentum.'
  } else if (putWingBid) {
    heroMainState = 'PUT FRIENDLY'
    heroStateTone = 'var(--mint)'
    breatheClass = styles.breatheGreen
    orbMotionClass = styles.orbFastOrbit
    wheelCenterTitle = 'PUT'
    wheelCenterSub = 'FRIENDLY'
    secondaryContextLabel = isCheap
      ? 'Premium Cheap / Buyer Friendly'
      : isExpensive
      ? 'Premium Expensive / Theta Risk'
      : 'Fair Premium / Selective'
    secondaryContextTone = isCheap ? 'var(--mint)' : isExpensive ? 'var(--algory-red)' : 'var(--amber)'
    plainLanguageExplanation = isExpensive
      ? 'PUT protection demand increasing but premium cost is high'
      : 'Traders are paying more for downside protection'
    finalDecisionConclusion = isExpensive
      ? 'PUT protection demand increasing but premium cost is high — selective entry only.'
      : 'PUT buying favourable with fast move response and supportive downside demand.'
  } else if (callWingBid) {
    heroMainState = 'CALL FRIENDLY'
    heroStateTone = 'var(--mint)'
    breatheClass = styles.breatheGreen
    orbMotionClass = styles.orbFastOrbit
    wheelCenterTitle = 'CALL'
    wheelCenterSub = 'FRIENDLY'
    secondaryContextLabel = isCheap
      ? 'Premium Cheap / Buyer Friendly'
      : isExpensive
      ? 'Premium Expensive / Theta Risk'
      : 'Fair Premium / Selective'
    secondaryContextTone = isCheap ? 'var(--mint)' : isExpensive ? 'var(--algory-red)' : 'var(--amber)'
    plainLanguageExplanation = isExpensive
      ? 'Upside demand active but premium cost is high'
      : 'Upside participation and call demand increasing'
    finalDecisionConclusion = isExpensive
      ? 'CALL friendly, but premium expensive — selective entry only.'
      : 'CALL buying favourable with fast move response and manageable time decay.'
  } else {
    heroMainState = 'SIDEWAYS / SELECTIVE'
    heroStateTone = 'var(--amber)'
    breatheClass = styles.breatheAmber
    orbMotionClass = styles.orbSlowOrbit
    wheelCenterTitle = 'SIDEWAYS'
    wheelCenterSub = 'SELECTIVE'
    secondaryContextLabel = isCheap
      ? 'Premium Cheap / Buyer Friendly'
      : isExpensive
      ? 'Premium Expensive / Theta Risk'
      : 'Fair Premium / Selective'
    secondaryContextTone = isCheap ? 'var(--mint)' : isExpensive ? 'var(--algory-red)' : 'var(--amber)'
    plainLanguageExplanation = 'Market balance me hai — dono taraf symmetrical demand hai.'
    finalDecisionConclusion = 'Sideways / selective — balanced premium demand and no clear directional edge.'
  }

  // Directional Demand Driver Chip
  let demandDriverChip = 'BALANCED PREMIUM DEMAND'
  if (number(put25d.iv) !== null && number(call25d.iv) !== null) {
    if (number(put25d.iv)! > number(call25d.iv)! + 0.6) {
      demandDriverChip = `PUT PROTECTION DEMAND ${num(put25d.iv)}%`
    } else if (number(call25d.iv)! > number(put25d.iv)! + 0.6) {
      demandDriverChip = `CALL UPSIDE DEMAND ${num(call25d.iv)}%`
    }
  }

  // IV Direction Chip (Market Fear)
  const ivDirectionChip =
    atmDeltas.trend === 'RISING'
      ? 'FEAR INCREASING ↑'
      : atmDeltas.trend === 'COOLING'
      ? 'FEAR SUBSIDING ↓'
      : 'IV STABLE →'

  // Premium Condition Chip
  const premiumConditionChip = isCheap ? 'PREMIUM CHEAP' : isExpensive ? 'PREMIUM EXPENSIVE' : 'FAIR PREMIUM'

  // Summary Banner Label for IV Section
  const ivSectionSummary = putWingBid
    ? 'PUT PREMIUM DEMAND DOMINANT'
    : callWingBid
    ? 'CALL PREMIUM DEMAND DOMINANT'
    : 'BALANCED PREMIUM DEMAND'

  return (
    <section
      className={`${styles.card} ${styles.optionBuyerIntelligence} ${breatheClass}`}
      style={{
        gridColumn: '1 / -1',
        marginTop: '16px',
        padding: '24px 28px',
        background: 'var(--bg-surface)',
        border: '1px solid var(--line-dim)',
      }}
      aria-label="Citadel Oracle Option Intelligence Master Surface"
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      {/* ════════════════════════════════════════════════════════════════════════════════════
          TIER 1: OPTION BUYER ENVIRONMENT HERO (1-SECOND INSTANT COGNITION LAYER)
          ════════════════════════════════════════════════════════════════════════════════════ */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1.4fr auto',
          gap: '24px',
          paddingBottom: '16px',
          borderBottom: '1px solid var(--line-dim)',
          marginBottom: '16px',
          alignItems: 'center',
          position: 'relative',
          zIndex: 5,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
            <span
              className={styles.monoLabel}
              style={{ color: 'var(--cyan)', fontSize: '11px', fontWeight: 800, letterSpacing: '0.14em' }}
            >
              OPTION BUYER ENVIRONMENT // DECISION TRANSLATION
            </span>
            <div
              className={`${styles.pill} ${
                isAvailable
                  ? isCheap
                    ? styles.pillMint
                    : isExpensive
                    ? styles.pillRed
                    : styles.pillAmber
                  : styles.pillAmber
              }`}
            >
              {isAvailable ? '● LIVE 3.0s' : 'STANDBY'}
            </div>
          </div>

          {/* SINGLE MAIN HERO STATE (e.g. PUT FRIENDLY / CALL FRIENDLY / SIDEWAYS / NO OPTION EDGE) */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', marginTop: '6px' }}>
            <span
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: '26px',
                fontWeight: 800,
                color: heroStateTone,
                letterSpacing: '-0.01em',
                lineHeight: 1.1,
                textShadow:
                  heroStateTone === 'var(--mint)'
                    ? '0 0 20px rgba(0,255,157,0.45)'
                    : heroStateTone === 'var(--algory-red)'
                    ? '0 0 20px rgba(255,30,75,0.45)'
                    : 'none',
              }}
            >
              {heroMainState}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: secondaryContextTone, fontWeight: 700 }}>
              · {secondaryContextLabel}
            </span>
          </div>

          {/* LIVE DRIVERS CHIPS STRIP (Directional Driver, IV Direction, Premium Condition) */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', marginTop: '8px' }}>
            <div
              style={{
                background: 'rgba(0,240,255,0.08)',
                border: '1px solid rgba(0,240,255,0.3)',
                padding: '3px 9px',
                borderRadius: '6px',
                fontSize: '9px',
                fontFamily: 'var(--font-mono)',
                fontWeight: 800,
                color: 'var(--cyan)',
              }}
            >
              {demandDriverChip}
            </div>
            <div
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid var(--line-dim)',
                padding: '3px 9px',
                borderRadius: '6px',
                fontSize: '9px',
                fontFamily: 'var(--font-mono)',
                fontWeight: 700,
                color: 'var(--text-white)',
              }}
            >
              {ivDirectionChip}
            </div>
            <div
              style={{
                background: isCheap
                  ? 'rgba(0,255,157,0.08)'
                  : isExpensive
                  ? 'rgba(255,30,75,0.08)'
                  : 'rgba(255,184,0,0.08)',
                border: isCheap
                  ? '1px solid var(--mint)'
                  : isExpensive
                  ? '1px solid var(--algory-red)'
                  : '1px solid var(--amber)',
                padding: '3px 9px',
                borderRadius: '6px',
                fontSize: '9px',
                fontFamily: 'var(--font-mono)',
                fontWeight: 800,
                color: isCheap ? 'var(--mint)' : isExpensive ? 'var(--algory-red)' : 'var(--amber)',
              }}
            >
              {premiumConditionChip}
            </div>
            <div
              style={{
                background: isAbsorbingGex ? 'rgba(0,255,157,0.06)' : 'rgba(255,30,75,0.06)',
                border: isAbsorbingGex ? '1px solid rgba(0,255,157,0.25)' : '1px solid rgba(255,30,75,0.25)',
                padding: '3px 9px',
                borderRadius: '6px',
                fontSize: '9px',
                fontFamily: 'var(--font-mono)',
                fontWeight: 700,
                color: isAbsorbingGex ? 'var(--mint)' : 'var(--algory-red)',
              }}
            >
              {isAbsorbingGex ? '🟢 POSITIVE GEX EST.' : '🔴 NEGATIVE GEX EST.'}
            </div>
          </div>

          {/* PLAIN-LANGUAGE MEANING & FINAL DECISION CONCLUSION */}
          <div
            style={{
              marginTop: '10px',
              padding: '8px 14px',
              borderRadius: '6px',
              background: 'rgba(0,0,0,0.45)',
              border: `1px solid ${heroStateTone}35`,
              display: 'flex',
              flexDirection: 'column',
              gap: '3px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ color: heroStateTone, fontSize: '10px', fontWeight: 800 }}>▶</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-mid)' }}>
                {plainLanguageExplanation}
              </span>
            </div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                fontWeight: 800,
                color: 'var(--text-white)',
                letterSpacing: '0.02em',
                marginTop: '2px',
              }}
            >
              CONCLUSION: <span style={{ color: heroStateTone }}>{finalDecisionConclusion}</span>
            </div>
          </div>

          {/* Core Numbers Bar: IV, RV, VOL GAP */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', marginTop: '12px', maxWidth: '580px' }}>
            <div style={{ background: 'rgba(0,0,0,0.35)', padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line-dim)' }}>
              <span className={styles.monoLabel} style={{ fontSize: '7.5px' }}>ATM IMPLIED VOL (IV)</span>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '15px', fontWeight: 800, color: 'var(--text-white)', marginTop: '2px' }}>
                {atmIv != null ? `${num(atmIv)}%` : '—'}
              </div>
            </div>
            <div style={{ background: 'rgba(0,0,0,0.35)', padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line-dim)' }}>
              <span className={styles.monoLabel} style={{ fontSize: '7.5px' }}>REALIZED VOL (1M RV)</span>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '15px', fontWeight: 800, color: 'var(--cyan)', marginTop: '2px' }}>
                {intradayRv != null ? `${num(intradayRv)}%` : '—'}
              </div>
            </div>
            <div style={{ background: 'rgba(0,0,0,0.35)', padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line-dim)' }}>
              <span className={styles.monoLabel} style={{ fontSize: '7.5px' }}>VOL GAP (IV - RV)</span>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '15px', fontWeight: 800, color: secondaryContextTone, marginTop: '2px' }}>
                {pct(ivRvSpread, true)}
              </div>
            </div>
          </div>
        </div>

        {/* ARGUS PLASMA SYNTHESIS ORB (HERO ANCHOR MATCHING MAIN STATE) */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px' }}>
          <div className={styles.plasmaSphereContainer} style={{ width: '110px', height: '110px' }}>
            <div className={`${styles.orbitFlareRing1} ${orbMotionClass}`} style={{ borderColor: `${heroStateTone}60` }}>
              <div className={styles.orbitSatellite1} style={{ background: heroStateTone, boxShadow: `0 0 12px ${heroStateTone}` }} />
            </div>
            <div className={styles.orbitFlareRing2} />
            <div className={styles.liquidColorCore} style={{ width: '70px', height: '70px', boxShadow: `0 0 28px ${heroStateTone}45` }} />
            <div className={styles.coreGlassBadge} style={{ minWidth: '82px', padding: '4px 6px', textAlign: 'center' }}>
              <span style={{ color: heroStateTone, fontSize: '10.5px', fontWeight: 800, letterSpacing: '0.06em', lineHeight: 1.1 }}>
                {wheelCenterTitle}
              </span>
              <b style={{ color: 'var(--text-white)', fontSize: '7.5px', fontWeight: 700, marginTop: '2px', whiteSpace: 'nowrap' }}>
                {wheelCenterSub}
              </b>
            </div>
          </div>
          <span className={styles.monoLabel} style={{ fontSize: '7.5px', color: 'var(--text-lo)' }}>
            DECISION VECTOR
          </span>
        </div>
      </div>

      {/* ════════════════════════════════════════════════════════════════════════════════════
          TIER 2: IV VELOCITY & HEDGE DEMAND
          ════════════════════════════════════════════════════════════════════════════════════ */}
      <div style={{ marginBottom: '22px', position: 'relative', zIndex: 5 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '8px' }}>
          <div className={styles.intelligenceHeading} style={{ color: 'var(--cyan)', marginBottom: 0 }}>
            IV VELOCITY & HEDGE DEMAND <em>ATM & WING ACCELERATION</em>
          </div>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: putWingBid ? 'var(--algory-red)' : callWingBid ? 'var(--mint)' : 'var(--text-mid)', fontWeight: 700 }}>
            ● {ivSectionSummary}
          </span>
        </div>

        {/* 5 Velocity Grid Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '10px' }}>
          <MiniVelocityCard
            title="ATM IV (Market Fear)"
            currentVal={atmIv != null ? `${num(atmIv)}%` : '—'}
            delta5m={atmDeltas.d5}
            delta15m={atmDeltas.d15}
            tone={isExpensive || atmDeltas.trend === 'RISING' ? 'red' : 'mint'}
            stateLabel={
              atmDeltas.trend === 'RISING'
                ? 'FEAR RISING'
                : isExpensive
                ? 'EXPENSIVE'
                : isCheap
                ? 'CHEAP'
                : 'FEAR STABLE'
            }
            trend={atmDeltas.trend}
          />
          <MiniVelocityCard
            title="25Δ CALL IV (Upside Demand)"
            currentVal={call25d.iv != null ? `${num(call25d.iv)}%` : '—'}
            delta5m={c25Deltas.d5}
            delta15m={c25Deltas.d15}
            tone="cyan"
            stateLabel={c25Deltas.trend === 'RISING' ? 'DEMAND RISING' : 'CALL WING'}
            trend={c25Deltas.trend}
          />
          <MiniVelocityCard
            title="25Δ PUT IV (Downside Protection)"
            currentVal={put25d.iv != null ? `${num(put25d.iv)}%` : '—'}
            delta5m={p25Deltas.d5}
            delta15m={p25Deltas.d15}
            tone={p25Deltas.trend === 'RISING' || (skew25dSpread && skew25dSpread > 0.6) ? 'red' : 'amber'}
            stateLabel={
              p25Deltas.trend === 'RISING'
                ? 'PROTECTION BUYING'
                : skew25dSpread && skew25dSpread > 0.6
                ? 'PUT WING BID'
                : 'NORMAL'
            }
            trend={p25Deltas.trend}
          />
          <MiniVelocityCard
            title="10Δ CALL IV (Far Upside)"
            currentVal={call10d.iv != null ? `${num(call10d.iv)}%` : '—'}
            delta5m={c10Deltas.d5}
            delta15m={c10Deltas.d15}
            tone="cyan"
            stateLabel={c10Deltas.trend === 'RISING' ? 'SPECULATION RISING' : 'FAR CALL'}
            trend={c10Deltas.trend}
          />
          <MiniVelocityCard
            title="10Δ PUT IV (Tail Hedge)"
            currentVal={put10d.iv != null ? `${num(put10d.iv)}%` : '—'}
            delta5m={p10Deltas.d5}
            delta15m={p10Deltas.d15}
            tone={p10Deltas.trend === 'RISING' || (skew10dSpread && skew10dSpread > 0.6) ? 'red' : 'amber'}
            stateLabel={
              p10Deltas.trend === 'RISING'
                ? 'TAIL HEDGING'
                : skew10dSpread && skew10dSpread > 0.6
                ? 'TAIL HEDGE'
                : 'NORMAL'
            }
            trend={p10Deltas.trend}
          />
        </div>

        {/* Animated VOB Rail: IV vs HAR-RV Forecast */}
        {atmIv !== null && harRvForecast !== null && (
          <div style={{ marginTop: '12px' }}>
            <VobRail
              left={`ATM IV ${num(atmIv)}%`}
              leftValue={atmIv}
              right={`HAR-RV FORECAST ${num(harRvForecast)}%`}
              rightValue={harRvForecast}
              tone={isExpensive ? 'red' : 'mint'}
            />
          </div>
        )}
      </div>

      {/* ════════════════════════════════════════════════════════════════════════════════════
          TIER 3: CALL & PUT OPTION QUALITY (MOVE RESPONSE & TIME DECAY)
          ════════════════════════════════════════════════════════════════════════════════════ */}
      <div style={{ marginBottom: '22px', position: 'relative', zIndex: 5 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '8px' }}>
          <div className={styles.intelligenceHeading} style={{ color: 'var(--mint)', marginBottom: 0 }}>
            OPTION QUALITY <em>MOVE RESPONSE & TIME DECAY</em>
          </div>
          <span className={styles.monoLabel} style={{ fontSize: '8px', color: 'var(--text-lo)' }}>
            Move aane par premium react karne ki speed aur decay balance
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          {/* CALL OPTION QUALITY CARD */}
          <div
            style={{
              background: 'rgba(0, 255, 157, 0.02)',
              border: '1px solid var(--line-dim)',
              borderRadius: '10px',
              padding: '14px 16px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '8px' }}>
              <span className={styles.monoLabel} style={{ color: 'var(--mint)', fontWeight: 800, fontSize: '10px' }}>
                CALL OPTION QUALITY (ATM CE)
              </span>
              <div
                className={`${styles.pill} ${
                  ceResult === 'GOOD FOR BUYING' ? styles.pillMint : styles.pillAmber
                }`}
                style={{ fontSize: '7.5px', padding: '2px 8px' }}
              >
                ● {ceResult}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', margin: '10px 0' }}>
              <div style={{ background: 'rgba(0,0,0,0.3)', padding: '6px 8px', borderRadius: '6px' }}>
                <span className={styles.monoLabel} style={{ fontSize: '7px' }}>MOVE RESPONSE</span>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px',
                    fontWeight: 800,
                    color: ceQualityRating === 'FAST ⚡' ? 'var(--mint)' : 'var(--text-white)',
                    marginTop: '2px',
                  }}
                >
                  {ceQualityRating} {ceRatio != null ? `(${num(ceRatio)}x)` : ''}
                </div>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.3)', padding: '6px 8px', borderRadius: '6px' }}>
                <span className={styles.monoLabel} style={{ fontSize: '7px' }}>TIME DECAY</span>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px',
                    fontWeight: 800,
                    color: ceDecayRisk === 'HIGH' ? 'var(--algory-red)' : ceDecayRisk === 'MEDIUM' ? 'var(--amber)' : 'var(--mint)',
                    marginTop: '2px',
                  }}
                >
                  {ceDecayRisk}
                </div>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.3)', padding: '6px 8px', borderRadius: '6px' }}>
                <span className={styles.monoLabel} style={{ fontSize: '7px' }}>ENTRY COST</span>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 800, color: 'var(--text-white)', marginTop: '2px' }}>
                  {atmCeQuality.spread != null ? `₹${num(atmCeQuality.spread)} pts` : '—'}
                </div>
              </div>
            </div>

            <Row
              label="Daily Theta Decay"
              value={atmCeQuality.theta_daily != null ? `₹${num(atmCeQuality.theta_daily)}/day` : '—'}
              subtext={
                ceResult === 'GOOD FOR BUYING'
                  ? 'Premium fast react kar sakta hai aur decay manageable hai'
                  : 'Move response slow hai ya time decay pressure zyada hai'
              }
            />
          </div>

          {/* PUT OPTION QUALITY CARD */}
          <div
            style={{
              background: 'rgba(255, 30, 75, 0.02)',
              border: '1px solid var(--line-dim)',
              borderRadius: '10px',
              padding: '14px 16px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '8px' }}>
              <span className={styles.monoLabel} style={{ color: 'var(--algory-red)', fontWeight: 800, fontSize: '10px' }}>
                PUT OPTION QUALITY (ATM PE)
              </span>
              <div
                className={`${styles.pill} ${
                  peResult === 'GOOD FOR BUYING' ? styles.pillMint : styles.pillAmber
                }`}
                style={{ fontSize: '7.5px', padding: '2px 8px' }}
              >
                ● {peResult}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', margin: '10px 0' }}>
              <div style={{ background: 'rgba(0,0,0,0.3)', padding: '6px 8px', borderRadius: '6px' }}>
                <span className={styles.monoLabel} style={{ fontSize: '7px' }}>MOVE RESPONSE</span>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px',
                    fontWeight: 800,
                    color: peQualityRating === 'FAST ⚡' ? 'var(--mint)' : 'var(--text-white)',
                    marginTop: '2px',
                  }}
                >
                  {peQualityRating} {peRatio != null ? `(${num(peRatio)}x)` : ''}
                </div>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.3)', padding: '6px 8px', borderRadius: '6px' }}>
                <span className={styles.monoLabel} style={{ fontSize: '7px' }}>TIME DECAY</span>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px',
                    fontWeight: 800,
                    color: peDecayRisk === 'HIGH' ? 'var(--algory-red)' : peDecayRisk === 'MEDIUM' ? 'var(--amber)' : 'var(--mint)',
                    marginTop: '2px',
                  }}
                >
                  {peDecayRisk}
                </div>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.3)', padding: '6px 8px', borderRadius: '6px' }}>
                <span className={styles.monoLabel} style={{ fontSize: '7px' }}>ENTRY COST</span>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 800, color: 'var(--text-white)', marginTop: '2px' }}>
                  {atmPeQuality.spread != null ? `₹${num(atmPeQuality.spread)} pts` : '—'}
                </div>
              </div>
            </div>

            <Row
              label="Daily Theta Decay"
              value={atmPeQuality.theta_daily != null ? `₹${num(atmPeQuality.theta_daily)}/day` : '—'}
              subtext={
                peResult === 'GOOD FOR BUYING'
                  ? 'Premium fast react kar sakta hai aur decay manageable hai'
                  : 'Move response slow hai ya time decay pressure zyada hai'
              }
            />
          </div>
        </div>

        {/* Quality Comparison Rail */}
        {ceRatio !== null && peRatio !== null && (
          <div style={{ marginTop: '10px' }}>
            <VobRail
              left={`CALL RESPONSE ${num(ceRatio)}x`}
              leftValue={ceRatio}
              right={`PUT RESPONSE ${num(peRatio)}x`}
              rightValue={peRatio}
              tone={ceRatio >= peRatio ? 'mint' : 'red'}
              height={5}
            />
          </div>
        )}
      </div>

      {/* ════════════════════════════════════════════════════════════════════════════════════
          TIER 4: GEX + HEDGE DEMAND + ZERO GAMMA (STRUCTURAL CONTEXT STRIP)
          ════════════════════════════════════════════════════════════════════════════════════ */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1.2fr 1.2fr 0.9fr',
          gap: '16px',
          borderTop: '1px solid var(--line-dim)',
          paddingTop: '16px',
          position: 'relative',
          zIndex: 5,
        }}
      >
        {/* SUB-PANEL 1: HEURISTIC GEX REGIME */}
        <div style={{ background: 'rgba(0,0,0,0.2)', padding: '12px 14px', borderRadius: '8px', border: '1px solid var(--line-dim)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
            <div className={styles.intelligenceHeading} style={{ color: 'var(--text-mid)', fontSize: '9px', marginBottom: 0 }}>
              GEX REGIME · HEURISTIC <em>DEALER-GAMMA ESTIMATE</em>
            </div>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '7.5px',
                color: isAbsorbingGex ? 'var(--mint)' : 'var(--algory-red)',
                fontWeight: 700,
              }}
            >
              {isAbsorbingGex ? '🟢 POSITIVE EST.' : '🔴 NEGATIVE EST.'}
            </span>
          </div>

          <Row
            label="NET GEX"
            value={moneyCr(netGexCr, true)}
            primary={netGexCr !== null}
            tone={netGexCr === null ? undefined : netGexCr >= 0 ? 'var(--mint)' : 'var(--algory-red)'}
            subtext={
              isAbsorbingGex
                ? '🟢 ABSORBING: Moves may slow down and extension can get rejected'
                : '🔴 EXPANSION: Moves can extend faster'
            }
          />

          {callGexCr !== null && putGexCr !== null && (
            <div style={{ marginTop: '8px' }}>
              <VobRail
                left={`CALL SUPPORT ₹${callGexCr.toFixed(0)}Cr`}
                leftValue={callGexCr}
                right={`PUT PRESSURE ₹${Math.abs(putGexCr).toFixed(0)}Cr`}
                rightValue={Math.abs(putGexCr)}
                tone={isAbsorbingGex ? 'mint' : 'red'}
                height={5}
              />
            </div>
          )}

          <div style={{ marginTop: '6px', color: 'var(--text-lo)', fontFamily: 'var(--font-mono)', fontSize: '7.5px' }}>
            Estimated structure context only · OI UNIT PENDING CERTIFICATION
          </div>
        </div>

        {/* SUB-PANEL 2: HEDGE DEMAND (PROTECTION DEMAND GAP) */}
        <div style={{ background: 'rgba(0,0,0,0.2)', padding: '12px 14px', borderRadius: '8px', border: '1px solid var(--line-dim)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
            <div className={styles.intelligenceHeading} style={{ color: 'var(--text-mid)', fontSize: '9px', marginBottom: 0 }}>
              HEDGE DEMAND <em>WING HEDGING CONTEXT</em>
            </div>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '7.5px',
                color: putWingBid ? 'var(--algory-red)' : callWingBid ? 'var(--mint)' : 'var(--text-mid)',
                fontWeight: 700,
              }}
            >
              {putWingBid ? '🔴 Downside Protection' : callWingBid ? '🟢 Upside Demand' : '⚪ Balanced Demand'}
            </span>
          </div>

          <Row
            label="PUT vs CALL Demand Gap"
            value={pct(skew25dSpread, true)}
            primary={skew25dSpread !== null}
            tone={skew25dSpread === null ? undefined : skew25dSpread > 0.6 ? 'var(--amber)' : 'var(--text-mid)'}
            subtext={
              putWingBid
                ? '🔴 Traders are paying more for downside protection'
                : callWingBid
                ? '🟢 Upside demand increasing'
                : '⚪ Balanced demand across wings'
            }
          />

          {number(call25d.iv) !== null && number(put25d.iv) !== null && (
            <div style={{ marginTop: '4px' }}>
              <VobRail
                left={`CALL UPSIDE BET ${num(call25d.iv)}%`}
                leftValue={number(call25d.iv)!}
                right={`PUT PROTECTION ${num(put25d.iv)}%`}
                rightValue={number(put25d.iv)!}
                tone={skew25dSpread !== null && skew25dSpread > 0.6 ? 'amber' : 'cyan'}
                height={4}
              />
            </div>
          )}

          {number(call10d.iv) !== null && number(put10d.iv) !== null && (
            <div style={{ marginTop: '4px' }}>
              <VobRail
                left={`10Δ CE ${num(call10d.iv)}%`}
                leftValue={number(call10d.iv)!}
                right={`10Δ PE ${num(put10d.iv)}%`}
                rightValue={number(put10d.iv)!}
                tone="cyan"
                height={4}
              />
            </div>
          )}

          <div style={{ marginTop: '6px', color: 'var(--text-lo)', fontFamily: 'var(--font-mono)', fontSize: '7.5px' }}>
            Note: PUT protection means traders paying for downside insurance, not automatically bearish.
          </div>
        </div>

        {/* SUB-PANEL 3: HEURISTIC PER-STRIKE GEX CROSS */}
        <div style={{ background: 'rgba(0,0,0,0.2)', padding: '12px 14px', borderRadius: '8px', border: '1px solid var(--line-dim)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
            <div className={styles.intelligenceHeading} style={{ color: 'var(--text-mid)', fontSize: '9px', marginBottom: 0 }}>
              STRIKE GEX CROSS <em>HEURISTIC · NON-CANONICAL</em>
            </div>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '7.5px',
                color: isAboveZeroGamma ? 'var(--mint)' : 'var(--algory-red)',
                fontWeight: 700,
              }}
            >
              {isAboveZeroGamma ? '🟢 POSITIVE SIDE' : '🔴 NEGATIVE SIDE'}
            </span>
          </div>

          <Row
            label="LEVEL"
            value={zeroGammaStrike ? num(zeroGammaStrike) : '—'}
            primary={zeroGammaStrike !== null}
            tone="var(--amber)"
            subtext={isAboveZeroGamma ? 'Market holding above transition level' : 'Market below transition level'}
          />

          <Row
            label="DISTANCE"
            value={spotDistanceToZero !== null ? `${num(spotDistanceToZero)} pts` : '—'}
          />

          <div style={{ marginTop: '8px', color: 'var(--text-lo)', fontFamily: 'var(--font-mono)', fontSize: '7.5px' }}>
            {isAboveZeroGamma
              ? '🟢 Moves may slow down and reject extension'
              : '🔴 Moves can extend faster across strikes'}
          </div>
        </div>
      </div>
    </section>
  )
})
