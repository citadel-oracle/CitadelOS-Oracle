'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'

export interface PhotonicMarketStoryStripProps {
  story?: string[]
  turnStrength?: number | null
}

export const PhotonicMarketStoryStrip = memo(function PhotonicMarketStoryStrip({
  story = ['WAITING FOR CANONICAL EVIDENCE SIGNALS'],
}: PhotonicMarketStoryStripProps) {
  const storyText = story.join(' → ')

  return (
    <div
      className={styles.card}
      style={{
        gridColumn: '1 / -1',
        padding: '10px 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(255, 30, 75, 0.015)',
        borderColor: 'var(--line-dim)',
      }}
      aria-label="Market Story Strip"
    >
      <div className={styles.monoLabel} style={{ color: 'var(--algory-red)' }}>
        MARKET STORY
      </div>
      <div style={{ flex: 1, textAlign: 'center', fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '0.15em', color: 'var(--text-white)' }}>
        // {storyText} //
      </div>
      <div className={styles.monoLabel} style={{ color: 'var(--mint)' }}>
        STATUS: ACTIVE SCAN
      </div>
    </div>
  )
})
