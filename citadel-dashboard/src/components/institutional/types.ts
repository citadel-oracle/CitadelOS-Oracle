import type { ReactNode } from 'react'

import type { CitadelDensity, CitadelTone } from '@/design-system'

export type InstitutionalTone = CitadelTone
export type InstitutionalDensity = CitadelDensity

export interface StatefulProps {
  loading?: boolean
  empty?: boolean
  loadingLabel?: ReactNode
  emptyTitle?: ReactNode
  emptyDescription?: ReactNode
}

export interface IdentifiedItem {
  id: string
}
