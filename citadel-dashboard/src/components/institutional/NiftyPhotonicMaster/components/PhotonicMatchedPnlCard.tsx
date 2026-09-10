'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import type { OracleShadowVariant } from '@/dashboard/store/oracleStore'
import {
  formatMoney,
  formatNumber,
  formatR,
  pnlTone,
  UNKNOWN,
} from '../photonicPresentationHelpers'

export interface PhotonicMatchedPnlCardProps {
  baseline?: OracleShadowVariant | null
  confirmed?: OracleShadowVariant | null
  early?: OracleShadowVariant | null
}

export const PhotonicMatchedPnlCard = memo(function PhotonicMatchedPnlCard({
  baseline = null,
  confirmed = null,
}: PhotonicMatchedPnlCardProps) {
  const vobTone = pnlTone(baseline?.pnl)
  const confTone = pnlTone(confirmed?.pnl)

  const baselinePnlText = baseline?.pnl !== null && baseline?.pnl !== undefined ? formatMoney(baseline.pnl) : 'P&L NOT REPORTED'
  const confirmedPnlText = confirmed?.pnl !== null && confirmed?.pnl !== undefined ? formatMoney(confirmed.pnl) : 'P&L NOT REPORTED'

  const baselineMfeWidth = baseline?.mfe !== null && baseline?.mfe !== undefined ? Math.min(100, Math.max(0, baseline.mfe * 10)) : 0
  const baselineMaeWidth = baseline?.mae !== null && baseline?.mae !== undefined ? Math.min(100, Math.max(0, Math.abs(baseline.mae) * 10)) : 0

  const confMfeWidth = confirmed?.mfe !== null && confirmed?.mfe !== undefined ? Math.min(100, Math.max(0, confirmed.mfe * 10)) : 0
  const confMaeWidth = confirmed?.mae !== null && confirmed?.mae !== undefined ? Math.min(100, Math.max(0, Math.abs(confirmed.mae) * 10)) : 0

  return (
    <div
      className={styles.card}
      style={{ gridColumn: 'span 1', gridRow: 'span 2' }}
      aria-label="Matched Comparison Frozen Contract P&L"
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
        <div className={styles.monoLabel}>MATCHED COMPARISON</div>
        <div className={styles.monoLabel} style={{ color: 'var(--cyan)' }}>FROZEN CONTRACT</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '14px' }}>
        {/* VOB ENTRY TILE */}
        <div
          className={`${styles.pnlInnerTile} ${vobTone === 'positive' ? styles.flashGreen : vobTone === 'negative' ? styles.flashRed : ''}`}
          style={{ borderColor: 'rgba(0, 255, 157, 0.35)' }}
        >
          <div className={styles.tileFlashAura} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <div className={styles.monoLabel} style={{ color: 'var(--mint)', fontWeight: 700 }}>VOB ENTRY</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '7.5px', color: 'var(--mint)', background: 'rgba(0,255,157,0.1)', padding: '1px 4px', borderRadius: '3px' }}>
              {baseline?.pnl !== null && baseline?.pnl !== undefined ? (baseline.pnl >= 0 ? `+₹${Math.round(baseline.pnl)}` : `-₹${Math.round(Math.abs(baseline.pnl))}`) : '—'}
            </div>
          </div>
          <div className={styles.monoLabel} style={{ color: 'var(--text-lo)', marginBottom: '8px', fontSize: '7.5px' }}>
            Entered at VOB
          </div>

          <div className={styles.title} style={{ fontSize: '15px', textAlign: 'center', marginBottom: '8px', color: vobTone === 'positive' ? 'var(--mint)' : vobTone === 'negative' ? 'var(--algory-red)' : 'var(--text-mid)', textShadow: vobTone === 'positive' ? '0 0 14px var(--mint-glow)' : 'none' }}>
            {baselinePnlText}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '7.5px' }} className={styles.monoLabel}>
            <div>R<br /><span style={{ color: vobTone === 'positive' ? 'var(--mint)' : 'var(--text-white)', fontWeight: 700 }}>{formatR(baseline?.r ?? null)}</span></div>
            <div>ENTRY<br /><span style={{ color: 'var(--text-white)', fontWeight: 700 }}>{formatMoney(baseline?.entryAsk ?? null)}</span></div>
            <div>BID<br /><span style={{ color: 'var(--text-white)', fontWeight: 700 }}>{formatMoney(baseline?.currentBid ?? null)}</span></div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '4px' }}>
            <span className={styles.monoLabel} style={{ fontSize: '7px' }}>MFE</span>
            <div className={styles.teslaTrack} style={{ flex: 1, height: '4px' }}>
              <div className={styles.teslaFill} style={{ width: `${baselineMfeWidth}%` }} />
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span className={styles.monoLabel} style={{ fontSize: '7px' }}>MAE</span>
            <div className={styles.teslaTrack} style={{ flex: 1, height: '4px' }}>
              <div className={`${styles.teslaFill} ${styles.teslaFillRed}`} style={{ width: `${baselineMaeWidth}%` }} />
            </div>
          </div>
        </div>

        {/* CONFIRMED ENTRY TILE */}
        <div
          className={`${styles.pnlInnerTile} ${confTone === 'positive' ? styles.flashGreen : confTone === 'negative' ? styles.flashRed : ''}`}
          style={{ borderColor: 'rgba(255, 30, 75, 0.35)' }}
        >
          <div className={styles.tileFlashAura} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <div className={styles.monoLabel} style={{ color: 'var(--algory-red)', fontWeight: 700 }}>CONFIRMED</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '7.5px', color: 'var(--algory-red)', background: 'rgba(255,30,75,0.1)', padding: '1px 4px', borderRadius: '3px' }}>
              {confirmed?.pnl !== null && confirmed?.pnl !== undefined ? (confirmed.pnl >= 0 ? `+₹${Math.round(confirmed.pnl)}` : `-₹${Math.round(Math.abs(confirmed.pnl))}`) : '—'}
            </div>
          </div>
          <div className={styles.monoLabel} style={{ color: 'var(--text-lo)', marginBottom: '8px', fontSize: '7.5px' }}>
            Oracle confirmed
          </div>

          <div className={styles.title} style={{ fontSize: '15px', textAlign: 'center', marginBottom: '8px', color: confTone === 'positive' ? 'var(--mint)' : confTone === 'negative' ? 'var(--algory-red)' : 'var(--text-mid)', textShadow: confTone === 'negative' ? '0 0 14px var(--algory-red-glow)' : 'none' }}>
            {confirmedPnlText}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '7.5px' }} className={styles.monoLabel}>
            <div>R<br /><span style={{ color: confTone === 'negative' ? 'var(--algory-red)' : 'var(--text-white)', fontWeight: 700 }}>{formatR(confirmed?.r ?? null)}</span></div>
            <div>ENTRY<br /><span style={{ color: 'var(--text-white)', fontWeight: 700 }}>{formatMoney(confirmed?.entryAsk ?? null)}</span></div>
            <div>BID<br /><span style={{ color: 'var(--text-white)', fontWeight: 700 }}>{formatMoney(confirmed?.currentBid ?? null)}</span></div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '4px' }}>
            <span className={styles.monoLabel} style={{ fontSize: '7px' }}>MFE</span>
            <div className={styles.teslaTrack} style={{ flex: 1, height: '4px' }}>
              <div className={styles.teslaFill} style={{ width: `${confMfeWidth}%` }} />
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span className={styles.monoLabel} style={{ fontSize: '7px' }}>MAE</span>
            <div className={styles.teslaTrack} style={{ flex: 1, height: '4px' }}>
              <div className={`${styles.teslaFill} ${styles.teslaFillRed}`} style={{ width: `${confMaeWidth}%` }} />
            </div>
          </div>
        </div>
      </div>

      <div className={styles.monoLabel} style={{ textAlign: 'center', color: 'var(--cyan)', fontSize: '7.5px' }}>
        EARLY REVERSAL RESEARCH · QUANTUM SHOCKWAVE
      </div>
    </div>
  )
})
