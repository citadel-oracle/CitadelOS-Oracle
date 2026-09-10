'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import type { OracleEvidenceObservation } from '@/dashboard/store/oracleStore'
import {
  friendlyArgus,
  UNKNOWN,
} from '../photonicPresentationHelpers'

export interface PhotonicArgusSupportProps {
  argus?: OracleEvidenceObservation | null
  flow?: OracleEvidenceObservation | null
  oi?: OracleEvidenceObservation | null
  futures?: OracleEvidenceObservation | null
  marketSupport?: number | null
}

export const PhotonicArgusSupport = memo(function PhotonicArgusSupport({
  argus = null,
  marketSupport = null,
}: PhotonicArgusSupportProps) {
  const hasSupport = marketSupport !== null && marketSupport !== undefined
  const supportPosition = hasSupport ? Math.max(0, Math.min(100, marketSupport)) : 50
  const argusStateText = argus?.known ? friendlyArgus(argus.state) : 'UNKNOWN'

  const whyText = argus?.known
    ? (argus.state === 'CONFIRMS_TARGET' ? 'ARGUS ALIGNED WITH REVERSAL DIRECTION' : friendlyArgus(argus.state))
    : 'NO ACTIVE ARGUS CONFIRMATION REPORTED'

  return (
    <div
      className={styles.card}
      style={{ gridColumn: 'span 1' }}
      aria-label="ARGUS Market Support Matrix"
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      <div className={styles.monoLabel} style={{ marginBottom: '10px' }}>
        MARKET SUPPORT MATRIX
      </div>
      <div className={styles.teslaTrack} style={{ marginBottom: '6px', height: '8px' }}>
        <div className={`${styles.teslaFill} ${styles.teslaFillMint}`} style={{ width: `${supportPosition}%` }} />
        <div className={styles.teslaHead} style={{ left: `calc(${supportPosition}% - 7px)` }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '18px' }} className={styles.monoLabel}>
        <span style={{ color: 'var(--algory-red)' }}>AGAINST TRADE</span>
        <span style={{ color: 'var(--mint)' }}>SUPPORTING TRADE</span>
      </div>

      <div className={styles.monoLabel} style={{ marginBottom: '4px' }}>
        ARGUS CONTEXT INDEX
      </div>
      <div className={styles.title} style={{ fontSize: '20px', color: argus?.known ? 'var(--cyan)' : 'var(--text-lo)', marginBottom: '4px' }}>
        {argusStateText}
      </div>
      <div className={styles.monoLabel} style={{ marginBottom: '12px', lineHeight: 1.4, fontSize: '8px' }}>
        QUALITY / CONTEXT CONFIRMATION · NOT A HARD GATE
      </div>

      <div style={{ borderTop: '1px solid var(--line-dim)', paddingTop: '10px' }} className={styles.monoLabel}>
        <span style={{ color: 'var(--cyan)' }}>WHY:</span> {whyText}
      </div>
    </div>
  )
})
