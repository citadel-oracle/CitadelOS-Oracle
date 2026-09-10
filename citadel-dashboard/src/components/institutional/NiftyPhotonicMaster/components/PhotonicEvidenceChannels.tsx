'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import { UNKNOWN } from '../photonicPresentationHelpers'

export interface PhotonicEvidenceChannelsProps {
  rows?: {
    label: string
    value: string
    known: boolean
    quality?: string
  }[]
}

export const PhotonicEvidenceChannels = memo(function PhotonicEvidenceChannels({
  rows = [],
}: PhotonicEvidenceChannelsProps) {
  const defaultChannels = [
    { label: 'FAILED AGGRESSION', value: UNKNOWN, known: false },
    { label: 'OPPOSING OPTION', value: UNKNOWN, known: false },
    { label: 'TARGET OPTION', value: UNKNOWN, known: false },
    { label: 'FUTURES RESPONSE', value: UNKNOWN, known: false },
  ]

  const displayRows = rows.length > 0 ? rows : defaultChannels

  return (
    <div
      className={styles.card}
      style={{ gridColumn: 'span 2' }}
      aria-label="Failed Aggression + Options Telemetry [4 Channels]"
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      <div style={{ display: 'flex', justifySelf: 'stretch', justifyContent: 'space-between', marginBottom: '12px' }}>
        <div className={styles.monoLabel}>FAILED AGGRESSION + OPTIONS TELEMETRY</div>
        <div className={styles.monoLabel} style={{ color: 'var(--cyan)' }}>PARALLEL EVIDENCE [4 CHANNELS]</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px' }}>
        {displayRows.map((row) => (
          <div key={row.label} className={styles.pnlInnerTile}>
            <div className={styles.monoLabel} style={{ marginBottom: '4px' }}>{row.label}</div>
            <div className={styles.monoLabel} style={{ color: row.known ? 'var(--mint)' : 'var(--text-lo)', fontWeight: 700 }}>
              {row.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
})
