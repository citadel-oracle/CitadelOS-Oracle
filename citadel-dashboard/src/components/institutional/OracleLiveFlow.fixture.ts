type FixtureName = 'call' | 'put' | 'wait' | 'chase' | 'absorption' | 'reversal' | 'degraded'
type JsonRecord = Record<string, unknown>

interface FlowFixture extends Record<string, unknown> {
  call_strength: number
  put_strength: number
  directional_score: number
  directional_state: string
  action_eligible: boolean
  action_lock_reasons: string[]
  data_quality: string
  reversal_state: string
  snapshot_age_seconds: number
  family_values: Record<string, JsonRecord>
  decision: JsonRecord
}

const base: FlowFixture = {
  status: 'AVAILABLE',
  schema_version: 1,
  formula_version: 'ORDER_FLOW_V1_20260809',
  revision: 91,
  snapshot_id: 'TEST_flow_01c_p3',
  session_id: '2026-08-07',
  generated_at: '2026-08-07T09:42:15+05:30',
  projection_state: 'LIVE',
  call_strength: 87,
  put_strength: 14,
  directional_score: 0.73,
  directional_state: 'CALL',
  action_eligible: true,
  action_lock_reasons: [],
  data_quality: 'GOOD',
  signed_flow_coverage: 0.91,
  profile_coverage: 0.88,
  reversal_state: 'STABLE_DIRECTION',
  snapshot_age_seconds: 0.8,
  freshness: {
    NIFTY_FUTURE: { state: 'FRESH', age_seconds: 0.08, event_timestamp: 1786075935 },
    ATM_CE: { state: 'FRESH', age_seconds: 0.11, event_timestamp: 1786075935 },
    ATM_PE: { state: 'FRESH', age_seconds: 0.12, event_timestamp: 1786075935 },
  },
  family_values: {
    FUTURES_PRESSURE: { state: 'BUY', status: 'AVAILABLE' },
    BOOK_PRESSURE: { book_pressure: 0.74, state: 'BUY', status: 'AVAILABLE' },
    RESPONSE_QUALITY: { response_quality: 0.82, state: 'CLEAN_BULL', status: 'AVAILABLE' },
    OPTION_CONFIRMATION: { value: 0.71, status: 'AVAILABLE_WITH_GREEKS', greeks_mode: 'DELTA_EQUIVALENT' },
    REVERSAL: { state: 'STABLE_DIRECTION' },
    LOCATION: {
      status: 'AVAILABLE', poc: 24982, vah: 25014, val: 24951,
      location_state: 'VAH_ACCEPTED', cvd: 18420, cvd_state: 'RISING',
      divergence_state: 'NONE', footprint_state: 'BUY 4x STACKED · CLEAN',
      stacked_levels: 4, imbalance_ratio_max: 4.2,
    },
  },
  decision: {
    action: 'BUY CALL', reason: 'CANONICAL_FLOW_ENTRY_READY', flow_state: 'STRENGTHENING',
    confirmed: true,
    entry_quality: 'HIGH', reversal_risk: 'LOW',
    contract: { trading_symbol: 'NIFTY 25000 CE', security_id: 'TEST-CE', option_type: 'CE', expiry: '2026-08-13', current_premium: 127.4 },
    entry_low: 126, entry_high: 129, invalidation: 121, target_1: 138, target_2: 147,
    rr_1: 2, rr_2: 3.6, levels_status: 'AVAILABLE', levels_reason: null,
    do_not_chase: false, advisory_only: true, execution_influence: 'ZERO',
  },
  diagnostics: {
    validation: 'SHADOW_LIVE_VALIDATION_PENDING', score_is_probability: false,
  },
  research: {
    status: 'READY', generated_at: '2026-08-07T09:42:15+05:30',
    current_episode: {
      episode_id: 'TEST_episode_call', direction: 'CALL', contract: 'TEST-CE',
      started_at: '2026-08-07T09:41:00+05:30', trigger_option_price: 126.4,
      current_option_price: 127.4, current_score: 87, peak_score: 91,
      trigger_score: 82, edge_captured: null, flow_state: 'STRENGTHENING',
      reversal_state: 'STABLE_DIRECTION', mfe: 18.2, mae: -3.1,
      complete: false, data_quality: 'GOOD',
    },
    today: {
      call_episodes: 4, put_episodes: 3, completed: 6, successful: null, failed: null,
      neutral: null, false_signals: null, reversals: 2, clean_reversals: null,
      median_reversal_lead_ms: null, data_quality_coverage: 0.93,
    },
    score_edge: [
      { band: '60-69', sample_count: 11, status: 'RESEARCHING', outcome_rate: null },
      { band: '70-79', sample_count: 8, status: 'RESEARCHING', outcome_rate: null },
      { band: '80-89', sample_count: 5, status: 'RESEARCHING', outcome_rate: null },
      { band: '90+', sample_count: 2, status: 'RESEARCHING', outcome_rate: null },
    ],
    best_combination: { status: 'RESEARCHING', families: ['FUTURES_PRESSURE', 'RESPONSE', 'OPTION_CONFIRMATION', 'CONTEXTUAL_LOCATION'] },
    reversal_log: [{ episode_id: 'TEST_episode_put', direction: 'PUT', latest: { timestamp: '09:34:12', state: 'REVERSAL_FORMING' }, actual_reversal: null }],
    event_timeline: [
      { timestamp: '09:41:00', event: 'EPISODE_ACTIVE', direction: 'CALL' },
      { timestamp: '09:42:15', event: 'FLOW_STRENGTHENING', direction: 'CALL' },
    ],
    shadow_pnl: { status: 'NOT_YET_AVAILABLE', reason: 'NO_DEFINED_SHADOW_EXIT_OUTCOME' },
    edge_health: { sample_count: 7, edge_stability: 'RESEARCHING', maturity: 'RESEARCH' },
    provisional_config: { validation: 'ENGINEERING_DEFAULTS_NOT_VALIDATED' },
  },
  advisory_only: true,
  execution_influence: 'ZERO',
  __fixture: true,
}

export function buildOracleLiveFlowFixture(value: string | null): Record<string, unknown> | null {
  const fixture = (value ?? '').toLowerCase() as FixtureName
  if (!['call', 'put', 'wait', 'chase', 'absorption', 'reversal', 'degraded'].includes(fixture)) return null
  const projection = structuredClone(base)
  if (fixture === 'put') {
    projection.call_strength = 18
    projection.put_strength = 84
    projection.directional_score = -0.66
    projection.directional_state = 'PUT'
    projection.family_values.FUTURES_PRESSURE = { state: 'SELL', status: 'AVAILABLE' }
    projection.family_values.BOOK_PRESSURE = { book_pressure: -0.69, state: 'SELL', status: 'AVAILABLE' }
    projection.family_values.RESPONSE_QUALITY = { response_quality: -0.77, state: 'CLEAN_BEAR', status: 'AVAILABLE' }
    projection.family_values.OPTION_CONFIRMATION = { value: -0.72, status: 'AVAILABLE_WITH_GREEKS', greeks_mode: 'DELTA_EQUIVALENT' }
    projection.family_values.LOCATION = {
      ...projection.family_values.LOCATION,
      location_state: 'VAL_BROKEN', cvd_state: 'FALLING', cvd: -14850,
      footprint_state: 'SELL 3x STACKED · CLEAN',
    }
    projection.decision = {
      ...projection.decision,
      action: 'BUY PUT', reason: 'CANONICAL_FLOW_ENTRY_READY', flow_state: 'STRENGTHENING',
      contract: { trading_symbol: 'NIFTY 25000 PE', security_id: 'TEST-PE', option_type: 'PE', expiry: '2026-08-13', current_premium: 131.2 },
      entry_low: 129, entry_high: 132, invalidation: 124, target_1: 142, target_2: 151,
    }
  }
  if (fixture === 'wait') {
    projection.call_strength = 56
    projection.put_strength = 44
    projection.directional_score = 0.12
    projection.directional_state = 'NEUTRAL'
    projection.action_eligible = false
    projection.action_lock_reasons = ['NO_DIRECTIONAL_FLOW_EDGE']
    projection.decision = {
      ...projection.decision, action: 'WAIT', reason: 'NO_DIRECTIONAL_FLOW_EDGE',
      confirmed: false, flow_state: 'STABLE', entry_quality: 'MEDIUM',
      contract: { trading_symbol: 'NIFTY 25000 CE (WATCH)', option_type: 'CE', current_premium: null },
      entry_low: 124, entry_high: 128, invalidation: null, target_1: null, target_2: null,
      rr_1: null, rr_2: null, levels_status: 'FORMING', levels_reason: 'NO_CANONICAL_FLOW_TRADE_PLANNER',
    }
  }
  if (fixture === 'chase') {
    projection.call_strength = 91
    projection.put_strength = 9
    projection.decision = {
      ...projection.decision, action: 'WAIT', reason: 'ENTRY_EXTENSION_EXCEEDED',
      confirmed: false, flow_state: 'STRENGTHENING', entry_quality: "MISSED / DON'T CHASE", reversal_risk: 'RISING', do_not_chase: true,
      contract: { ...(projection.decision.contract as JsonRecord), current_premium: 137 },
    }
    projection.family_values.LOCATION = {
      ...projection.family_values.LOCATION,
      location_state: 'VAH_REJECTION', cvd_state: 'RISING',
      footprint_state: 'BUY 5x STACKED · CLEAN', stacked_levels: 5,
    }
  }
  if (fixture === 'absorption') {
    projection.call_strength = 76
    projection.put_strength = 24
    projection.action_eligible = false
    projection.action_lock_reasons = ['BUYERS_ABSORBED']
    projection.reversal_state = 'REVERSAL_FORMING'
    projection.family_values.RESPONSE_QUALITY = { response_quality: -0.62, state: 'BUYERS_ABSORBED', status: 'AVAILABLE' }
    projection.family_values.LOCATION = {
      ...projection.family_values.LOCATION,
      location_state: 'VAH_TEST', cvd_state: 'RISING',
      footprint_state: 'BUY 5x STACKED · ABSORBED', stacked_levels: 5,
      divergence_state: 'PRICE_NOT_RESPONDING',
    }
    projection.decision = {
      ...projection.decision, action: 'NO TRADE', reason: 'BUYERS_ABSORBED', confirmed: false,
      flow_state: 'WEAKENING', entry_quality: 'POOR', reversal_risk: 'HIGH',
      entry_low: null, entry_high: null, invalidation: null, target_1: null, target_2: null,
      rr_1: null, rr_2: null, levels_status: 'UNAVAILABLE', levels_reason: 'BUYERS_ABSORBED',
    }
  }
  if (fixture === 'reversal') {
    projection.call_strength = 39
    projection.put_strength = 61
    projection.directional_state = 'PUT'
    projection.reversal_state = 'REVERSAL_CONFIRMED'
    projection.family_values.FUTURES_PRESSURE = { state: 'SELL', status: 'AVAILABLE' }
    projection.family_values.BOOK_PRESSURE = { book_pressure: -0.66, state: 'SELL', status: 'AVAILABLE' }
    projection.family_values.RESPONSE_QUALITY = { response_quality: -0.79, state: 'CLEAN_BEAR', status: 'AVAILABLE' }
    projection.family_values.LOCATION = {
      ...projection.family_values.LOCATION,
      location_state: 'VAH_REJECTION', cvd_state: 'FALLING', cvd: -9420,
      footprint_state: 'SELL 4x STACKED · CLEAN', stacked_levels: 4,
      divergence_state: 'BEARISH_DIVERGENCE',
    }
    projection.decision = {
      ...projection.decision, action: 'PROTECT / EXIT', reason: 'REVERSAL_CONFIRMED', confirmed: false,
      flow_state: 'WEAKENING', entry_quality: 'POOR', reversal_risk: 'CONFIRMED',
      contract: { ...(projection.decision.contract as JsonRecord), trading_symbol: 'NIFTY 25000 CE (OPEN)', current_premium: 123 },
    }
  }
  if (fixture === 'degraded') {
    projection.projection_state = 'LAST_GOOD'
    projection.data_quality = 'UNUSABLE'
    projection.directional_state = 'DATA_LOCKED'
    projection.action_eligible = false
    projection.action_lock_reasons = ['FUTURES_FULL_PACKET_STALE', 'PROFILE_DEGRADED']
    projection.snapshot_age_seconds = 9.8
    projection.family_values.LOCATION = {
      status: 'PROFILE_DEGRADED', poc: null, vah: null, val: null,
      location_state: 'UNAVAILABLE', cvd: 812, cvd_state: 'FLAT',
      footprint_state: 'NO_STACKED_IMBALANCE',
    }
    projection.decision = {
      ...projection.decision, action: 'NO TRADE', reason: 'FUTURES_FULL_PACKET_STALE',
      confirmed: false, flow_state: 'UNAVAILABLE', entry_quality: 'UNAVAILABLE', reversal_risk: 'UNAVAILABLE',
      contract: null, entry_low: null, entry_high: null, invalidation: null,
      target_1: null, target_2: null, rr_1: null, rr_2: null,
      levels_status: 'UNAVAILABLE', levels_reason: 'DATA_QUALITY_UNUSABLE',
    }
  }
  return projection
}
