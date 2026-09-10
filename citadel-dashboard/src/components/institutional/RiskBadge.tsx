import type { ComponentProps } from 'react'

import { Badge } from '@/design-system'
import { classNames, toneClass } from './shared'
import styles from './institutional.module.css'
import type { InstitutionalTone, StatefulProps } from './types'

export interface RiskBadgeProps extends Omit<ComponentProps<typeof Badge>, 'tone'>, StatefulProps {
  tone?: InstitutionalTone
}

export function RiskBadge({ tone = 'warning', loading, empty, loadingLabel = 'Loading', emptyTitle = '—', className, children, ...props }: RiskBadgeProps) {
  const content = loading ? loadingLabel : empty ? emptyTitle : children
  return <Badge {...props} tone={tone} className={classNames(styles.riskBadge, toneClass[tone], className)}>{content}</Badge>
}
