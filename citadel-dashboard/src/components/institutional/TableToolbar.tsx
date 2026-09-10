import type { HTMLAttributes, ReactNode } from 'react'

import { Typography } from '@/design-system'
import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { StatefulProps } from './types'

export interface TableToolbarProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'>, StatefulProps {
  title: ReactNode
  meta?: ReactNode
  actions?: ReactNode
  leading?: ReactNode
}

export function TableToolbar({ title, meta, actions, leading, loading, empty, loadingLabel, emptyTitle, emptyDescription, className, children, ...props }: TableToolbarProps) {
  const state = renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription })
  return <div {...props} className={classNames(styles.tableToolbar, className)}>{leading}<div className={styles.tableToolbarTitle}><Typography variant="body">{title}</Typography>{meta ? <span className={styles.toolbarMeta}>{meta}</span> : null}</div>{state ?? children}{actions ? <div className={styles.toolbarActions}>{actions}</div> : null}</div>
}
