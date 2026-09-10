import test from 'node:test'
import assert from 'node:assert/strict'
import {
  deriveCenterDisplayIdentity,
  deriveCenterDecisionDisplay,
  formatReadableOptionIdentity,
} from '../src/components/institutional/oracleCenterIdentityHelpers'

test('CASE 1 — CURRENT NIFTY CALL', () => {
  const identity = deriveCenterDisplayIdentity({
    chartState: {
      symbol: {
        raw_symbol: 'NSE:NIFTY260811C24500',
        normalized_symbol: 'NIFTY260811C24500',
        exchange: 'NSE',
        route: 'EXACT_OPTION',
      },
      option: {
        underlying: 'NIFTY',
        strike: 24500,
        option_side: 'CE',
        expiry: '2026-08-11',
        trading_symbol: 'NIFTY260811C24500',
      },
      timeframe: '5m',
      availability: 'AVAILABLE',
      freshness: 'FRESH',
    },
    exactOption: null,
  })

  assert.equal(identity.title, 'NIFTY 24,500 CALL')
  assert.equal(identity.subtitle, '11 AUG 2026 · 5m')
  assert.equal(identity.technicalFooter, 'NIFTY260811C24500')
})

test('CASE 2 — NIFTY PUT', () => {
  const identity = deriveCenterDisplayIdentity({
    chartState: {
      symbol: {
        raw_symbol: 'NSE:NIFTY260811P24600',
        normalized_symbol: 'NIFTY260811P24600',
        exchange: 'NSE',
        route: 'EXACT_OPTION',
      },
      option: {
        underlying: 'NIFTY',
        strike: 24600,
        option_side: 'PE',
        expiry: '2026-08-11',
        trading_symbol: 'NIFTY260811P24600',
      },
      timeframe: '5m',
      availability: 'AVAILABLE',
      freshness: 'FRESH',
    },
    exactOption: null,
  })

  assert.equal(identity.title, 'NIFTY 24,600 PUT')
  assert.equal(identity.subtitle, '11 AUG 2026 · 5m')
  assert.equal(identity.technicalFooter, 'NIFTY260811P24600')
})

test('CASE 3 — BANKNIFTY CALL', () => {
  const identity = deriveCenterDisplayIdentity({
    chartState: {
      symbol: {
        raw_symbol: 'NSE:BANKNIFTY260811C55000',
        normalized_symbol: 'BANKNIFTY260811C55000',
        exchange: 'NSE',
        route: 'EXACT_OPTION',
      },
      option: {
        underlying: 'BANKNIFTY',
        strike: 55000,
        option_side: 'CALL',
        expiry: '2026-08-11',
      },
      timeframe: '5m',
      availability: 'AVAILABLE',
    },
  })

  assert.equal(identity.title, 'BANKNIFTY 55,000 CALL')
})

test('CASE 4 — SENSEX PUT', () => {
  const identity = deriveCenterDisplayIdentity({
    chartState: {
      symbol: {
        raw_symbol: 'BSE:SENSEX260811P79500',
        normalized_symbol: 'SENSEX260811P79500',
        exchange: 'BSE',
        route: 'EXACT_OPTION',
      },
      option: {
        underlying: 'SENSEX',
        strike: 79500,
        option_side: 'PUT',
        expiry: '2026-08-11',
      },
      timeframe: '5m',
      availability: 'AVAILABLE',
    },
  })

  assert.equal(identity.title, 'SENSEX 79,500 PUT')
  assert.equal(identity.subtitle, '11 AUG 2026 · 5m')
})

test('CASE 5 — MONTHLY EXPIRY', () => {
  const identity = deriveCenterDisplayIdentity({
    chartState: {
      symbol: {
        raw_symbol: 'NSE:NIFTY26AUG24500CE',
        normalized_symbol: 'NIFTY26AUG24500CE',
        exchange: 'NSE',
        route: 'EXACT_OPTION',
      },
      option: {
        underlying: 'NIFTY',
        strike: 24500,
        option_side: 'CE',
        expiry: '2026-08-27',
      },
      timeframe: '5m',
      availability: 'AVAILABLE',
    },
  })

  assert.equal(identity.title, 'NIFTY 24,500 CALL')
  assert.equal(identity.subtitle, '27 AUG 2026 · 5m')
})

test('CASE 6 — UNDERLYING INDEX', () => {
  const identity = deriveCenterDisplayIdentity({
    chartState: {
      symbol: {
        raw_symbol: 'NSE:NIFTY',
        normalized_symbol: 'NIFTY',
        exchange: 'NSE',
        route: 'UNDERLYING_INDEX',
      },
      timeframe: '5m',
      availability: 'AVAILABLE',
      freshness: 'FRESH',
    },
    exactOption: null,
  })

  assert.equal(identity.title, 'NIFTY')
  assert.equal(identity.subtitle, 'UNDERLYING INDEX · 5m')
  assert.equal(identity.technicalFooter, 'NIFTY')
})

test('CASE 7 — PARTIAL STRUCTURED METADATA WITH VERIFIED RAW FALLBACK', () => {
  const formatted = formatReadableOptionIdentity({
    rawSymbol: 'NIFTY260811C24500',
    timeframe: '5m',
  })

  assert.equal(formatted.humanTitle, 'NIFTY 24,500 CALL')
  assert.equal(formatted.humanSubtitle, '11 AUG 2026 · 5m')
  assert.equal(formatted.confidence, 'HIGH')
  assert.equal(formatted.source, 'RAW_FALLBACK_PARSER')
})

test('CASE 8 — AMBIGUOUS OR MALFORMED RAW SYMBOL', () => {
  const formatted = formatReadableOptionIdentity({
    rawSymbol: 'UNKNOWN_XYZ_999',
    timeframe: '5m',
  })

  assert.equal(formatted.humanTitle, 'UNKNOWN_XYZ_999')
  assert.equal(formatted.humanSubtitle, 'OPTION DETAILS UNAVAILABLE · 5m')
  assert.equal(formatted.confidence, 'LOW')
})

test('CASE 9 — IDENTITY SWITCH', () => {
  // Step A: NIFTY underlying
  let identity = deriveCenterDisplayIdentity({
    chartState: { symbol: { normalized_symbol: 'NIFTY', route: 'UNDERLYING_INDEX' }, timeframe: '5m', availability: 'AVAILABLE' },
  })
  assert.equal(identity.title, 'NIFTY')
  assert.equal(identity.subtitle, 'UNDERLYING INDEX · 5m')

  // Step B: NIFTY CALL
  identity = deriveCenterDisplayIdentity({
    chartState: {
      symbol: { normalized_symbol: 'NIFTY260811C24500', route: 'EXACT_OPTION' },
      option: { underlying: 'NIFTY', strike: 24500, option_side: 'CE', expiry: '2026-08-11' },
      timeframe: '5m', availability: 'AVAILABLE',
    },
  })
  assert.equal(identity.title, 'NIFTY 24,500 CALL')
  assert.equal(identity.subtitle, '11 AUG 2026 · 5m')

  // Step C: NIFTY PUT
  identity = deriveCenterDisplayIdentity({
    chartState: {
      symbol: { normalized_symbol: 'NIFTY260811P24600', route: 'EXACT_OPTION' },
      option: { underlying: 'NIFTY', strike: 24600, option_side: 'PE', expiry: '2026-08-11' },
      timeframe: '5m', availability: 'AVAILABLE',
    },
  })
  assert.equal(identity.title, 'NIFTY 24,600 PUT')
  assert.equal(identity.subtitle, '11 AUG 2026 · 5m')

  // Step D: Back to NIFTY underlying (no contract leakage)
  identity = deriveCenterDisplayIdentity({
    chartState: { symbol: { normalized_symbol: 'NIFTY', route: 'UNDERLYING_INDEX' }, timeframe: '5m', availability: 'AVAILABLE' },
  })
  assert.equal(identity.title, 'NIFTY')
  assert.equal(identity.subtitle, 'UNDERLYING INDEX · 5m')
})

test('CASE 10 — CURRENT-EPOCH PROTECTION', () => {
  const chartState = {
    symbol: { normalized_symbol: 'NIFTY260811P24600', route: 'EXACT_OPTION' },
    option: { underlying: 'NIFTY', strike: 24600, option_side: 'PE', expiry: '2026-08-11' },
    timeframe: '5m',
    availability: 'AVAILABLE',
  }

  // Stale exactOption from previous epoch (CALL) must not override chartState.option (PUT)
  const staleExactOption = {
    exact_contract: { underlying: 'NIFTY', strike: 24500, option_side: 'CALL', expiry: '2026-08-11' },
  }

  const identity = deriveCenterDisplayIdentity({
    chartState,
    exactOption: staleExactOption,
  })

  assert.equal(identity.title, 'NIFTY 24,600 PUT')
})
