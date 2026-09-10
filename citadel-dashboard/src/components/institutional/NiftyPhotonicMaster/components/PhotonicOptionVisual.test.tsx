import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { OracleOptionDisplay } from '@/dashboard/store/oracleStore'
import { PhotonicCallCard } from './PhotonicCallCard'
import { PhotonicOptionBuyerIntelligence } from './PhotonicOptionBuyerIntelligence'
import { PhotonicOracleHeroWheel } from './PhotonicOracleHeroWheel'
import { PhotonicPutCard } from './PhotonicPutCard'
import { PhotonicSuddenOiIntelligence, suddenOiAlertFrames } from './PhotonicSuddenOiIntelligence'
import { acceptSemanticEvent } from '../../vobPresentation'

// Exact model output produced from the first two genuine 19-Aug records in:
// logs/strategy_command/argus_edge_lab/market_snapshots.jsonl
// Observed at 14:01:52 and 14:01:59 IST; never injected into the live store.
const recordedObi = {
  status: 'MODEL_DERIVED_RESEARCH',
  source_timestamp: '2026-08-19T14:01:59.456871+05:30',
  provenance: 'RECORDED_20260819_ARGUS_EDGE_MARKET_SNAPSHOT',
  CE: {
    fair_price: 165.74, ask: 156, bid: 155.75, comparison: 'BELOW_FAIR', below_fair_pct: 5.88,
    fair_advantage: 9.74,
    time_loss_expected: -0, actual_change: -0.9, premium_holding: -0.9,
    market_pressure: { total_buy_quantity: 365300, total_sell_quantity: 590135, book_buy_share_pct: 22.45, book_sell_share_pct: 77.55, last_trade_quantity: 65, average_trade_price: 146.18 },
    book: { best_bid: { price: 150, quantity: 130, orders: 1 }, best_ask: { price: 151.95, quantity: 195, orders: 1 }, biggest_buy_level: { price: 149.85, quantity: 325, orders: 1 }, biggest_sell_level: { price: 154, quantity: 1690, orders: 4 }, five_level_buy_quantity: 845, five_level_sell_quantity: 2925 },
    quality: { valid: true, fair_iv_method: 'NEIGHBOUR_INTERPOLATION_EXCLUDING_TARGET' },
  },
  PE: {
    fair_price: 123.34, ask: 137.05, bid: 136.85, comparison: 'INFLATED', extra_paying: 13.71, inflated_pct: 11.12,
    fair_advantage: -13.71,
    time_loss_expected: -0, actual_change: 1.05, premium_holding: 1.05,
    market_pressure: { total_buy_quantity: 790920, total_sell_quantity: 534560, book_buy_share_pct: 61.25, book_sell_share_pct: 38.75, last_trade_quantity: 130, average_trade_price: 115.42 },
    book: { best_bid: { price: 97.3, quantity: 260, orders: 2 }, best_ask: { price: 98, quantity: 195, orders: 1 }, biggest_buy_level: { price: 97.1, quantity: 650, orders: 4 }, biggest_sell_level: { price: 98.5, quantity: 520, orders: 3 }, five_level_buy_quantity: 1560, five_level_sell_quantity: 980 },
    quality: { valid: true, fair_iv_method: 'NEIGHBOUR_INTERPOLATION_EXCLUDING_TARGET' },
  },
  straddle: {
    now: 239.35, vwap: null, premium_today: 0.1, state: 'RISING', market_still_prices: 239.35,
    time_loss_expected: null, actual_change: 0.1, premium_holding: null, premium_driver: 'PUT',
    call_change: -0.85, put_change: 0.95, continuity_state: 'CONTINUOUS',
  },
  fit: { call_evidence: null, put_evidence: null, state: 'NO_CLEAN_FIT' },
} as const

function option(optionType: 'CE' | 'PE'): OracleOptionDisplay {
  const call = optionType === 'CE'
  return {
    contract: { securityId: call ? '61605' : '61646', strike: call ? 24050 : 24150, optionType, expiry: '2026-08-25', tradingSymbol: `NIFTY 25 AUG ${call ? 24050 : 24150} ${optionType}`, lotSize: 65, source: 'ARGUS_OPTION_CHAIN_RESOLVER' },
    contractStatus: 'CURRENT_ITM1', quoteSecurityId: call ? '61605' : '61646', vobSecurityId: call ? '61605' : '61646',
    premium: call ? 156.9 : 135.75, bid: call ? 156.9 : 135.5, ask: call ? 157 : 135.7,
    quoteTimestamp: '2026-08-19T14:01:52.119986+05:30', freshness: 'FRESH', quoteSource: 'ARGUS_DHAN_OPTION_CHAIN',
    vobTimeframe: call ? '3M' : '5M', zoneTop: call ? 144.46 : 126.58, zoneBottom: call ? 139.15 : 122.1,
    zoneState: 'TESTED', zoneRole: 'SUPPORT', zoneSource: 'CURRENT_ITM_EXACT_SECURITY_ID_CANONICAL_VOB', zonePrimary: true,
    zoneVolume: call ? '1.18M' : '1.61M', zonePercent: call ? 100 : 77,
    vobLanes: [
      { timeframe: '1M', state: 'TESTED', role: 'SUPPORT', zoneTop: call ? 144.47 : 131.4, zoneBottom: call ? 141.55 : 129.1, zoneVolume: null, zonePercent: null, distancePoints: null, distancePercent: null },
      { timeframe: '3M', state: call ? 'TESTED' : 'ACTIVE', role: 'SUPPORT', zoneTop: call ? 144.46 : 84.93, zoneBottom: call ? 139.15 : 81.6, zoneVolume: null, zonePercent: null, distancePoints: null, distancePercent: null },
      { timeframe: '5M', state: call ? 'TESTED' : 'TESTED', role: 'SUPPORT', zoneTop: call ? 165.3 : 126.58, zoneBottom: call ? 158.43 : 122.1, zoneVolume: null, zonePercent: null, distancePoints: null, distancePercent: null },
    ],
    distancePoints: call ? 10.19 : 4.92, distancePct: call ? 6.59 : 3.74, insideZone: false, nearestZoneBoundary: call ? 144.46 : 126.58, relation: 'ABOVE',
    dayPriceChange: null, previousClose: null, openingPrice: null, dayChangePct: null,
    oi: null, openingOi: null, changeOi: null, changeOiPct: null, positioning: null, derivedPositioning: null, positioningFormula: null, positioningAgreement: null,
  }
}

describe('Photonic option VOB + OBI visual truth', () => {
  const horsepower = {
    instrument: 'CE:61647', sessionId: '2026-08-20',
    timeframes: {
      '1m': { status: 'NEUTRAL', eventId: null, supportBroken: 0, resistanceBroken: 0 },
      '3m': { status: 'RESISTANCE_OUT', eventId: 'event-3m', supportBroken: 0, resistanceBroken: 1 },
      '5m': { status: 'RESISTANCE_OUT', eventId: 'event-5m', supportBroken: 0, resistanceBroken: 1 },
    },
    combined: 'BOTH RESISTANCES OUT · 2X HORSEPOWER', pulse1m: 'NEUTRAL',
    events: [], continuity: 'SESSION_RECONSTRUCTED', bootstrapMs: 8.1,
  } as const

  it('renders the complete mirrored VOB section in both option cards', () => {
    const call = renderToStaticMarkup(<PhotonicCallCard option={option('CE')} geometry={{ pricePct: 72, zoneStartPct: 20, zoneEndPct: 35 }} />)
    const put = renderToStaticMarkup(<PhotonicPutCard option={option('PE')} geometry={{ pricePct: 68, zoneStartPct: 22, zoneEndPct: 38 }} />)
    for (const html of [call, put]) {
      expect(html).toContain('SETUP PROGRESS')
      expect(html).toContain('ENTRY ZONE')
      expect(html).toContain('SL')
      expect(html).toContain('TARGET')
      expect(html).toContain('RECOVERY / CONTEXT')
      expect(html).toContain('1M VOB')
      expect(html).toContain('3M VOB')
      expect(html).toContain('5M VOB')
      expect(html).toContain('VOB · SUPPORT MATRIX')
      expect(html).toContain('VOB PROXIMITY MAGNET')
    }
  })

  it('keeps 1M/3M/5M Horsepower rows visible for options and NIFTY', () => {
    const call = renderToStaticMarkup(<PhotonicCallCard option={{ ...option('CE'), horsepower }} />)
    const nifty = renderToStaticMarkup(<PhotonicOracleHeroWheel horsepower={{ ...horsepower, instrument: 'NIFTY' }} />)
    for (const html of [call, nifty]) {
      expect(html).toContain('1M PULSE')
      expect(html).toContain('3M POWER')
      expect(html).toContain('5M POWER')
      expect(html).toContain('HORSEPOWER')
      expect(html).toContain('BOTH RESISTANCES OUT · 2X HORSEPOWER')
    }
  })

  it('renders genuine Dhan market pressure and visible depth without unsupported blank scaffolding', () => {
    const html = renderToStaticMarkup(<PhotonicOptionBuyerIntelligence side="CE" intelligence={recordedObi} />)
    expect((html.match(/data-obi-rail/g) ?? []).length).toBe(2)
    expect(html).toContain('FAIR ₹165.74')
    expect(html).toContain('₹0.90 WEAKER')
    expect(html).toContain('LIVE MARKET PRESSURE')
    expect(html).toContain('TOTAL BUY QTY')
    expect(html).toContain('BUY 22% · SELL 78%')
    expect(html).toContain('BOOK / DEPTH')
    expect(html).toContain('BIGGEST BUY LEVEL')
    for (const removed of ['BUYING VOL', 'SELLING VOL', 'NET FLOW', 'ACTIVITY × NORMAL', 'ENTRY + EXIT COST', 'EDGE AFTER COSTS', 'MY BUY PRICE', 'MOST TRADED PRICE']) {
      expect(html).not.toContain(removed)
    }
  })

  it('keeps Straddle and the factual Evidence tile honest and compact', () => {
    const straddle = renderToStaticMarkup(<PhotonicOracleHeroWheel presentation="STRADDLE" intelligence={recordedObi} />)
    const fit = renderToStaticMarkup(<PhotonicOracleHeroWheel presentation="FIT" intelligence={recordedObi} callHorsepower={horsepower} putHorsepower={{ ...horsepower, instrument: 'PE:61703', combined: 'SUPPORT BACK · HORSEPOWER RETURNING ↑' }} />)
    expect(straddle).toContain('RISING')
    expect(straddle).toContain('~239.35 pts')
    expect(straddle).toContain('PUT +₹0.95')
    expect(straddle).not.toContain('VWAP')
    expect(straddle).not.toContain('PREMIUM EXPANSION')
    expect(fit).toContain('PRICE · CE')
    expect(fit).toContain('+₹9.74')
    expect(fit).toContain('VOB · PE')
    expect(fit).toContain('SUPPORT BACK · HORSEPOWER RETURNING ↑')
    expect(fit).toContain('BUY 22% · SELL 78%')
    expect(fit).not.toContain('/ 5')
    expect(fit).not.toContain('FLOW')
    expect(fit).not.toContain('ENTRY')
    expect(fit).toContain('CURRENT LEAN')
  })

  it('renders canonical heuristic GEX values beneath buy and write without frontend recomputation', () => {
    const intelligence = {
      ...recordedObi,
      option_intelligence: {
        gex: {
          total_net_gex_inr_cr: -179.26,
          zero_gamma_strike: 24103.9,
        },
      },
    }
    const html = renderToStaticMarkup(<PhotonicOracleHeroWheel intelligence={intelligence} />)
    const positiveHtml = renderToStaticMarkup(<PhotonicOracleHeroWheel intelligence={{
      ...intelligence,
      option_intelligence: { gex: { total_net_gex_inr_cr: 350.78, zero_gamma_strike: 24170.4 } },
    }} />)
    expect(html).toContain('NET GEX')
    expect(html).toContain('-₹179.26 Cr')
    expect(html).toContain('data-gex-sign="negative"')
    expect(html).toContain('color:var(--algory-red)')
    expect(positiveHtml).toContain('+₹350.78 Cr')
    expect(positiveHtml).toContain('data-gex-sign="positive"')
    expect(positiveHtml).toContain('color:var(--mint)')
    expect(html).toContain('GEX CROSS · HEURISTIC')
    expect(html).toContain('24,103.9')
    expect(html).toContain('data-gex-metric="cross"')
    expect(html).toContain('color:var(--cyan)')
    expect(html).not.toContain('ZERO GAMMA')
  })

  it('renders canonical sudden OI cards and shared context without recalculating metrics', () => {
    const intelligence = {
      sudden_oi: {
        status: 'LIVE',
        CALL: {
          status: 'LIVE', previous_5m_activity: 600000, normal_5m_activity: 140000, current_5m_activity: 890000, current_to_normal_x: 6.3571, percentile: 99,
          recent_5m_activity: [{ window_timestamp: '2026-08-25T12:35:00+05:30', activity: 600000 }, { window_timestamp: '2026-08-25T12:40:00+05:30', activity: 890000 }],
          previous_session_high: 620000, new_session_extreme: true, state_label: 'CALL WRITING / SHORT BUILDUP',
          breadth: { count: 4, total: 5, valid: 5 }, read: 'NEW SESSION EXTREME', window_closed_at: '2026-08-25T12:40:00+05:30',
          top_strike: { security_id: '61605', strike: 24300, option_type: 'CE', activity_5m: 380000, percentile: 99, state: 'SHORT COVERING', new_5m_high: true, squeeze: true },
        },
        PUT: {
          status: 'LIVE', previous_5m_activity: 250000, normal_5m_activity: 210000, current_5m_activity: 300000, current_to_normal_x: 1.4286, percentile: 68,
          recent_5m_activity: [{ window_timestamp: '2026-08-25T12:35:00+05:30', activity: 250000 }, { window_timestamp: '2026-08-25T12:40:00+05:30', activity: 300000 }],
          previous_session_high: 780000, new_session_extreme: false, state_label: 'PUT LONG UNWINDING',
          breadth: { count: 2, total: 5, valid: 5 }, read: 'NORMAL', window_closed_at: '2026-08-25T12:40:00+05:30',
          top_strike: { security_id: '61670', strike: 24250, option_type: 'PE', activity_5m: 120000, percentile: 72, state: 'LONG UNWINDING', new_5m_high: false, squeeze: false },
        },
        price_oi_response: { nifty_price_change_2m: 36, price_speed_percentile: 96, call_oi_percentile: 99, put_oi_percentile: 68, call_timing: 'FOLLOWED BY 32s', put_timing: 'NO CLEAR FOLLOW', read: 'OI ACTIVITY AT SESSION HIGH' },
        nifty_book: { scope: 'GLOBAL NIFTY FUTURES BOOK PRESSURE', direction: 'BUY', mlofi: 0.31, pressure_x: 3.8 },
        activity_release: { price_speed_percentile: 96, oi_activity_percentile: 99, straddle_activity_percentile: 83, book_pressure_direction: 'BUY', book_pressure_x: 3.8, read: 'OI ACTIVITY AT SESSION HIGH' },
        alerts: [{ event_id: '2026-08-25:61605:12:40:WRITER_SQUEEZE', event_type: 'WRITER_SQUEEZE', side: 'CE', title: 'CALL SHORT-COVERING SURGE', detail: 'SHORT COVERING · NEW 5M HIGH' }],
      },
    }
    const html = renderToStaticMarkup(<PhotonicSuddenOiIntelligence intelligence={intelligence} />)
    expect(html).toContain('SUDDEN OI · CALL · ATM ±2')
    expect(html).toContain('SUDDEN OI · PUT · ATM ±2')
    expect(html).toContain('8.9L')
    expect((html.match(/PREVIOUS 5M/g) ?? []).length).toBe(2)
    expect(html).toContain('6L')
    expect(html).toContain('2.5L')
    expect((html.match(/VS NORMAL/g) ?? []).length).toBe(2)
    expect(html).toContain('6.36X')
    expect(html).toContain('1.43X')
    expect((html.match(/SESSION 5M TRACK/g) ?? []).length).toBe(2)
    expect(html).toContain('12:35')
    expect(html).toContain('6.2L → 8.9L ↑')
    expect(html).toContain('24,300 CE')
    expect(html).toContain('CALL SHORT-COVERING SURGE')
    expect(html).toContain('PRICE ↔ OI RESPONSE')
    expect(html).toContain('NIFTY BUY BOOK PRESSURE 3.8X')
    expect(html).toContain('GLOBAL NIFTY FUTURES BOOK PRESSURE')

    const [frame] = suddenOiAlertFrames(intelligence)
    const seen = new Set<string>()
    const event = { kind: 'ENTRY' as const, key: frame.eventId, title: frame.title, detail: frame.detail, reason: '', tone: 'positive' as const }
    expect(acceptSemanticEvent(seen, event)).toBe(true)
    expect(acceptSemanticEvent(seen, event)).toBe(false)
  })
})
