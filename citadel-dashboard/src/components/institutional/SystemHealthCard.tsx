import type { HTMLAttributes, ReactNode } from 'react'

import { Card, Row, Typography } from '@/design-system'
import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { IdentifiedItem, InstitutionalTone, StatefulProps } from './types'

export interface SystemHealthItem extends IdentifiedItem { label: ReactNode; value: ReactNode; tone?: InstitutionalTone }
export interface SystemHealthCardProps extends Omit<HTMLAttributes<HTMLElement>, 'title'>, StatefulProps {
  title: ReactNode
  summary?: ReactNode
  items?: SystemHealthItem[]
  interactive?: boolean
}

export function SystemHealthCard({ title, summary, items = [], interactive = false, loading, empty, loadingLabel, emptyTitle, emptyDescription, className, ...props }: SystemHealthCardProps) {
  const state = renderState({ loading, empty: empty ?? items.length === 0, loadingLabel, emptyTitle, emptyDescription })
  return <Card as="article" variant="default" interactive={interactive} tabIndex={interactive ? 0 : undefined} {...props} className={classNames(styles.healthCard, interactive && styles.interactive, className)}><div className={styles.healthHeader}><Typography as="h3" variant="sectionTitle">{title}</Typography>{summary}</div>{state ?? <div className={styles.healthList}>{items.map((item) => <Row density="compact" justify="between" divided key={item.id}><Typography variant="caption" tone="muted">{item.label}</Typography><Typography variant="body" tone={item.tone ?? 'neutral'} mono>{item.value}</Typography></Row>)}</div>}</Card>
}
