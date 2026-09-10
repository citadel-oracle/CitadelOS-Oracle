'use client'

import {
  Activity,
  BarChart3,
  BookOpen,
  Clock3,
  History,
  Target,
  TrendingDown,
  TrendingUp,
  WifiOff,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  Badge as DesignBadge,
  Card as DesignCard,
  DataTable as DesignTable,
  MetricCard as DesignMetricCard,
  SectionHeader as DesignSectionHeader,
  StatusChip as DesignStatusChip,
  TableCell as DesignTableCell,
  TableHeaderCell as DesignTableHeaderCell,
  TableRow as DesignTableRow,
} from '@/design-system'
import productionStyles from './production-mode.module.css'
import workspaceStyles from './trading-workspace.module.css'
import { SafetyStrip, ActionRequiredPanel, TodaysClosedTradesPanel, NiftyVOBPanel, OptionsStructurePanel, ArgusPrimePanel, ArgusEdgeLabPanel, PremiumIntelligenceCards, RiskIntelligenceShadowConsole, CitadelPrimaryNavigation, CitadelLuxuryHeroLayer, OptionBuyerDecisionDeck, UnifiedOptionBuyerCommandDeck } from '@/components/institutional'
import type { ArgusTacticalEdgeData } from '@/components/institutional'
import type { ArgusEdgeLabData, NiftyVOBData, TodaysClosedTradesData } from '@/components/institutional'
import { feedSelectors, selectFeedMeta, selectFooter, selectForecastProjectionMeta, selectHeader, selectIsRefreshing, selectSelectedSymbol, useDashboardActions, useDashboardSelector } from '@/dashboard'
import type { PersonalOracleModel, PersonalOracleObservationModel } from '@/dashboard/models/entities'
import { loadOracleAcknowledgements, oracleAcknowledgementKey, saveOracleAcknowledgement } from '@/dashboard/utils/oracleAcknowledgements'
import { safeArgusSnapshot, safeArgusStatus, safeBaselineLabel } from './argus-safety-helpers'

type SessionStatus = {
  market_open: boolean
  entry_allowed: boolean
  square_off: boolean
  state: string
  reason: string
  next_valid_open: string | null
  calendar_version: string | null
}

type PerformanceStats = {
  total_trades: number
  wins: number
  losses: number
  win_rate: number
  net_points: number
  profit_factor: number
  expectancy: number
  max_win_streak: number
  max_loss_streak: number
  verdict: string
  comment: string
}

type Trade = {
  trade_id: number
  symbol: string
  side: 'BUY' | 'SELL'
  entry: number
  sl: number
  initial_sl: number
  target: number
  confidence: number
  reason: string
  status: string
  ltp: number
  pnl_points: number
  r_multiple: number
  break_even_done: boolean
  trailing_active: boolean
  exit_reason: string | null
  opened_at: string
  closed_at: string | null
}

type MissionControl = {
  system: {
    system: string
    phase: string
    strategy: string
    mode: string | null
    broker: string | null
    live_trading_enabled: boolean | null
    session: SessionStatus
  }
  journal: {
    total_closed: number
    wins: number
    losses: number
    net_points: number
  }
  active_trade: Trade | null
  analytics: PerformanceStats
  optimizer: Array<{ priority: string; type: string; message: string }>
}

type MarketRow = {
  symbol: string
  ltp: number | null
  change_percent: number | null
  direction: string
  regime: string
  bias: string
  confidence: number
  strategy: string
  structure: string | null
  liquidity: string | null
  pullback_signal: string
}

type KronosGauge = {
  score: number | null
  label: string | null
  regime: string | null
  confidence: number | null
  trend: number | null
  momentum: number | null
  structure: number | null
  liquidity: number | null
}

type KronosAlphaStatus = {
  generated_at: string
  model_status: 'OFFLINE' | 'DOWNLOADING' | 'LOADING' | 'READY' | 'DEGRADED' | 'STALE' | 'ERROR' | 'UNAVAILABLE'
  mode: 'SHADOW'
  execution_influence_percentage: 0
  aegis_influence_percentage: 0
  model_name: string
  model_variant: string
  model_revision: string
  tokenizer_name: string
  tokenizer_revision: string
  device: string | null
  symbol: string
  timeframe: string
  input_candle_count: number | null
  context_limit: number
  forecast_horizon: number
  last_input_candle_at: string | null
  input_age_seconds: number | null
  last_inference_at: string | null
  inference_duration_ms: number | null
  cache_status: string
  readiness_state: string
  expected_direction: 'BULLISH' | 'BEARISH' | 'SIDEWAYS' | 'UNKNOWN'
  bullish_probability: number | null
  bearish_probability: number | null
  sideways_probability: number | null
  expected_return_percentage: number | null
  forecast_volatility: number | null
  volatility_label: string
  trend_persistence_probability: number | null
  reversal_probability: number | null
  forecast_uncertainty: number | null
  uncertainty_label: string
  forecast_dispersion: number | null
  expected_high: number | null
  expected_low: number | null
  upside_quantile: number | null
  downside_quantile: number | null
  horizon_candles: number
  horizon_minutes: number
  path_count: number | null
  reason_codes: string[]
  warnings: string[]
  missing_inputs: string[]
  maturity_label: 'EXPERIMENTAL_SHADOW'
  source_metadata: { source: string; fixture_data: boolean; external_refresh_on_read: false }
  scheduler_health: string
  next_expected_inference: string | null
  session: {
    exchange: string
    session_state: 'PRE_OPEN' | 'OPEN' | 'CLOSED' | 'WEEKEND' | 'HOLIDAY' | 'SPECIAL_SESSION' | 'UNKNOWN'
    market_open: boolean
    session_date: string
    reason: string
    next_valid_open: string | null
    calendar_source: string | null
    calendar_version: string | null
  } | null
  input_metadata: {
    health: string
    candle_count: number
    last_candle_at: string | null
    source: string
    volume_available: boolean | null
    instrument: { symbol: string; exchange: string; segment: string; security_id: string; instrument: string; timeframe: string }
  } | null
  outlooks: {
    ce: OptionOutlook
    pe: OptionOutlook
    forecast_quality_score: number | null
  }
  evaluation: {
    evaluated_forecasts: number
    directional_hit_rate: number | null
    average_forecast_error: number | null
    calibration_status: string
    sample_warning: string | null
  }
}

type Chronos2Quality = {
  score: number | null
  interpretation: string
  evidence_coverage: number
  freshness?: string
  missing_components: string[]
  label: string
  shadow: true
  recommendation: null
}

type Chronos2Status = {
  generated_at: string
  status: string
  freshness: string
  model_name: string
  model_revision: string
  package_version: string
  mode: 'UNIVARIATE' | 'MULTIVARIATE' | null
  symbol: string
  timeframe: string
  shadow_mode: true
  advisory_only: true
  execution_influence: 0
  aegis_direct_influence: 0
  prediction_length: number
  input_candle_count: number | null
  input_feature_count: number | null
  input_feature_names: string[]
  input_coverage: number | null
  forecast_id: string | null
  context_end: string | null
  median_terminal_move_points: number | null
  median_terminal_move_percentage: number | null
  forecast_low: number | null
  forecast_high: number | null
  terminal_p10: number | null
  terminal_p50: number | null
  terminal_p90: number | null
  device: string | null
  inference_duration_ms: number | null
  warnings: string[]
  next_eligible_session?: string | null
  model_readiness?: string
  input_readiness?: string
  runtime: {
    scheduler_health: string
    next_expected_inference: string | null
    session: { session_state: string; market_open: boolean; reason: string; next_valid_open: string | null }
    input_metadata: { health: string; candle_count: number; last_candle_at: string | null; source: string }
  }
  derived_analytics: {
    label: string
    directional_bias: string
    directional_confidence: number | null
    median_expected_move_points: number | null
    median_expected_move_percentage: number | null
    uncertainty: string
    trend_persistence: number | null
    upward_persistence: number | null
    downward_persistence: number | null
    reversal_risk: number | null
    forecast_quality: number | null
    ce_quality: Chronos2Quality
    pe_quality: Chronos2Quality
  }
}

type OptionOutlook = {
  side: 'CE' | 'PE'
  option_buying_quality_score: number | null
  recommendation_state: 'STRONG_ALIGNMENT' | 'MODERATE_ALIGNMENT' | 'WEAK_ALIGNMENT' | 'AVOID' | 'UNAVAILABLE'
  directional_probability: number | null
  persistence_probability: number | null
  reversal_risk: number | null
  sideways_probability: number | null
  opposite_probability: number | null
  forecast_volatility: number | null
  uncertainty: number | null
  expected_favorable_move: number | null
  label: 'OPTION_BUYING_QUALITY'
}

type OracleReasoning = {
  symbol: string
  timeframe: string
  generated_at: string
  market_data_as_of: string | null
  data_age_seconds: number | null
  data_status: 'LIVE' | 'CACHED' | 'STALE' | 'UNAVAILABLE'
  oracle_status: 'READY' | 'DEGRADED' | 'BLOCKED' | 'UNAVAILABLE'
  directional_bias: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
  signal: 'LONG' | 'SHORT' | 'WAIT' | 'NO_TRADE'
  confidence: number | null
  confidence_label: 'HIGH' | 'MODERATE' | 'LOW' | 'UNAVAILABLE'
  confidence_formula: string
  regime: 'TRENDING' | 'RANGING' | 'VOLATILE' | 'LOW_LIQUIDITY' | 'UNKNOWN'
  reason_codes: string[]
  reasoning: string
  input_features: {
    close: number | null
    ema_21: number | null
    ema_38: number | null
    vwap: number | null
    rsi_14: number | null
    adx_14: number | null
    atr_14: number | null
    price_trend: string
    vwap_relationship: string
    momentum: string
    volatility: string
    volume_status: string
    liquidity: string
    timeframe_bias: string
    scanner_bias: string
    scanner_signal: string
    session_status: string
  }
  warnings: string[]
  maturity_label: string
  source_metadata: {
    source: string
    fallback_used: boolean
    fallback_type: string
    snapshot_age_seconds: number | null
    timestamp_semantics: string
    oracle_broker_calls: boolean
  }
}

type AthenaWheel = {
  generated_at: string
  trading_date: string | null
  athena_status: 'READY' | 'DEGRADED' | 'BLOCKED' | 'UNAVAILABLE'
  risk_state: string
  recommendation: 'CONTINUE' | 'REDUCE' | 'PAUSE' | 'STOP'
  recommended_size_multiplier: number
  advisory_only: boolean
  daily_realized_pnl: number | null
  daily_unrealized_pnl: number | null
  total_daily_pnl: number | null
  daily_loss_limit: number | null
  daily_loss_used_percentage: number | null
  daily_loss_headroom: number | null
  trades_taken: number | null
  maximum_trades: number | null
  trade_usage_percentage: number | null
  consecutive_losses: number | null
  maximum_consecutive_losses: number | null
  loss_streak_usage_percentage: number | null
  open_positions: number | null
  maximum_open_positions: number | null
  exposure_usage_percentage: number | null
  exposure_acceptable: boolean | null
  current_drawdown: number | null
  maximum_allowed_drawdown: number | null
  available_capital: number | null
  blocked_capital: number | null
  current_equity: number | null
  risk_headroom_percentage: number | null
  reason_codes: string[]
  explanation: string
  warnings: string[]
  missing_inputs: string[]
  maturity_label: string
  source_metadata: {
    source: string
    advisory_only: boolean
    risk_authorization_final_veto: boolean
    risk_state_health: string
    paper_state_health: string
    live_trading_enabled: boolean | null
    latest_authorization_decision: string | null
    latest_authorization_reason_code: string | null
    exposure_basis: string | null
    capital_basis: string | null
    drawdown_basis: string | null
    risk_source_last_updated: string | null
    paper_source_last_updated: string | null
  }
}

type HermesEvent = {
  event_id: string
  headline: string
  summary: string
  event_type: string
  impact: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | 'UNKNOWN'
  sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | 'MIXED' | 'UNKNOWN'
  timing_state: 'UPCOMING' | 'IMMINENT' | 'LIVE' | 'RECENT' | 'EXPIRED' | 'UNKNOWN'
  scheduled_at: string | null
  published_at: string | null
  received_at: string | null
  age_seconds: number | null
  event_countdown_seconds: number | null
  source_name: string | null
  source_type: string
  source_confidence: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'
  source_url: string | null
  country: string | null
  market: string | null
  affected_indices: string[]
  affected_sectors: string[]
  affected_symbols: string[]
  currency: string | null
  commodity: string | null
  affects_global: boolean
  tags: string[]
  reason_codes: string[]
  warnings: string[]
  provider_name: string | null
  is_scheduled: boolean
  is_confirmed: boolean
  is_conflicting: boolean
  duplicate_group_id: string | null
  source_names: string[]
  source_count: number
}

type HermesStatus = {
  generated_at: string
  hermes_status: 'READY' | 'DEGRADED' | 'STALE' | 'UNAVAILABLE' | 'NOT_CONFIGURED' | 'BLOCKED'
  market_session_context: string | null
  overall_event_risk: 'NONE' | 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL' | 'UNKNOWN'
  recommendation: 'NORMAL' | 'CAUTION' | 'WAIT' | 'AVOID_NEW_TRADES'
  dominant_sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | 'MIXED' | 'UNKNOWN'
  imminent_event_count: number | null
  high_impact_event_count: number | null
  critical_event_count: number | null
  conflicting_event_count: number | null
  stale_event_count: number | null
  next_major_event: HermesEvent | null
  top_events: HermesEvent[]
  affected_markets: string[]
  affected_indices: string[]
  affected_sectors: string[]
  affected_symbols: string[]
  reason_codes: string[]
  human_readable_summary: string
  warnings: string[]
  missing_inputs: string[]
  maturity_label: string
  source_metadata: {
    provider_mode: string
    provider_name: string | null
    provider_configured: boolean
    advisory_only: boolean
    external_refresh_on_read: boolean
    fixture_data: boolean
    normalized_input_count: number
    rejected_input_count: number
    last_refresh_at: string | null
  }
  freshness_metadata: {
    snapshot_age_seconds: number | null
    stale_after_seconds: number
    freshest_event_age_seconds: number | null
    oldest_event_age_seconds: number | null
    timestamp_semantics: string
  }
}

type AIInsight = {
  source: string
  title: string
  message: string
  severity: string
  timestamp: string | null
}

type RiskStatus = {
  status: 'healthy' | 'degraded' | 'unavailable'
  state_health: 'HEALTHY' | 'DEGRADED' | 'UNAVAILABLE'
  live_trading_enabled: boolean | null
  kill_switch_active: boolean | null
  kill_switch_state: 'ACTIVE' | 'INACTIVE' | 'UNKNOWN' | 'CORRUPT'
  kill_switch_reason: string | null
  kill_switch_activated_at: string | null
  risk_state_available: boolean
  limits: {
    max_daily_loss: number | null
    max_trades_per_day: number | null
    max_consecutive_losses: number | null
    max_risk_per_trade: number | null
    max_raw_quantity: number | null
    max_open_positions: number | null
    max_market_data_age_seconds: number | null
    max_volatility: number | null
  }
  latest_authorization: {
    decision: string | null
    reason_code: string | null
    reason: string | null
    timestamp: string | null
  } | null
  error: { code: string; message: string } | null
  last_updated: string
}

type KillSwitchStatus = {
  enabled: boolean
  state: 'ACTIVE' | 'INACTIVE' | 'UNKNOWN' | 'CORRUPT'
  reason: string
  activated_at: string | null
  deactivated_at: string | null
  updated_at: string | null
  source: string
  schema_version: number
  persistence_health: 'HEALTHY' | 'MISSING' | 'CORRUPT'
  last_valid_state: string | null
  warnings: string[]
  status: 'healthy' | 'unavailable'
  warning: string | null
}

type ReadinessItem = {
  component: string
  status: 'READY' | 'READY_WITH_LIMITATIONS' | 'NOT_READY' | 'WAITING_FOR_MARKET' | 'BLOCKED'
  reason: string
  required_condition: string
  last_checked: string
  blocking: boolean
  warning: string | null
}

type OpenMarketReadiness = {
  status: ReadinessItem['status']
  generated_at: string
  items: ReadinessItem[]
  blocking_components: string[]
  advisory_only: boolean
  provider_refresh_triggered: boolean
  model_inference_triggered: boolean
  broker_call_triggered: boolean
}

type NextSessionPlan = {
  status: string
  expected_open: string | null
  first_candle_close: string | null
  grace_complete: string | null
  minimum_candle_count: number
  grace_seconds: number
  steps: { sequence: number; action: string; expected_at: string | null; observed: boolean }[]
  warnings: string[]
}

type PaperStatus = {
  status: 'healthy' | 'degraded' | 'unavailable'
  state_health: 'HEALTHY' | 'DEGRADED' | 'UNAVAILABLE'
  trading_date: string | null
  realized_pnl: number | null
  unrealized_pnl: number | null
  total_daily_pnl: number | null
  trades_taken_today: number | null
  consecutive_losses: number | null
  open_position_count: number | null
  accepted_request_count: number | null
  last_updated: string | null
  state_last_mutated_at: string | null
  projection_observed_at: string | null
  freshness_semantics: string
  error: { code: string; message: string } | null
}

type ArgusLeg = {
  ltp: number | null
  intraday_change_oi: number | null
  activity: string
  positioning: string
  oi: number | null
  volume: number | null
  iv: number | null
}

type ArgusStrike = {
  strike: number
  ce_moneyness: string
  pe_moneyness: string
  ce: ArgusLeg
  pe: ArgusLeg
}

type ArgusLevel = {
  strike: number
  value: number
} | null

type ArgusResponse = {
  status: 'available' | 'stale'
  freshness: 'fresh' | 'cached' | 'stale'
  cache: {
    hit: boolean
    age_seconds: number
    ttl_seconds: number
  }
  data: {
    underlying: {
      symbol: string
      security_id: number
      segment: string
      ltp: number | null
      expiry: string | null
      atm_strike: number | null
      fetched_at: string
      market_state: string
      session_name: string
      trading_date: string
      baseline_timestamp: string | null
      baseline_status: string
    }
    totals: {
      ce_oi: number | null
      pe_oi: number | null
      day_ce_change_oi: number | null
      day_pe_change_oi: number | null
      intraday_ce_change_oi: number | null
      intraday_pe_change_oi: number | null
      pcr: number | null
      day_change_pcr: number | null
      intraday_change_pcr: number | null
    }
    atm_window: ArgusStrike[]
    walls: {
      highest_ce_oi: ArgusLevel
      highest_pe_oi: ArgusLevel
      highest_intraday_ce_oi_addition: ArgusLevel
      highest_intraday_pe_oi_addition: ArgusLevel
      strongest_ce_unwind: ArgusLevel
      strongest_pe_unwind: ArgusLevel
    }
    dominance: {
      writer_dominance_percentage: number | null
      buyer_dominance_percentage: number | null
    }
    verdict: {
      regime: string
      bias: string
      preferred_option_side: 'CE' | 'PE' | 'NONE' | string
      confidence: number | null
      reasons: string[]
      call_wall: ArgusLevel
      put_wall: ArgusLevel
      breakout_above: number | null
      breakdown_below: number | null
      avoid_zone: { lower: number; upper: number } | null
    }
    provenance: {
      day_change_oi_basis: string
      intraday_change_oi_basis: string
      activity_basis: string
      minimum_price_change: number
      minimum_oi_change: number
    }
    missing_fields: string[]
    tactical_edge?: ArgusTacticalEdgeData | null
  }
}

type PersonalOracleSummary = PersonalOracleModel

type AegisDecision = {
  decision_id: string
  generated_at: string
  symbol: string
  timeframe: string
  strategy_id: string
  strategy_name: string
  requested_side: 'CE' | 'PE' | 'LONG' | 'SHORT' | 'NONE'
  decision: 'APPROVE' | 'APPROVE_REDUCED' | 'WAIT' | 'REJECT' | 'BLOCK'
  mode: 'ADVISORY'
  recommendation: 'NORMAL' | 'CAUTION' | 'PAUSE' | 'REJECT'
  would_recommend: 'NORMAL' | 'CAUTION' | 'PAUSE' | 'REJECT'
  recommendation_is_execution_decision: false
  execution_influence: 'ZERO'
  calculation_timestamp: string
  input_status: 'AVAILABLE' | 'STALE' | 'UNAVAILABLE'
  freshness: 'FRESH' | 'STALE' | 'UNAVAILABLE'
  stale_reason: string | null
  unavailable_reason: string | null
  decision_score: number | null
  decision_quality: string
  data_coverage_percentage: number
  hard_gate_status: string
  hard_gate_reasons: string[]
  hard_gate_details: Record<string, { state: string; reason: string }>
  component_scores: Record<string, number | null>
  weighted_contributions: Record<string, number | null>
  component_details: Record<string, { status: string | null; freshness: string | number | null; top_reason: string }>
  conflicts: Array<{ conflict_id: string; modules: string[]; description: string; severity: string; resolution: string; score_impact: number; reason_codes: string[] }>
  recommended_size_multiplier: number
  dominant_reasons: string[]
  warnings: string[]
  missing_inputs: string[]
  maturity: string
  advisory_only: true
  execution_permission: false
  risk_authorization_required: false
  live_trading_enabled: boolean | null
}

type OrderLedgerStatus = {
  status: 'READY' | 'UNAVAILABLE'
  health: string
  schema_version: number
  mode: 'AUDIT_ONLY'
  order_count: number | null
  active_order_count: number | null
  terminal_order_count: number | null
  fill_count: number | null
  execution_engine: 'NOT_ACTIVE'
  broker_submission: 'DISABLED'
  live_trading_enabled: false
  paper_state_mutation: false
  empty: boolean | null
  warnings: string[]
}

type PaperTradingDashboard = {
  generated_at: string
  status: {
    state: string
    reason: string
    updated_at: string | null
    mode: 'REAL_DATA_PAPER_ONLY'
    scheduler_running: boolean
    frontend_execution: false
    broker_submission: false
    live_trading_enabled: false
    symbols: ['NIFTY']
    maximum_lots: 1
    maximum_open_positions: 1
    maximum_trades_per_day: 2
    last_evaluated_candle: string | null
    last_signal: { signal: string; confidence: number | null; entry: number | null; sl: number | null; target: number | null; reason: string; strategy: string } | null
    last_aegis: { decision: string; decision_score: number | null; hard_gate_reasons: string[]; execution_permission: false } | null
    last_risk: { decision: string; reason_code: string; maximum_loss: number; lot_size: number } | null
    last_mark: { price: number; timestamp: string; source: string } | null
    strategy_registry: { active_count: number; maximum_strategies: number; strategies: Array<{ name: string; logic_modified: false }> }
  }
  readiness: { status: string; closed_candles_only: true; dhan_market_data: true; broker_submission: false; frontend_execution: false }
  position: { status: string; position: { symbol: string; option_type: string; strike: number; expiry: string; raw_quantity: number; lot_size: number; entry_price: number; mark_price: number; unrealized_pnl: number } | null }
  pnl: { status: string; realized_pnl: number | null; unrealized_pnl: number | null; total_daily_pnl: number | null; open_positions?: number; trades_taken?: number }
  timeline: { status: string; events: Array<{ timestamp: string; status: string; code: string; detail: string }> }
}

type DevelopmentModuleVote = { vote: string; score: number | null; direction: string | null; confidence: number | null }
type DevelopmentDecision = {
  decision_id: string
  decision: 'ALLOW' | 'WAIT' | 'BLOCK'
  weighted_score: number
  allow_threshold: number
  data_coverage_percentage: number
  module_votes: Record<string, DevelopmentModuleVote>
  module_contributions: Record<string, number | null>
  missing_optional_evidence: string[]
  hard_vetoes: string[]
  why_trade: string[]
  why_not_trade: string[]
  confidence: number
  generated_at: string
}
type DevelopmentDashboard = {
  generated_at: string
  status: {
    state: string
    reason: string
    updated_at: string | null
    mode: 'DEVELOPMENT_PAPER_ONLY'
    scheduler_running: boolean
    production_state_mutated: false
    production_aegis_used: false
    frontend_execution: false
    broker_submission: false
    live_trading_enabled: false
    strategy: 'Simple Pullback (Development)'
    timeframe: '5m'
    maximum_lots: number
    maximum_open_positions: number
    evidence_ceiling_per_day: 20
    last_signal: { signal: string; confidence: number | null; entry: number | null; sl: number | null; target: number | null; reason: string; strategy: string } | null
    last_decision: DevelopmentDecision | null
    last_risk: { decision: string; reason_code: string; maximum_loss: number; lot_size: number } | null
    weighted_policy: { weights: Record<string, number>; allow_threshold: number }
  }
  position: { status: string; position: { option_type: string; strike: number; expiry: string; raw_quantity: number; entry_price: number; mark_price: number; unrealized_pnl: number } | null }
  pnl: { status: string; realized_pnl: number | null; unrealized_pnl: number | null; total_daily_pnl: number | null; open_positions?: number; trades_taken?: number; closed_trades?: number }
  ledger: { status: string; health: string; order_count: number | null; fill_count: number | null; broker_submission: string; live_trading_enabled: false }
  timeline: { status: string; events: Array<{ timestamp: string; status: string; code: string; detail: string }> }
  evidence: { status: string; integrity: { valid: boolean; records?: number }; decision_count: number | null; closed_trade_evidence_count: number | null; recent_decisions: unknown[]; recent_trades: unknown[] }
  safety_labels: ['DEVELOPMENT PAPER TRADING', 'NOT USED FOR PRODUCTION', 'NOT USED FOR LIVE TRADING']
}

type StrategyLabStatistics = {
  completed_trades: number
  wins?: number
  losses?: number
  win_rate: number | null
  profit_factor: number | null
  expectancy: number | null
  rr: number | null
  mfe: number | null
  mae: number | null
  net_pnl: number
  drawdown: number
  sharpe: number | null
  average_hold_time?: number | null
  consecutive_wins?: number | null
  consecutive_losses?: number | null
  daily_return?: number | null
  monthly_return?: number | null
  equity_curve?: number[]
  ranking_eligible: boolean
  basis: 'COMPLETED_PAPER_TRADES_ONLY'
}
type StrategyLabPosition = {
  position_id?: string
  strategy_id?: string
  contract?: string
  instrument?: string
  underlying?: string
  option_type?: string
  strike?: number
  expiry?: string
  side?: string
  entry?: number
  exit?: number
  entry_price?: number
  average_price?: number
  current_price?: number
  pnl?: number
  unrealized_pnl?: number
  rr?: number
  stop?: number
  target?: number
  underlying_stop?: number
  underlying_target?: number
  option_contract?: { security_id?: string | number; option_type?: string; strike?: number; expiry?: string; underlying?: string; lot_size?: number; trading_symbol?: string }
  duration_seconds?: number
  status?: string
  quantity?: number
  initial_risk_per_unit?: number
  held_security_id?: string
  protective_stop?: number | null
  initial_stop?: number | null
  current_stop?: number | null
  underlying_initial_stop?: number | null
  underlying_current_stop?: number | null
  trailing_enabled?: boolean | null
  trailing_activation_price?: number | null
  trailing_anchor?: number | null
  trailing_distance?: number | null
  trailing_step?: number | null
  last_stop_update_time?: string | null
  risk_source?: string | null
  risk_source_timestamp?: string | null
  strategy_version?: string | null
  risk_rule_version?: string | null
  risk_status?: 'REPORTED' | 'NOT_REPORTED'
  risk_snapshot?: Record<string, unknown>
  trade_id?: string
  replay_id?: string | null
  entry_time?: string
  exit_time?: string | null
  realized_pnl?: number
  exit_reason?: string
  reason?: string
  pnl_valid?: boolean
  pnl_status?: 'AVAILABLE' | 'MTM_STALE' | 'MTM_UNAVAILABLE'
  quote_status?: 'FRESH' | 'STALE' | 'UNAVAILABLE'
  quote_timestamp?: string | null
  quote_age_seconds?: number | null
  quote_source?: string | null
  quote_security_id?: string | null
  quote_stale_reason?: string | null
  stop_breach?: { breached?: boolean; stop_price?: number; breach_price?: number; breach_timestamp?: string; exit_order_status?: string; latest_exit_attempt?: string | null; retry_eligible?: boolean; failure_reason?: string | null }
}
type StrategyLabOrder = {
  order_id: string
  strategy_id?: string
  status: string
  contract?: string
  side?: string
  quantity?: number
  filled_quantity?: number
  rejection_reason?: string | null
  created_at?: string
  updated_at?: string
}
type StrategyLabFill = {
  fill_id: string
  order_id: string
  strategy_id?: string
  time?: string
  price?: number
  quantity?: number
  fees?: number
}
type StrategyLabTimelineEvent = {
  record_id?: string
  strategy_id: string
  event_type: string
  entity_id?: string | null
  recorded_at?: string
  payload?: Record<string, unknown>
}
type StrategyLabReviewRecord = {
  strategy_id: string
  record_id?: string
  recorded_at?: string
  event_type?: string
  payload?: Record<string, unknown>
}
type StrategyLabStrategy = {
  strategy_id: string
  metadata: {
    name: string
    version: string
    author: string
    input_type: string
    supported_markets: string[]
    supported_timeframes: string[]
    rr: number | null
    risk_model: string
    status: string
  }
  state: string
  health: string
  readiness: string
  reason: string
  latency_ms?: number | null
  last_updated?: string | null
  scheduler?: { state?: string; tick_count?: number; skipped_count?: number; last_tick_at?: string | null; thread_alive?: boolean; activation_enabled?: boolean; activation_reason?: string | null }
  risk?: { authorization?: string; last_decision?: string | null; risk_model?: string }
  current_position: StrategyLabPosition | null
  current_positions?: StrategyLabPosition[]
  current_position_count?: number
  DATA_READY?: boolean
  data_readiness?: { DATA_READY?: boolean; not_ready_reason?: string; required_bars?: number; loaded_bars?: number }
  current_decision: { signal?: string; reason?: string; evaluated_at?: string; confidence?: number; option_contract?: { option_type?: string }; underlying_price?: number; position_state?: { entry?: number; stop?: number; target?: number } } | null
  today_trades: number
  statistics: StrategyLabStatistics
  paper_only: true
  live_trading_enabled: false
  broker_submission: false
}
type StrategyLabDashboard = {
  generated_at: string
  status: {
    status: string
    health: string
    readiness: string
    manager_started: boolean
    deployment_count: number
    loaded_runtime_count: number
    running_strategy_count: number
    paper_only: true
    live_trading_enabled: false
    broker_submission: false
  }
  strategies: StrategyLabStrategy[]
  leaderboard: {
    basis: 'COMPLETED_PAPER_TRADES_ONLY'
    entries: Array<{
      rank: number
      strategy_id: string
      strategy_name: string
      expectancy: number | null
      profit_factor: number | null
      win_rate: number | null
      drawdown: number
      sharpe: number | null
      net_pnl: number
      completed_trades: number
      rr: number | null
    }>
    eligible_strategy_count: number
  }
  summary: {
    deployed_strategies: number
    running_strategies: number
    completed_paper_trades: number
    ranking_eligible_strategies: number
  }
  deployment: {
    status: string
    adapters: Array<{ input_type: string; deployment_interface: string; compiler_or_parser: string }>
    pine_parser_implemented: false
    paper_only: true
  }
  tournament: {
    architecture_status: string
    same_candle_fanout: boolean
    same_market_context: boolean
    independent_paper_state: boolean
    independent_execution: boolean
  }
  safety_labels: string[]
  empty_state: string | null
  portfolio?: {
    status?: string
    generated_at?: string
    total_equity?: number | null
    current_capital?: number | null
    initial_capital?: number | null
    available_capital?: number | null
    used_capital?: number | null
    today_pnl?: number | null
    open_pnl?: number | null
    closed_pnl?: number | null
    total_pnl?: number | null
    open_trades?: number | null
    closed_trades?: number | null
    win_rate?: number | null
    profit_factor?: number | null
    expectancy?: number | null
    portfolio_drawdown?: number | null
    exposure?: number | null
    risk_usage?: number | null
    strategy_accounts?: number | null
    paper_only?: true
    live_trading_enabled?: false
    broker_submission?: false
  }
  execution?: {
    status: string
    positions: StrategyLabPosition[]
    authoritative_open_positions?: StrategyLabPosition[]
    orders: StrategyLabOrder[]
    fills: StrategyLabFill[]
    closed_trades: StrategyLabPosition[]
    todays_closed_trades?: TodaysClosedTradesData
    nifty_vob?: NiftyVOBData
    options_structure?: import('@/components/institutional').OptionsStructureData
    timeline: StrategyLabTimelineEvent[]
    order_counts: Record<string, number>
    position_count: number
    order_count: number
    fill_count: number
    closed_trade_count: number
    paper_only: true
    live_trading_enabled: false
    broker_submission: false
    reconciliation?: { status?: string; warnings?: string[]; authoritative_open_count?: number; mapped_open_count?: number }
    mtm?: { status?: 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE'; live_mtm?: number | null; exposure?: number; valid_position_count?: number; unavailable_position_count?: number }
  }
  review?: {
    status: string
    journal: StrategyLabReviewRecord[]
    replay: StrategyLabReviewRecord[]
    evidence: StrategyLabReviewRecord[]
    validation: Array<{ strategy_id: string; status: string; valid: boolean }>
    paper_only: true
  }
}

type DashboardMode = 'production' | 'workspace'

type FeedState<T> = {
  data: T | null
  error: string | null
  lastUpdated: Date | null
  loading: boolean
}

type StrategyCommandProjection = {
  status: string
  edge_lab?: ArgusEdgeLabData
}

type V2Feed = { ok: boolean; data: unknown; error: { code: string; message: string } | null; meta: { health: string; readiness: string; latency_ms: number; last_updated: string | null; source_last_updated: string | null; symbol?: string | null; timeframe?: string | null; candle_id?: string | null; latest_completed_candle_at?: string | null; source_timestamp?: string | null; calculation_timestamp?: string | null; calculation_age_seconds?: number | null; input_candle_count?: number | null; freshness_age_seconds?: number | null; market_input_state?: 'READY' | 'WAITING_FOR_NEXT_CANDLE' | 'STALE' | null; runtime_state?: string | null; stale_reason?: string | null; real_candles?: boolean | null; advisory_only?: boolean; execution_influence?: number | null } }
type ForecastProjectionMeta = { traceId: string; publishedAt: string; observedAt: string; sourceLastUpdated: string | null }

export default function Home() {
  const [dashboardMode, setDashboardMode] = useState<DashboardMode>('workspace')
  const selectedSymbol = useDashboardSelector(selectSelectedSymbol)
  const mission = useDashboardSelector(feedSelectors.mission) as FeedState<MissionControl>
  const matrix = useDashboardSelector(feedSelectors.matrix) as FeedState<MarketRow[]>
  const trade = useDashboardSelector(feedSelectors.trade) as FeedState<Trade | null>
  const performance = useDashboardSelector(feedSelectors.performance) as FeedState<PerformanceStats>
  const kronos = useDashboardSelector(feedSelectors.kronos) as FeedState<KronosGauge>
  const kronosAlpha = useDashboardSelector(feedSelectors.kronosAlpha) as FeedState<KronosAlphaStatus>
  const chronos2 = useDashboardSelector(feedSelectors.chronos2) as FeedState<Chronos2Status>
  const oracle = useDashboardSelector(feedSelectors.oracle) as FeedState<OracleReasoning>
  const athena = useDashboardSelector(feedSelectors.athena) as FeedState<AthenaWheel>
  const hermes = useDashboardSelector(feedSelectors.hermes) as FeedState<HermesStatus>
  const insights = useDashboardSelector(feedSelectors.insights) as FeedState<AIInsight[]>
  const argus = useDashboardSelector(feedSelectors.argus) as FeedState<ArgusResponse>
  const riskStatus = useDashboardSelector(feedSelectors.riskStatus) as FeedState<RiskStatus>
  const killSwitch = useDashboardSelector(feedSelectors.killSwitch) as FeedState<KillSwitchStatus>
  const paperStatus = useDashboardSelector(feedSelectors.paperStatus) as FeedState<PaperStatus>
  const personalOracle = useDashboardSelector(feedSelectors.personalOracle) as FeedState<PersonalOracleSummary>
  const aegis = useDashboardSelector(feedSelectors.aegis) as FeedState<AegisDecision>
  const readiness = useDashboardSelector(feedSelectors.readiness) as FeedState<OpenMarketReadiness>
  const nextSessionPlan = useDashboardSelector(feedSelectors.nextSessionPlan) as FeedState<NextSessionPlan>
  const orderLedger = useDashboardSelector(feedSelectors.orderLedger) as FeedState<OrderLedgerStatus>
  const paperTrading = useDashboardSelector(feedSelectors.paperTrading) as FeedState<PaperTradingDashboard>
  const strategyLab = useDashboardSelector(feedSelectors.strategyLab) as FeedState<StrategyLabDashboard>
  const comparison = useDashboardSelector(feedSelectors.comparison) as FeedState<StrategyComparisonPayload>
  const strategiesCommand = useDashboardSelector(feedSelectors.strategies) as FeedState<StrategyCommandProjection>
  const v2FeedMeta = useDashboardSelector(selectFeedMeta)
  const forecastProjectionMeta = useDashboardSelector(selectForecastProjectionMeta)
  const isRefreshing = useDashboardSelector(selectIsRefreshing)
  const dashboardHeader = useDashboardSelector(selectHeader)
  const dashboardFooter = useDashboardSelector(selectFooter)
  const dashboardActions = useDashboardActions()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const modeParam = params.get('mode')
    const stored = window.sessionStorage.getItem('citadelDashboardMode')
    const requestedMode = modeParam === 'production' || modeParam === 'workspace' ? modeParam : null
    const restoredMode = stored === 'production' || stored === 'workspace' ? stored : null
    const restore = window.setTimeout(() => {
      const nextMode = requestedMode ?? restoredMode
      if (nextMode) setDashboardMode(nextMode)
      if (requestedMode) window.sessionStorage.setItem('citadelDashboardMode', requestedMode)
    }, 0)
    return () => window.clearTimeout(restore)
  }, [])

  const changeSymbol = useCallback((symbol: string) => {
    dashboardActions.setSymbol(symbol)
    window.sessionStorage.setItem('selectedSymbol', symbol)
  }, [dashboardActions])

  const retry = useCallback(() => dashboardActions.refresh(), [dashboardActions])

  const feeds = [mission, matrix, trade, performance, kronos, kronosAlpha, chronos2, oracle, athena, hermes, insights, argus, riskStatus, killSwitch, paperStatus, personalOracle, aegis, readiness, nextSessionPlan, orderLedger, paperTrading, strategyLab, comparison, strategiesCommand]
  const initialLoading = feeds.every((feed) => feed.loading && !feed.lastUpdated)
  const receivedProjection = feeds.some((feed) => feed.lastUpdated)
  const transportFailed = feeds.every((feed) => Boolean(feed.error))
  const backendState = initialLoading ? 'connecting' : transportFailed ? receivedProjection ? 'degraded' : 'offline' : 'connected'
  const latestUpdate = feeds
    .map((feed) => feed.lastUpdated?.getTime() ?? 0)
    .reduce((latest, time) => Math.max(latest, time), 0)
  const oracleSectionStatus = oracle.error
    ? 'stale'
    : oracle.loading
    ? 'connecting'
    : oracle.data?.data_status === 'LIVE'
    ? oracle.data.oracle_status === 'READY'
      ? 'live'
      : 'partial'
    : oracle.data?.data_status === 'CACHED'
    ? 'cached'
    : oracle.data?.data_status === 'STALE'
    ? 'stale'
    : oracle.data
    ? 'unavailable'
    : 'connecting'
  const athenaSectionStatus = athena.error
    ? 'stale'
    : athena.loading
    ? 'connecting'
    : athena.data?.athena_status === 'READY'
    ? 'live'
    : athena.data?.athena_status === 'DEGRADED'
    ? 'partial'
    : athena.data?.athena_status === 'BLOCKED'
    ? 'error'
    : athena.data
    ? 'unavailable'
    : 'connecting'
  const hermesSectionStatus = hermes.error
    ? 'stale'
    : hermes.loading
    ? 'connecting'
    : hermes.data?.hermes_status === 'READY'
    ? 'cached'
    : hermes.data?.hermes_status === 'DEGRADED'
    ? 'partial'
    : hermes.data?.hermes_status === 'STALE'
    ? 'stale'
    : hermes.data?.hermes_status === 'BLOCKED'
    ? 'error'
    : hermes.data
    ? 'unavailable'
    : 'connecting'
  const showTradingWorkspace = dashboardMode === 'workspace'
  const headerUpdatedAt = latestUpdate ?? strategyLab.data?.generated_at ?? null
  const headerLatency = v2FeedMeta.strategy_lab?.latency_ms
  const headerConnectionTone = backendState === 'connected' ? 'positive' : backendState === 'degraded' || backendState === 'connecting' ? 'warning' : 'negative'

  return (
    <main className="dashboard-shell">
      <div className="ambient-grid" aria-hidden="true" />
      <CitadelPrimaryNavigation
        active={showTradingWorkspace ? 'workspace' : 'production'}
        title="CITADEL OS"
        instrument={`${selectedSymbol} · ${mission.data?.system.strategy ?? 'SYSTEM'}`}
        marketStatus={mission.data?.system.session.market_open ? 'NSE MARKET OPEN' : humanize(mission.data?.system.session.state ?? 'MARKET STATUS UNAVAILABLE')}
      />

      <header className="mission-header" aria-label="Mission Control">
        <div className="mission-header-identity"><strong>MISSION CONTROL</strong></div>
        <div className="mission-header-status">
          <span>Status</span>
          <strong className={
            v2FeedMeta.strategy_lab?.canonical_status?.overall_status === 'HEALTHY' ? 'positive' :
            v2FeedMeta.strategy_lab?.canonical_status?.overall_status === 'DEGRADED' ? 'warning' : 'negative'
          }>
            {v2FeedMeta.strategy_lab?.canonical_status?.wording_summary || (mission.loading ? 'Connecting' : `[${mission.data?.system.system ?? 'Unknown'}]`)}
          </strong>
        </div>
        <div><span>Mode</span><strong>{mission.loading ? 'Loading' : mission.data?.system.mode ? `${mission.data.system.mode.toUpperCase()} Execution` : 'Unavailable'}</strong></div>
        <div><span>Strategy</span><strong>{mission.loading ? 'Loading' : mission.data?.system.strategy ?? '—'}</strong></div>
        <div><span>Engine</span><strong className={strategyLab.data?.status.manager_started ? 'positive' : 'warning'}>{strategyLab.data?.status.manager_started ? 'Strategy Lab' : 'Starting'}</strong></div>
        <div><span>Backend</span><strong className={headerConnectionTone}>{backendState === 'connected' ? 'Connected' : backendState === 'degraded' ? 'Reconnecting' : backendState === 'connecting' ? 'Connecting' : 'Offline'}</strong></div>
        <div><span>Latency</span><strong>{headerLatency == null ? '—' : `${formatNumber(headerLatency)}ms`}</strong></div>
        <div><span>Market</span><strong className={mission.data?.system.session.market_open ? 'positive' : 'warning'}>{kronosAlpha.data?.input_metadata?.instrument.exchange ?? 'NSE'} {humanize(v2FeedMeta.strategy_lab?.canonical_status?.operating_mode || mission.data?.system.session.state || 'Waiting')}</strong></div>
        <div><span>Auto Refresh</span><strong className="positive">{dashboardHeader.autoRefresh ? 'ON' : 'OFF'} · {formatNumber(dashboardHeader.refreshIntervalMs / 1_000)}s</strong></div>
        <div><span>Last Update</span><strong>{headerUpdatedAt ? formatTimeOnly(headerUpdatedAt) : 'Awaiting'}</strong></div>
      </header>

      {!showTradingWorkspace ? (
        <>
          <SafetyStrip
            canonicalStatus={v2FeedMeta.strategy_lab?.canonical_status}
            paperOnly={true}
            liveTradingEnabled={false}
            brokerSubmission={false}
          />
          <ActionRequiredPanel issues={v2FeedMeta.strategy_lab?.canonical_status?.action_required_issues} />
          <div className="development-mode-banner" role="status">
            <strong>PRODUCTION OPERATIONS</strong>
            <span>EXECUTION {mission.data?.system.mode?.toUpperCase() ?? 'UNAVAILABLE'}</span>
            <span>BROKER {humanize(mission.data?.system.broker ?? 'UNAVAILABLE')}</span>
            <small>Authoritative production state · Real backend permissions and deployment telemetry.</small>
          </div>
        </>
      ) : null}

      {showTradingWorkspace ? (
        <TradingWorkspace strategyLab={strategyLab} strategiesCommand={strategiesCommand} comparison={comparison} mission={mission} performance={performance} kronos={kronos} kronosAlpha={kronosAlpha} chronos2={chronos2} argus={argus} athena={athena} oracle={oracle} hermes={hermes} personalOracle={personalOracle} aegis={aegis} readiness={readiness} nextSessionPlan={nextSessionPlan} orderLedger={orderLedger} feedMeta={v2FeedMeta} forecastProjectionMeta={forecastProjectionMeta} headerUpdatedAt={headerUpdatedAt} selectedSymbol={selectedSymbol} onSymbolChange={changeSymbol} onRetry={retry} retrying={isRefreshing} />
      ) : (
      <>
      <section className="mission-grid" aria-label="Mission Control summary">
        <SectionHeading eyebrow="01 / Mission Control" title="Operational posture" error={mission.error} status={mission.error ? 'stale' : mission.loading ? 'connecting' : 'live'} />
        <div className="metric-grid">
          <MetricCard
            label="Market session"
            value={mission.data ? humanize(mission.data.system.session.state) : '—'}
            detail={mission.data ? humanize(mission.data.system.session.reason) : 'Waiting for mission control'}
            tone={mission.data?.system.session.market_open ? 'positive' : 'neutral'}
            icon={<Activity size={18} />}
            loading={mission.loading}
          />
          <MetricCard
            label="Strategy engine"
            value={mission.data?.system.strategy ?? '—'}
            detail={mission.data?.system.phase.replaceAll('_', ' ') ?? 'Waiting for mission control'}
            tone="purple"
            icon={<Zap size={18} />}
            loading={mission.loading}
          />
          <MetricCard
            label="Closed journal"
            value={mission.data ? formatInteger(mission.data.journal.total_closed) : '—'}
            detail={mission.data ? `${mission.data.journal.wins} wins · ${mission.data.journal.losses} losses` : 'Waiting for mission control'}
            tone="blue"
            icon={<BarChart3 size={18} />}
            loading={mission.loading}
          />
          <MetricCard
            label="Journal net"
            value={mission.data ? formatSigned(mission.data.journal.net_points) : '—'}
            detail="Realized points"
            tone={(mission.data?.journal.net_points ?? 0) >= 0 ? 'positive' : 'negative'}
            icon={(mission.data?.journal.net_points ?? 0) >= 0 ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
            loading={mission.loading}
          />
        </div>
      </section>

      <section className="risk-paper-section" aria-label="Risk and paper control">
        <SectionHeading
          eyebrow="SAFE / Risk & Paper Control"
          title="Read-Only Safety State"
          error={riskStatus.error ?? killSwitch.error ?? paperStatus.error}
          status={
            riskStatus.error || killSwitch.error || paperStatus.error
              ? 'stale'
              : riskStatus.loading || killSwitch.loading || paperStatus.loading
              ? 'connecting'
              : riskStatus.data?.status === 'healthy' && paperStatus.data?.status === 'healthy'
              ? 'live'
              : riskStatus.data || paperStatus.data
              ? 'partial'
              : 'unavailable'
          }
          aside="Authoritative backend telemetry"
        />
        {riskStatus.loading && killSwitch.loading && paperStatus.loading ? (
          <RiskPaperLoading />
        ) : riskStatus.data || paperStatus.data ? (
          <RiskPaperControl
            risk={riskStatus.data}
            killSwitch={killSwitch.data}
            paper={paperStatus.data}
            staleMessage={riskStatus.error ?? killSwitch.error ?? paperStatus.error}
          />
        ) : (
          <FeedPlaceholder error={riskStatus.error ?? killSwitch.error ?? paperStatus.error} label="risk and paper control" />
        )}
      </section>

      <div className="primary-grid">
        <DesignCard as="section" unstyled className="panel matrix-panel">
          <SectionHeading eyebrow="02 / Market Matrix" title="Live index intelligence" error={matrix.error} status={matrix.error ? 'stale' : matrix.loading ? 'connecting' : 'live'} aside={`${matrix.data?.length ?? 0} instruments`} />
          {matrix.loading ? <MarketMatrixLoading /> : matrix.data ? <MarketMatrix rows={matrix.data} /> : <FeedPlaceholder error={matrix.error} label="market matrix" />}
        </DesignCard>

        <DesignCard as="section" unstyled className="panel trade-panel">
          <SectionHeading eyebrow="03 / Active Trade" title="Simulated Execution Monitor" error={trade.error} status={trade.error ? 'stale' : trade.loading ? 'connecting' : 'live'} />
          {trade.loading ? (
            <WidgetLoading label="Loading active trade" />
          ) : trade.error && !trade.lastUpdated ? (
            <FeedPlaceholder error={trade.error} label="active trade" />
          ) : trade.data ? (
            <ActiveTrade trade={trade.data} />
          ) : (
            <div className="flat-state">
              <div className="radar-orbit"><Target size={27} /></div>
              <p>No active trade</p>
              <span>Execution engine is flat. Waiting for a qualified setup.</span>
              <div className="flat-meta"><i /> Strategy monitoring</div>
            </div>
          )}
        </DesignCard>
      </div>

      <section className="performance-section">
        <SectionHeading eyebrow="04 / Performance Nexus" title="Simulated Forward-Test Analytics" error={performance.error} status={performance.error ? 'stale' : performance.loading ? 'connecting' : 'live'} aside={performance.data?.verdict.replaceAll('_', ' ') ?? undefined} />
        {performance.loading ? (
          <PerformanceLoading />
        ) : performance.data ? (
          <>
            <div className="performance-grid">
              <PerformanceCard label="Net points" value={formatSigned(performance.data.net_points)} sub={`${performance.data.total_trades} analyzed trades`} tone={performance.data.net_points >= 0 ? 'positive' : 'negative'} />
              <PerformanceCard label="Win rate" value={formatPercent(performance.data.win_rate)} sub={`${performance.data.wins} wins · ${performance.data.losses} losses`} tone="blue" />
              <PerformanceCard label="Profit factor" value={formatNumber(performance.data.profit_factor)} sub="Gross profit / gross loss" tone="purple" />
              <PerformanceCard label="Expectancy" value={formatSigned(performance.data.expectancy)} sub="Points per trade" tone={performance.data.expectancy >= 0 ? 'positive' : 'negative'} />
              <PerformanceCard label="Best win streak" value={formatInteger(performance.data.max_win_streak)} sub={`Max loss streak ${performance.data.max_loss_streak}`} tone="neutral" />
            </div>
            <div className="analytics-note">
              <span>System assessment</span>
              <p>{performance.data.comment}</p>
            </div>
          </>
        ) : (
          <FeedPlaceholder error={performance.error} label="performance stats" />
        )}
      </section>

      <section className="aegis-section" aria-label="AEGIS — FINAL DECISION INTELLIGENCE">
        <SectionHeading eyebrow="05A / AEGIS" title="Final Decision Intelligence" error={aegis.error} status={aegis.error ? 'stale' : aegis.loading ? 'connecting' : aegis.data?.hard_gate_reasons.includes('MARKET_CLOSED') ? 'closed' : aegis.data?.decision === 'BLOCK' ? 'error' : 'live'} aside="Advisory controller · No execution" />
        {aegis.loading ? <WidgetLoading label="Loading AEGIS decision cache" /> : aegis.data ? <AegisPanel data={aegis.data} readiness={readiness.data} plan={nextSessionPlan.data} readinessError={readiness.error ?? nextSessionPlan.error} /> : <FeedPlaceholder error={aegis.error} label="AEGIS decision intelligence" />}
      </section>

      <section className="order-ledger-section" aria-label="ORDER & FILL OPERATIONS">
        <SectionHeading eyebrow="05B / OPERATIONS" title="Order & Fill Operations" error={orderLedger.error} status={orderLedger.error || orderLedger.data?.status === 'UNAVAILABLE' ? 'error' : orderLedger.loading ? 'connecting' : 'live'} aside="Audit-only · Read-only" />
        {orderLedger.loading ? <WidgetLoading label="Loading order ledger status" /> : orderLedger.data ? <OrderLedgerPanel data={orderLedger.data} /> : <FeedPlaceholder error={orderLedger.error} label="order and fill ledger" />}
      </section>

      <section className="paper-trading-section development-paper-section mode-paper-section" aria-label="REAL MARKET PAPER TRADING">
        <SectionHeading
          eyebrow="05C / PAPER ENGINE"
          title="Real Market Paper Trading"
          error={paperTrading.error}
          status={paperTrading.error ? 'stale' : paperTrading.loading ? 'connecting' : paperTrading.data?.readiness.status === 'READY' ? 'live' : 'partial'}
          aside="Dhan data · Paper only"
        />
        {paperTrading.loading ? <WidgetLoading label="Loading paper execution state" /> : paperTrading.data ? <PaperTradingPanel data={paperTrading.data} /> : <FeedPlaceholder error={paperTrading.error} label="real market paper trading" />}
      </section>

      <section className="intelligence-section" aria-label="Live intelligence engines">
        <div className="intelligence-grid">
          <DesignCard as="section" unstyled className="panel intelligence-panel kronos-panel kronos-core-panel">
            <SectionHeading eyebrow="06 / Heuristic Kronos" title="Heuristic Trend & Momentum Gauge" error={kronos.error} status={kronos.error ? 'stale' : kronos.loading ? 'connecting' : 'live'} aside={kronos.data?.label ?? undefined} />
            {kronos.loading ? <WidgetLoading label="Loading Kronos intelligence" /> : kronos.data ? <KronosPanel data={kronos.data} /> : <FeedPlaceholder error={kronos.error} label="Kronos gauge" />}
          </DesignCard>

          <DesignCard as="section" unstyled className="panel intelligence-panel oracle-panel">
            <SectionHeading eyebrow="07 / Technical Intelligence" title="Deterministic Signal Assessment" error={oracle.error} status={oracleSectionStatus} aside={oracle.data ? `${oracle.data.symbol} · ${humanize(oracle.data.signal)}` : undefined} />
            {oracle.loading ? <WidgetLoading label="Loading technical assessment" /> : oracle.data ? <OraclePanel data={oracle.data} /> : <FeedPlaceholder error={oracle.error} label="technical assessment" />}
          </DesignCard>

          <DesignCard as="section" unstyled className="panel intelligence-panel athena-panel">
            <SectionHeading eyebrow="08 / Athena" title="Risk & Capital Intelligence" error={athena.error} status={athenaSectionStatus} aside={athena.data ? `${humanize(athena.data.risk_state)} · ${humanize(athena.data.recommendation)}` : undefined} />
            {athena.loading ? <WidgetLoading label="Loading Athena intelligence" /> : athena.data ? <AthenaPanel data={athena.data} /> : <FeedPlaceholder error={athena.error} label="Athena intelligence" />}
          </DesignCard>

          <DesignCard as="section" unstyled className="panel intelligence-panel hermes-panel">
            <SectionHeading eyebrow="09 / Hermes" title="News & Event Intelligence" error={hermes.error} status={hermesSectionStatus} aside={hermes.data ? `Provider: ${humanize(hermes.data.source_metadata.provider_mode)}` : undefined} />
            {hermes.loading ? <WidgetLoading label="Loading Hermes intelligence" /> : hermes.data ? <HermesPanel data={hermes.data} /> : <FeedPlaceholder error={hermes.error} label="Hermes intelligence" />}
          </DesignCard>

          <DesignCard as="section" unstyled className="panel intelligence-panel insights-panel">
            <SectionHeading eyebrow="10 / System Insights" title="Heuristic Optimization Suggestions" error={insights.error} status={insights.error ? 'stale' : insights.loading ? 'connecting' : 'live'} aside={insights.data ? `${insights.data.length} items` : undefined} />
            {insights.loading ? <WidgetLoading label="Loading system insights" /> : insights.data ? <InsightsPanel insights={insights.data} /> : <FeedPlaceholder error={insights.error} label="system insights" />}
          </DesignCard>
        </div>
      </section>
      </>
      )}

      <footer>
        <span>{dashboardFooter.product}</span>
        <span className="footer-dedication">{dashboardFooter.build}</span>
        <span>{dashboardFooter.telemetry}</span>
      </footer>
    </main>
  )
}

function RiskPaperLoading() {
  return (
    <div className="risk-control-loading" aria-label="Loading risk and paper control" aria-busy="true">
      {Array.from({ length: 3 }, (_, index) => (
        <div key={index}><i className="loading-line" /><i className="loading-line" /><i className="loading-line" /></div>
      ))}
    </div>
  )
}

function RiskPaperControl({ risk, killSwitch, paper, staleMessage }: { risk: RiskStatus | null; killSwitch: KillSwitchStatus | null; paper: PaperStatus | null; staleMessage: string | null }) {
  const killLabel = killSwitch?.state ?? risk?.kill_switch_state ?? (risk?.kill_switch_active === true ? 'ACTIVE' : risk?.kill_switch_active === false ? 'INACTIVE' : 'UNKNOWN')
  const liveLabel = risk?.live_trading_enabled === false ? 'DISABLED' : risk?.live_trading_enabled === true ? 'ENABLED' : 'UNKNOWN'
  const stateHealth = risk?.state_health === 'HEALTHY' && paper?.state_health === 'HEALTHY'
    ? 'HEALTHY'
    : risk?.state_health === 'UNAVAILABLE' || paper?.state_health === 'UNAVAILABLE'
    ? 'UNAVAILABLE'
    : 'DEGRADED'
  const stateLastChanged = paper?.state_last_mutated_at ?? paper?.last_updated ?? null
  const projectionObserved = paper?.projection_observed_at ?? risk?.last_updated ?? null
  const latestDecision = risk?.latest_authorization

  return (
    <div className="risk-control-content">
      {staleMessage && <div className="risk-control-stale">Last successful safety state preserved · {staleMessage}</div>}
      <div className="risk-control-grid">
        <article className="risk-control-card safety-card">
          <div className="control-card-heading"><span>System safety</span><i className={controlTone(stateHealth)} /></div>
          <ControlStatus label="Kill Switch" value={killLabel} tone={killLabel === 'ACTIVE' || killLabel === 'CORRUPT' ? 'negative' : killLabel === 'INACTIVE' ? 'positive' : 'unavailable'} />
          <ControlStatus label="Live Trading" value={liveLabel} tone={risk?.live_trading_enabled === false ? 'positive' : risk?.live_trading_enabled === true ? 'negative' : 'unavailable'} />
          <ControlStatus label="State Health" value={stateHealth} tone={controlTone(stateHealth)} />
          <p>{killSwitch?.reason ?? risk?.kill_switch_reason ?? risk?.error?.message ?? 'Kill-switch reason unavailable'}</p>
          <div className="kill-switch-meta"><span>Persistence <strong>{killSwitch?.persistence_health ?? 'UNKNOWN'}</strong></span><span>Updated <strong>{killSwitch?.updated_at ? formatTimestamp(killSwitch.updated_at) : '—'}</strong></span></div>
        </article>

        <article className="risk-control-card">
          <div className="control-card-heading"><span>Daily paper state</span><small>{paper?.trading_date ?? 'Date unavailable'}</small></div>
          <div className="control-metric-grid daily-control-metrics">
            <ControlMetric label="Realized P&L" value={formatControlSigned(paper?.realized_pnl)} tone={metricTone(paper?.realized_pnl)} />
            <ControlMetric label="Unrealized P&L" value={formatControlSigned(paper?.unrealized_pnl)} tone={metricTone(paper?.unrealized_pnl)} />
            <ControlMetric label="Total Daily P&L" value={formatControlSigned(paper?.total_daily_pnl)} tone={metricTone(paper?.total_daily_pnl)} />
            <ControlMetric label="Trades Today" value={formatControlInteger(paper?.trades_taken_today)} />
            <ControlMetric label="Consecutive Losses" value={formatControlInteger(paper?.consecutive_losses)} tone={(paper?.consecutive_losses ?? 0) > 0 ? 'warning' : 'neutral'} />
            <ControlMetric label="Open Positions" value={formatControlInteger(paper?.open_position_count)} />
          </div>
        </article>

        <article className="risk-control-card">
          <div className="control-card-heading"><span>Active limits</span><small>Non-live defaults</small></div>
          <div className="control-metric-grid limit-control-metrics">
            <ControlMetric label="Daily Loss" value={formatControlNumber(risk?.limits.max_daily_loss)} />
            <ControlMetric label="Max Trades" value={formatControlInteger(risk?.limits.max_trades_per_day)} />
            <ControlMetric label="Loss Streak" value={formatControlInteger(risk?.limits.max_consecutive_losses)} />
            <ControlMetric label="Per-Trade Risk" value={formatControlNumber(risk?.limits.max_risk_per_trade)} />
            <ControlMetric label="Raw Quantity" value={formatControlInteger(risk?.limits.max_raw_quantity)} />
            <ControlMetric label="Open Positions" value={formatControlInteger(risk?.limits.max_open_positions)} />
            <ControlMetric label="Data Age" value={risk?.limits.max_market_data_age_seconds === null || risk?.limits.max_market_data_age_seconds === undefined ? 'Unavailable' : `${formatNumber(risk.limits.max_market_data_age_seconds)}s`} />
            <ControlMetric label="Volatility" value={formatControlNumber(risk?.limits.max_volatility)} />
          </div>
        </article>
      </div>

      <div className="risk-control-audit">
        <span>Read-only audit</span>
        <strong>{latestDecision?.decision ?? 'No authorization decision available'}</strong>
        <p>{latestDecision?.reason_code ? `${humanize(latestDecision.reason_code)} · ${latestDecision.reason ?? 'Reason unavailable'}` : risk?.error?.message ?? paper?.error?.message ?? 'Awaiting a non-secret authorization audit record.'}</p>
        <div><span>Accepted IDs {formatControlInteger(paper?.accepted_request_count)}</span><span>State changed {stateLastChanged ? formatTimestamp(stateLastChanged) : 'Unavailable'}</span><span>Observed {projectionObserved ? formatTimestamp(projectionObserved) : 'Unavailable'}</span></div>
      </div>
    </div>
  )
}

function ControlStatus({ label, value, tone }: { label: string; value: string; tone: string }) {
  return <div className="control-status-row"><span>{label}</span><strong className={tone}><i />{value}</strong></div>
}

function ControlMetric({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: string }) {
  return <div><span>{label}</span><strong className={`${tone} ${value === 'Unavailable' ? 'unavailable' : ''}`}>{value}</strong></div>
}

function controlTone(value: string) {
  if (value === 'HEALTHY') return 'positive'
  if (value === 'DEGRADED') return 'warning'
  return 'unavailable'
}

function metricTone(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return 'neutral'
  return value > 0 ? 'positive' : 'negative'
}

function formatControlNumber(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? formatNumber(value) : 'Unavailable'
}

function formatControlInteger(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? formatInteger(value) : 'Unavailable'
}

function formatControlSigned(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? formatSigned(value) : 'Unavailable'
}

function SectionHeading({
  eyebrow,
  title,
  error,
  aside,
  status = 'live',
}: {
  eyebrow: string
  title: string
  error: string | null
  aside?: string
  status?: 'live' | 'fresh' | 'cached' | 'stale' | 'error' | 'closed' | 'partial' | 'preview' | 'unavailable' | 'insufficient_data' | 'connecting'
}) {
  const label =
    status === 'live' || status === 'fresh'
      ? 'Live Polling'
      : status === 'cached'
      ? 'Cached Data'
      : status === 'stale' || status === 'error'
      ? 'Stale / Connection Offline'
      : status === 'closed'
      ? 'Market Closed'
      : status === 'partial' || status === 'preview'
      ? 'Simulation / Preview'
      : 'Awaiting Update'

  return (
    <DesignSectionHeader
      as="div"
      unstyled
      className="section-heading"
      eyebrowClassName="section-eyebrow"
      eyebrow={<>{eyebrow}<span className={`status-dot ${status}`} title={`Telemetry State: ${label}`} /></>}
      title={title}
      asideClassName={error ? 'feed-error' : 'section-aside'}
      aside={error ? <><WifiOff size={13} /> Disconnected · {error}</> : aside}
    />
  )
}

function OrderLedgerPanel({ data }: { data: OrderLedgerStatus }) {
  const unavailable = data.status === 'UNAVAILABLE' || data.health !== 'HEALTHY'
  return (
    <div className="order-ledger-body">
      <div className="order-ledger-metrics">
        <div><span>Health</span><strong>{humanize(data.health)}</strong></div>
        <div><span>Orders</span><strong>{data.order_count ?? '—'}</strong></div>
        <div><span>Active</span><strong>{data.active_order_count ?? '—'}</strong></div>
        <div><span>Fills</span><strong>{data.fill_count ?? '—'}</strong></div>
        <div><span>Mode</span><strong>AUDIT ONLY</strong></div>
        <div><span>Execution Engine</span><strong>NOT ACTIVE</strong></div>
        <div><span>Broker Submission</span><strong>DISABLED</strong></div>
        <div><span>Live Trading</span><strong>FALSE</strong></div>
      </div>
      <div className={`order-ledger-empty ${unavailable ? 'unavailable' : ''}`}>
        <strong>{unavailable ? 'ORDER LEDGER UNAVAILABLE' : 'ORDER LEDGER READY'}</strong>
        <p>{unavailable ? 'State is unavailable or corrupt. Operations remain fail-closed.' : data.empty ? 'No order intents recorded.' : `${data.active_order_count ?? 0} active order intents recorded.`}</p>
        <small>Execution engine is not active.</small>
      </div>
      <div className="order-ledger-safety">AUDIT ONLY · NO BROKER SUBMISSION · NO AUTOMATIC PAPER APPLICATION · LIVE TRADING FALSE · RISK VETO · KILL-SWITCH STATE · AEGIS PROVENANCE</div>
    </div>
  )
}

function PaperTradingPanel({ data }: { data: PaperTradingDashboard }) {
  const position = data.position.position
  const signal = data.status.last_signal
  const events = data.timeline.events.slice(0, 4)
  return (
    <div className="paper-trading-body">
      <div className="paper-trading-safety">
        <strong>REAL DHAN DATA · PAPER ONLY</strong>
        <span>Closed candles only</span><span>Broker submission disabled</span><span>Frontend execution disabled</span><span>Live trading false</span>
      </div>
      <div className="paper-trading-metrics">
        <div><span>Engine</span><strong>{humanize(data.status.state)}</strong><small>{humanize(data.status.reason)}</small></div>
        <div><span>Strategy</span><strong>{data.status.strategy_registry.strategies[0]?.name ?? '—'}</strong><small>{data.status.strategy_registry.active_count}/2 active</small></div>
        <div><span>Daily trades</span><strong>{data.pnl.trades_taken ?? '—'} / 2</strong><small>One position maximum</small></div>
        <div><span>Daily P&amp;L</span><strong className={metricTone(data.pnl.total_daily_pnl)}>{formatControlSigned(data.pnl.total_daily_pnl)}</strong><small>Authoritative Paper State</small></div>
      </div>
      <div className="paper-trading-grid">
        <article>
          <span>Strategy monitor</span>
          <strong>{signal ? humanize(signal.signal) : 'Awaiting closed candle'}</strong>
          <p>{signal?.reason ?? 'No strategy evaluation recorded.'}</p>
          <small>{signal ? `Entry ${signal.entry ?? '—'} · SL ${signal.sl ?? '—'} · Target ${signal.target ?? '—'}` : 'NIFTY · 5m · closed-candle evaluation'}</small>
        </article>
        <article>
          <span>Paper position</span>
          <strong>{position ? `${position.option_type} ${formatNumber(position.strike)}` : 'No open position'}</strong>
          <p>{position ? `${position.raw_quantity} units · 1 lot · ${position.expiry}` : 'Waiting for AEGIS and Risk ALLOW.'}</p>
          <small>{position ? `Entry ${formatNumber(position.entry_price)} · Mark ${formatNumber(position.mark_price)} · uPnL ${formatSigned(position.unrealized_pnl)}` : 'No averaging · No pyramiding · No overnight'}</small>
        </article>
        <article>
          <span>Decision gates</span>
          <strong>{data.status.last_aegis?.decision ?? 'AEGIS —'}</strong>
          <p>{data.status.last_risk ? `Risk ${data.status.last_risk.decision} · ${humanize(data.status.last_risk.reason_code)}` : 'Risk not evaluated for a paper intent.'}</p>
          <small>KRONOS ALPHA SHADOW · CHRONOS-2 SHADOW</small>
        </article>
      </div>
      <div className="paper-trading-timeline">
        <span>Execution timeline</span>
        {events.length ? events.map((event) => <div key={`${event.timestamp}-${event.code}`}><time>{formatTimestamp(event.timestamp)}</time><strong>{humanize(event.code)}</strong><small>{event.detail || humanize(event.status)}</small></div>) : <p>No paper execution events recorded.</p>}
      </div>
    </div>
  )
}

// Retained as an inert rollback reference; DEV is no longer a navigable or rendered session mode.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function DevelopmentPaperPanel({ data }: { data: DevelopmentDashboard }) {
  const decision = data.status.last_decision
  const position = data.position.position
  const moduleNames = ['technical', 'kronos_core', 'argus', 'kronos_alpha', 'chronos_2', 'athena', 'oracle', 'hermes']
  const missingEvidence = decision?.missing_optional_evidence ?? []
  const whyTrade = decision?.why_trade ?? []
  const whyNotTrade = decision?.why_not_trade ?? []
  return (
    <div className="development-paper-body">
      <div className="development-safety-strip">
        {data.safety_labels.map((label, index) => <strong className={index === 0 ? 'primary' : ''} key={label}><i aria-hidden="true" />{label}</strong>)}
      </div>

      <section className="development-panel-group" aria-label="Weighted development decision">
        <header className="development-group-heading">
          <div><span>Weighted Decision</span><small>Isolated evidence-based development policy</small></div>
          <span className="development-policy-chip">Threshold {formatNumber(data.status.weighted_policy.allow_threshold)}</span>
        </header>
        <div className="development-decision-hero">
          <div className="development-decision-card">
            <span>Current decision</span>
            <strong className={`development-decision ${decision?.decision.toLowerCase() ?? 'waiting'}`}>{decision?.decision ?? 'WAITING'}</strong>
            <small>{humanize(data.status.reason)}</small>
          </div>
          <div><span>Weighted score</span><strong>{decision ? formatNumber(decision.weighted_score) : '—'}</strong><small>of 100 available points</small></div>
          <div><span>Allow threshold</span><strong>{formatNumber(data.status.weighted_policy.allow_threshold)}</strong><small>Development policy gate</small></div>
          <div><span>Evidence coverage</span><strong>{decision ? formatPercent(decision.data_coverage_percentage) : '—'}</strong><small>{missingEvidence.length} optional modules unavailable</small></div>
          <div><span>Decision confidence</span><strong>{decision ? formatPercent(decision.confidence) : '—'}</strong><small>{decision ? formatTimestamp(decision.generated_at) : 'Awaiting decision'}</small></div>
        </div>
      </section>

      <section className="development-panel-group" aria-label="Development module vote breakdown">
        <header className="development-group-heading">
          <div><span>Module Vote Breakdown</span><small>Contribution to the current weighted decision</small></div>
          <span className="development-policy-chip">8 evidence modules</span>
        </header>
        <div className="development-contribution-grid">
        {moduleNames.map((name) => {
          const contribution = decision?.module_contributions[name] ?? null
          const vote = decision?.module_votes[name]
          const voteTone = vote?.vote ? vote.vote.toLowerCase().replaceAll('_', '-') : 'unavailable'
          return (
            <article key={name}>
              <div className="development-module-heading"><span>{humanize(name)}</span><em className={`development-vote ${voteTone}`}>{vote ? humanize(vote.vote) : 'Unavailable'}</em></div>
              <div className="development-module-stat"><span>Contribution</span><strong className={contribution == null ? 'unavailable' : ''}>{contribution == null ? '—' : formatNumber(contribution)}</strong></div>
              <div className="development-module-stat secondary"><span>Evidence score</span><strong className={vote?.score == null ? 'unavailable' : ''}>{vote?.score == null ? '—' : formatNumber(vote.score)}</strong></div>
            </article>
          )
        })}
        </div>
      </section>

      <div className="development-analysis-grid">
        <section className="development-panel-group development-reasons" aria-label="Development decision reasons">
          <header className="development-group-heading"><div><span>Decision Rationale</span><small>Explicit trade and rejection evidence</small></div></header>
          <div className="development-reason-block positive">
            <span>Why Trade</span>
            {whyTrade.length ? <ul>{whyTrade.map((reason) => <li key={reason}>{humanize(reason)}</li>)}</ul> : <p>No positive trade reasons recorded.</p>}
          </div>
          <div className="development-reason-block negative">
            <span>Why Not Trade</span>
            {whyNotTrade.length ? <ul>{whyNotTrade.map((reason) => <li key={reason}>{humanize(reason)}</li>)}</ul> : <p>No rejection reasons recorded.</p>}
          </div>
          <div className="development-veto-row"><span>Hard vetoes</span><strong>{decision?.hard_vetoes?.length ? decision.hard_vetoes.map(humanize).join(', ') : 'None'}</strong></div>
        </section>

        <section className="development-panel-group" aria-label="Development paper state and evidence">
          <header className="development-group-heading"><div><span>Paper State &amp; Evidence</span><small>Isolated development records only</small></div></header>
          <div className="development-state-grid">
            <div><span>Position</span><strong>{position ? `${position.option_type} ${formatNumber(position.strike)}` : 'No open position'}</strong><small>{position ? `${position.raw_quantity} units · Entry ${formatNumber(position.entry_price)} · Mark ${formatNumber(position.mark_price)}` : 'Paper state is flat'}</small></div>
            <div><span>Daily P&amp;L</span><strong className={metricTone(data.pnl.total_daily_pnl)}>{formatControlSigned(data.pnl.total_daily_pnl)}</strong><small>Isolated Paper State</small></div>
            <div><span>Evidence trades</span><strong>{data.pnl.trades_taken ?? '—'} / {data.status.evidence_ceiling_per_day}</strong><small>{data.pnl.closed_trades ?? 0} closed · No quota</small></div>
            <div><span>Position limit</span><strong>{data.status.maximum_open_positions ?? '—'}</strong><small>{data.status.maximum_lots ?? '—'} lot maximum</small></div>
            <div><span>Evidence integrity</span><strong className={data.evidence.integrity.valid ? 'positive' : 'unavailable'}>{data.evidence.integrity.valid ? 'Verified' : humanize(data.evidence.status)}</strong><small>{data.evidence.integrity.records ?? '—'} immutable records</small></div>
            <div><span>Ledger counts</span><strong>{data.ledger.order_count ?? '—'} / {data.ledger.fill_count ?? '—'}</strong><small>Orders / fills</small></div>
            <div><span>Decisions</span><strong>{data.evidence.decision_count ?? '—'}</strong><small>Persisted development decisions</small></div>
            <div><span>Trade evidence</span><strong>{data.evidence.closed_trade_evidence_count ?? '—'}</strong><small>Closed trade records</small></div>
          </div>
          <div className="development-missing-row"><span>Missing optional evidence</span>{missingEvidence.length ? <div>{missingEvidence.map((item) => <em key={item}>{humanize(item)}</em>)}</div> : <strong>None</strong>}</div>
        </section>
      </div>

      <div className="development-disclaimer" aria-label="Development safety protections">
        <span><i aria-hidden="true" />Production AEGIS not used</span>
        <span><i aria-hidden="true" />Production state not mutated</span>
        <span><i aria-hidden="true" />Broker submission disabled</span>
        <span><i aria-hidden="true" />Live trading false</span>
      </div>
    </div>
  )
}

// Retained as an inert rollback reference; DEV and PROD now share the master interface.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function ProductionTerminal(props: {
  strategyLab: FeedState<StrategyLabDashboard>
  mission: FeedState<MissionControl>
  riskStatus: FeedState<RiskStatus>
  killSwitch: FeedState<KillSwitchStatus>
  paperStatus: FeedState<PaperStatus>
  orderLedger: FeedState<OrderLedgerStatus>
  backendState: 'connecting' | 'connected' | 'degraded' | 'offline'
  feedMeta: Record<string, { latency_ms?: number | null; status?: string }>
}) {
  const { strategyLab, mission, riskStatus, killSwitch, paperStatus, orderLedger, backendState, feedMeta } = props
  const data = strategyLab.data
  const deployments = data?.strategies ?? []
  const execution = data?.execution
  const positions = (execution?.positions ?? []).filter((position) => {
    const status = (position.status ?? 'OPEN').toUpperCase()
    return !position.exit_time && !['CLOSED', 'EXITED', 'TARGET_HIT', 'STOP_HIT'].includes(status)
  })
  const orders = (execution?.orders ?? []).filter((order) => !['FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED'].includes(order.status.toUpperCase())).slice(0, 12)
  const timeline = (execution?.timeline ?? []).slice(0, 20)
  const schedulerRunning = deployments.length > 0 && deployments.every((strategy) => strategy.scheduler?.state === 'RUNNING')
  const managerRunning = data?.status.manager_started === true
  const paperOnly = data?.status.paper_only === true && data.status.live_trading_enabled === false && data.status.broker_submission === false
  const liveBlocked = !mission.data?.system.live_trading_enabled && !data?.status.live_trading_enabled
  const killActive = killSwitch.data?.state === 'ACTIVE' || riskStatus.data?.kill_switch_active === true
  const projectionLatency = feedMeta.strategy_lab?.latency_ms ?? null

  const deploymentMeta = (strategy: StrategyLabStrategy) => {
    const option = /^(PB|BO)_NIFTY_(CE|PE)_(1M|3M)$/.exec(strategy.strategy_id)
    const prefix = option?.[1] ?? (strategy.strategy_id.toLowerCase().includes('pullback') ? 'PB' : 'BO')
    const side = option?.[2] ?? strategy.current_decision?.option_contract?.option_type ?? 'NIFTY'
    const configured = strategy.metadata.supported_timeframes?.[0]
    const timeframe = option?.[3]?.toLowerCase() ?? (configured && configured !== 'CHART_TIMEFRAME' ? configured : '5m')
    return { prefix, side, timeframe }
  }
  const deploymentFor = (position: StrategyLabPosition) => deployments.find((strategy) => strategy.strategy_id === position.strategy_id || strategy.current_position?.position_id === position.position_id)
  const contractFor = (position: StrategyLabPosition) => {
    const contract = position.option_contract
    const expiry = contract?.expiry ?? position.expiry
    const month = expiry ? new Date(expiry).toLocaleString('en-IN', { month: 'short', timeZone: 'Asia/Kolkata' }).toUpperCase() : ''
    const strike = contract?.strike ?? position.strike
    const optionType = contract?.option_type ?? position.option_type
    if (strike != null && optionType) return `NIFTY ${month} ${formatNumber(strike)} ${optionType}`.replace(/\s+/g, ' ').trim()
    return position.contract ?? position.instrument ?? position.underlying ?? 'NIFTY'
  }
  const timelineTone = (event: StrategyLabTimelineEvent) => {
    const value = `${event.event_type} ${String(event.payload?.status ?? '')}`.toLowerCase()
    if (value.includes('reject') || value.includes('cancel') || value.includes('warning')) return productionStyles.warning
    if (value.includes('stop') || value.includes('error') || value.includes('exit')) return productionStyles.negative
    if (value.includes('fill') || value.includes('open') || value.includes('target')) return productionStyles.positive
    return productionStyles.info
  }
  const alerts = [
    killActive ? `KILL SWITCH ACTIVE · ${killSwitch.data?.reason ?? riskStatus.data?.kill_switch_reason ?? 'Execution blocked'}` : null,
    backendState === 'offline' ? 'BACKEND OFFLINE · Runtime telemetry unavailable' : null,
    backendState === 'degraded' ? 'CONNECTION DEGRADED · Reconnecting to authoritative projection' : null,
    !liveBlocked ? 'LIVE EXECUTION GATE OPEN · Operator intervention required' : null,
    data && !schedulerRunning ? 'SCHEDULER DEGRADED · One or more deployment clocks are not running' : null,
  ].filter((value): value is string => Boolean(value))

  if (strategyLab.loading && !data) {
    return <div className={productionStyles.terminal}><div className={productionStyles.loading}>CONNECTING TO PRODUCTION CONTROL PLANE</div></div>
  }

  return (
    <div className={productionStyles.terminal} aria-label="Production Mode execution terminal">
      <section className={`${productionStyles.alertStrip} ${alerts.length ? productionStyles.alertActive : productionStyles.alertClear}`} aria-label="Emergency Alerts">
        <strong>EMERGENCY ALERTS</strong>
        <span>{alerts.length ? alerts.join(' · ') : 'No critical alerts · execution safeguards nominal'}</span>
        <b>{alerts.length ? `${alerts.length} ACTIVE` : 'CLEAR'}</b>
      </section>

      <section className={productionStyles.engineStrip} aria-label="Engine Status">
        <div><span>ENGINE</span><strong className={managerRunning ? productionStyles.positiveText : productionStyles.warningText}>{managerRunning ? 'RUNNING' : 'STARTING'}</strong></div>
        <div><span>SCHEDULER</span><strong className={schedulerRunning ? productionStyles.positiveText : productionStyles.warningText}>{schedulerRunning ? 'RUNNING' : 'DEGRADED'}</strong></div>
        <div><span>MODE</span><strong className={paperOnly ? productionStyles.infoText : productionStyles.negativeText}>{paperOnly ? 'PAPER' : 'UNSAFE'}</strong></div>
        <div><span>LIVE ROUTING</span><strong className={liveBlocked ? productionStyles.positiveText : productionStyles.negativeText}>{liveBlocked ? 'DISABLED' : 'ENABLED'}</strong></div>
        <div><span>DEPLOYMENTS</span><strong>{deployments.filter((strategy) => strategy.state === 'RUNNING').length}/{deployments.length}</strong></div>
        <div><span>OPEN POSITIONS</span><strong>{positions.length}</strong></div>
        <div><span>ORDER QUEUE</span><strong>{execution?.order_counts?.PENDING ?? execution?.order_counts?.SUBMITTED ?? 0}</strong></div>
        <div><span>PROJECTION</span><strong>{projectionLatency == null ? '—' : `${formatNumber(projectionLatency)}ms`}</strong></div>
      </section>

      <div className={productionStyles.controlGrid}>
        <div className={productionStyles.executionColumn}>
          <section className={productionStyles.module} aria-label="Live Positions">
            <header className={productionStyles.moduleHeader}><div><span>EXECUTION / 01</span><h2>Live Positions</h2></div><b>{positions.length} OPEN</b></header>
            <div className={productionStyles.tableFrame}>
              <table><thead><tr><th>Strategy</th><th>Contract</th><th>TF</th><th>Side</th><th>Qty</th><th>Entry</th><th>Current</th><th>MTM</th><th>Stop</th><th>Target</th><th>Status</th><th>Opened</th></tr></thead><tbody>
                {positions.length ? positions.map((position) => { const deployment = deploymentFor(position); const meta = deployment ? deploymentMeta(deployment) : null; return <tr key={position.position_id ?? position.trade_id}><td>{meta?.prefix ?? 'SYS'}</td><td>{contractFor(position)}</td><td>{meta?.timeframe ?? '—'}</td><td>{humanize(position.side ?? 'BUY')}</td><td>{position.quantity ?? '—'}</td><td>{typeof (position.average_price ?? position.entry_price ?? position.entry) === 'number' ? formatPrice(position.average_price ?? position.entry_price ?? position.entry) : '—'}</td><td>{typeof position.current_price === 'number' ? formatPrice(position.current_price) : '—'}</td><td className={metricTone(position.pnl ?? position.unrealized_pnl)}>{typeof (position.pnl ?? position.unrealized_pnl) === 'number' ? formatMoney(position.pnl ?? position.unrealized_pnl) : '—'}</td><td>{typeof (position.stop ?? position.underlying_stop) === 'number' ? formatPrice(position.stop ?? position.underlying_stop) : '—'}</td><td>{typeof (position.target ?? position.underlying_target) === 'number' ? formatPrice(position.target ?? position.underlying_target) : '—'}</td><td>{humanize(position.status ?? 'OPEN')}</td><td>{position.entry_time ? formatTimeOnly(position.entry_time) : '—'}</td></tr> }) : <tr><td colSpan={12} className={productionStyles.emptyRow}>BOOK FLAT · awaiting qualified paper execution</td></tr>}
              </tbody></table>
            </div>
          </section>

          <section className={productionStyles.module} aria-label="Active Deployments">
            <header className={productionStyles.moduleHeader}><div><span>EXECUTION / 02</span><h2>Active Deployments</h2></div><b>{deployments.length} REGISTERED</b></header>
            <div className={productionStyles.deploymentRack}>
              {deployments.map((strategy) => { const meta = deploymentMeta(strategy); return <a href={`/strategy-lab/${encodeURIComponent(strategy.strategy_id)}`} className={productionStyles.deploymentBlade} key={strategy.strategy_id}><strong>{meta.prefix}</strong><b>{meta.side}</b><span>{meta.timeframe}</span><em className={strategy.state === 'RUNNING' ? productionStyles.positiveText : productionStyles.warningText}>{strategy.state}</em><span>{strategy.current_position ? 'POSITION OPEN' : 'FLAT'}</span><span>{humanize(strategy.current_decision?.signal ?? 'WAIT')}</span><span className={metricTone(strategy.current_position?.pnl ?? strategy.statistics.net_pnl)}>{formatMoney(strategy.current_position?.pnl ?? strategy.statistics.net_pnl)}</span><span>{strategy.latency_ms == null ? '—' : `${formatNumber(strategy.latency_ms)}ms`}</span><span>{strategy.scheduler?.last_tick_at ? formatTimeOnly(strategy.scheduler.last_tick_at) : 'NO CANDLE'}</span><i className={strategy.health === 'HEALTHY' ? productionStyles.healthGood : productionStyles.healthBad} /></a> })}
            </div>
          </section>

          <section className={productionStyles.module} aria-label="Execution Timeline">
            <header className={productionStyles.moduleHeader}><div><span>EXECUTION / 03</span><h2>Execution Timeline</h2></div><b>LAST {timeline.length}</b></header>
            <div className={productionStyles.timeline}>
              {timeline.length ? timeline.map((event) => { const strategy = deployments.find((item) => item.strategy_id === event.strategy_id); const meta = strategy ? deploymentMeta(strategy) : null; const pnl = typeof event.payload?.realized_pnl === 'number' ? event.payload.realized_pnl : typeof event.payload?.pnl === 'number' ? event.payload.pnl : null; return <div className={timelineTone(event)} key={event.record_id ?? `${event.strategy_id}-${event.recorded_at}-${event.event_type}`}><time>{event.recorded_at ? formatTimeOnly(event.recorded_at) : '—'}</time><i /><strong>{meta?.prefix ?? 'SYS'}</strong><span>{meta ? `${meta.side} ${meta.timeframe}` : 'RUNTIME'}</span><b>{humanize(event.event_type)}</b><em className={metricTone(pnl)}>{pnl == null ? '—' : formatMoney(pnl)}</em></div> }) : <div className={productionStyles.emptyTimeline}>No execution events recorded in the current session.</div>}
            </div>
          </section>
        </div>

        <aside className={productionStyles.controlColumn} aria-label="Production controls and health">
          <section className={productionStyles.module} aria-label="Paper Live Mode Indicator">
            <header className={productionStyles.moduleHeader}><div><span>CONTROL / 01</span><h2>Execution Mode</h2></div></header>
            <div className={productionStyles.modeLock}><strong>PAPER</strong><span>LIVE execution disabled</span><b>{paperOnly && liveBlocked ? 'LOCKED SAFE' : 'CHECK REQUIRED'}</b></div>
          </section>

          <section className={productionStyles.module} aria-label="Kill Switch">
            <header className={productionStyles.moduleHeader}><div><span>CONTROL / 02</span><h2>Kill Switch</h2></div></header>
            <div className={`${productionStyles.killSwitch} ${killActive ? productionStyles.killActive : productionStyles.killSafe}`}><strong>{killActive ? 'ACTIVE' : 'INACTIVE'}</strong><span>{killSwitch.data?.reason ?? 'Emergency execution halt is armed and available'}</span><b>{killSwitch.data?.persistence_health ?? 'UNKNOWN'}</b></div>
          </section>

          <section className={productionStyles.module} aria-label="Risk Controls">
            <header className={productionStyles.moduleHeader}><div><span>CONTROL / 03</span><h2>Risk Controls</h2></div><b>{humanize(riskStatus.data?.status ?? 'UNKNOWN')}</b></header>
            <dl className={productionStyles.controlList}>
              <div><dt>Daily P&amp;L</dt><dd className={metricTone(data?.portfolio?.today_pnl ?? paperStatus.data?.total_daily_pnl)}>{data?.portfolio?.today_pnl == null && paperStatus.data?.total_daily_pnl == null ? '—' : formatMoney(data?.portfolio?.today_pnl ?? paperStatus.data?.total_daily_pnl ?? 0)}</dd></div>
              <div><dt>Max daily loss</dt><dd>{riskStatus.data?.limits.max_daily_loss == null ? '—' : formatMoney(riskStatus.data.limits.max_daily_loss)}</dd></div>
              <div><dt>Open / limit</dt><dd>{positions.length} / {riskStatus.data?.limits.max_open_positions ?? '—'}</dd></div>
              <div><dt>Trades / limit</dt><dd>{paperStatus.data?.trades_taken_today ?? '—'} / {riskStatus.data?.limits.max_trades_per_day ?? '—'}</dd></div>
              <div><dt>Authorization</dt><dd>{humanize(riskStatus.data?.latest_authorization?.decision ?? 'NONE')}</dd></div>
              <div><dt>State health</dt><dd>{humanize(riskStatus.data?.state_health ?? 'UNKNOWN')}</dd></div>
            </dl>
          </section>

          <section className={productionStyles.module} aria-label="Order Queue">
            <header className={productionStyles.moduleHeader}><div><span>CONTROL / 04</span><h2>Order Queue</h2></div><b>{orders.length} SHOWN</b></header>
            <div className={productionStyles.orderQueue}>
              {orders.length ? orders.map((order) => <div key={order.order_id}><time>{order.created_at ? formatTimeOnly(order.created_at) : '—'}</time><strong>{order.side ?? '—'}</strong><span>{order.contract ?? order.strategy_id ?? '—'}</span><b>{order.quantity ?? '—'}</b><em className={order.status === 'FILLED' ? productionStyles.positiveText : order.status === 'REJECTED' ? productionStyles.negativeText : productionStyles.warningText}>{order.status}</em></div>) : <p>Queue clear · no orders recorded</p>}
            </div>
          </section>

          <section className={productionStyles.module} aria-label="Connection Health">
            <header className={productionStyles.moduleHeader}><div><span>CONTROL / 05</span><h2>Connection Health</h2></div><b className={backendState === 'connected' ? productionStyles.positiveText : productionStyles.warningText}>{backendState.toUpperCase()}</b></header>
            <dl className={productionStyles.controlList}>
              <div><dt>Backend</dt><dd>{backendState === 'connected' ? 'ONLINE' : backendState.toUpperCase()}</dd></div>
              <div><dt>Projection</dt><dd>{feedMeta.strategy_lab?.status ?? (data ? 'AVAILABLE' : 'WAITING')}</dd></div>
              <div><dt>Last update</dt><dd>{data?.generated_at ? formatTimeOnly(data.generated_at) : '—'}</dd></div>
              <div><dt>Paper engine</dt><dd>{humanize(paperStatus.data?.status ?? 'UNKNOWN')}</dd></div>
            </dl>
          </section>

          <section className={productionStyles.module} aria-label="Runtime Diagnostics">
            <header className={productionStyles.moduleHeader}><div><span>CONTROL / 06</span><h2>Runtime Diagnostics</h2></div><b>{humanize(data?.status.health ?? 'UNKNOWN')}</b></header>
            <dl className={productionStyles.controlList}>
              <div><dt>Loaded runtimes</dt><dd>{data?.status.loaded_runtime_count ?? '—'}</dd></div>
              <div><dt>Manager</dt><dd>{managerRunning ? 'STARTED' : 'STOPPED'}</dd></div>
              <div><dt>Order ledger</dt><dd>{humanize(orderLedger.data?.health ?? 'UNKNOWN')}</dd></div>
              <div><dt>Broker submission</dt><dd>{orderLedger.data?.broker_submission ?? 'DISABLED'}</dd></div>
              <div><dt>Projection error</dt><dd>{strategyLab.error ?? 'NONE'}</dd></div>
            </dl>
          </section>
        </aside>
      </div>
    </div>
  )
}

function TradingWorkspace(props: {
  strategyLab: FeedState<StrategyLabDashboard>
  strategiesCommand: FeedState<StrategyCommandProjection>
  mission: FeedState<MissionControl>
  performance: FeedState<PerformanceStats>
  kronos: FeedState<KronosGauge>
  kronosAlpha: FeedState<KronosAlphaStatus>
  chronos2: FeedState<Chronos2Status>
  argus: FeedState<ArgusResponse>
  athena: FeedState<AthenaWheel>
  oracle: FeedState<OracleReasoning>
  hermes: FeedState<HermesStatus>
  personalOracle: FeedState<PersonalOracleSummary>
  aegis: FeedState<AegisDecision>
  readiness: FeedState<OpenMarketReadiness>
  nextSessionPlan: FeedState<NextSessionPlan>
  orderLedger: FeedState<OrderLedgerStatus>
  comparison: FeedState<StrategyComparisonPayload>
  feedMeta: Record<string, V2Feed['meta']>
  forecastProjectionMeta: { kronosAlpha: ForecastProjectionMeta; chronos2: ForecastProjectionMeta } | null
  headerUpdatedAt: string | number | Date | null
  selectedSymbol: string
  onSymbolChange: (symbol: string) => void
  onRetry: () => void
  retrying: boolean
}) {
  const { strategyLab, strategiesCommand, comparison, performance, kronosAlpha, chronos2, argus, personalOracle, aegis, readiness, nextSessionPlan, orderLedger, forecastProjectionMeta, feedMeta, headerUpdatedAt, selectedSymbol, onSymbolChange, onRetry, retrying } = props
  const data = strategyLab.data
  const portfolio = data?.portfolio
  const execution = data?.execution
  const review = data?.review

  if (strategyLab.loading && !data) return <div className="trading-workspace"><WidgetLoading label="Loading Trading Workspace" /></div>
  if (!data) return <div className="trading-workspace"><FeedPlaceholder error={strategyLab.error} label="Strategy Lab trading workspace" /></div>

  const deployments = data.strategies
  const optionDeployments = deployments.filter((strategy) => /^(PB|BO)_NIFTY_(CE|PE)_(1M|3M)$/.test(strategy.strategy_id))
  const positions = (execution?.authoritative_open_positions ?? execution?.positions
    ?? optionDeployments.flatMap((strategy) => strategy.current_position ? [strategy.current_position] : []))
    .filter((position) => String(position.status ?? 'OPEN').toUpperCase() === 'OPEN')
  const schedulerRunning = deployments.length === 10 && deployments.every((strategy) => strategy.scheduler?.state === 'RUNNING')
  const journal = [...(review?.journal ?? [])]
    .filter((record) => record.event_type !== 'STRATEGY_DECISION' || String(record.payload?.signal ?? 'WAIT').toUpperCase() !== 'WAIT')
    .sort((left, right) => (right.recorded_at ?? '').localeCompare(left.recorded_at ?? ''))
    .slice(0, 10)
  const timeline = [...(execution?.timeline ?? [])]
    .sort((left, right) => (right.recorded_at ?? '').localeCompare(left.recorded_at ?? ''))
  const generatedDate = data.generated_at.slice(0, 10)
  const ordersToday = execution?.orders.filter((order) => order.created_at?.slice(0, 10) === generatedDate).length ?? 0
  const countOrders = (status: string) => execution?.orders.filter((order) => order.status.toUpperCase() === status).length ?? 0
  const deploymentFor = (position: StrategyLabPosition) => deployments.find((strategy) =>
    strategy.strategy_id === position.strategy_id || strategy.current_position?.position_id === position.position_id)
  const deploymentMeta = (strategy: StrategyLabStrategy) => {
    const option = /^(PB|BO)_NIFTY_(CE|PE)_(1M|3M)$/.exec(strategy.strategy_id)
    const prefix = option?.[1] ?? (strategy.strategy_id.toLowerCase().includes('pullback') ? 'PB' : 'BO')
    const side = option?.[2] ?? strategy.current_decision?.option_contract?.option_type ?? 'NIFTY'
    const configuredTimeframe = strategy.metadata.supported_timeframes?.[0]
    const timeframe = option?.[3]?.toLowerCase() ?? (configuredTimeframe && configuredTimeframe !== 'CHART_TIMEFRAME' ? configuredTimeframe : '5m')
    return { prefix, side, timeframe }
  }
  const lifecycleExitLabel = (reason: string | null | undefined, status?: string) => {
    const normalized = (reason ?? status ?? 'OPEN').toUpperCase().replaceAll('-', '_').replaceAll(' ', '_')
    if (normalized.includes('TRAIL')) return 'TRAILING STOP'
    if (normalized.includes('STOP')) return 'STOP LOSS'
    if (normalized.includes('TARGET')) return 'TARGET HIT'
    if (normalized.includes('SQUARE')) return 'SQUARE OFF'
    if (normalized.includes('MANUAL')) return 'MANUAL EXIT'
    if (normalized.includes('SESSION')) return 'SESSION EXIT'
    if (normalized.includes('AUTO')) return 'AUTO EXIT'
    if (normalized.includes('REJECT')) return 'REJECTED'
    if (normalized.includes('FAIL')) return 'FAILED'
    return normalized === 'OPEN' ? 'OPEN' : humanize(normalized)
  }
  const lifecycleDuration = (start: string | null | undefined, end: string | null | undefined, explicit?: number) => {
    const seconds = typeof explicit === 'number' && Number.isFinite(explicit)
      ? explicit
      : start && end ? (new Date(end).getTime() - new Date(start).getTime()) / 1_000 : null
    if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—'
    const wholeSeconds = Math.floor(seconds)
    const hours = Math.floor(wholeSeconds / 3_600)
    const minutes = Math.floor((wholeSeconds % 3_600) / 60)
    const remainder = wholeSeconds % 60
    return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${String(remainder).padStart(2, '0')}s` : `${remainder}s`
  }
  const nearestOrder = (strategyId: string | undefined, effect: 'OPEN' | 'CLOSE', timestamp: string | null | undefined) => {
    if (!timestamp) return undefined
    const target = new Date(timestamp).getTime()
    return execution?.orders
      .filter((order) => order.strategy_id === strategyId)
      .map((order) => ({ order, distance: Math.abs(new Date(order.created_at ?? order.updated_at ?? '').getTime() - target) }))
      .filter(({ distance, order }) => Number.isFinite(distance) && distance < 5_000 && (effect === 'OPEN' ? order.side?.toUpperCase() === 'BUY' : order.side?.toUpperCase() === 'SELL'))
      .sort((left, right) => left.distance - right.distance)[0]?.order
  }
  const lifecycleCards = [
    ...(execution?.closed_trades ?? []).map((trade) => {
      const strategy = deployments.find((item) => item.strategy_id === trade.strategy_id)
      const meta = strategy ? deploymentMeta(strategy) : null
      const entryOrder = nearestOrder(trade.strategy_id, 'OPEN', trade.entry_time)
      const exitOrder = nearestOrder(trade.strategy_id, 'CLOSE', trade.exit_time)
      const entryFill = execution?.fills.find((fill) => fill.order_id === entryOrder?.order_id)
      const exitFill = execution?.fills.find((fill) => fill.order_id === exitOrder?.order_id)
      const option = trade.option_contract as (StrategyLabPosition['option_contract'] & { underlying?: string; lot_size?: number }) | undefined
      const pnl = trade.realized_pnl ?? trade.pnl ?? 0
      const occurredAt = trade.exit_time ?? trade.entry_time ?? data.generated_at
      const entryAt = trade.entry_time ?? occurredAt
      const exitAt = trade.exit_time ?? occurredAt
      const entryMs = new Date(entryAt).getTime()
      const exitMs = new Date(exitAt).getTime()
      const rawEvents = timeline.filter((event) => event.strategy_id === trade.strategy_id && event.recorded_at && new Date(event.recorded_at).getTime() >= entryMs - 1_000 && new Date(event.recorded_at).getTime() <= exitMs + 1_000)
      const fillLatency = entryOrder?.created_at && entryFill?.time ? Math.max(0, new Date(entryFill.time).getTime() - new Date(entryOrder.created_at).getTime()) : null
      const quantity = entryFill?.quantity ?? entryOrder?.filled_quantity ?? option?.lot_size ?? trade.quantity ?? 0
      const exitLabel = lifecycleExitLabel(trade.exit_reason, trade.status)
      return {
        id: trade.trade_id ?? trade.position_id ?? `${trade.strategy_id}-${occurredAt}`,
        priority: fillLatency != null && fillLatency > 1_000 ? 3 : 5,
        occurredAt,
        entryAt,
        exitAt,
        strategyId: trade.strategy_id ?? 'SYSTEM',
        strategy: meta?.prefix === 'PB' ? 'PULLBACK' : meta?.prefix === 'BO' ? 'BREAKOUT' : humanize(strategy?.metadata.name ?? trade.strategy_id ?? 'STRATEGY'),
        instrument: meta?.side === 'CE' || meta?.side === 'PE' ? `NIFTY ${meta.side}` : `${option?.underlying ?? 'NIFTY'} ${option?.option_type ?? ''}`.trim(),
        timeframe: meta?.timeframe ?? '—',
        direction: (trade.side ?? 'LONG').toUpperCase(),
        outcome: exitLabel,
        entry: trade.average_price ?? trade.entry_price ?? trade.entry ?? entryFill?.price ?? null,
        exit: trade.exit ?? trade.current_price ?? exitFill?.price ?? null,
        quantity,
        duration: lifecycleDuration(entryAt, exitAt, trade.duration_seconds),
        pnl,
        state: 'COMPLETED',
        entryOrder,
        exitOrder,
        entryFill,
        exitFill,
        fillLatency,
        partialFills: [entryOrder, exitOrder].filter((order) => order && typeof order.filled_quantity === 'number' && order.filled_quantity < quantity).length,
        rawEvents,
      }
    }),
    ...positions.map((trade) => {
      const strategy = deployments.find((item) => item.strategy_id === trade.strategy_id)
      const meta = strategy ? deploymentMeta(strategy) : null
      const entryOrder = nearestOrder(trade.strategy_id, 'OPEN', trade.entry_time)
      const entryFill = execution?.fills.find((fill) => fill.order_id === entryOrder?.order_id)
      const option = trade.option_contract as (StrategyLabPosition['option_contract'] & { underlying?: string; lot_size?: number }) | undefined
      const entryAt = trade.entry_time ?? data.generated_at
      const entryMs = new Date(entryAt).getTime()
      const rawEvents = timeline.filter((event) => event.strategy_id === trade.strategy_id && event.recorded_at && new Date(event.recorded_at).getTime() >= entryMs - 1_000)
      const fillLatency = entryOrder?.created_at && entryFill?.time ? Math.max(0, new Date(entryFill.time).getTime() - new Date(entryOrder.created_at).getTime()) : null
      return {
        id: trade.trade_id ?? trade.position_id ?? `${trade.strategy_id}-${entryAt}`,
        priority: fillLatency != null && fillLatency > 1_000 ? 3 : 4,
        occurredAt: entryAt,
        entryAt,
        exitAt: null,
        strategyId: trade.strategy_id ?? 'SYSTEM',
        strategy: meta?.prefix === 'PB' ? 'PULLBACK' : meta?.prefix === 'BO' ? 'BREAKOUT' : humanize(strategy?.metadata.name ?? trade.strategy_id ?? 'STRATEGY'),
        instrument: meta?.side === 'CE' || meta?.side === 'PE' ? `NIFTY ${meta.side}` : `${option?.underlying ?? 'NIFTY'} ${option?.option_type ?? ''}`.trim(),
        timeframe: meta?.timeframe ?? '—',
        direction: (trade.side ?? 'LONG').toUpperCase(),
        outcome: 'OPEN',
        entry: trade.average_price ?? trade.entry_price ?? trade.entry ?? entryFill?.price ?? null,
        exit: trade.current_price ?? null,
        quantity: entryFill?.quantity ?? entryOrder?.filled_quantity ?? option?.lot_size ?? trade.quantity ?? 0,
        duration: lifecycleDuration(entryAt, data.generated_at, trade.duration_seconds),
        pnl: trade.pnl ?? trade.unrealized_pnl ?? null,
        state: 'OPEN',
        entryOrder,
        exitOrder: undefined,
        entryFill,
        exitFill: undefined,
        fillLatency,
        partialFills: 0,
        rawEvents,
      }
    }),
    ...(execution?.orders ?? []).filter((order) => ['FAILED', 'REJECTED'].includes(order.status.toUpperCase())).map((order) => {
      const strategy = deployments.find((item) => item.strategy_id === order.strategy_id)
      const meta = strategy ? deploymentMeta(strategy) : null
      const requestedQuantity = (order as StrategyLabOrder & { requested_quantity?: number }).requested_quantity
      return {
        id: order.order_id,
        priority: order.status.toUpperCase() === 'FAILED' ? 1 : 2,
        occurredAt: order.updated_at ?? order.created_at ?? data.generated_at,
        entryAt: order.created_at ?? null,
        exitAt: order.updated_at ?? null,
        strategyId: order.strategy_id ?? 'SYSTEM',
        strategy: meta?.prefix === 'PB' ? 'PULLBACK' : meta?.prefix === 'BO' ? 'BREAKOUT' : humanize(strategy?.metadata.name ?? order.strategy_id ?? 'STRATEGY'),
        instrument: meta?.side === 'CE' || meta?.side === 'PE' ? `NIFTY ${meta.side}` : order.contract ?? 'NIFTY',
        timeframe: meta?.timeframe ?? '—',
        direction: (order.side ?? 'ORDER').toUpperCase(),
        outcome: lifecycleExitLabel(order.rejection_reason, order.status),
        entry: null,
        exit: null,
        quantity: requestedQuantity ?? order.quantity ?? order.filled_quantity ?? 0,
        duration: lifecycleDuration(order.created_at, order.updated_at),
        pnl: null,
        state: order.status.toUpperCase(),
        entryOrder: order,
        exitOrder: undefined,
        entryFill: undefined,
        exitFill: undefined,
        fillLatency: null,
        partialFills: 0,
        rawEvents: timeline.filter((event) => event.entity_id === order.order_id),
      }
    }),
  ].sort((left, right) => left.priority - right.priority || right.occurredAt.localeCompare(left.occurredAt)).slice(0, 6)
  const completedTimelineTrades = execution?.closed_trades?.length ?? 0
  const timelineNet = execution?.closed_trades?.reduce((sum, trade) => sum + (trade.realized_pnl ?? trade.pnl ?? 0), 0) ?? 0
  const timelineDate = lifecycleCards[0]?.occurredAt
    ? new Date(lifecycleCards[0].occurredAt).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase()
    : 'CURRENT SESSION'
  const valueFrom = (record: StrategyLabReviewRecord, ...keys: string[]) => {
    for (const key of keys) {
      const value = record.payload?.[key]
      if (typeof value === 'number' && Number.isFinite(value)) return formatPrice(value)
      if (typeof value === 'string' && value.trim()) return humanize(value)
    }
    return '—'
  }
  const durationFor = (position: StrategyLabPosition) => {
    if (typeof position.duration_seconds === 'number' && position.duration_seconds > 0) return formatDuration(position.duration_seconds)
    if (!position.entry_time) return '—'
    const elapsed = (new Date(data.generated_at).getTime() - new Date(position.entry_time).getTime()) / 1_000
    return Number.isFinite(elapsed) && elapsed >= 0 ? formatDuration(elapsed) : '—'
  }
  const currentRRFor = (position: StrategyLabPosition) => {
    if (typeof position.rr === 'number') return position.rr
    const entry = position.average_price ?? position.entry_price ?? position.entry
    const stop = position.stop ?? position.underlying_stop
    const current = position.current_price
    if (typeof entry === 'number' && typeof stop === 'number' && typeof current === 'number') {
      const risk = Math.abs(entry - stop)
      if (risk > 0 && risk <= Math.abs(entry) * 0.8) {
        return (position.side ?? 'LONG').toUpperCase() === 'SHORT' ? (entry - current) / risk : (current - entry) / risk
      }
    }
    return null
  }
  const positionValues = (position: StrategyLabPosition) => {
    const deployment = deploymentFor(position)
    const entry = position.average_price ?? position.entry_price ?? position.entry ?? null
    const current = position.current_price ?? null
    const stop = position.stop ?? position.underlying_stop ?? null
    const target = position.target ?? position.underlying_target ?? null
    const side = (position.side ?? 'LONG').toUpperCase()
    const quoteUsable = position.quote_status == null || position.quote_status === 'FRESH'
    const stopBreached = position.stop_breach?.breached === true || (quoteUsable && typeof current === 'number' && typeof stop === 'number' && (side === 'SHORT' ? current > stop : current < stop))
    return { deployment, entry, current, stop, target, side, stopBreached }
  }
  const heldContractDetails = (position: StrategyLabPosition, meta: ReturnType<typeof deploymentMeta> | null) => {
    const option = position.option_contract
    const underlying = position.underlying ?? option?.underlying ?? 'NIFTY'
    const expiry = position.expiry ?? option?.expiry
    const strike = position.strike ?? option?.strike
    const optionType = position.option_type ?? option?.option_type ?? (meta?.side === 'CE' || meta?.side === 'PE' ? meta.side : null)
    const strikeLabel = typeof strike === 'number' ? formatNumber(strike) : strike
    const rawContract = position.contract?.trim() || position.instrument?.trim() || ''
    const primary = strikeLabel && optionType
      ? `${underlying} ${strikeLabel} ${optionType}`
      : rawContract && !/^\d+$/.test(rawContract) ? rawContract : [underlying, optionType].filter(Boolean).join(' ')
    const expiryLabel = expiry
      ? new Date(`${expiry}T00:00:00+05:30`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' })
      : 'Expiry not reported'
    const expirySymbol = expiry
      ? new Date(`${expiry}T00:00:00+05:30`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' }).toUpperCase()
      : ''
    const tradingSymbol = option?.trading_symbol
      ?? (strikeLabel && optionType ? [underlying, expirySymbol, strikeLabel, optionType].filter(Boolean).join(' ') : rawContract || primary)
    return { primary, expiryLabel, tradingSymbol }
  }
  const heldContractLabel = (position: StrategyLabPosition, meta: ReturnType<typeof deploymentMeta> | null) => heldContractDetails(position, meta).primary
  const rankedPositions = [...positions].sort((left, right) => {
    const leftValues = positionValues(left)
    const rightValues = positionValues(right)
    if (leftValues.stopBreached !== rightValues.stopBreached) return leftValues.stopBreached ? -1 : 1
    const leftMtm = left.pnl ?? left.unrealized_pnl ?? 0
    const rightMtm = right.pnl ?? right.unrealized_pnl ?? 0
    if (leftMtm !== rightMtm) return leftMtm - rightMtm
    return (currentRRFor(left) ?? 0) - (currentRRFor(right) ?? 0)
  })
  const positionMtm = rankedPositions.reduce((sum, position) => sum + (position.pnl_valid === false ? 0 : (position.pnl ?? position.unrealized_pnl ?? 0)), 0)
  const positionExposure = portfolio?.exposure ?? portfolio?.used_capital ?? rankedPositions.reduce((sum, position) => {
    const { entry } = positionValues(position)
    return sum + (typeof entry === 'number' ? Math.abs(entry * (position.quantity ?? 1)) : 0)
  }, 0)
  const closedRR = execution?.closed_trades.map((trade) => trade.rr).filter((value): value is number => typeof value === 'number') ?? []
  const latencySamples = deployments.map((strategy) => strategy.latency_ms).filter((value): value is number => typeof value === 'number')
  const averageLatency = latencySamples.length ? latencySamples.reduce((sum, value) => sum + value, 0) / latencySamples.length : null
  const lastCandleAt = deployments.map((strategy) => strategy.scheduler?.last_tick_at).filter((value): value is string => Boolean(value)).sort().at(-1)
  const filledOrders = countOrders('FILLED')
  const overview = [
    { label: 'Capital', value: portfolio?.current_capital == null && portfolio?.total_equity == null ? '—' : formatMoney(portfolio.current_capital ?? portfolio.total_equity ?? 0), detail: 'Paper equity', tone: 'neutral' },
    { label: 'Available Capital', value: portfolio?.available_capital == null ? '—' : formatMoney(portfolio.available_capital), detail: 'Unallocated', tone: 'neutral' },
    { label: 'Exposure', value: portfolio?.exposure == null && portfolio?.used_capital == null ? '—' : formatMoney(portfolio.exposure ?? portfolio.used_capital ?? 0), detail: 'Capital deployed', tone: 'neutral' },
    { label: "Today's P&L", value: portfolio?.today_pnl == null ? '—' : formatMoney(portfolio.today_pnl), detail: 'Realized + live', tone: metricTone(portfolio?.today_pnl) },
    { label: 'Live MTM', value: execution?.mtm?.status === 'UNAVAILABLE' ? 'MTM UNAVAILABLE' : execution?.mtm?.status === 'PARTIAL' ? `${formatMoney(execution.mtm.live_mtm ?? 0)} PARTIAL` : execution?.mtm?.live_mtm != null ? formatMoney(execution.mtm.live_mtm) : portfolio?.open_pnl == null ? '—' : formatMoney(portfolio.open_pnl), detail: 'Open positions', tone: metricTone(execution?.mtm?.live_mtm ?? portfolio?.open_pnl) },
    { label: 'Risk', value: portfolio?.risk_usage == null ? '—' : formatPercent(portfolio.risk_usage), detail: 'Portfolio limit', tone: 'neutral' },
    { label: 'Win Rate', value: portfolio?.win_rate == null ? '—' : formatPercent(portfolio.win_rate), detail: 'Closed trades', tone: 'neutral' },
    { label: 'Open Positions', value: formatInteger(positions.length), detail: 'Paper positions', tone: positions.length ? 'blue' : 'neutral' },
    { label: 'Latency', value: averageLatency == null ? '—' : `${formatNumber(averageLatency)}ms`, detail: 'Runtime average', tone: 'neutral' },
    { label: 'Completed Candles', value: lastCandleAt ? formatTimeOnly(lastCandleAt) : 'Waiting', detail: 'Latest close', tone: lastCandleAt ? 'positive' : 'neutral' },
    { label: 'Connection', value: strategyLab.error ? 'Degraded' : 'Connected', detail: 'Backend projection', tone: strategyLab.error ? 'negative' : 'positive' },
    { label: 'Health', value: `${deployments.filter((strategy) => strategy.health === 'HEALTHY').length} / ${deployments.length}`, detail: schedulerRunning ? 'All systems running' : 'Scheduler starting', tone: schedulerRunning ? 'positive' : 'neutral' },
  ]
  const primaryOverviewLabels = ["Today's P&L", 'Live MTM', 'Open Positions', 'Exposure']
  const primaryOverview = primaryOverviewLabels.flatMap((label) => overview.find((item) => item.label === label) ?? [])
  const secondaryOverview = overview.filter((item) => !primaryOverviewLabels.includes(item.label))
  const workspaceDeployments = deployments.filter((strategy) => /^(PB|BO)_NIFTY_(CE|PE)_(1M|3M)$/.test(strategy.strategy_id))
  const deploymentPnl = (strategy: StrategyLabStrategy) => strategy.current_positions?.length
    ? strategy.current_positions.reduce((sum, position) => sum + (position.pnl_valid === false ? 0 : position.pnl ?? position.unrealized_pnl ?? 0), 0)
    : strategy.current_position?.pnl ?? strategy.current_position?.unrealized_pnl ?? strategy.statistics.net_pnl
  const deploymentState = (strategy: StrategyLabStrategy) => {
    const state = strategy.state.toUpperCase()
    const health = strategy.health.toUpperCase()
    if (state.includes('FAIL') || health.includes('FAIL')) return { label: 'FAILED', rank: 4, rail: workspaceStyles.deploymentFailed }
    if (state.includes('DISCONNECT') || health.includes('DISCONNECT')) return { label: 'DISCONNECTED', rank: 3, rail: workspaceStyles.deploymentFailed }
    if ((strategy.current_position_count ?? strategy.current_positions?.length ?? (strategy.current_position ? 1 : 0)) > 0) return { label: 'OPEN', rank: 0, rail: workspaceStyles.deploymentAttention }
    if (state === 'RUNNING' && health === 'HEALTHY') return { label: 'RUNNING', rank: 1, rail: workspaceStyles.deploymentHealthy }
    return { label: humanize(strategy.state), rank: 2, rail: workspaceStyles.deploymentAttention }
  }
  const sortedDeployments = [...workspaceDeployments].sort((left, right) => deploymentState(left).rank - deploymentState(right).rank || left.strategy_id.localeCompare(right.strategy_id))
  const runningDeployments = workspaceDeployments.filter((strategy) => strategy.state.toUpperCase() === 'RUNNING').length
  const openDeployments = workspaceDeployments.filter((strategy) => (strategy.current_position_count ?? strategy.current_positions?.length ?? (strategy.current_position ? 1 : 0)) > 0).length
  const failedDeployments = workspaceDeployments.filter((strategy) => deploymentState(strategy).label === 'FAILED').length
  const deploymentNetMtm = workspaceDeployments.reduce((sum, strategy) => sum + deploymentPnl(strategy), 0)
  const healthyDeployments = workspaceDeployments.filter((strategy) => strategy.health.toUpperCase() === 'HEALTHY').length
  const deploymentHealth = workspaceDeployments.length ? (healthyDeployments / workspaceDeployments.length) * 100 : 0
  const deploymentSparkline = (strategy: StrategyLabStrategy) => {
    const history = strategy.statistics.equity_curve?.filter((value) => Number.isFinite(value)).slice(-16) ?? []
    const samples = history.length > 1 ? history : [deploymentPnl(strategy), deploymentPnl(strategy)]
    const low = Math.min(...samples)
    const high = Math.max(...samples)
    const span = high - low || 1
    const points = samples.map((value, index) => `${(index / Math.max(1, samples.length - 1)) * 100},${18 - ((value - low) / span) * 14}`).join(' ')
    const change = samples.at(-1)! - samples[0]
    return { points, tone: change > 0 ? workspaceStyles.sparkPositive : change < 0 ? workspaceStyles.sparkNegative : workspaceStyles.sparkFlat }
  }
  const journalSignal = (record: StrategyLabReviewRecord) => valueFrom(record, 'signal', 'side') !== '—' ? valueFrom(record, 'signal', 'side').toUpperCase() : humanize(record.event_type ?? 'Event').toUpperCase()
  const journalSignalTone = (signal: string) => signal.includes('BUY') ? workspaceStyles.signalBuy : signal.includes('SELL') ? workspaceStyles.signalSell : signal.includes('LONG') ? workspaceStyles.signalLong : signal.includes('SHORT') ? workspaceStyles.signalShort : workspaceStyles.signalNeutral
  const journalPnl = (record: StrategyLabReviewRecord) => {
    const value = record.payload?.realized_pnl ?? record.payload?.pnl
    return typeof value === 'number' && Number.isFinite(value) ? value : null
  }
  const journalReason = (record: StrategyLabReviewRecord) => {
    const raw = valueFrom(record, 'reason', 'exit_reason') !== '—' ? valueFrom(record, 'reason', 'exit_reason') : humanize(record.event_type ?? 'Lifecycle event')
    const sentence = raw.replaceAll('_', ' ').toLowerCase()
    return sentence ? `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)}` : '—'
  }
  const journalTimestamp = (value: string | undefined) => {
    if (!value) return { date: '—', time: '—' }
    const timestamp = new Date(value)
    if (Number.isNaN(timestamp.getTime())) return { date: value, time: '' }
    return {
      date: timestamp.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }),
      time: timestamp.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true }).toUpperCase(),
    }
  }
  const renderPositionHero = (position: StrategyLabPosition) => {
    const { deployment, entry, current, stop, target, side, stopBreached } = positionValues(position)
    const meta = deployment ? deploymentMeta(deployment) : null
    const mtm = position.pnl_valid === false ? null : position.pnl ?? position.unrealized_pnl ?? null
    const rr = currentRRFor(position)
    const move = typeof entry === 'number' && typeof current === 'number' && entry !== 0 ? ((current - entry) / entry) * 100 : null
    const quantity = position.quantity ?? 1
    const lotSize = position.option_contract?.lot_size
    const lots = lotSize && quantity ? quantity / lotSize : null
    const capital = typeof entry === 'number' ? Math.abs(entry * quantity) : null
    const values = [entry, current, stop, target].filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
    const low = values.length ? Math.min(...values) : 0
    const high = values.length ? Math.max(...values) : 1
    const span = high - low || 1
    const railPosition = (value: number | null) => value == null ? 50 : 4 + ((value - low) / span) * 92
    const currentPoint = railPosition(current)
    const stopPoint = railPosition(stop)
    const entryPoint = railPosition(entry)
    const targetPoint = railPosition(target)
    const segmentStyle = (from: number, to: number): CSSProperties => ({ left: `${Math.min(from, to)}%`, width: `${Math.abs(to - from)}%` })
    const updatedAge = Math.max(0, (Date.now() - new Date(data.generated_at).getTime()) / 1_000)
    const updatedLabel = updatedAge < 60 ? 'Just now' : formatTimeOnly(data.generated_at)
    const strategyLabel = meta?.prefix === 'PB' ? 'Pullback' : meta?.prefix === 'BO' ? 'Breakout' : deployment?.metadata.name ?? 'Strategy'
    const contractIdentity = heldContractDetails(position, meta)
    const instrument = contractIdentity.primary
    const positionId = position.position_id ?? position.trade_id ?? `${position.strategy_id ?? 'strategy'}-${position.entry_time ?? 'open'}`
    const securityId = position.option_contract?.security_id

    return (
      <article className={`${workspaceStyles.positionHero} ${stopBreached ? workspaceStyles.positionDanger : ''}`} data-position-id={positionId}>
        <aside className={workspaceStyles.positionIdentity}>
          <div className={workspaceStyles.positionTitle}><strong>{strategyLabel}</strong><i /><b title={securityId == null ? instrument : `${instrument} · Security ID ${securityId}`}>{instrument}</b><small>{contractIdentity.expiryLabel} · {contractIdentity.tradingSymbol}</small><i /><em>{meta?.timeframe ?? '—'}</em></div>
          <div className={workspaceStyles.positionStatus}><span>{side} / {humanize(position.status ?? 'OPEN')}</span><i /></div>
          <div className={workspaceStyles.liveMtm}><span>Live MTM <i /></span><strong className={metricTone(mtm)}>{position.pnl_status === 'MTM_STALE' ? 'MTM STALE' : position.pnl_status === 'MTM_UNAVAILABLE' || mtm == null ? 'MTM UNAVAILABLE' : formatMoney(mtm)}</strong><b className={metricTone(rr)}>{rr == null ? '—' : `${formatNumber(rr)}R`}</b></div>
          {stopBreached ? <div className={workspaceStyles.positionWarning}><strong>STOP BREACHED</strong><span>Position still open</span></div> : <div className={workspaceStyles.positionNominal}><strong>RISK MONITORED</strong><span>Position within stop boundary</span></div>}
        </aside>

        <div className={workspaceStyles.positionExecution}>
          <div className={workspaceStyles.priceMetrics}>
            <div><span>Entry</span><strong>{entry == null ? '—' : formatMoney(entry)}</strong></div>
            <div><span>LTP</span><strong className={stopBreached ? 'negative' : ''}>{position.quote_status === 'UNAVAILABLE' ? 'QUOTE UNAVAILABLE' : current == null ? '—' : formatMoney(current)}</strong></div>
            <div><span>SL</span><strong>{stop == null ? '—' : formatMoney(stop)}</strong></div>
            <div><span>Target</span><strong>{target == null ? '—' : formatMoney(target)}</strong></div>
            <div><span>Percentage Move</span><strong className={metricTone(move)}>{move == null ? '—' : formatPercent(move)}</strong></div>
          </div>

          <div className={workspaceStyles.priceJourney} aria-label="Position price journey">
            <div className={workspaceStyles.railBase} />
            <div className={`${workspaceStyles.railSegment} ${workspaceStyles.railDanger}`} style={segmentStyle(currentPoint, stopPoint)} />
            <div className={`${workspaceStyles.railSegment} ${workspaceStyles.railRisk}`} style={segmentStyle(stopPoint, entryPoint)} />
            <div className={`${workspaceStyles.railSegment} ${workspaceStyles.railTarget}`} style={segmentStyle(entryPoint, targetPoint)} />
            {[
              { label: 'LTP', value: current, point: currentPoint, tone: workspaceStyles.markerCurrent },
              { label: 'Stop Loss', value: stop, point: stopPoint, tone: workspaceStyles.markerStop },
              { label: 'Entry', value: entry, point: entryPoint, tone: workspaceStyles.markerEntry },
              { label: 'Target', value: target, point: targetPoint, tone: workspaceStyles.markerTarget },
            ].map((marker) => <div className={`${workspaceStyles.railMarker} ${marker.tone}`} style={{ left: `${marker.point}%` }} key={marker.label}><i /><strong>{marker.value == null ? '—' : formatMoney(marker.value)}</strong><span>{marker.label}</span></div>)}
          </div>

          <div className={workspaceStyles.positionMetadata}>
            <div><span>Open Duration</span><strong>{durationFor(position)}</strong></div>
            <div><span>Opened</span><strong>{position.entry_time ? formatTimeOnly(position.entry_time) : '—'}</strong></div>
            <div><span>Quantity / Lots</span><strong>{formatInteger(quantity)}{lots == null ? '' : ` / ${formatNumber(lots)}`}</strong></div>
            <div><span>Capital Deployed</span><strong>{capital == null ? '—' : formatMoney(capital)}</strong></div>
            <div><span>Updated</span><strong title={position.quote_stale_reason ?? position.quote_source ?? undefined}>{position.quote_timestamp ? formatTimeOnly(position.quote_timestamp) : updatedLabel}<i /></strong></div>
          </div>
        </div>
      </article>
    )
  }

  return (
    <div className={`trading-workspace ${workspaceStyles.cockpit}`} aria-label="Trading Workspace">
      <DesignCard as="section" unstyled className={`panel workspace-unified-section workspace-operator-panel ${workspaceStyles.summaryPanel}`} aria-label="Operator Summary">
        <SectionHeading eyebrow="01 / Trading Workspace" title="Operator Summary" error={strategyLab.error} status={strategyLab.error ? 'stale' : 'live'} aside="Authoritative paper state" />
        <div className={workspaceStyles.summaryMatrix}>
          <div className={workspaceStyles.primaryMetrics}>
            {primaryOverview.map((item) => <DesignMetricCard unstyled className={`${workspaceStyles.metric} ${workspaceStyles.primaryMetric} ${item.tone}`} key={item.label} label={item.label} value={item.value} detail={item.detail} />)}
          </div>
          <div className={workspaceStyles.secondaryMetrics}>
            {secondaryOverview.map((item) => <DesignMetricCard unstyled className={`${workspaceStyles.metric} ${item.tone}`} key={item.label} label={item.label} value={item.value} detail={item.detail} />)}
          </div>
        </div>
      </DesignCard>

      <NiftyVOBPanel
        data={strategyLab.data?.execution?.nifty_vob || (feedMeta.strategy_lab as unknown as { execution?: { nifty_vob?: NiftyVOBData } })?.execution?.nifty_vob}
        verifiedTime={headerUpdatedAt ? String(formatTimeOnly(typeof headerUpdatedAt === 'number' || typeof headerUpdatedAt === 'string' ? headerUpdatedAt : headerUpdatedAt.getTime())) : undefined}
      />

      <OptionsStructurePanel
        data={strategyLab.data?.execution?.options_structure ?? null}
        argusWriter={argus.loading
          ? <ArgusLoading />
          : argus.data
            ? <ArgusWriterDominatedPanel data={argus.data} error={argus.error} onRetry={onRetry} retrying={retrying} selectedSymbol={selectedSymbol} onSymbolChange={onSymbolChange} />
            : <ArgusUnavailable error={argus.error} />}
        tacticalEdge={<ArgusPrimePanel
          data={argus.data?.data?.tactical_edge}
          onRetry={onRetry}
          retrying={retrying}
        />}
      />

      <UnifiedOptionBuyerCommandDeck />

      <PremiumIntelligenceCards />

      <ArgusEdgeLabPanel
        data={strategiesCommand.data?.edge_lab}
        loading={strategiesCommand.loading}
        error={strategiesCommand.error}
      />

      <div className={`${workspaceStyles.operationalGrid} ${positions.length ? workspaceStyles.hasPositions : workspaceStyles.flatBook}`}>
      <section className={`panel workspace-unified-section ${workspaceStyles.panel} ${workspaceStyles.deploymentPanel}`} aria-label="Active Deployments">
        <SectionHeading eyebrow="02 / Trading Workspace" title="Active Deployments" error={strategyLab.error} status={schedulerRunning ? 'live' : 'connecting'} />
        <div className={workspaceStyles.deploymentSummary}><span>Running <strong>{formatInteger(runningDeployments)}</strong></span><i /><span>Open <strong>{formatInteger(openDeployments)}</strong></span><i /><span>Failed <strong className={failedDeployments ? 'negative' : ''}>{formatInteger(failedDeployments)}</strong></span><i /><span>Net MTM <strong className={metricTone(deploymentNetMtm)}>{formatMoney(deploymentNetMtm)}</strong></span><i /><span>Average Health <strong>{formatPercent(deploymentHealth)}</strong></span></div>
        <div className="workspace-deployment-groups">
          {(['PB', 'BO'] as const).map((prefix) => (
            <div className="workspace-deployment-group" key={prefix}>
              <header><span>{prefix === 'PB' ? 'Pullback' : 'Breakout'}</span><small>4 isolated deployments</small></header>
              <div className="workspace-deployment-grid">
                {sortedDeployments.filter((strategy) => deploymentMeta(strategy).prefix === prefix).map((strategy) => {
                  const { side, timeframe } = deploymentMeta(strategy)
                  const state = deploymentState(strategy)
                  const pnl = deploymentPnl(strategy)
                  const spark = deploymentSparkline(strategy)
                  return (
                    <a className={`workspace-deployment-card ${state.rail}`} href={`/strategy-lab/${encodeURIComponent(strategy.strategy_id)}`} key={strategy.strategy_id}>
                      <header><div><span>{prefix === 'PB' ? 'Pullback' : 'Breakout'}</span><strong>NIFTY{side !== 'NIFTY' ? <> <em>{side}</em></> : null}</strong><small>{timeframe}</small></div><StatusPill label={state.label} tone={state.label === 'FAILED' ? 'negative' : state.label === 'RUNNING' ? 'positive' : 'neutral'} /></header>
                      <dl>
                        <div><dt>Current Position</dt><dd>{strategy.current_position ? 'OPEN' : 'FLAT'}</dd></div>
                        <div><dt>Last Signal</dt><dd>{strategy.current_decision?.signal ? humanize(strategy.current_decision.signal) : 'WAITING'}</dd></div>
                        <div><dt>Trades Today</dt><dd>{formatInteger(strategy.today_trades)}</dd></div>
                        <div><dt>Current P&amp;L</dt><dd className={metricTone(pnl)}>{formatMoney(pnl)}</dd></div>
                      </dl>
                      <svg className={`${workspaceStyles.deploymentSparkline} ${spark.tone}`} viewBox="0 0 100 22" preserveAspectRatio="none" aria-label="Intraday MTM movement"><polyline points={spark.points} /></svg>
                      <footer className={workspaceStyles.deploymentFooter}><span>Health <strong>{humanize(strategy.health)}</strong></span><span>Candle <strong title={strategy.scheduler?.last_tick_at ?? undefined}>{strategy.scheduler?.last_tick_at ? formatTimeOnly(strategy.scheduler.last_tick_at) : 'Waiting'}</strong></span><span>Activation <strong>{strategy.scheduler?.activation_enabled == null ? 'Not Reported' : strategy.scheduler.activation_enabled ? 'Enabled' : 'Disabled'}</strong></span><span>Connection <strong className={strategyLab.error ? 'negative' : 'positive'}>{strategyLab.error ? 'Disconnected' : 'Connected'}</strong></span></footer>
                    </a>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </section>

      <StrategyComparisonPanel feed={comparison} />

      <DesignCard as="section" unstyled className={`panel workspace-unified-section ${workspaceStyles.panel} ${workspaceStyles.positionsPanel}`} aria-label="Active Positions">
        <SectionHeading eyebrow="03 / Trading Workspace" title="Active Positions" error={strategyLab.error ?? (execution?.reconciliation?.status === 'WARNING' ? execution.reconciliation.warnings?.join(' · ') ?? 'POSITION RECONCILIATION WARNING' : null)} status={execution?.reconciliation?.status === 'WARNING' ? 'stale' : rankedPositions.length ? 'live' : 'partial'} />
        {rankedPositions.length ? (
          <>
          <div className={workspaceStyles.positionHeaderSummary}><strong>{rankedPositions.length} OPEN</strong><i /><span>{formatMoney(positionExposure)} EXPOSURE</span><i /><b className={metricTone(positionMtm)}>{formatMoney(positionMtm)} MTM</b></div>
          {renderPositionHero(rankedPositions[0])}
          {rankedPositions.length > 1 ? <div className={workspaceStyles.collapsedPositions}>{rankedPositions.slice(1).map((position) => { const values = positionValues(position); const meta = values.deployment ? deploymentMeta(values.deployment) : null; const rr = currentRRFor(position); const mtm = position.pnl_valid === false ? null : position.pnl ?? position.unrealized_pnl ?? null; return <details key={position.position_id ?? position.trade_id ?? `${position.strategy_id ?? 'strategy'}-${position.entry_time ?? 'open'}`}><summary><strong>{meta?.prefix === 'PB' ? 'Pullback' : 'Breakout'}</strong><span>{heldContractLabel(position, meta)}</span><b>{values.side}</b><em className={metricTone(mtm)}>{mtm == null ? humanize(position.pnl_status ?? 'MTM UNAVAILABLE') : formatMoney(mtm)}</em><span>{rr == null ? '—' : `${formatNumber(rr)}R`}</span><span>LTP {position.quote_status === 'UNAVAILABLE' ? 'UNAVAILABLE' : values.current == null ? '—' : formatMoney(values.current)}</span><span>SL {values.stop == null ? '—' : formatMoney(values.stop)}</span><span>Target {values.target == null ? '—' : formatMoney(values.target)}</span><span>{durationFor(position)}</span><b className={values.stopBreached ? 'negative' : 'positive'}>{values.stopBreached ? 'STOP BREACHED' : humanize(position.status ?? 'OPEN')}</b></summary>{renderPositionHero(position)}</details> })}</div> : null}
          </>
        ) : <div className={`workspace-unified-empty ${workspaceStyles.emptyState}`} role="status"><Activity size={18} /><strong>NO ACTIVE PAPER POSITIONS</strong><span>All registered strategies are currently flat.</span></div>}
      </DesignCard>

      <TodaysClosedTradesPanel
        data={execution?.todays_closed_trades}
        verifiedTime={headerUpdatedAt ? String(formatTimeOnly(typeof headerUpdatedAt === 'number' || typeof headerUpdatedAt === 'string' ? headerUpdatedAt : headerUpdatedAt.getTime())) : undefined}
      />

      <DesignCard as="section" unstyled className={`panel workspace-unified-section intelligence-panel personal-oracle-panel ${workspaceStyles.panel} ${workspaceStyles.oraclePanel}`} aria-label="Personal Trading Intelligence">
        <SectionHeading eyebrow="06C / ORACLE" title="Personal Trading Intelligence" error={personalOracle.error} status={personalOracle.error ? 'stale' : personalOracle.loading ? 'connecting' : 'live'} aside={personalOracle.data ? 'ADVISORY ONLY · EXECUTION INFLUENCE 0%' : undefined} />
        {personalOracle.loading ? <WidgetLoading label="Loading Personal ORACLE dataset" /> : personalOracle.data ? <PersonalOraclePanel data={personalOracle.data} /> : <FeedPlaceholder error={personalOracle.error} label="Personal ORACLE intelligence" />}
      </DesignCard>

      <DesignCard as="section" unstyled className={`panel workspace-unified-section ${workspaceStyles.panel} ${workspaceStyles.timelinePanel}`} aria-label="Execution Timeline">
        <div className={workspaceStyles.timelineHeading}>
          <SectionHeading eyebrow="04 / Trading Workspace" title="Execution Timeline" error={strategyLab.error} status={lifecycleCards.length ? 'live' : 'partial'} />
          <div className={workspaceStyles.timelineFilters} aria-label="Timeline filters"><button className={workspaceStyles.activeFilter} type="button">All</button><button type="button">Entries</button><button type="button">Exits</button><button type="button">PB</button><button type="button">BO</button></div>
          <div className={workspaceStyles.timelineSummary}><span>{formatInteger(timeline.length)} events</span><i /><span>{formatInteger(completedTimelineTrades)} trades</span><i /><strong className={metricTone(timelineNet)}>{formatMoney(timelineNet)} net</strong></div>
        </div>
        {lifecycleCards.length ? (
          <div className={workspaceStyles.lifecycleTimeline}>
            <div className={workspaceStyles.timelineDate}>{timelineDate}</div>
            {lifecycleCards.map((card) => {
              const isProfit = typeof card.pnl === 'number' && card.pnl > 0
              const isLoss = typeof card.pnl === 'number' && card.pnl < 0
              const isRejected = card.state === 'REJECTED' || card.state === 'FAILED'
              const statusTone = isRejected || isLoss ? workspaceStyles.lifecycleLoss : isProfit ? workspaceStyles.lifecycleProfit : workspaceStyles.lifecycleNeutral
              const lifecycleEnd = card.state === 'OPEN' ? 'OPEN' : isRejected ? card.state : 'EXIT'
              const flowSteps = isRejected ? ['SIGNAL', 'ORDER', card.state] : ['SIGNAL', 'ORDER', 'FILLED', lifecycleEnd]
              return (
                <div className={workspaceStyles.lifecycleRow} key={card.id}>
                  <div className={workspaceStyles.timelineStamp}><time>{formatTimeOnly(card.occurredAt)}</time><i className={statusTone} /></div>
                  <details className={`${workspaceStyles.lifecycleCard} ${statusTone}`}>
                    <summary>
                      <div className={workspaceStyles.lifecycleIdentity}><strong>{card.strategy}</strong><span>{card.instrument}<i />{card.timeframe}</span></div>
                      <div className={workspaceStyles.lifecycleStatus}><b>{card.direction}</b><i>→</i><strong>{card.outcome === 'OPEN' ? 'OPEN' : card.outcome.includes('STOP') ? 'STOP' : card.outcome.includes('TARGET') ? 'TARGET' : lifecycleEnd}</strong></div>
                      <dl className={workspaceStyles.lifecycleMetrics}>
                        <div><dt>Entry</dt><dd>{card.entry == null ? '—' : formatMoney(card.entry)}</dd></div>
                        <div><dt>{card.state === 'OPEN' ? 'LTP' : 'Exit'}</dt><dd>{card.exit == null ? '—' : formatMoney(card.exit)}</dd></div>
                        <div><dt>Qty</dt><dd>{formatInteger(card.quantity)}</dd></div>
                        <div><dt>Reason</dt><dd>{card.outcome}</dd></div>
                        <div><dt>Duration</dt><dd>{card.duration}</dd></div>
                      </dl>
                      <strong className={`${workspaceStyles.lifecyclePnl} ${metricTone(card.pnl)}`}>{card.pnl == null ? '—' : formatMoney(card.pnl)}</strong>
                      <span className={workspaceStyles.lifecycleChevron}>⌄</span>
                      <div className={`${workspaceStyles.executionFlow} ${isRejected ? workspaceStyles.shortFlow : ''}`}>
                        {flowSteps.map((step, index) => <span className={isRejected && index === flowSteps.length - 1 ? workspaceStyles.flowRejected : ''} key={step}><i />{step}</span>)}
                      </div>
                    </summary>
                    <div className={workspaceStyles.lifecycleDetails}>
                      <dl>
                        <div><dt>Entry Order ID</dt><dd>{card.entryOrder?.order_id ?? '—'}</dd></div>
                        <div><dt>Exit Order ID</dt><dd>{card.exitOrder?.order_id ?? '—'}</dd></div>
                        <div><dt>Order Timestamp</dt><dd>{card.entryOrder?.created_at ? formatTimestamp(card.entryOrder.created_at) : '—'}</dd></div>
                        <div><dt>Exchange Fill</dt><dd>{card.entryFill?.time ? formatTimestamp(card.entryFill.time) : '—'}</dd></div>
                        <div><dt>Fill Latency</dt><dd>{card.fillLatency == null ? '—' : `${formatNumber(card.fillLatency)}ms`}</dd></div>
                        <div><dt>Partial Fills</dt><dd>{formatInteger(card.partialFills)}</dd></div>
                      </dl>
                      <details><summary>Raw execution events · {formatInteger(card.rawEvents.length)}</summary><pre>{JSON.stringify(card.rawEvents, null, 2)}</pre></details>
                    </div>
                  </details>
                </div>
              )
            })}
          </div>
        ) : <div className={`workspace-unified-empty ${workspaceStyles.emptyState}`} role="status"><History size={18} /><strong>Waiting for the first paper lifecycle event.</strong></div>}
      </DesignCard>

      <DesignCard as="section" unstyled className={`panel workspace-unified-section ${workspaceStyles.panel} ${workspaceStyles.paperPanel}`} aria-label="Paper Engine Summary">
        <SectionHeading eyebrow="05 / Trading Workspace" title="Paper Engine Summary" error={strategyLab.error} status={execution ? 'live' : 'partial'} aside="Current paper session" />
        <div className={`workspace-paper-summary ${workspaceStyles.paperMetrics}`}>
          <DesignMetricCard unstyled label="Orders" value={formatInteger(ordersToday)} />
          <DesignMetricCard unstyled label="Filled" value={formatInteger(filledOrders)} />
          <DesignMetricCard unstyled label="Rejected" value={formatInteger(countOrders('REJECTED'))} />
          <DesignMetricCard unstyled label="Fill %" value={ordersToday ? formatPercent((filledOrders / ordersToday) * 100) : '—'} />
          <DesignMetricCard unstyled label="Average RR" value={closedRR.length ? `${formatNumber(closedRR.reduce((sum, rr) => sum + rr, 0) / closedRR.length)}R` : '—'} />
          <DesignMetricCard unstyled label="Today's P&L" value={portfolio?.today_pnl == null ? '—' : formatMoney(portfolio.today_pnl)} valueClassName={metricTone(portfolio?.today_pnl)} />
          <DesignMetricCard unstyled label="Latency" value={averageLatency == null ? '—' : `${formatNumber(averageLatency)}ms`} />
          <DesignMetricCard unstyled label="Runtime" value={humanize(data.status.readiness)} />
        </div>
      </DesignCard>

      <DesignCard as="section" unstyled className={`panel workspace-unified-section ${workspaceStyles.panel} ${workspaceStyles.journalPanel}`} aria-label="Latest Journal">
        <SectionHeading eyebrow="06 / Trading Workspace" title="Latest Journal" error={strategyLab.error} status={journal.length ? 'live' : 'partial'} aside="Latest 10 entries" />
        {journal.length ? (
          <DesignTable unstyled frameClassName={`workspace-table-wrap ${workspaceStyles.tableFrame}`} className={`workspace-table workspace-unified-table ${workspaceStyles.table}`}><caption className="sr-only">Latest Strategy Lab lifecycle events</caption><thead><tr><th>Signal</th><th>Entry</th><th>Exit</th><th>Target</th><th>Stop</th><th>Reason</th><th>Timestamp</th></tr></thead><tbody>
              {journal.map((record) => { const signal = journalSignal(record); const pnl = journalPnl(record); const timestamp = journalTimestamp(record.recorded_at); return <tr className={`${pnl != null && pnl > 0 ? workspaceStyles.journalWin : pnl != null && pnl < 0 ? workspaceStyles.journalLoss : ''}`} key={record.record_id ?? `${record.strategy_id}-${record.recorded_at}-${record.event_type}`}><td><span className={`${workspaceStyles.journalSignal} ${journalSignalTone(signal)}`}>{signal}</span></td><td>{valueFrom(record, 'entry', 'entry_price')}</td><td>{valueFrom(record, 'exit', 'exit_price')}</td><td>{valueFrom(record, 'target', 'target_price', 'underlying_target')}</td><td>{valueFrom(record, 'stop', 'stop_loss', 'sl', 'underlying_stop')}</td><td className={workspaceStyles.journalReason}>{journalReason(record)}</td><td><time className={workspaceStyles.journalTime} dateTime={record.recorded_at}><span>{timestamp.date}</span><b>{timestamp.time}</b></time></td></tr> })}
            </tbody></DesignTable>
        ) : <div className={`workspace-unified-empty ${workspaceStyles.emptyState}`} role="status"><BookOpen size={18} /><strong>No completed trades yet.</strong></div>}
      </DesignCard>
      </div>

      <details className={`panel workspace-diagnostics ${workspaceStyles.diagnostics}`}>
        <summary><span>Advanced Diagnostics</span><small>Engineering and debug information</small></summary>
        <div className="workspace-diagnostics-grid">
          <article><span>Evidence</span><strong>{formatInteger(review?.evidence?.length ?? 0)}</strong></article>
          <article><span>Replay</span><strong>{formatInteger(review?.replay?.length ?? 0)}</strong></article>
          <article><span>OMS Diagnostics</span><strong>{formatInteger(execution?.order_count ?? 0)} orders · {formatInteger(execution?.fill_count ?? 0)} fills</strong></article>
          <article><span>Runtime IDs</span><strong>{deployments.map((strategy) => strategy.strategy_id).join(' · ')}</strong></article>
          <article><span>Latency</span><strong>{deployments.some((strategy) => typeof strategy.latency_ms === 'number') ? `${formatNumber(deployments.reduce((sum, strategy) => sum + (strategy.latency_ms ?? 0), 0) / deployments.filter((strategy) => typeof strategy.latency_ms === 'number').length)} ms average` : 'Not reported'}</strong></article>
          <article><span>Adapter Details</span><strong>{data.deployment.adapters.map((adapter) => adapter.input_type).join(' · ')}</strong></article>
          <article><span>Serialization</span><strong>{humanize(data.status.readiness)}</strong></article>
          <article><span>Developer Messages</span><strong>{strategyLab.error ?? 'No active frontend warnings'}</strong></article>
        </div>
      </details>

      <section className="performance-section">
        <SectionHeading eyebrow="04 / Performance Nexus" title="Simulated Forward-Test Analytics" error={performance.error} status={performance.data ? 'live' : 'connecting'} aside={performance.data?.verdict.replaceAll('_', ' ') ?? undefined} />
        {performance.data ? <><div className="performance-grid"><PerformanceCard label="Net points" value={formatSigned(performance.data.net_points)} sub={`${performance.data.total_trades} analyzed trades`} tone={performance.data.net_points >= 0 ? 'positive' : 'negative'} /><PerformanceCard label="Win rate" value={formatPercent(performance.data.win_rate)} sub={`${performance.data.wins} wins · ${performance.data.losses} losses`} tone="blue" /><PerformanceCard label="Profit factor" value={formatNumber(performance.data.profit_factor)} sub="Gross profit / gross loss" tone="purple" /><PerformanceCard label="Expectancy" value={formatSigned(performance.data.expectancy)} sub="Points per trade" tone={performance.data.expectancy >= 0 ? 'positive' : 'negative'} /><PerformanceCard label="Best win streak" value={formatInteger(performance.data.max_win_streak)} sub={`Max loss streak ${performance.data.max_loss_streak}`} tone="neutral" /></div><div className="analytics-note"><span>System assessment</span><p>{performance.data.comment}</p></div></> : <FeedPlaceholder error={performance.error} label="performance stats" />}
      </section>

      <section className="performance-section" aria-label="Live intelligence shadow pipeline certification">
        <SectionHeading eyebrow="04A / Intelligence Safety" title="Live-Mode Certification" error={null} status={Object.values(feedMeta).some((meta) => meta?.health === 'STALE') ? 'stale' : 'live'} aside="Advisory only · Zero execution influence" />
        <DesignTable unstyled frameClassName="workspace-table-wrap" className="workspace-table workspace-unified-table">
          <caption className="sr-only">Live intelligence shadow pipeline certification</caption>
          <thead><tr><th>Module</th><th>Real candles</th><th>Latest candle</th><th>Freshness</th><th>Running</th><th>Backend parity</th><th>Execution influence</th></tr></thead>
          <tbody>{([
            ['KRONOS Alpha', 'kronos_alpha'], ['Chronos2', 'chronos2'], ['ARGUS', 'argus'], ['ATHENA', 'athena'],
            ['AEGIS', 'aegis'], ['HERMES', 'hermes'], ['Oracle', 'oracle'], ['Personal Oracle', 'personal_oracle'],
            ['Performance Nexus', 'performance'],
          ] as const).map(([label, key]) => {
            const meta = feedMeta[key]
            const stale = meta?.health === 'STALE'
            return <tr key={key}><td><strong>{label}</strong></td><td>{meta?.real_candles == null ? 'Not Reported' : meta.real_candles ? 'YES' : 'NO'}</td><td title={meta?.candle_id ?? undefined}>{meta?.latest_completed_candle_at ? formatTimestamp(meta.latest_completed_candle_at) : 'Not Reported'}</td><td className={stale ? 'negative' : ''}>{stale ? meta?.stale_reason ?? 'STALE' : meta?.market_input_state ? `${humanize(meta.market_input_state)} · ${formatNumber(meta.freshness_age_seconds)}s` : meta?.freshness_age_seconds == null ? humanize(meta?.health ?? 'UNAVAILABLE') : `${formatNumber(meta.freshness_age_seconds)}s`}</td><td>{humanize(meta?.runtime_state ?? meta?.readiness ?? 'UNAVAILABLE')}</td><td>{meta?.source_timestamp ? 'BACKEND' : 'Not Reported'}</td><td className={meta?.execution_influence === 0 ? 'positive' : 'negative'}>{meta?.execution_influence === 0 ? 'ZERO' : 'UNAVAILABLE'}</td></tr>
          })}</tbody>
        </DesignTable>
        <details className="aegis-session-plan">
          <summary><span>Backend lineage details</span><small>Unreported fields remain unreported</small></summary>
          <DesignTable unstyled frameClassName="workspace-table-wrap" className="workspace-table workspace-unified-table">
            <thead><tr><th>Module</th><th>Symbol / TF</th><th>Candle ID</th><th>Source time</th><th>Calculation time</th><th>Input window</th><th>State / reason</th></tr></thead>
            <tbody>{([
              ['KRONOS Alpha', 'kronos_alpha'], ['Chronos2', 'chronos2'], ['ARGUS', 'argus'], ['ATHENA', 'athena'],
              ['AEGIS', 'aegis'], ['HERMES', 'hermes'], ['Oracle', 'oracle'], ['Personal Oracle', 'personal_oracle'],
              ['Performance Nexus', 'performance'],
            ] as const).map(([label, key]) => {
              const meta = feedMeta[key]
              return <tr key={`${key}-lineage`}><td>{label}</td><td>{meta?.symbol || meta?.timeframe ? `${meta.symbol ?? 'Not Reported'} / ${meta.timeframe ?? 'Not Reported'}` : 'Not Reported'}</td><td>{meta?.candle_id ?? 'Not Reported'}</td><td>{meta?.source_timestamp ? formatTimestamp(meta.source_timestamp) : 'Not Reported'}</td><td>{meta?.calculation_timestamp ? formatTimestamp(meta.calculation_timestamp) : 'Not Reported'}</td><td>{meta?.input_candle_count ?? 'Not Reported'}</td><td>{humanize(meta?.stale_reason ?? meta?.runtime_state ?? meta?.readiness ?? 'UNAVAILABLE')}</td></tr>
            })}</tbody>
          </DesignTable>
        </details>
        <div className="analytics-note"><span>Shadow pipeline contract</span><p>Advisory only — does not control strategy execution. “Not Reported” fields are preserved and are not inferred by the workspace.</p></div>
      </section>

      <section className="aegis-section" aria-label="AEGIS — FINAL DECISION INTELLIGENCE">
        <SectionHeading eyebrow="05A / AEGIS" title="Final Decision Intelligence" error={aegis.error} status={aegis.data ? 'live' : 'connecting'} aside="Advisory controller · No execution" />
        {aegis.data ? <AegisPanel data={aegis.data} readiness={readiness.data} plan={nextSessionPlan.data} readinessError={readiness.error ?? nextSessionPlan.error} /> : <FeedPlaceholder error={aegis.error} label="AEGIS decision intelligence" />}
      </section>

      <section className="order-ledger-section" aria-label="ORDER & FILL OPERATIONS">
        <SectionHeading eyebrow="05B / OPERATIONS" title="Order & Fill Operations" error={orderLedger.error} status={orderLedger.data ? 'live' : 'connecting'} aside="Audit-only · Read-only" />
        {orderLedger.data ? <OrderLedgerPanel data={orderLedger.data} /> : <FeedPlaceholder error={orderLedger.error} label="order and fill ledger" />}
      </section>
    </div>
  )
}

function formatDuration(seconds: number) {
  if (!Number.isFinite(seconds)) return 'UNAVAILABLE'
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  return hours ? `${hours}h ${minutes % 60}m` : `${minutes}m`
}

function StatusPill({ label, tone }: { label: string; tone: 'positive' | 'negative' | 'neutral' }) {
  return <DesignStatusChip as="div" unstyled className={`status-pill ${tone}`}><i /> {label}</DesignStatusChip>
}

function MetricCard({ label, value, detail, tone, icon, loading = false }: { label: string; value: string; detail: string; tone: string; icon: React.ReactNode; loading?: boolean }) {
  return (
    <DesignCard as="article" unstyled className={`metric-card ${tone}`} aria-busy={loading}>
      <div className="metric-icon">{icon}</div>
      <span>{label}</span>
      {loading ? <><i className="loading-line metric-value-loading" /><i className="loading-line metric-detail-loading" /></> : <><strong>{value}</strong><small>{detail}</small></>}
    </DesignCard>
  )
}

function MarketMatrixLoading() {
  return (
    <div className="table-loading" aria-label="Loading market matrix" aria-busy="true">
      {Array.from({ length: 5 }, (_, index) => <div key={index}><i className="loading-line" /><i className="loading-line" /><i className="loading-line" /><i className="loading-line" /></div>)}
    </div>
  )
}

function MarketMatrix({ rows }: { rows: MarketRow[] }) {
  if (rows.length === 0) return <div className="empty-inline">No instruments returned by the backend.</div>

  return (
    <DesignTable unstyled frameClassName="table-scroll" className="matrix-table">
        <thead>
          <DesignTableRow unstyled>
            <DesignTableHeaderCell unstyled>Instrument</DesignTableHeaderCell>
            <DesignTableHeaderCell unstyled className="text-right">LTP</DesignTableHeaderCell>
            <DesignTableHeaderCell unstyled className="text-right">Change</DesignTableHeaderCell>
            <DesignTableHeaderCell unstyled>Trend</DesignTableHeaderCell>
            <DesignTableHeaderCell unstyled>Bias</DesignTableHeaderCell>
            <DesignTableHeaderCell unstyled>Confidence</DesignTableHeaderCell>
            <DesignTableHeaderCell unstyled>Structure</DesignTableHeaderCell>
            <DesignTableHeaderCell unstyled className="text-center">Signal</DesignTableHeaderCell>
          </DesignTableRow>
        </thead>
        <tbody>
          {rows.map((row) => (
            <DesignTableRow unstyled key={row.symbol}>
              <DesignTableCell unstyled><div className="symbol-cell"><i className={toneFor(row.bias)}>{row.direction}</i><div><strong>{row.symbol}</strong><span>{row.strategy}</span></div></div></DesignTableCell>
              <DesignTableCell unstyled className="mono text-right">{formatPrice(row.ltp)}</DesignTableCell>
              <DesignTableCell unstyled className={`mono change-value text-right ${(row.change_percent ?? 0) > 0 ? 'positive-text' : (row.change_percent ?? 0) < 0 ? 'negative-text' : ''}`}>{formatSignedPercent(row.change_percent)}</DesignTableCell>
              <DesignTableCell unstyled><Badge value={row.regime} /></DesignTableCell>
              <DesignTableCell unstyled><Badge value={row.bias} /></DesignTableCell>
              <DesignTableCell unstyled><div className="confidence"><span><i style={{ width: `${clamp(row.confidence)}%` }} /></span><strong>{formatPercent(row.confidence)}</strong></div></DesignTableCell>
              <DesignTableCell unstyled><div className="structure-cell"><strong>{humanize(row.structure)}</strong><span>{humanize(row.liquidity)}</span></div></DesignTableCell>
              <DesignTableCell unstyled className="text-center"><Badge value={row.pullback_signal} prominent /></DesignTableCell>
            </DesignTableRow>
          ))}
        </tbody>
    </DesignTable>
  )
}

function Badge({ value, prominent = false }: { value: string | null; prominent?: boolean }) {
  return <DesignBadge unstyled className={`badge ${toneFor(value)} ${prominent ? 'prominent' : ''}`}>{humanize(value)}</DesignBadge>
}

function ActiveTrade({ trade }: { trade: Trade }) {
  return (
    <div className="active-trade">
      <div className="trade-hero">
        <div><Badge value={trade.side} prominent /><h3>{trade.symbol}</h3><span>Trade #{trade.trade_id}</span></div>
        <div className={trade.pnl_points >= 0 ? 'positive-text' : 'negative-text'}><span>Simulated P&amp;L</span><strong>{formatSigned(trade.pnl_points)}</strong></div>
      </div>
      <div className="trade-levels">
        <TradeLevel label="Entry" value={trade.entry} />
        <TradeLevel label="LTP" value={trade.ltp} />
        <TradeLevel label="Stop" value={trade.sl} />
        <TradeLevel label="Target" value={trade.target} />
      </div>
      <div className="trade-footer"><span>{trade.status}</span><span>{formatNumber(trade.r_multiple)}R</span></div>
      <p>{trade.reason}</p>
    </div>
  )
}

function TradeLevel({ label, value }: { label: string; value: number }) {
  return <div><span>{label}</span><strong>{formatPrice(value)}</strong></div>
}

function PerformanceCard({ label, value, sub, tone }: { label: string; value: string; sub: string; tone: string }) {
  return <DesignMetricCard unstyled className={`performance-card ${tone}`} label={label} value={value} detail={sub} />
}

function PerformanceLoading() {
  return (
    <div className="performance-grid" aria-label="Loading performance analytics" aria-busy="true">
      {Array.from({ length: 5 }, (_, index) => <article className="performance-card loading-card" key={index}><i className="loading-line" /><i className="loading-line" /><i className="loading-line" /></article>)}
    </div>
  )
}

function ArgusLoading() {
  return (
    <div className="argus-loading" aria-label="Loading ARGUS OI positioning" aria-busy="true">
      <div className="argus-loading-head"><i className="loading-line" /><i className="loading-line" /><i className="loading-line" /></div>
      <div className="argus-loading-body"><i className="loading-line" /><i className="loading-line" /><i className="loading-line" /><i className="loading-line" /></div>
    </div>
  )
}

function ArgusUnavailable({ error }: { error: string | null }) {
  const state = argusProviderState(error)
  return (
    <div className="argus-unavailable" role="status">
      <div><span>ARGUS</span><strong>UNAVAILABLE</strong></div>
      <div className="argus-unavailable-grid">
        <PersonalOracleMetric label="Provider state" value={humanize(state)} />
        <PersonalOracleMetric label="Reason code" value={state} />
        <PersonalOracleMetric label="Last valid update" value="—" />
      </div>
      <p>No current OI assessment available.</p>
      <small>{error ? 'The provider request failed. Automatic bounded polling will retry; no values are fabricated.' : 'Waiting for the first sanitized option-chain snapshot.'}</small>
    </div>
  )
}

function ArgusWriterDominatedPanel({
  data,
  error,
  onRetry,
  retrying,
  selectedSymbol,
  onSymbolChange,
}: {
  data: ArgusResponse
  error: string | null
  onRetry: () => void
  retrying: boolean
  selectedSymbol: string
  onSymbolChange: (symbol: string) => void
}) {
  const { isValid, snapshot } = safeArgusSnapshot(data)
  if (!isValid || !snapshot) {
    return <ArgusUnavailable error={error} />
  }

  const status = safeArgusStatus(data, error)
  const statusTone = status === 'Live' ? 'positive' : status === 'Cached' ? 'purple' : status === 'Closed' ? 'neutral' : 'negative'
  const baseline = safeBaselineLabel(snapshot.underlying)

  return (
    <div className="argus-content" data-argus-writer-dominated>
      {error && <div className="argus-stale-banner"><span>Last successful snapshot preserved · {error}</span><button type="button" onClick={onRetry} disabled={retrying}>{retrying ? 'Retrying…' : 'Retry'}</button></div>}
      <div className="argus-header">
        <div className="argus-identity">
          <select
            value={selectedSymbol}
            onChange={(event) => onSymbolChange(event.target.value)}
            className="argus-symbol-select"
            aria-label="ARGUS symbol"
          >
            <option value="NIFTY">NIFTY</option>
            <option value="BANKNIFTY">BANKNIFTY</option>
            <option value="FINNIFTY">FINNIFTY</option>
            <option value="MIDCPNIFTY">MIDCPNIFTY</option>
            <option value="SENSEX">SENSEX</option>
          </select>
          <span>Expiry {snapshot.underlying.expiry ?? 'Unavailable'}</span>
          <span>ATM {formatPrice(snapshot.underlying.atm_strike)}</span>
        </div>
        <div className="argus-header-metrics">
          <div><span>Underlying LTP</span><strong>{formatPrice(snapshot.underlying.ltp)}</strong></div>
          <div><span>Last updated</span><strong>{formatTimestamp(snapshot.underlying.fetched_at)}</strong></div>
          <span className={`argus-status ${statusTone}`}>{status}</span>
        </div>
      </div>

      <div className="argus-decision-grid">
        <div className={`argus-verdict ${toneFor(snapshot.verdict.bias)}`}>
          <span>Primary verdict</span>
          <strong>{humanize(snapshot.verdict.regime)}</strong>
          <div><Badge value={snapshot.verdict.bias} prominent /><Badge value={snapshot.verdict.preferred_option_side} /></div>
          <small>{snapshot.verdict.confidence === null ? 'Unavailable' : `${formatNumber(snapshot.verdict.confidence)}% confidence`}</small>
        </div>
        <div className="argus-dominance">
          <div className="argus-subheading"><span>Buyer versus writer</span><span>{formatPercent(snapshot.dominance.writer_dominance_percentage)} / {formatPercent(snapshot.dominance.buyer_dominance_percentage)}</span></div>
          <div className="dominance-bar" aria-label="Writer versus buyer dominance">
            <span style={{ width: `${clamp(snapshot.dominance.writer_dominance_percentage ?? 0)}%` }} />
          </div>
          <div className="dominance-labels"><span>Writers {formatPercent(snapshot.dominance.writer_dominance_percentage)}</span><span>Buyers {formatPercent(snapshot.dominance.buyer_dominance_percentage)}</span></div>
        </div>
        <div className="argus-baseline"><span>Baseline truth</span><strong>{baseline}</strong><small>Baseline status · {humanize(snapshot.underlying.baseline_status)}</small></div>
      </div>

      <div className="argus-lower-grid">
        <div className="argus-levels">
          <div className="argus-subheading"><span>Key OI levels</span><span>Observed</span></div>
          <div className="argus-level-grid">
            <ArgusLevel label="Call wall" value={snapshot.walls.highest_ce_oi ? snapshot.walls.highest_ce_oi.strike : null} />
            <ArgusLevel label="Put wall" value={snapshot.walls.highest_pe_oi ? snapshot.walls.highest_pe_oi.strike : null} />
            <ArgusLevel label="Breakout above" value={snapshot.verdict.breakout_above} />
            <ArgusLevel label="Breakdown below" value={snapshot.verdict.breakdown_below} />
            <ArgusLevel label="Avoid zone" value={snapshot.verdict.avoid_zone ? `${formatPrice(snapshot.verdict.avoid_zone.lower)} — ${formatPrice(snapshot.verdict.avoid_zone.upper)}` : null} text />
          </div>
        </div>
        <div className="argus-evidence"><div className="argus-subheading"><span>Evidence</span><span>Backend reasons</span></div>{snapshot.verdict.reasons.slice(0, 3).map((reason: string) => <p key={reason}>{reason}</p>)}</div>
      </div>
    </div>
  )
}

function ArgusLevel({ label, value, text = false }: { label: string; value: number | string | null; text?: boolean }) {
  return <div><span>{label}</span><strong className={value === null ? 'unavailable' : ''}>{value === null ? '—' : text ? value : formatPrice(value as number)}</strong></div>
}

function baselineLabel(underlying: ArgusResponse['data']['underlying']) {
  return safeBaselineLabel(underlying)
}

function AegisPanel({ data, readiness, plan, readinessError }: { data: AegisDecision; readiness: OpenMarketReadiness | null; plan: NextSessionPlan | null; readinessError: string | null }) {
  const gates = Object.entries(data.hard_gate_details)
  const components = ['technical', 'kronos_core', 'argus', 'personal_oracle', 'hermes', 'athena']
  const marketClosed = !['OPEN', 'SPECIAL_SESSION'].includes(data.hard_gate_details.market_session?.state ?? 'UNKNOWN')
  return (
    <div className="aegis-content">
      {marketClosed && <div className="aegis-market-closed"><Clock3 size={13} /><strong>MARKET CLOSED</strong><span>Cached context only · advisory has no execution authority</span></div>}
      <div className="aegis-hero">
        <div><span>Final advisory recommendation</span><strong className={toneFor(data.recommendation)}>{humanize(data.recommendation)}</strong><small>{data.symbol} · {data.timeframe} · {data.strategy_name}</small></div>
        <div className="aegis-hero-metrics"><div className="aegis-score-row"><PersonalOracleMetric label="Decision score" value={data.decision_score == null ? '—' : formatNumber(data.decision_score)} /><PersonalOracleMetric label="Quality" value={humanize(data.decision_quality)} /></div><div className="aegis-context-row"><span>Coverage <strong>{formatPercent(data.data_coverage_percentage)}</strong></span><span>Size <strong>{formatNumber(data.recommended_size_multiplier)}×</strong></span></div></div>
      </div>
      <div className="aegis-safety-strip"><span>Advisory only <strong>YES</strong></span><span>Execution influence <strong>ZERO</strong></span><span>Strategy authority <strong>RUNTIME ONLY</strong></span></div>
      <div className="aegis-block"><span>Hard gates</span><div className="aegis-gates">{gates.map(([name, gate]) => <article key={name}><div><span>{humanize(name)}</span><Badge value={gate.state} /></div><small>{humanize(gate.reason)}</small></article>)}</div></div>
      <div className="aegis-block"><span>Component matrix</span><div className="aegis-components">{components.map((name) => { const detail = data.component_details[name]; const score = data.component_scores[name]; const contribution = data.weighted_contributions[name]; return <details key={name}><summary><strong>{humanize(name)}</strong><span>{score == null ? '—' : formatNumber(score)}</span><Badge value={detail?.status ?? 'UNAVAILABLE'} /></summary><dl><div><dt>Score</dt><dd>{score == null ? '—' : formatNumber(score)}</dd></div><div><dt>Contribution</dt><dd>{contribution == null ? '—' : formatNumber(contribution)}</dd></div><div><dt>Freshness</dt><dd>{detail?.freshness == null ? '—' : humanize(String(detail.freshness))}</dd></div></dl><p>{humanize(detail?.top_reason ?? 'INPUT UNAVAILABLE')}</p></details> })}</div></div>
      <div className="aegis-block aegis-primary-reasons"><span>Primary reasons</span><div className="aegis-reason-codes">{data.dominant_reasons.slice(0, 4).map((reason) => <span key={reason}>{humanize(reason)}</span>)}</div><div className="aegis-conflicts">{data.conflicts.slice(0, 3).length ? data.conflicts.slice(0, 3).map((conflict) => <article key={conflict.conflict_id}><div><Badge value={conflict.severity} /><span>{conflict.modules.join(' × ')}</span><small>−{formatNumber(conflict.score_impact)}</small></div><strong>{conflict.description}</strong><p>{conflict.resolution}</p></article>) : <p>No material module conflicts in the current assessment.</p>}</div></div>
      <div className="aegis-summary-grid"><div><span>Warnings</span>{data.warnings.slice(0, 4).map((warning) => <p key={warning}>{humanize(warning)}</p>)}</div><div><span>Missing inputs</span>{data.missing_inputs.length ? data.missing_inputs.slice(0, 4).map((item) => <p key={item}>{humanize(item)}</p>) : <p>None</p>}</div></div>
      <div className="aegis-readiness">
        <div className="aegis-readiness-heading"><span>Open-market readiness</span><Badge value={readiness?.status ?? 'UNAVAILABLE'} /></div>
        {readinessError && !readiness ? <p>{readinessError}</p> : <div className="aegis-readiness-grid">{readiness?.items.slice(0, 12).map((item) => <article key={item.component}><div><strong>{item.component}</strong><Badge value={item.status} /></div><small>{humanize(item.reason)}</small>{item.warning && <p>{item.warning}</p>}</article>)}</div>}
      </div>
      <details className="aegis-session-plan"><summary><span>Validation timeline</span><small>Next evaluation · {plan?.first_candle_close ? formatTimestamp(plan.first_candle_close) : plan?.expected_open ? formatTimestamp(plan.expected_open) : 'Awaiting canonical calendar'}</small></summary><ol>{plan?.steps.slice(0, 10).map((step) => <li key={step.sequence}><span>{step.sequence}</span><div><strong>{step.action}</strong><small>{step.expected_at ? formatTimestamp(step.expected_at) : 'Time derived at next valid open'}</small></div></li>)}</ol>{plan && <p>64 closed candles minimum · {plan.grace_seconds}s scheduler grace · plan only, not observed</p>}</details>
      <div className="aegis-disclaimer">Advisory only — does not control strategy execution.</div>
    </div>
  )
}

function argusStatus(data: ArgusResponse, error: string | null) {
  return safeArgusStatus(data, error)
}

function argusProviderState(error: string | null) {
  if (!error) return 'UNAVAILABLE'
  return /(auth|token|credential|unauthori[sz]ed|401|403)/i.test(error) ? 'AUTH_FAILED' : 'PROVIDER_ERROR'
}

function KronosPanel({ data }: { data: KronosGauge }) {
  return (
    <div className="engine-content">
      <div className="engine-hero">
        <div className="score-orbit"><strong>{formatNumber(data.score)}</strong><span>Overall score</span></div>
        <div><Badge value={data.label} prominent /><p>Directional bias</p></div>
      </div>
      <div className="engine-metrics">
        <EngineMetric label="Market regime" value={data.regime ? humanize(data.regime) : 'Unavailable'} />
        <EngineMetric label="Confidence" value={formatPercent(data.confidence)} />
        <EngineMetric label="Trend" value={formatNumber(data.trend)} />
        <EngineMetric label="Momentum" value={formatNumber(data.momentum)} />
        <EngineMetric label="Structure" value={formatNumber(data.structure)} />
        <EngineMetric label="Liquidity" value={formatNumber(data.liquidity)} />
      </div>
    </div>
  )
}

function KronosAlphaPanel({ data, projection, meta }: { data: KronosAlphaStatus; projection: ForecastProjectionMeta | null; meta?: V2Feed['meta'] }) {
  const effectiveStatus = meta?.market_input_state === 'STALE' ? 'STALE' : meta?.market_input_state === 'WAITING_FOR_NEXT_CANDLE' ? 'WAITING_FOR_NEXT_CANDLE' : data.model_status
  return (
    <div className="forecast-model-content kronos-alpha-content">
      <div className="forecast-gauge-row">
        <ForecastGauge label="Direction" value={humanize(data.expected_direction)} tone={forecastDirectionTone(data.expected_direction)} variant="full" />
        <ForecastGauge label="Forecast quality" value={data.outlooks.forecast_quality_score === null ? MODEL_FIELD_NOT_EXPOSED : formatPercent(data.outlooks.forecast_quality_score)} percent={data.outlooks.forecast_quality_score} tone="platinum" variant="radial" />
        <ForecastGauge label="Trend persistence" value={data.trend_persistence_probability === null ? MODEL_FIELD_NOT_EXPOSED : formatPercent(data.trend_persistence_probability)} percent={data.trend_persistence_probability} tone="platinum" />
      </div>
      <div className="forecast-summary-section">
        <div className="forecast-summary-heading"><span>Forecast Summary</span><small>Decision-grade model outputs</small></div>
        <div className="forecast-primary-metrics">
          <ForecastMetric label="Expected move" value={data.expected_return_percentage === null ? MODEL_FIELD_NOT_EXPOSED : `${formatSigned(data.expected_return_percentage)}%`} description="Median forecast return" emphasis />
          <ForecastRange low={data.expected_low} high={data.expected_high} description="Expected low to expected high" />
          <ForecastMetric label="Forecast horizon" value={data.horizon_candles ? `${formatInteger(data.horizon_candles)} candles · ${formatInteger(data.horizon_minutes)} min` : MODEL_FIELD_NOT_EXPOSED} description="Forward prediction window" />
          <ForecastMetric label="Context window" value={data.input_candle_count === null ? MODEL_FIELD_NOT_EXPOSED : `${formatInteger(data.input_candle_count)} candles`} description="Historical context analysed" />
        </div>
      </div>
      <p className="forecast-safety-note">Probabilistic forecast, not execution permission.</p>
      <details className="forecast-advanced">
        <summary><span>Advanced Forecast Details</span><small>All authoritative KRONOS ALPHA outputs</small></summary>
        <div className="forecast-advanced-body">
          <div className="kronos-alpha-wheels" aria-label="CE and PE option-buying outlooks">
            <ProbabilityWheel side="CE" outlook={data.outlooks.ce} bullish={data.bullish_probability} bearish={data.bearish_probability} sideways={data.sideways_probability} />
            <ProbabilityWheel side="PE" outlook={data.outlooks.pe} bullish={data.bullish_probability} bearish={data.bearish_probability} sideways={data.sideways_probability} />
          </div>
          <div className="forecast-detail-grid">
            <ForecastMetric label="Bullish probability" value={data.bullish_probability === null ? 'Unavailable' : formatPercent(data.bullish_probability)} />
            <ForecastMetric label="Bearish probability" value={data.bearish_probability === null ? 'Unavailable' : formatPercent(data.bearish_probability)} />
            <ForecastMetric label="Sideways probability" value={data.sideways_probability === null ? 'Unavailable' : formatPercent(data.sideways_probability)} />
            <ForecastMetric label="Reversal probability" value={data.reversal_probability === null ? 'Unavailable' : formatPercent(data.reversal_probability)} />
            <ForecastMetric label="Forecast volatility" value={data.forecast_volatility === null ? 'Unavailable' : formatNumber(data.forecast_volatility)} />
            <ForecastMetric label="Volatility label" value={humanize(data.volatility_label)} />
            <ForecastMetric label="Forecast uncertainty" value={data.forecast_uncertainty === null ? 'Unavailable' : formatNumber(data.forecast_uncertainty)} />
            <ForecastMetric label="Uncertainty label" value={humanize(data.uncertainty_label)} />
            <ForecastMetric label="Forecast dispersion" value={data.forecast_dispersion === null ? 'Unavailable' : formatNumber(data.forecast_dispersion)} />
            <ForecastMetric label="Forecast quantiles" value={data.upside_quantile === null || data.downside_quantile === null ? 'Unavailable' : `${formatSigned(data.upside_quantile)}% / ${formatSigned(data.downside_quantile)}%`} />
            <ForecastMetric label="Forecast quality" value={data.outlooks.forecast_quality_score === null ? 'Unavailable' : formatPercent(data.outlooks.forecast_quality_score)} />
            <ForecastMetric label="Path count" value={data.path_count === null ? 'Unavailable' : formatInteger(data.path_count)} />
            <ForecastMetric label="Evaluated forecasts" value={formatInteger(data.evaluation.evaluated_forecasts)} />
            <ForecastMetric label="Directional hit rate" value={data.evaluation.directional_hit_rate === null ? 'Unavailable' : formatPercent(data.evaluation.directional_hit_rate)} />
            <ForecastMetric label="Average forecast error" value={data.evaluation.average_forecast_error === null ? 'Unavailable' : formatNumber(data.evaluation.average_forecast_error)} />
            <ForecastMetric label="Calibration status" value={humanize(data.evaluation.calibration_status)} />
          </div>
          <ForecastDetailGroup title="Model and input provenance">
            <ForecastDetail label="Model name" value={data.model_name} /><ForecastDetail label="Model variant" value={data.model_variant} />
            <ForecastDetail label="Model revision" value={data.model_revision} /><ForecastDetail label="Tokenizer" value={data.tokenizer_name} />
            <ForecastDetail label="Tokenizer revision" value={data.tokenizer_revision} /><ForecastDetail label="Device" value={data.device ? humanize(data.device) : 'Unavailable'} />
            <ForecastDetail label="Symbol / timeframe" value={`${data.symbol} · ${data.timeframe}`} /><ForecastDetail label="Exact instrument" value={data.input_metadata ? `${data.input_metadata.instrument.symbol} · ${data.input_metadata.instrument.exchange} · ${data.input_metadata.instrument.segment} · ${data.input_metadata.instrument.security_id} · ${data.input_metadata.instrument.instrument} · ${data.input_metadata.instrument.timeframe}` : 'Unavailable'} />
            <ForecastDetail label="Input source / health" value={data.input_metadata ? `${humanize(data.input_metadata.source)} · ${humanize(data.input_metadata.health)}` : 'Unavailable'} /><ForecastDetail label="Input metadata last candle" value={data.input_metadata?.last_candle_at ? formatTimestamp(data.input_metadata.last_candle_at) : 'Unavailable'} />
            <ForecastDetail label="Volume available" value={data.input_metadata?.volume_available === true ? 'True' : data.input_metadata?.volume_available === false ? 'False' : 'Unavailable'} /><ForecastDetail label="Forecast horizon field" value={formatInteger(data.forecast_horizon)} />
          </ForecastDetailGroup>
          <ForecastDetailGroup title="Input coverage and variables">
            <ForecastDetail label="Coverage" value={MODEL_FIELD_NOT_EXPOSED} /><ForecastDetail label="Variables used" value={MODEL_FIELD_NOT_EXPOSED} />
          </ForecastDetailGroup>
          <ForecastDetailGroup title="Operational metadata">
            <ForecastDetail label="Model generated at" value={formatTimestamp(data.generated_at)} /><ForecastDetail label="API published at" value={projection ? formatTimestamp(projection.publishedAt) : MODEL_FIELD_NOT_EXPOSED} />
            <ForecastDetail label="Source last updated" value={projection?.sourceLastUpdated ? formatTimestamp(projection.sourceLastUpdated) : MODEL_FIELD_NOT_EXPOSED} /><ForecastDetail label="UI observed at" value={projection ? formatTimestamp(projection.observedAt) : MODEL_FIELD_NOT_EXPOSED} />
            <ForecastDetail label="Trace ID" value={projection?.traceId ?? MODEL_FIELD_NOT_EXPOSED} /><ForecastDetail label="Model status" value={humanize(effectiveStatus)} />
            <ForecastDetail label="Mode" value={humanize(data.mode)} /><ForecastDetail label="Maturity label" value={humanize(data.maturity_label)} />
            <ForecastDetail label="Execution influence" value={`${data.execution_influence_percentage}%`} /><ForecastDetail label="AEGIS influence" value={`${data.aegis_influence_percentage}%`} />
            <ForecastDetail label="Readiness state" value={humanize(data.readiness_state)} /><ForecastDetail label="Cache status" value={humanize(data.cache_status)} />
            <ForecastDetail label="Scheduler health" value={humanize(data.scheduler_health)} /><ForecastDetail label="Last input candle" value={data.last_input_candle_at ? formatTimestamp(data.last_input_candle_at) : 'Unavailable'} />
            <ForecastDetail label="Input age" value={data.input_age_seconds === null ? 'Unavailable' : `${formatNumber(data.input_age_seconds)}s`} /><ForecastDetail label="Last inference" value={data.last_inference_at ? formatTimestamp(data.last_inference_at) : 'Unavailable'} />
            <ForecastDetail label="Next inference" value={data.next_expected_inference ? formatTimestamp(data.next_expected_inference) : 'Unavailable'} /><ForecastDetail label="Inference duration" value={data.inference_duration_ms === null ? 'Unavailable' : `${formatNumber(data.inference_duration_ms)}ms`} />
            <ForecastDetail label="Session" value={data.session ? `${data.session.exchange} · ${data.session.session_date} · ${humanize(data.session.session_state)} · market open ${String(data.session.market_open)} · ${humanize(data.session.reason)}` : 'Unavailable'} /><ForecastDetail label="Next valid open" value={data.session?.next_valid_open ? formatTimestamp(data.session.next_valid_open) : 'Unavailable'} />
            <ForecastDetail label="Calendar source / version" value={data.session ? `${data.session.calendar_source ?? 'Unavailable'} · ${data.session.calendar_version ?? 'Unavailable'}` : 'Unavailable'} /><ForecastDetail label="Source metadata" value={`${humanize(data.source_metadata.source)} · fixture ${String(data.source_metadata.fixture_data)} · refresh on read ${String(data.source_metadata.external_refresh_on_read)}`} />
          </ForecastDetailGroup>
          <ForecastMessages reasons={data.reason_codes} warnings={data.warnings} missing={data.missing_inputs} extra={data.evaluation.sample_warning} />
          <ForecastRawOutput data={data} />
        </div>
      </details>
    </div>
  )
}

function Chronos2Panel({ data, projection, meta }: { data: Chronos2Status; projection: ForecastProjectionMeta | null; meta?: V2Feed['meta'] }) {
  const analytics = data.derived_analytics
  const session = data.runtime?.session
  const effectiveStatus = meta?.market_input_state === 'STALE' ? 'STALE' : meta?.market_input_state === 'WAITING_FOR_NEXT_CANDLE' ? 'WAITING_FOR_NEXT_CANDLE' : data.status
  const effectiveFreshness = meta?.market_input_state ?? data.freshness
  return (
    <div className="forecast-model-content chronos-2-content">
      <div className="forecast-gauge-row">
        <ForecastGauge label="Direction" value={analytics.directional_bias ? humanize(analytics.directional_bias) : MODEL_FIELD_NOT_EXPOSED} tone={forecastDirectionTone(analytics.directional_bias)} variant="full" />
        <ForecastGauge label="Forecast confidence" value={analytics.directional_confidence === null ? MODEL_FIELD_NOT_EXPOSED : formatPercent(analytics.directional_confidence)} percent={analytics.directional_confidence} tone="platinum" variant="semicircle" />
        <ForecastGauge label="Expected move" value={data.median_terminal_move_points === null ? MODEL_FIELD_NOT_EXPOSED : `${formatSigned(data.median_terminal_move_points)} pts`} tone={forecastDirectionTone(analytics.directional_bias)} />
      </div>
      <div className="forecast-summary-section">
        <div className="forecast-summary-heading"><span>Forecast Summary</span><small>Decision-grade model outputs</small></div>
        <div className="forecast-primary-metrics">
          <ForecastMetric label="Expected move" value={data.median_terminal_move_points === null ? MODEL_FIELD_NOT_EXPOSED : `${formatSigned(data.median_terminal_move_points)} pts${data.median_terminal_move_percentage === null ? '' : ` · ${formatSigned(data.median_terminal_move_percentage)}%`}`} description="Median terminal forecast move" emphasis />
          <ForecastRange low={data.forecast_low} high={data.forecast_high} description="Probabilistic low-to-high interval" />
          <ForecastMetric label="Forecast horizon" value={data.prediction_length ? `${formatInteger(data.prediction_length)} candles` : MODEL_FIELD_NOT_EXPOSED} description="Forward prediction window" />
          <ForecastMetric label="Context window" value={data.input_candle_count === null ? MODEL_FIELD_NOT_EXPOSED : `${formatInteger(data.input_candle_count)} candles`} description="Historical context analysed" />
        </div>
      </div>
      <details className="forecast-advanced">
        <summary><span>Advanced Forecast Details</span><small>All authoritative CHRONOS-2 outputs</small></summary>
        <div className="forecast-advanced-body">
          <div className="chronos-2-wheels" aria-label="CHRONOS-2 CE and PE quality wheels">
            <ChronosQualityWheel side="CE" quality={analytics.ce_quality} freshness={data.freshness} />
            <ChronosQualityWheel side="PE" quality={analytics.pe_quality} freshness={data.freshness} />
          </div>
          <div className="forecast-detail-grid">
            <ForecastMetric label="Uncertainty" value={analytics.uncertainty ? humanize(analytics.uncertainty) : 'Unavailable'} />
            <ForecastMetric label="Trend persistence" value={analytics.trend_persistence === null ? 'Unavailable' : formatPercent(analytics.trend_persistence)} />
            <ForecastMetric label="Upward persistence" value={analytics.upward_persistence === null ? 'Unavailable' : formatPercent(analytics.upward_persistence)} />
            <ForecastMetric label="Downward persistence" value={analytics.downward_persistence === null ? 'Unavailable' : formatPercent(analytics.downward_persistence)} />
            <ForecastMetric label="Reversal risk" value={analytics.reversal_risk === null ? 'Unavailable' : formatPercent(analytics.reversal_risk)} />
            <ForecastMetric label="Forecast quality" value={analytics.forecast_quality === null ? 'Unavailable' : formatPercent(analytics.forecast_quality)} />
            <ForecastMetric label="Raw median terminal move" value={data.median_terminal_move_points === null ? 'Unavailable' : `${formatSigned(data.median_terminal_move_points)} pts${data.median_terminal_move_percentage === null ? '' : ` · ${formatSigned(data.median_terminal_move_percentage)}%`}`} />
            <ForecastMetric label="Terminal P10" value={data.terminal_p10 === null ? 'Unavailable' : formatPrice(data.terminal_p10)} />
            <ForecastMetric label="Terminal P50" value={data.terminal_p50 === null ? 'Unavailable' : formatPrice(data.terminal_p50)} />
            <ForecastMetric label="Terminal P90" value={data.terminal_p90 === null ? 'Unavailable' : formatPrice(data.terminal_p90)} />
          </div>
          <ForecastDetailGroup title="Model and forecast provenance">
            <ForecastDetail label="Analytics label" value={analytics.label} /><ForecastDetail label="Model name" value={data.model_name} />
            <ForecastDetail label="Model revision" value={data.model_revision} /><ForecastDetail label="Package version" value={data.package_version} />
            <ForecastDetail label="Mode" value={data.mode ?? 'Unavailable'} /><ForecastDetail label="Symbol / timeframe" value={`${data.symbol} · ${data.timeframe}`} />
            <ForecastDetail label="Forecast ID" value={data.forecast_id ?? 'Unavailable'} /><ForecastDetail label="Device" value={data.device ? humanize(data.device) : 'Unavailable'} />
            <ForecastDetail label="Input source" value={data.runtime?.input_metadata?.source ? humanize(data.runtime.input_metadata.source) : 'Unavailable'} /><ForecastDetail label="Runtime input count" value={data.runtime?.input_metadata ? formatInteger(data.runtime.input_metadata.candle_count) : 'Unavailable'} />
            <ForecastDetail label="Input health / last candle" value={data.runtime?.input_metadata ? `${humanize(data.runtime.input_metadata.health)} · ${data.runtime.input_metadata.last_candle_at ? formatTimestamp(data.runtime.input_metadata.last_candle_at) : 'Unavailable'}` : 'Unavailable'} /><ForecastDetail label="Context end" value={data.context_end ? formatTimestamp(data.context_end) : 'Unavailable'} />
          </ForecastDetailGroup>
          <ForecastDetailGroup title="Input coverage and variables">
            <ForecastDetail label="Coverage" value={data.input_coverage === null ? MODEL_FIELD_NOT_EXPOSED : formatPercent(data.input_coverage)} /><ForecastDetail label="Variables used" value={data.input_feature_names.length > 0 ? data.input_feature_names.map(humanize).join(', ') : MODEL_FIELD_NOT_EXPOSED} />
            <ForecastDetail label="Variable count" value={data.input_feature_count === null ? MODEL_FIELD_NOT_EXPOSED : formatInteger(data.input_feature_count)} />
          </ForecastDetailGroup>
          <ForecastDetailGroup title="Operational metadata">
            <ForecastDetail label="Model generated at" value={formatTimestamp(data.generated_at)} /><ForecastDetail label="API published at" value={projection ? formatTimestamp(projection.publishedAt) : MODEL_FIELD_NOT_EXPOSED} />
            <ForecastDetail label="Source last updated" value={projection?.sourceLastUpdated ? formatTimestamp(projection.sourceLastUpdated) : MODEL_FIELD_NOT_EXPOSED} /><ForecastDetail label="UI observed at" value={projection ? formatTimestamp(projection.observedAt) : MODEL_FIELD_NOT_EXPOSED} />
            <ForecastDetail label="Trace ID" value={projection?.traceId ?? MODEL_FIELD_NOT_EXPOSED} /><ForecastDetail label="Status / freshness" value={`${humanize(effectiveStatus)} · ${humanize(effectiveFreshness)}`} />
            <ForecastDetail label="Model readiness" value={data.model_readiness ? humanize(data.model_readiness) : 'Unavailable'} /><ForecastDetail label="Input readiness" value={data.input_readiness ? humanize(data.input_readiness) : 'Unavailable'} />
            <ForecastDetail label="Scheduler health" value={data.runtime?.scheduler_health ? humanize(data.runtime.scheduler_health) : 'Unavailable'} /><ForecastDetail label="Next inference" value={data.runtime?.next_expected_inference ? formatTimestamp(data.runtime.next_expected_inference) : 'Unavailable'} />
            <ForecastDetail label="Inference duration" value={data.inference_duration_ms === null ? 'Unavailable' : `${formatNumber(data.inference_duration_ms)}ms`} /><ForecastDetail label="Session" value={session ? `${humanize(session.session_state)} · market open ${String(session.market_open)} · ${humanize(session.reason)}` : 'Unavailable'} />
            <ForecastDetail label="Next eligible session" value={data.next_eligible_session ? formatTimestamp(data.next_eligible_session) : 'Unavailable'} /><ForecastDetail label="Next valid open" value={session?.next_valid_open ? formatTimestamp(session.next_valid_open) : 'Unavailable'} />
            <ForecastDetail label="Shadow / advisory" value={`${String(data.shadow_mode)} / ${String(data.advisory_only)}`} /><ForecastDetail label="Execution / AEGIS influence" value={`${data.execution_influence}% / ${data.aegis_direct_influence}%`} />
          </ForecastDetailGroup>
          <ForecastMessages reasons={[]} warnings={data.warnings} missing={[...analytics.ce_quality.missing_components, ...analytics.pe_quality.missing_components]} />
          <ForecastRawOutput data={data} />
        </div>
      </details>
    </div>
  )
}

const MODEL_FIELD_NOT_EXPOSED = 'Not Reported'

function ForecastGauge({ label, value, percent = null, tone, variant = 'radial' }: { label: string; value: string; percent?: number | null; tone: string; variant?: 'full' | 'radial' | 'semicircle' }) {
  const bounded = percent === null ? null : Math.max(0, Math.min(100, percent))
  const missing = value === MODEL_FIELD_NOT_EXPOSED
  return (
    <div className={`forecast-gauge ${variant} ${bounded === null && variant !== 'full' ? 'non-quantitative' : ''} ${missing ? 'not-exposed' : tone}`} style={bounded === null ? undefined : { '--gauge-value': `${bounded}%`, '--gauge-semi-value': `${bounded / 2}%` } as CSSProperties}>
      <div><strong className={missing ? 'model-field-not-exposed' : ''}>{missing ? MODEL_FIELD_NOT_EXPOSED : value}</strong><span>{label}</span></div>
    </div>
  )
}

function ForecastMetric({ label, value, description, percent = null, compact = false, emphasis = false }: { label: string; value: string; description?: string; percent?: number | null; compact?: boolean; emphasis?: boolean }) {
  const missing = value === MODEL_FIELD_NOT_EXPOSED || value === 'Unavailable' || value === '—'
  const bounded = percent === null ? null : Math.max(0, Math.min(100, percent))
  return <div className={`forecast-metric ${compact ? 'compact-value' : ''} ${emphasis ? 'emphasis' : ''} ${missing ? 'not-exposed' : ''}`}><span>{label}</span><strong className={missing ? 'model-field-not-exposed' : ''}>{missing ? MODEL_FIELD_NOT_EXPOSED : value}</strong>{description && <small>{description}</small>}{bounded !== null && <div className="forecast-micro-bar"><i style={{ width: `${bounded}%` }} /></div>}</div>
}

function ForecastRange({ low, high, description }: { low: number | null; high: number | null; description: string }) {
  const missing = low === null || high === null
  return <div className={`forecast-metric forecast-range ${missing ? 'not-exposed' : ''}`}><span>Prediction range</span>{missing ? <strong className="model-field-not-exposed">{MODEL_FIELD_NOT_EXPOSED}</strong> : <><div className="forecast-range-values"><strong>{formatPrice(low)}</strong><strong>{formatPrice(high)}</strong></div><div className="forecast-range-rail" aria-label="Reported low-to-high interval" /></>}<small>{description}</small></div>
}

function ForecastDetailGroup({ title, children }: { title: string; children: ReactNode }) {
  return <section className="forecast-detail-group"><h4>{title}</h4><dl>{children}</dl></section>
}

function ForecastDetail({ label, value }: { label: string; value: string }) {
  const normalized = (value || MODEL_FIELD_NOT_EXPOSED).replaceAll('Unavailable', MODEL_FIELD_NOT_EXPOSED)
  return <div><dt>{label}</dt><dd>{normalized}</dd></div>
}

function ForecastRawOutput({ data }: { data: object }) {
  return <details className="forecast-raw-output"><summary>Authoritative raw model output</summary><pre>{JSON.stringify(data, null, 2)}</pre></details>
}

function forecastDirectionTone(value: string | null) {
  const normalized = value?.toUpperCase()
  if (normalized === 'BULLISH') return 'positive'
  if (normalized === 'BEARISH') return 'negative'
  if (normalized === 'SIDEWAYS' || normalized === 'NEUTRAL') return 'neutral'
  return 'not-exposed'
}

function ForecastMessages({ reasons, warnings, missing, extra = null }: { reasons: string[]; warnings: string[]; missing: string[]; extra?: string | null }) {
  const uniqueMissing = [...new Set(missing)]
  if (reasons.length === 0 && warnings.length === 0 && uniqueMissing.length === 0 && !extra) return null
  return (
    <div className="forecast-messages">
      {reasons.length > 0 && <div><span>Reason codes</span><p>{reasons.map(humanize).join(' · ')}</p></div>}
      {warnings.length > 0 && <div><span>Warnings</span><p>{warnings.map(humanize).join(' · ')}</p></div>}
      {uniqueMissing.length > 0 && <div><span>Missing inputs</span><p>{uniqueMissing.map(humanize).join(' · ')}</p></div>}
      {extra && <div><span>Evaluation note</span><p>{extra}</p></div>}
    </div>
  )
}

function ChronosQualityWheel({ side, quality, freshness }: { side: 'CE' | 'PE'; quality: Chronos2Quality; freshness: string }) {
  const score = quality.score
  const color = side === 'CE' ? 'rgba(56,189,248,.78)' : 'rgba(139,92,246,.8)'
  const arc = score === null ? 'conic-gradient(rgba(255,255,255,.06) 0 100%)' : `conic-gradient(${color} 0 ${score}%, rgba(255,255,255,.055) ${score}% 100%)`
  return <article className={`chronos-quality-card ${side.toLowerCase()}`}>
    <div className="chronos-quality-wheel" style={{ background: arc }}><div><span>CITADEL-DERIVED</span><strong>{score === null ? 'FIELD NOT EXPOSED' : formatNumber(score)}</strong><small>{side} quality</small></div></div>
    <div><strong>{score === null ? MODEL_FIELD_NOT_EXPOSED : humanize(quality.interpretation)}</strong><span>Evidence coverage <b>{formatPercent(quality.evidence_coverage)}</b></span><span>Freshness <b>{humanize(quality.freshness ?? freshness)}</b></span><span>Label <b>{humanize(quality.label)}</b></span><span>Shadow <b>{String(quality.shadow)}</b></span><span>Recommendation <b>{quality.recommendation === null ? MODEL_FIELD_NOT_EXPOSED : quality.recommendation}</b></span>{quality.missing_components.length > 0 && <small>Missing: {quality.missing_components.map(humanize).join(', ')}</small>}</div>
  </article>
}

function ProbabilityWheel({ side, outlook, bullish, bearish, sideways }: { side: 'CE' | 'PE'; outlook: OptionOutlook; bullish: number | null; bearish: number | null; sideways: number | null }) {
  const available = [bullish, bearish, sideways].every((value) => value !== null)
  const primary = side === 'CE' ? bullish : bearish
  const primaryColor = side === 'CE' ? 'rgba(16,185,129,.82)' : 'rgba(239,68,68,.78)'
  const oppositeColor = side === 'CE' ? 'rgba(239,68,68,.68)' : 'rgba(16,185,129,.68)'
  const background = available
    ? `conic-gradient(${primaryColor} 0 ${primary}%, rgba(139,92,246,.58) ${primary}% ${(primary ?? 0) + (sideways ?? 0)}%, ${oppositeColor} ${(primary ?? 0) + (sideways ?? 0)}% 100%)`
    : 'conic-gradient(rgba(255,255,255,.05) 0 100%)'
  return (
    <article className={`probability-wheel-card ${side.toLowerCase()}`}>
      <div className="probability-wheel" style={{ background }} aria-label={`${side} directional path probability wheel`}>
        <div><span>{side} OUTLOOK</span><strong>{outlook.option_buying_quality_score === null ? 'FIELD NOT EXPOSED' : formatNumber(outlook.option_buying_quality_score)}</strong><small>Option-buying quality</small></div>
      </div>
      <div className="wheel-legend">
        <span><i className="bullish" /><em>Bullish</em><strong>{formatKronosPercent(bullish)}</strong></span>
        <span><i className="sideways" /><em>Sideways</em><strong>{formatKronosPercent(sideways)}</strong></span>
        <span><i className="bearish" /><em>Bearish</em><strong>{formatKronosPercent(bearish)}</strong></span>
      </div>
      <div className="wheel-detail-grid">
        <WheelMetric label="Directional probability" value={formatKronosPercent(outlook.directional_probability)} />
        <WheelMetric label={`${side === 'CE' ? 'Bullish' : 'Bearish'} persistence`} value={formatKronosPercent(outlook.persistence_probability)} />
        <WheelMetric label="Reversal risk" value={formatKronosPercent(outlook.reversal_risk)} />
        <WheelMetric label="Sideways probability" value={formatKronosPercent(outlook.sideways_probability)} />
        <WheelMetric label="Opposite probability" value={formatKronosPercent(outlook.opposite_probability)} />
        <WheelMetric label="Forecast volatility" value={formatKronosPercent(outlook.forecast_volatility)} />
        <WheelMetric label="Uncertainty" value={formatKronosPercent(outlook.uncertainty)} />
        <WheelMetric label="Expected favorable move" value={outlook.expected_favorable_move === null ? MODEL_FIELD_NOT_EXPOSED : `${formatNumber(outlook.expected_favorable_move)}%`} />
        <WheelMetric label="Recommendation" value={outlook.recommendation_state === 'UNAVAILABLE' ? MODEL_FIELD_NOT_EXPOSED : humanize(outlook.recommendation_state)} />
        <WheelMetric label="Output label" value={humanize(outlook.label)} />
      </div>
    </article>
  )
}

function WheelMetric({ label, value }: { label: string; value: string }) {
  return <div className="wheel-metric"><span>{label}</span><strong>{value}</strong></div>
}

function formatKronosPercent(value: number | null | undefined) {
  return value === null || value === undefined ? MODEL_FIELD_NOT_EXPOSED : `${formatNumber(value)}%`
}

function OraclePanel({ data }: { data: OracleReasoning }) {
  return (
    <div className="engine-content">
      <div className="oracle-verdict">
        <div><span>Technical signal</span><Badge value={data.signal} prominent /></div>
        <div><span>Confidence</span><strong>{formatPercent(data.confidence)}</strong><small>{humanize(data.confidence_label)}</small></div>
      </div>
      <div className="oracle-health-row">
        <span>Health <strong className={data.oracle_status === 'READY' ? 'positive-text' : data.oracle_status === 'BLOCKED' ? 'negative-text' : ''}>{data.oracle_status}</strong></span>
        <span>Freshness <strong>{data.data_status}</strong></span>
        <span>Last updated <strong>{formatTimestamp(data.generated_at)}</strong></span>
      </div>
      <div className="reasoning-block"><span>Explainable assessment</span><p>{data.reasoning}</p></div>
      <div className="engine-metrics oracle-levels">
        <EngineMetric label="Symbol / timeframe" value={`${data.symbol} · ${data.timeframe}`} />
        <EngineMetric label="Directional bias" value={humanize(data.directional_bias)} />
        <EngineMetric label="Regime" value={humanize(data.regime)} />
        <EngineMetric label="Data age" value={data.data_age_seconds === null ? 'Unavailable' : `${formatNumber(data.data_age_seconds)}s`} />
        <EngineMetric label="Maturity" value={humanize(data.maturity_label)} />
      </div>
      <div className="oracle-reasons"><span>Top reason codes</span><div>{data.reason_codes.slice(0, 4).map((code) => <Badge key={code} value={code} />)}</div></div>
      {data.warnings.length > 0 && <div className="oracle-warning"><span>Assessment warning</span><p>{data.warnings.slice(0, 2).map(humanize).join(' · ')}</p></div>}
    </div>
  )
}

function AthenaPanel({ data }: { data: AthenaWheel }) {
  const hasCapital = [data.available_capital, data.blocked_capital, data.current_equity].some((value) => value !== null)
  return (
    <div className="engine-content">
      <div className="risk-state athena-summary">
        <div><span>Risk state</span><Badge value={data.risk_state} prominent /></div>
        <div><span>Recommendation</span><Badge value={data.recommendation} prominent /></div>
        <div><span>Advisory size</span><strong>{formatNumber(data.recommended_size_multiplier)}×</strong></div>
      </div>
      <div className="oracle-health-row">
        <span>Health <strong className={data.athena_status === 'BLOCKED' || data.athena_status === 'UNAVAILABLE' ? 'negative-text' : data.athena_status === 'READY' ? 'positive-text' : ''}>{data.athena_status}</strong></span>
        <span>Last update <strong>{formatTimestamp(data.generated_at)}</strong></span>
        <span>Maturity <strong>{humanize(data.maturity_label)}</strong></span>
      </div>
      <div className="reasoning-block"><span>Advisory assessment</span><p>{data.explanation}</p></div>
      <div className="engine-metrics athena-metrics">
        <EngineMetric label="Daily loss used" value={formatPercent(data.daily_loss_used_percentage)} />
        <EngineMetric label="Daily risk headroom" value={formatMoney(data.daily_loss_headroom)} />
        <EngineMetric label="Trades used" value={formatLimitPair(data.trades_taken, data.maximum_trades)} />
        <EngineMetric label="Loss-streak usage" value={formatPercent(data.loss_streak_usage_percentage)} />
        <EngineMetric label="Open positions" value={formatLimitPair(data.open_positions, data.maximum_open_positions)} />
        <EngineMetric label="Drawdown" value={formatMoney(data.current_drawdown)} />
        <EngineMetric label="Exposure usage" value={formatPercent(data.exposure_usage_percentage)} />
        <EngineMetric label="Risk headroom" value={formatPercent(data.risk_headroom_percentage)} />
      </div>
      {hasCapital && <div className="engine-metrics athena-capital-metrics">
        {data.available_capital !== null && <EngineMetric label={data.source_metadata.capital_basis === 'DEVELOPMENT_CAPITAL_SIMULATION_ONLY' ? 'Development capital · simulation only' : 'Available capital'} value={formatMoney(data.available_capital)} />}
        {data.blocked_capital !== null && <EngineMetric label="Blocked capital" value={formatMoney(data.blocked_capital)} />}
        {data.current_equity !== null && <EngineMetric label="Current equity" value={formatMoney(data.current_equity)} />}
      </div>}
      <div className="oracle-reasons"><span>Top reason codes</span><div>{data.reason_codes.slice(0, 4).map((code) => <Badge key={code} value={code} />)}</div></div>
      {data.warnings.length > 0 && <div className="oracle-warning"><span>Advisory warnings</span><p>{data.warnings.slice(0, 3).map(humanize).join(' · ')}</p></div>}
    </div>
  )
}

function HermesPanel({ data }: { data: HermesStatus }) {
  const next = data.next_major_event
  const affectedScope = [...data.affected_markets, ...data.affected_indices, ...data.affected_sectors, ...data.affected_symbols]
  const unavailable = data.hermes_status === 'UNAVAILABLE' || data.hermes_status === 'NOT_CONFIGURED'
  return (
    <div className="engine-content">
      <div className="risk-state hermes-summary">
        <div className={data.overall_event_risk === 'HIGH' || data.overall_event_risk === 'CRITICAL' ? 'event-risk-high' : ''}><span>Event risk</span><Badge value={data.overall_event_risk} prominent /></div>
        <div><span>Recommendation</span><Badge value={data.recommendation} prominent /></div>
        <div><span>Sentiment</span><Badge value={data.dominant_sentiment} /></div>
      </div>
      <div className="oracle-health-row">
        <span>Health <strong className={data.hermes_status === 'STALE' || data.hermes_status === 'UNAVAILABLE' || data.hermes_status === 'BLOCKED' ? 'negative-text' : data.hermes_status === 'READY' ? 'positive-text' : ''}>{data.hermes_status.replaceAll('_', ' ')}</strong></span>
        <span>Provider <strong>{humanize(data.source_metadata.provider_mode)}</strong></span>
        <span>Freshness <strong>{data.freshness_metadata.snapshot_age_seconds === null ? 'Unavailable' : `${formatNumber(data.freshness_metadata.snapshot_age_seconds)}s`}</strong></span>
        <span>Updated <strong>{formatTimestamp(data.generated_at)}</strong></span>
      </div>
      {(data.source_metadata.fixture_data || data.source_metadata.provider_mode === 'IN_MEMORY') && <div className="hermes-mode-banner">Fixture / development intelligence · Not live news</div>}
      <div className="reasoning-block"><span>Advisory event assessment</span><p>{data.human_readable_summary}</p></div>
      <article className={`hermes-next-event ${next?.impact === 'CRITICAL' || next?.impact === 'HIGH' ? 'high-risk' : ''}`}>
        <span>Next major event</span>
        {next ? <>
          <strong>{next.headline}</strong>
          <div><Badge value={next.impact} /><Badge value={next.timing_state} /><Badge value={next.source_confidence} /><time dateTime={next.scheduled_at ?? next.published_at ?? undefined}>{next.event_countdown_seconds === null ? 'Countdown unavailable' : formatCountdown(next.event_countdown_seconds)}</time></div>
        </> : <strong className="unavailable">{unavailable ? 'Unavailable — no configured provider data' : 'No upcoming major event in the normalized set'}</strong>}
      </article>
      <div className="engine-metrics hermes-metrics">
        <EngineMetric label="Imminent events" value={formatNullableInteger(data.imminent_event_count)} />
        <EngineMetric label="High / critical" value={data.high_impact_event_count === null || data.critical_event_count === null ? 'Unavailable' : `${formatInteger(data.high_impact_event_count)} / ${formatInteger(data.critical_event_count)}`} />
        <EngineMetric label="Conflicts" value={formatNullableInteger(data.conflicting_event_count)} />
        <EngineMetric label="Affected scope" value={affectedScope.length > 0 ? affectedScope.slice(0, 3).join(' · ') : 'Unavailable'} />
      </div>
      <div className="hermes-event-list">
        <span>Top normalized events</span>
        {data.top_events.length > 0 ? data.top_events.slice(0, 3).map((item) => (
          <article key={item.event_id}>
            <div><Badge value={item.impact} /><Badge value={item.timing_state} />{item.is_conflicting && <Badge value="CONFLICT" />}</div>
            <strong>{item.headline}</strong>
            <small>{item.source_name ?? 'Source unavailable'} · {humanize(item.source_confidence)} confidence</small>
          </article>
        )) : <p className="hermes-empty">{unavailable ? 'Event data unavailable.' : 'No normalized events returned.'}</p>}
      </div>
      <div className="oracle-reasons"><span>Top reason codes</span><div>{data.reason_codes.slice(0, 5).map((code) => <Badge key={code} value={code} />)}</div></div>
      {(data.warnings.length > 0 || data.missing_inputs.length > 0) && <div className="oracle-warning"><span>Source / coverage warnings</span><p>{[...data.warnings, ...data.missing_inputs.map((item) => `MISSING_${item}`)].slice(0, 4).map(humanize).join(' · ')}</p></div>}
      <div className="hermes-maturity">Maturity: {humanize(data.maturity_label)} · Advisory only</div>
    </div>
  )
}

function InsightsPanel({ insights }: { insights: AIInsight[] }) {
  if (insights.length === 0) return <div className="empty-inline">No insights returned by the backend.</div>

  return (
    <div className="insights-list">
      {insights.map((insight) => (
        <article key={`${insight.source}|${insight.title}|${insight.message}`}>
          <div><Badge value={insight.severity} /><span>Category: {insight.title}</span><span>Source: {insight.source}</span><time dateTime={insight.timestamp ?? undefined}>{insight.timestamp ? formatTimestamp(insight.timestamp) : "—"}</time></div>
          <p>{insight.message}</p>
        </article>
      ))}
    </div>
  )
}

function PersonalOraclePanel({ data }: { data: PersonalOracleSummary }) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [acknowledged, setAcknowledged] = useState<Set<string>>(() => loadOracleAcknowledgements())
  const [search, setSearch] = useState('')
  const [family, setFamily] = useState('ALL')
  const [timeframe, setTimeframe] = useState('ALL')
  const [symbol, setSymbol] = useState('ALL')
  const [optionSide, setOptionSide] = useState('ALL')
  const [page, setPage] = useState(0)
  const strategies = useMemo(() => data.strategyScope.filter((row) => {
    const query = search.trim().toLowerCase()
    return (!query || `${row.id} ${row.family} ${row.symbol}`.toLowerCase().includes(query))
      && (family === 'ALL' || row.family === family)
      && (timeframe === 'ALL' || row.timeframe === timeframe)
      && (symbol === 'ALL' || row.symbol === symbol)
      && (optionSide === 'ALL' || row.optionSide === optionSide)
  }), [data.strategyScope, family, optionSide, search, symbol, timeframe])
  const pageSize = 20
  const visibleStrategies = strategies.slice(page * pageSize, page * pageSize + pageSize)
  const acknowledge = (observation: PersonalOracleObservationModel) => {
    setAcknowledged(saveOracleAcknowledgement(observation.id, observation.version))
    setDrawerOpen(true)
  }
  if (data.status === 'UNAVAILABLE') return <div className="empty-inline">Personal ORACLE dataset unavailable.</div>
  return (
    <>
      <div className="personal-oracle-content personal-oracle-lite">
        <div className="personal-oracle-statusline">
          <span><i />{humanize(data.health)}</span>
          <Badge value={data.ingestion.label} />
          <Badge value="ADVISORY ONLY" />
          <Badge value="EXECUTION INFLUENCE 0%" />
        </div>
        <div className="personal-oracle-overview personal-oracle-lite-overview">
          <PersonalOracleMetric label="STRATEGY INTELLIGENCE" value={`${formatInteger(data.hero.discoveredStrategyCount)} strategies · ${formatInteger(data.hero.needsAttentionCount)} need attention`} />
          <PersonalOracleMetric label="EXECUTION AUDIT" value={data.hero.highestPriorityExecutionIssue ?? 'No active execution defect'} />
          <PersonalOracleMetric label="PATTERN DETECTION" value={`${formatInteger(data.hero.activeObservationCount)} active · ${formatInteger(data.hero.newObservationCount)} new`} />
          <PersonalOracleMetric label="PERFORMANCE LEAKS" value={data.hero.highestImpactPerformanceLeak ? `Top impact: ${data.hero.highestImpactPerformanceLeak}` : 'No active issue'} />
          <PersonalOracleMetric label="DISCIPLINE ANALYSIS" value={data.hero.disciplineMetric ? `${data.hero.disciplineMetric.label}: ${formatPercent(data.hero.disciplineMetric.percentage)}` : 'Insufficient evidence'} />
          <PersonalOracleMetric label="TODAY'S FOCUS" value={data.hero.todayFocus.text} />
        </div>
        <div className="personal-oracle-block" aria-label="Personal Shadow Advisory">
          <span>Personal Shadow Advisory</span>
          {data.shadow.latest ? (
            <div className="personal-oracle-status-counts">
              <PersonalOracleMetric label="CLASSIFICATION" value={humanize(data.shadow.latest.classification)} />
              <PersonalOracleMetric label="CONFIDENCE" value={humanize(data.shadow.latest.confidenceBand)} />
              <PersonalOracleMetric label="STRATEGY / SETUP" value={`${data.shadow.latest.strategy ?? 'NOT REPORTED'} · ${data.shadow.latest.setup ?? 'NOT REPORTED'} · ${data.shadow.latest.timeframe ?? 'NOT REPORTED'}`} />
              <PersonalOracleMetric label="EVIDENCE" value={`Expectancy ${data.shadow.latest.cohortExpectancy == null ? 'NOT REPORTED' : formatSigned(data.shadow.latest.cohortExpectancy)} · Win rate ${data.shadow.latest.cohortWinRate == null ? 'NOT REPORTED' : formatPercent(data.shadow.latest.cohortWinRate)} · n=${formatInteger(data.shadow.latest.cohortSampleSize)}`} />
              <PersonalOracleMetric label="REASONS" value={data.shadow.latest.reasonCodes.map(humanize).join(' · ') || 'INSUFFICIENT DATA'} />
              <PersonalOracleMetric label="CONTEXT / POLICY" value={`${formatPercent(data.shadow.latest.contextCompletenessPercentage)} · ${humanize(data.shadow.latest.policySource)} · ${humanize(data.shadow.outcomeStatus)}`} />
            </div>
          ) : <div className="empty-inline">No prospective advisory recorded. Shadow intelligence is collecting pre-trade evidence.</div>}
          <small>Generated {data.shadow.latest?.generatedAt ? formatTimestamp(data.shadow.latest.generatedAt) : 'NOT REPORTED'} · Execution influence ZERO</small>
        </div>
        <div className="personal-oracle-block" aria-label="Prospective Validation">
          <span>Prospective Validation</span>
          <div className="personal-oracle-status-counts">
            <PersonalOracleMetric label="ADVISORIES" value={formatInteger(data.shadow.scorecard.prospectiveAdvisories)} />
            <PersonalOracleMetric label="COMPLETED" value={formatInteger(data.shadow.scorecard.completedOutcomes)} />
            <PersonalOracleMetric label="PENDING" value={formatInteger(data.shadow.scorecard.pendingAdvisories)} />
            <PersonalOracleMetric label="OUTCOME EVIDENCE" value={data.shadow.scorecard.completedOutcomes < 5 ? 'INSUFFICIENT SAMPLE' : Object.entries(data.shadow.scorecard.classificationDistribution).map(([label, count]) => `${humanize(label)} ${count}`).join(' · ')} />
          </div>
        </div>
        <div className="personal-oracle-block">
          <span>Top insights</span>
          <div className="personal-oracle-observations">
            {data.observations.length ? data.observations.slice(0, 3).map((observation) => {
              const isAcknowledged = acknowledged.has(oracleAcknowledgementKey(observation.id, observation.version))
              const isNew = observation.status === 'NEW' && !isAcknowledged
              return (
                <button
                  key={`${observation.id}:${observation.version}`}
                  type="button"
                  className={`personal-oracle-observation severity-${observation.severity.toLowerCase()}${isNew ? ' is-new' : ''}`}
                  onClick={() => acknowledge(observation)}
                >
                  <span>{humanize(isAcknowledged ? 'ACKNOWLEDGED' : observation.category)}</span>
                  <strong>{observation.title}</strong>
                  <p>{observation.summary}</p>
                  <small>{observation.sampleSize} samples · {formatPercent((observation.confidence ?? 0) * 100)} confidence</small>
                </button>
              )
            }) : <div className="empty-inline">Collecting evidence. No threshold-qualified observation yet.</div>}
          </div>
        </div>
        <div className="personal-oracle-focus">
          <div>
            <span>Operational metadata</span>
            <small>
              Status {humanize(data.status)} · Health {humanize(data.health)} · Readiness {humanize(data.readiness)}
              {' · '}{formatInteger(data.observedTrades)} observed · {formatInteger(data.analysedStrategies)} analysed
              {' · '}Last {data.lastAnalysedAt ? formatTimestamp(data.lastAnalysedAt) : 'NOT REPORTED'}
              {' · '}Manual {humanize(data.manualBehaviourStatus)} · Freshness {humanize(data.freshness.state)}
              {data.freshness.ageSeconds == null ? '' : ` ${formatNumber(data.freshness.ageSeconds)}s`}
              {' · '}Snapshot {formatInteger(data.snapshotVersion)} · Influence 0%
              <br />Trade {data.ingestion.latestTradeTimestamp ? formatTimestamp(data.ingestion.latestTradeTimestamp) : 'NOT REPORTED'}
              {' · '}Oracle ingest {data.ingestion.latestOracleIngestTimestamp ? formatTimestamp(data.ingestion.latestOracleIngestTimestamp) : 'NOT REPORTED'}
              {' · '}{humanize(data.ingestion.freshnessStatus)} · Context {formatPercent(data.ingestion.contextCompletenessPercentage)}
              {' · '}Missing {data.ingestion.missingContextFields.length ? data.ingestion.missingContextFields.map(humanize).join(', ') : 'NONE'}
            </small>
          </div>
          <button type="button" onClick={() => setDrawerOpen(true)}>View details →</button>
        </div>
        <div className="hermes-maturity">Advisory only · No psychology inference · No execution, risk, strategy, or AEGIS authority</div>
      </div>
      {drawerOpen && (
        <div className="personal-oracle-drawer-backdrop" role="presentation" onMouseDown={() => setDrawerOpen(false)}>
          <aside className="personal-oracle-drawer" role="dialog" aria-modal="true" aria-label="Personal Oracle evidence" onMouseDown={(event) => event.stopPropagation()}>
            <header><div><span>06C / ORACLE EVIDENCE</span><h3>Personal Trading Intelligence</h3></div><button type="button" onClick={() => setDrawerOpen(false)}>Close</button></header>
            <section>
              <h4>Observations <small>{data.evidence.observationCount} total</small></h4>
              <div className="personal-oracle-drawer-observations">
                {(data.allObservations.length ? data.allObservations : data.observations).map((observation) => {
                  const read = acknowledged.has(oracleAcknowledgementKey(observation.id, observation.version))
                  return <article key={`${observation.id}:${observation.version}`}><div><Badge value={read ? 'ACKNOWLEDGED' : observation.status} /><Badge value={observation.severity} /></div><strong>{observation.title}</strong><p>{observation.summary}</p><dl><div><dt>Confidence</dt><dd>{formatPercent((observation.confidence ?? 0) * 100)}</dd></div><div><dt>Sample</dt><dd>{observation.sampleSize}</dd></div><div><dt>Strategies</dt><dd>{observation.affectedStrategyCount}</dd></div><div><dt>Actual impact</dt><dd>{observation.actualImpact == null ? 'NOT REPORTED' : formatSigned(observation.actualImpact)}</dd></div><div><dt>Hypothetical</dt><dd>{observation.hypotheticalImpact == null ? 'NOT REPORTED' : formatSigned(observation.hypotheticalImpact)}</dd></div><div><dt>Updated</dt><dd>{observation.lastUpdatedAt ? formatTimestamp(observation.lastUpdatedAt) : 'NOT REPORTED'}</dd></div></dl></article>
                })}
              </div>
            </section>
            <section>
              <h4>Strategy status</h4>
              <div className="personal-oracle-status-counts"><PersonalOracleMetric label="Stable" value={formatInteger(data.strategyStatus.stable)} /><PersonalOracleMetric label="Improving" value={formatInteger(data.strategyStatus.improving)} /><PersonalOracleMetric label="Needs attention" value={formatInteger(data.strategyStatus.needsAttention)} /><PersonalOracleMetric label="Learning" value={formatInteger(data.strategyStatus.learning)} /><PersonalOracleMetric label="Insufficient data" value={formatInteger(data.strategyStatus.insufficientData)} /></div>
              <div className="personal-oracle-filters">
                <input aria-label="Search strategies" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0) }} placeholder="Search strategy or family" />
                <OracleFilter label="Family" value={family} values={data.strategyScope.map((row) => row.family)} onChange={(value) => { setFamily(value); setPage(0) }} />
                <OracleFilter label="Timeframe" value={timeframe} values={data.strategyScope.map((row) => row.timeframe)} onChange={(value) => { setTimeframe(value); setPage(0) }} />
                <OracleFilter label="Symbol" value={symbol} values={data.strategyScope.map((row) => row.symbol)} onChange={(value) => { setSymbol(value); setPage(0) }} />
                <OracleFilter label="Side" value={optionSide} values={data.strategyScope.map((row) => row.optionSide)} onChange={(value) => { setOptionSide(value); setPage(0) }} />
              </div>
              <div className="personal-oracle-strategy-table">{visibleStrategies.map((row) => <div key={row.id}><strong>{row.id}</strong><span>{row.family}</span><span>{row.symbol}</span><span>{row.timeframe}</span><span>{row.optionSide}</span><Badge value={row.status} /></div>)}</div>
              <div className="personal-oracle-pagination"><span>{strategies.length} strategies · page {page + 1}</span><div><button type="button" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button><button type="button" disabled={(page + 1) * pageSize >= strategies.length} onClick={() => setPage((value) => value + 1)}>Next</button></div></div>
            </section>
            <PersonalOracleLegacyEvidence data={data} />
            <section>
              <h4>Trade evidence <small>Latest {data.tradeEvidence.length}</small></h4>
              <div className="personal-oracle-trade-evidence">{data.tradeEvidence.map((row) => <div key={`${row.strategyId}:${row.sourceId}`}><strong>{row.strategyId}</strong><span>{row.sourceId}</span><Badge value={row.outcome} /><span className={row.realizedPnl == null ? 'unavailable' : row.realizedPnl >= 0 ? 'positive' : 'negative'}>{row.realizedPnl == null ? 'NOT REPORTED' : formatSigned(row.realizedPnl)}</span><span>{humanize(row.executionIntegrity)}</span><time>{row.exitedAt ? formatTimestamp(row.exitedAt) : 'NOT REPORTED'}</time></div>)}</div>
            </section>
          </aside>
        </div>
      )}
    </>
  )
}

function PersonalOracleMetric({ label, value }: { label: string; value: string }) {
  return <div className="personal-oracle-metric"><span>{label}</span><strong className={value === '—' ? 'unavailable' : ''}>{value}</strong></div>
}

function OracleFilter({ label, value, values, onChange }: { label: string; value: string; values: string[]; onChange: (value: string) => void }) {
  return <label><span>{label}</span><select value={value} onChange={(event) => onChange(event.target.value)}><option value="ALL">All</option>{[...new Set(values.filter(Boolean))].sort().map((item) => <option key={item} value={item}>{humanize(item)}</option>)}</select></label>
}

function PersonalOracleLegacyEvidence({ data }: { data: PersonalOracleSummary }) {
  const coverage = data.evidence.coverage
  const behavior = data.evidence.behavior
  const trends = oracleObject(data.evidence.trends)
  const currentTrend = oracleObject(trends.current_window)
  const coaching = oracleList(oracleObject(data.evidence.coaching).recommendations)
  const findings = data.evidence.behavioralFindings
  const postLoss = findings.find((item) => item.type === 'POST_LOSS_DEGRADATION')
  const supporting = oracleObject(postLoss?.supporting_sample)
  const comparison = oracleObject(postLoss?.comparison_sample)
  return <section><h4>Existing 06C evidence</h4><div className="personal-oracle-status-counts"><PersonalOracleMetric label="Observed trades" value={formatInteger(data.observedTrades)} /><PersonalOracleMetric label="Behaviour coverage" value={oraclePercent(behavior.behavioral_coverage_percentage)} /><PersonalOracleMetric label="Context coverage" value={oraclePercent(coverage.complete_context_percentage)} /><PersonalOracleMetric label="Cooldown compliance" value={oraclePercent(currentTrend.cooldown_compliance)} /><PersonalOracleMetric label="After-loss expectancy" value={oracleSigned(supporting.expectancy)} /><PersonalOracleMetric label="After-win expectancy" value={oracleSigned(comparison.expectancy)} /></div><div className="personal-oracle-coaching">{coaching.slice(0, 3).map((item, index) => <article key={String(item.recommendation_id ?? index)}><div><Badge value={String(item.state ?? 'INSUFFICIENT_DATA')} /><small>{formatInteger(Number(item.sample_size ?? 0))} samples</small></div><strong>{String(item.title ?? 'Continue collecting evidence')}</strong><p>{String(item.evidence_summary ?? 'No additional evidence reported.')}</p></article>)}</div><div className="hermes-maturity">Evidence maturity: {humanize(data.evidence.maturity)} · {data.evidence.limitations.join(' · ') || 'No limitations reported'}</div></section>
}

function oracleObject(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
}

function oracleList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.map(oracleObject) : []
}

function oraclePercent(value: unknown) {
  return typeof value === 'number' ? formatPercent(value) : 'NOT REPORTED'
}

function oracleSigned(value: unknown) {
  return typeof value === 'number' ? formatSigned(value) : 'NOT REPORTED'
}

function EngineMetric({ label, value }: { label: string; value: string }) {
  const isUnavailable = value === 'Unavailable'
  return (
    <div title={isUnavailable ? 'Simulation Mode Only' : undefined}>
      <span>{label}</span>
      <strong className={isUnavailable ? 'unavailable' : ''}>{value}</strong>
    </div>
  )
}

function WidgetLoading({ label }: { label: string }) {
  return <div className="widget-loading" aria-label={label} aria-busy="true"><i className="loading-ring" /><strong>{label}</strong><span>Waiting for backend response</span></div>
}

function FeedPlaceholder({ error, label }: { error: string | null; label: string }) {
  return <div className="feed-placeholder"><WifiOff size={22} /><strong>{error ? `Unable to load ${label}` : `Connecting to ${label}`}</strong><span>{error ? `${error}. Retrying automatically.` : 'Waiting for the first backend response.'}</span></div>
}

function toneFor(value: string | null) {
  const normalized = value?.toUpperCase() ?? ''
  if (['BUY', 'LONG', 'BULLISH', 'OPEN', 'TRENDING', 'YES', 'READY', 'LIVE', 'SAFE', 'CONTINUE'].some((token) => normalized.includes(token))) return 'positive'
  if (['SELL', 'SHORT', 'BEARISH', 'CLOSED', 'NO_TRADE', 'BLOCKED', 'STALE', 'STOP', 'HIGH_RISK', 'CRITICAL', 'AVOID_NEW_TRADES'].some((token) => normalized.includes(token))) return 'negative'
  if (['WAIT', 'MIXED', 'SIDEWAYS', 'NEUTRAL', 'CAUTION', 'REDUCE', 'PAUSE'].some((token) => normalized.includes(token))) return 'neutral'
  return 'purple'
}

function humanize(value: string | null) {
  return value ? value.replaceAll('_', ' ') : '—'
}

function clamp(value: number) {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
}

function formatNumber(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value) : 'Unavailable'
}

function formatInteger(value: number) {
  return Number.isFinite(value) ? new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value) : '—'
}

function formatPrice(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) : 'Unavailable'
}

function formatPercent(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? `${formatNumber(value)}%` : 'Unavailable'
}

function formatMoney(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? `₹${formatNumber(value)}` : 'Unavailable'
}

function formatLimitPair(value: number | null, limit: number | null) {
  return value !== null && limit !== null ? `${formatInteger(value)} / ${formatInteger(limit)}` : 'Unavailable'
}

function formatNullableInteger(value: number | null) {
  return value === null ? 'Unavailable' : formatInteger(value)
}

function formatCountdown(seconds: number) {
  if (!Number.isFinite(seconds)) return 'Unavailable'
  const absolute = Math.abs(seconds)
  const hours = Math.floor(absolute / 3600)
  const minutes = Math.floor((absolute % 3600) / 60)
  const label = hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`
  return seconds >= 0 ? `T−${label}` : `T+${label}`
}

function formatSigned(value: number) {
  return Number.isFinite(value) ? `${value > 0 ? '+' : ''}${formatNumber(value)}` : '—'
}

function formatSignedPercent(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${formatNumber(value)}%` : 'Unavailable'
}

function formatTimestamp(value: string) {
  const timestamp = new Date(value)
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'medium' })
}

function formatTimeOnly(value: string | number) {
  const timestamp = new Date(value)
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
}

type StrategyComparisonData = {
  deployment_id: string
  strategy_name: string
  timeframe: string
  argus_mode: string
  runtime_health: string
  total_native_signals: number
  native_executed_trades: number
  shadow_evaluations: number
  native_net_pnl: number
  native_win_rate: number
  native_expectancy: number
  native_profit_factor: number
  native_max_drawdown: number
  argus_hypothetical_allows: number
  argus_hypothetical_blocks: number
  argus_hypothetical_delays: number
  useful_blocks: number
  false_blocks: number
  avoided_losses: number
  missed_winners: number
  argus_unavailable_count: number
  argus_stale_count: number
  last_signal_time: string | null
  last_argus_snapshot_time: string | null
  sample_size: number
  evidence_status: 'NO_DATA' | 'INSUFFICIENT_SAMPLE' | 'COLLECTING' | 'REVIEW_READY'
  reason_code_breakdown: Array<{
    reason_code: string
    count: number
    useful_block_count: number
    false_block_count: number
    avg_native_outcome: number
  }>
  recent_signals: Array<{
    time: string
    strategy: string
    contract: string
    native_result: string
    argus_action: string
    confidence: number
    reason_codes: string[]
    journal_status: string
  }>
  equity_curve: Array<{
    timestamp: string
    native_pnl: number
    counterfactual_pnl: number
  }>
}

type StrategyComparisonPayload = {
  status: string
  paper_only: boolean
  comparison: StrategyComparisonData
  deployments: Record<string, StrategyComparisonData>
}

function EquityComparisonSvg({ points }: { points: Array<{ timestamp: string; native_pnl: number; counterfactual_pnl: number }> }) {
  if (!points || points.length < 2) {
    return <div className="chart-placeholder"><span>Requires at least 2 points to render equity curve comparison.</span></div>
  }
  const minVal = Math.min(...points.map((p) => p.native_pnl), ...points.map((p) => p.counterfactual_pnl), 0)
  const maxVal = Math.max(...points.map((p) => p.native_pnl), ...points.map((p) => p.counterfactual_pnl), 100)
  const range = maxVal - minVal || 1

  const width = 800
  const height = 140
  const padding = 16

  const getX = (idx: number) => padding + (idx / (points.length - 1)) * (width - 2 * padding)
  const getY = (val: number) => height - padding - ((val - minVal) / range) * (height - 2 * padding)

  const nativePts = points.map((p, idx) => `${getX(idx)},${getY(p.native_pnl)}`).join(' ')
  const cfPts = points.map((p, idx) => `${getX(idx)},${getY(p.counterfactual_pnl)}`).join(' ')

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="comparison-svg" preserveAspectRatio="none">
      <polyline fill="none" stroke="var(--purple-light)" strokeWidth="2" points={nativePts} />
      <polyline fill="none" stroke="var(--green)" strokeWidth="2" strokeDasharray="4 2" points={cfPts} />
    </svg>
  )
}

function StrategyComparisonPanel({ feed }: { feed: FeedState<StrategyComparisonPayload> }) {
  const [selectedId, setSelectedId] = useState<string>('TC_NIFTY_PE_1M')
  const payload = feed.data
  const deployments = payload?.deployments
  const selectedData = deployments?.[selectedId] ?? payload?.comparison

  const sampleSize = selectedData?.sample_size ?? 0
  const evidenceStatus = selectedData?.evidence_status ?? 'NO_DATA'

  return (
    <DesignCard as="section" unstyled className={`panel workspace-unified-section strategy-comparison-panel ${workspaceStyles.panel}`} aria-label="Strategy Comparison — OFF vs SHADOW">
      <SectionHeading
        eyebrow="02B / TRADING WORKSPACE"
        title="Strategy Comparison — OFF vs SHADOW"
        error={feed.error}
        status={feed.error ? 'stale' : feed.loading ? 'connecting' : 'live'}
        aside={`Sample: ${sampleSize} · ${evidenceStatus.replaceAll('_', ' ')}`}
      />

      <div className="comparison-selector-tabs" role="tablist">
        {[
          { id: 'TC_NIFTY_PE_1M', label: 'Trend Catcher 1M', mode: 'SHADOW' },
          { id: 'TC_NIFTY_PE_3M', label: 'Trend Catcher 3M', mode: 'OFF' },
          { id: 'BP_NIFTY_CE_1M', label: 'Bull Pulse 1M', mode: 'SHADOW' },
          { id: 'BP_NIFTY_CE_3M', label: 'Bull Pulse 3M', mode: 'OFF' },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selectedId === tab.id}
            className={`tab-btn ${selectedId === tab.id ? 'active' : ''}`}
            onClick={() => setSelectedId(tab.id)}
          >
            <span>{tab.label}</span>
            <Badge value={tab.mode} prominent={selectedId === tab.id} />
          </button>
        ))}
      </div>

      <div className="comparison-columns">
        <div className="comparison-column-card native-card">
          <header className="card-header">
            <div>
              <span className="card-kicker">NATIVE ENGINE</span>
              <h3>Native Execution</h3>
            </div>
            <Badge value="AUTHORITATIVE" />
          </header>
          <div className="comparison-compact-grid">
            <div className="metric-cell"><span className="label">Trades</span><strong className="value">{selectedData?.native_executed_trades ?? 0}</strong></div>
            <div className="metric-cell"><span className="label">Win Rate</span><strong className="value">{formatPercent(selectedData?.native_win_rate)}</strong></div>
            <div className="metric-cell"><span className="label">Net P&amp;L</span><strong className={`value ${metricTone(selectedData?.native_net_pnl)}`}>{formatMoney(selectedData?.native_net_pnl ?? 0)}</strong></div>
            <div className="metric-cell"><span className="label">Expectancy</span><strong className="value">{formatNumber(selectedData?.native_expectancy)}</strong></div>
            <div className="metric-cell"><span className="label">Profit Factor</span><strong className="value">{formatNumber(selectedData?.native_profit_factor)}</strong></div>
            <div className="metric-cell"><span className="label">Max Drawdown</span><strong className="value negative">{formatMoney(selectedData?.native_max_drawdown ?? 0)}</strong></div>
          </div>
        </div>

        <div className="comparison-column-card shadow-card">
          <header className="card-header">
            <div>
              <span className="card-kicker">ARGUS SHADOW EVALUATION</span>
              <h3>Counterfactual Intelligence</h3>
            </div>
            <Badge value={selectedData?.argus_mode ?? 'SHADOW'} prominent />
          </header>
          <div className="comparison-compact-grid">
            <div className="metric-cell"><span className="label">Allows</span><strong className="value positive">{selectedData?.argus_hypothetical_allows ?? 0}</strong></div>
            <div className="metric-cell"><span className="label">Blocks</span><strong className="value negative">{selectedData?.argus_hypothetical_blocks ?? 0}</strong></div>
            <div className="metric-cell"><span className="label">Delays</span><strong className="value warn">{selectedData?.argus_hypothetical_delays ?? 0}</strong></div>
            <div className="metric-cell"><span className="label">Useful Blocks</span><strong className="value positive">{selectedData?.useful_blocks ?? 0}</strong></div>
            <div className="metric-cell"><span className="label">False Blocks</span><strong className="value negative">{selectedData?.false_blocks ?? 0}</strong></div>
            <div className="metric-cell"><span className="label">Avoided Losses</span><strong className="value positive">{formatMoney(selectedData?.avoided_losses ?? 0)}</strong></div>
          </div>
        </div>
      </div>

      {(!selectedData || sampleSize === 0) && (
        <div className="comparison-status-banner">
          <Activity size={14} />
          <span>Awaiting evaluation data for deployment <strong>{selectedId}</strong> ({evidenceStatus}). Native execution active.</span>
          <Badge value={evidenceStatus} />
        </div>
      )}

      <div className="comparison-compact-chart">
        <header className="chart-header">
          <h4>Realized vs Counterfactual Equity Curve</h4>
          <div className="chart-legend">
            <span className="legend-item native"><i /> Native P&amp;L</span>
            <span className="legend-item counterfactual"><i /> Counterfactual P&amp;L</span>
          </div>
        </header>
        <div className="comparison-chart-wrapper">
          {!selectedData || !selectedData.equity_curve || selectedData.equity_curve.length === 0 ? (
            <span className="comparison-chart-placeholder">Waiting for completed trades</span>
          ) : (
            <EquityComparisonSvg points={selectedData.equity_curve} />
          )}
        </div>
      </div>

      {selectedData && selectedData.reason_code_breakdown.length > 0 && (
        <div className="comparison-table-block">
          <header className="block-header">
            <h4>ARGUS Reason-Code Breakdown</h4>
          </header>
          <table className="comparison-table">
            <thead>
              <tr>
                <th>Reason Code</th>
                <th>Evaluations</th>
                <th>Useful Blocks</th>
                <th>False Blocks</th>
                <th>Avg Native Outcome</th>
              </tr>
            </thead>
            <tbody>
              {selectedData.reason_code_breakdown.map((row) => (
                <tr key={row.reason_code}>
                  <td><code>{row.reason_code}</code></td>
                  <td>{row.count}</td>
                  <td className="positive">{row.useful_block_count}</td>
                  <td className="negative">{row.false_block_count}</td>
                  <td className={metricTone(row.avg_native_outcome)}>{formatMoney(row.avg_native_outcome)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedData && selectedData.recent_signals.length > 0 && (
        <div className="comparison-table-block">
          <header className="block-header">
            <h4>Recent Signals &amp; Shadow Journal</h4>
          </header>
          <table className="comparison-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Strategy</th>
                <th>Contract</th>
                <th>Native Result</th>
                <th>ARGUS Action</th>
                <th>Confidence</th>
                <th>Reason Codes</th>
                <th>Journal Status</th>
              </tr>
            </thead>
            <tbody>
              {selectedData.recent_signals.map((sig, idx) => (
                <tr key={idx}>
                  <td>{formatTimeOnly(sig.time)}</td>
                  <td>{sig.strategy}</td>
                  <td><code>{sig.contract}</code></td>
                  <td>{sig.native_result}</td>
                  <td><Badge value={sig.argus_action} prominent={sig.argus_action === 'ALLOW'} /></td>
                  <td>{formatPercent(sig.confidence)}</td>
                  <td><small>{sig.reason_codes.join(', ') || 'NONE'}</small></td>
                  <td><Badge value={sig.journal_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </DesignCard>
  )
}
