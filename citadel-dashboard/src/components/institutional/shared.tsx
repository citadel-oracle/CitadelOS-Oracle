import type { ReactNode } from 'react'

import styles from './institutional.module.css'
import type { InstitutionalTone, StatefulProps } from './types'

export function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(' ')
}

export const toneClass: Record<InstitutionalTone, string> = {
  neutral: styles.neutral,
  brand: styles.brand,
  positive: styles.positive,
  negative: styles.negative,
  info: styles.info,
  warning: styles.warning,
}

export function LoadingBlock({ label = 'Loading' }: { label?: ReactNode }) {
  return <div className={styles.loadingState} role="status" aria-live="polite"><span className={styles.loadingBar} /><span className={styles.loadingBarShort} /><small>{label}</small></div>
}

export function EmptyBlock({ title = 'No data', description }: { title?: ReactNode; description?: ReactNode }) {
  return <div className={styles.emptyState} role="status"><strong>{title}</strong>{description ? <small>{description}</small> : null}</div>
}

export function renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription }: StatefulProps): ReactNode | null {
  if (loading) return <LoadingBlock label={loadingLabel} />
  if (empty) return <EmptyBlock title={emptyTitle} description={emptyDescription} />
  return null
}
