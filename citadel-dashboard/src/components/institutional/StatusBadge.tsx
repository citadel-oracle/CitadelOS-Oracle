import type { ComponentProps } from 'react'

import { Badge } from '@/design-system'
import { classNames, toneClass } from './shared'
import styles from './institutional.module.css'
import type { InstitutionalTone, StatefulProps } from './types'

export interface StatusBadgeProps extends Omit<ComponentProps<typeof Badge>, 'tone'>, StatefulProps {
  tone?: InstitutionalTone
}

export function StatusBadge({ tone = 'neutral', loading, empty, loadingLabel = 'Loading', emptyTitle = '—', className, children, ...props }: StatusBadgeProps) {
  const content = loading ? loadingLabel : empty ? emptyTitle : children
  return <Badge {...props} tone={tone} dot className={classNames(styles.statusBadge, toneClass[tone], className)}>{content}</Badge>
}
