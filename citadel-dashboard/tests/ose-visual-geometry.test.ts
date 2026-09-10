import assert from 'node:assert/strict'
import test from 'node:test'

// @ts-expect-error Node's type-stripping test runner requires the explicit TypeScript extension.
import { duelMarkerPosition, energyDashOffset, flowMarkerPosition, latestLifecycleSummary, precisionArcPath, precisionTick, precisionWheelNeedle, trendInstrumentNeedle, trendRingNeedle, wheelNeedle, wheelPosition } from '../src/components/institutional/oseVisualGeometry.ts'

test('wheel maps all five directional states to deterministic intensity positions', () => {
  assert.deepEqual(
    ['ULTRA BEARISH', 'BEARISH', 'NEUTRAL', 'BULLISH', 'ULTRA BULLISH'].map(wheelPosition),
    [8, 29, 50, 71, 92],
  )
  assert.equal(wheelPosition('NEUTRAL / MIXED'), 50)
  assert.equal(wheelNeedle('ULTRA BULLISH').position, 92)
  assert.equal(trendRingNeedle('ULTRA BEARISH').position, 8)
  assert.notDeepEqual(trendRingNeedle('BULLISH'), wheelNeedle('BULLISH'))
})

test('flow rail uses the same deterministic two-sided score geometry', () => {
  assert.equal(flowMarkerPosition(50, 50), 50)
  assert.ok(flowMarkerPosition(24, 86) > 75)
  assert.ok(flowMarkerPosition(90, 20) < 25)
})

test('precision wheel uses the same five-state geometry across all concentric layers', () => {
  assert.equal(precisionWheelNeedle('ULTRA BEARISH').position, 8)
  assert.equal(precisionWheelNeedle('ULTRA BULLISH').position, 92)
  assert.match(precisionArcPath(3, 97, 106), /^M/)
  assert.notDeepEqual(precisionTick(0, true), precisionTick(50, true))
})

test('trend energy geometry is deterministic and independent from the semicircle', () => {
  assert.equal(trendInstrumentNeedle('NEUTRAL').position, 50)
  assert.equal(energyDashOffset('ULTRA BULLISH'), 8)
  assert.equal(energyDashOffset('ULTRA BEARISH'), 92)
  assert.notDeepEqual(trendInstrumentNeedle('BULLISH'), precisionWheelNeedle('BULLISH'))
})

test('duel marker is the normalized score balance and points toward the stronger contract', () => {
  assert.equal(duelMarkerPosition(50, 50), 50)
  assert.equal(duelMarkerPosition(0, 0), 50)
  assert.ok(Math.abs(duelMarkerPosition(21, 78) - 78.787878) < 0.0001)
  assert.ok(duelMarkerPosition(84, 31) < 50)
})

test('latest lifecycle summary renders only explicit backend lifecycle flags', () => {
  assert.equal(latestLifecycleSummary({ supply_break: true, demand_break: false, bullish_retest: true, bearish_retest: false }), 'Latest: Supply broken → bullish retest held')
  assert.equal(latestLifecycleSummary({ supply_break: false, demand_break: true, bullish_retest: false, bearish_retest: true }), 'Latest: Demand broken → bearish continuation')
  assert.equal(latestLifecycleSummary({ supply_break: false, demand_break: false, bullish_retest: false, bearish_retest: false }), 'Latest: No confirmed break')
})
