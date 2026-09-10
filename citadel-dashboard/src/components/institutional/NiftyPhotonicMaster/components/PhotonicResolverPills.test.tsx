import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { PhotonicCallCard } from './PhotonicCallCard'
import { PhotonicPutCard } from './PhotonicPutCard'
import { OracleOptionDisplay } from '@/dashboard/store/oracleStore'

const makeOption = (side: 'CE' | 'PE', overrides: Partial<OracleOptionDisplay> = {}): OracleOptionDisplay => ({
  contract: { securityId: side === 'CE' ? '61647' : '61703', strike: side === 'CE' ? 24200 : 24300, optionType: side },
  contractStatus: 'CURRENT_ITM1',
  quoteSecurityId: side === 'CE' ? '61647' : '61703',
  vobSecurityId: side === 'CE' ? '61647' : '61703',
  premium: 125.5,
  bid: 125.0,
  ask: 126.0,
  quoteTimestamp: '2026-08-21T10:00:00+05:30',
  freshness: 'RECEIVED',
  quoteSource: 'DHAN',
  vobTimeframe: '3m',
  zoneTop: 130,
  zoneBottom: 120,
  zoneState: 'SUPPORT_GONE',
  zoneRole: 'SUPPORT',
  zoneSource: 'CANONICAL',
  zonePrimary: true,
  distancePoints: 0,
  distancePct: 0,
  insideZone: true,
  nearestZoneBoundary: 120,
  relation: 'INSIDE',
  dayPriceChange: 5.0,
  previousClose: 120.0,
  openingPrice: 122.0,
  dayChangePct: 4.1,
  oi: 9120000,
  openingOi: 9290000,
  changeOi: 710000,
  changeOiPct: 7.8,
  positioning: 'LONG_BUILDUP',
  derivedPositioning: 'LONG_BUILDUP',
  positioningFormula: 'OI_UP_PRICE_UP',
  positioningAgreement: 'AGREED',
  oi5mChange: null,
  oi15mChange: null,
  ...overrides,
})

describe('PhotonicResolverPills presentation certification', () => {
  it('1. Renders FULL_FRESH mint variant with dynamic label on Call card', () => {
    const opt = makeOption('CE', {
      resolverEvent: {
        label: 'RES OUT 3M+5M · FLOW 3.2X',
        semanticDirection: 'BULLISH',
        variant: 'mint',
        confluenceState: 'FULL_FRESH',
        pulseKey: '61647_EV5M_1',
        sourceEventTime: '2026-08-21T10:00:00+05:30',
        heldPrevious: false,
      },
    })
    const html = renderToStaticMarkup(<PhotonicCallCard option={opt} />)
    expect(html).toContain('RES OUT 3M+5M · FLOW 3.2X')
    expect(html).toContain('pillMint')
    expect(html).toContain('box-shadow')
  })

  it('2. Renders FULL_FRESH red variant with dynamic label on Put card', () => {
    const opt = makeOption('PE', {
      resolverEvent: {
        label: 'SUPPORT GONE 3M · FLOW 4.1X',
        semanticDirection: 'BEARISH',
        variant: 'red',
        confluenceState: 'FULL_FRESH',
        pulseKey: '61703_EV3M_1',
        sourceEventTime: '2026-08-21T10:05:00+05:30',
        heldPrevious: false,
      },
    })
    const html = renderToStaticMarkup(<PhotonicPutCard option={opt} />)
    expect(html).toContain('SUPPORT GONE 3M · FLOW 4.1X')
    expect(html).toContain('pillRed')
    expect(html).toContain('box-shadow')
  })

  it('3. Renders ALIGNED_SETTLED mint variant without extra glow on Call card', () => {
    const opt = makeOption('CE', {
      resolverEvent: {
        label: 'SUPPORT GONE 3M',
        semanticDirection: 'BULLISH',
        variant: 'mint',
        confluenceState: 'ALIGNED_SETTLED',
        pulseKey: '61647_EV3M_SETTLED',
        sourceEventTime: '2026-08-21T10:00:00+05:30',
        heldPrevious: true,
      },
    })
    const html = renderToStaticMarkup(<PhotonicCallCard option={opt} />)
    expect(html).toContain('SUPPORT GONE 3M')
    expect(html).toContain('pillMint')
    expect(html).not.toContain('box-shadow:0 0 14px')
  })

  it('4. Renders MIXED amber variant on Call card', () => {
    const opt = makeOption('CE', {
      resolverEvent: {
        label: 'VOB ALIGN 1M+3M ↑',
        semanticDirection: 'NEUTRAL',
        variant: 'amber',
        confluenceState: 'MIXED',
        pulseKey: '61647_EV_MIXED',
        sourceEventTime: '2026-08-21T10:00:00+05:30',
        heldPrevious: false,
      },
    })
    const html = renderToStaticMarkup(<PhotonicCallCard option={opt} />)
    expect(html).toContain('VOB ALIGN 1M+3M ↑')
    expect(html).toContain('pillAmber')
  })

  it('5. Renders IDLE cyan variant with strike label', () => {
    const opt = makeOption('CE', {
      resolverEvent: {
        label: 'ACTIVE RESOLVER · 24,200 CE',
        semanticDirection: 'INFO',
        variant: 'cyan',
        confluenceState: 'IDLE',
        pulseKey: '61647_REV_1',
        sourceEventTime: '2026-08-21T10:00:00+05:30',
        heldPrevious: true,
      },
    })
    const html = renderToStaticMarkup(<PhotonicCallCard option={opt} />)
    expect(html).toContain('ACTIVE RESOLVER · 24,200 CE')
    expect(html).toContain('pillCyan')
  })

  it('6. Falls back to default ACTIVE RESOLVER when resolverEvent is null', () => {
    const opt = makeOption('CE', { resolverEvent: null })
    const html = renderToStaticMarkup(<PhotonicCallCard option={opt} />)
    expect(html).toContain('ACTIVE RESOLVER')
  })

  it('7. Renders longest approved multi-TF shock labels without distortion or clipping', () => {
    const longLabels = [
      'SUPPORT GONE 3M+5M · FLOW 4.1X',
      'RES OUT 3M+5M · FLOW 3.2X',
      'SHORT BUILD · OI 2.8X',
      'FULL VOB ALIGN ↑',
    ]
    for (const label of longLabels) {
      const opt = makeOption('CE', {
        resolverEvent: {
          label,
          semanticDirection: 'BULLISH',
          variant: 'mint',
          confluenceState: 'FULL_FRESH',
          pulseKey: '61647_EV_LONG',
          sourceEventTime: '2026-08-21T10:00:00+05:30',
          heldPrevious: false,
        },
      })
      const html = renderToStaticMarkup(<PhotonicCallCard option={opt} />)
      expect(html).toContain(label)
      expect(html).toContain('pillMint')
    }
  })
})
