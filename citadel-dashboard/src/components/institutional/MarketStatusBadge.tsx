import type { ComponentProps } from 'react'

import { Badge } from '@/design-system'
import { classNames, toneClass } from './shared'
import styles from './institutional.module.css'
import type { InstitutionalTone, StatefulProps } from './types'

export interface MarketStatusBadgeProps extends Omit<ComponentProps<typeof Badge>, 'tone'>, StatefulProps {
  tone?: InstitutionalTone
}

export function MarketStatusBadge({ tone = 'neutral', loading, empty, loadingLabel = 'Loading', emptyTitle = '—', className, children, ...props }: MarketStatusBadgeProps) {
  const content = loading ? loadingLabel : empty ? emptyTitle : children
  return <Badge {...props} tone={tone} dot className={classNames(styles.marketBadge, toneClass[tone], className)}>{content}</Badge>
}
