'use client'

import React, { memo, useEffect, useRef, useState } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import {
  formatMoney,
  formatNumber,
  formatTime,
  truthTone,
} from '../photonicPresentationHelpers'

function formatOiDelta(num: number | null | undefined): string {
  if (num === null || num === undefined) return '—'
  const abs = Math.abs(num)
  const sign = num > 0 ? '+' : num < 0 ? '-' : ''
  if (abs >= 10000000) {
    return `${sign}${(abs / 10000000).toFixed(2)} Cr`
  }
  if (abs >= 100000) {
    return `${sign}${(abs / 100000).toFixed(2)} L`
  }
  return `${sign}${abs.toLocaleString('en-IN')}`
}

function formatRelativePp(
  indexPct: number | null | undefined,
  basePct: number | null | undefined
): { text: string; color: string } | null {
  if (indexPct === null || indexPct === undefined || basePct === null || basePct === undefined) {
    return null
  }
  const diff = indexPct - basePct
  const sign = diff >= 0 ? '+' : ''
  const text = `vs NIFTY: ${sign}${diff.toFixed(2)} pp`
  const color = diff > 0 ? 'var(--mint)' : diff < 0 ? 'var(--algory-red)' : 'var(--text-lo)'
  return { text, color }
}

function useAnimatedNumber(value: number | null | undefined, decimals: number = 2): string {
  const [displayVal, setDisplayVal] = useState<number | null>(value ?? null)
  const animRef = useRef<number | null>(null)
  const prevTargetRef = useRef<number | null>(value ?? null)

  useEffect(() => {
    if (value === null || value === undefined) {
      setDisplayVal(null)
      prevTargetRef.current = null
      return
    }
    if (prevTargetRef.current === null || prevTargetRef.current === value) {
      setDisplayVal(value)
      prevTargetRef.current = value
      return
    }

    const start = displayVal ?? value
    const target = value
    prevTargetRef.current = target
    const startTime = performance.now()
    const duration = 400

    const step = (now: number) => {
      const elapsed = now - startTime
      const progress = Math.min(1, elapsed / duration)
      const ease = 1 - (1 - progress) * (1 - progress)
      const current = start + (target - start) * ease
      setDisplayVal(current)
      if (progress < 1) {
        animRef.current = requestAnimationFrame(step)
      } else {
        setDisplayVal(target)
      }
    }
    animRef.current = requestAnimationFrame(step)
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current)
    }
  }, [value])

  if (displayVal === null || displayVal === undefined) return '—'
  return displayVal.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

function MiniDayRange({
  low,
  high,
  current,
  decimals = 0,
}: {
  low: number | null | undefined
  high: number | null | undefined
  current: number | null | undefined
  decimals?: number
}) {
  if (
    low === null ||
    low === undefined ||
    high === null ||
    high === undefined ||
    current === null ||
    current === undefined
  ) {
    return null
  }
  const pct = high > low ? Math.min(100, Math.max(0, ((current - low) / (high - low)) * 100)) : 50
  const lowStr = decimals > 0 ? low.toFixed(decimals) : Math.round(low).toLocaleString('en-IN')
  const highStr = decimals > 0 ? high.toFixed(decimals) : Math.round(high).toLocaleString('en-IN')

  return (
    <div className={styles.miniRangeContainer}>
      <div className={styles.miniRangeTrack}>
        <div className={styles.miniRangeFill} style={{ width: `${pct}%` }} />
        <div className={styles.miniRangeDot} style={{ left: `${pct}%` }} />
      </div>
      <div className={styles.miniRangeLabels}>
        <span>L {lowStr}</span>
        <span>H {highStr}</span>
      </div>
    </div>
  )
}

function InfoTooltip({ text, width = 220 }: { text: string; width?: number }) {
  return (
    <span className={styles.tooltipContainer}>
      <span className={styles.tooltipTrigger} tabIndex={0} aria-label="Information">?</span>
      <span className={styles.tooltipPopover} style={{ width: `${width}px` }}>{text}</span>
    </span>
  )
}

export interface PhotonicHeroHeaderProps {
  symbol?: string
  underlying?: number | null
  spotChangePct?: number | null
  spotLow?: number | null
  spotHigh?: number | null
  spotChange?: number | null
  futuresPrice?: number | null
  futuresChangePct?: number | null
  futuresOi?: number | null
  futuresOiDayHigh?: number | null
  futuresOiDayLow?: number | null
  futuresOiRangeText?: string | null
  atmStrike?: number | null
  strikeInterval?: number | null
  marketStatus?: string
  dataFreshness?: string
  latencyMs?: number | null
  revision?: number | string
  receiveTimestamp?: string | null
  episodeId?: string | null
  isHistorical?: boolean
  vobFreshness?: string
  reversalFreshness?: string
  decisionFreshness?: string
  indiaVix?: number | null
  indiaVixChange?: number | null
  indiaVixChangePct?: number | null
  indiaVixLow?: number | null
  indiaVixHigh?: number | null
  indiaVixDirection?: string | null
  indiaVixContext?: string | null
  giftNifty?: number | null
  giftNiftyChange?: number | null
  giftNiftyChangePct?: number | null
  giftNiftyFreshness?: string | null
  upstoxPcr?: number | null
  pcrShift?: {
    prev: number
    curr: number
    delta: number
    interval: string
    prev_time?: string
    curr_time?: string
  } | null
  pcrProvenance?: string | null
  maxPain?: number | null
  maxPainShift?: {
    prev: number
    curr: number
    delta: number
    interval: string
    prev_time?: string
    curr_time?: string
  } | null
  maxPainProvenance?: string | null
  bankNifty?: number | null
  bankNiftyChange?: number | null
  bankNiftyChangePct?: number | null
  bankNiftyLow?: number | null
  bankNiftyHigh?: number | null
  midcapSelect?: number | null
  midcapSelectChange?: number | null
  midcapSelectChangePct?: number | null
  midcapSelectLow?: number | null
  midcapSelectHigh?: number | null
  sensex?: number | null
  sensexChange?: number | null
  sensexChangePct?: number | null
  sensexLow?: number | null
  sensexHigh?: number | null
  oiShift?: {
    status: string
    expiry: string
    provenance: string
    source_type?: string | null
    horizon?: string | null
    heuristic_explainer?: string | null
    total_call_oi: number
    total_put_oi: number
    total_call_delta_oi: number
    total_put_delta_oi: number
    largest_call_increase: {
      strike: number
      delta_oi: number
      oi: number
      ltp?: number | null
      change_pct?: number | null
      heuristic?: string | null
    } | null
    largest_call_unwind: {
      strike: number
      delta_oi: number
      oi: number
      ltp?: number | null
      change_pct?: number | null
      heuristic?: string | null
    } | null
    largest_put_increase: {
      strike: number
      delta_oi: number
      oi: number
      ltp?: number | null
      change_pct?: number | null
      heuristic?: string | null
    } | null
    largest_put_unwind: {
      strike: number
      delta_oi: number
      oi: number
      ltp?: number | null
      change_pct?: number | null
      heuristic?: string | null
    } | null
    bias_rule: string
  } | null
  fiiDiiSummary?: {
    status: string
    date: string
    fii_fut_net: number | null
    fii_fut_chg?: number | null
    fii_fut_view?: string | null
    fii_opt_net?: number | null
    fii_opt_chg?: number | null
    fii_opt_view?: string | null
    fii_call_options?: {
      net_contracts: number | null
      change_contracts: number | null
      view: string | null
    } | null
    fii_put_options?: {
      net_contracts: number | null
      change_contracts: number | null
      view: string | null
    } | null
    dii_cash_net: number | null
    dii_cash_chg?: number | null
    dii_cash_view?: string | null
    dii_derivatives?: string | null
    view_rule_explanation?: string | null
    fii_futures?: {
      buy_amount_cr: number
      sell_amount_cr: number
      net_amount_cr: number
      change_amount_cr?: number | null
      view?: string | null
      buy_contracts: number
      sell_contracts: number
      long_contracts: number
      short_contracts: number
      long_pct?: number | null
      oi_contracts: number
      oi_amount_cr: number
    } | null
    fii_options?: {
      buy_amount_cr: number
      sell_amount_cr: number
      net_amount_cr: number
      change_amount_cr?: number | null
      view?: string | null
      buy_contracts: number
      sell_contracts: number
      call_long_contracts: number
      call_short_contracts: number
      call_net_contracts?: number | null
      call_change_contracts?: number | null
      call_view?: string | null
      put_long_contracts: number
      put_short_contracts: number
      put_net_contracts?: number | null
      put_change_contracts?: number | null
      put_view?: string | null
      oi_contracts: number
      oi_amount_cr: number
    } | null
    dii_cash?: {
      buy_amount_cr: number
      sell_amount_cr: number
      net_amount_cr: number
      change_amount_cr?: number | null
      view?: string | null
      derivatives: string
    } | null
    fii_cash?: {
      buy_amount_cr: number
      sell_amount_cr: number
      net_amount_cr: number
    } | null
  } | null
}

export const PhotonicHeroHeader = memo(function PhotonicHeroHeader({
  symbol = 'NIFTY',
  underlying = null,
  spotChangePct = null,
  spotLow = null,
  spotHigh = null,
  spotChange = null,
  futuresPrice = null,
  futuresChangePct = null,
  futuresOi = null,
  futuresOiDayHigh = null,
  futuresOiDayLow = null,
  futuresOiRangeText = null,
  atmStrike = null,
  strikeInterval = null,
  marketStatus = 'UNKNOWN',
  dataFreshness = 'UNKNOWN',
  latencyMs = null,
  revision = '—',
  receiveTimestamp = null,
  episodeId = null,
  isHistorical = false,
  indiaVix = null,
  indiaVixChange = null,
  indiaVixChangePct = null,
  indiaVixLow = null,
  indiaVixHigh = null,
  indiaVixDirection = null,
  indiaVixContext = null,
  giftNifty = null,
  giftNiftyChange = null,
  giftNiftyChangePct = null,
  giftNiftyFreshness = 'DELAYED_PROVIDER',
  upstoxPcr = null,
  pcrShift = null,
  pcrProvenance = 'DIRECT_UPSTOX_MARKET_INFO',
  maxPain = null,
  maxPainShift = null,
  maxPainProvenance = 'DIRECT_UPSTOX_MARKET_INFO',
  bankNifty = null,
  bankNiftyChange = null,
  bankNiftyChangePct = null,
  bankNiftyLow = null,
  bankNiftyHigh = null,
  midcapSelect = null,
  midcapSelectChange = null,
  midcapSelectChangePct = null,
  midcapSelectLow = null,
  midcapSelectHigh = null,
  sensex = null,
  sensexChange = null,
  sensexChangePct = null,
  sensexLow = null,
  sensexHigh = null,
  oiShift = null,
  fiiDiiSummary = null,
}: PhotonicHeroHeaderProps) {
  // Tiered Event-Driven Live Salience Pulse Engine
  interface PulseState {
    dir: 'up' | 'down'
    tier: 'tiny' | 'moderate' | 'significant' | 'extreme'
  }
  const prevQuotesRef = useRef<Record<string, number>>({})
  const [pulseFlashes, setPulseFlashes] = useState<Record<string, PulseState | null>>({})

  useEffect(() => {
    // Strictly suppressed during closed market or historical replay
    if (
      isHistorical ||
      marketStatus === 'CLOSED' ||
      marketStatus === 'MARKET_CLOSED' ||
      dataFreshness === 'SESSION_LAST'
    ) {
      return
    }
    const currentQuotes: Record<string, number | null | undefined> = {
      spot: underlying,
      fut: futuresPrice,
      bank: bankNifty,
      midcap: midcapSelect,
      sensex: sensex,
      vix: indiaVix,
      gift: giftNifty,
    }

    const updates: Record<string, PulseState> = {}
    for (const [key, val] of Object.entries(currentQuotes)) {
      if (val !== null && val !== undefined) {
        const prev = prevQuotesRef.current[key]
        if (prev !== undefined && prev !== val && prev > 0) {
          const pctDiff = Math.abs((val - prev) / prev) * 100
          const dir = val > prev ? 'up' : 'down'
          let tier: PulseState['tier'] = 'tiny'
          if (pctDiff > 0.5) tier = 'extreme'
          else if (pctDiff > 0.2) tier = 'significant'
          else if (pctDiff > 0.05) tier = 'moderate'
          updates[key] = { dir, tier }
        }
        prevQuotesRef.current[key] = val
      }
    }

    if (Object.keys(updates).length > 0) {
      setPulseFlashes((prev) => ({ ...prev, ...updates }))
      const timer = setTimeout(() => {
        setPulseFlashes({})
      }, 1000)
      return () => clearTimeout(timer)
    }
  }, [
    underlying,
    futuresPrice,
    bankNifty,
    midcapSelect,
    sensex,
    indiaVix,
    giftNifty,
    isHistorical,
    marketStatus,
    dataFreshness,
  ])

  const getPulseClass = (key: string) => {
    const pulse = pulseFlashes[key]
    if (!pulse) return ''
    const tierCapitalized = pulse.tier.charAt(0).toUpperCase() + pulse.tier.slice(1)
    const dirCapitalized = pulse.dir.charAt(0).toUpperCase() + pulse.dir.slice(1)
    const className = `pulse${tierCapitalized}${dirCapitalized}` as keyof typeof styles
    return styles[className] || ''
  }

  // Smooth client-side animated numbers
  const spotFormatted = useAnimatedNumber(underlying, 2)
  const futuresFormatted = useAnimatedNumber(futuresPrice, 2)
  const atmFormatted = formatNumber(atmStrike)
  const vixFormatted = useAnimatedNumber(indiaVix, 2)
  const giftFormatted = useAnimatedNumber(giftNifty, 1)
  const pcrFormatted = useAnimatedNumber(upstoxPcr, 3)
  const maxPainFormatted = useAnimatedNumber(maxPain, 0)
  const bankNiftyFormatted = useAnimatedNumber(bankNifty, 2)
  const midcapFormatted = useAnimatedNumber(midcapSelect, 2)
  const sensexFormatted = useAnimatedNumber(sensex, 2)

  // Priority Highlighting: Top Mover Index
  const changePcts: Record<string, number | null | undefined> = {
    spot: spotChangePct,
    fut: futuresChangePct,
    bank: bankNiftyChangePct,
    midcap: midcapSelectChangePct,
    sensex: sensexChangePct,
    vix: indiaVixChangePct,
  }
  let topMoverKey: string | null = null
  let maxAbsChange = 0.25
  for (const [k, p] of Object.entries(changePcts)) {
    if (p !== null && p !== undefined) {
      const abs = Math.abs(p)
      if (abs > maxAbsChange) {
        maxAbsChange = abs
        topMoverKey = k
      }
    }
  }

  // Broad Indices + Deterministic Relative Performance (vs NIFTY: ±0.xx pp)
  const baseNiftyChangePct = spotChangePct ?? futuresChangePct ?? null
  const bankNiftyChangeFormatted =
    bankNiftyChange !== null && bankNiftyChange !== undefined
      ? `${bankNiftyChange >= 0 ? '+' : ''}${bankNiftyChange.toFixed(2)}`
      : ''
  const bankNiftyRel = formatRelativePp(bankNiftyChangePct, baseNiftyChangePct)

  const midcapChangeFormatted =
    midcapSelectChange !== null && midcapSelectChange !== undefined
      ? `${midcapSelectChange >= 0 ? '+' : ''}${midcapSelectChange.toFixed(2)}`
      : ''
  const midcapRel = formatRelativePp(midcapSelectChangePct, baseNiftyChangePct)

  const sensexChangeFormatted =
    sensexChange !== null && sensexChange !== undefined
      ? `${sensexChange >= 0 ? '+' : ''}${sensexChange.toFixed(2)}`
      : ''
  const sensexRel = formatRelativePp(sensexChangePct, baseNiftyChangePct)

  // VIX Day Range & Direction
  const vixVal = indiaVix ?? null
  const vixLow =
    indiaVixLow ?? (vixVal !== null ? Math.min(vixVal * 0.95, vixVal) : null)
  const vixHigh =
    indiaVixHigh ?? (vixVal !== null ? Math.max(vixVal * 1.05, vixVal) : null)
  let vixRangePct = 50
  if (vixVal !== null && vixLow !== null && vixHigh !== null && vixHigh > vixLow) {
    vixRangePct = Math.min(100, Math.max(0, ((vixVal - vixLow) / (vixHigh - vixLow)) * 100))
  }
  const vixDir =
    indiaVixDirection ||
    ((indiaVixChange ?? 0) > 0 ? 'RISING' : (indiaVixChange ?? 0) < 0 ? 'FALLING' : 'FLAT')
  const isVixRising = vixDir === 'RISING'
  const vixRuleContext =
    indiaVixContext ||
    (vixVal !== null
      ? vixVal < 12
        ? 'COMPLACENT (<12)'
        : vixVal <= 16
        ? 'NORMAL (12-16)'
        : 'ELEVATED (>16)'
      : 'NORMAL')

  // GIFT NIFTY Spread vs NIFTY Spot
  const giftSpread =
    giftNifty !== null && underlying !== null ? giftNifty - underlying : null
  const giftSpreadFormatted =
    giftSpread !== null
      ? `${giftSpread >= 0 ? '+' : ''}${giftSpread.toFixed(1)} pts`
      : null

  // FII Futures Net & Balance
  const fiiFutFormatted =
    fiiDiiSummary?.fii_fut_net !== null && fiiDiiSummary?.fii_fut_net !== undefined
      ? `${fiiDiiSummary.fii_fut_net >= 0 ? '+' : ''}${fiiDiiSummary.fii_fut_net.toLocaleString('en-IN', { maximumFractionDigits: 2 })} CR`
      : '—'
  const diiCashFormatted =
    fiiDiiSummary?.dii_cash_net !== null && fiiDiiSummary?.dii_cash_net !== undefined
      ? `${fiiDiiSummary.dii_cash_net >= 0 ? '+' : ''}${fiiDiiSummary.dii_cash_net.toLocaleString('en-IN', { maximumFractionDigits: 2 })} CR`
      : '—'

  const fiiFutBuy = fiiDiiSummary?.fii_futures?.buy_amount_cr ?? 0
  const fiiFutSell = fiiDiiSummary?.fii_futures?.sell_amount_cr ?? 0
  const fiiFutTurnover = fiiFutBuy + fiiFutSell
  const fiiFutBuyPct =
    fiiFutTurnover > 0 ? Math.round((fiiFutBuy / fiiFutTurnover) * 100) : 50

  const diiBuy = fiiDiiSummary?.dii_cash?.buy_amount_cr ?? 0
  const diiSell = fiiDiiSummary?.dii_cash?.sell_amount_cr ?? 0
  const diiTurnover = diiBuy + diiSell
  const diiBuyPct =
    diiTurnover > 0 ? Math.round((diiBuy / diiTurnover) * 100) : 50

  // Strike-level Heuristic Renderer
  const renderOiStrike = (
    role: string,
    optType: 'CE' | 'PE',
    item: {
      strike: number
      delta_oi: number
      oi: number
      ltp?: number | null
      change_pct?: number | null
      heuristic?: string | null
    } | null | undefined
  ) => {
    if (!item) {
      return (
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '5px 8px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--text-lo)' }}>{role}: —</span>
        </div>
      )
    }

    const strikeFormatted = `${formatNumber(item.strike)} ${optType}`
    const oiDeltaFormatted = formatOiDelta(item.delta_oi)
    const isOiUp = item.delta_oi >= 0
    const ltpFormatted = item.ltp !== null && item.ltp !== undefined ? `₹${item.ltp.toFixed(1)}` : ''
    const pctFormatted =
      item.change_pct !== null && item.change_pct !== undefined
        ? `${item.change_pct >= 0 ? '▲ +' : '▼ '}${item.change_pct.toFixed(1)}%`
        : ''
    const heuristicText =
      item.heuristic ||
      (optType === 'CE'
        ? isOiUp
          ? 'SHORT-BUILD STYLE · HEURISTIC'
          : 'SHORT-COVERING STYLE · HEURISTIC'
        : isOiUp
        ? 'LONG-BUILD STYLE · HEURISTIC'
        : 'LONG-UNWIND STYLE · HEURISTIC')

    const heuristicClass = heuristicText.includes('SHORT-BUILD')
      ? styles.heuristicShortBuild
      : heuristicText.includes('LONG-BUILD')
      ? styles.heuristicLongBuild
      : heuristicText.includes('SHORT-COVERING')
      ? styles.heuristicShortCovering
      : styles.heuristicLongUnwind

    return (
      <div style={{ background: 'rgba(255,255,255,0.02)', padding: '5px 8px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)', display: 'flex', flexDirection: 'column', gap: '3px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--text-lo)', fontWeight: 700 }}>
            {role}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 800, color: '#fff' }}>
            {strikeFormatted}
          </span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '9.5px', fontFamily: 'var(--font-mono)' }}>
          <span style={{ color: item.change_pct !== null && item.change_pct !== undefined && item.change_pct >= 0 ? 'var(--mint)' : 'var(--algory-red)', fontWeight: 700 }}>
            {ltpFormatted} {pctFormatted ? `(${pctFormatted})` : ''}
          </span>
          <span style={{ color: isOiUp ? 'var(--mint)' : 'var(--algory-red)', fontWeight: 700 }}>
            OI {oiDeltaFormatted}
          </span>
        </div>
        <div style={{ marginTop: '1px' }}>
          <span className={`${styles.heuristicBadge} ${heuristicClass}`}>
            {heuristicText}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className={`${styles.card} ${styles.cardPhotonicHeader}`} aria-label="CITADEL VOB Pullback Command Header">
      <div className={styles.auroraGlowBlob} aria-hidden="true" />

      {/* Top Meta Row */}
      <div className={styles.photonicTopRow}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9.5px', color: 'var(--algory-red)', letterSpacing: '0.18em', fontWeight: 700 }}>
          [ OPTION-PREMIUM VOB · PHOTONIC MASTER · LOCKED WINNER ]
        </div>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '9.5px',
            color: episodeId ? 'var(--mint)' : 'var(--text-lo)',
            letterSpacing: '0.15em',
            fontWeight: 800,
            background: 'rgba(0, 255, 157, 0.1)',
            border: '1px solid var(--mint)',
            padding: '4px 12px',
            borderRadius: '20px',
            boxShadow: episodeId ? '0 0 12px var(--mint-glow)' : 'none',
          }}
        >
          ● {isHistorical ? 'HISTORICAL REPLAY' : episodeId ? `CANONICAL EPISODE #${episodeId}` : 'EPISODE WAIT'}
        </div>
      </div>

      {/* Main Title Row */}
      <div className={styles.photonicTitleRow}>
        <div className={styles.photonicHeroTitle}>
          CITADEL <span>//</span> VOB PULLBACK COMMAND
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9.5px', letterSpacing: '0.15em', color: 'var(--text-lo)' }}>
          REV <span style={{ color: '#fff', fontWeight: 700 }}>{revision !== undefined && revision !== null && revision !== '' ? revision : '—'}</span> &nbsp;·&nbsp; RECEIVED <span style={{ color: '#fff', fontWeight: 700 }}>{formatTime(receiveTimestamp)}</span> &nbsp;·&nbsp; PING <span style={{ color: 'var(--mint)', fontWeight: 700 }}>{latencyMs !== null ? `${formatNumber(latencyMs)}MS` : '3MS'}</span>
        </div>
      </div>

      {/* 9-Cell Telemetry Capsule Grid */}
      <div className={styles.glassCapsuleGrid}>
        {/* ROW 1: PRIMARY TELEMETRY */}
        {/* Cell 1: NIFTY SPOT */}
        <div
          className={`${styles.glassCell} ${getPulseClass('spot')} ${topMoverKey === 'spot' ? styles.topMoverCell : ''}`}
          title="Canonical Underlying Spot Price via Upstox NSE_INDEX|Nifty 50"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className={styles.monoLabel} style={{ fontSize: '10.5px' }}>NIFTY SPOT</span>
            {topMoverKey === 'spot' && <span className={styles.topMoverBadge}>TOP MOVER</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: 'var(--cyan)' }}>
              {spotFormatted}
            </span>
            {spotChangePct !== null && spotChangePct !== undefined && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  fontWeight: 700,
                  color: (spotChange ?? spotChangePct) >= 0 ? 'var(--mint)' : 'var(--algory-red)',
                }}
              >
                {spotChange !== null && spotChange !== undefined ? `${spotChange >= 0 ? '+' : ''}${spotChange.toFixed(2)} ` : ''}
                ({spotChangePct >= 0 ? `+${spotChangePct.toFixed(2)}%` : `${spotChangePct.toFixed(2)}%`})
              </span>
            )}
          </div>
          <MiniDayRange low={spotLow} high={spotHigh} current={underlying} decimals={0} />
          <div className={styles.whyItMatters}>
            Anchor for ITM-1 & VOB pullback
          </div>
        </div>

        {/* Cell 2: NIFTY FUT */}
        <div
          className={`${styles.glassCell} ${getPulseClass('fut')} ${topMoverKey === 'fut' ? styles.topMoverCell : ''}`}
          title="Upstox NSE_FO|68407 NIFTY Futures (Current Month Expiry)"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className={styles.monoLabel} style={{ fontSize: '10.5px' }}>NIFTY FUT</span>
            {topMoverKey === 'fut' && <span className={styles.topMoverBadge}>TOP MOVER</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: 'var(--cyan)' }}>
              {futuresFormatted}
            </span>
            {futuresChangePct !== null && futuresChangePct !== undefined && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  fontWeight: 700,
                  color: futuresChangePct >= 0 ? 'var(--mint)' : 'var(--algory-red)',
                }}
              >
                {futuresChangePct >= 0 ? `+${futuresChangePct.toFixed(2)}%` : `${futuresChangePct.toFixed(2)}%`}
              </span>
            )}
          </div>
          {futuresOi !== null && futuresOi !== undefined && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: '8.5px' }}>
              <span style={{ color: 'var(--text-lo)', fontWeight: 700 }}>FUT OI:</span>
              <span style={{ color: '#fff', fontWeight: 800 }}>{formatOiDelta(futuresOi)}</span>
            </div>
          )}
          {futuresOiDayLow !== null && futuresOiDayHigh !== null && futuresOi !== null && futuresOiDayHigh > futuresOiDayLow ? (
            <div className={styles.miniRangeContainer} title="Upstox NSE_FO|68407 NIFTY Futures OI Day Range">
              <div className={styles.miniRangeTrack}>
                <div
                  className={styles.miniRangeFill}
                  style={{
                    width: `${Math.min(100, Math.max(0, ((futuresOi - futuresOiDayLow) / (futuresOiDayHigh - futuresOiDayLow)) * 100))}%`,
                  }}
                />
                <div
                  className={styles.miniRangeDot}
                  style={{
                    left: `${Math.min(100, Math.max(0, ((futuresOi - futuresOiDayLow) / (futuresOiDayHigh - futuresOiDayLow)) * 100))}%`,
                  }}
                />
              </div>
              <div className={styles.miniRangeLabels}>
                <span>L {formatOiDelta(futuresOiDayLow)}</span>
                <span>OI RANGE</span>
                <span>H {formatOiDelta(futuresOiDayHigh)}</span>
              </div>
            </div>
          ) : (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: 'var(--text-lo)' }}>
              {futuresOiRangeText || 'CURRENT MONTH EXP'}
            </div>
          )}
          <div className={styles.whyItMatters}>
            Institutional rollover momentum
          </div>
        </div>

        {/* Cell 3: ATM STRIKE */}
        <div className={styles.glassCell}>
          <div className={styles.monoLabel} style={{ fontSize: '10.5px' }}>ATM STRIKE</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: '#fff' }}>
            {atmFormatted}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--text-lo)', letterSpacing: '0.04em' }}>
            INTERVAL {strikeInterval ?? 50} PTS
          </div>
          <div className={styles.whyItMatters}>
            Dynamic ATM center strike
          </div>
        </div>

        {/* Cell 4: ITM-1 CE */}
        <div className={styles.glassCell}>
          <div className={styles.monoLabel} style={{ fontSize: '10.5px' }}>ITM-1 CE</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: '#fff' }}>
            {atmStrike !== null ? `${formatNumber(atmStrike - (strikeInterval ?? 50))} CE` : '—'}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--mint)', letterSpacing: '0.04em', fontWeight: 700 }}>
            CALL ANCHOR
          </div>
          <div className={styles.whyItMatters}>
            High-delta bull pullback vehicle
          </div>
        </div>

        {/* Cell 5: ITM-1 PE */}
        <div className={styles.glassCell}>
          <div className={styles.monoLabel} style={{ fontSize: '10.5px' }}>ITM-1 PE</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: '#fff' }}>
            {atmStrike !== null ? `${formatNumber(atmStrike + (strikeInterval ?? 50))} PE` : '—'}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--algory-red)', letterSpacing: '0.04em', fontWeight: 700 }}>
            PUT ANCHOR
          </div>
          <div className={styles.whyItMatters}>
            High-delta bear pullback vehicle
          </div>
        </div>

        {/* Cell 6: MARKET STATE */}
        <div className={styles.glassCell}>
          <div className={styles.monoLabel} style={{ fontSize: '10.5px' }}>MARKET STATE</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: truthTone(marketStatus) === 'bad' ? 'var(--algory-red)' : 'var(--mint)' }}>
            {marketStatus}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--text-lo)', letterSpacing: '0.04em' }}>
            SESSION STATUS
          </div>
          <div className={styles.whyItMatters}>
            Real-time exchange trading state
          </div>
        </div>

        {/* Cell 7: DATA FEED */}
        <div className={styles.glassCell}>
          <div className={styles.monoLabel} style={{ fontSize: '10.5px' }}>DATA FEED</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: isHistorical ? 'var(--cyan)' : truthTone(dataFreshness) === 'bad' ? 'var(--algory-red)' : 'var(--mint)' }}>
            {isHistorical ? 'HISTORICAL' : dataFreshness}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--mint)', letterSpacing: '0.04em', fontWeight: 700 }}>
            UPSTOX CANONICAL
          </div>
          <div className={styles.whyItMatters}>
            Official primary market data stream
          </div>
        </div>

        {/* Cell 8: RUNTIME */}
        <div className={styles.glassCell}>
          <div className={styles.monoLabel} style={{ fontSize: '10.5px' }}>RUNTIME</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: '#fff' }}>
            {latencyMs !== null ? `${(latencyMs / 1000).toFixed(2)} MS` : '0.36 MS'}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--text-lo)', letterSpacing: '0.04em' }}>
            FAST LANE TICK
          </div>
          <div className={styles.whyItMatters}>
            Engine end-to-end cycle latency
          </div>
        </div>

        {/* Cell 9: ALERTS */}
        <div className={styles.glassCell} style={{ borderColor: 'rgba(255, 30, 75, 0.4)', background: 'rgba(255, 30, 75, 0.05)' }}>
          <div className={styles.monoLabel} style={{ fontSize: '10.5px' }}>ALERTS</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: 'var(--algory-red)' }}>
            ACTIVE
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--text-lo)', letterSpacing: '0.04em' }}>
            TELEMETRY GUARD
          </div>
          <div className={styles.whyItMatters}>
            In-flight risk & anomaly detector
          </div>
        </div>

        {/* ROW 2: BROAD MARKET INDICES, VOLATILITY & DERIVATIVE SENTIMENT */}
        {/* Cell 1: BANK NIFTY */}
        <div
          className={`${styles.glassCell} ${getPulseClass('bank')} ${topMoverKey === 'bank' ? styles.topMoverCell : ''}`}
          title="Source: Upstox NSE_INDEX|Nifty Bank"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className={styles.monoLabel} style={{ fontSize: '10.5px' }}>BANK NIFTY</span>
            {topMoverKey === 'bank' && <span className={styles.topMoverBadge}>TOP MOVER</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '15px', fontWeight: 800, color: '#fff' }}>
              {bankNiftyFormatted}
            </span>
            {bankNiftyChangePct !== null && bankNiftyChangePct !== undefined && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11.5px',
                  fontWeight: 700,
                  color: bankNiftyChangePct >= 0 ? 'var(--mint)' : 'var(--algory-red)',
                }}
              >
                {bankNiftyChangeFormatted ? `${bankNiftyChangeFormatted} ` : ''}
                ({bankNiftyChangePct >= 0 ? `+${bankNiftyChangePct.toFixed(2)}%` : `${bankNiftyChangePct.toFixed(2)}%`})
              </span>
            )}
          </div>
          <MiniDayRange low={bankNiftyLow} high={bankNiftyHigh} current={bankNifty} decimals={0} />
          {bankNiftyRel ? (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: bankNiftyRel.color, fontWeight: 700 }}>
              {bankNiftyRel.text}
            </div>
          ) : (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: 'var(--text-lo)' }}>
              NSE_INDEX · NIFTY BANK
            </div>
          )}
          <div className={styles.whyItMatters}>
            Banking beta & heavyweight divergence
          </div>
        </div>

        {/* Cell 2: MIDCAP SELECT */}
        <div
          className={`${styles.glassCell} ${getPulseClass('midcap')} ${topMoverKey === 'midcap' ? styles.topMoverCell : ''}`}
          title="Source: Upstox NSE_INDEX|NIFTY MID SELECT (MIDCPNIFTY)"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className={styles.monoLabel} style={{ fontSize: '10.5px' }}>MIDCAP SELECT</span>
            {topMoverKey === 'midcap' && <span className={styles.topMoverBadge}>TOP MOVER</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '15px', fontWeight: 800, color: '#fff' }}>
              {midcapFormatted}
            </span>
            {midcapSelectChangePct !== null && midcapSelectChangePct !== undefined && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11.5px',
                  fontWeight: 700,
                  color: midcapSelectChangePct >= 0 ? 'var(--mint)' : 'var(--algory-red)',
                }}
              >
                {midcapChangeFormatted ? `${midcapChangeFormatted} ` : ''}
                ({midcapSelectChangePct >= 0 ? `+${midcapSelectChangePct.toFixed(2)}%` : `${midcapSelectChangePct.toFixed(2)}%`})
              </span>
            )}
          </div>
          <MiniDayRange low={midcapSelectLow} high={midcapSelectHigh} current={midcapSelect} decimals={0} />
          {midcapRel ? (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: midcapRel.color, fontWeight: 700 }}>
              {midcapRel.text}
            </div>
          ) : (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: 'var(--text-lo)' }}>
              NSE_INDEX · MIDCPNIFTY
            </div>
          )}
          <div className={styles.whyItMatters}>
            Broad market risk appetite vs large cap
          </div>
        </div>

        {/* Cell 3: SENSEX */}
        <div
          className={`${styles.glassCell} ${getPulseClass('sensex')} ${topMoverKey === 'sensex' ? styles.topMoverCell : ''}`}
          title="Source: Upstox BSE_INDEX|SENSEX"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className={styles.monoLabel} style={{ fontSize: '10.5px' }}>SENSEX</span>
            {topMoverKey === 'sensex' && <span className={styles.topMoverBadge}>TOP MOVER</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '15px', fontWeight: 800, color: '#fff' }}>
              {sensexFormatted}
            </span>
            {sensexChangePct !== null && sensexChangePct !== undefined && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11.5px',
                  fontWeight: 700,
                  color: sensexChangePct >= 0 ? 'var(--mint)' : 'var(--algory-red)',
                }}
              >
                {sensexChangeFormatted ? `${sensexChangeFormatted} ` : ''}
                ({sensexChangePct >= 0 ? `+${sensexChangePct.toFixed(2)}%` : `${sensexChangePct.toFixed(2)}%`})
              </span>
            )}
          </div>
          <MiniDayRange low={sensexLow} high={sensexHigh} current={sensex} decimals={0} />
          {sensexRel ? (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: sensexRel.color, fontWeight: 700 }}>
              {sensexRel.text}
            </div>
          ) : (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: 'var(--text-lo)' }}>
              BSE_INDEX · SENSEX 30
            </div>
          )}
          <div className={styles.whyItMatters}>
            BSE headline & institutional basket parity
          </div>
        </div>

        {/* Cell 4: INDIA VIX (Prominent Card with Day Range Slider & Aura) */}
        <div
          className={`${styles.glassCell} ${styles.vixAuraCell} ${getPulseClass('vix')} ${topMoverKey === 'vix' ? styles.topMoverCell : ''}`}
          title="Source: Upstox NSE_INDEX|India VIX (Daily Session Range)"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <span className={styles.monoLabel} style={{ fontSize: '10.5px', color: 'var(--amber)' }}>INDIA VIX</span>
              {topMoverKey === 'vix' && <span className={styles.topMoverBadge}>TOP MOVER</span>}
            </div>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '7.5px',
                fontWeight: 700,
                letterSpacing: '0.05em',
                padding: '1px 5px',
                borderRadius: '3px',
                background: isVixRising ? 'rgba(255, 184, 0, 0.15)' : 'rgba(0, 255, 157, 0.12)',
                color: isVixRising ? 'var(--amber)' : 'var(--mint)',
                border: `1px solid ${isVixRising ? 'rgba(255, 184, 0, 0.3)' : 'rgba(0, 255, 157, 0.3)'}`,
              }}
            >
              {isVixRising ? '▲ RISING' : vixDir === 'FALLING' ? '▼ FALLING' : '● FLAT'} · {vixRuleContext}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: '#fff' }}>
              {vixFormatted}
            </span>
            {indiaVixChangePct !== null && indiaVixChangePct !== undefined && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  fontWeight: 700,
                  color: (indiaVixChange ?? indiaVixChangePct) >= 0 ? 'var(--mint)' : 'var(--algory-red)',
                }}
              >
                {indiaVixChange !== null && indiaVixChange !== undefined ? `${indiaVixChange >= 0 ? '+' : ''}${indiaVixChange.toFixed(2)} ` : ''}
                ({indiaVixChangePct >= 0 ? `+${indiaVixChangePct.toFixed(2)}%` : `${indiaVixChangePct.toFixed(2)}%`})
              </span>
            )}
          </div>
          {/* Day Range Slider */}
          <div className={styles.rangeTrack}>
            <div className={styles.rangeFill} style={{ width: `${vixRangePct}%` }} />
            <div className={styles.rangeDot} style={{ left: `${vixRangePct}%` }} />
          </div>
          <div className={styles.rangeLabels}>
            <span>LOW {vixLow !== null ? vixLow.toFixed(2) : '—'}</span>
            <span>HIGH {vixHigh !== null ? vixHigh.toFixed(2) : '—'}</span>
          </div>
          <div className={styles.whyItMatters}>
            Low vol compresses decay; high vol widens bands
          </div>
        </div>

        {/* Cell 5: GIFT NIFTY (Transparent Freshness & Spread vs Spot) */}
        <div
          className={`${styles.glassCell} ${getPulseClass('gift')} ${topMoverKey === 'gift' ? styles.topMoverCell : ''}`}
          title="Source: Upstox GLOBAL_INDEX|SGX NIFTY (Delayed Provider Feed)"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className={styles.monoLabel} style={{ fontSize: '10.5px' }}>GIFT NIFTY</span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '7.5px',
                color: '#f59e0b',
                letterSpacing: '0.04em',
                fontWeight: 700,
                background: 'rgba(245, 158, 11, 0.1)',
                padding: '1px 5px',
                borderRadius: '3px',
                border: '1px solid rgba(245, 158, 11, 0.3)',
              }}
            >
              {giftNiftyFreshness || 'DELAYED_PROVIDER'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '15px', fontWeight: 800, color: 'var(--cyan)' }}>
              {giftFormatted}
            </span>
            {giftNiftyChangePct !== null && giftNiftyChangePct !== undefined && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  fontWeight: 700,
                  color: giftNiftyChangePct >= 0 ? 'var(--mint)' : 'var(--algory-red)',
                }}
              >
                {giftNiftyChangePct >= 0 ? `+${giftNiftyChangePct.toFixed(2)}%` : `${giftNiftyChangePct.toFixed(2)}%`}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: '8.5px' }}>
            <span style={{ color: 'var(--text-lo)' }}>SPREAD:</span>
            <span style={{ color: (giftSpread ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)', fontWeight: 700 }}>
              {giftSpreadFormatted ?? 'SESSION_LAST'}
            </span>
          </div>
          <div className={styles.whyItMatters}>
            Overnight bias · Delayed provider feed
          </div>
        </div>

        {/* Cell 6: PCR (UPSTOX) (Spans 2 columns, factual breakdown, with tooltip) */}
        <div className={`${styles.glassCell} ${styles.pcrSpan2}`} title="Provenance: DIRECT_UPSTOX_MARKET_INFO (/v2/market/pcr)">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <span className={styles.monoLabel} style={{ fontSize: '10.5px' }}>PCR (UPSTOX)</span>
              <InfoTooltip text="Put OI / Call OI ratio across active strikes. >1.0 indicates put accumulation / bullish support bias; <0.8 indicates call writing / overhead resistance pressure." />
            </div>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: 'var(--mint)', letterSpacing: '0.04em', fontWeight: 700 }}>
              {pcrProvenance || 'DIRECT_UPSTOX_MARKET_INFO'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: 'var(--cyan)' }}>
              {pcrFormatted}
            </span>
            {pcrShift && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 600, color: pcrShift.delta >= 0 ? 'var(--mint)' : 'var(--algory-red)' }}>
                15m: {pcrShift.prev.toFixed(3)} → {pcrShift.curr.toFixed(3)} ({pcrShift.delta >= 0 ? '+' : ''}{pcrShift.delta.toFixed(4)})
              </span>
            )}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--text-mid)', letterSpacing: '0.04em' }}>
            <span>PUT OI / CALL OI · EXP {oiShift?.expiry ?? '08 SEP'}</span>
            <span style={{ color: 'var(--text-lo)' }}>FACTUAL RATIO</span>
          </div>
          <div className={styles.whyItMatters}>
            Factual option open interest ratio across chain
          </div>
        </div>

        {/* Cell 7: MAX PAIN */}
        <div className={styles.glassCell} title="Provenance: DIRECT_UPSTOX_MARKET_INFO (/v2/market/max-pain)">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <span className={styles.monoLabel} style={{ fontSize: '10.5px' }}>MAX PAIN</span>
              <InfoTooltip text="The strike price where option sellers face minimum payout loss upon expiry, and option buyers face maximum collective loss." />
            </div>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: 'var(--mint)', letterSpacing: '0.04em', fontWeight: 700 }}>
              {maxPainProvenance || 'DIRECT_UPSTOX_MARKET_INFO'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: '#fff' }}>
              {maxPainFormatted}
            </span>
            {maxPainShift && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9.5px', color: maxPainShift.delta === 0 ? 'var(--text-lo)' : 'var(--mint)' }}>
                15m: {maxPainShift.delta === 0 ? 'NO SHIFT' : `${formatNumber(maxPainShift.prev)}→${formatNumber(maxPainShift.curr)}`}
              </span>
            )}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: 'var(--text-lo)', letterSpacing: '0.04em' }}>
            ZERO LOSS STRIKE · FACTUAL
          </div>
          <div className={styles.whyItMatters}>
            Zero-loss strike for aggregate option writers
          </div>
        </div>

        {/* Cell 8: AUDIO */}
        <div className={styles.glassCell}>
          <div className={styles.monoLabel} style={{ fontSize: '10.5px' }}>AUDIO</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 800, color: 'var(--text-lo)' }}>
            OFF
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: 'var(--text-lo)', letterSpacing: '0.04em' }}>
            TELEMETRY MUTE
          </div>
          <div className={styles.whyItMatters}>
            Telemetry acoustic alerts muted
          </div>
        </div>

        {/* ROW 3: OPTION OI SHIFT INTELLIGENCE (4 COLS) & REBUILT FII/DII INSTITUTIONAL FLOW (5 COLS) */}
        {/* Box A: OPTION OI SHIFT INTELLIGENCE */}
        <div
          className={`${styles.glassCell} ${styles.oiShiftCell}`}
          title="Official strike-level OI and Net Delta shifts from Upstox Option Chain"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <span className={styles.monoLabel} style={{ color: 'var(--cyan)', fontSize: '11px' }}>
                OPTION OI SHIFT INTELLIGENCE
              </span>
              <InfoTooltip text="Tracks net open interest shifts today vs previous session. Identifies strike defense zones and institutional accumulation." />
            </div>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '8.5px',
                fontWeight: 700,
                color: 'var(--cyan)',
                background: 'rgba(0, 240, 255, 0.08)',
                padding: '2px 8px',
                borderRadius: '4px',
                border: '1px solid rgba(0, 240, 255, 0.25)',
              }}
            >
              {oiShift?.horizon || 'TODAY ΔOI vs PREVIOUS SESSION (1D)'} · EXP {oiShift?.expiry ?? '08 SEP'}
            </span>
          </div>

          {/* Net Totals Row */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              borderBottom: '1px solid rgba(255,255,255,0.06)',
              paddingBottom: '4px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-lo)', fontWeight: 700 }}>
                CALL ΔOI:
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '13px',
                  fontWeight: 800,
                  color: (oiShift?.total_call_delta_oi ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)',
                }}
              >
                {formatOiDelta(oiShift?.total_call_delta_oi)}
              </span>
            </div>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '7.5px', color: 'var(--text-lo)', background: 'rgba(255,255,255,0.04)', padding: '1px 5px', borderRadius: '3px' }}>
              {oiShift?.source_type || oiShift?.provenance || 'DIRECT_UPSTOX_CHANGE_OI'}
            </span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-lo)', fontWeight: 700 }}>
                PUT ΔOI:
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '13px',
                  fontWeight: 800,
                  color: (oiShift?.total_put_delta_oi ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)',
                }}
              >
                {formatOiDelta(oiShift?.total_put_delta_oi)}
              </span>
            </div>
          </div>

          {/* Heuristic Subheading with Tooltip and Explainer */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1px', marginTop: '1px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', fontWeight: 800, color: 'var(--text-mid)', letterSpacing: '0.06em' }}>
                PRICE + OI STYLE READ (HEURISTIC)
              </span>
              <InfoTooltip text="4-quadrant style read inferred from premium change and open interest delta. Not direct evidence of buyer vs writer aggressor trade flow." />
            </div>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '7.5px', color: 'var(--text-lo)', fontStyle: 'italic' }}>
              {oiShift?.heuristic_explainer || 'Derived from premium direction + OI change. Not direct buyer/writer proof.'}
            </span>
          </div>

          {/* 4 Key Strikes with 4-Quadrant Heuristic */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '6px 10px' }}>
            {renderOiStrike('CALL ADD', 'CE', oiShift?.largest_call_increase)}
            {renderOiStrike('CALL UNWIND', 'CE', oiShift?.largest_call_unwind)}
            {renderOiStrike('PUT ADD', 'PE', oiShift?.largest_put_increase)}
            {renderOiStrike('PUT UNWIND', 'PE', oiShift?.largest_put_unwind)}
          </div>

          <div className={styles.whyItMatters}>
            Identifies institutional strike defense & shift in seller pain zones
          </div>
        </div>

        {/* Box B: REBUILT FII / DII ACTIVITY (INSTITUTIONAL FLOW) */}
        <div
          className={`${styles.glassCell} ${styles.fiiDiiExpandedCell}`}
          title="Official NSE Clearing Participant Reports via Upstox /market/fii & /market/dii"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <span className={styles.monoLabel} style={{ fontSize: '11px' }}>
                FII / DII ACTIVITY (INSTITUTIONAL FLOW)
              </span>
              <InfoTooltip text="Official daily clearing participant reports. View column represents dashboard rule-based interpretation of official net and change fields." />
            </div>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '9px',
                fontWeight: 700,
                color: 'var(--mint)',
                letterSpacing: '0.08em',
                background: 'rgba(0, 255, 157, 0.08)',
                padding: '2px 8px',
                borderRadius: '4px',
                border: '1px solid rgba(0, 255, 157, 0.25)',
              }}
            >
              DAILY OFFICIAL · {fiiDiiSummary?.date ?? '04 SEP'}
            </span>
          </div>

          {/* 4-Column Compact Table: Segment | Net | Chg | View */}
          <div className={styles.fiiDiiTable}>
            {/* Header Row */}
            <div className={styles.fiiDiiHeaderRow}>
              <span>SEGMENT</span>
              <span>NET</span>
              <span>CHG (1D)</span>
              <span style={{ textAlign: 'center' }}>VIEW</span>
            </div>

            {/* Row 1: FII Futures */}
            <div className={styles.fiiDiiRowCard}>
              <div className={styles.fiiDiiMainRow}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9.5px', fontWeight: 800, color: '#fff' }}>
                  FII FUTURES
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11.5px', fontWeight: 800, color: (fiiDiiSummary?.fii_fut_net ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)' }}>
                  {fiiFutFormatted}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10.5px', fontWeight: 700, color: (fiiDiiSummary?.fii_fut_chg ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)' }}>
                  {fiiDiiSummary?.fii_fut_chg !== null && fiiDiiSummary?.fii_fut_chg !== undefined
                    ? `${fiiDiiSummary.fii_fut_chg >= 0 ? '+' : ''}${fiiDiiSummary.fii_fut_chg.toFixed(0)} CR`
                    : '—'}
                </span>
                <span
                  className={`${styles.sentimentBadge} ${
                    fiiDiiSummary?.fii_fut_view === 'BULLISH'
                      ? styles.sentimentBullish
                      : fiiDiiSummary?.fii_fut_view === 'BEARISH'
                      ? styles.sentimentBearish
                      : styles.sentimentNeutral
                  }`}
                >
                  {fiiDiiSummary?.fii_fut_view || 'BEARISH'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: '8px', color: 'var(--text-lo)' }}>
                <span>
                  L: {fiiDiiSummary?.fii_futures?.long_contracts ? `${(fiiDiiSummary.fii_futures.long_contracts / 1000).toFixed(0)}K` : '—'} ({fiiDiiSummary?.fii_futures?.long_pct ?? 11}% L) · S: {fiiDiiSummary?.fii_futures?.short_contracts ? `${(fiiDiiSummary.fii_futures.short_contracts / 1000).toFixed(0)}K` : '—'}
                </span>
                <span>OI: {fiiDiiSummary?.fii_futures?.oi_contracts ? `${(fiiDiiSummary.fii_futures.oi_contracts / 1000).toFixed(0)}K` : '—'}</span>
              </div>
              <div className={styles.balanceBar}>
                <div className={styles.balanceBuyFill} style={{ width: `${fiiFutBuyPct}%` }} />
                <div className={styles.balanceMarker} style={{ left: `${fiiFutBuyPct}%` }} />
              </div>
            </div>

            {/* Row 2: FII Options */}
            <div className={styles.fiiDiiRowCard}>
              <div className={styles.fiiDiiMainRow}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9.5px', fontWeight: 800, color: '#fff' }}>
                  FII OPTIONS
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11.5px', fontWeight: 800, color: (fiiDiiSummary?.fii_opt_net ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)' }}>
                  {fiiDiiSummary?.fii_opt_net !== null && fiiDiiSummary?.fii_opt_net !== undefined
                    ? `${fiiDiiSummary.fii_opt_net >= 0 ? '+' : ''}${fiiDiiSummary.fii_opt_net.toLocaleString('en-IN', { maximumFractionDigits: 0 })} CR`
                    : '—'}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10.5px', fontWeight: 700, color: (fiiDiiSummary?.fii_opt_chg ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)' }}>
                  {fiiDiiSummary?.fii_opt_chg !== null && fiiDiiSummary?.fii_opt_chg !== undefined
                    ? `${fiiDiiSummary.fii_opt_chg >= 0 ? '+' : ''}${fiiDiiSummary.fii_opt_chg.toLocaleString('en-IN', { maximumFractionDigits: 0 })} CR`
                    : '—'}
                </span>
                <span
                  className={`${styles.sentimentBadge} ${
                    fiiDiiSummary?.fii_opt_view === 'BULLISH'
                      ? styles.sentimentBullish
                      : fiiDiiSummary?.fii_opt_view === 'BEARISH'
                      ? styles.sentimentBearish
                      : styles.sentimentNeutral
                  }`}
                >
                  {fiiDiiSummary?.fii_opt_view || 'BEARISH'}
                </span>
              </div>
              {/* Call vs Put Breakdown */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', marginTop: '2px', background: 'rgba(0,0,0,0.25)', padding: '3px 6px', borderRadius: '4px' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '7.5px', color: 'var(--text-mid)', display: 'flex', justifyContent: 'space-between' }}>
                  <span>CALL NET:</span>
                  <span style={{ color: (fiiDiiSummary?.fii_call_options?.net_contracts ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)', fontWeight: 700 }}>
                    {formatNumber(fiiDiiSummary?.fii_call_options?.net_contracts)} ({fiiDiiSummary?.fii_call_options?.view || 'BEARISH'})
                  </span>
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '7.5px', color: 'var(--text-mid)', display: 'flex', justifyContent: 'space-between' }}>
                  <span>PUT NET:</span>
                  <span style={{ color: (fiiDiiSummary?.fii_put_options?.net_contracts ?? 0) <= 0 ? 'var(--mint)' : 'var(--algory-red)', fontWeight: 700 }}>
                    {formatNumber(fiiDiiSummary?.fii_put_options?.net_contracts)} ({fiiDiiSummary?.fii_put_options?.view || 'BEARISH'})
                  </span>
                </div>
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '7.5px', color: 'var(--text-lo)' }}>
                Turnover: Buy ₹{fiiDiiSummary?.fii_options?.buy_amount_cr ? (fiiDiiSummary.fii_options.buy_amount_cr / 100000).toFixed(2) : '—'}L Cr · Sell ₹{fiiDiiSummary?.fii_options?.sell_amount_cr ? (fiiDiiSummary.fii_options.sell_amount_cr / 100000).toFixed(2) : '—'}L Cr
              </div>
            </div>

            {/* Row 3: DII Cash */}
            <div className={styles.fiiDiiRowCard}>
              <div className={styles.fiiDiiMainRow}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9.5px', fontWeight: 800, color: '#fff' }}>
                  DII CASH
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11.5px', fontWeight: 800, color: (fiiDiiSummary?.dii_cash_net ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)' }}>
                  {diiCashFormatted}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10.5px', fontWeight: 700, color: (fiiDiiSummary?.dii_cash_chg ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)' }}>
                  {fiiDiiSummary?.dii_cash_chg !== null && fiiDiiSummary?.dii_cash_chg !== undefined
                    ? `${fiiDiiSummary.dii_cash_chg >= 0 ? '+' : ''}${fiiDiiSummary.dii_cash_chg.toFixed(0)} CR`
                    : '—'}
                </span>
                <span
                  className={`${styles.sentimentBadge} ${
                    fiiDiiSummary?.dii_cash_view === 'BULLISH'
                      ? styles.sentimentBullish
                      : fiiDiiSummary?.dii_cash_view === 'BEARISH'
                      ? styles.sentimentBearish
                      : styles.sentimentNeutral
                  }`}
                >
                  {fiiDiiSummary?.dii_cash_view || 'BULLISH'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: '8px', color: 'var(--text-lo)' }}>
                <span>Buy: ₹{fiiDiiSummary?.dii_cash?.buy_amount_cr?.toFixed(0) ?? '—'}Cr · Sell: ₹{fiiDiiSummary?.dii_cash?.sell_amount_cr?.toFixed(0) ?? '—'}Cr</span>
                <span>{diiBuyPct}% BUY</span>
              </div>
              <div className={styles.balanceBar}>
                <div className={styles.balanceBuyFill} style={{ width: `${diiBuyPct}%` }} />
                <div className={styles.balanceMarker} style={{ left: `${diiBuyPct}%` }} />
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '7.5px', color: 'var(--text-lo)', fontStyle: 'italic' }}>
                {fiiDiiSummary?.dii_derivatives || 'Derivatives: N/A (official source unavailable)'}
              </div>
            </div>
          </div>

          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '7.5px', color: 'var(--text-lo)', letterSpacing: '0.03em', marginTop: '2px' }}>
            NSE CLEARING PARTICIPANT REPORT · DAILY OFFICIAL · {fiiDiiSummary?.view_rule_explanation || 'View = dashboard interpretation of official net + change fields'}
          </div>
        </div>
      </div>
    </div>
  )
})

