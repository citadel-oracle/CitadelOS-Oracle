import { describe, expect, it } from 'vitest'

import type { OracleOptionDisplay } from '@/dashboard/store/oracleStore'

import {
  acceptSemanticEvent,
  auraTone,
  formatDisplayTradeId,
  magnetGeometry,
  pnlTone,
  proximityLabel,
  readBooleanPreference,
  semanticAlert,
  trackATradeAlert,
  writeBooleanPreference,
  type SemanticFrame,
} from './vobPresentation'

const option = (override: Partial<OracleOptionDisplay> = {}): OracleOptionDisplay => ({
  contract: { securityId: '45098', tradingSymbol: null, expiry: null, strike: 24_200, optionType: 'CE', lotSize: 65, source: 'DHAN' },
  contractStatus: 'FROZEN_EPISODE', quoteSecurityId: '45098', vobSecurityId: '45098', premium: 151.4, bid: 151.2, ask: 151.6,
  quoteTimestamp: '2026-08-14T10:00:00+05:30', freshness: 'FRESH', quoteSource: 'ARGUS_DHAN_OPTION_CHAIN',
  vobTimeframe: '3M', zoneTop: 153, zoneBottom: 148, zoneState: 'TESTED', zoneRole: 'SUPPORT', zoneSource: 'OSE', zonePrimary: true,
  distancePoints: 0, distancePct: 0, insideZone: true, nearestZoneBoundary: 153, relation: 'INSIDE',
  ...override,
})

const frame = (override: Partial<SemanticFrame> = {}): SemanticFrame => ({
  episodeId: 'episode-a', revision: 10, reversalState: 'WATCHING', vobState: 'TESTED', direction: 'CALL',
  contract: '24,200 CE', premium: 151.4, timeframe: '3M', entryTime: null, exitTime: null, exitReason: null, pnl: null,
  ...override,
})

describe('VOB presentation-only semantics', () => {
  it('uses hard P&L tones', () => {
    expect(pnlTone(12)).toBe('positive')
    expect(pnlTone(-0.01)).toBe('negative')
    expect(pnlTone(0)).toBe('neutral')
    expect(pnlTone(null)).toBe('neutral')
  })

  it('maps backend semantic states and real P&L to aura tones', () => {
    expect(auraTone(frame())).toBe('watching')
    expect(auraTone(frame({ reversalState: 'REVERSAL_BUILDING' }))).toBe('building')
    expect(auraTone(frame({ reversalState: 'REVERSAL_READY' }))).toBe('ready')
    expect(auraTone(frame({ entryTime: '2026-08-14T10:01:00+05:30', pnl: 3 }))).toBe('positive')
    expect(auraTone(frame({ entryTime: '2026-08-14T10:01:00+05:30', pnl: -3 }))).toBe('negative')
    expect(auraTone(frame({ exitTime: '2026-08-14T10:02:00+05:30', exitReason: 'TARGET_HIT' }))).toBe('target')
  })

  it('reports exact backend VOB proximity without inventing values', () => {
    expect(proximityLabel(option())).toBe('INSIDE VOB')
    expect(proximityLabel(option({ insideZone: false, relation: 'TOUCHING' }))).toBe('TOUCHING VOB')
    expect(proximityLabel(option({ insideZone: false, relation: 'ABOVE', distancePoints: 2.35 }))).toBe('2.35 pts ABOVE VOB')
    expect(proximityLabel(option({ insideZone: false, relation: 'BELOW', distancePoints: 1.2 }))).toBe('1.20 pts BELOW VOB')
    expect(proximityLabel(option({ premium: null, distancePoints: null, insideZone: null, relation: 'UNKNOWN' }))).toBe('UNKNOWN')
  })

  it('creates only display geometry from exact premium and zone bounds', () => {
    const geometry = magnetGeometry(option())
    expect(geometry).not.toBeNull()
    expect(geometry!.pricePct).toBeGreaterThanOrEqual(geometry!.zoneStartPct)
    expect(geometry!.pricePct).toBeLessThanOrEqual(geometry!.zoneEndPct)
    expect(magnetGeometry(option({ premium: null }))).toBeNull()
  })

  it('emits one ready alert for a semantic transition, not repeated revisions', () => {
    const ready = frame({ revision: 11, reversalState: 'REVERSAL_READY' })
    const event = semanticAlert(frame(), ready)
    const seen = new Set<string>()
    expect(event?.kind).toBe('READY')
    expect(acceptSemanticEvent(seen, event)).toBe(true)
    expect(acceptSemanticEvent(seen, event)).toBe(false)
    expect(semanticAlert(ready, frame({ revision: 12, reversalState: 'REVERSAL_READY' }))).toBeNull()
  })

  it('emits entry, target, and stop only from backend lifecycle fields', () => {
    expect(semanticAlert(frame(), frame({ revision: 11, entryTime: '2026-08-14T10:01:00+05:30' }))?.kind).toBe('ENTRY')
    expect(semanticAlert(frame(), frame({ revision: 12, exitTime: '2026-08-14T10:02:00+05:30', exitReason: 'TARGET_HIT' }))?.kind).toBe('TARGET')
    expect(semanticAlert(frame(), frame({ revision: 13, exitTime: '2026-08-14T10:02:00+05:30', exitReason: 'STOP_HIT' }))?.kind).toBe('STOP')
  })

  it('deduplicates Track-A entry and exit alerts from real lifecycle timestamps', () => {
    const eligible = { tradeId: 'track-a-1', contract: 'NIFTY 24100 CE', timeframe: '3M', entryTime: null, exitTime: null, exitReason: null, pnl: null }
    const entered = { ...eligible, entryTime: '2026-08-18T11:15:00+05:30' }
    const exited = { ...entered, exitTime: '2026-08-18T11:35:00+05:30', exitReason: 'TARGET_HIT', pnl: 312.5 }
    const seen = new Set<string>()
    const entry = trackATradeAlert(eligible, entered)
    expect(entry?.kind).toBe('ENTRY')
    expect(acceptSemanticEvent(seen, entry)).toBe(true)
    expect(acceptSemanticEvent(seen, entry)).toBe(false)
    expect(trackATradeAlert(entered, exited)?.kind).toBe('TARGET')
  })

  it('persists explicit alert and sound preferences', () => {
    const values = new Map<string, string>()
    const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) } }
    expect(readBooleanPreference(storage, 'sound')).toBe(false)
    writeBooleanPreference(storage, 'sound', true)
    expect(readBooleanPreference(storage, 'sound')).toBe(true)
  })

  it('generates stable deterministic display trade IDs (T-TF-XXX) from canonical trade identities', () => {
    const id1m = formatDisplayTradeId('vobep_666c01_1m_VOB_ONLY', '1M')
    const id3m = formatDisplayTradeId('vobep_666c01_3m_CONFIRMED_REVERSAL', '3M')
    const id5m = formatDisplayTradeId('vobep_666c01_5m_VOB_ONLY', '5M')
    const id5mConfirmed = formatDisplayTradeId('vobep_666c01_5m_CONFIRMED_REVERSAL', '5M')

    expect(id1m).toMatch(/^T-1M-\d{3}$/)
    expect(id3m).toMatch(/^T-3M-\d{3}$/)
    expect(id5m).toMatch(/^T-5M-\d{3}$/)
    expect(id5mConfirmed).toMatch(/^T-5M-\d{3}$/)

    // Deterministic repeatability across calls/rerenders
    expect(formatDisplayTradeId('vobep_666c01_1m_VOB_ONLY', '1M')).toBe(id1m)
    expect(formatDisplayTradeId('vobep_666c01_5m_CONFIRMED_REVERSAL', '5M')).toBe(id5mConfirmed)

    // Distinct variants within same episode generate distinct display IDs
    expect(id5m).not.toBe(id5mConfirmed)
  })
})
