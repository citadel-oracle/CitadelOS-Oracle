import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { DashboardFeedMeta, DashboardFeedState } from '@/dashboard/types'
import { GeminiMarketBrainSection } from './GeminiMarketBrainSection'
import { selectOracleDeterministicSensors } from './oracleDeterministicSensors'

// Read-only subset captured from GET /v1/oracle/fast-lane revision 1087 on
// 2026-09-02. Values are genuine session records, not generated test prices.
const recordedArgus = {
  data: {
    underlying: {
      atm_strike: 23900,
      ltp: 23914.45,
      market_state: 'CLOSED',
      source_event_time: '2026-09-02T15:39:53+05:30',
      trading_date: '2026-09-02',
    },
    argus_market_snapshot: {
      source: 'DHAN_V2_MARKETFEED_FULL_PLUS_DHAN_V2_OPTION_CHAIN',
      futures: {
        ltp: 23994.8,
        basis: 80.34999999999854,
        quote_source: 'DHAN_V2_MARKETFEED_QUOTE',
        source_timestamp: '2026-09-02T15:39:59+05:30',
      },
    },
    totals: {
      ce_oi: 147677855,
      pe_oi: 107537170,
      ce_change_oi: 43432155,
      pe_change_oi: 35430655,
      pcr: 0.7282,
    },
    tactical_edge: {
      previous_oi: {
        call_wall: 24200,
        put_wall: 23800,
        current_scope: { observation_timestamp: '2026-09-02T15:10:26.162533+05:30' },
      },
      argus_prime: {
        freshness: 'STALE',
        live_pcr: {
          oi_pcr: 0.7282,
          total_call_oi: 147677855,
          total_put_oi: 107537170,
          source: 'ARGUS_DHAN_FULL_CHAIN_TOTALS',
          source_timestamp: '2026-09-02T15:10:24+05:30',
        },
      },
    },
    atm_window: [{
      strike: 23900,
      ce: {
        ltp: 131.6,
        top_bid_price: 130.15,
        top_ask_price: 131.6,
        activity: 'CALL_LONG_UNWINDING',
      },
      pe: {
        ltp: 114.4,
        top_bid_price: 114.4,
        top_ask_price: 115,
        activity: 'PUT_LONG_UNWINDING',
      },
    }],
  },
}

const recordedOptionBuyer = {
  status: 'LIVE',
  provenance: 'CANONICAL_ARGUS_DHAN_OPTION_CHAIN + DHAN_FULL_QUOTE + EXISTING_FUTURES',
  CE: {
    spread: 0.75,
    market_pressure: { source_timestamp: '2026-09-02T15:39:59+05:30' },
  },
  PE: {
    spread: 0.9,
    market_pressure: { source_timestamp: '2026-09-02T15:39:59+05:30' },
  },
  straddle: { now: 250.2, actual_change: null, state: 'RISING' },
  option_intelligence: {
    status: 'LIVE',
    volatility_opportunity: { atm_iv: 9.92 },
    iv_skew: { skew_25d_spread: 2.61, skew_10d_spread: 2.88 },
    gex: { total_net_gex_inr_cr: 53.11, zero_gamma_strike: 23865.6 },
  },
  fit: {
    call_evidence: null,
    put_evidence: null,
    state: 'NO_CLEAN_FIT',
    provenance: 'NO_INVENTED_FIT_FORMULA',
  },
}

const meta = (health: string): DashboardFeedMeta => ({
  health,
  readiness: health === 'HEALTHY' ? 'READY' : 'DEGRADED',
  latency_ms: 0,
  last_updated: '2026-09-02T15:39:59+05:30',
  source_last_updated: '2026-09-02T15:39:59+05:30',
})

const feed = (data: unknown): DashboardFeedState<unknown> => ({
  data,
  error: null,
  lastUpdated: new Date('2026-09-02T15:39:59+05:30'),
  loading: false,
})

describe('Oracle deterministic Fast Lane sensor selector', () => {
  it('renders recorded deterministic values while Gemini is unavailable', () => {
    const html = renderToStaticMarkup(
      <GeminiMarketBrainSection
        argusFeed={feed(recordedArgus)}
        futuresFeed={feed({ market_status: 'MARKET_CLOSED' })}
        optionBuyerFeed={feed(recordedOptionBuyer)}
        orderFlowFeed={feed({ status: 'UNAVAILABLE', cvd: 0 })}
        sensorFeedMeta={{
          argus: meta('STALE'),
          futuresChart: meta('STALE'),
          optionBuyerIntelligence: meta('HEALTHY'),
          orderFlow: meta('OFFLINE'),
        }}
        dashboardRevision={1087}
      />,
    )

    expect(html).toContain('data-sensor-id="pcr_oi"')
    expect(html).toContain('data-citadel-value="0.7282"')
    expect(html).toContain('₹250.20 · RISING')
    expect(html).toContain('data-citadel-value="53.11"')
    expect(html).toContain('data-citadel-status="SESSION_LAST"')
    expect(html).not.toContain('data-citadel-status="LIVE"')
    expect(html).toContain('Live analysis unavailable.')
  })

  it('keeps session-final values and labels them SESSION_LAST after close', () => {
    const sensors = selectOracleDeterministicSensors({
      argus: recordedArgus,
      optionBuyerIntelligence: recordedOptionBuyer,
      argusMeta: meta('STALE'),
      optionBuyerMeta: meta('HEALTHY'),
      revision: 1087,
    })

    expect(sensors.marketClosed).toBe(true)
    expect(sensors.readings.nifty_spot.value).toBe(23914.45)
    expect(sensors.readings.nifty_spot.status).toBe('SESSION_LAST')
    expect(sensors.readings.pcr_oi.status).toBe('SESSION_LAST')
    expect(sensors.readings.straddle.status).toBe('SESSION_LAST')
    expect(sensors.readings.atm_iv.status).toBe('SESSION_LAST')
  })

  it('renders backend null as unavailable and does not expose unavailable CVD zero', () => {
    const sensors = selectOracleDeterministicSensors({
      argus: null,
      optionBuyerIntelligence: null,
      orderFlow: { status: 'UNAVAILABLE', cvd: 0 },
      orderFlowMeta: meta('OFFLINE'),
      revision: 1088,
    })

    expect(sensors.readings.pcr_oi.status).toBe('UNAVAILABLE')
    expect(sensors.readings.pcr_oi.display).toBe('—')
    expect(sensors.readings.cvd.status).toBe('UNAVAILABLE')
    expect(sensors.readings.cvd.value).toBeNull()
  })

  it('rejects a stale open-market value instead of showing it as live', () => {
    const openArgus = {
      ...recordedArgus,
      data: {
        ...recordedArgus.data,
        underlying: { ...recordedArgus.data.underlying, market_state: 'OPEN' },
      },
    }
    const sensors = selectOracleDeterministicSensors({
      argus: openArgus,
      argusMeta: meta('STALE'),
      revision: 1089,
    })

    expect(sensors.readings.pcr_oi.status).toBe('UNAVAILABLE')
    expect(sensors.readings.pcr_oi.value).toBeNull()
    expect(sensors.readings.nifty_spot.status).toBe('UNAVAILABLE')
  })

  it('keeps explicitly available live fields visible during a coarse ARGUS advisory', () => {
    const openArgus = {
      ...recordedArgus,
      data: {
        ...recordedArgus.data,
        underlying: {
          ...recordedArgus.data.underlying,
          market_state: 'OPEN',
          baseline_status: 'AVAILABLE',
        },
        argus_market_snapshot: {
          ...recordedArgus.data.argus_market_snapshot,
          futures: {
            ...recordedArgus.data.argus_market_snapshot.futures,
            status: 'AVAILABLE',
          },
        },
        tactical_edge: {
          ...recordedArgus.data.tactical_edge,
          argus_prime: {
            ...recordedArgus.data.tactical_edge.argus_prime,
            live_pcr: {
              ...recordedArgus.data.tactical_edge.argus_prime.live_pcr,
              status: 'AVAILABLE',
              freshness: 'FRESH',
            },
          },
        },
      },
    }
    const sensors = selectOracleDeterministicSensors({
      argus: openArgus,
      argusMeta: meta('DEGRADED'),
      revision: 1090,
    })

    expect(sensors.readings.nifty_spot.value).toBe(23914.45)
    expect(sensors.readings.nifty_spot.status).toBe('LIVE')
    expect(sensors.readings.nifty_futures.status).toBe('LIVE')
    expect(sensors.readings.futures_basis.status).toBe('LIVE')
    expect(sensors.readings.pcr_oi.status).toBe('LIVE')
    expect(sensors.readings.total_oi.status).toBe('LIVE')
  })

  it('uses the exact OI PCR, straddle, IV, skew, and GEX producer paths', () => {
    const sensors = selectOracleDeterministicSensors({
      argus: recordedArgus,
      optionBuyerIntelligence: recordedOptionBuyer,
      revision: 1090,
    }).readings

    expect(sensors.pcr_oi.value).toBe(0.7282)
    expect(sensors.pcr_oi.backendPath).toContain('live_pcr.oi_pcr')
    expect(sensors.straddle.value).toBe(250.2)
    expect(sensors.atm_iv.value).toBe(9.92)
    expect(sensors.skew_25d.value).toBe(2.61)
    expect(sensors.skew_10d.value).toBe(2.88)
    expect(sensors.net_gex.value).toBe(53.11)
    expect(sensors.zero_gamma.value).toBe(23865.6)
    expect(sensors.expected_move.status).toBe('NOT_IMPLEMENTED')
  })

  it('keeps Order Flow independent of Gemini and preserves numeric zero', () => {
    const sensors = selectOracleDeterministicSensors({
      argus: {
        data: {
          underlying: {
            market_state: 'OPEN',
            trading_date: '2026-09-02',
          },
        },
      },
      orderFlow: {
        status: 'AVAILABLE',
        directional_state: 'NEUTRAL',
        generated_at: '2026-09-02T09:45:00+00:00',
        cvd: 0,
        family_values: {
          BOOK_PRESSURE: { status: 'AVAILABLE', mlofi: 0, book_pressure: 0 },
          LOCATION: { cvd: 0 },
        },
      },
      orderFlowMeta: meta('HEALTHY'),
      revision: 1091,
    }).readings

    expect(sensors.order_flow.status).toBe('LIVE')
    expect(sensors.mlofi.value).toBe(0)
    expect(sensors.cvd.value).toBe(0)
    expect(sensors.book_pressure.value).toBe(0)
  })

  it('correctly attributes Upstox provider provenance and activates sensors in Upstox fallback', () => {
    const sensors = selectOracleDeterministicSensors({
      argus: {
        data: {
          underlying: {
            atm_strike: 23800,
            ltp: 23779.15,
            market_state: 'OPEN',
            source: 'UPSTOX',
            source_event_time: '2026-09-07T15:30:00+05:30',
            trading_date: '2026-09-07',
            status: 'AVAILABLE',
          },
          totals: {
            ce_oi: 262194335,
            pe_oi: 147901195,
            ce_change_oi: 5000000,
            pe_change_oi: 3000000,
            pcr: 0.5641,
          },
          verdict: {
            call_wall: { strike: 24000 },
            put_wall: { strike: 23500 },
          },
          atm_window: [{
            strike: 23800,
            ce: { ltp: 150.0, top_bid_price: 149.5, top_ask_price: 150.5, activity: 'CALL_WRITING' },
            pe: { ltp: 120.0, top_bid_price: 119.5, top_ask_price: 120.5, activity: 'PUT_WRITING' },
          }],
        },
      },
      argusMeta: meta('HEALTHY'),
      revision: 2001,
    }).readings

    expect(sensors.nifty_spot.value).toBe(23779.15)
    expect(sensors.nifty_spot.source).toBe('UPSTOX')
    expect(sensors.nifty_spot.status).toBe('LIVE')
    expect(sensors.pcr_oi.value).toBe(0.5641)
    expect(sensors.pcr_oi.source).toBe('UPSTOX')
    expect(sensors.pcr_oi.status).toBe('LIVE')
    expect(sensors.call_put_wall.value).toBe('24,000 / 23,500')
    expect(sensors.call_put_wall.status).toBe('LIVE')
    expect(sensors.total_oi.value).toBe('26,21,94,335 / 14,79,01,195')
    expect(sensors.total_oi.status).toBe('LIVE')
  })
})
