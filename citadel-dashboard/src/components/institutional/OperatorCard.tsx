import type { HTMLAttributes, ReactNode } from 'react'

import { Card, Typography } from '@/design-system'
import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { StatefulProps } from './types'

export interface OperatorCardProps extends Omit<HTMLAttributes<HTMLElement>, 'title'>, StatefulProps {
  title: ReactNode
  eyebrow?: ReactNode
  status?: ReactNode
  footer?: ReactNode
  interactive?: boolean
}

export function OperatorCard({ title, eyebrow, status, footer, interactive = false, loading, empty, loadingLabel, emptyTitle, emptyDescription, className, children, ...props }: OperatorCardProps) {
  const state = renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription })
  return <Card as="article" variant="default" interactive={interactive} tabIndex={interactive ? 0 : undefined} {...props} className={classNames(styles.operatorCard, interactive && styles.interactive, className)}><div className={styles.operatorHeader}><div>{eyebrow ? <Typography variant="caption" tone="brand">{eyebrow}</Typography> : null}<Typography as="h3" variant="sectionTitle">{title}</Typography></div>{status}</div><div className={styles.operatorBody}>{state ?? children}</div>{footer ? <footer className={styles.operatorFooter}>{footer}</footer> : null}</Card>
}
