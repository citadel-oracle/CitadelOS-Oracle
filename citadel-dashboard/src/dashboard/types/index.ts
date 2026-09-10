export const DASHBOARD_FEED_KEYS = [
  'mission', 'matrix', 'trade', 'performance', 'kronos', 'kronos_alpha',
  'chronos2', 'oracle', 'athena', 'hermes', 'insights', 'argus',
  'risk_status', 'kill_switch', 'paper_status', 'personal_oracle', 'aegis',
  'readiness', 'next_session_plan', 'order_ledger', 'paper_trading',
  'development', 'strategy_lab', 'comparison',
  'strategies', 'eye_oracle_projection', 'order_flow', 'futures_chart',
  'fusion_shadow', 'options_structure', 'vob_reversal',
] as const


export type DashboardFeedKey = (typeof DASHBOARD_FEED_KEYS)[number]
export type DashboardProviderKind = 'mock' | 'rest' | 'websocket' | 'replay' | 'historical'
export type DashboardHealth = 'healthy' | 'degraded' | 'offline' | 'unknown'
export type ConnectionState = 'connected' | 'delayed' | 'stale' | 'offline'
export type RuntimeState = 'running' | 'waiting' | 'stopped' | 'error'
export type MarketSessionState = 'pre_open' | 'open' | 'closed' | 'weekend' | 'holiday'
export type PositionSide = 'BUY' | 'SELL'
export type NotificationSeverity = 'info' | 'success' | 'warning' | 'critical'

export interface DashboardFeedState<T = unknown> {
  data: T | null
  error: string | null
  lastUpdated: Date | null
  loading: boolean
}

export interface OracleAssessmentData {
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
  live_workspace?: OracleLiveWorkspaceProjection
}

export interface OracleLiveWorkspaceProjection {
  event_id: string
  content_hash: string
  generated_timestamp: string
  source_timestamp?: string
  sync_state: 'DETECTING' | 'LOADING_CONTEXT' | 'BUY' | 'WAIT' | 'NO_TRADE' | 'WATCHING' | 'REVALIDATING' | 'PAPER_ORDER' | 'MANAGE' | 'EXIT' | 'EXITED' | 'UNAVAILABLE' | 'AMBIGUOUS'
  chart_state: null | {
    content_hash: string
    source_timestamp: string
    change_reason: string
    timeframe: string
    availability: string
    freshness: string
    symbol: { raw_symbol: string; normalized_symbol: string; exchange: string | null; route: string; ambiguity_status: string }
    instrument: { route: string; underlying: string; security_id: string | null; analysis_supported: boolean; mapping_status: string }
    option: null | { underlying: string; expiry: string; strike: number; option_side: 'CE' | 'PE'; trading_symbol: string; security_id: string | null }
    layout: { layout_identity: string; active_pane_index: number | null; chart_count: number }
  }
  decision: {
    decision_id: string | null
    content_hash: string | null
    decision_timestamp?: string | null
    source_hashes?: Record<string, string>
    candle_timestamp?: string | null
    completed_candle?: boolean
    market_state?: string | null
    setup_family?: string | null
    market_thesis?: {
      direction?: string | null
      location_quality?: string | null
      permitted_thesis_types?: string[]
      setup_quality?: number | null
    } | null
    structural_stop?: {
      invalidation_id?: string | null
      level?: number | null
      mapping_status?: string | null
      type?: string | null
    } | null
    natural_targets?: Array<{
      authority?: string | null
      level?: number | null
      target_id?: string | null
      type?: string | null
    }>
    provider_lineage?: Record<string, unknown>
    evidence?: {
      supporting?: string[]
      conflicting?: string[]
      missing?: string[]
    }
    knowledge_card_ids?: string[]
    action: string
    exact_contract: string | null
    displayed_option?: string | null
    current_contract_accepted?: boolean
    current_contract_rejected?: boolean
    current_contract_reason?: string
    better_option_found?: boolean
    exact_option?: null | {
      status: string
      verdict: 'KEEP_CURRENT_CONTRACT' | 'REJECT_CURRENT_CONTRACT' | 'INSUFFICIENT_EVIDENCE'
      current_contract_analyzed_first: boolean
      exact_contract: { trading_symbol?: string | null; security_id?: string | null; expiry?: string; strike?: number; option_side?: string; underlying?: string }
      premium_candles?: { status?: string; source?: string; completed_1m_count?: number; completed_3m_count?: number; completed_5m_count?: number; evaluated_through?: string }
      premium_features?: { authority?: string; status?: string; trend?: Record<string, unknown>; structure?: Record<string, unknown>; atr?: number | null; volume?: number | null; vwap_status?: string }
      premium_trigger?: { predicate?: string; level?: number | null }
      premium_invalidation?: { predicate?: string; level?: number | null }
      executable_entry_band?: number[] | null
      spread_quality?: string
      greeks_iv_condition?: string
      confirmations?: Record<string, unknown>
      current_contract_suitability?: string
      material_rejection_reasons?: string[]
      alternative_contract?: Record<string, unknown> | null
      missing_evidence?: string[]
      freshness?: string
    }
    setup_quality: number | null
    visual_certainty: string
    data_completeness: number
    execution_quality: number
    evidence_agreement: number
    calibration_status: string
    historical_probability: number | null
    trigger: string
    entry_band: number[] | null
    structural_invalidation: string | null
    premium_stop: number | null
    targets: number[]
    costs: number | null
    resulting_rr: number[]
    why: string
    why_proof?: unknown
    risk_conflict: string
    freshness: string
    missing_evidence: string[]
    reason_codes?: string[]
    execution_authority: false
  }
  knowledge: { references?: unknown[]; conflicts?: unknown[]; status?: string }
  personal_oracle: {
    available?: boolean
    cooldown_status?: string | null
    obsidian_sync_status?: string | null
    second_brain?: {
      status?: string
      constitution?: { version?: string; immutable?: boolean; content_hash?: string; principles?: Array<{ principle_id: string; kind: string; text: string }> }
      discipline?: { recommendation?: 'WAIT' | 'REVIEW' | 'COOLDOWN' | 'NO_TRADE'; warnings?: Array<{ code: string; recommendation: string; objective_evidence: string[]; constitution_refs: string[] }>; emotion_only_blocking?: false; execution_authority?: false }
      explainability?: { why?: string[]; why_not?: string[]; missing_evidence?: string[]; conflicting_evidence?: unknown[]; alternative_scenarios?: string[]; invalidation?: unknown; natural_targets?: unknown[]; discipline_warnings?: unknown[]; related_journal_links?: string[]; related_historical_trades?: string[]; knowledge_cards_used?: unknown[]; constitution_refs?: string[]; confidence_boundary?: string }
      memory?: { append_only?: boolean; event_count?: number; latest_references?: string[] }
      obsidian?: { status?: string; last_sync_event_id?: string; policy_version?: string }
      latency_ms?: number
      safety?: { execution_influence?: 'ZERO'; execution_authority?: false }
    }
  }
  phase5: {
    condition_id?: string | null
    condition_state?: string | null
    trigger_id?: string | null
    paper_order_state?: string | null
    position_id?: string | null
    protection?: unknown
    guardian_action?: string | null
    guardian_health?: unknown
    order?: unknown
    latest_event_hash?: string | null
    latest_explanation?: string | null
  }
  health: {
    last_error?: string | null; state_age_seconds?: number | null; worker_alive?: boolean; backoff_active?: boolean
    push_transport?: string
    telemetry?: Record<string, { latest_ms: number | null; mean_ms: number | null; p50_ms: number | null; p95_ms: number | null; maximum_ms: number | null; sample_count: number; error_count: number }>
  }
  frontend_transport?: { transport: 'SSE' | 'POLLING_FALLBACK'; event_id?: string; event_type?: string; delivery_mode?: 'INITIAL_STATE' | 'REPLAY' | 'LIVE'; received_at_epoch_ms: number; event_receipt_ms: number | null }
  alert_event?: null | {
    event_id: string
    event_type: string
    severity: 'INFO' | 'CRITICAL'
    message: string
    deduplication_key: string
    cooldown_seconds: number
    generated_at: string
  }
  safety: { paper_only: true; live_trading_enabled: false; broker_submission: false; advisory_only: true; execution_influence: 'ZERO'; execution_authority: false }
}

export interface DashboardFeedMeta {
  health: string
  readiness: string
  latency_ms: number
  last_updated: string | null
  source_last_updated: string | null
  symbol?: string | null
  timeframe?: string | null
  candle_id?: string | null
  latest_completed_candle_at?: string | null
  source_timestamp?: string | null
  calculation_timestamp?: string | null
  calculation_age_seconds?: number | null
  input_candle_count?: number | null
  freshness_age_seconds?: number | null
  freshness?: 'FRESH' | 'STALE' | 'UNAVAILABLE' | string | null
  market_input_state?: 'READY' | 'WAITING_FOR_NEXT_CANDLE' | 'STALE' | null
  freshness_threshold_seconds?: number | null
  runtime_state?: string | null
  stale_reason?: string | null
  real_candles?: boolean | null
  advisory_only?: boolean
  execution_influence?: number | null
  // Canonical status is validated by the backend and narrowed by SafetyStrip.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  canonical_status?: any
}

export interface ForecastProjectionMeta {
  traceId: string
  publishedAt: string
  observedAt: string
  sourceLastUpdated: string | null
}

export interface DashboardSourceSnapshot {
  schemaVersion: 1
  provider: DashboardProviderKind
  traceId: string
  generatedAt: string
  selectedSymbol: string
  feeds: Record<DashboardFeedKey, unknown>
  feedMeta: Record<DashboardFeedKey, DashboardFeedMeta>
}
