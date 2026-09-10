import type { HTMLAttributes, ReactNode } from 'react'

import { EmptyBlock, LoadingBlock } from './shared'

export interface LoadingStateProps extends HTMLAttributes<HTMLDivElement> {
  label?: ReactNode
  loading?: boolean
  empty?: boolean
}

export function LoadingState({ label, loading, empty, ...props }: LoadingStateProps) {
  if (empty) return <div {...props}><EmptyBlock /></div>
  if (loading === false) return null
  return <div {...props}><LoadingBlock label={label} /></div>
}
