'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import type { ResearchSlice } from '@/dashboard/store/oracleStore'
import {
  formatR,
} from '../photonicPresentationHelpers'

export interface PhotonicScoreboardProps {
  research?: Partial<ResearchSlice> | null
  summaryText?: string
}

export const PhotonicScoreboard = memo(function PhotonicScoreboard({
  research = null,
  summaryText = 'WIN RATE · PROFIT FACTOR · MEDIAN R · MFE · MAE · WINNERS MISSED · LOSSES AVOIDED · CONFIRMATION DELAY · MAX DRAWDOWN — NOT REPORTED',
}: PhotonicScoreboardProps) {
  const vobAvgR = formatR(research?.vobAverageR ?? null)
  const confirmedAvgR = formatR(research?.confirmedAverageR ?? null)
  const expectancy = formatR(research?.expectancyDelta ?? null)
  const matchedVobs = research?.matchedVobs !== null && research?.matchedVobs !== undefined ? `${research.matchedVobs} MATCHED` : '—'
  const status = research?.status ?? 'NOT REPORTED'

  return (
    <div
      className={styles.card}
      style={{ gridColumn: '1 / -1', padding: '16px 24px' }}
      aria-label="Experiment Scoreboard"
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <div className={styles.monoLabel} style={{ color: 'var(--algory-red)', fontWeight: 700 }}>
          // EXPERIMENT SCOREBOARD
        </div>
        <div className={styles.monoLabel}>
          STATIC RESEARCH · MATCHED EPISODES · {status}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '12px' }}>
        <div style={{ background: 'rgba(255, 30, 75, 0.03)', padding: '10px', borderRadius: '8px', border: '1px solid var(--line-dim)' }}>
          <div className={styles.monoLabel} style={{ marginBottom: '4px' }}>VOB AVG R</div>
          <div className={styles.title} style={{ fontSize: '18px', color: 'var(--text-white)' }}>
            {vobAvgR}
          </div>
        </div>
        <div style={{ background: 'rgba(255, 30, 75, 0.03)', padding: '10px', borderRadius: '8px', border: '1px solid var(--line-dim)' }}>
          <div className={styles.monoLabel} style={{ marginBottom: '4px' }}>CONFIRMED AVG R</div>
          <div className={styles.title} style={{ fontSize: '18px', color: 'var(--cyan)' }}>
            {confirmedAvgR}
          </div>
        </div>
        <div style={{ background: 'rgba(255, 30, 75, 0.03)', padding: '10px', borderRadius: '8px', border: '1px solid var(--line-dim)' }}>
          <div className={styles.monoLabel} style={{ marginBottom: '4px' }}>Δ EXPECTANCY</div>
          <div className={styles.title} style={{ fontSize: '18px', color: 'var(--mint)' }}>
            {expectancy}
          </div>
        </div>
        <div style={{ background: 'rgba(255, 30, 75, 0.03)', padding: '10px', borderRadius: '8px', border: '1px solid var(--line-dim)' }}>
          <div className={styles.monoLabel} style={{ marginBottom: '4px' }}>MATCHED VOBS</div>
          <div className={styles.title} style={{ fontSize: '18px', color: 'var(--text-white)' }}>
            {matchedVobs}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--line-dim)', paddingTop: '8px' }} className={styles.monoLabel}>
        <span>{summaryText}</span>
        <span style={{ color: 'var(--cyan)' }}>● CITADEL MASTER (PHOTONIC HEADER & CHROMATIC PLASMA)</span>
      </div>
    </div>
  )
})
