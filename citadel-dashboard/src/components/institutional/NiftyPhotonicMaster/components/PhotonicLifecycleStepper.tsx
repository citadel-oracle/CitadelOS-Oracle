'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import { formatTime } from '../photonicPresentationHelpers'

export interface PhotonicLifecycleStepItem {
  label?: string
  name?: string
  state?: string
  active?: boolean
  done?: boolean
  time?: string | null
}

export interface PhotonicLifecycleStepperProps {
  steps?: readonly PhotonicLifecycleStepItem[] | PhotonicLifecycleStepItem[]
  activeState?: string
}

export const PhotonicLifecycleStepper = memo(function PhotonicLifecycleStepper({
  steps = [],
  activeState = 'TOUCHED',
}: PhotonicLifecycleStepperProps) {
  const defaultSteps: PhotonicLifecycleStepItem[] = [
    { label: 'VOB READY', state: 'complete', time: '15:25:00' },
    { label: 'APPROACHING', state: 'complete', time: '15:25:00' },
    { label: 'TOUCHED', state: 'complete', time: '15:25:30' },
    { label: 'WATCHING TURN', state: 'active', time: 'ACTIVE' },
    { label: 'REVERSAL BLDG', state: 'pending', time: '—' },
    { label: 'REVERSAL READY', state: 'pending', time: '—' },
    { label: 'TRADE LIVE', state: 'pending', time: '—' },
    { label: 'EXIT', state: 'pending', time: '—' },
  ]

  const rawSteps = steps.length > 0 ? steps : defaultSteps

  return (
    <div
      className={styles.card}
      style={{ gridColumn: '1 / -1' }}
      aria-label="Lifecycle Pipeline Progression 8-Node Connected Stepper"
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <div className={styles.monoLabel} style={{ color: 'var(--mint)', fontWeight: 700 }}>
          // LIFECYCLE PIPELINE PROGRESSION
        </div>
        <div className={styles.monoLabel}>
          BACKEND SEMANTIC STATE · 8-NODE DISCRETE STATE MACHINE
        </div>
      </div>

      <div className={styles.lifecycleStepper}>
        {rawSteps.map((step, idx) => {
          const stepName = step.label ?? step.name ?? `STEP ${idx + 1}`
          const isActive = step.active ?? step.state === 'active'
          const isDone = step.done ?? step.state === 'complete'

          const circleClass = isActive
            ? `${styles.nodeCircle} ${styles.active}`
            : isDone
            ? `${styles.nodeCircle} ${styles.done}`
            : styles.nodeCircle

          const displayTime = step.time ? (step.time === 'ACTIVE' || step.time === '—' ? step.time : formatTime(step.time)) : (isActive ? 'ACTIVE' : '—')

          return (
            <div key={stepName} className={styles.stepperNode}>
              <div className={circleClass}>{idx + 1}</div>
              <div className={styles.nodeTitle} style={{ color: isActive || isDone ? 'var(--mint)' : 'var(--text-mid)', fontWeight: isActive ? 800 : 700 }}>
                {stepName}
              </div>
              <div className={styles.nodeTime} style={{ color: isActive ? 'var(--mint)' : 'var(--text-lo)' }}>
                {displayTime}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
})
