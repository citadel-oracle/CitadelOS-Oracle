import type { ComponentProps } from 'react'

import { Card, MetricCard as DesignMetricCard } from '@/design-system'
import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { StatefulProps } from './types'

export interface MetricCardProps extends ComponentProps<typeof DesignMetricCard>, StatefulProps {}

export function MetricCard({ loading, empty, loadingLabel, emptyTitle, emptyDescription, className, label, value, detail, ...props }: MetricCardProps) {
  const state = renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription })
  if (state) return <Card as="article" variant="metric" className={classNames(styles.surface, className)}>{state}</Card>
  return <DesignMetricCard {...props} label={label} value={value} detail={detail} className={classNames(styles.surface, className)} />
}
