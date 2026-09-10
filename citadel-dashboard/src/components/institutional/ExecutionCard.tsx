import type { HTMLAttributes, ReactNode } from 'react'

import { Card, Typography } from '@/design-system'
import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { StatefulProps } from './types'

export interface ExecutionCardProps extends Omit<HTMLAttributes<HTMLElement>, 'title'>, StatefulProps {
  title: ReactNode
  subtitle?: ReactNode
  status?: ReactNode
  summary?: ReactNode
  actions?: ReactNode
  interactive?: boolean
}

export function ExecutionCard({ title, subtitle, status, summary, actions, interactive = false, loading, empty, loadingLabel, emptyTitle, emptyDescription, className, children, ...props }: ExecutionCardProps) {
  const state = renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription })
  return <Card as="article" variant="default" interactive={interactive} tabIndex={interactive ? 0 : undefined} {...props} className={classNames(styles.executionCard, interactive && styles.interactive, className)}><div className={styles.executionHeader}><div><Typography as="h3" variant="sectionTitle">{title}</Typography>{subtitle ? <Typography variant="caption" tone="muted">{subtitle}</Typography> : null}</div>{status}</div><div className={styles.executionBody}>{state ?? <>{summary}{children}</>}</div>{actions ? <footer className={styles.operatorFooter}>{actions}</footer> : null}</Card>
}
