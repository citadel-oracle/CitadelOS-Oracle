import type { DashboardState } from '../models/entities'
import type { DashboardFeedKey } from '../types'

export type DashboardSelector<T> = (state: DashboardState) => T

function memoized<T>(project: DashboardSelector<T>): DashboardSelector<T> {
  let previousState: DashboardState | undefined
  let previousValue: T
  return (state) => {
    if (state !== previousState) {
      previousState = state
      previousValue = project(state)
    }
    return previousValue
  }
}

export const selectFeed = <T>(key: DashboardFeedKey): DashboardSelector<DashboardState['feeds'][DashboardFeedKey] & { data: T | null }> =>
  memoized((state) => state.feeds[key] as DashboardState['feeds'][DashboardFeedKey] & { data: T | null })

export const feedSelectors = {
  mission: selectFeed<unknown>('mission'), matrix: selectFeed<unknown>('matrix'), trade: selectFeed<unknown>('trade'), performance: selectFeed<unknown>('performance'),
  kronos: selectFeed<unknown>('kronos'), kronosAlpha: selectFeed<unknown>('kronos_alpha'), chronos2: selectFeed<unknown>('chronos2'), oracle: selectFeed<unknown>('oracle'),
  athena: selectFeed<unknown>('athena'), hermes: selectFeed<unknown>('hermes'), insights: selectFeed<unknown>('insights'), argus: selectFeed<unknown>('argus'),
  riskStatus: selectFeed<unknown>('risk_status'), killSwitch: selectFeed<unknown>('kill_switch'), paperStatus: selectFeed<unknown>('paper_status'), personalOracle: selectFeed<unknown>('personal_oracle'),
  aegis: selectFeed<unknown>('aegis'), readiness: selectFeed<unknown>('readiness'), nextSessionPlan: selectFeed<unknown>('next_session_plan'), orderLedger: selectFeed<unknown>('order_ledger'),
  paperTrading: selectFeed<unknown>('paper_trading'), development: selectFeed<unknown>('development'), strategyLab: selectFeed<unknown>('strategy_lab'),
  comparison: selectFeed<unknown>('comparison'),
  strategies: selectFeed<unknown>('strategies'),
  eyeOracleProjection: selectFeed<unknown>('eye_oracle_projection'),
  orderFlow: selectFeed<unknown>('order_flow'),
  futuresChart: selectFeed<unknown>('futures_chart'),
  fusionShadow: selectFeed<unknown>('fusion_shadow'),
  optionsStructure: selectFeed<unknown>('options_structure'),
  vobReversal: selectFeed<unknown>('vob_reversal'),
  optionBuyerIntelligence: selectFeed<unknown>('option_buyer_intelligence'),
  marketInfo: selectFeed<unknown>('market_info'),
} as const


export const selectHeader = memoized((state: DashboardState) => state.sections.header)
export const selectMarketSession = memoized((state: DashboardState) => state.sections.marketSession)
export const selectDeploymentSummary = memoized((state: DashboardState) => state.sections.deploymentSummary)
export const selectActiveDeployments = memoized((state: DashboardState) => state.sections.activeDeployments)
export const selectActivePositions = memoized((state: DashboardState) => state.sections.activePositions)
export const selectExecutionTimeline = memoized((state: DashboardState) => state.sections.executionTimeline)
export const selectLatestJournal = memoized((state: DashboardState) => state.sections.latestJournal)
export const selectPaperEngineSummary = memoized((state: DashboardState) => state.sections.paperEngineSummary)
export const selectSystemHealth = memoized((state: DashboardState) => state.sections.systemHealth)
export const selectConnectionStatus = memoized((state: DashboardState) => state.sections.connectionStatus)
export const selectLatency = memoized((state: DashboardState) => state.sections.latency)
export const selectRisk = memoized((state: DashboardState) => state.sections.risk)
export const selectCapital = memoized((state: DashboardState) => state.sections.capital)
export const selectExposure = memoized((state: DashboardState) => state.sections.exposure)
export const selectPerformance = memoized((state: DashboardState) => state.sections.performance)
export const selectNotifications = memoized((state: DashboardState) => state.sections.notifications)
export const selectRuntimeStatus = memoized((state: DashboardState) => state.sections.runtimeStatus)
export const selectFooter = memoized((state: DashboardState) => state.sections.footer)
export const selectFeedMeta = memoized((state: DashboardState) => state.feedMeta)
export const selectForecastProjectionMeta = memoized((state: DashboardState) => state.forecastProjectionMeta)
export const selectSelectedSymbol = memoized((state: DashboardState) => state.selectedSymbol)
export const selectIsRefreshing = memoized((state: DashboardState) => state.isRefreshing)
export const selectFastLaneRevision = memoized((state: DashboardState) => state.sourceRevision)
