import type {
  ConnectionState, DashboardFeedKey, DashboardFeedMeta, DashboardFeedState,
  DashboardHealth, ForecastProjectionMeta, MarketSessionState,
  NotificationSeverity, PositionSide, RuntimeState,
} from '../types'

export interface HeaderModel { system: string; mode: string; strategy: string; lastUpdate: string; autoRefresh: boolean; refreshIntervalMs: number }
export interface MarketSessionModel { state: MarketSessionState; marketOpen: boolean; exchange: string; timezone: string; reason: string }
export interface DeploymentSummaryModel { deployed: number; running: number; healthy: number; openPositions: number }
export interface DeploymentModel { id: string; strategy: string; instrument: string; timeframe: string; status: RuntimeState; health: DashboardHealth; pnl: number; tradesToday: number; activationEnabled: boolean | null }
export interface PositionModel {
  id: string
  deploymentId: string
  instrument: string
  side: PositionSide
  entry: number
  current: number | null
  stop: number | null
  target: number | null
  quantity: number
  pnl: number | null
  openedAt: string
  heldSecurityId: string
  protectiveStop: number | null
  initialStop: number | null
  currentStop: number | null
  initialRiskPerUnit: number | null
  underlyingInitialStop: number | null
  underlyingCurrentStop: number | null
  trailingEnabled: boolean | null
  trailingActivationPrice: number | null
  trailingAnchor: number | null
  trailingDistance: number | null
  trailingStep: number | null
  lastStopUpdateTime: string | null
  riskSource: string | null
  riskSourceTimestamp: string | null
  strategyVersion: string | null
  riskRuleVersion: string | null
  riskStatus: string
}
export interface TimelineModel { id: string; deploymentId: string; event: string; timestamp: string; pnl?: number }
export interface JournalModel { id: string; deploymentId: string; signal: string; reason: string; timestamp: string; pnl?: number }
export interface PaperEngineModel { orders: number; fills: number; open: number; closed: number; rejected: number; cancelled: number; realizedPnl: number; unrealizedPnl: number }
export interface SystemHealthModel { backend: DashboardHealth; scheduler: DashboardHealth; projection: DashboardHealth; paperEngine: DashboardHealth }
export interface ConnectionModel { state: ConnectionState; lastUpdate: string; source: string }
export interface LatencyModel { currentMs: number; averageMs: number; maximumMs: number }
export interface RiskModel { usedPercent: number; exposure: number; dailyLimit: number; state: DashboardHealth }
export interface CapitalModel { initial: number; current: number; available: number; equity: number }
export interface ExposureModel { gross: number; net: number; openPositions: number }
export interface PerformanceModel { realizedPnl: number; unrealizedPnl: number; totalPnl: number; wins: number; losses: number; winRate: number }
export interface NotificationModel { id: string; severity: NotificationSeverity; message: string; timestamp: string; acknowledged: boolean }
export interface RuntimeStatusModel { manager: RuntimeState; scheduler: RuntimeState; processedCandles: number; duplicateSuppression: boolean }
export interface FooterModel { product: string; build: string; telemetry: string }
export interface PersonalOracleObservationModel {
  id: string
  version: number
  title: string
  summary: string
  category: string
  severity: string
  status: string
  confidence: number | null
  sampleSize: number
  affectedStrategyCount: number
  affectedStrategyIds: string[]
  strategyFamily: string
  actualImpact: number | null
  hypotheticalImpact: number | null
  firstDetectedAt: string | null
  lastUpdatedAt: string | null
  evidenceReferences: string[]
}
export interface PersonalOracleStrategyModel {
  id: string
  family: string
  symbol: string
  timeframe: string
  optionSide: string
  observedTrades: number
  status: string
}
export interface PersonalOracleTradeEvidenceModel {
  strategyId: string
  family: string
  symbol: string
  timeframe: string
  optionSide: string
  sourceId: string
  outcome: string
  realizedPnl: number | null
  classifications: string[]
  executionIntegrity: string
  exitedAt: string | null
}
export interface PersonalOracleModel {
  status: string
  health: string
  readiness: string
  generatedAt: string | null
  snapshotVersion: number
  executionInfluence: 0
  discoveredStrategies: number
  analysedStrategies: number
  observedTrades: number
  classifiedEvents: number
  newObservations: number
  lastAnalysedAt: string | null
  manualBehaviourStatus: string
  maturity: string
  freshness: { state: string; ageSeconds: number | null }
  ingestion: {
    mode: string
    label: string
    contextCaptured: boolean
    contextCompletenessPercentage: number
    missingContextFields: string[]
    sourceEventId: string | null
    latestOracleIngestTimestamp: string | null
    latestTradeTimestamp: string | null
    freshnessStatus: string
  }
  shadow: {
    status: string
    errorReason: string | null
    outcomeStatus: string
    latestSuccessfulEvaluation: string | null
    latest: null | {
      id: string
      classification: string
      confidenceBand: string
      generatedAt: string | null
      strategy: string | null
      setup: string | null
      timeframe: string | null
      reasonCodes: string[]
      contextCompletenessPercentage: number
      policySource: string
      cohortSampleSize: number
      cohortExpectancy: number | null
      cohortWinRate: number | null
    }
    scorecard: {
      prospectiveAdvisories: number
      completedOutcomes: number
      pendingAdvisories: number
      classificationDistribution: Record<string, number>
    }
  }
  hero: {
    discoveredStrategyCount: number
    needsAttentionCount: number
    activeObservationCount: number
    newObservationCount: number
    highestPriorityExecutionIssue: string | null
    highestImpactPerformanceLeak: string | null
    cooldownCompliancePercentage: number | null
    disciplineMetric: { label: string; percentage: number } | null
    todayFocus: { text: string; confidence: number | null; sampleSize: number }
  }
  observations: PersonalOracleObservationModel[]
  allObservations: PersonalOracleObservationModel[]
  todayFocus: { text: string; confidence: number | null; sampleSize: number }
  strategyStatus: { stable: number; improving: number; needsAttention: number; learning: number; insufficientData: number }
  strategyScope: PersonalOracleStrategyModel[]
  tradeEvidence: PersonalOracleTradeEvidenceModel[]
  evidence: {
    coverage: Record<string, unknown>
    performance: Record<string, unknown>
    behavior: Record<string, unknown>
    behavioralFindings: Array<Record<string, unknown>>
    coaching: Record<string, unknown>
    scorecard: Record<string, unknown>
    trends: Record<string, unknown>
    limitations: string[]
    maturity: string
    observationCount: number
  }
}

export interface DashboardSections {
  header: HeaderModel
  marketSession: MarketSessionModel
  deploymentSummary: DeploymentSummaryModel
  activeDeployments: DeploymentModel[]
  activePositions: PositionModel[]
  executionTimeline: TimelineModel[]
  latestJournal: JournalModel[]
  paperEngineSummary: PaperEngineModel
  systemHealth: SystemHealthModel
  connectionStatus: ConnectionModel
  latency: LatencyModel
  risk: RiskModel
  capital: CapitalModel
  exposure: ExposureModel
  performance: PerformanceModel
  notifications: NotificationModel[]
  runtimeStatus: RuntimeStatusModel
  footer: FooterModel
}

export interface DashboardState {
  feeds: Record<DashboardFeedKey, DashboardFeedState>
  feedMeta: Partial<Record<DashboardFeedKey, DashboardFeedMeta>>
  forecastProjectionMeta: { kronosAlpha: ForecastProjectionMeta; chronos2: ForecastProjectionMeta } | null
  sections: DashboardSections
  selectedSymbol: string
  isRefreshing: boolean
  revision: number
}
