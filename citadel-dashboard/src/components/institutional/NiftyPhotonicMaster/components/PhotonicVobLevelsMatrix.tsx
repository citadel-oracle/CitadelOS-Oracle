'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import type { OracleVobLevel } from '@/dashboard/store/oracleStore'
import {
  formatRange,
  formatTime,
  UNKNOWN,
} from '../photonicPresentationHelpers'

export interface PhotonicVobLevelsMatrixProps {
  levels?: readonly OracleVobLevel[]
  episodeId?: string | null
}

export const PhotonicVobLevelsMatrix = memo(function PhotonicVobLevelsMatrix({
  levels = [],
  episodeId = null,
}: PhotonicVobLevelsMatrixProps) {
  const defaultLevels: OracleVobLevel[] = [
    { timeframe: '1M', zoneBottom: null, zoneTop: null, state: 'NOT REPORTED', touchAt: null, role: 'UNKNOWN', primary: false, sourceLineage: [], reportedSource: null, alignment: 'UNKNOWN', episodeId: null },
    { timeframe: '3M', zoneBottom: null, zoneTop: null, state: 'NOT REPORTED', touchAt: null, role: 'UNKNOWN', primary: false, sourceLineage: [], reportedSource: null, alignment: 'UNKNOWN', episodeId: null },
    { timeframe: '5M', zoneBottom: null, zoneTop: null, state: 'NOT REPORTED', touchAt: null, role: 'UNKNOWN', primary: false, sourceLineage: [], reportedSource: null, alignment: 'UNKNOWN', episodeId: null },
  ]

  const displayLevels = levels.length > 0 ? levels : defaultLevels

  return (
    <div
      className={styles.card}
      style={{ gridColumn: 'span 2' }}
      aria-label="VOB Key Levels Alignment Matrix"
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '10px' }}>
        <div className={styles.monoLabel} style={{ color: 'var(--cyan)' }}>VOB LEVELS MATRIX</div>
        <div className={styles.monoLabel}>{episodeId ? `EPISODE ${episodeId.slice(-8)} · CANONICAL` : 'CANONICAL EPISODE MATRIX'}</div>
      </div>

      <div style={{ display: 'grid', gap: '6px' }}>
        {displayLevels.map((lvl) => {
          const isAmber = lvl.primary || lvl.timeframe === '5M'
          const hasData = lvl.zoneBottom !== null && lvl.zoneTop !== null
          return (
            <div
              key={lvl.timeframe}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '6px 12px',
                border: isAmber && hasData ? '1px solid var(--amber-glow)' : '1px solid var(--line-dim)',
                borderRadius: '6px',
                background: isAmber && hasData ? 'rgba(255, 184, 0, 0.05)' : 'rgba(0,0,0,0.3)',
                boxShadow: isAmber && hasData ? '0 0 15px rgba(255,184,0,0.1)' : 'none',
              }}
              className={styles.monoLabel}
            >
              <span style={{ color: isAmber && hasData ? 'var(--amber)' : 'var(--cyan)', fontWeight: 700 }}>
                {lvl.timeframe} VOB
              </span>
              <span style={{ color: isAmber && hasData ? 'var(--amber)' : hasData ? '#fff' : 'var(--text-lo)', fontWeight: 700 }}>
                {formatRange(lvl.zoneBottom, lvl.zoneTop)}
              </span>
              <span style={{ color: hasData ? 'var(--mint)' : 'var(--text-lo)', fontWeight: isAmber && hasData ? 700 : 400 }}>
                {lvl.state}
              </span>
              <span>{formatTime(lvl.touchAt)}</span>
              <span style={{ color: isAmber && hasData ? 'var(--amber)' : hasData ? 'var(--mint)' : 'var(--text-lo)', fontWeight: isAmber && hasData ? 700 : 400 }}>
                {lvl.role}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
})
