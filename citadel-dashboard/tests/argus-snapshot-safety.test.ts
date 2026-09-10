import assert from 'node:assert/strict'
import test from 'node:test'
import { safeArgusSnapshot, safeArgusStatus, safeBaselineLabel } from '../src/app/argus-safety-helpers'

test('ARGUS safety: handles null or undefined data without throwing', () => {
  // Test null/undefined data input
  const resNull = safeArgusSnapshot(null as any)
  assert.equal(resNull.isValid, false)
  assert.equal(resNull.snapshot, null)

  const resUndefined = safeArgusSnapshot(undefined as any)
  assert.equal(resUndefined.isValid, false)
  assert.equal(resUndefined.snapshot, null)

  const resEmptyObj = safeArgusSnapshot({} as any)
  assert.equal(resEmptyObj.isValid, false)
  assert.equal(resEmptyObj.snapshot, null)
})

test('ARGUS safety: handles snapshot missing verdict or underlying without throwing', () => {
  const missingVerdict = {
    data: {
      underlying: { ltp: 24500, expiry: '2026-08-07', atm_strike: 24500, fetched_at: '2026-08-06T15:30:00Z', market_state: 'CLOSED', baseline_timestamp: null, baseline_status: 'UNAVAILABLE' }
    }
  } as any

  const resMissingVerdict = safeArgusSnapshot(missingVerdict)
  assert.equal(resMissingVerdict.isValid, false)

  const status = safeArgusStatus(missingVerdict, null)
  assert.equal(status, 'Closed') // underlying is present

  const baseline = safeBaselineLabel(missingVerdict.data.underlying)
  assert.equal(baseline, 'Intraday baseline unavailable')
})

test('ARGUS safety: preserves valid complete ARGUS snapshot and verdict bias', () => {
  const validData = {
    freshness: 'live',
    data: {
      underlying: { ltp: 24500, expiry: '2026-08-07', atm_strike: 24500, fetched_at: '2026-08-06T15:30:00Z', market_state: 'OPEN', baseline_timestamp: '2026-08-06T03:45:00Z', baseline_status: 'AVAILABLE' },
      verdict: { bias: 'BULLISH', regime: 'writer_dominated', preferred_option_side: 'CE', confidence: 85, breakout_above: 24600, breakdown_below: 24400, avoid_zone: null, reasons: ['Strong CE unwind'] },
      dominance: { writer_dominance_percentage: 60, buyer_dominance_percentage: 40 },
      walls: { highest_ce_oi: { strike: 25000 }, highest_pe_oi: { strike: 24000 } }
    }
  } as any

  const resValid = safeArgusSnapshot(validData)
  assert.equal(resValid.isValid, true)
  assert.equal(resValid.snapshot?.verdict?.bias, 'BULLISH')

  const status = safeArgusStatus(validData, null)
  assert.equal(status, 'Live')

  const baseline = safeBaselineLabel(validData.data.underlying)
  assert.equal(baseline, 'Intraday baseline: 09:15 IST')
})

test('ARGUS safety: error or missing snapshot returns honest UNAVAILABLE/Stale state without fabricating values', () => {
  const errorData = safeArgusStatus({} as any, 'Network Error')
  assert.equal(errorData, 'Stale')

  const emptyBaseline = safeBaselineLabel(null as any)
  assert.equal(emptyBaseline, 'Unavailable')
})
