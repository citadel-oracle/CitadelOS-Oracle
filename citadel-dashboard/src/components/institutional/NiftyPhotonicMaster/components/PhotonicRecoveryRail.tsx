'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import type { OracleEvidenceObservation } from '@/dashboard/store/oracleStore'
import { UNKNOWN } from '../photonicPresentationHelpers'

export interface PhotonicRecoveryRailProps {
  direction?: string
  state?: string
  turnStrength?: number | null
  control?: string
  failed?: OracleEvidenceObservation | null
  flow?: OracleEvidenceObservation | null
  futures?: OracleEvidenceObservation | null
}

export const PhotonicRecoveryRail = memo(function PhotonicRecoveryRail({
  turnStrength = null,
  control = 'CONTROL DYNAMICS: EVALUATING',
  failed = null,
  flow = null,
  futures = null,
}: PhotonicRecoveryRailProps) {
  const hasTurnStrength = turnStrength !== null && turnStrength !== undefined
  const buyerPct = hasTurnStrength ? Math.max(4, Math.min(96, turnStrength)) : 50
  const sellerPct = 100 - buyerPct

  const sellersLabel = hasTurnStrength ? `SELLERS (${Math.round(sellerPct)}%)` : 'SELLERS (—)'
  const buyersLabel = hasTurnStrength ? `BUYERS (${Math.round(buyerPct)}%)` : 'BUYERS (—)'

  const sellerPressureText = failed?.known ? failed.state : UNKNOWN
  const buyerSupportText = flow?.known ? flow.state : UNKNOWN
  const futuresDeltaText = futures?.known ? futures.state : UNKNOWN

  return (
    <div
      className={styles.card}
      style={{ gridColumn: 'span 2' }}
      aria-label="Recovery Engine Seller ↔ Buyer Control Dynamics"
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
        <div className={styles.monoLabel}>RECOVERY ENGINE · ORDER FLOW DYNAMICS</div>
        <div className={styles.monoLabel} style={{ color: 'var(--algory-red)' }}>CANONICAL EVIDENCE</div>
      </div>
      <div className={styles.title} style={{ fontSize: '18px', marginBottom: '14px' }}>
        {control}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '14px' }}>
        <div className={styles.monoLabel} style={{ color: 'var(--algory-red)', fontWeight: 700 }}>
          {sellersLabel}
        </div>
        <div className={styles.teslaTrack} style={{ flex: 1, height: '14px' }}>
          <div className={styles.teslaFill} style={{ width: `${buyerPct}%` }} />
          <div className={styles.teslaHead} style={{ left: `calc(${buyerPct}% - 8px)` }} />
        </div>
        <div className={styles.monoLabel} style={{ color: 'var(--cyan)', fontWeight: 700 }}>
          {buyersLabel}
        </div>
      </div>
      <div className={styles.monoLabel} style={{ textAlign: 'center', marginBottom: '14px', fontSize: '8px' }}>
        {hasTurnStrength ? 'CANONICAL ROTATION ESTIMATE' : 'CONTROL RATIO UNKNOWN · MAGNITUDE NOT REPORTED'}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '14px', borderTop: '1px solid var(--line-dim)', paddingTop: '12px' }}>
        <div>
          <div className={styles.monoLabel} style={{ marginBottom: '4px' }}>SELLER PRESSURE</div>
          <div className={styles.monoLabel} style={{ color: failed?.known ? 'var(--text-white)' : 'var(--text-lo)', fontWeight: 700 }}>
            {sellerPressureText}
          </div>
        </div>
        <div>
          <div className={styles.monoLabel} style={{ marginBottom: '4px' }}>BUYER SUPPORT</div>
          <div className={styles.monoLabel} style={{ color: flow?.known ? 'var(--mint)' : 'var(--text-lo)', fontWeight: 700 }}>
            {buyerSupportText}
          </div>
        </div>
        <div>
          <div className={styles.monoLabel} style={{ marginBottom: '4px' }}>FUTURES DELTA</div>
          <div className={styles.monoLabel} style={{ color: futures?.known ? 'var(--cyan)' : 'var(--text-lo)', fontWeight: 700 }}>
            {futuresDeltaText}
          </div>
        </div>
      </div>
    </div>
  )
})
