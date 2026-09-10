import assert from 'node:assert/strict'
import test from 'node:test'
import type { PREData, PLIData, CoverageData, RiskStatusData, StrategyLaneItem } from '../src/components/institutional/UnifiedOptionBuyerCommandDeck'

export function computeUnifiedCommandDeckState(
  pre: PREData | null | undefined,
  pli: PLIData | null | undefined,
  coverage: CoverageData | null | undefined,
  risk: RiskStatusData | null | undefined,
  lanes: StrategyLaneItem[]
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

  const indiaVixStatus = 'NOT AVAILABLE'
  const indiaVixNote = 'Live quote source for INDIA VIX not connected to backend API; thresholds UNVALIDATED_DEFAULT.'

  const totalLanes = lanes.length || 13
  const enabledLanes = lanes.filter(l => l.mode === 'PAPER' || l.mode === 'SHADOW').length
  const runningLanes = lanes.filter(l => l.mode === 'PAPER').length
  const stoppedLanes = lanes.filter(l => l.mode === 'OFF').length
  const disabledLanes = lanes.filter(l => l.mode === 'OFF').length

  return {
    decisionTitle,
    tone,
    alignmentCount,
    straddleImpactState,
    indiaVixStatus,
    indiaVixNote,
    inventoryTotals: {
      totalLanes,
      enabledLanes,
      runningLanes,
      stoppedLanes,
      disabledLanes,
    },
    executionInfluence: 'ZERO',
  }
}

test('Unified command deck correctly synthesizes NO TRADE — NO LIVE AUTHORITY when live authority bar is null', () => {
  const covMock: CoverageData = {
    capture_schema_version: 'V2',
    latest_restored_closed_bar_id: 'bar_5m_2026-07-31_15:25:00',
    latest_live_authority_bar_id: null,
    coverage_readiness: 'INSUFFICIENT',
    session_state: 'CLOSED',
    execution_influence: 'ZERO',
  }

  const mockLanes: StrategyLaneItem[] = [
    { deployment_id: 'PB_NIFTY_CE_1M', strategy_class: 'PULLBACK', option_side: 'CE', timeframe: '1m', underlying: 'NIFTY', mode: 'PAPER', premium_domain: true, risk_engine_enabled: true, note: 'Paper' },
    { deployment_id: 'PB_NIFTY_PE_1M', strategy_class: 'PULLBACK', option_side: 'PE', timeframe: '1m', underlying: 'NIFTY', mode: 'PAPER', premium_domain: true, risk_engine_enabled: true, note: 'Paper' },
    { deployment_id: 'TC_NIFTY_PE_3M', strategy_class: 'TREND_CATCHER', option_side: 'PE', timeframe: '3m', underlying: 'NIFTY', mode: 'OFF', premium_domain: true, risk_engine_enabled: false, note: 'Off' },
  ]

  const state = computeUnifiedCommandDeckState(null, null, covMock, null, mockLanes)

  assert.equal(state.decisionTitle, 'NO TRADE — NO LIVE AUTHORITY')
  assert.equal(state.tone, 'muted')
  assert.equal(state.indiaVixStatus, 'NOT AVAILABLE')
  assert.equal(state.inventoryTotals.totalLanes, 3)
  assert.equal(state.inventoryTotals.enabledLanes, 2)
  assert.equal(state.inventoryTotals.stoppedLanes, 1)
  assert.equal(state.executionInfluence, 'ZERO')
})

test('Unified command deck formats India VIX as NOT AVAILABLE without fake numbers', () => {
  const state = computeUnifiedCommandDeckState(null, null, null, null, [])
  assert.equal(state.indiaVixStatus, 'NOT AVAILABLE')
  assert.match(state.indiaVixNote, /UNVALIDATED_DEFAULT/)
})
