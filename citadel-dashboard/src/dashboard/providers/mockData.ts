import { DASHBOARD_FEED_KEYS, type DashboardFeedKey } from '../types'

const deploymentSeed = [
  ['PB_NIFTY_CE_1M', -175.5, 3], ['PB_NIFTY_CE_3M', 643.5, 2],
  ['PB_NIFTY_PE_1M', -533, 3], ['PB_NIFTY_PE_3M', -263.25, 2],
  ['BO_NIFTY_CE_1M', -3991, 2], ['BO_NIFTY_CE_3M', -419.25, 2],
  ['BO_NIFTY_PE_1M', 4173, 3], ['BO_NIFTY_PE_3M', 0, 0],
  ['PULLBACK_MASTER', 0, 0], ['BREAKOUT_MAIN', 0, 0],
] as const

const makePosition = (now: string) => ({
  position_id: 'paper-position-bo-ce-1m', strategy_id: 'BO_NIFTY_CE_1M', trade_id: 'BO-CE-1M-20260715-0922',
  contract: 'NIFTY JUL 25100 CE', instrument: 'NIFTY JUL 25100 CE', underlying: 'NIFTY', option_type: 'CE', strike: 25100,
  expiry: '2026-07-30', side: 'BUY', entry: 193.2, entry_price: 193.2, average_price: 193.2,
  current_price: 131.8, pnl: -3991, unrealized_pnl: -3991, rr: -9.16, stop: 186.5, target: 278.26,
  quantity: 65, status: 'OPEN', duration_seconds: 22020, entry_time: '2026-07-15T09:22:00+05:30', exit_time: null,
  reason: 'Breakout confirmed', option_contract: { security_id: '52349', option_type: 'CE', strike: 25100, expiry: '2026-07-30' },
  updated_at: now,
})

const makeDeployment = (seed: typeof deploymentSeed[number], now: string) => {
  const [strategyId, pnl, trades] = seed
  const [, , parsedOptionType, parsedTimeframe] = strategyId.split('_')
  const optionType = parsedOptionType ?? 'NIFTY'
  const timeframe = parsedTimeframe ?? '3M'
  const open = strategyId === 'BO_NIFTY_CE_1M'
  return {
    strategy_id: strategyId,
    metadata: {
      name: strategyId.startsWith('PB_') ? 'Pullback Master' : 'Breakout Main', version: '1.0.0', author: 'CITADEL',
      input_type: 'COMPLETED_CANDLE', supported_markets: ['NIFTY'], supported_timeframes: [timeframe.toLowerCase()],
      rr: 2, risk_model: 'SHARED_CORE', status: 'ACTIVE',
    },
    state: 'RUNNING', health: 'HEALTHY', readiness: 'READY', reason: 'Completed-candle runtime active', latency_ms: 32,
    last_updated: now, scheduler: { state: 'RUNNING', tick_count: 126, skipped_count: 0, last_tick_at: now },
    risk: { authorization: 'PAPER_ONLY', last_decision: 'ALLOW', risk_model: 'SHARED_CORE' },
    current_position: open ? makePosition(now) : null,
    current_decision: { signal: open ? 'BUY' : 'WAIT', reason: open ? 'Breakout confirmed' : 'Awaiting qualified setup', evaluated_at: now, confidence: open ? 78 : 0, option_contract: { option_type: optionType }, underlying_price: 25072.35, position_state: open ? { entry: 193.2, stop: 186.5, target: 278.26 } : undefined },
    today_trades: trades,
    statistics: { completed_trades: trades, wins: pnl > 0 ? trades : 0, losses: pnl < 0 ? trades : 0, win_rate: trades ? (pnl > 0 ? 100 : 0) : null, profit_factor: null, expectancy: null, rr: null, mfe: null, mae: null, net_pnl: pnl, drawdown: Math.min(0, pnl), sharpe: null, ranking_eligible: false, basis: 'COMPLETED_PAPER_TRADES_ONLY' },
    paper_only: true, live_trading_enabled: false, broker_submission: false,
  }
}

const makeClosedTrade = (id: string, strategy: string, entry: number, exit: number, pnl: number, entryTime: string, exitTime: string, reason: string) => ({
  position_id: id, trade_id: id, strategy_id: strategy, contract: `NIFTY JUL ${strategy.includes('PE') ? '25000 PE' : '25100 CE'}`,
  option_type: strategy.includes('PE') ? 'PE' : 'CE', strike: strategy.includes('PE') ? 25000 : 25100, expiry: '2026-07-30',
  side: 'BUY', entry, entry_price: entry, average_price: entry, exit, current_price: exit, quantity: 65,
  realized_pnl: pnl, pnl, stop: entry - 3, target: entry + 30, status: 'CLOSED', entry_time: entryTime, exit_time: exitTime,
  exit_reason: reason, reason: strategy.startsWith('PB_') ? 'Pullback confirmed' : 'Breakout confirmed',
})

export function createMockFeeds(now: string, symbol: string, markOffset = 0): Record<DashboardFeedKey, unknown> {
  const openPosition = { ...makePosition(now), current_price: 131.8 + markOffset, pnl: -3991 + markOffset * 65, unrealized_pnl: -3991 + markOffset * 65 }
  const strategies = deploymentSeed.map((seed) => {
    const deployment = makeDeployment(seed, now)
    return deployment.strategy_id === 'BO_NIFTY_CE_1M' ? { ...deployment, current_position: openPosition } : deployment
  })
  const closed = [
    makeClosedTrade('trade-8', 'BO_NIFTY_PE_1M', 171.25, 238.65, 4381, '2026-07-15T15:02:00+05:30', '2026-07-15T15:16:02+05:30', 'SQUARE_OFF'),
    makeClosedTrade('trade-7', 'PB_NIFTY_CE_1M', 89.6, 89.35, -16.25, '2026-07-15T15:02:00+05:30', '2026-07-15T15:03:28+05:30', 'STOP_LOSS'),
    makeClosedTrade('trade-6', 'PB_NIFTY_CE_1M', 93.8, 94.9, 71.5, '2026-07-15T14:54:04+05:30', '2026-07-15T14:55:00+05:30', 'TRAILING_STOP'),
  ]
  const orders = closed.flatMap((trade, index) => ([
    { order_id: `order-${index}-entry`, strategy_id: trade.strategy_id, status: 'FILLED', contract: trade.contract, side: 'BUY', quantity: 65, filled_quantity: 65, created_at: trade.entry_time, updated_at: trade.entry_time },
    { order_id: `order-${index}-exit`, strategy_id: trade.strategy_id, status: 'FILLED', contract: trade.contract, side: 'SELL', quantity: 65, filled_quantity: 65, created_at: trade.exit_time, updated_at: trade.exit_time },
  ]))
  const fills = orders.map((order, index) => ({ fill_id: `fill-${index}`, order_id: order.order_id, strategy_id: order.strategy_id, time: order.updated_at, price: index % 2 ? closed[Math.floor(index / 2)].exit : closed[Math.floor(index / 2)].entry, quantity: 65, fees: 0 }))
  const timeline = closed.flatMap((trade) => ([
    { record_id: `${trade.trade_id}-exit`, strategy_id: trade.strategy_id, event_type: trade.exit_reason, entity_id: trade.trade_id, recorded_at: trade.exit_time, payload: { realized_pnl: trade.realized_pnl, status: 'CLOSED' } },
    { record_id: `${trade.trade_id}-fill`, strategy_id: trade.strategy_id, event_type: 'ORDER_FILLED', entity_id: trade.trade_id, recorded_at: trade.entry_time, payload: { status: 'FILLED' } },
  ]))
  const journal = closed.flatMap((trade) => ([
    { record_id: `${trade.trade_id}-journal-exit`, strategy_id: trade.strategy_id, event_type: 'POSITION_CLOSED', recorded_at: trade.exit_time, payload: { signal: 'SELL', entry: trade.entry, exit: trade.exit, target: trade.target, stop: trade.stop, reason: trade.exit_reason, realized_pnl: trade.realized_pnl } },
    { record_id: `${trade.trade_id}-journal-entry`, strategy_id: trade.strategy_id, event_type: 'POSITION_OPENED', recorded_at: trade.entry_time, payload: { signal: 'BUY', entry: trade.entry, target: trade.target, stop: trade.stop, reason: trade.reason } },
  ]))
  const strategyLab = {
    generated_at: now,
    status: { status: 'PAPER_ACTIVE', health: 'HEALTHY', readiness: 'READY', manager_started: true, deployment_count: 10, loaded_runtime_count: 10, running_strategy_count: 10, paper_only: true, live_trading_enabled: false, broker_submission: false },
    strategies,
    leaderboard: { basis: 'COMPLETED_PAPER_TRADES_ONLY', entries: [], eligible_strategy_count: 0 },
    summary: { deployed_strategies: 10, running_strategies: 10, completed_paper_trades: 17, ranking_eligible_strategies: 0 },
    deployment: { status: 'ACTIVE', adapters: [{ input_type: 'COMPLETED_CANDLE', deployment_interface: 'NATIVE_RUNTIME', compiler_or_parser: 'NONE' }], pine_parser_implemented: false, paper_only: true },
    tournament: { architecture_status: 'ISOLATED', same_candle_fanout: true, same_market_context: true, independent_paper_state: true, independent_execution: true },
    safety_labels: ['PAPER ONLY', 'LIVE TRADING DISABLED'], empty_state: null,
    portfolio: { status: 'READY', generated_at: now, total_equity: 96700.5, current_capital: 100000, initial_capital: 100000, available_capital: 87442, used_capital: 12558, today_pnl: -3308.5, open_pnl: openPosition.pnl, closed_pnl: 682.5, total_pnl: -3308.5, open_trades: 1, closed_trades: 8, win_rate: 62.5, profit_factor: 1.42, expectancy: 0.31, portfolio_drawdown: 3.3, exposure: 12558, risk_usage: 12.56, strategy_accounts: 10, paper_only: true, live_trading_enabled: false, broker_submission: false },
    execution: { status: 'READY', positions: [openPosition], orders, fills, closed_trades: closed, timeline, order_counts: { FILLED: orders.length, REJECTED: 2, CANCELLED: 0 }, position_count: 1, order_count: 37, fill_count: 35, closed_trade_count: 8, paper_only: true, live_trading_enabled: false, broker_submission: false },
    review: { status: 'READY', journal, replay: journal, evidence: journal, validation: strategies.map((strategy) => ({ strategy_id: strategy.strategy_id, status: 'VALID', valid: true })), paper_only: true },
  }
  const session = { market_open: true, entry_allowed: true, square_off: false, state: 'OPEN', reason: 'Regular market session', next_valid_open: null, calendar_version: '2026.1' }
  const mission = { system: { system: 'ONLINE', phase: 'PAPER_ACTIVE', strategy: 'Simple Pullback', mode: 'paper', broker: 'disabled', live_trading_enabled: false, session }, journal: { total_closed: 8, wins: 5, losses: 3, net_points: 50.9 }, active_trade: null, analytics: { total_trades: 8, wins: 5, losses: 3, win_rate: 62.5, net_points: 50.9, profit_factor: 1.42, expectancy: 6.36, max_win_streak: 3, max_loss_streak: 2, verdict: 'POSITIVE', comment: 'Paper execution operating within reviewed controls.' }, optimizer: [] }
  const outlook = (side: 'CE' | 'PE', quality: number) => ({ side, option_buying_quality_score: quality, recommendation_state: 'MODERATE_ALIGNMENT', directional_probability: side === 'CE' ? 68 : 22, persistence_probability: 71, reversal_risk: 24, sideways_probability: 10, opposite_probability: side === 'CE' ? 22 : 68, forecast_volatility: 42, uncertainty: 28, expected_favorable_move: side === 'CE' ? 0.64 : 0.21, label: 'OPTION_BUYING_QUALITY' })
  const kronosAlpha = {
    generated_at: now, model_status: 'READY', mode: 'SHADOW', execution_influence_percentage: 0, aegis_influence_percentage: 0,
    model_name: 'KRONOS ALPHA', model_variant: 'FOUNDATION_FORECAST', model_revision: 'v1.0', tokenizer_name: 'CITADEL_MARKET_TOKENIZER', tokenizer_revision: 'v1', device: 'CPU',
    symbol, timeframe: '3m', input_candle_count: 512, context_limit: 512, forecast_horizon: 10, last_input_candle_at: now, input_age_seconds: 0,
    last_inference_at: now, inference_duration_ms: 38.4, cache_status: 'FRESH', readiness_state: 'READY', expected_direction: 'BULLISH',
    bullish_probability: 68, bearish_probability: 22, sideways_probability: 10, expected_return_percentage: 0.64, forecast_volatility: 42,
    volatility_label: 'NORMAL', trend_persistence_probability: 71, reversal_probability: 24, forecast_uncertainty: 28, uncertainty_label: 'LOW',
    forecast_dispersion: 0.31, expected_high: 25232.4, expected_low: 24984.2, upside_quantile: 0.91, downside_quantile: -0.35,
    horizon_candles: 10, horizon_minutes: 30, path_count: 500, reason_codes: ['TREND_PERSISTENCE', 'STRUCTURE_ALIGNED', 'LIQUIDITY_HEALTHY'],
    warnings: [], missing_inputs: [], maturity_label: 'EXPERIMENTAL_SHADOW',
    source_metadata: { source: 'MOCK_PROVIDER', fixture_data: true, external_refresh_on_read: false }, scheduler_health: 'HEALTHY', next_expected_inference: now,
    session: { exchange: 'NSE', session_state: 'OPEN', market_open: true, session_date: now.slice(0, 10), reason: 'Regular market session', next_valid_open: null, calendar_source: 'NSE', calendar_version: '2026.1' },
    input_metadata: { health: 'HEALTHY', candle_count: 512, last_candle_at: now, source: 'COMPLETED_CANDLE_CACHE', volume_available: true, instrument: { symbol, exchange: 'NSE', segment: 'INDEX', security_id: '13', instrument: 'NIFTY 50', timeframe: '3m' } },
    outlooks: { ce: outlook('CE', 74), pe: outlook('PE', 31), forecast_quality_score: 82 },
    evaluation: { evaluated_forecasts: 148, directional_hit_rate: 67.6, average_forecast_error: 0.28, calibration_status: 'CALIBRATED', sample_warning: null },
  }
  const quality = (side: 'CE' | 'PE', score: number) => ({ score, interpretation: side === 'CE' ? 'FAVORABLE' : 'WEAK', evidence_coverage: 100, freshness: 'FRESH', missing_components: [], label: `${side}_QUALITY`, shadow: true, recommendation: null })
  const chronos2 = {
    generated_at: now, status: 'READY', freshness: 'FRESH', model_name: 'CHRONOS-2', model_revision: 'v2.0', package_version: '1.0.0', mode: 'MULTIVARIATE',
    symbol, timeframe: '3m', shadow_mode: true, advisory_only: true, execution_influence: 0, aegis_direct_influence: 0,
    prediction_length: 10, input_candle_count: 512, input_feature_count: 8, input_feature_names: ['open', 'high', 'low', 'close', 'volume', 'vwap', 'atr', 'rsi'],
    input_coverage: 100, forecast_id: `chronos-${now}`, context_end: now, median_terminal_move_points: 118.4, median_terminal_move_percentage: 0.47,
    forecast_low: 24942.1, forecast_high: 25261.8, terminal_p10: 24982.4, terminal_p50: 25190.75, terminal_p90: 25244.2,
    device: 'CPU', inference_duration_ms: 44.8, warnings: [], next_eligible_session: now, model_readiness: 'READY', input_readiness: 'READY',
    runtime: { scheduler_health: 'HEALTHY', next_expected_inference: now, session: { session_state: 'OPEN', market_open: true, reason: 'Regular market session', next_valid_open: null }, input_metadata: { health: 'HEALTHY', candle_count: 512, last_candle_at: now, source: 'COMPLETED_CANDLE_CACHE' } },
    derived_analytics: { label: 'BULLISH_EXPANSION', directional_bias: 'BULLISH', directional_confidence: 76, median_expected_move_points: 118.4, median_expected_move_percentage: 0.47, uncertainty: 'LOW', trend_persistence: 73, upward_persistence: 76, downward_persistence: 24, reversal_risk: 21, forecast_quality: 84, ce_quality: quality('CE', 78), pe_quality: quality('PE', 34) },
  }
  const readiness = {
    status: 'READY', generated_at: now,
    items: [
      { component: 'MARKET_DATA', status: 'READY', reason: 'Completed candles current', required_condition: 'Fresh completed candle', last_checked: now, blocking: false, warning: null },
      { component: 'STRATEGY_RUNTIME', status: 'READY', reason: 'All runtimes registered', required_condition: 'Runtime healthy', last_checked: now, blocking: false, warning: null },
      { component: 'RISK_ENGINE', status: 'READY', reason: 'Paper risk controls healthy', required_condition: 'Risk authorization available', last_checked: now, blocking: false, warning: null },
    ],
    blocking_components: [], advisory_only: true, provider_refresh_triggered: false, model_inference_triggered: false, broker_call_triggered: false,
  }
  const nextSessionPlan = {
    status: 'READY', expected_open: `${now.slice(0, 10)}T09:15:00+05:30`, first_candle_close: `${now.slice(0, 10)}T09:18:00+05:30`, grace_complete: `${now.slice(0, 10)}T09:18:05+05:30`,
    minimum_candle_count: 1, grace_seconds: 5,
    steps: [
      { sequence: 1, action: 'Confirm session open', expected_at: `${now.slice(0, 10)}T09:15:00+05:30`, observed: true },
      { sequence: 2, action: 'Receive first completed candle', expected_at: `${now.slice(0, 10)}T09:18:00+05:30`, observed: true },
      { sequence: 3, action: 'Evaluate paper runtimes', expected_at: `${now.slice(0, 10)}T09:18:05+05:30`, observed: true },
    ], warnings: [],
  }
  const aegis = {
    decision_id: `aegis-${now}`, generated_at: now, symbol, timeframe: '3m', strategy_id: 'PULLBACK_MASTER', strategy_name: 'Pullback Master', requested_side: 'CE',
    decision: 'WAIT', decision_score: 74, decision_quality: 'HIGH', data_coverage_percentage: 100, hard_gate_status: 'CLEAR', hard_gate_reasons: [], hard_gate_details: {},
    component_scores: { market_structure: 82, liquidity: 76, momentum: 69, volatility: 72, risk: 88 },
    weighted_contributions: { market_structure: 24.6, liquidity: 15.2, momentum: 13.8, volatility: 7.2, risk: 13.2 },
    component_details: { market_structure: { status: 'ALIGNED', freshness: 'FRESH', top_reason: 'Higher-high structure remains intact' }, liquidity: { status: 'HEALTHY', freshness: 'FRESH', top_reason: 'Liquidity available around execution levels' }, risk: { status: 'SAFE', freshness: 'FRESH', top_reason: 'Paper limits have sufficient headroom' } },
    conflicts: [], recommended_size_multiplier: 0.75, dominant_reasons: ['STRUCTURE_ALIGNED', 'RISK_SAFE', 'AWAIT_ENTRY_CONFIRMATION'], warnings: [], missing_inputs: [],
    maturity: 'DETERMINISTIC_ADVISORY', advisory_only: true, execution_permission: false, risk_authorization_required: true, live_trading_enabled: false,
  }
  const feeds: Partial<Record<DashboardFeedKey, unknown>> = {
    mission, strategy_lab: strategyLab,
    matrix: [{ symbol, ltp: 25072.35, change_percent: 0.42, direction: 'UP', regime: 'TRENDING', bias: 'BULLISH', confidence: 78, strategy: 'PULLBACK', structure: 'HH-HL', liquidity: 'HEALTHY', pullback_signal: 'WAIT' }],
    trade: null,
    performance: mission.analytics,
    kronos: { score: 78, label: 'BULLISH', regime: 'TRENDING', confidence: 78, trend: 82, momentum: 74, structure: 79, liquidity: 76 },
    kronos_alpha: kronosAlpha,
    chronos2,
    oracle: { symbol, timeframe: '3m', generated_at: now, market_data_as_of: now, data_age_seconds: 0, data_status: 'LIVE', oracle_status: 'READY', directional_bias: 'BULLISH', signal: 'WAIT', confidence: 72, confidence_label: 'MODERATE', confidence_formula: 'WEIGHTED_EVIDENCE', regime: 'TRENDING', reason_codes: ['STRUCTURE_ALIGNED'], reasoning: 'Structure is constructive; execution waits for a qualified setup.', input_features: { close: 25072.35, ema_21: 25040, ema_38: 25012, vwap: 25031, rsi_14: 58, adx_14: 26, atr_14: 42, price_trend: 'UP', vwap_relationship: 'ABOVE', momentum: 'POSITIVE', volatility: 'NORMAL', volume_status: 'CONFIRMED', liquidity: 'HEALTHY', timeframe_bias: 'BULLISH', scanner_bias: 'BULLISH', scanner_signal: 'WAIT', session_status: 'OPEN' }, warnings: [], maturity_label: 'DETERMINISTIC', source_metadata: { source: 'MOCK_PROVIDER', fallback_used: false, fallback_type: 'NONE', snapshot_age_seconds: 0, timestamp_semantics: 'PROVIDER_EMISSION', oracle_broker_calls: false } },
    insights: [],
    risk_status: { status: 'healthy', state_health: 'HEALTHY', kill_switch_active: false, kill_switch_reason: null, limits: { max_daily_loss: 5000, max_open_positions: 10, max_trades_per_day: 20 }, latest_authorization: { decision: 'ALLOW' } },
    kill_switch: { state: 'INACTIVE', reason: 'Safeguards nominal', persistence_health: 'HEALTHY' },
    paper_status: { status: 'healthy', total_daily_pnl: -3308.5, trades_taken_today: 17 },
    order_ledger: { status: 'READY', health: 'HEALTHY', schema_version: 1, mode: 'AUDIT_ONLY', order_count: 37, active_order_count: 0, terminal_order_count: 37, fill_count: 35, execution_engine: 'NOT_ACTIVE', broker_submission: 'DISABLED', live_trading_enabled: false, paper_state_mutation: false, empty: false, warnings: [] },
    aegis,
    readiness,
    next_session_plan: nextSessionPlan,
    argus: {
      data: {
        tactical_edge: {
          pressure: {
            call_score: 42.8,
            put_score: 54.5,
            delta: -11.6,
            acceleration: 0,
            seven_strike_breadth: { confirming_strikes: 4, sample_size: 7 },
            strikes: [
              { strike: 23700, CE: { activity: 'CALL_WRITING' }, PE: { activity: 'PUT_SHORT_COVERING' } },
              { strike: 23750, CE: { activity: 'CALL_WRITING' }, PE: { activity: 'PUT_BUYING' } },
              { strike: 23800, CE: { activity: 'CALL_WRITING' }, PE: { activity: 'PUT_BUYING' } },
              { strike: 23850, CE: { activity: 'CALL_WRITING' }, PE: { activity: 'PUT_BUYING' } },
              { strike: 23900, CE: { activity: 'CALL_WRITING' }, PE: { activity: 'PUT_BUYING' } },
              { strike: 23950, CE: { activity: 'CALL_LONG_UNWINDING' }, PE: { activity: 'PUT_SHORT_COVERING' } },
              { strike: 24000, CE: { activity: 'CALL_LONG_UNWINDING' }, PE: { activity: 'PUT_SHORT_COVERING' } },
            ],
          },
          contract_selection: {
            PE: { trading_symbol: '24100 PE', strike: 23900 },
          },
          premium_attribution: {
            PE: { premium: 248, intrinsic: 231.4, extrinsic: 31.75 },
          },
          decision: {
            current_action: 'WAIT_FOR_RETEST',
            banner: 'Directional alignment present. Awaiting lower timeframe confirmation.',
            next_trigger: 'Lower timeframe retest at 23900–23950',
            entry_zone_low: 23900,
            entry_zone_high: 23950,
            hold_guidance: '15-30 min',
            risk_reward: 2.5,
            readiness_score: null,
            evidence_count: 4,
            evidence_total: 7,
            invalidation_level: '24000',
          },
          persistence: { snapshots_retained: 1 },
          continuation_reversal: { confirmed_state: 'BALANCED' },
          previous_oi: { call_wall: 25000, put_wall: 23000, aggregate_intraday_pe_change: '-3929120' },
          melt_risk: { state: 'WATCH' },
          gamma: { status: 'UNAVAILABLE', available: false },
          why: {
            observed: [
              'PUT writing dominance in 23800–24000 band',
              'CALL unwinding below ATM',
              'Seven strike breadth 4 / 7',
              'Pressure net delta negative',
            ],
            unavailable: [
              'CALL wall at 25000 remains intact',
              'No confirmed breakdown below 23900',
              'OI build-up in 24100 CE',
              'Gamma unavailable for confirmation',
            ],
          },
        },
      },
    },
  }
  for (const key of DASHBOARD_FEED_KEYS) if (!(key in feeds)) feeds[key] = null
  return feeds as Record<DashboardFeedKey, unknown>
}
