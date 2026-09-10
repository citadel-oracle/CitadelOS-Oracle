import assert from 'node:assert/strict'
import test from 'node:test'
import type { PremiumIntelligenceSnapshotData, PREData, PLIData } from '../src/components/institutional/PremiumIntelligenceCards'

export function computePRECardDisplay(pre: PREData | null | undefined) {
  if (!pre) {
    return {
      heroTitle: 'PREMIUM REGIME — NO DATA',
      layerState: 'NO_DATA',
      layerBadgeClass: 'noData',
      expansionVal: 0,
      meltVal: 0,
      efficiencyVal: 0,
      chaseState: 'LOW',
      ivImpulseStr: 'NOT AVAILABLE',
    }
  }

  const regimeStr = pre.regime ? pre.regime.replaceAll('_', ' ') : 'NO DATA'
  const heroTitle = `PREMIUM REGIME — ${regimeStr}`
  const layerState = pre.premium_layer_state || 'NO_DATA'
  const ivImpulseStr =
    pre.iv_impulse !== null && pre.iv_impulse !== undefined
      ? `${pre.iv_impulse.toFixed(2)} pts`
      : 'NOT AVAILABLE'

  return {
    heroTitle,
    layerState,
    expansionVal: Math.min(100, pre.premium_expansion_index ?? 0),
    meltVal: Math.min(100, pre.melt_decay_index ?? 0),
    efficiencyVal: Math.min(100, pre.movement_efficiency ?? 0),
    chaseState: pre.chase_exhaustion_state || 'LOW',
    ivImpulseStr,
  }
}

export function computePLICardDisplay(pli: PLIData | null | undefined, pre: PREData | null | undefined) {
  if (!pli) {
    return {
      heroTitle: 'PREMIUM LEAD — NO DATA',
      straddlePriceStr: '₹—',
      straddleChangeStr: '+₹0.0',
      ceLeadVal: 50,
      peLeadVal: 50,
      structure: 'BALANCED',
    }
  }

  const leadStr = pli.lead_side ? pli.lead_side.replaceAll('_', ' ') : 'NO DATA'
  const heroTitle = `PREMIUM LEAD — ${leadStr}`
  const straddlePrice = pre?.atm_straddle_price ?? pli.atm_straddle_price ?? null
  const straddleChange = pre?.straddle_session_change ?? 0.0

  const straddlePriceStr = straddlePrice !== null ? `₹${straddlePrice.toFixed(1)}` : '₹—'
  const straddleChangeStr =
    straddleChange >= 0
      ? `+₹${straddleChange.toFixed(1)}`
      : `-₹${Math.abs(straddleChange).toFixed(1)}`

  return {
    heroTitle,
    straddlePriceStr,
    straddleChangeStr,
    ceLeadVal: Math.min(100, pli.ce_normalized_lead_index ?? 50),
    peLeadVal: Math.min(100, pli.pe_normalized_lead_index ?? 50),
    structure: pli.expansion_structure || 'BALANCED',
  }
}

test('PRE card display transformations for EARLY_EXPANSION & BUYING_FRIENDLY', () => {
  const preMock: PREData = {
    snapshot_id: 'pre_1',
    instrument: 'NIFTY',
    expiry: '2026-08-25',
    atm_strike: 24400,
    source_timestamp: '2026-07-31T15:28:14Z',
    data_state: 'LIVE',
    atm_straddle_price: 210.0,
    straddle_bar_change: 10.0,
    straddle_session_change: 18.0,
    straddle_velocity: 2.5,
    straddle_acceleration: 0.5,
    premium_expansion_index: 78.5,
    premium_compression_index: 21.5,
    melt_decay_index: 15.0,
    iv_impulse: 1.25,
    movement_efficiency: 72.0,
    chase_exhaustion_state: 'LOW',
    regime: 'EARLY_EXPANSION',
    premium_layer_state: 'BUYING_FRIENDLY',
    execution_influence: 'ZERO',
  }

  const display = computePRECardDisplay(preMock)
  assert.equal(display.heroTitle, 'PREMIUM REGIME — EARLY EXPANSION')
  assert.equal(display.layerState, 'BUYING_FRIENDLY')
  assert.equal(display.expansionVal, 78.5)
  assert.equal(display.meltVal, 15.0)
  assert.equal(display.efficiencyVal, 72.0)
  assert.equal(display.ivImpulseStr, '1.25 pts')
})

test('PLI card display transformations for CALL_LEAD & ATM straddle', () => {
  const pliMock: PLIData = {
    snapshot_id: 'pli_1',
    instrument: 'NIFTY',
    expiry: '2026-08-25',
    atm_strike: 24400,
    source_timestamp: '2026-07-31T15:28:14Z',
    atm_ce_symbol: 'NIFTY26AUG24400CE',
    atm_ce_premium: 120.0,
    atm_pe_symbol: 'NIFTY26AUG24400PE',
    atm_pe_premium: 90.0,
    atm_straddle_price: 210.0,
    ce_premium_change: 15.0,
    pe_premium_change: -5.0,
    ce_normalized_lead_index: 75.0,
    pe_normalized_lead_index: 25.0,
    lead_side: 'CALL_LEAD',
    lead_strength: 50.0,
    expansion_structure: 'ONE_SIDED',
    data_quality: 'HIGH',
    execution_influence: 'ZERO',
  }

  const preMock: Partial<PREData> = {
    atm_straddle_price: 210.0,
    straddle_session_change: 18.0,
  }

  const display = computePLICardDisplay(pliMock, preMock as PREData)
  assert.equal(display.heroTitle, 'PREMIUM LEAD — CALL LEAD')
  assert.equal(display.straddlePriceStr, '₹210.0')
  assert.equal(display.straddleChangeStr, '+₹18.0')
  assert.equal(display.ceLeadVal, 75)
  assert.equal(display.peLeadVal, 25)
  assert.equal(display.structure, 'ONE_SIDED')
})

test('Missing IV impulse yields NOT AVAILABLE string without crashing', () => {
  const preMock: PREData = {
    snapshot_id: 'pre_2',
    instrument: 'NIFTY',
    expiry: null,
    atm_strike: null,
    source_timestamp: null,
    data_state: 'NO_DATA',
    atm_straddle_price: null,
    straddle_bar_change: null,
    straddle_session_change: null,
    straddle_velocity: null,
    straddle_acceleration: null,
    premium_expansion_index: 0,
    premium_compression_index: 0,
    melt_decay_index: 0,
    iv_impulse: null,
    movement_efficiency: 0,
    chase_exhaustion_state: 'LOW',
    regime: 'NO_DATA',
    premium_layer_state: 'NO_DATA',
    execution_influence: 'ZERO',
  }

  const display = computePRECardDisplay(preMock)
  assert.equal(display.ivImpulseStr, 'NOT AVAILABLE')
})
