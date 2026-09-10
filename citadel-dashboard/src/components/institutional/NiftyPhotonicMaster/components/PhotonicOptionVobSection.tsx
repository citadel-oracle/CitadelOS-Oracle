'use client'

import React, { memo } from 'react'
import type { OracleOptionDisplay, OracleTradeRecord, VobTimeframe } from '@/dashboard/store/oracleStore'
import styles from '../NiftyPhotonicMaster.module.css'
import {
  formatMoney,
  formatRange,
  formatSetupDistance,
  formatZoneEvidence,
  proximityLabel,
  setupLaneLabel,
  setupProgressLabel,
} from '../photonicPresentationHelpers'

export interface PhotonicOptionVobSectionProps {
  option?: OracleOptionDisplay | null
  trade?: OracleTradeRecord | null
  geometry?: { pricePct: number; zoneStartPct: number; zoneEndPct: number } | null
  side: 'CE' | 'PE'
}

const TIMEFRAMES: VobTimeframe[] = ['1M', '3M', '5M']

/**
 * Exact accepted option-card support matrix and Tesla rail, with canonical
 * setup/lifecycle truth placed above it. No VOB geometry or trade level is
 * calculated here; missing backend authority remains an em dash.
 */
export const PhotonicOptionVobSection = memo(function PhotonicOptionVobSection({
  option = null,
  trade = null,
  geometry = null,
  side,
}: PhotonicOptionVobSectionProps) {
  const isCall = side === 'CE'
  const tone = isCall ? 'var(--mint)' : 'var(--algory-red)'
  const stage = option ? setupProgressLabel(option, trade) : 'NO ACTIVE VOB'
  const distance = option ? proximityLabel(option) : 'UNKNOWN'
  const sliderPct = geometry ? Math.max(4, Math.min(96, geometry.pricePct)) : 50
  const lanes = TIMEFRAMES.map((timeframe) => option?.vobLanes?.find((lane) => lane.timeframe === timeframe) ?? null)

  return <section className={styles.optionVobSection} aria-label={`${side} complete VOB intelligence`}>
    <div className={styles.optionVobDivider} />
    <div className={styles.optionVobHeader}>
      <span className={styles.monoLabel}>SETUP PROGRESS · {option?.vobTimeframe ?? '—'} VOB</span>
      <strong style={{ color: tone }}>{stage}</strong>
    </div>
    <div className={styles.optionVobZone}>{option ? formatZoneEvidence(option) : 'NO ACTIVE VOB'}</div>
    <div className={styles.optionVobDistance}>{option ? formatSetupDistance(option) : 'DIST —'}</div>

    <div className={styles.optionVobTruthGrid}>
      <div><span>ENTRY ZONE</span><strong>{formatRange(option?.zoneBottom, option?.zoneTop)}</strong></div>
      <div><span>SL</span><strong>{formatMoney(trade?.stopLoss)}</strong></div>
      <div><span>TARGET</span><strong>{formatMoney(trade?.target)}</strong></div>
      <div><span>RECOVERY / CONTEXT</span><strong>{option ? `${option.zoneState} · ${option.relation}` : '—'}</strong></div>
    </div>

    <div className={styles.optionVobLaneMatrix} aria-label={`${side} 1M 3M 5M VOB context`}>
      {lanes.map((lane, index) => <div key={TIMEFRAMES[index]}>
        <span style={{ color: lane ? tone : 'var(--text-lo)' }}>{TIMEFRAMES[index]} VOB</span>
        <strong>{lane ? formatRange(lane.zoneBottom, lane.zoneTop) : '—'}</strong>
        <em>{lane ? setupLaneLabel(lane) : 'WAITING'}</em>
      </div>)}
    </div>

    {/* Exact accepted pre-OBI support matrix and High-Voltage Tesla rail. */}
    <div className={styles.monoLabel} style={{ marginBottom: '6px' }}>{option?.vobTimeframe ?? '5M'} VOB · SUPPORT MATRIX</div>
    <div className={styles.optionVobAcceptedRange}>{formatRange(option?.zoneBottom, option?.zoneTop)}</div>
    <div className={styles.optionVobAcceptedDistance}>{distance} · MAGNET ZONE</div>
    <div style={{ position: 'relative' }}>
      <div className={styles.optionVobRailLabels}>
        <span>CURRENT PREMIUM</span>
        <span style={{ color: tone }}>VOB PROXIMITY MAGNET</span>
      </div>
      <div className={styles.teslaTrack}>
        <div className={`${styles.teslaFill} ${isCall ? '' : styles.teslaFillRed}`} style={{ width: `${sliderPct}%` }} />
        <div className={`${styles.teslaHead} ${isCall ? '' : styles.headRed}`} style={{ left: `calc(${sliderPct}% - 8px)` }} />
      </div>
      <div className={styles.optionVobRailFoot}>
        <span style={{ color: tone }}>NEAREST KEY LEVEL {formatMoney(option?.zoneTop)}</span>
      </div>
    </div>
  </section>
})
