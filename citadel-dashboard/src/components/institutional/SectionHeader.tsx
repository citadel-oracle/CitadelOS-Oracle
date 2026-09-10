import type { ComponentProps } from 'react'

import { SectionHeader as DesignSectionHeader } from '@/design-system'
import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { StatefulProps } from './types'

export interface SectionHeaderProps extends ComponentProps<typeof DesignSectionHeader>, StatefulProps {}

export function SectionHeader({ loading, empty, loadingLabel, emptyTitle, emptyDescription, aside, className, ...props }: SectionHeaderProps) {
  const state = renderState({ loading, empty, loadingLabel, emptyTitle, emptyDescription })
  return <DesignSectionHeader {...props} aside={state ?? aside} className={classNames(styles.sectionHeader, className)} />
}
