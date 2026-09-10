import assert from 'node:assert/strict'
import test from 'node:test'

// @ts-expect-error Node's type-stripping test runner requires the explicit TypeScript extension.
import { buildVobAxisGeometry } from '../src/components/institutional/vobAxisGeometry.ts'

const support = { zone_low: 100, zone_high: 110 }
const resistance = { zone_low: 190, zone_high: 200 }

test('main marker moves with authoritative spot and never defaults to the centre', () => {
  const first = buildVobAxisGeometry(125, support, resistance)
  const second = buildVobAxisGeometry(160, support, resistance)
  assert.ok(first && second)
  assert.notEqual(first.spot, second.spot)
  assert.notEqual(first.spot, 50)
})

test('the same spot maps independently for different timeframe structures', () => {
  const shortStructure = buildVobAxisGeometry(150, support, resistance)
  const wideStructure = buildVobAxisGeometry(150, { zone_low: 50, zone_high: 80 }, { zone_low: 260, zone_high: 300 })
  assert.ok(shortStructure && wideStructure)
  assert.notEqual(shortStructure.spot, wideStructure.spot)
})

test('spot enters the exact support and resistance visual bands', () => {
  const insideSupport = buildVobAxisGeometry(105, support, resistance)
  const insideResistance = buildVobAxisGeometry(195, support, resistance)
  assert.ok(insideSupport && insideResistance)
  assert.ok(insideSupport.spot >= insideSupport.supportStart)
  assert.ok(insideSupport.spot <= insideSupport.supportStart + insideSupport.supportWidth)
  assert.ok(insideResistance.spot >= insideResistance.resistanceStart)
  assert.ok(insideResistance.spot <= insideResistance.resistanceStart + insideResistance.resistanceWidth)
})

test('prices beyond the structure clamp safely without NaN or overflow', () => {
  const below = buildVobAxisGeometry(-10_000, support, resistance)
  const above = buildVobAxisGeometry(10_000, support, resistance)
  assert.ok(below && above)
  assert.equal(below.spot, 0)
  assert.equal(above.spot, 100)
  assert.ok(Number.isFinite(below.spot) && Number.isFinite(above.spot))
})

test('invalid or incomplete structures do not fabricate an axis', () => {
  assert.equal(buildVobAxisGeometry(150, support, null), null)
  assert.equal(buildVobAxisGeometry(Number.NaN, support, resistance), null)
  assert.equal(buildVobAxisGeometry(150, { zone_low: 150, zone_high: 200 }, { zone_low: 190, zone_high: 210 }), null)
})
