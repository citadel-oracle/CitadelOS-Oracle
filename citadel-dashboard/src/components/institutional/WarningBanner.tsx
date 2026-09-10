import type { HTMLAttributes, ReactNode } from 'react'

import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { StatefulProps } from './types'

export interface WarningBannerProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'>, StatefulProps {
  title: ReactNode
  message?: ReactNode
  actions?: ReactNode
  severity?: 'warning' | 'negative'
}

export function WarningBanner({ title, message, actions, severity = 'warning', loading, empty, loadingLabel, emptyTitle, emptyDescription, className, ...props }: WarningBannerProps) {
  const state = renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription })
  return <div {...props} className={classNames(styles.warningBanner, severity === 'negative' && styles.negative, className)} role="alert">{state ?? <><div className={styles.warningCopy}><strong>{title}</strong>{message ? <small>{message}</small> : null}</div>{actions ? <div className={styles.bannerActions}>{actions}</div> : null}</>}</div>
}
