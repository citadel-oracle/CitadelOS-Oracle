import assert from 'node:assert/strict'
import test from 'node:test'
import type { PREData, PLIData, CoverageData, RiskStatusData } from '../src/components/institutional/OptionBuyerDecisionDeck'

export function computeDecisionDeckState(
  pre: PREData | null | undefined,
  pli: PLIData | null | undefined,
  coverage: CoverageData | null | undefined,
  risk: RiskStatusData | null | undefined
) {
  const liveAuthBarId = coverage?.latest_live_authority_bar_id ?? null
  const layerState = pre?.premium_layer_state || 'NO_DATA'
  const straddleChange = pre?.straddle_session_change ?? null

  let decisionTitle = 'NO TRADE — NO LIVE AUTHORITY'
  let tone = 'muted'
  let alignmentCount = 0

  if (!liveAuthBarId) {
    decisionTitle = 'NO TRADE — NO LIVE AUTHORITY'
    tone = 'muted'
    alignmentCount = 0
  } else if (layerState === 'BUYING_FRIENDLY' && pli?.lead_side === 'CALL_LEAD') {
    decisionTitle = 'BUY CALL ↑'
    tone = 'emerald'
    alignmentCount = 4
  } else if (layerState === 'BUYING_FRIENDLY' && pli?.lead_side === 'PUT_LEAD') {
    decisionTitle = 'BUY PUT ↓'
    tone = 'rose'
    alignmentCount = 4
  } else if (layerState === 'AVOID') {
    decisionTitle = 'SIDEWAYS — AVOID OPTION BUYING'
    tone = 'amber'
    alignmentCount = 2
  } else {
    decisionTitle = 'WAIT FOR CONFIRMATION'
    tone = 'amber'
    alignmentCount = 1
  }

  let straddleImpactState = 'NO DATA'
  if (straddleChange !== null && straddleChange < 0) {
    straddleImpactState = 'SIDEWAYS / PREMIUM MELT — AVOID FRESH BUYING'
  } else if (straddleChange !== null && straddleChange > 0) {
    if (pli?.expansion_structure === 'ONE_SIDED') {
      straddleImpactState = 'DIRECTIONAL BUY OPPORTUNITY'
    } else {
      straddleImpactState = 'VOLATILITY EXPANSION — DIRECTION NOT CONFIRMED'
    }
  }

  return {
    decisionTitle,
    tone,
    alignmentCount,
    straddleImpactState,
    executionInfluence: 'ZERO',
  }
}

test('Decision deck returns NO TRADE — NO LIVE AUTHORITY when live authority bar is null', () => {
  const covMock: CoverageData = {
    capture_schema_version: 'V2',
    latest_restored_closed_bar_id: 'bar_5m_2026-07-31_15:25:00',
    latest_live_authority_bar_id: null,
    coverage_readiness: 'INSUFFICIENT',
    session_state: 'CLOSED',
    execution_influence: 'ZERO',
  }

  const preMock: PREData = {
    snapshot_id: 'pre_1',
    instrument: 'NIFTY',
    expiry: '2026-08-25',
    atm_strike: 24400,
    source_timestamp: '2026-07-31T15:28:15+05:30',
    data_state: 'RESTORED',
    atm_straddle_price: 210.0,
    straddle_bar_change: 0.0,
    straddle_session_change: -5.0,
    straddle_velocity: 0.0,
    straddle_acceleration: 0.0,
    premium_expansion_index: 50.0,
    premium_compression_index: 50.0,
    melt_decay_index: 40.0,
    iv_impulse: null,
    movement_efficiency: 50.0,
    chase_exhaustion_state: 'LOW',
    regime: 'EARLY_EXPANSION',
    premium_layer_state: 'BUYING_FRIENDLY',
    execution_influence: 'ZERO',
  }

  const pliMock: PLIData = {
    snapshot_id: 'pli_1',
    instrument: 'NIFTY',
    expiry: '2026-08-25',
    atm_strike: 24400,
    source_timestamp: '2026-07-31T15:28:15+05:30',
    atm_ce_symbol: 'CE',
    atm_ce_premium: 100,
    atm_pe_symbol: 'PE',
    atm_pe_premium: 110,
    atm_straddle_price: 210.0,
    ce_premium_change: 10,
    pe_premium_change: -15,
    ce_normalized_lead_index: 70,
    pe_normalized_lead_index: 30,
    lead_side: 'CALL_LEAD',
    lead_strength: 40,
    lead_acceleration: 0.5,
    expansion_structure: 'ONE_SIDED',
    session_straddle_range: { high: 220, low: 200, position_pct: 50 },
    data_quality: 'HIGH',
    execution_influence: 'ZERO',
  }

  const state = computeDecisionDeckState(preMock, pliMock, covMock, null)

  assert.equal(state.decisionTitle, 'NO TRADE — NO LIVE AUTHORITY')
  assert.equal(state.tone, 'muted')
  assert.equal(state.executionInfluence, 'ZERO')
  assert.equal(state.straddleImpactState, 'SIDEWAYS / PREMIUM MELT — AVOID FRESH BUYING')
})

test('Decision deck returns BUY CALL ↑ when live authority exists, PRE is BUYING_FRIENDLY, and PLI is CALL_LEAD', () => {
  const covMock: CoverageData = {
    capture_schema_version: 'V2',
    latest_restored_closed_bar_id: 'bar_5m_2026-07-31_15:25:00',
    latest_live_authority_bar_id: 'bar_5m_2026-07-31_15:30:00',
    coverage_readiness: 'READY',
    session_state: 'LIVE',
    execution_influence: 'ZERO',
  }

  const preMock: PREData = {
    snapshot_id: 'pre_2',
    instrument: 'NIFTY',
    expiry: '2026-08-25',
    atm_strike: 24400,
    source_timestamp: '2026-07-31T15:30:00+05:30',
    data_state: 'LIVE',
    atm_straddle_price: 215.0,
    straddle_bar_change: 5.0,
    straddle_session_change: 10.0,
    straddle_velocity: 2.5,
    straddle_acceleration: 0.8,
    premium_expansion_index: 75.0,
    premium_compression_index: 25.0,
    melt_decay_index: 10.0,
    iv_impulse: 1.2,
    movement_efficiency: 80.0,
    chase_exhaustion_state: 'LOW',
    regime: 'EARLY_EXPANSION',
    premium_layer_state: 'BUYING_FRIENDLY',
    execution_influence: 'ZERO',
  }

  const pliMock: PLIData = {
    snapshot_id: 'pli_2',
    instrument: 'NIFTY',
    expiry: '2026-08-25',
    atm_strike: 24400,
    source_timestamp: '2026-07-31T15:30:00+05:30',
    atm_ce_symbol: 'CE',
    atm_ce_premium: 125,
    atm_pe_symbol: 'PE',
    atm_pe_premium: 90,
    atm_straddle_price: 215.0,
    ce_premium_change: 15,
    pe_premium_change: -5,
    ce_normalized_lead_index: 80,
    pe_normalized_lead_index: 20,
    lead_side: 'CALL_LEAD',
    lead_strength: 60,
    lead_acceleration: 1.2,
    expansion_structure: 'ONE_SIDED',
    session_straddle_range: { high: 220, low: 200, position_pct: 75 },
    data_quality: 'HIGH',
    execution_influence: 'ZERO',
  }

  const state = computeDecisionDeckState(preMock, pliMock, covMock, null)

  assert.equal(state.decisionTitle, 'BUY CALL ↑')
  assert.equal(state.tone, 'emerald')
  assert.equal(state.alignmentCount, 4)
  assert.equal(state.straddleImpactState, 'DIRECTIONAL BUY OPPORTUNITY')
})
