import type { HTMLAttributes, ReactNode } from 'react'

import { Card, Typography } from '@/design-system'
import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { IdentifiedItem, StatefulProps } from './types'

export interface InfoPanelItem extends IdentifiedItem { label: ReactNode; value: ReactNode }
export interface InfoPanelProps extends Omit<HTMLAttributes<HTMLElement>, 'title'>, StatefulProps {
  title: ReactNode
  aside?: ReactNode
  items?: InfoPanelItem[]
  interactive?: boolean
}

export function InfoPanel({ title, aside, items = [], interactive = false, loading, empty, loadingLabel, emptyTitle, emptyDescription, className, children, ...props }: InfoPanelProps) {
  const state = renderState({ loading, empty: empty ?? (!children && items.length === 0), loadingLabel, emptyTitle, emptyDescription })
  return <Card as="section" variant="default" interactive={interactive} tabIndex={interactive ? 0 : undefined} {...props} className={classNames(styles.infoPanel, interactive && styles.interactive, className)}><div className={styles.infoHeader}><Typography as="h3" variant="sectionTitle">{title}</Typography>{aside}</div>{state ?? <><div className={styles.infoGrid}>{items.map((item) => <div className={styles.infoItem} key={item.id}><span>{item.label}</span><strong>{item.value}</strong></div>)}</div>{children}</>}</Card>
}
