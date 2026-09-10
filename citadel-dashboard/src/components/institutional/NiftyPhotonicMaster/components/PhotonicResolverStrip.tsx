'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import type { OracleOptionDisplay } from '@/dashboard/store/oracleStore'
import {
  contractLabel,
  formatMoney,
  formatNumber,
  formatRange,
  formatTime,
  UNKNOWN,
} from '../photonicPresentationHelpers'

export interface PhotonicResolverStripProps {
  currentItmCall?: OracleOptionDisplay | null
  currentItmPut?: OracleOptionDisplay | null
  underlying?: number | null
  atmStrike?: number | null
  strikeInterval?: number | null
  marketStatus?: string | null
  pcr?: number | null
  openingPcr?: number | null
  deltaPcr?: number | null
  deltaPcrPct?: number | null
  changePcr?: number | null
  isHistorical?: boolean
}

export const PhotonicResolverStrip = memo(function PhotonicResolverStrip({
  currentItmCall = null,
  currentItmPut = null,
  underlying = null,
  atmStrike = null,
  strikeInterval = null,
  marketStatus = null,
  pcr = null,
  openingPcr = null,
  deltaPcr = null,
  deltaPcrPct = null,
  changePcr = null,
  isHistorical = false,
}: PhotonicResolverStripProps) {
  const pcrText = pcr !== null && pcr !== undefined ? pcr.toFixed(2) : '—'
  const effectiveDelta = deltaPcr ?? changePcr
  let changePcrText = 'PCR BASELINE UNAVAILABLE'
  let pcrTone = 'var(--text-mid)'
  if (effectiveDelta !== null && effectiveDelta !== undefined) {
    const sign = effectiveDelta >= 0 ? '+' : ''
    const arrow = effectiveDelta >= 0 ? '↑' : '↓'
    pcrTone = effectiveDelta >= 0 ? 'var(--mint)' : 'var(--algory-red)'
    const openText = openingPcr !== null && openingPcr !== undefined ? `OPEN ${openingPcr.toFixed(2)} → ` : ''
    if (deltaPcrPct !== null && deltaPcrPct !== undefined) {
      changePcrText = `${openText}${sign}${effectiveDelta.toFixed(2)} (${sign}${deltaPcrPct.toFixed(2)}% ${arrow})`
    } else {
      changePcrText = `${openText}${sign}${effectiveDelta.toFixed(2)} ${arrow}`
    }
  }
  const statusText = (marketStatus || 'OPEN').toUpperCase()
  const isOpen = statusText.includes('OPEN')

  return (
    <div className={`${styles.card} ${styles.cardResolverStrip}`} aria-label="Current canonical resolver authority and market structure">
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      <div className={styles.resolverGrid5}>
        {/* 1. CANONICAL OPEN INTEREST PCR */}
        <div className={styles.resolverDividerCell}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span className={styles.monoLabel} style={{ color: 'var(--cyan)' }}>OPEN INTEREST PCR</span>
            <span className={`${styles.pill} ${styles.pillCyan}`} style={{ fontSize: '8px', padding: '2px 6px' }}>OI RATIO</span>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', fontWeight: 800, color: 'var(--cyan)', marginBottom: '4px' }}>
            {pcrText}
          </div>
          <div className={styles.monoLabel} style={{ fontSize: '8.5px', color: pcrTone, fontWeight: 700 }}>
            {changePcrText}
          </div>
        </div>

        {/* 2. CANONICAL ATM */}
        <div className={styles.resolverDividerCell}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span className={styles.monoLabel}>CANONICAL ATM</span>
            <span className={`${styles.pill} ${styles.pillMint}`} style={{ fontSize: '8px', padding: '2px 6px' }}>UPSTOX CHAIN</span>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', fontWeight: 800, color: '#fff', marginBottom: '4px' }}>
            {formatNumber(atmStrike)}
          </div>
          <div className={styles.monoLabel} style={{ fontSize: '8.5px', color: 'var(--mint)' }}>
            ARGUS RESOLVER
          </div>
        </div>

        {/* 3. SPOT REFERENCE */}
        <div className={styles.resolverDividerCell}>
          <div className={styles.monoLabel}>SPOT REFERENCE</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '18px', fontWeight: 800, color: '#fff', marginBottom: '4px', marginTop: '2px' }}>
            {formatNumber(underlying)}
          </div>
          <div className={styles.monoLabel} style={{ color: 'var(--cyan)', fontSize: '8.5px' }}>
            LIVE NIFTY 50
          </div>
        </div>

        {/* 4. STRIKE STEP */}
        <div className={styles.resolverDividerCell}>
          <div className={styles.monoLabel}>STRIKE INTERVAL</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '18px', fontWeight: 800, color: '#fff', marginBottom: '4px', marginTop: '2px' }}>
            {formatNumber(strikeInterval)} PTS
          </div>
          <div className={styles.monoLabel} style={{ color: 'var(--text-lo)', fontSize: '8.5px' }}>
            DISCRETE STEP
          </div>
        </div>

        {/* 5. MARKET SESSION */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span className={styles.monoLabel}>MARKET SESSION</span>
            <span className={`${styles.pill} ${isOpen ? styles.pillMint : styles.pillAmber}`} style={{ fontSize: '8px', padding: '2px 6px' }}>
              ● {statusText}
            </span>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '18px', fontWeight: 800, color: isOpen ? 'var(--mint)' : 'var(--amber)', marginBottom: '4px' }}>
            {statusText}
          </div>
          <div className={styles.monoLabel} style={{ color: 'var(--text-lo)', fontSize: '8.5px' }}>
            NSE BSE REGULAR
          </div>
        </div>
      </div>
    </div>
  )
})
