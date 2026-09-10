import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { OracleOptionDisplay } from '@/dashboard/store/oracleStore'
import { PhotonicCallCard } from './PhotonicCallCard'
import { PhotonicOptionBuyerIntelligence } from './PhotonicOptionBuyerIntelligence'
import { PhotonicOracleHeroWheel } from './PhotonicOracleHeroWheel'
import { PhotonicPutCard } from './PhotonicPutCard'

// Exact model output produced from the first two genuine 19-Aug records in:
// logs/strategy_command/argus_edge_lab/market_snapshots.jsonl
// Observed at 14:01:52 and 14:01:59 IST; never injected into the live store.
const recordedObi = {
  status: 'MODEL_DERIVED_RESEARCH',
  source_timestamp: '2026-08-19T14:01:59.456871+05:30',
  provenance: 'RECORDED_20260819_ARGUS_EDGE_MARKET_SNAPSHOT',
  CE: {
    fair_price: 165.74, ask: 156, bid: 155.75, comparison: 'BELOW_FAIR', below_fair_pct: 5.88,
    time_loss_expected: -0, actual_change: -0.9, premium_holding: -0.9,
    flow: { buying_volume: null, selling_volume: null, net_flow: null, imbalance: null, activity_normal: null },
    book: { biggest_buy_orders: null, biggest_sell_orders: null, most_traded_price: null, current_vs_most_traded: null, my_buy_price: null },
    quality: { valid: true, fair_iv_method: 'NEIGHBOUR_INTERPOLATION_EXCLUDING_TARGET' },
  },
  PE: {
    fair_price: 123.34, ask: 137.05, bid: 136.85, comparison: 'INFLATED', extra_paying: 13.71, inflated_pct: 11.12,
    time_loss_expected: -0, actual_change: 1.05, premium_holding: 1.05,
    flow: { buying_volume: null, selling_volume: null, net_flow: null, imbalance: null, activity_normal: null },
    book: { biggest_buy_orders: null, biggest_sell_orders: null, most_traded_price: null, current_vs_most_traded: null, my_buy_price: null },
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

  it('renders Fair and Premium Holding/Decay rails from genuine recorded data while keeping microstructure unavailable', () => {
    const html = renderToStaticMarkup(<PhotonicOptionBuyerIntelligence side="CE" intelligence={recordedObi} />)
    expect((html.match(/data-obi-rail/g) ?? []).length).toBe(2)
    expect(html).toContain('FAIR ₹165.74')
    expect(html).toContain('₹0.90 WEAKER')
    expect(html).toContain('FLOW TAPE UNAVAILABLE')
    expect(html).toContain('BUYING VOL')
    expect(html).not.toContain('50/50')
  })

  it('keeps the recorded Straddle factual and Fit/Lean uninvented', () => {
    const straddle = renderToStaticMarkup(<PhotonicOracleHeroWheel presentation="STRADDLE" intelligence={recordedObi} />)
    const fit = renderToStaticMarkup(<PhotonicOracleHeroWheel presentation="FIT" intelligence={recordedObi} />)
    expect(straddle).toContain('RISING')
    expect(straddle).toContain('~239.35 pts')
    expect(straddle).toContain('PREMIUM DRIVER')
    expect(straddle).toContain('VWAP')
    expect(fit).toContain('— / 5')
    expect(fit).toContain('CURRENT LEAN')
  })
})
