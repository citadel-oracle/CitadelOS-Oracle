import type { HTMLAttributes, ReactNode } from 'react'

import { Typography } from '@/design-system'
import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { StatefulProps } from './types'

export interface ModuleHeaderProps extends Omit<HTMLAttributes<HTMLElement>, 'title'>, StatefulProps {
  title: ReactNode
  eyebrow?: ReactNode
  meta?: ReactNode
  status?: ReactNode
  actions?: ReactNode
}

export function ModuleHeader({ title, eyebrow, meta, status, actions, loading, empty, loadingLabel, emptyTitle, emptyDescription, className, ...props }: ModuleHeaderProps) {
  const state = renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription })
  return <header {...props} className={classNames(styles.moduleHeader, className)}><div className={styles.moduleTitle}>{eyebrow ? <Typography variant="caption" tone="brand">{eyebrow}</Typography> : null}<Typography as="h3" variant="sectionTitle">{title}</Typography>{meta ? <span className={styles.moduleMeta}>{meta}</span> : null}</div>{state ?? status}{actions ? <div className={styles.moduleActions}>{actions}</div> : null}</header>
}
