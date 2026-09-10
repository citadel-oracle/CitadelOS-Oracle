import type { ComponentProps, ReactNode } from 'react'

import { Badge } from '@/design-system'
import { classNames, toneClass } from './shared'
import styles from './institutional.module.css'
import type { InstitutionalTone, StatefulProps } from './types'

export interface LatencyBadgeProps extends Omit<ComponentProps<typeof Badge>, 'tone'>, StatefulProps {
  value: ReactNode
  label?: ReactNode
  tone?: InstitutionalTone
}

export function LatencyBadge({ value, label = 'Latency', tone = 'neutral', loading, empty, loadingLabel = 'Loading', emptyTitle = '—', className, ...props }: LatencyBadgeProps) {
  const content = loading ? loadingLabel : empty ? emptyTitle : <>{label} · {value}</>
  return <Badge {...props} tone={tone} className={classNames(styles.latencyBadge, toneClass[tone], className)}>{content}</Badge>
}
