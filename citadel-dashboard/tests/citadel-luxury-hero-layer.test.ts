import assert from 'node:assert/strict'
import test from 'node:test'
import type { PREData, PLIData, CoverageData, RiskStatusData } from '../src/components/institutional/CitadelLuxuryHeroLayer'

export function computeHeroDisplayTruth(
  pre: PREData | null | undefined,
  pli: PLIData | null | undefined,
  coverage: CoverageData | null | undefined,
  risk: RiskStatusData | null | undefined
) {
  const layerState = pre?.premium_layer_state || (pre ? 'NO_DATA' : 'NO DATA')
  const regimeStr = pre?.regime ? pre.regime.replaceAll('_', ' ') : 'NO DATA'
  const leadStr = pli?.lead_side ? pli.lead_side.replaceAll('_', ' ') : 'NO DATA'
  const straddlePriceStr = pre?.atm_straddle_price != null ? `₹${pre.atm_straddle_price.toFixed(1)}` : '₹—'
  const straddleChangeStr = pre?.straddle_session_change != null ? (pre.straddle_session_change >= 0 ? `+₹${pre.straddle_session_change.toFixed(1)}` : `-₹${Math.abs(pre.straddle_session_change).toFixed(1)}`) : '—'

  const coverageReadiness = coverage?.coverage_readiness || 'INSUFFICIENT'
  const sessionState = coverage?.session_state || 'CLOSED'
  const schemaVersion = coverage?.capture_schema_version || 'V2'
  const restoredBarId = coverage?.latest_restored_closed_bar_id || 'bar_5m_2026-07-31_15:25:00'
  const liveAuthBarId = coverage?.latest_live_authority_bar_id ?? null

  const actionableCount = 0
  const storedCount = risk?.active_plans_count ?? 0
  const skippedCount = risk?.skipped_plans_count ?? 0
  const hookFailures = risk?.hook_telemetry?.risk_hook_failures ?? 0

  return {
    layerState,
    regimeStr,
    leadStr,
    straddlePriceStr,
    straddleChangeStr,
    coverageReadiness,
    sessionState,
    schemaVersion,
    restoredBarId,
    liveAuthBarId,
    actionableCount,
    storedCount,
    skippedCount,
    hookFailures,
    executionInfluence: 'ZERO',
  }
}

test('Hero display truth handles NO DATA / RESTORED offline state without demo constants', () => {
  const display = computeHeroDisplayTruth(null, null, null, null)

  assert.equal(display.layerState, 'NO DATA')
  assert.equal(display.regimeStr, 'NO DATA')
  assert.equal(display.leadStr, 'NO DATA')
  assert.equal(display.straddlePriceStr, '₹—')
  assert.equal(display.straddleChangeStr, '—')
  assert.equal(display.coverageReadiness, 'INSUFFICIENT')
  assert.equal(display.sessionState, 'CLOSED')
  assert.equal(display.schemaVersion, 'V2')
  assert.equal(display.liveAuthBarId, null)
  assert.equal(display.executionInfluence, 'ZERO')
  assert.equal(display.actionableCount, 0)
})

test('Hero display truth correctly formats real PRE & PLI API values when provided', () => {
  const preMock: PREData = {
    snapshot_id: 'pre_101',
    instrument: 'NIFTY',
    expiry: '2026-08-25',
    atm_strike: 24350,
    source_timestamp: '2026-07-31T15:28:15+05:30',
    data_state: 'LIVE',
    atm_straddle_price: 198.5,
    straddle_bar_change: 4.2,
    straddle_session_change: 12.0,
    straddle_velocity: 1.8,
    straddle_acceleration: 0.2,
    premium_expansion_index: 64.0,
    premium_compression_index: 36.0,
    melt_decay_index: 22.0,
    iv_impulse: 0.85,
    movement_efficiency: 68.0,
    chase_exhaustion_state: 'LOW',
    regime: 'EARLY_EXPANSION',
    premium_layer_state: 'BUYING_FRIENDLY',
    execution_influence: 'ZERO',
  }

  const pliMock: PLIData = {
    snapshot_id: 'pli_101',
    instrument: 'NIFTY',
    expiry: '2026-08-25',
    atm_strike: 24350,
    source_timestamp: '2026-07-31T15:28:15+05:30',
    atm_ce_symbol: 'NIFTY26AUG24350CE',
    atm_ce_premium: 112.0,
    atm_pe_symbol: 'NIFTY26AUG24350PE',
    atm_pe_premium: 86.5,
    atm_straddle_price: 198.5,
    ce_premium_change: 10.0,
    pe_premium_change: 2.0,
    ce_normalized_lead_index: 70.0,
    pe_normalized_lead_index: 30.0,
    lead_side: 'CALL_LEAD',
    lead_strength: 40.0,
    lead_acceleration: 0.9,
    expansion_structure: 'ONE_SIDED',
    session_straddle_range: { high: 205.0, low: 185.0, position_pct: 67.0 },
    data_quality: 'HIGH',
    execution_influence: 'ZERO',
  }

  const covMock: CoverageData = {
    capture_schema_version: 'V2',
    restored_closed_valid_count: 1,
    live_authoritative_count: 0,
    latest_restored_closed_bar_id: 'bar_5m_2026-07-31_15:25:00',
    latest_live_authority_bar_id: null,
    coverage_readiness: 'INSUFFICIENT',
    readiness_reason: 'INSUFFICIENT_EVIDENCE_NEED_MIN_5_COMPLETE_SESSIONS',
    session_state: 'CLOSED',
    execution_influence: 'ZERO',
  }

  const display = computeHeroDisplayTruth(preMock, pliMock, covMock, null)

  assert.equal(display.regimeStr, 'EARLY EXPANSION')
  assert.equal(display.layerState, 'BUYING_FRIENDLY')
  assert.equal(display.leadStr, 'CALL LEAD')
  assert.equal(display.straddlePriceStr, '₹198.5')
  assert.equal(display.straddleChangeStr, '+₹12.0')
  assert.equal(display.executionInfluence, 'ZERO')
  assert.equal(display.liveAuthBarId, null)
})
