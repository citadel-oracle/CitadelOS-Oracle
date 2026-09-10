import type { HTMLAttributes, ReactNode } from 'react'

import { Typography } from '@/design-system'
import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { StatefulProps } from './types'

export interface CommandBarProps extends Omit<HTMLAttributes<HTMLElement>, 'title'>, StatefulProps {
  title: ReactNode
  meta?: ReactNode
  actions?: ReactNode
  leading?: ReactNode
}

export function CommandBar({ title, meta, actions, leading, loading, empty, loadingLabel, emptyTitle, emptyDescription, className, children, ...props }: CommandBarProps) {
  const state = renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription })
  return <nav {...props} className={classNames(styles.commandBar, className)}>{leading}<div className={styles.commandTitle}><Typography variant="body">{title}</Typography>{meta ? <span className={styles.commandMeta}>{meta}</span> : null}</div>{state ?? children}{actions ? <div className={styles.commandActions}>{actions}</div> : null}</nav>
}
