import type { HTMLAttributes, ReactNode } from 'react'

import { classNames, renderState, toneClass } from './shared'
import styles from './institutional.module.css'
import type { InstitutionalTone, StatefulProps } from './types'

export interface ConfidenceBarProps extends HTMLAttributes<HTMLDivElement>, StatefulProps {
  value: number
  label?: ReactNode
  valueLabel?: ReactNode
  tone?: InstitutionalTone
}

export function ConfidenceBar({ value, label = 'Confidence', valueLabel, tone = 'brand', loading, empty, loadingLabel, emptyTitle, emptyDescription, className, ...props }: ConfidenceBarProps) {
  const state = renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription })
  if (state) return <div {...props} className={classNames(styles.confidence, className)}>{state}</div>
  const bounded = Math.min(100, Math.max(0, value))
  return <div {...props} className={classNames(styles.confidence, toneClass[tone], className)}><div className={styles.confidenceHeader}><span>{label}</span><strong>{valueLabel ?? `${bounded}%`}</strong></div><div className={styles.confidenceTrack}><span className={styles.confidenceFill} style={{ width: `${bounded}%` }} /></div></div>
}
