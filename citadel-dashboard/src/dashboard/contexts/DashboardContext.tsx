'use client'

import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { DashboardDataAdapter } from '../adapters/DashboardDataAdapter'
import type { DashboardDataProvider, DashboardRepository } from '../contracts'
import { MockDashboardProvider } from '../providers/MockDashboardProvider'
import { RestDashboardProvider } from '../providers/RestDashboardProvider'
import { InMemoryDashboardRepository } from '../repositories/InMemoryDashboardRepository'
import { DashboardStore } from '../store/DashboardStore'

const DashboardContext = createContext<DashboardStore | null>(null)

export function DashboardProvider({ children, provider, repository }: { children: ReactNode; provider?: DashboardDataProvider; repository?: DashboardRepository }) {
  const store = useMemo(() => {
    const configuredProvider = provider ?? (process.env.NEXT_PUBLIC_CITADEL_DATA_MODE === 'mock' ? new MockDashboardProvider() : new RestDashboardProvider())
    const selectedRepository = repository ?? new InMemoryDashboardRepository(configuredProvider)
    return new DashboardStore(selectedRepository, new DashboardDataAdapter())
  }, [provider, repository])
  useEffect(() => { store.start(); return () => store.stop() }, [store])
  return <DashboardContext.Provider value={store}>{children}</DashboardContext.Provider>
}

export function useDashboardStore() {
  const store = useContext(DashboardContext)
  if (!store) throw new Error('useDashboardStore must be used within DashboardProvider')
  return store
}
