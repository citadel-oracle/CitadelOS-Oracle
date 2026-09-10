import type { ArgusProviderProjection } from './oracleArgusProjection'

type VisualFixture = {
  tactical: Record<string, unknown>
  optionsStructure: Record<string, unknown>
  vob: Record<string, unknown>
  provider: ArgusProviderProjection
}

const SNAPSHOT = 'TEST-01C-20260807-152902'
const SOURCE_TIMESTAMP = '2026-08-07T15:29:02.318313+05:30'

const outcome = (score: number, state: string, trend = 'STABLE') => ({
  raw_score: score,
  smoothed_score: score,
  display_score: score,
  state,
  trend,
})

const spine = [24450, 24500, 24550, 24600, 24650, 24700, 24750].map((strike, index) => ({
  strike,
  structural_role: strike === 24600 ? 'STRONGEST STRUCTURAL STRIKE' : strike < 24600 ? 'SUPPORT OBSERVATION' : 'RESISTANCE OBSERVATION',
  wall_role: strike === 24600 ? 'WALL / MAGNET' : 'BACKGROUND',
  CE: {
    probable_flow: index < 3 ? 'CALL SHORT COVERING' : index > 4 ? 'CALL WRITING' : 'MIXED',
    velocity_arrow: index < 3 ? '↑↑' : index > 4 ? '↓' : '→',
    oi_velocity: 14200 - index * 920,
    oi_acceleration: 3100 - index * 410,
    load_intensity: Math.max(42, 96 - Math.abs(index - 3) * 12),
    covering_unwind: index < 3 ? 'ACCELERATING' : 'STABLE',
    heat_history: [index + 1, index + 2, index + 4, index + 6, index + 9],
  },
  PE: {
    probable_flow: index <= 3 ? 'PUT WRITING' : index > 4 ? 'PUT BUYING' : 'MIXED',
    velocity_arrow: index <= 3 ? '↑' : index > 4 ? '↑↑' : '→',
    oi_velocity: 11600 + index * 760,
    oi_acceleration: 1800 + index * 330,
    load_intensity: Math.max(38, 88 - Math.abs(index - 3) * 11),
    covering_unwind: index <= 3 ? 'ADDING' : 'ACCELERATING',
    heat_history: [index + 2, index + 3, index + 5, index + 7, index + 8],
  },
}))

const provider: ArgusProviderProjection = {
  state: 'LIVE',
  verdict: 'CALL SIDE BUILDING',
  providerLineageAvailable: true,
  exactContractLineageAvailable: true,
  underlying: 'NIFTY',
  expiry: '2026-08-11',
  securityId: 'TEST-CE-24600',
  sourceTimestamp: SOURCE_TIMESTAMP,
  sourceEventTime: SOURCE_TIMESTAMP,
  timestampSemantics: 'AUTHORITATIVE_SOURCE_EVENT_TIME',
  snapshotId: SNAPSHOT,
  producerRevision: 'TEST-REV-01',
  chainTimeframe: 'OPTION_CHAIN',
  callPressure: 64,
  putPressure: 47,
  breadth: '5C · 2P',
  persistence: 'CALL · 3/3',
  pcr: 0.7335,
  pcrTrend: 'FALLING',
  straddleState: 'EXPANDING',
  ceBuyWriteSplit: 'NOT REPORTED',
  peBuyWriteSplit: 'NOT REPORTED',
  bestStackStrike: null,
  supportStrike: 24600,
  resistanceStrike: 24700,
  highestLoadStrike: 24600,
  highestLoadCe: 96,
  highestLoadPe: 88,
  highestLoadRole: 'WALL / MAGNET',
  fastestAccelerationStrike: 24450,
  fastestAccelerationCe: 3100,
  fastestAccelerationPe: 1800,
  flowType: 'PROBABLE FLOW',
  gammaStrike: 24600,
  wallMagnet: 'WALL 24600 · MAGNET 24600',
  gammaBlast: 'LOADING · PROXY',
  proposedContract: 'NO AUTHORIZED CONTRACT',
  trigger: '5M CONFIRMATION REQUIRED',
  invalidation: 'CANONICAL INVALIDATION UNAVAILABLE',
  chaseRisk: 'MODERATE',
  canonicalRead: 'CALL structure leads; contract authorization remains locked.',
  canonicalWhy: 'Structure and probable flow align while execution evidence remains incomplete.',
  compactSpine: [],
  fullSpine: [],
}

export const buildOracleArgusPrime01CVisualFixture = (mode: string): VisualFixture => {
  const isUnavailable = mode === 'unavailable'
  const isStale = mode === 'stale'
  const score = mode === '49' ? 49 : mode === '50' ? 50 : mode === 'green' || mode === 'reduced' || isStale ? 72 : 29
  const direction = score >= 50 ? 'CALL' : 'HOLD'
  const truthState = isUnavailable ? 'NO_DATA' : isStale ? 'LAST_GOOD' : 'LIVE'
  const age = isStale ? 84.5 : isUnavailable ? null : 1.8

  const prime = isUnavailable ? {
    data_truth: {
      state: 'NO_DATA',
      age_seconds: null,
      snapshot_id: `${SNAPSHOT}-UNAVAILABLE`,
      source_timestamp: null,
      formula_version: 'ARGUS_PRIME_V3_AUDITABLE',
      evidence_coverage: 0,
    },
    hero_state: 'DATA UNAVAILABLE',
    action: 'Action locked · canonical projection unavailable',
    display_score: null,
    outcome_engines: {},
    tactical_summary: { state: 'DATA LOCKED', title: 'DATA UNAVAILABLE', reasons: ['Canonical producer has not published a coherent snapshot.'] },
    chain_summary: ['No current option-chain evidence is authorized.'],
    why: ['No coherent canonical snapshot.'],
  } : {
    data_truth: {
      state: truthState,
      age_seconds: age,
      snapshot_id: `${SNAPSHOT}-${mode.toUpperCase()}`,
      source_timestamp: SOURCE_TIMESTAMP,
      receive_timestamp: '2026-08-07T15:29:04.955800+05:30',
      freshness_threshold_seconds: 20,
      formula_version: 'ARGUS_PRIME_V3_AUDITABLE',
      evidence_coverage: 100,
    },
    snapshot_id: `${SNAPSHOT}-${mode.toUpperCase()}`,
    direction,
    hero_state: score >= 50 ? 'CALL SIDE BUILDING' : 'HOLD — NO CLEAN EDGE',
    display_state: score >= 50 ? 'CALL SIDE BUILDING' : 'HOLD',
    action: isStale ? 'LAST GOOD SNAPSHOT · actionable levels locked' : 'Wait for completed 5M confirmation',
    raw_score: score + 2.4,
    smoothed_score: score + 0.8,
    display_score: score,
    argus_prime_score: score,
    score_formula_version: 'ARGUS_PRIME_V3_AUDITABLE',
    evidence_coverage: 100,
    trigger: '5M CLOSE ABOVE CANONICAL TRIGGER',
    invalidation_text: 'CANONICAL INVALIDATION UNAVAILABLE',
    recommended_contract: 'NO AUTHORIZED CONTRACT',
    retest_status: 'WAITING',
    outcome_engines: {
      call_edge: outcome(score >= 50 ? 72 : 41, score >= 50 ? 'BUILDING' : 'WEAK', score >= 50 ? 'RISING' : 'STABLE'),
      put_edge: outcome(score >= 50 ? 36 : 61, score >= 50 ? 'WEAK' : 'MODERATE', score >= 50 ? 'FALLING' : 'STABLE'),
      hold_edge: outcome(score >= 50 ? 34 : 47, score >= 50 ? 'RECEDING' : 'BALANCED'),
      decay_risk: outcome(25, 'MANAGEABLE'),
      big_move: outcome(53, 'LOADING', 'RISING'),
      gamma_blast: outcome(34, 'NO BLAST'),
      reversal: outcome(12, 'LOW'),
    },
    tactical_summary: {
      state: score >= 50 ? 'STABLE BIAS' : 'BALANCED',
      title: score >= 50 ? 'CALL SIDE BUILDING' : 'HOLD — NO CLEAN EDGE',
      directional_posture: direction,
      reasons: score >= 50
        ? ['CALL edge exceeds PUT edge.', 'Big Move readiness is loading.', '24,600 is the strongest structural stack.', 'Fresh completed 5M confirmation is still required.']
        : ['CALL and PUT evidence is not independently aligned.', 'Structural focus is observation-only.', 'No contract is authorized.'],
    },
    chain_summary: score >= 50
      ? ['Bullish probable-flow posture.', 'Strongest structural focus: 24,600.', 'OI migration is upward.', 'Futures confirmation is unavailable.', 'No authorized contract.']
      : ['Mixed option-chain posture.', 'No clean directional edge.', 'Structural focus is not a best strike.'],
    why: ['Canonical projection is shared with Workspace.', 'Score is edge/readiness, not probability.', 'Execution influence remains zero.'],
    smart_money_flow: { score: 35, label: 'BALANCED QUIET' },
    pressure_to_price: { score: 44, state: 'MIXED' },
    wall_outcome: { score: 35, outcome: 'PIN' },
    gamma_regime: { score: 43, state: 'MOVE SUPPRESSED' },
    futures_confirmation: { score: null, state: 'UNAVAILABLE' },
    live_pcr: {
      oi_pcr: 0.7335,
      trend: 'FALLING',
      change_1m: -0.0097,
      change_1m_state: 'AVAILABLE',
      change_5m: null,
      change_5m_state: 'HISTORY BUILDING',
      session_percentile: 24,
      session_percentile_state: 'AVAILABLE',
      freshness: truthState,
      source_age_seconds: age,
    },
    best_strike_stack: {
      strongest_structural_strike: 24600,
      authorized_contract: false,
      authorization_reason: 'CONTRACT QUALITY NOT AUTHORIZED',
      state: score >= 50 ? 'BULLISH OBSERVATION' : 'MIXED OBSERVATION',
      direction,
      score: 48.3,
      primary_flow: { label: 'CALL SHORT COVERING', arrow: '↑↑', acceleration: 3100, load: 96 },
      defence_flow: { label: 'PUT WRITING', arrow: '↑', acceleration: 2790, load: 88 },
      migration: { state: 'UPWARD', label: 'COHERENT', path: [24550, 24600, 24650] },
      score_contributions: {
        ce_directional_flow: { contribution: 8.4, weight: 0.18 },
        pe_directional_flow: { contribution: 7.8, weight: 0.18 },
        acceleration: { contribution: 6.1, weight: 0.14 },
        structural_load: { contribution: 8.7, weight: 0.16 },
        migration: { contribution: 5.8, weight: 0.12 },
        liquidity: { contribution: 5.2, weight: 0.12 },
      },
    },
    expiry_gamma_blast: {
      phase: 'LOADING',
      score: 34,
      direction: 'CALL',
      chase_risk: 'MODERATE',
      components: { concentration: 57, wall_integrity: 48, probable_flow: 44, convexity: 31, breadth: 42, persistence: 39 },
    },
    strike_spine: spine,
    score_breakdown: { smart_flow: 35, pressure_to_price: 44, wall_outcome: 35, gamma_regime: 43, big_move: 53 },
  }

  const optionsStructure = isUnavailable ? {} : {
    symbol: 'NIFTY', spot: 24570.65, anchor: 24600, expiry: '2026-08-11', runtime: 'LIVE', source_freshness: 'FRESH', executionInfluence: 'ZERO',
    rollover: { state: 'LOCKED', last_rollover: '2026-08-07T09:30:00+05:30' },
    data_quality: { status: 'LIVE', data_gap_count: 0 },
    structural_read: { headline: score >= 50 ? 'CALL STRUCTURE LEADS' : 'PUT STRUCTURE LEADS', lines: ['Completed 3M and 5M option buckets only.', 'ARGUS flow remains a separate participation read.'] },
    duel: { ce_score: score >= 50 ? 60 : 45, pe_score: score >= 50 ? 45 : 60, delta: score >= 50 ? 15 : -15, state: score >= 50 ? 'MODERATE CALL ADVANTAGE' : 'MODERATE PUT ADVANTAGE', label: score >= 50 ? 'CALL +15' : 'PUT +15' },
    contracts: {
      CE: {
        premium: 146.75,
        ssi: { score: score >= 50 ? 60 : 45, band: score >= 50 ? 'STRONG' : 'MIXED' },
        contract: { trading_symbol: 'NIFTY 11 AUG 24600 CE', security_id: 'TEST-CE-24600', expiry: '2026-08-11' },
        composite: { state: 'BULLISH' },
        decision_window: { state: 'ROOM AVAILABLE' },
        engine_agreement: { result: 'PARTIAL AGREEMENT' }, quality: { status: 'LIVE', freshness: 'FRESH' },
        vob: { state: 'BULLISH', strength: 71, reason: '3M supply close-break confirmed; retest held.' },
        latest_state_change: { summary: '3M supply break; retest held', evaluated_through: SOURCE_TIMESTAMP },
        trend: { state: 'BULLISH', strength: 71, ema_50: 139.4, supertrend_value: 143.6, supertrend_direction: 'BULLISH', reason: 'Premium remains above EMA50 and bullish Supertrend.' },
        structures: {
          '3m': { state: 'BULLISH', premium: 146.75, completed_bucket: true, evaluated_through: SOURCE_TIMESTAMP, demand: { status: 'TESTED', zone_low: 145.8, zone_high: 147.1, touch_count: 3 }, supply: { status: 'BROKEN', zone_low: 153.4, zone_high: 154.2, touch_count: 2 }, supply_break: true, bullish_retest: true },
          '5m': { state: 'BULLISH', premium: 146.75, completed_bucket: true, evaluated_through: SOURCE_TIMESTAMP, demand: { status: 'ACTIVE', zone_low: 141.9, zone_high: 143.6, touch_count: 2 }, supply: { status: 'ACTIVE', zone_low: 158.2, zone_high: 160.1, touch_count: 1 } },
        },
        score_breakdown: { vob_structure: { contribution: 24 }, agreement: { contribution: 11 }, ema_50: { contribution: 12 } },
      },
      PE: {
        premium: 154.2,
        ssi: { score: score >= 50 ? 45 : 60, band: score >= 50 ? 'MIXED' : 'STRONG' },
        contract: { trading_symbol: 'NIFTY 11 AUG 24600 PE', security_id: 'TEST-PE-24600', expiry: '2026-08-11' },
        composite: { state: 'BEARISH' },
        decision_window: { state: 'NEAR OPPOSING ZONE' },
        engine_agreement: { result: 'STRUCTURE LEADS' }, quality: { status: 'LIVE', freshness: 'FRESH' },
        vob: { state: 'BEARISH', strength: 29, reason: 'Demand close-break remains authoritative.' },
        latest_state_change: { summary: 'Demand close-break confirmed', evaluated_through: SOURCE_TIMESTAMP },
        trend: { state: 'BEARISH', strength: 29, ema_50: 161.3, supertrend_value: 158.8, supertrend_direction: 'BEARISH', reason: 'Premium remains below EMA50 and bearish Supertrend.' },
        structures: {
          '3m': { state: 'BEARISH', premium: 154.2, completed_bucket: true, evaluated_through: SOURCE_TIMESTAMP, demand: { status: 'BROKEN', zone_low: 150.1, zone_high: 151.5, touch_count: 2 }, supply: { status: 'TESTED', zone_low: 160.3, zone_high: 162.2, touch_count: 3 }, demand_break: true, bearish_retest: false },
          '5m': { state: 'NEUTRAL', premium: 154.2, completed_bucket: true, evaluated_through: SOURCE_TIMESTAMP, demand: { status: 'ACTIVE', zone_low: 148.7, zone_high: 150.4, touch_count: 1 }, supply: { status: 'ACTIVE', zone_low: 164.8, zone_high: 167.1, touch_count: 2 } },
        },
        score_breakdown: { vob_structure: { contribution: 18 }, agreement: { contribution: 8 }, ema_50: { contribution: 9 } },
      },
    },
    option_flow: {
      call: { score: 61, activity: 'SHORT COVERING', quality_band: 'MEDIUM' },
      put: { score: 62, activity: 'WRITING / SHORT BUILDUP', quality_band: 'MEDIUM' },
      edge: { label: 'NO CLEAN EDGE', state: 'BALANCED', summary: 'Near-equal participation; no directional flow claim.' },
    },
  }

  return {
    tactical: { symbol: 'NIFTY', expiry: '2026-08-11', argus_prime: prime },
    optionsStructure,
    vob: isUnavailable ? {} : {
      nearest_support: { zone_low: 24497.95, zone_high: 24516.8 },
      nearest_resistance: { zone_low: 24575.1, zone_high: 24591.6 },
    },
    provider: { ...provider, state: truthState, snapshotId: `${SNAPSHOT}-${mode.toUpperCase()}` },
  }
}
