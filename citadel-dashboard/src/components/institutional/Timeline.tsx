import type { HTMLAttributes, ReactNode } from 'react'

import { Row } from '@/design-system'
import { classNames, renderState, toneClass } from './shared'
import styles from './institutional.module.css'
import type { IdentifiedItem, InstitutionalTone, StatefulProps } from './types'

export interface TimelineItem extends IdentifiedItem {
  time: ReactNode
  label: ReactNode
  meta?: ReactNode
  result?: ReactNode
  tone?: InstitutionalTone
}

export interface TimelineProps extends HTMLAttributes<HTMLDivElement>, StatefulProps {
  items?: TimelineItem[]
  interactive?: boolean
  onItemActivate?: (item: TimelineItem) => void
}

export function Timeline({ items = [], interactive = false, onItemActivate, loading, empty, loadingLabel, emptyTitle, emptyDescription, className, ...props }: TimelineProps) {
  const state = renderState({ loading, empty: empty ?? items.length === 0, loadingLabel, emptyTitle, emptyDescription })
  if (state) return <div {...props} className={classNames(styles.timeline, className)}>{state}</div>
  return <div {...props} className={classNames(styles.timeline, className)}>{items.map((item) => <Row as="article" density="default" key={item.id} interactive={interactive} tabIndex={interactive ? 0 : undefined} className={classNames(styles.timelineRow, toneClass[item.tone ?? 'neutral'])} onClick={onItemActivate ? () => onItemActivate(item) : undefined} onKeyDown={onItemActivate ? (event) => { if (event.key === 'Enter' || event.key === ' ') onItemActivate(item) } : undefined}><time className={styles.timelineTime}>{item.time}</time><i className={styles.timelineMarker} /><strong className={styles.timelineLabel}>{item.label}</strong>{item.meta ? <span className={styles.timelineMeta}>{item.meta}</span> : null}{item.result ? <span className={styles.timelineMeta}>{item.result}</span> : null}</Row>)}</div>
}
