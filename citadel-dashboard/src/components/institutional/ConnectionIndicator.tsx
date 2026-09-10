import type { HTMLAttributes, ReactNode } from 'react'

import { classNames, renderState, toneClass } from './shared'
import styles from './institutional.module.css'
import type { InstitutionalTone, StatefulProps } from './types'

export interface ConnectionIndicatorProps extends HTMLAttributes<HTMLDivElement>, StatefulProps {
  label: ReactNode
  detail?: ReactNode
  tone?: InstitutionalTone
}

export function ConnectionIndicator({ label, detail, tone = 'neutral', loading, empty, loadingLabel, emptyTitle, emptyDescription, className, ...props }: ConnectionIndicatorProps) {
  const state = renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription })
  if (state) return <div {...props} className={classNames(styles.connection, className)}>{state}</div>
  return <div {...props} className={classNames(styles.connection, toneClass[tone], className)}><i className={styles.connectionDot} /><span className={styles.connectionCopy}><strong>{label}</strong>{detail ? <small>{detail}</small> : null}</span></div>
}
