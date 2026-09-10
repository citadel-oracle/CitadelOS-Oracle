'use client'

import { OracleWorkspacePanel } from '@/components/institutional'
import {
  feedSelectors,
  selectFeedMeta,
  useDashboardSelector,
} from '@/dashboard'
import type {
  DashboardFeedState,
  OracleAssessmentData,
} from '@/dashboard/types'

import styles from './oracle.module.css'
import { useOracleMissionRuntime } from './useOracleMissionRuntime'

export default function OracleWorkspace() {
  const oracle = useDashboardSelector(feedSelectors.oracle) as DashboardFeedState<OracleAssessmentData>
  const argus = useDashboardSelector(feedSelectors.argus) as DashboardFeedState<unknown>
  const riskStatus = useDashboardSelector(feedSelectors.riskStatus) as DashboardFeedState<unknown>
  const paperStatus = useDashboardSelector(feedSelectors.paperStatus) as DashboardFeedState<unknown>
  const strategyLab = useDashboardSelector(feedSelectors.strategyLab) as DashboardFeedState<unknown>
  const strategies = useDashboardSelector(feedSelectors.strategies) as DashboardFeedState<unknown>
  const eyeOracleProjection = useDashboardSelector(feedSelectors.eyeOracleProjection) as DashboardFeedState<unknown>
  const futuresChart = useDashboardSelector(feedSelectors.futuresChart) as DashboardFeedState<unknown>
  const fusionShadow = useDashboardSelector(feedSelectors.fusionShadow) as DashboardFeedState<unknown>
  const optionsStructure = useDashboardSelector(feedSelectors.optionsStructure) as DashboardFeedState<unknown>
  const feedMeta = useDashboardSelector(selectFeedMeta)
  const missionRuntime = useOracleMissionRuntime(oracle.data?.symbol ?? null)

  return (
    <main className={styles.workspace} aria-label="CITADEL Oracle Workspace">
      <OracleWorkspacePanel
        oracle={oracle}
        argus={argus}
        riskStatus={riskStatus}
        paperStatus={paperStatus}
        strategyLab={strategyLab}
        strategies={strategies}
        eyeOracleProjection={eyeOracleProjection}
        futuresChart={futuresChart}
        fusionShadow={fusionShadow}
        optionsStructure={optionsStructure}
        oracleMeta={feedMeta.oracle}
        missionRuntime={missionRuntime}
      />
    </main>
  )

}
