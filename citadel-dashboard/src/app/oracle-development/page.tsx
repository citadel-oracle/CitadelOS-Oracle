'use client'

import { useState, Suspense, useEffect } from 'react'
import { useSearchParams } from 'next/navigation'
import { useDashboardSelector, feedSelectors, selectFeedMeta } from '@/dashboard'
import type { DashboardFeedState } from '@/dashboard/types'

import styles from '../oracle/oracle.module.css'
import { useOracleDevMissionRuntime } from './useOracleDevMissionRuntime'
import { OracleDevWorkspacePanel } from '@/components/institutional/OracleDevWorkspacePanel'

function OracleDevelopmentWorkspaceContent() {
  const searchParams = useSearchParams()
  const laneParam = searchParams.get('lane') as '1m' | '3m' | '5m' | null
  const expandParam = searchParams.get('expand') === 'true'
  const layersParam = searchParams.get('layers')?.split(',') || null
  const selectedTradeParam = searchParams.get('selectedTrade') || null
  const staleParam = searchParams.get('stale') === 'true'

  const zoomParam = searchParams.get('zoom') ? parseInt(searchParams.get('zoom') || '100') : null
  const scrollParam = searchParams.get('scroll') ? parseInt(searchParams.get('scroll') || '0') : null
  const insufficientParam = searchParams.get('insufficient') === 'true'
  const rawHover = searchParams.get('hover')
  const hoverParam = rawHover === 'auto' ? 'auto' : (rawHover ? parseInt(rawHover) : null)

  const [selectedLane, setSelectedLane] = useState<'1m' | '3m' | '5m'>('3m')

  useEffect(() => {
    if (laneParam) {
      const timer = setTimeout(() => {
        setSelectedLane(laneParam)
      }, 0)
      return () => clearTimeout(timer)
    }
  }, [laneParam])

  const riskStatus = useDashboardSelector(feedSelectors.riskStatus) as DashboardFeedState<unknown>
  const paperStatus = useDashboardSelector(feedSelectors.paperStatus) as DashboardFeedState<unknown>
  const feedMeta = useDashboardSelector(selectFeedMeta)
  const devRuntime = useOracleDevMissionRuntime('NIFTY', selectedLane)

  return (
    <main className={styles.workspace} aria-label="CITADEL Oracle Development Workspace">
      <OracleDevWorkspacePanel
        devRuntime={devRuntime}
        riskStatus={riskStatus}
        paperStatus={paperStatus}
        oracleMeta={feedMeta.oracle}
        selectedLane={selectedLane}
        setSelectedLane={setSelectedLane}
        overrideExpand={expandParam}
        overrideLayers={layersParam}
        overrideSelectedTradeId={selectedTradeParam}
        forceStale={staleParam}
        overrideZoom={zoomParam}
        overrideScroll={scrollParam}
        forceInsufficient={insufficientParam}
        overrideHoverIndex={hoverParam}
      />
    </main>
  )
}

export default function OracleDevelopmentWorkspace() {
  return (
    <Suspense fallback={<div style={{ padding: '20px', color: '#22d3ee', fontFamily: 'monospace' }}>HYDRATING WORKSPACE SYSTEM...</div>}>
      <OracleDevelopmentWorkspaceContent />
    </Suspense>
  )
}
