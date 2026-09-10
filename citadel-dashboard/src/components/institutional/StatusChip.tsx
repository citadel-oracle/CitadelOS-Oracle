import type { ComponentProps } from 'react'

import { StatusChip as DesignStatusChip } from '@/design-system'
import { classNames, toneClass } from './shared'
import styles from './institutional.module.css'
import type { InstitutionalTone, StatefulProps } from './types'

export interface StatusChipProps extends Omit<ComponentProps<typeof DesignStatusChip>, 'tone'>, StatefulProps {
  tone?: InstitutionalTone
}

export function StatusChip({ tone = 'neutral', loading, empty, loadingLabel = 'Loading', emptyTitle = '—', className, children, ...props }: StatusChipProps) {
  const content = loading ? loadingLabel : empty ? emptyTitle : children
  return <DesignStatusChip {...props} tone={tone} className={classNames(styles.statusChip, toneClass[tone], className)}>{content}</DesignStatusChip>
}
