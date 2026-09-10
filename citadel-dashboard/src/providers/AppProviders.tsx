'use client'

import { useMemo, type ReactNode } from 'react'
import { usePathname } from 'next/navigation'
import { DashboardProvider } from '@/dashboard'
import { RestDashboardProvider } from '@/dashboard/providers/RestDashboardProvider'
import { ThemeProvider } from './ThemeProvider'

export function AppProviders({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const oracleRoute = pathname === '/oracle'
  const provider = useMemo(
    () => new RestDashboardProvider(oracleRoute),
    [oracleRoute],
  )
  return (
    <ThemeProvider>
      <DashboardProvider key={oracleRoute ? 'oracle-fast' : 'dashboard'} provider={provider}>
        {children}
      </DashboardProvider>
    </ThemeProvider>
  )
}
