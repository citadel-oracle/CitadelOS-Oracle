import { DEFAULT_CAPITAL, DEFAULT_EXCHANGE, DEFAULT_TIMEZONE, MOCK_EMISSION_INTERVAL_MS } from '../constants/index'
import type {
  DashboardSections,
  DashboardState,
  PersonalOracleModel,
  PersonalOracleObservationModel,
  PersonalOracleStrategyModel,
  PersonalOracleTradeEvidenceModel,
} from '../models/entities'
import { dashboardSourceSnapshotSchema } from '../schemas/dashboard'
import { DASHBOARD_FEED_KEYS, type DashboardSourceSnapshot } from '../types'

const object = (value: unknown): Record<string, unknown> => typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const number = (value: unknown, fallback = 0) => typeof value === 'number' && Number.isFinite(value) ? value : fallback
const string = (value: unknown, fallback = '') => typeof value === 'string' ? value : fallback
const nullableNumber = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : null
const nullableString = (value: unknown) => typeof value === 'string' && value.length > 0 ? value : null
const adaptObservation = (item: unknown): PersonalOracleObservationModel => {
  const row = object(item)
  return {
    id: string(row.observation_id),
    version: number(row.version, 1),
    title: string(row.title, 'Observation'),
    summary: string(row.summary),
    category: string(row.category, 'INSUFFICIENT_DATA'),
    severity: string(row.severity, 'INFORMATIONAL'),
    status: string(row.status, 'ACTIVE'),
    confidence: nullableNumber(row.confidence),
    sampleSize: number(row.sample_size),
    affectedStrategyCount: number(row.affected_strategy_count),
    affectedStrategyIds: list(row.affected_strategy_ids).map((entry) => string(entry)).filter(Boolean),
    strategyFamily: string(row.strategy_family, 'NOT_RECORDED'),
    actualImpact: nullableNumber(row.actual_realized_impact),
    hypotheticalImpact: nullableNumber(row.hypothetical_impact),
    firstDetectedAt: nullableString(row.first_detected_at),
    lastUpdatedAt: nullableString(row.last_updated_at),
    evidenceReferences: list(row.evidence_references).map((entry) => string(entry)).filter(Boolean),
  }
}

const adaptPersonalOracle = (value: unknown): PersonalOracleModel => {
  const source = object(value)
  const scope = object(source.scope)
  const insights = object(source.insights)
  const behavior = object(source.behavior)
  const freshness = object(source.freshness)
  const ingestion = object(source.ingestion)
  const shadow = object(source.shadow)
  const shadowLatest = object(shadow.latest_advisory)
  const shadowMetrics = object(shadowLatest.personal_metrics)
  const shadowCohort = object(shadowMetrics.strategy_setup)
  const shadowScorecard = object(shadow.prospective_scorecard)
  const shadowDistribution = object(shadowScorecard.classification_distribution)
  const evidence = object(source.evidence)
  const hero = object(source.hero)
  const discipline = object(hero.discipline_metric)
  const legacyBehavior = object(evidence.behavior)
  const statuses = object(source.strategy_status_counts)
  const focus = object(hero.today_focus)
  const legacyFocus = object(insights.today_focus)
  const observations = list(insights.top_observations).slice(0, 3).map(adaptObservation)
  const allObservations = list(evidence.observations).map(adaptObservation)
  const strategyScope: PersonalOracleStrategyModel[] = list(evidence.strategy_scope).map((item) => {
    const row = object(item)
    return {
      id: string(row.strategy_id),
      family: string(row.strategy_family, 'NOT_RECORDED'),
      symbol: string(row.symbol, 'NOT_RECORDED'),
      timeframe: string(row.timeframe, 'NOT_RECORDED'),
      optionSide: string(row.option_side, 'NOT_RECORDED'),
      observedTrades: number(row.observed_trade_count),
      status: string(row.status, 'INSUFFICIENT_DATA'),
    }
  })
  const tradeEvidence: PersonalOracleTradeEvidenceModel[] = list(evidence.trade_evidence).map((item) => {
    const row = object(item)
    return {
      strategyId: string(row.strategy_id, 'NOT_RECORDED'),
      family: string(row.strategy_family, 'NOT_RECORDED'),
      symbol: string(row.symbol, 'NOT_RECORDED'),
      timeframe: string(row.timeframe, 'NOT_RECORDED'),
      optionSide: string(row.option_side, 'NOT_RECORDED'),
      sourceId: string(row.source_record_id),
      outcome: string(row.outcome, 'NOT_REPORTED'),
      realizedPnl: nullableNumber(row.realized_pnl),
      classifications: list(row.classifications).map((entry) => string(entry)).filter(Boolean),
      executionIntegrity: string(row.execution_integrity, 'NOT_REPORTED'),
      exitedAt: nullableString(row.exit_at),
    }
  })
  return {
    status: string(source.status, 'UNAVAILABLE'),
    health: string(source.health, 'UNAVAILABLE'),
    readiness: string(source.readiness, 'UNAVAILABLE'),
    generatedAt: nullableString(source.generated_at),
    snapshotVersion: number(source.snapshot_version),
    executionInfluence: 0,
    discoveredStrategies: number(scope.discovered_strategy_count),
    analysedStrategies: number(scope.analysed_strategy_count),
    observedTrades: number(scope.observed_trade_count, number(source.sample_size)),
    classifiedEvents: number(scope.classified_event_count),
    newObservations: number(insights.new_observation_count),
    lastAnalysedAt: nullableString(source.last_event_at) ?? nullableString(behavior.latest_update) ?? nullableString(legacyBehavior.latest_update),
    manualBehaviourStatus: string(behavior.manual_behaviour_status, 'NOT_RECORDED'),
    maturity: string(source.maturity, string(evidence.maturity, 'COLLECTING')),
    freshness: {
      state: string(freshness.state, 'UNAVAILABLE'),
      ageSeconds: nullableNumber(freshness.age_seconds),
    },
    ingestion: {
      mode: string(ingestion.mode, 'LEGACY'),
      label: string(ingestion.label, 'STARTUP-ONLY'),
      contextCaptured: ingestion.context_captured === true,
      contextCompletenessPercentage: number(ingestion.context_completeness_percentage),
      missingContextFields: list(ingestion.missing_context_fields).map((entry) => string(entry)).filter(Boolean),
      sourceEventId: nullableString(ingestion.source_event_id),
      latestOracleIngestTimestamp: nullableString(ingestion.latest_oracle_ingest_timestamp),
      latestTradeTimestamp: nullableString(ingestion.latest_trade_timestamp),
      freshnessStatus: string(ingestion.freshness_status, 'NO_DATA'),
    },
    shadow: {
      status: string(shadow.status, 'COLLECTING'),
      errorReason: nullableString(shadow.error_reason),
      outcomeStatus: string(shadow.latest_outcome_status, 'NO_DATA'),
      latestSuccessfulEvaluation: nullableString(shadow.latest_successful_shadow_evaluation),
      latest: Object.keys(shadowLatest).length ? {
        id: string(shadowLatest.advisory_id),
        classification: string(shadowLatest.classification, 'INSUFFICIENT_DATA'),
        confidenceBand: string(shadowLatest.confidence_band, 'UNCALIBRATED'),
        generatedAt: nullableString(shadowLatest.generated_at),
        strategy: nullableString(shadowLatest.strategy),
        setup: nullableString(shadowLatest.setup),
        timeframe: nullableString(shadowLatest.timeframe),
        reasonCodes: list(shadowLatest.reason_codes).slice(0, 4).map((entry) => string(entry)).filter(Boolean),
        contextCompletenessPercentage: number(shadowLatest.context_completeness_percentage),
        policySource: string(shadowLatest.policy_source, 'POLICY_DEFAULT'),
        cohortSampleSize: number(shadowLatest.cohort_sample_size),
        cohortExpectancy: nullableNumber(shadowCohort.expectancy),
        cohortWinRate: nullableNumber(shadowCohort.win_rate),
      } : null,
      scorecard: {
        prospectiveAdvisories: number(shadowScorecard.total_prospective_advisories),
        completedOutcomes: number(shadowScorecard.completed_outcomes),
        pendingAdvisories: number(shadowScorecard.pending_advisories),
        classificationDistribution: Object.fromEntries(
          Object.entries(shadowDistribution).map(([key, value]) => [key, number(value)])
        ),
      },
    },
    hero: {
      discoveredStrategyCount: number(hero.discovered_strategy_count, number(scope.discovered_strategy_count)),
      needsAttentionCount: number(hero.needs_attention_count, number(statuses.needs_attention)),
      activeObservationCount: number(hero.active_observation_count, allObservations.filter((row) => row.status !== 'RESOLVED').length),
      newObservationCount: number(hero.new_observation_count, number(insights.new_observation_count)),
      highestPriorityExecutionIssue: nullableString(hero.highest_priority_execution_issue),
      highestImpactPerformanceLeak: nullableString(hero.highest_impact_performance_leak),
      cooldownCompliancePercentage: nullableNumber(hero.cooldown_compliance_percentage),
      disciplineMetric: typeof discipline.percentage === 'number' && Number.isFinite(discipline.percentage)
        ? { label: string(discipline.label, 'Discipline'), percentage: discipline.percentage }
        : null,
      todayFocus: {
        text: string(focus.text, string(legacyFocus.text, 'Insufficient evidence—continue collecting completed trades.')),
        confidence: nullableNumber(focus.confidence) ?? nullableNumber(legacyFocus.confidence),
        sampleSize: number(focus.sample_size, number(legacyFocus.sample_size)),
      },
    },
    observations,
    allObservations,
    todayFocus: {
      text: string(focus.text, string(legacyFocus.text, 'Insufficient evidence—continue collecting completed trades.')),
      confidence: nullableNumber(focus.confidence) ?? nullableNumber(legacyFocus.confidence),
      sampleSize: number(focus.sample_size, number(legacyFocus.sample_size)),
    },
    strategyStatus: {
      stable: number(statuses.stable),
      improving: number(statuses.improving),
      needsAttention: number(statuses.needs_attention),
      learning: number(statuses.learning),
      insufficientData: number(statuses.insufficient_data),
    },
    strategyScope,
    tradeEvidence,
    evidence: {
      coverage: object(evidence.coverage),
      performance: object(evidence.performance),
      behavior: legacyBehavior,
      behavioralFindings: list(evidence.behavioral_findings).map(object),
      coaching: object(evidence.coaching),
      scorecard: object(evidence.scorecard),
      trends: object(evidence.trends),
      limitations: list(evidence.limitations).map((entry) => string(entry)).filter(Boolean),
      maturity: string(evidence.maturity, 'COLLECTING'),
      observationCount: number(evidence.observation_count, allObservations.length),
    },
  }
}

export class DashboardDataAdapter {
  private sourceFeedReferences: Partial<Record<(typeof DASHBOARD_FEED_KEYS)[number], unknown>> = {}

  toState(snapshot: DashboardSourceSnapshot, previous?: DashboardState): DashboardState {
    dashboardSourceSnapshotSchema.parse(snapshot)
    const strategyLab = object(snapshot.feeds.strategy_lab)
    const mission = object(snapshot.feeds.mission)
    const system = object(mission.system)
    const session = object(system.session)
    const portfolio = object(strategyLab.portfolio)
    const execution = object(strategyLab.execution)
    const status = object(strategyLab.status)
    const strategies = list(strategyLab.strategies).map(object)
    const authoritative = list(execution.authoritative_open_positions).map(object)
    const positions = authoritative.length ? authoritative : list(execution.positions).map(object)
    const activePositions = positions.filter((item) => string(item.status, 'OPEN').toUpperCase() === 'OPEN')
    const closedTrades = list(execution.closed_trades).map(object)
    const journal = list(object(strategyLab.review).journal).map(object)
    const timeline = list(execution.timeline).map(object)
    const openPnl = number(portfolio.open_pnl)
    const closedPnl = number(portfolio.closed_pnl)
    const projectionHealth = snapshot.feedMeta.strategy_lab?.health.toUpperCase() ?? 'UNKNOWN'
    const backendHealth = ['HEALTHY', 'LIVE', 'READY'].includes(projectionHealth) ? 'healthy' : projectionHealth === 'STALE' ? 'degraded' : 'offline'
    const connectionState = backendHealth === 'healthy' ? 'connected' : backendHealth === 'degraded' ? 'stale' : 'offline'
    const sections: DashboardSections = {
      header: { system: string(system.system, 'ONLINE'), mode: string(system.mode, 'paper'), strategy: string(system.strategy, 'Simple Pullback'), lastUpdate: snapshot.generatedAt, autoRefresh: true, refreshIntervalMs: MOCK_EMISSION_INTERVAL_MS },
      marketSession: { state: string(session.state, 'open').toLowerCase() as DashboardSections['marketSession']['state'], marketOpen: session.market_open === true, exchange: DEFAULT_EXCHANGE, timezone: DEFAULT_TIMEZONE, reason: string(session.reason) },
      deploymentSummary: { deployed: number(status.deployment_count), running: number(status.running_strategy_count), healthy: strategies.filter((item) => item.health === 'HEALTHY').length, openPositions: activePositions.length },
      activeDeployments: strategies.map((item) => ({ id: string(item.strategy_id), strategy: string(object(item.metadata).name), instrument: string(item.strategy_id).includes('_PE_') ? 'NIFTY PE' : 'NIFTY CE', timeframe: string(list(object(item.metadata).supported_timeframes)[0], '3m'), status: string(item.state, 'waiting').toLowerCase() as 'running' | 'waiting' | 'stopped' | 'error', health: item.health === 'HEALTHY' ? 'healthy' : 'degraded', pnl: number(object(item.statistics).net_pnl), tradesToday: number(item.today_trades), activationEnabled: typeof object(item.scheduler).activation_enabled === 'boolean' ? object(item.scheduler).activation_enabled as boolean : null })),
      activePositions: activePositions.map((item) => ({
        id: string(item.position_id),
        deploymentId: string(item.strategy_id),
        instrument: string(item.contract, string(item.instrument, 'NIFTY')),
        side: string(item.side, 'BUY') as 'BUY' | 'SELL',
        entry: number(item.entry_price, number(item.entry)),
        current: nullableNumber(item.current_price),
        stop: nullableNumber(item.current_stop ?? item.stop),
        target: nullableNumber(item.target),
        quantity: number(item.quantity),
        pnl: item.pnl_valid === false ? null : number(item.pnl, number(item.unrealized_pnl)),
        openedAt: string(item.entry_time, snapshot.generatedAt),
        heldSecurityId: string(item.held_security_id, string(item.contract)),
        protectiveStop: nullableNumber(item.protective_stop),
        initialStop: nullableNumber(item.initial_stop),
        currentStop: nullableNumber(item.current_stop),
        initialRiskPerUnit: nullableNumber(item.initial_risk_per_unit),
        underlyingInitialStop: nullableNumber(item.underlying_initial_stop),
        underlyingCurrentStop: nullableNumber(item.underlying_current_stop),
        trailingEnabled: typeof item.trailing_enabled === 'boolean' ? item.trailing_enabled : null,
        trailingActivationPrice: nullableNumber(item.trailing_activation_price),
        trailingAnchor: nullableNumber(item.trailing_anchor),
        trailingDistance: nullableNumber(item.trailing_distance),
        trailingStep: nullableNumber(item.trailing_step),
        lastStopUpdateTime: typeof item.last_stop_update_time === 'string' ? item.last_stop_update_time : null,
        riskSource: typeof item.risk_source === 'string' ? item.risk_source : null,
        riskSourceTimestamp: typeof item.risk_source_timestamp === 'string' ? item.risk_source_timestamp : null,
        strategyVersion: typeof item.strategy_version === 'string' ? item.strategy_version : null,
        riskRuleVersion: typeof item.risk_rule_version === 'string' ? item.risk_rule_version : null,
        riskStatus: string(item.risk_status, 'NOT_REPORTED'),
      })),
      executionTimeline: timeline.map((item, index) => ({ id: string(item.record_id, `timeline-${index}`), deploymentId: string(item.strategy_id), event: string(item.event_type), timestamp: string(item.recorded_at, snapshot.generatedAt), pnl: number(object(item.payload).realized_pnl, number(object(item.payload).pnl)) })),
      latestJournal: journal.map((item, index) => ({ id: string(item.record_id, `journal-${index}`), deploymentId: string(item.strategy_id), signal: string(object(item.payload).signal, string(item.event_type)), reason: string(object(item.payload).reason), timestamp: string(item.recorded_at, snapshot.generatedAt), pnl: number(object(item.payload).realized_pnl) })),
      paperEngineSummary: { orders: number(execution.order_count), fills: number(execution.fill_count), open: activePositions.length, closed: number(execution.closed_trade_count), rejected: number(object(execution.order_counts).REJECTED), cancelled: number(object(execution.order_counts).CANCELLED), realizedPnl: closedPnl, unrealizedPnl: openPnl },
      systemHealth: { backend: backendHealth, scheduler: strategies.every((item) => object(item.scheduler).state === 'RUNNING') ? 'healthy' : 'degraded', projection: backendHealth, paperEngine: object(snapshot.feeds.paper_status).status === 'healthy' ? 'healthy' : 'degraded' },
      connectionStatus: { state: connectionState, lastUpdate: snapshot.generatedAt, source: snapshot.provider },
      latency: { currentMs: number(snapshot.feedMeta.strategy_lab.latency_ms), averageMs: number(snapshot.feedMeta.strategy_lab.latency_ms), maximumMs: Math.max(...Object.values(snapshot.feedMeta).map((meta) => meta.latency_ms)) },
      risk: { usedPercent: number(portfolio.risk_usage), exposure: number(portfolio.exposure), dailyLimit: 5000, state: 'healthy' },
      capital: { initial: number(portfolio.initial_capital, DEFAULT_CAPITAL), current: number(portfolio.current_capital, DEFAULT_CAPITAL), available: number(portfolio.available_capital, DEFAULT_CAPITAL), equity: number(portfolio.total_equity, DEFAULT_CAPITAL) },
      exposure: { gross: number(portfolio.exposure), net: number(portfolio.exposure), openPositions: activePositions.length },
      performance: { realizedPnl: closedPnl, unrealizedPnl: openPnl, totalPnl: number(portfolio.total_pnl, closedPnl + openPnl), wins: closedTrades.filter((item) => number(item.realized_pnl) > 0).length, losses: closedTrades.filter((item) => number(item.realized_pnl) < 0).length, winRate: number(portfolio.win_rate) },
      notifications: [],
      runtimeStatus: { manager: status.manager_started === true ? 'running' : 'stopped', scheduler: strategies.every((item) => object(item.scheduler).state === 'RUNNING') ? 'running' : 'waiting', processedCandles: strategies.reduce((sum, item) => sum + number(object(item.scheduler).tick_count), 0), duplicateSuppression: true },
      footer: { product: 'CITADEL OS / LIVE DASHBOARD MVP', build: 'Legacy Build • Vihaann', telemetry: 'Read-only telemetry · No order controls exposed' },
    }
    const updated = new Date(snapshot.generatedAt)
    const feedError = (key: (typeof DASHBOARD_FEED_KEYS)[number]) => {
      const health = snapshot.feedMeta[key]?.health.toUpperCase()
      return ['OFFLINE', 'UNAVAILABLE', 'ERROR'].includes(health) ? 'Backend projection unavailable' : health === 'STALE' ? 'Backend projection stale' : null
    }
    const feeds = Object.fromEntries(DASHBOARD_FEED_KEYS.map((key) => {
      const sourceValue = snapshot.feeds[key]
      const error = feedError(key)
      const prior = previous?.feeds[key]
      if (prior && this.sourceFeedReferences[key] === sourceValue && prior.error === error) {
        return [key, prior]
      }
      this.sourceFeedReferences[key] = sourceValue
      return [key, {
        data: key === 'personal_oracle' ? adaptPersonalOracle(sourceValue) : sourceValue,
        error,
        lastUpdated: updated,
        loading: false,
      }]
    })) as DashboardState['feeds']
    return {
      feeds,
      feedMeta: snapshot.feedMeta,
      forecastProjectionMeta: {
        kronosAlpha: { traceId: snapshot.traceId, publishedAt: snapshot.generatedAt, observedAt: snapshot.generatedAt, sourceLastUpdated: snapshot.feedMeta.kronos_alpha.source_last_updated },
        chronos2: { traceId: snapshot.traceId, publishedAt: snapshot.generatedAt, observedAt: snapshot.generatedAt, sourceLastUpdated: snapshot.feedMeta.chronos2.source_last_updated },
      },
      sections, selectedSymbol: snapshot.selectedSymbol, isRefreshing: false, revision: (previous?.revision ?? 0) + 1,
    }
  }
}
