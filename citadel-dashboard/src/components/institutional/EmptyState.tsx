import type { HTMLAttributes, ReactNode } from 'react'

import { EmptyBlock, LoadingBlock } from './shared'

export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: ReactNode
  description?: ReactNode
  loading?: boolean
  empty?: boolean
}

export function EmptyState({ title, description, loading, empty, ...props }: EmptyStateProps) {
  if (loading) return <div {...props}><LoadingBlock /></div>
  if (empty === false) return null
  return <div {...props}><EmptyBlock title={title} description={description} /></div>
}
