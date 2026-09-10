import { describe, expect, it } from 'vitest'

import type { DashboardSourceSnapshot } from '../types'
import { createOracleStore } from './oracleStore'

type SnapshotOptions = {
  revision?: number
  episodeId?: string
  securityId?: string
  reversalState?: string
  evidenceKnown?: boolean
  underlying?: number
  pnl?: number | null
  callPrice?: number | null
  putPrice?: number | null
  currentCallPrice?: number | null
  currentPutPrice?: number | null
  atmStrike?: number
  currentCeId?: string
  currentPeId?: string
}

function snapshot({
  revision = 1,
  episodeId = 'episode-a',
  securityId = '45098',
  reversalState = 'WATCHING',
  evidenceKnown = false,
  underlying = 24_300,
  pnl = null,
  callPrice = 151.4,
  putPrice = 126.2,
  currentCallPrice = 159.25,
  currentPutPrice = 74.3,
  atmStrike = 24_350,
  currentCeId = '45102',
  currentPeId = '45107',
}: SnapshotOptions = {}): DashboardSourceSnapshot {
  const evidence = {
    failed_aggression: {
      state: evidenceKnown ? 'PRESENT' : 'UNKNOWN', revision: 'flow-1',
      event_time: '2026-08-14T10:00:00+05:30', receive_time: null,
      persistence: evidenceKnown ? 2 : 0, persistence_state: evidenceKnown ? 'REVERSAL_FORMING' : 'UNPROVEN',
      quality: evidenceKnown ? 'AVAILABLE' : 'UNKNOWN', known: evidenceKnown,
    },
  }
  return {
    schemaVersion: 1,
    provider: 'rest',
    traceId: `trace-${revision}`,
    generatedAt: '2026-08-14T10:00:01+05:30',
    selectedSymbol: 'NIFTY',
    feeds: {
      oracle: { symbol: 'NIFTY', data_status: 'LIVE', input_features: { close: underlying, session_status: 'OPEN' } },
      options_structure: {
        contracts: {
          CE: {
            contract: { security_id: '45098', option_type: 'CE', strike: 24_200 },
            structures: {
              '1m': { demand: { zone_low: 149, zone_high: 152, status: 'ACTIVE', role: 'SUPPORT' } },
              '3m': { demand: { zone_low: 148, zone_high: 153, status: 'TESTED', role: 'SUPPORT', last_tested_time: '2026-08-14T10:00:00+05:30' } },
              '5m': { demand: { zone_low: 146, zone_high: 154, status: 'ACTIVE', role: 'SUPPORT' } },
            },
          },
          PE: { contract: { security_id: '45111', option_type: 'PE', strike: 24_500 } },
        },
      },
      vob_reversal: {
        schema_version: 4, revision, episode_id: episodeId, direction: 'CALL', timeframe: '3m',
        vob_state: 'TESTED', reversal_state: reversalState, quality: evidenceKnown ? 'AVAILABLE' : 'UNKNOWN',
        episode: {
          episode_id: episodeId, vob_revision: `ose-${revision}`, source_engine: 'OPTIONS_STRUCTURE_ENGINE_V1', source_zone_id: 'zone-a',
          symbol: 'NIFTY 18 AUG 24200 CE', direction: 'CALL', timeframe: '3m', zone_top: 153, zone_bottom: 148,
          created_at: '2026-08-14T09:59:00+05:30', approach_at: '2026-08-14T09:59:30+05:30', touch_at: '2026-08-14T10:00:00+05:30',
          primary_role: 'SUPPORT', primary_reason: 'NEAREST_SUPPORT', vob_state: 'TESTED', evidence_revision: revision,
          contract_identity: { security_id: securityId, trading_symbol: 'NIFTY 18 AUG 24200 CE', expiry: '2026-08-18', strike: 24_200, option_type: 'CE', lot_size: 65, source: 'DHAN_INSTRUMENT_MASTER' },
          contract_frozen_at: '2026-08-14T09:59:00+05:30',
        },
        evidence,
        entry_ref: null, sl_ref: null, target_ref: null,
        authority: { entry_sl_target_one_use_trail: 'PULLBACK_MASTER' },
        canonical_market: {
          reference_price: underlying, atm_strike: atmStrike, strike_interval: 50,
          source: 'ARGUS_OPTION_CHAIN_RESOLVER', source_timestamp: '2026-08-14T10:00:00+05:30',
        },
        current_itm1_contracts: {
          CE: {
            contract: { security_id: currentCeId, option_type: 'CE', strike: atmStrike - 50, expiry: '2026-08-18', source: 'ARGUS_OPTION_CHAIN_RESOLVER' },
            quote: { security_id: currentCeId, option_type: 'CE', strike: atmStrike - 50, ltp: currentCallPrice, bid: currentCallPrice === null ? null : currentCallPrice - 0.05, ask: currentCallPrice === null ? null : currentCallPrice + 0.75, timestamp: '2026-08-14T10:00:00+05:30', source: 'ARGUS_DHAN_OPTION_CHAIN' },
          },
          PE: {
            contract: { security_id: currentPeId, option_type: 'PE', strike: atmStrike + 50, expiry: '2026-08-18', source: 'ARGUS_OPTION_CHAIN_RESOLVER' },
            quote: { security_id: currentPeId, option_type: 'PE', strike: atmStrike + 50, ltp: currentPutPrice, bid: currentPutPrice === null ? null : currentPutPrice, ask: currentPutPrice === null ? null : currentPutPrice + 0.25, timestamp: '2026-08-14T10:00:00+05:30', source: 'ARGUS_DHAN_OPTION_CHAIN' },
          },
        },
        option_contracts: {
          CE: {
            contract: { security_id: securityId, option_type: 'CE', strike: 24_200, trading_symbol: 'NIFTY 18 AUG 24200 CE' },
            contract_status: 'FROZEN_EPISODE',
            quote: { security_id: securityId, ltp: callPrice, bid: callPrice === null ? null : callPrice - 0.2, ask: callPrice === null ? null : callPrice + 0.2, timestamp: '2026-08-14T10:00:00+05:30', freshness: 'FRESH', source: 'ARGUS_DHAN_OPTION_CHAIN' },
            vob: { timeframe: '3m', zone_bottom: 148, zone_top: 153, state: 'TESTED', role: 'SUPPORT', source: 'OSE', primary: true },
            distance: { distance_to_zone_points: 0, distance_to_zone_pct: 0, inside_zone: true, nearest_zone_boundary: 153, relation: 'INSIDE' },
          },
          PE: {
            contract: { security_id: '45111', option_type: 'PE', strike: 24_500, trading_symbol: 'NIFTY 18 AUG 24500 PE' },
            contract_status: 'FROZEN_EPISODE',
            quote: { security_id: '45111', ltp: putPrice, bid: putPrice === null ? null : putPrice - 0.2, ask: putPrice === null ? null : putPrice + 0.2, timestamp: '2026-08-14T10:00:00+05:30', freshness: 'FRESH', source: 'ARGUS_DHAN_OPTION_CHAIN' },
            vob: { timeframe: '5m', zone_bottom: 120, zone_top: 124, state: 'ACTIVE', role: 'SUPPORT', source: 'OSE', primary: false },
            distance: { distance_to_zone_points: 2.2, distance_to_zone_pct: 1.743265, inside_zone: false, nearest_zone_boundary: 124, relation: 'ABOVE' },
          },
        },
        shadow: {
          VOB_ONLY: { contract_security_id: securityId, entry_ask: 150, current_bid: 154, pnl, r: 0.4, mfe: 8, mae: 2, post_hoc: false },
          EARLY_REVERSAL: null,
          CONFIRMED_REVERSAL: { contract_security_id: securityId, entry_ask: 152, current_bid: 154, pnl, r: 0.2, mfe: 5, mae: 1, post_hoc: false },
        },
      },
    },
    feedMeta: {
      vob_reversal: { health: 'HEALTHY', readiness: 'READY', latency_ms: 2.1, last_updated: '2026-08-14T10:00:01+05:30', source_last_updated: '2026-08-14T10:00:00+05:30', freshness: 'FRESH' },
    },
  } as unknown as DashboardSourceSnapshot
}

describe('oracle VOB command store', () => {
  it('accepts only newer VOB revisions and counts stale rejections', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ revision: 10 }))
    store.getState().ingestSnapshot(snapshot({ revision: 9, reversalState: 'REVERSAL_READY' }))
    expect(store.getState().runtime.revision).toBe(10)
    expect(store.getState().runtime.ignoredStaleRevisions).toBe(1)
    expect(store.getState().reversal.state).toBe('WATCHING')
  })

  it('preserves canonical UNKNOWN evidence without inventing a display value', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ evidenceKnown: false }))
    expect(store.getState().reversal.evidence.failed_aggression).toMatchObject({ state: 'UNKNOWN', known: false })
    expect(store.getState().reversal.displayScores).toEqual({ vobSetup: null, turnStrength: null, marketSupport: null, overall: null })
  })

  it('reports MARKET_CLOSED from canonical ARGUS when the legacy Oracle session is unavailable', () => {
    const store = createOracleStore()
    const next = snapshot()
    const oracle = next.feeds.oracle as Record<string, unknown>
    oracle.data_status = 'UNAVAILABLE'
    oracle.input_features = { close: 24_300, session_status: 'UNAVAILABLE' }
    next.feeds.argus = { data: { data: { underlying: { market_state: 'CLOSED' } } } }
    store.getState().ingestSnapshot(next)
    expect(store.getState().market.marketStatus).toBe('MARKET_CLOSED')
    expect(store.getState().market.dataFreshness).toBe('MARKET_CLOSED')
  })

  it('uses canonical Fast Lane freshness when the empty legacy Oracle snapshot is unavailable', () => {
    const store = createOracleStore()
    const next = snapshot() as any
    next.feeds.oracle.data_status = 'UNAVAILABLE'
    next.feeds.vob_reversal = {
      ok: true,
      data: next.feeds.vob_reversal,
      meta: { freshness: 'FRESH' },
    }
    store.getState().ingestSnapshot(next)
    expect(store.getState().market.dataFreshness).toBe('FRESH')
  })

  it('retains truthful timeframe lineage and exact PRIMARY episode source', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot())
    const [one, three, five] = store.getState().vob.levels
    expect(one.sourceLineage).toEqual(['PULLBACK'])
    expect(one).toMatchObject({ reportedSource: 'OSE', zoneBottom: 149, zoneTop: 152, state: 'ACTIVE' })
    expect(three.sourceLineage).toEqual(['PULLBACK', 'OSE'])
    expect(three).toMatchObject({ primary: true, reportedSource: 'OSE', episodeId: 'episode-a', zoneBottom: 148, zoneTop: 153 })
    expect(five.sourceLineage).toEqual(['OSE'])
  })

  it('publishes all current-ITM VOB lanes only from the matching security id', () => {
    const store = createOracleStore()
    const next = snapshot()
    const reversal = next.feeds.vob_reversal as Record<string, unknown>
    const current = reversal.current_itm1_contracts as Record<string, Record<string, unknown>>
    current.CE.vob = {
      security_id: '45102',
      source: 'CURRENT_ITM_EXACT_SECURITY_ID_CANONICAL_VOB',
      timeframes: {
        '1m': { demand: { zone_low: 151, zone_high: 152, status: 'ACTIVE', role: 'SUPPORT' } },
        '3m': { demand: { zone_low: 149, zone_high: 153, status: 'TESTED', role: 'SUPPORT' } },
        '5m': { demand: { zone_low: 146, zone_high: 154, status: 'ACTIVE', role: 'SUPPORT' } },
      },
    }
    store.getState().ingestSnapshot(next)
    expect(store.getState().vob.levels).toEqual(expect.arrayContaining([
      expect.objectContaining({ timeframe: '1M', reportedSource: 'CURRENT_ITM', zoneBottom: 151, zoneTop: 152 }),
      expect.objectContaining({ timeframe: '3M', reportedSource: 'CURRENT_ITM', zoneBottom: 149, zoneTop: 153 }),
      expect.objectContaining({ timeframe: '5M', reportedSource: 'CURRENT_ITM', zoneBottom: 146, zoneTop: 154 }),
    ]))
    expect(store.getState().vob.levels[1].episodeId).toBeNull()
  })

  it('keeps the episode contract frozen even when a later ATM identity arrives', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ revision: 1, securityId: '45098' }))
    store.getState().ingestSnapshot(snapshot({ revision: 2, securityId: '99999' }))
    expect(store.getState().vob.episode?.contract.securityId).toBe('45098')
    expect(store.getState().trade.contract.securityId).toBe('45098')
  })

  it('accepts a new frozen contract only for a new episode', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ revision: 1, securityId: '45098' }))
    store.getState().ingestSnapshot(snapshot({ revision: 2, episodeId: 'episode-b', securityId: '99999' }))
    expect(store.getState().vob.episode?.contract.securityId).toBe('99999')
  })

  it('accepts a lower worker-local revision for a genuinely newer episode', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ revision: 40, episodeId: 'episode-a', securityId: '45098' }))
    const next = snapshot({ revision: 1, episodeId: 'episode-b', securityId: '99999' })
    const episode = next.feeds.vob_reversal as Record<string, unknown>
    episode.episode = { ...(episode.episode as Record<string, unknown>), created_at: '2026-08-14T11:00:00+05:30' }
    store.getState().ingestSnapshot(next)
    expect(store.getState().runtime.revision).toBe(1)
    expect(store.getState().vob.episode?.episodeId).toBe('episode-b')
  })

  it('retains last authority but marks missing provider freshness truthfully', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ revision: 4 }))
    const unavailable = snapshot({ revision: 5 })
    unavailable.feeds.vob_reversal = null
    unavailable.feedMeta.vob_reversal = {
      health: 'OFFLINE', readiness: 'UNAVAILABLE', latency_ms: 0,
      last_updated: null, source_last_updated: null, freshness: 'UNAVAILABLE',
    }
    store.getState().ingestSnapshot(unavailable)
    expect(store.getState().vob.episode?.episodeId).toBe('episode-a')
    expect(store.getState().runtime.reversalFreshness).toBe('UNAVAILABLE')
  })

  it('passes backend shadow P&L through without reconstructing it', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ pnl: 312.5 }))
    expect(store.getState().trade.variants.VOB_ONLY?.pnl).toBe(312.5)
    expect(store.getState().trade.variants.CONFIRMED_REVERSAL?.pnl).toBe(312.5)
  })

  it('keeps current ITM-1 identity separate from exact frozen quote, VOB, and distance fields', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot())
    expect(store.getState().market.itmCall).toMatchObject({
      contract: { securityId: '45098', strike: 24_200, optionType: 'CE' },
      contractStatus: 'FROZEN_EPISODE', premium: 151.4, ask: 151.6,
      zoneBottom: 148, zoneTop: 153, insideZone: true, relation: 'INSIDE', zonePrimary: true,
    })
    expect(store.getState().market.itmCall.bid).toBeCloseTo(151.2)
    expect(store.getState().market.itmPut).toMatchObject({
      contract: { securityId: '45111', strike: 24_500, optionType: 'PE' },
      contractStatus: 'FROZEN_EPISODE', premium: 126.2,
      distancePoints: 2.2, distancePct: 1.743265, relation: 'ABOVE',
    })
    expect(store.getState().market).toMatchObject({
      canonicalAtmStrike: 24_350,
      strikeInterval: 50,
      activeCe: { securityId: '45102', strike: 24_300, optionType: 'CE' },
      activePe: { securityId: '45107', strike: 24_400, optionType: 'PE' },
      currentItmCall: {
        contract: { securityId: '45102', strike: 24_300, optionType: 'CE' },
        quoteSecurityId: '45102', vobSecurityId: null, premium: 159.25, bid: 159.2, ask: 160,
      },
      currentItmPut: {
        contract: { securityId: '45107', strike: 24_400, optionType: 'PE' },
        quoteSecurityId: '45107', vobSecurityId: null, premium: 74.3, bid: 74.3, ask: 74.55,
      },
    })
  })

  it('never cross-binds current quotes or frozen VOB distance across security IDs', () => {
    const store = createOracleStore()
    const mismatched = snapshot()
    const reversal = mismatched.feeds.vob_reversal as Record<string, unknown>
    const current = reversal.current_itm1_contracts as Record<string, { quote: Record<string, unknown> }>
    current.CE.quote.security_id = 'wrong-current-ce'
    store.getState().ingestSnapshot(mismatched)
    expect(store.getState().market.currentItmCall).toMatchObject({
      contract: { securityId: '45102' }, quoteSecurityId: 'wrong-current-ce',
      premium: null, bid: null, ask: null, vobSecurityId: null,
    })
    expect(store.getState().market.itmCall).toMatchObject({
      contract: { securityId: '45098' }, quoteSecurityId: '45098',
      vobSecurityId: '45098', distancePoints: 0,
    })
  })

  it('publishes current VOB metadata only when its security ID matches the resolver contract', () => {
    const store = createOracleStore()
    const rejected = snapshot()
    const rejectedCurrent = (rejected.feeds.vob_reversal as Record<string, any>).current_itm1_contracts.CE
    rejectedCurrent.vob = {
      security_id: 'expired-ce', timeframe: '3m', zone_id: 'expired-zone',
      zone_bottom: 1, zone_top: 2, state: 'ACTIVE', role: 'SUPPORT',
    }
    store.getState().ingestSnapshot(rejected)
    expect(store.getState().market.currentItmCall).toMatchObject({ vobSecurityId: null, zoneBottom: null, zoneTop: null })

    const accepted = snapshot({ revision: 2 })
    const acceptedCurrent = (accepted.feeds.vob_reversal as Record<string, any>).current_itm1_contracts.CE
    acceptedCurrent.vob = {
      security_id: '45102', timeframe: '3m', zone_id: 'current-zone',
      zone_bottom: 158, zone_top: 162, state: 'ACTIVE', role: 'SUPPORT',
      timeframes: {
        '1m': { state: 'BULLISH', demand: { status: 'ACTIVE', role: 'SUPPORT', zone_low: 157, zone_high: 159, origin_volume_formatted: '12.4K', volume_ratio: .12 } },
        '3m': { state: 'BULLISH', demand: { zone_id: 'current-zone', status: 'ACTIVE', role: 'SUPPORT', zone_low: 158, zone_high: 162, origin_volume_formatted: '44.9K', volume_ratio: .45, distance_points: 1.25, distance_percent: .79 } },
        '5m': { state: 'NEUTRAL' },
      },
    }
    store.getState().ingestSnapshot(accepted)
    expect(store.getState().market.currentItmCall).toMatchObject({
      vobSecurityId: '45102', zoneBottom: 158, zoneTop: 162, zoneVolume: '44.9K', zonePercent: 45,
      distancePoints: 1.25,
    })
    expect(store.getState().market.currentItmCall.vobLanes).toEqual(expect.arrayContaining([
      expect.objectContaining({ timeframe: '1M', zoneVolume: '12.4K', zonePercent: 12 }),
      expect.objectContaining({ timeframe: '3M', zoneVolume: '44.9K', zonePercent: 45 }),
    ]))
  })

  it('rolls both current ITM-1 references together while frozen episode displays stay fixed', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ revision: 1, atmStrike: 24_350, currentCeId: 'ce-old', currentPeId: 'pe-old' }))
    store.getState().ingestSnapshot(snapshot({ revision: 2, atmStrike: 24_400, currentCeId: 'ce-new', currentPeId: 'pe-new' }))
    const market = store.getState().market
    expect(market.activeCe).toMatchObject({ securityId: 'ce-new', strike: 24_350 })
    expect(market.activePe).toMatchObject({ securityId: 'pe-new', strike: 24_450 })
    expect(market.currentItmCall).toMatchObject({ contract: { securityId: 'ce-new', strike: 24_350 }, quoteSecurityId: 'ce-new' })
    expect(market.currentItmPut).toMatchObject({ contract: { securityId: 'pe-new', strike: 24_450 }, quoteSecurityId: 'pe-new' })
    expect(market.itmCall.contract).toMatchObject({ securityId: '45098', strike: 24_200 })
    expect(market.itmPut.contract).toMatchObject({ securityId: '45111', strike: 24_500 })
  })

  it('preserves UNKNOWN rather than fabricating missing option prices', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ callPrice: null, putPrice: null }))
    expect(store.getState().market.itmCall.premium).toBeNull()
    expect(store.getState().market.itmPut.premium).toBeNull()
  })

  it('preserves UNKNOWN instead of borrowing frozen quotes for missing current ITM-1 prices', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ currentCallPrice: null, currentPutPrice: null }))
    expect(store.getState().market.currentItmCall.premium).toBeNull()
    expect(store.getState().market.currentItmPut.premium).toBeNull()
    expect(store.getState().market.itmCall.premium).toBe(151.4)
    expect(store.getState().market.itmPut.premium).toBe(126.2)
  })

  it('updates market leaves without notifying VOB selectors for an unchanged revision', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ revision: 7, underlying: 24_300 }))
    let vobRenders = 0
    let marketRenders = 0
    const offVob = store.subscribe((state) => state.vob.levels, () => { vobRenders += 1 })
    const offMarket = store.subscribe((state) => state.market, () => { marketRenders += 1 })
    store.getState().ingestSnapshot(snapshot({ revision: 7, underlying: 24_321 }))
    offVob(); offMarket()
    expect(marketRenders).toBe(1)
    expect(vobRenders).toBe(0)
  })

  it('isolates a CALL price tick from the PUT leaf and the VOB-level selector', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ revision: 20, callPrice: 151.4 }))
    let callRenders = 0
    let putRenders = 0
    let vobRenders = 0
    const offCall = store.subscribe((state) => state.market.itmCall, () => { callRenders += 1 })
    const offPut = store.subscribe((state) => state.market.itmPut, () => { putRenders += 1 })
    const offVob = store.subscribe((state) => state.vob.levels, () => { vobRenders += 1 })
    store.getState().ingestSnapshot(snapshot({ revision: 21, callPrice: 151.8 }))
    offCall(); offPut(); offVob()
    expect(callRenders).toBe(1)
    expect(putRenders).toBe(0)
    expect(vobRenders).toBe(0)
  })

  it('isolates price and P&L revisions from VOB and reversal leaf selectors', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ revision: 8, pnl: 10 }))
    let vobRenders = 0
    let reversalRenders = 0
    let tradeRenders = 0
    const offVob = store.subscribe((state) => state.vob.levels, () => { vobRenders += 1 })
    const offReversal = store.subscribe((state) => state.reversal, () => { reversalRenders += 1 })
    const offTrade = store.subscribe((state) => state.trade, () => { tradeRenders += 1 })
    store.getState().ingestSnapshot(snapshot({ revision: 9, pnl: 14 }))
    offVob(); offReversal(); offTrade()
    expect(tradeRenders).toBe(1)
    expect(vobRenders).toBe(0)
    expect(reversalRenders).toBe(0)
  })

  it('isolates recovery evidence revisions from VOB levels and research selectors', () => {
    const store = createOracleStore()
    store.getState().ingestSnapshot(snapshot({ revision: 11, evidenceKnown: false }))
    let vobRenders = 0
    let reversalRenders = 0
    let researchRenders = 0
    const offVob = store.subscribe((state) => state.vob.levels, () => { vobRenders += 1 })
    const offReversal = store.subscribe((state) => state.reversal, () => { reversalRenders += 1 })
    const offResearch = store.subscribe((state) => state.research, () => { researchRenders += 1 })
    store.getState().ingestSnapshot(snapshot({ revision: 12, evidenceKnown: true, reversalState: 'REVERSAL_BUILDING' }))
    offVob(); offReversal(); offResearch()
    expect(reversalRenders).toBe(1)
    expect(vobRenders).toBe(0)
    expect(researchRenders).toBe(0)
  })

  it('steps canonical historical snapshots forward and backward through the production store', () => {
    const store = createOracleStore()
    const first = snapshot({ revision: 1, reversalState: 'WATCHING', underlying: 24_300 })
    const second = snapshot({ revision: 2, reversalState: 'REVERSAL_BUILDING', underlying: 24_320 })
    store.getState().loadHistoricalReplay([
      { snapshot: second, timestamp: '2026-08-14T10:01:00+05:30', date: '2026-08-14', contract: 'NIFTY260818P24400', timeframe: '1M', episodeId: 'episode-a' },
      { snapshot: first, timestamp: '2026-08-14T10:00:00+05:30', date: '2026-08-14', contract: 'NIFTY260818P24400', timeframe: '1M', episodeId: 'episode-a' },
    ])
    expect(store.getState().replay).toMatchObject({ mode: 'HISTORICAL_REPLAY', index: 0 })
    expect(store.getState().runtime.revision).toBe(1)
    expect(store.getState().reversal.state).toBe('WATCHING')

    store.getState().stepHistoricalReplay(1)
    expect(store.getState().runtime.revision).toBe(2)
    expect(store.getState().reversal.state).toBe('REVERSAL_BUILDING')
    store.getState().stepHistoricalReplay(0)
    expect(store.getState().runtime.revision).toBe(1)
    expect(store.getState().market.underlying).toBe(24_300)
  })

  it('does not let live polling overwrite a historical replay frame', () => {
    const store = createOracleStore()
    store.getState().loadHistoricalReplay([{
      snapshot: snapshot({ revision: 4, underlying: 24_300 }),
      timestamp: '2026-08-14T10:00:00+05:30', date: '2026-08-14',
      contract: 'NIFTY260818P24400', timeframe: '1M', episodeId: 'episode-a',
    }])
    store.getState().ingestSnapshot(snapshot({ revision: 99, underlying: 25_000 }))
    expect(store.getState().runtime.revision).toBe(4)
    expect(store.getState().market.underlying).toBe(24_300)
    store.getState().exitHistoricalReplay()
    expect(store.getState().replay.mode).toBe('LIVE')
    expect(store.getState().runtime.revision).toBe(-1)
  })

  describe('multi-timeframe VOB trade ledger', () => {
    it('1. 1M ORIGINAL appears in activeTrades', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 1, episodeId: 'ep_1m_zone' })
      base.feeds.vob_reversal.episodes_by_timeframe = {
        '1m': {
          episode_id: 'ep_1m_zone', timeframe: '1m', direction: 'CALL',
          contract_identity: { security_id: '45098', strike: 24200, option_type: 'CE' },
        },
      }
      base.feeds.vob_reversal.all_shadow_trades = {
        ep_1m_zone: {
          VOB_ONLY: {
            trade_id: 'ep_1m_zone_VOB_ONLY',
            timeframe: '1m',
            entry_ask: 150.0,
            initial_sl: 140.0,
            target: 170.0,
            current_bid: 153.0,
            pnl: 195.0,
            r: 0.3,
          },
        },
      }
      store.getState().ingestSnapshot(base)
      const trades = store.getState().trade.activeTrades
      expect(trades).toHaveLength(1)
      expect(trades[0]).toMatchObject({
        tradeId: 'ep_1m_zone_VOB_ONLY',
        timeframe: '1M',
        variant: 'VOB_ONLY',
        entryPrice: 150.0,
        currentBid: 153.0,
        pnl: 195.0,
        rMultiple: 0.3,
        status: 'ACTIVE',
      })
    })

    it('2. 3M CONFIRMED appears in activeTrades', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 2, episodeId: 'ep_3m_zone' })
      base.feeds.vob_reversal.episodes_by_timeframe = {
        '3m': {
          episode_id: 'ep_3m_zone', timeframe: '3m', direction: 'CALL',
          contract_identity: { security_id: '45098', strike: 24200, option_type: 'CE' },
        },
      }
      base.feeds.vob_reversal.all_shadow_trades = {
        ep_3m_zone: {
          CONFIRMED_REVERSAL: {
            trade_id: 'ep_3m_zone_CONFIRMED_REVERSAL',
            timeframe: '3m',
            entry_ask: 148.0,
            initial_sl: 138.0,
            target: 168.0,
            current_bid: 152.0,
            pnl: 260.0,
            r: 0.4,
          },
        },
      }
      store.getState().ingestSnapshot(base)
      const trades = store.getState().trade.activeTrades
      expect(trades).toHaveLength(1)
      expect(trades[0]).toMatchObject({
        tradeId: 'ep_3m_zone_CONFIRMED_REVERSAL',
        timeframe: '3M',
        variant: 'CONFIRMED_REVERSAL',
        entryPrice: 148.0,
      })
    })

    it('3. 1M ORIGINAL + 3M CONFIRMED coexist simultaneously as distinct records', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 3, episodeId: 'ep_3m_zone' })
      base.feeds.vob_reversal.episodes_by_timeframe = {
        '1m': { episode_id: 'ep_1m_zone', timeframe: '1m', direction: 'CALL' },
        '3m': { episode_id: 'ep_3m_zone', timeframe: '3m', direction: 'CALL' },
      }
      base.feeds.vob_reversal.all_shadow_trades = {
        ep_1m_zone: {
          VOB_ONLY: {
            trade_id: 'ep_1m_zone_VOB_ONLY',
            timeframe: '1m',
            entry_ask: 150.0,
          },
        },
        ep_3m_zone: {
          CONFIRMED_REVERSAL: {
            trade_id: 'ep_3m_zone_CONFIRMED_REVERSAL',
            timeframe: '3m',
            entry_ask: 148.0,
          },
        },
      }
      store.getState().ingestSnapshot(base)
      const trades = store.getState().trade.activeTrades
      expect(trades).toHaveLength(2)
      const tradeIds = trades.map((t) => t.tradeId)
      expect(tradeIds).toContain('ep_1m_zone_VOB_ONLY')
      expect(tradeIds).toContain('ep_3m_zone_CONFIRMED_REVERSAL')
    })

    it('4. 1M + 3M + 5M coexist simultaneously', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 4, episodeId: 'ep_5m_zone' })
      base.feeds.vob_reversal.episodes_by_timeframe = {
        '1m': { episode_id: 'ep_1m_zone', timeframe: '1m', direction: 'CALL' },
        '3m': { episode_id: 'ep_3m_zone', timeframe: '3m', direction: 'CALL' },
        '5m': { episode_id: 'ep_5m_zone', timeframe: '5m', direction: 'CALL' },
      }
      base.feeds.vob_reversal.all_shadow_trades = {
        ep_1m_zone: { VOB_ONLY: { trade_id: 'ep_1m_zone_VOB_ONLY', timeframe: '1m', entry_ask: 150.0 } },
        ep_3m_zone: { CONFIRMED_REVERSAL: { trade_id: 'ep_3m_zone_CONFIRMED_REVERSAL', timeframe: '3m', entry_ask: 148.0 } },
        ep_5m_zone: { VOB_ONLY: { trade_id: 'ep_5m_zone_VOB_ONLY', timeframe: '5m', entry_ask: 146.0 } },
      }
      store.getState().ingestSnapshot(base)
      const trades = store.getState().trade.activeTrades
      expect(trades).toHaveLength(3)
      expect(trades.map((t) => t.timeframe)).toEqual(expect.arrayContaining(['1M', '3M', '5M']))
    })

    it('5. Same-episode ORIGINAL + CONFIRMED coexist', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 5, episodeId: 'ep_same' })
      base.feeds.vob_reversal.episodes_by_timeframe = {
        '3m': { episode_id: 'ep_same', timeframe: '3m', direction: 'CALL' },
      }
      base.feeds.vob_reversal.all_shadow_trades = {
        ep_same: {
          VOB_ONLY: { trade_id: 'ep_same_VOB_ONLY', timeframe: '3m', entry_ask: 150.0, r: 1.2 },
          CONFIRMED_REVERSAL: { trade_id: 'ep_same_CONFIRMED_REVERSAL', timeframe: '3m', entry_ask: 147.0, r: 1.8 },
        },
      }
      store.getState().ingestSnapshot(base)
      const trades = store.getState().trade.activeTrades
      expect(trades).toHaveLength(2)
      expect(trades.find((t) => t.variant === 'VOB_ONLY')?.entryPrice).toBe(150.0)
      expect(trades.find((t) => t.variant === 'CONFIRMED_REVERSAL')?.entryPrice).toBe(147.0)
    })

    it('6. Duplicate backend event does not duplicate frontend row', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 6, episodeId: 'ep_dupe' })
      base.feeds.vob_reversal.all_shadow_trades = {
        ep_dupe: {
          VOB_ONLY: { trade_id: 'ep_dupe_VOB_ONLY', timeframe: '1m', entry_ask: 150.0 },
        },
      }
      store.getState().ingestSnapshot(base)
      expect(store.getState().trade.activeTrades).toHaveLength(1)

      // Re-ingest with updated quote/revision
      const next = snapshot({ revision: 7, episodeId: 'ep_dupe' })
      next.feeds.vob_reversal.all_shadow_trades = {
        ep_dupe: {
          VOB_ONLY: { trade_id: 'ep_dupe_VOB_ONLY', timeframe: '1m', entry_ask: 150.0, current_bid: 154.0 },
        },
      }
      store.getState().ingestSnapshot(next)
      expect(store.getState().trade.activeTrades).toHaveLength(1)
      expect(store.getState().trade.activeTrades[0].currentBid).toBe(154.0)
    })

    it('7. Null P&L shows null (not zero or fabricated)', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 8, episodeId: 'ep_null_pnl' })
      base.feeds.vob_reversal.all_shadow_trades = {
        ep_null_pnl: {
          VOB_ONLY: { trade_id: 'ep_null_pnl_VOB_ONLY', timeframe: '5m', entry_ask: 150.0, pnl: null, r: null },
        },
      }
      store.getState().ingestSnapshot(base)
      const trade = store.getState().trade.activeTrades[0]
      expect(trade.pnl).toBeNull()
      expect(trade.rMultiple).toBeNull()
    })

    it('8. Canonical trade_id is preserved', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 9, episodeId: 'ep_custom_id' })
      base.feeds.vob_reversal.all_shadow_trades = {
        ep_custom_id: {
          VOB_ONLY: { trade_id: 'custom_canonical_trade_hash_123', timeframe: '3m', entry_ask: 150.0 },
        },
      }
      store.getState().ingestSnapshot(base)
      expect(store.getState().trade.activeTrades[0].tradeId).toBe('custom_canonical_trade_hash_123')
    })

    it('9. Timeframe is preserved', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 10, episodeId: 'ep_tf' })
      base.feeds.vob_reversal.all_shadow_trades = {
        ep_tf: {
          CONFIRMED_REVERSAL: { trade_id: 'ep_tf_CONFIRMED', timeframe: '3m', entry_ask: 149.0 },
        },
      }
      store.getState().ingestSnapshot(base)
      expect(store.getState().trade.activeTrades[0].timeframe).toBe('3M')
    })

    it('10. Variant is preserved', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 11, episodeId: 'ep_var' })
      base.feeds.vob_reversal.all_shadow_trades = {
        ep_var: {
          EARLY_REVERSAL: { trade_id: 'ep_var_EARLY', timeframe: '1m', entry_ask: 151.0 },
        },
      }
      store.getState().ingestSnapshot(base)
      expect(store.getState().trade.activeTrades[0].variant).toBe('EARLY_REVERSAL')
    })

    it('11. Ingests canonical ARGUS Prime dominance, verdict, positioning, and focus strike spine', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 12, episodeId: 'ep_argus' })
      base.feeds.argus = {
        data: {
          verdict: { bias: 'BEARISH', regime: 'WRITER_DOMINATED', breakdown_below: 24200, breakout_above: 24300, call_wall: { strike: 24300 }, put_wall: { strike: 24200 } },
          dominance: { buyer_dominance_percentage: 20.55, writer_dominance_percentage: 79.45, call_writing_score: 79.45, put_buying_score: 20.55 },
          tactical_edge: {
            dominant_positioning: 'CALL WRITE BUILD',
            argus_prime: {
              canonical_presentation: {
                highest_load: { strike: 24300, ce_load: 84.75, pe_load: 85.08 },
              },
            },
            pressure: {
              strikes: [
                { strike: 24300, CE: { activity: 'CALL_WRITING' }, PE: { activity: 'PUT_BUYING' } },
              ],
            },
          },
        },
      }
      store.getState().ingestSnapshot(base)
      expect(store.getState().argus).toMatchObject({
        bias: 'PUT',
        regime: 'WRITER_DOMINATED',
        buyerDominancePct: 20.55,
        writerDominancePct: 79.45,
        breakdownBelow: 24200,
        breakoutAbove: 24300,
        positioning: 'CALL WRITE BUILD',
        focusStrike: 24300,
        focusStrikeCePositioning: 'WRITING',
        focusStrikePePositioning: 'LONG BUILD',
        focusStrikeLabel: 'FOCUS STRIKE',
      })
    })

    it('12. Ingests canonical underlying NIFTY VOB support and resistance zones from Strategy Lab', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 13, episodeId: 'ep_nifty_vob' })
      base.feeds.strategy_lab = {
        execution: {
          nifty_vob: {
            timeframes: {
              '5m': {
                nearest_bullish_support: {
                  zone_low: 24227.25,
                  zone_high: 24245.03,
                  role: 'SUPPORT',
                  side: 'BULLISH',
                  status: 'TESTED',
                },
                nearest_bearish_resistance: {
                  zone_low: 24373.40,
                  zone_high: 24384.40,
                  role: 'RESISTANCE',
                  side: 'BEARISH',
                  status: 'TESTED',
                },
              },
            },
          },
        },
      }
      store.getState().ingestSnapshot(base)
      expect(store.getState().vob.underlyingSupport).toBe(24227.25)
      expect(store.getState().vob.underlyingResistance).toBe(24384.40)
      expect(store.getState().vob.underlyingSupportZone).toEqual({ zoneLow: 24227.25, zoneHigh: 24245.03 })
      expect(store.getState().vob.underlyingResistanceZone).toEqual({ zoneLow: 24373.40, zoneHigh: 24384.40 })
    })

    it('13. Ingests spot & futures change %, rotates live ITM-1 contracts, and isolates frozen episode contracts', () => {
      const store = createOracleStore()
      const snapshot: DashboardSourceSnapshot = {
        meta: { schema_version: 2, timestamp: '2026-08-17T14:40:00Z', revision: 99 },
        feeds: {
          oracle: {
            symbol: 'NIFTY',
            data_status: 'FRESH',
            input_features: { close: 24345.0, session_status: 'OPEN' },
            vob: {
              current_itm1_contracts: {
                CE: {
                  contract: { security_id: '45102', strike: 24300, option_type: 'CE' },
                  quote: { ltp: 109.85, day_price_change: -51.55, previous_close: 161.40, day_change_pct: -31.94, oi: 13409500, change_oi: 5304715, positioning: 'SHORT_BUILDUP', freshness: 'FRESH' },
                },
                PE: {
                  contract: { security_id: '45107', strike: 24400, option_type: 'PE' },
                  quote: { ltp: 65.80, day_price_change: -5.55, previous_close: 71.35, day_change_pct: -7.78, oi: 7724145, change_oi: 455455, positioning: 'LONG_BUILDUP', freshness: 'FRESH' },
                },
              },
              option_contracts: {
                CE: {
                  contract: { security_id: '45102', strike: 24300, option_type: 'CE' },
                  quote: { ltp: 109.85, freshness: 'FRESH' },
                },
                PE: {
                  contract: { security_id: '45107', strike: 24400, option_type: 'PE' },
                  quote: { ltp: 65.80, freshness: 'FRESH' },
                },
              },
              frozen_episode_contracts: {
                CE: {
                  contract: { security_id: '45098', strike: 24200, option_type: 'CE' },
                  contract_status: 'FROZEN_EPISODE',
                  quote: { ltp: 195.8 },
                },
                PE: {
                  contract: { security_id: '45111', strike: 24500, option_type: 'PE' },
                  contract_status: 'FROZEN_EPISODE',
                  quote: { ltp: 133.6 },
                },
              },
              canonical_market: {
                atm_strike: 24350.0,
                reference_price: 24345.0,
                strike_interval: 50.0,
                pcr: 0.9869,
                change_pcr: 2.9133,
              },
            },
          },
          futures_chart: {
            data: {
              symbol: 'NIFTY FUT',
              current_price: 24420.0,
              candles: [{ open: 24480.0, close: 24472.5 }],
            },
          },
          argus: {
            data: {
              underlying: { ltp: 24345.0, baseline_ltp: 24370.0 },
              totals: { pcr: 0.9869, change_pcr: 2.9133 },
              verdict: { bias: 'RANGE_BOUND' },
            },
          },
        },
      }
      store.getState().ingestSnapshot(snapshot)
      const market = store.getState().market
      const argus = store.getState().argus

      // 1. Spot, Futures, and PCR
      expect(market.underlying).toBe(24345.0)
      expect(market.spotChangePct).toBeCloseTo(-0.10, 2)
      expect(market.futuresPrice).toBe(24420.0)
      expect(market.futuresChangePct).toBeCloseTo(-0.25, 2)
      expect(market.pcr).toBe(0.9869)
      expect(market.changePcr).toBe(2.9133)

      // 2. Live Rotating ITM-1 with OI and Buildup
      expect(market.currentItmCall.contract.strike).toBe(24300)
      expect(market.currentItmCall.premium).toBe(109.85)
      expect(market.currentItmCall.dayChangePct).toBe(-31.94)
      expect(market.currentItmCall.oi).toBe(13409500)
      expect(market.currentItmCall.changeOi).toBe(5304715)
      expect(market.currentItmCall.positioning).toBe('SHORT_BUILDUP')

      expect(market.currentItmPut.contract.strike).toBe(24400)
      expect(market.currentItmPut.premium).toBe(65.80)
      expect(market.currentItmPut.dayChangePct).toBe(-7.78)
      expect(market.currentItmPut.oi).toBe(7724145)
      expect(market.currentItmPut.changeOi).toBe(455455)
      expect(market.currentItmPut.positioning).toBe('LONG_BUILDUP')

      // 3. Frozen Episode isolation
      expect(market.frozenEpisodeCall?.contract.strike).toBe(24200)
      expect(market.frozenEpisodeCall?.contractStatus).toBe('FROZEN_EPISODE')
      expect(market.frozenEpisodePut?.contract.strike).toBe(24500)
      expect(market.frozenEpisodePut?.contractStatus).toBe('FROZEN_EPISODE')

      // 4. Bias normalization
      expect(argus.bias).toBe('RANGE BOUND')
    })

    it('resolves ITM-1 CE/PE with OI, ΔOI, and buildup directly from argus atm_window fallback when projection is empty', () => {
      const store = createOracleStore()
      const snapshot: DashboardSourceSnapshot = {
        traceId: 'trace-fallback-rotation',
        generatedAt: '2026-08-17T15:29:59Z',
        selectedSymbol: 'NIFTY',
        feedMeta: {},
        feeds: {
          oracle: { input_features: { session_status: 'OPEN' } },
          argus: {
            data: {
              underlying: { ltp: 24287.65, atm_strike: 24300, baseline_ltp: 24250.0, expiry: '2026-08-20' },
              totals: { pcr: 0.9869, change_pcr: 2.9133 },
              atm_window: [
                {
                  strike: 24250,
                  ce: { security_id: '45100', ltp: 135.5, top_bid_price: 135.4, top_ask_price: 135.6, day_price_change: -20.5, previous_close: 156.0, oi: 15400000, day_change_oi: 2100000, day_positioning: 'SHORT_BUILDUP' },
                  pe: { security_id: '45101', ltp: 45.2, top_bid_price: 45.1, top_ask_price: 45.3, day_price_change: 5.2, previous_close: 40.0, oi: 8900000, day_change_oi: -1200000, day_positioning: 'SHORT_COVERING' },
                },
                {
                  strike: 24300,
                  ce: { security_id: '45102', ltp: 100.5, top_bid_price: 100.4, top_ask_price: 100.6, day_price_change: -15.0, previous_close: 115.5, oi: 13400000, day_change_oi: 1800000, day_positioning: 'SHORT_BUILDUP' },
                  pe: { security_id: '45103', ltp: 60.5, top_bid_price: 60.4, top_ask_price: 60.6, day_price_change: 8.0, previous_close: 52.5, oi: 9500000, day_change_oi: 400000, day_positioning: 'LONG_BUILDUP' },
                },
                {
                  strike: 24350,
                  ce: { security_id: '45104', ltp: 72.0, top_bid_price: 71.9, top_ask_price: 72.1, day_price_change: -10.0, previous_close: 82.0, oi: 11200000, day_change_oi: 900000, day_positioning: 'SHORT_BUILDUP' },
                  pe: { security_id: '45105', ltp: 81.0, top_bid_price: 80.9, top_ask_price: 81.1, day_price_change: 12.0, previous_close: 69.0, oi: 14200000, day_change_oi: 3100000, day_positioning: 'LONG_BUILDUP' },
                },
              ],
            },
          },
        },
      }
      store.getState().ingestSnapshot(snapshot)
      const market = store.getState().market

      // Boundary Resolution for ATM 24300:
      // ITM-1 CE = 24250 CE (45100)
      // ITM-1 PE = 24350 PE (45105)
      expect(market.canonicalAtmStrike).toBe(24300)
      expect(market.strikeInterval).toBe(50)
      expect(market.pcr).toBe(0.9869)
      expect(market.changePcr).toBe(2.9133)

      expect(market.currentItmCall.contract.strike).toBe(24250)
      expect(market.currentItmCall.contract.securityId).toBe('45100')
      expect(market.currentItmCall.premium).toBe(135.5)
      expect(market.currentItmCall.dayChangePct).toBeCloseTo(-13.14, 2)
      expect(market.currentItmCall.oi).toBe(15400000)
      expect(market.currentItmCall.changeOi).toBe(2100000)
      expect(market.currentItmCall.positioning).toBe('SHORT_BUILDUP')

      expect(market.currentItmPut.contract.strike).toBe(24350)
      expect(market.currentItmPut.contract.securityId).toBe('45105')
      expect(market.currentItmPut.premium).toBe(81.0)
      expect(market.currentItmPut.dayChangePct).toBeCloseTo(17.39, 2)
      expect(market.currentItmPut.oi).toBe(14200000)
      expect(market.currentItmPut.changeOi).toBe(3100000)
      expect(market.currentItmPut.positioning).toBe('LONG_BUILDUP')
    })

    it('proves Track A (VOB_ONLY) and Track B (CONFIRMED_REVERSAL) coexist under the same episode with independent trade IDs', () => {
      const store = createOracleStore()
      const snapshot: DashboardSourceSnapshot = {
        traceId: 'trace-dual-track',
        generatedAt: '2026-08-17T15:30:00Z',
        selectedSymbol: 'NIFTY',
        feedMeta: {},
        feeds: {
          vob_reversal: {
            data: {
              revision: 100,
              schema_version: 5,
              episode_id: 'EP-5M-20260817-001',
              direction: 'CALL',
              timeframe: '5m',
              vob_state: 'ACTIVE',
              reversal_state: 'REVERSAL_READY',
              episode: {
                episode_id: 'EP-5M-20260817-001',
                direction: 'CALL',
                timeframe: '5m',
                zone_top: 24320.0,
                zone_bottom: 24300.0,
                created_at: '2026-08-17T15:20:00Z',
                touch_at: '2026-08-17T15:22:30Z',
                contract_identity: { security_id: '45100', strike: 24250, option_type: 'CE' },
              },
              all_shadow_trades: {
                'EP-5M-20260817-001': {
                  VOB_ONLY: {
                    trade_id: 'EP-5M-20260817-001_VOB_ONLY',
                    episode_id: 'EP-5M-20260817-001',
                    variant: 'VOB_ONLY',
                    entry_time: '2026-08-17T15:22:30Z',
                    entry_ask: 130.0,
                    initial_sl: 24300.0,
                    current_bid: 145.0,
                    mfe: 15.0,
                    mae: 2.0,
                    r: 1.5,
                  },
                  CONFIRMED_REVERSAL: {
                    trade_id: 'EP-5M-20260817-001_CONFIRMED_REVERSAL',
                    episode_id: 'EP-5M-20260817-001',
                    variant: 'CONFIRMED_REVERSAL',
                    entry_time: '2026-08-17T15:25:00Z',
                    entry_ask: 136.0,
                    initial_sl: 24300.0,
                    current_bid: 145.0,
                    mfe: 9.0,
                    mae: 1.0,
                    r: 0.9,
                  },
                },
              },
            },
          },
        },
      }
      store.getState().ingestSnapshot(snapshot)
      const trade = store.getState().trade
      const activeTrades = trade.activeTrades

      expect(activeTrades.length).toBe(2)

      const vobOnly = activeTrades.find((t) => t.variant === 'VOB_ONLY')
      const confirmed = activeTrades.find((t) => t.variant === 'CONFIRMED_REVERSAL')

      expect(vobOnly).toBeDefined()
      expect(vobOnly?.tradeId).toBe('EP-5M-20260817-001_VOB_ONLY')
      expect(vobOnly?.entryPrice).toBe(130.0)
      expect(vobOnly?.entryTime).toBe('2026-08-17T15:22:30Z')

      expect(confirmed).toBeDefined()
      expect(confirmed?.tradeId).toBe('EP-5M-20260817-001_CONFIRMED_REVERSAL')
      expect(confirmed?.entryPrice).toBe(136.0)
      expect(confirmed?.entryTime).toBe('2026-08-17T15:25:00Z')
    })

    it('parses exact option and NIFTY Horsepower without deriving events', () => {
      const store = createOracleStore()
      const value = snapshot({ revision: 120 }) as any
      const projection = value.feeds.vob_reversal
      const horsepower = {
        instrument: 'CE:45102', session_id: '2026-08-20',
        timeframes: {
          '1m': { status: 'NEUTRAL', event_id: null, support_broken: 0, resistance_broken: 0 },
          '3m': { status: 'RESISTANCE_OUT', event_id: 'hp-1', support_broken: 0, resistance_broken: 1 },
          '5m': { status: 'NEUTRAL', event_id: null, support_broken: 0, resistance_broken: 0 },
        },
        combined: 'RESISTANCE OUT · 1X POWER', pulse_1m: 'NEUTRAL', continuity: 'CONTINUOUS',
        events: [{
          event_id: 'hp-1', instrument: 'CE:45102', timeframe: '3M', event: 'RESISTANCE_OUT',
          zone_id: 'zone-r', confirmed_candle: '2026-08-20T11:48:00+05:30', close: 217.45,
          notification_eligible: true,
        }],
      }
      projection.current_itm1_contracts.CE.vob = { security_id: '45102', horsepower }
      projection.nifty_horsepower = { ...horsepower, instrument: 'NIFTY' }
      store.getState().ingestSnapshot(value)
      expect(store.getState().market.currentItmCall.horsepower?.events[0].eventId).toBe('hp-1')
      expect(store.getState().vob.underlyingHorsepower?.instrument).toBe('NIFTY')
      expect(store.getState().vob.underlyingHorsepower?.timeframes['3m'].status).toBe('RESISTANCE_OUT')
    })

    it('parses resolver_event for CE and PE without client-side derivation', () => {
      const store = createOracleStore()
      const value = snapshot({ revision: 150 }) as any
      value.feeds.option_buyer_intelligence = {
        data: {
          CE: {
            resolver_event: {
              label: 'SUPPORT GONE 3M · FLOW 4.1X',
              semantic_direction: 'BEARISH',
              variant: 'red',
              confluence_state: 'FULL_FRESH',
              pulse_key: '61647_EV3M_1787300000',
              source_event_time: '2026-08-21T10:00:00+05:30',
              held_previous: false,
            },
          },
          PE: {
            resolver_event: {
              label: 'RES OUT 5M · OI 3.2X',
              semantic_direction: 'BULLISH',
              variant: 'mint',
              confluence_state: 'FULL_FRESH',
              pulse_key: '61703_EV5M_1787300000',
              source_event_time: '2026-08-21T10:05:00+05:30',
              held_previous: true,
            },
          },
        },
      }
      store.getState().ingestSnapshot(value)
      const ceResolver = store.getState().market.currentItmCall.resolverEvent
      const peResolver = store.getState().market.currentItmPut.resolverEvent

      expect(ceResolver).toBeDefined()
      expect(ceResolver?.label).toBe('SUPPORT GONE 3M · FLOW 4.1X')
      expect(ceResolver?.variant).toBe('red')
      expect(ceResolver?.semanticDirection).toBe('BEARISH')
      expect(ceResolver?.confluenceState).toBe('FULL_FRESH')
      expect(ceResolver?.pulseKey).toBe('61647_EV3M_1787300000')
      expect(ceResolver?.heldPrevious).toBe(false)

      expect(peResolver).toBeDefined()
      expect(peResolver?.label).toBe('RES OUT 5M · OI 3.2X')
      expect(peResolver?.variant).toBe('mint')
      expect(peResolver?.confluenceState).toBe('FULL_FRESH')
      expect(peResolver?.heldPrevious).toBe(true)
    })

    it('hydrates Upstox market_info metrics into market slice', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 50 })
      const value: DashboardSourceSnapshot = {
        ...base,
        feeds: {
          ...base.feeds,
          market_info: {
            status: 'AVAILABLE',
            provider: 'UPSTOX',
            india_vix: 11.16,
            india_vix_change: 0.48,
            india_vix_change_pct: 4.49,
            gift_nifty: 23809.5,
            gift_nifty_change: -17.0,
            gift_nifty_change_pct: -0.07,
            pcr: 0.5641,
            pcr_provenance: 'DIRECT_UPSTOX_MARKET_INFO',
            max_pain: 23800.0,
            max_pain_provenance: 'DIRECT_UPSTOX_MARKET_INFO',
            gift_nifty_freshness: 'DELAYED_PROVIDER',
            fii_dii_summary: {
              status: 'DAILY_OFFICIAL',
              date: '04 SEP',
              fii_fut_net: -122.86,
              dii_cash_net: 8930.12,
            },
          },
        },
      }
      store.getState().ingestSnapshot(value)
      const market = store.getState().market

      expect(market.indiaVix).toBe(11.16)
      expect(market.indiaVixChange).toBe(0.48)
      expect(market.indiaVixChangePct).toBe(4.49)
      expect(market.giftNifty).toBe(23809.5)
      expect(market.giftNiftyChange).toBe(-17.0)
      expect(market.giftNiftyChangePct).toBe(-0.07)
      expect(market.giftNiftyFreshness).toBe('DELAYED_PROVIDER')
      expect(market.upstoxPcr).toBe(0.5641)
      expect(market.pcrProvenance).toBe('DIRECT_UPSTOX_MARKET_INFO')
      expect(market.maxPain).toBe(23800.0)
      expect(market.maxPainProvenance).toBe('DIRECT_UPSTOX_MARKET_INFO')
      expect(market.fiiDiiSummary).toMatchObject({
        status: 'DAILY_OFFICIAL',
        date: '04 SEP',
        fii_fut_net: -122.86,
        dii_cash_net: 8930.12,
      })
    })

    it('hydrates expanded Upstox market context (indices, shifts, OI shift, FII/DII derivatives) into market slice', () => {
      const store = createOracleStore()
      const base = snapshot({ revision: 51 })
      const value: DashboardSourceSnapshot = {
        ...base,
        feeds: {
          ...base.feeds,
          market_info: {
            status: 'AVAILABLE',
            provider: 'UPSTOX',
            bank_nifty: 57088.30,
            bank_nifty_change: -281.35,
            bank_nifty_change_pct: -0.49,
            midcap_select: 14650.70,
            midcap_select_change: -62.95,
            midcap_select_change_pct: -0.43,
            sensex: 76132.81,
            sensex_change: -382.62,
            sensex_change_pct: -0.50,
            pcr: 0.5641,
            pcr_shift: {
              prev: 0.6521,
              curr: 0.6100,
              delta: -0.0421,
              interval: '15m',
              prev_time: '15:15',
              curr_time: '15:30',
            },
            max_pain: 23800.0,
            max_pain_shift: {
              prev: 23800.0,
              curr: 23800.0,
              delta: 0.0,
              interval: '15m',
              prev_time: '15:15',
              curr_time: '15:30',
            },
            oi_shift: {
              status: 'AVAILABLE',
              expiry: '2026-09-08',
              provenance: 'DERIVED_UPSTOX_OPTION_CHAIN',
              total_call_oi: 262194335,
              total_put_oi: 147901195,
              total_call_delta_oi: 69788420,
              total_put_delta_oi: -14552395,
              largest_call_increase: { strike: 23800.0, delta_oi: 15535650.0, oi: 17532970.0 },
              largest_call_unwind: { strike: 25500.0, delta_oi: -1827735.0, oi: 3977545.0 },
              largest_put_increase: { strike: 23750.0, delta_oi: 4150900.0, oi: 8411260.0 },
              largest_put_unwind: { strike: 23900.0, delta_oi: -7532785.0, oi: 3586050.0 },
              bias_rule: 'FACTUAL_OI_DELTAS_NO_BIAS_INFERRED',
            },
            fii_dii_summary: {
              status: 'DAILY_OFFICIAL',
              date: '04 SEP',
              fii_fut_net: -122.86,
              dii_cash_net: 8930.12,
              fii_futures: {
                buy_amount_cr: 1106.90,
                sell_amount_cr: 1229.76,
                net_amount_cr: -122.86,
                buy_contracts: 6906,
                sell_contracts: 7642,
                long_contracts: 33689,
                short_contracts: 269527,
                oi_contracts: 303216,
                oi_amount_cr: 48891.52,
              },
              fii_options: {
                buy_amount_cr: 871378.46,
                sell_amount_cr: 881281.75,
                net_amount_cr: -9903.29,
                buy_contracts: 5566210,
                sell_contracts: 5626595,
                call_long_contracts: 561316,
                call_short_contracts: 864770,
                put_long_contracts: 1070255,
                put_short_contracts: 489344,
                oi_contracts: 2985686,
                oi_amount_cr: 470956.48,
              },
              dii_cash: {
                buy_amount_cr: 19254.19,
                sell_amount_cr: 10324.07,
                net_amount_cr: 8930.12,
                derivatives: 'N/A',
              },
            },
          },
        },
      }
      store.getState().ingestSnapshot(value)
      const market = store.getState().market

      // Indices
      expect(market.bankNifty).toBe(57088.30)
      expect(market.bankNiftyChange).toBe(-281.35)
      expect(market.bankNiftyChangePct).toBe(-0.49)
      expect(market.midcapSelect).toBe(14650.70)
      expect(market.midcapSelectChange).toBe(-62.95)
      expect(market.midcapSelectChangePct).toBe(-0.43)
      expect(market.sensex).toBe(76132.81)
      expect(market.sensexChange).toBe(-382.62)
      expect(market.sensexChangePct).toBe(-0.50)

      // Shifts
      expect(market.pcrShift?.delta).toBe(-0.0421)
      expect(market.pcrShift?.interval).toBe('15m')
      expect(market.maxPainShift?.prev).toBe(23800.0)
      expect(market.maxPainShift?.curr).toBe(23800.0)

      // OI Shift
      expect(market.oiShift?.total_call_delta_oi).toBe(69788420)
      expect(market.oiShift?.total_put_delta_oi).toBe(-14552395)
      expect(market.oiShift?.largest_call_increase?.strike).toBe(23800.0)
      expect(market.oiShift?.largest_call_unwind?.strike).toBe(25500.0)
      expect(market.oiShift?.bias_rule).toBe('FACTUAL_OI_DELTAS_NO_BIAS_INFERRED')

      // FII/DII
      expect(market.fiiDiiSummary?.fii_futures?.buy_contracts).toBe(6906)
      expect(market.fiiDiiSummary?.fii_futures?.sell_contracts).toBe(7642)
      expect(market.fiiDiiSummary?.fii_options?.call_long_contracts).toBe(561316)
      expect(market.fiiDiiSummary?.dii_cash?.net_amount_cr).toBe(8930.12)
      expect(market.fiiDiiSummary?.dii_cash?.derivatives).toBe('N/A')
    })
  })
})
