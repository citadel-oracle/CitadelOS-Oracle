'use client'

import { useSyncExternalStore } from 'react'
import { useDashboardStore } from '../contexts/DashboardContext'
import type { DashboardSelector } from '../selectors'

export function useDashboardSelector<T>(selector: DashboardSelector<T>): T {
  const store = useDashboardStore()
  return useSyncExternalStore(store.subscribe, () => selector(store.getSnapshot()), () => selector(store.getSnapshot()))
}

export function useDashboardActions() {
  const store = useDashboardStore()
  return { setSymbol: (symbol: string) => store.setSymbol(symbol), refresh: () => store.refresh() }
}
