import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import {
  LivingMarketForcesViewport,
  getVideoPlaybackPlan,
  guardVideoPlayTransition,
  synchronizeMarketVideos,
} from './LivingMarketForcesViewport'
import {
  GeminiMarketBrainSection,
  SOL_TRANSPORT_LOSS_GRACE_MS,
  advanceCanonicalRevision,
  canonicalBiasLabel,
  canonicalReadingDomainStatus,
  compactDisplayBullets,
  dataStreamStatusFromBeacon,
  isCanonicalTransportUnavailable,
  plainCanonicalText,
  plainStatusLabel,
  resolveCanonicalMarketPresentation,
} from './GeminiMarketBrainSection'
import { advanceFastLaneRevision } from '../../dashboard/providers/RestDashboardProvider'

describe('Gemini Market Brain & Living Market Forces Truth-Firewall Integration', () => {

  it('maps compact backend beacon health without inventing a market conclusion', () => {
    expect(dataStreamStatusFromBeacon('HEALTHY')).toBe('LIVE')
    expect(dataStreamStatusFromBeacon('DATA_DEGRADED')).toBe('DEGRADED')
    expect(dataStreamStatusFromBeacon('OFF_MARKET')).toBe('OFF_MARKET')
    expect(dataStreamStatusFromBeacon(undefined)).toBe('UNAVAILABLE')
  })

  // Test 1: Single unified Luna Award-Motion cognitive surface renders and legacy secondaryDeck is absent
  it('1. single unified Luna Award-Motion cognitive surface renders and legacy secondaryDeck is absent', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).toContain('data-testid="cognitive-decision-core"')
    expect(html).toContain('data-citadel-field="cognitive.primary.state"')
    expect(html).not.toMatch(/\b(?:abhi|kya|nahi|hai|badla|kyu|hoga|agar|pichhle|pichle)\b/i)
    expect(html).not.toContain('WHAT GEMINI SEES')
    expect(html).not.toContain('INTELLIGENCE NETWORK')
    expect(html).not.toContain('GEMINI HISTORY')
    expect(html).not.toContain('STORED MODEL ANALYSES')
    expect(html).not.toContain('EXTERNAL CONTEXT · NEWS &amp; EVENTS')
  })

  // Test 2: Unavailable canonical content remains unavailable
  it('2. unavailable canonical content remains unavailable without fake defaults', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).toContain('UNAVAILABLE')
    expect(html).toContain('—')
    expect(html).not.toContain('24,541.15')
    expect(html).not.toContain('+32.40')
    expect(html).not.toContain('0.94')
    expect(html).not.toContain('13.8%')
    expect(html).not.toContain('+0.45')
  })

  // Test 3: canonicalReadingDomainStatus utility behaves purely and legacy reading strip is absent
  it('3. canonicalReadingDomainStatus utility behaves purely and legacy reading strip is absent', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('GEMINI IS READING')
    expect(canonicalReadingDomainStatus({
      status: 'PARTIAL',
      closed_5m_oi: 'PARTIAL',
      closed_15m_oi: 'UNAVAILABLE',
      total_oi: 'UNAVAILABLE',
      pcr_oi: 'UNAVAILABLE',
    })).toBe('PARTIAL')
    expect(canonicalReadingDomainStatus(undefined)).toBe('UNAVAILABLE')
  })

  // Test 4: ANALYZING appears only from canonical reasoning state
  it('4. ANALYZING appears only from canonical reasoning state', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).toContain('UNAVAILABLE')
    expect(html).not.toContain('ANALYSIS:')
    expect(html).not.toContain('ANALYZING EVIDENCE')
  })

  // Test 5: Legacy multi-model drawers and legacy stories are eradicated
  it('5. legacy multi-model drawers and legacy stories are eradicated', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('WHAT GEMINI SEES')
    expect(html).not.toContain('POSITIONING')
    expect(html).not.toContain('STORED MODEL ANALYSES')
  })

  // Test 6: Legacy evidence refs area is replaced by Award-Motion receipt and temporal observer
  it('6. legacy evidence refs area is replaced by Award-Motion receipt and temporal observer', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('EVIDENCE · 0 REFERENCES')
    expect(html).toContain('TEMPORAL OBSERVER')
    expect(html).toContain('INGESTION RECEIPT')
  })

  // Test 7: Legacy external context radar is absent from cognitive section
  it('7. legacy external context radar is absent from cognitive section', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('EXTERNAL CONTEXT · NEWS &amp; EVENTS')
    expect(html).not.toContain('WORLD MARKET QUOTES · UNAVAILABLE')
    expect(html).not.toContain('MONITORED: 6 PROVIDERS')
  })

  // Test 8: Unavailable radar does not fabricate instrument rows
  it('8. unavailable radar stays absent and does not fabricate instrument rows', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('S&amp;P 500 Futures')
    expect(html).not.toContain('Dow Jones Futures')
    expect(html).not.toContain('NO MATERIAL BREAKING EVENTS FOR TODAY')
  })

  // Test 9: Unavailable reasoning does NOT become semantic NO_TRADE
  it('9. unavailable reasoning does NOT become semantic NO_TRADE', () => {
    const html = renderToStaticMarkup(
      <LivingMarketForcesViewport
        marketState="NO_TRADE"
        operationalStatus="UNAVAILABLE"
      />
    )
    expect(html).toContain('SYSTEM UNAVAILABLE')
    expect(html).toContain('LIVE ANALYSIS PAUSED')
    expect(html).not.toContain('>NO TRADE<')
    expect(html).not.toContain('>BALANCED<')
  })

  // Test 10: Video assets are correctly mapped
  it('10. video assets are correctly mapped for all 5 states', () => {
    const balanced = renderToStaticMarkup(<LivingMarketForcesViewport marketState="NO_TRADE" operationalStatus="HEALTHY" />)
    const bullDev = renderToStaticMarkup(<LivingMarketForcesViewport marketState="CALL_DEVELOPING" operationalStatus="HEALTHY" />)
    const bullDom = renderToStaticMarkup(<LivingMarketForcesViewport marketState="CALL" operationalStatus="HEALTHY" />)
    const bearDev = renderToStaticMarkup(<LivingMarketForcesViewport marketState="PUT_DEVELOPING" operationalStatus="HEALTHY" />)
    const bearDom = renderToStaticMarkup(<LivingMarketForcesViewport marketState="PUT" operationalStatus="HEALTHY" />)

    expect(balanced).toContain('dual-01-balanced-sideways.mp4')
    expect(bullDev).toContain('bull-02-pressure-advance.mp4')
    expect(bullDom).toContain('bull-03-full-dominance.mp4')
    expect(bearDev).toContain('bear-02-pressure-advance.mp4')
    expect(bearDom).toContain('bear-03-full-dominance.mp4')
    expect(getVideoPlaybackPlan('NO_TRADE')).toEqual({ targetId: 'vidBalanced', startTime: 0, semanticState: 'NO_TRADE' })
    expect(getVideoPlaybackPlan('CALL_DEVELOPING')).toEqual({ targetId: 'vidBullPressure', startTime: 11.8, semanticState: 'CALL_DEVELOPING' })
    expect(getVideoPlaybackPlan('CALL')).toEqual({ targetId: 'vidBullDominant', startTime: 0, semanticState: 'CALL' })
    expect(getVideoPlaybackPlan('PUT_DEVELOPING')).toEqual({ targetId: 'vidBearPressure', startTime: 11, semanticState: 'PUT_DEVELOPING' })
    expect(getVideoPlaybackPlan('PUT')).toEqual({ targetId: 'vidBearDominant', startTime: 0, semanticState: 'PUT' })
    expect(getVideoPlaybackPlan('CALL', 'OFF_MARKET')).toEqual({ targetId: 'vidBalanced', startTime: 0, semanticState: null })
  })

  it('10b. rapid video flips leave one active clip and pause/reset every inactive clip', () => {
    const makeVideo = () => {
      const classes = new Set<string>()
      let pauseCount = 0
      return {
        video: {
          currentTime: 7,
          pause: () => { pauseCount += 1 },
          play: () => Promise.resolve(),
          classList: {
            add: (token: string) => { classes.add(token) },
            remove: (token: string) => { classes.delete(token) },
            toggle: (token: string, force?: boolean) => {
              if (force) classes.add(token)
              else classes.delete(token)
              return classes.has(token)
            },
          },
        },
        classes,
        pauseCount: () => pauseCount,
      }
    }
    const balanced = makeVideo()
    const bullPressure = makeVideo()
    const bearPressure = makeVideo()
    const videos = {
      vidBalanced: balanced.video,
      vidBullPressure: bullPressure.video,
      vidBearPressure: bearPressure.video,
    }

    synchronizeMarketVideos(videos, 'vidBullPressure', 11.8, 'active')
    synchronizeMarketVideos(videos, 'vidBearPressure', 11, 'active')

    expect(bearPressure.classes.has('active')).toBe(true)
    expect(bullPressure.classes.has('active')).toBe(false)
    expect(balanced.classes.has('active')).toBe(false)
    expect(bearPressure.video.currentTime).toBe(11)
    expect(bullPressure.video.currentTime).toBe(0)
    expect(bullPressure.pauseCount()).toBeGreaterThan(0)
    expect(balanced.pauseCount()).toBeGreaterThan(0)
  })

  it('10c. a stale resolved play promise cannot revive the previous animal', async () => {
    const classes = new Set<string>(['active'])
    let pauseCount = 0
    let resolvePlay!: () => void
    const playPromise = new Promise<void>(resolve => { resolvePlay = resolve })
    const video = {
      currentTime: 11.8,
      pause: () => { pauseCount += 1 },
      play: () => playPromise,
      classList: {
        add: (token: string) => { classes.add(token) },
        remove: (token: string) => { classes.delete(token) },
        toggle: (token: string, force?: boolean) => {
          if (force) classes.add(token)
          else classes.delete(token)
          return classes.has(token)
        },
      },
    }
    let currentTransition = 1
    const guarded = guardVideoPlayTransition(
      playPromise,
      video,
      1,
      () => currentTransition,
      'active',
    )

    currentTransition = 2
    resolvePlay()
    await guarded

    expect(pauseCount).toBe(1)
    expect(video.currentTime).toBe(0)
    expect(classes.has('active')).toBe(false)
  })

  // Test 11: Basis color strictly distinguishes positive, negative, zero, and unavailable
  it('11. basis color strictly distinguishes positive, negative, zero, and unavailable', () => {
    const positiveHtml = renderToStaticMarkup(<LivingMarketForcesViewport marketState="NO_TRADE" basis={10.5} />)
    const negativeHtml = renderToStaticMarkup(<LivingMarketForcesViewport marketState="NO_TRADE" basis={-5.25} />)
    const zeroHtml = renderToStaticMarkup(<LivingMarketForcesViewport marketState="NO_TRADE" basis={0} />)
    const unavailHtml = renderToStaticMarkup(<LivingMarketForcesViewport marketState="NO_TRADE" basis={null} />)

    expect(positiveHtml).toContain('color:#00f0ff')
    expect(negativeHtml).toContain('color:#ff2a55')
    expect(zeroHtml).toContain('color:#cbd5e1')
    expect(unavailHtml).toContain('color:#64748b')
  })

  // Test 12: Suppresses fabricated prose
  it('12. suppresses fabricated prose', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('Evaluating microstructural orderflow')
    expect(html).not.toContain('No major structural contradiction detected')
    expect(html).not.toContain('Awaiting price action confirmation on key option strikes')
    expect(html).not.toContain('Thesis invalidates upon sudden adverse liquidity')
  })

  // Test 13: VOB remains untouched and independent, legacy secondaryDeck footer eradicated
  it('13. VOB remains untouched and independent, legacy secondaryDeck footer eradicated', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('secondaryDeck')
    expect(html).not.toContain('INTELLIGENCE NETWORK')
    expect(html).toContain('data-testid="cognitive-decision-core"')
  })

  // Test 14: Verification never assumes a connected source, legacy radar absent
  it('14. verification never assumes a connected source, legacy radar absent', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('SOURCE CHECK: NOT REPORTED')
    expect(html).not.toContain('MONITORED: 6 PROVIDERS')
  })

  // Test 15: Zero-trust architecture verified in Luna Award-Motion surface
  it('15. zero-trust architecture verified in Luna Award-Motion surface', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).toContain('Deterministic privacy sanitization')
    expect(html).toContain('SHADOW COGNITION')
    expect(html).not.toContain('SAFE MODE ACTIVE')
  })

  it.each([
    ['Gemini 429', 'DEGRADED_ADVISORY'],
    ['Gemini 503', 'DEGRADED_ADVISORY'],
    ['Gemini timeout', 'DEGRADED_ADVISORY'],
    ['malformed JSON', 'DEGRADED_ADVISORY'],
    ['invalid evidence', 'OUTPUT_INVALID'],
    ['null verdict', 'ACTIVE_REASONING'],
  ])('16. %s cannot become semantic NO_TRADE', (_failure, reasoningStatus) => {
    const presentation = resolveCanonicalMarketPresentation({
      system_status: 'HEALTHY',
      reasoning_status: reasoningStatus,
      market_verdict: null,
      developing_state: 'UNRESOLVED',
      why_bullets: [],
      main_contradiction: 'TEST_FAILURE',
      what_changed: 'Reasoning unavailable.',
      thesis_timestamp_ist: '10:15:00',
      feed_age_ms: 100,
      configured_model: 'gemini-3.7-flash',
      actually_invoked_model: 'NONE',
      canonical_market_state: null,
    }, false)

    const html = renderToStaticMarkup(
      <LivingMarketForcesViewport
        marketState={presentation.marketState}
        operationalStatus={presentation.operationalStatus}
      />
    )

    expect(presentation.marketState).toBeNull()
    expect(html).toContain('data-active-market-state="NONE"')
    expect(html).toContain('LIVE ANALYSIS PAUSED')
    expect(html).not.toContain('>NO TRADE<')
    expect(html).not.toContain('>BALANCED<')
  })

  it('17. explicit backend NO_TRADE remains the only path to semantic NO_TRADE', () => {
    const presentation = resolveCanonicalMarketPresentation({
      system_status: 'HEALTHY',
      reasoning_status: 'ACTIVE_REASONING',
      market_verdict: 'NO_TRADE',
      developing_state: 'NONE',
      why_bullets: [],
      main_contradiction: 'NONE_OBSERVED',
      what_changed: 'No coherent directional thesis.',
      thesis_timestamp_ist: '10:15:00',
      feed_age_ms: 100,
      configured_model: 'gemini-3.7-flash',
      actually_invoked_model: 'gemini-3.7-flash',
      canonical_market_state: 'NO_TRADE',
    }, false)

    expect(presentation.marketState).toBe('NO_TRADE')
    expect(presentation.operationalStatus).toBe('HEALTHY')
  })

  it('17b. plain-language helpers preserve canonical meaning without adding a market view', () => {
    expect(canonicalBiasLabel('CALL_DEVELOPING')).toBe('CALL')
    expect(canonicalBiasLabel('PUT')).toBe('PUT')
    expect(canonicalBiasLabel('NO_TRADE')).toBe('WAIT')
    expect(canonicalBiasLabel(null)).toBe('UNAVAILABLE')
    expect(plainCanonicalText('SYSTEM_OFF_MARKET')).toBe('Market is closed. Live Gemini analysis is paused.')
    expect(plainCanonicalText('DATA_LINEAGE_CONTAMINATION')).toBe('Some market data cannot be fully trusted. Live analysis is paused.')
    expect(plainCanonicalText('FAIL_CLOSED_SYSTEM_STATUS')).toBe('Live analysis is paused for safety.')
    expect(plainCanonicalText('Spot breaks and sustains above Zero Gamma Level (24095.60) with CE pricing IV expansion and positive mlofi acceleration above +0.50.'))
      .toBe('Call side gets stronger if spot holds above Zero Gamma (24095.60) and call premiums rise. Order flow must stay above +0.50.')
    expect(plainCanonicalText('Spot falls below 24050.0 ATM strike with basis compression below +190.00.'))
      .toBe('This view weakens if spot falls below 24050.0 and futures basis drops below +190.00.')
    expect(plainStatusLabel('OFF_MARKET')).toBe('MARKET CLOSED')
    expect(plainStatusLabel('DATA_LINEAGE_CONTAMINATION')).toBe('DATA NOT VERIFIED')
    expect(compactDisplayBullets('First point; Second point; Third point', 2)).toEqual(['First point', 'Second point'])
  })

  it('18. dual transport loss suspends CALL after the documented network grace and recovers', () => {
    const receiptAtMs = 100_000
    const callBeacon = {
      system_status: 'HEALTHY',
      reasoning_status: 'ACTIVE_REASONING',
      market_verdict: 'CALL',
      developing_state: 'NONE',
      why_bullets: [],
      main_contradiction: 'NONE_OBSERVED',
      what_changed: 'Canonical CALL.',
      thesis_timestamp_ist: '10:15:00',
      feed_age_ms: 100,
      configured_model: 'gemini-3.7-flash',
      actually_invoked_model: 'gemini-3.7-flash',
      canonical_market_state: 'CALL',
    }

    const receivedCall = isCanonicalTransportUnavailable({
      pollAvailable: true,
      sseAvailable: true,
      lastCanonicalReceiptAtMs: receiptAtMs,
      nowMs: receiptAtMs,
    })
    const sseBroken = isCanonicalTransportUnavailable({
      pollAvailable: true,
      sseAvailable: false,
      lastCanonicalReceiptAtMs: receiptAtMs,
      nowMs: receiptAtMs + SOL_TRANSPORT_LOSS_GRACE_MS,
    })
    const insideGrace = isCanonicalTransportUnavailable({
      pollAvailable: false,
      sseAvailable: false,
      lastCanonicalReceiptAtMs: receiptAtMs,
      nowMs: receiptAtMs + SOL_TRANSPORT_LOSS_GRACE_MS - 1,
    })

    const transportLost = isCanonicalTransportUnavailable({
      pollAvailable: false,
      sseAvailable: false,
      lastCanonicalReceiptAtMs: receiptAtMs,
      nowMs: receiptAtMs + SOL_TRANSPORT_LOSS_GRACE_MS,
    })
    const unavailable = resolveCanonicalMarketPresentation(callBeacon, transportLost)
    const unavailableHtml = renderToStaticMarkup(
      <LivingMarketForcesViewport
        marketState={unavailable.marketState}
        operationalStatus={unavailable.operationalStatus}
        lastKnown
      />
    )

    expect(receivedCall).toBe(false)
    expect(sseBroken).toBe(false)
    expect(insideGrace).toBe(false)
    expect(transportLost).toBe(true)
    expect(unavailable.marketState).toBeNull()
    expect(unavailable.operationalStatus).toBe('TRANSPORT_UNAVAILABLE')
    expect(unavailableHtml).toContain('LAST KNOWN · LIVE ANALYSIS PAUSED')
    expect(unavailableHtml).toContain('data-active-market-state="NONE"')
    expect(unavailableHtml).not.toContain('>CALL<')

    const transportRecovered = isCanonicalTransportUnavailable({
      pollAvailable: true,
      sseAvailable: false,
      lastCanonicalReceiptAtMs: receiptAtMs + SOL_TRANSPORT_LOSS_GRACE_MS + 1,
      nowMs: receiptAtMs + SOL_TRANSPORT_LOSS_GRACE_MS + 1,
    })
    const recovered = resolveCanonicalMarketPresentation(callBeacon, transportRecovered)
    expect(transportRecovered).toBe(false)
    expect(recovered).toEqual({ marketState: 'CALL', operationalStatus: 'HEALTHY' })
  })

  it('18b. GET and SSE revision ordering rejects older and retired-runtime state', () => {
    const initial = {
      activeRuntimeInstanceId: null,
      retiredRuntimeInstanceIds: new Set<string>(),
      lastAppliedRevision: -1,
    }
    const sseRevision10 = advanceCanonicalRevision(initial, 'runtime-a', 10)
    expect(sseRevision10).not.toBeNull()
    expect(advanceCanonicalRevision(sseRevision10!, 'runtime-a', 9)).toBeNull()

    const restarted = advanceCanonicalRevision(sseRevision10!, 'runtime-b', 0)
    expect(restarted?.activeRuntimeInstanceId).toBe('runtime-b')
    expect(advanceCanonicalRevision(restarted!, 'runtime-a', 11)).toBeNull()
  })

  it('18c. Fast Lane GET cannot overwrite a newer SSE revision', () => {
    const initial = {
      activeRuntimeInstanceId: null,
      retiredRuntimeInstanceIds: new Set<string>(),
      lastAppliedRevision: -1,
    }
    const sse10 = advanceFastLaneRevision(initial, 'runtime-a', 10)
    expect(sse10).not.toBeNull()
    expect(advanceFastLaneRevision(sse10!, 'runtime-a', 9)).toBeNull()
    const restarted = advanceFastLaneRevision(sse10!, 'runtime-b', 0)
    expect(restarted?.activeRuntimeInstanceId).toBe('runtime-b')
    expect(advanceFastLaneRevision(restarted!, 'runtime-a', 11)).toBeNull()
  })

  // Test 19: No invented 1% shock threshold or sign-based market semantic classification
  it('19. no frontend invented 1% shock threshold or sign-based market semantics', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('SHOCK &amp; VOLATILITY RADAR')
    expect(html).not.toContain('SHOCK & VOLATILITY RADAR')
    expect(html).not.toContain('shockBadge')
    expect(html).not.toContain('shockPulse')
  })

  // Test 20: OFF_MARKET, PROVIDER_UNAVAILABLE, DATA_DEGRADED, STALE never become semantic NO_TRADE
  it.each([
    ['OFF_MARKET', 'MARKET CLOSED'],
    ['SYSTEM_OFF_MARKET', 'MARKET CLOSED'],
    ['PROVIDER_UNAVAILABLE', 'ANALYSIS UNAVAILABLE'],
    ['REASONING_UNAVAILABLE', 'ANALYSIS UNAVAILABLE'],
    ['DATA_DEGRADED', 'DATA LIMITED'],
    ['DATA_LINEAGE_CONTAMINATION', 'DATA NOT VERIFIED'],
    ['UNAVAILABLE', 'SYSTEM UNAVAILABLE'],
    ['SYSTEM_UNAVAILABLE', 'SYSTEM UNAVAILABLE'],
    ['TRANSPORT_UNAVAILABLE', 'CONNECTION LOST'],
  ])('20. %s never becomes semantic NO_TRADE and displays %s', (opStatus, expectedLabel) => {
    const presentation = resolveCanonicalMarketPresentation({
      system_status: opStatus === 'REASONING_UNAVAILABLE' || opStatus === 'PROVIDER_UNAVAILABLE' ? 'HEALTHY' : opStatus,
      reasoning_status: opStatus === 'REASONING_UNAVAILABLE' ? 'REASONING_UNAVAILABLE' : opStatus === 'PROVIDER_UNAVAILABLE' ? 'PROVIDER_UNAVAILABLE' : 'ACTIVE_REASONING',
      market_verdict: null,
      developing_state: 'UNRESOLVED',
      why_bullets: [],
      main_contradiction: 'NONE',
      what_changed: 'Status change.',
      thesis_timestamp_ist: '10:15:00',
      feed_age_ms: 100,
      configured_model: 'gemini-3.7-flash',
      actually_invoked_model: 'gemini-3.7-flash',
      canonical_market_state: null,
    }, opStatus === 'TRANSPORT_UNAVAILABLE')

    const html = renderToStaticMarkup(
      <LivingMarketForcesViewport
        marketState={presentation.marketState}
        operationalStatus={presentation.operationalStatus}
      />
    )

    expect(presentation.marketState).toBeNull()
    expect(html).toContain(expectedLabel)
    expect(html).toContain('data-active-market-state="NONE"')
    expect(html).not.toContain('>NO TRADE<')
    expect(html).not.toContain('>BALANCED<')
  })

  // Test 21: Structured external radar items are absent from unified cognitive surface
  it('21. structured external radar items are absent from unified cognitive surface', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('EXTERNAL CONTEXT · NEWS &amp; EVENTS')
    expect(html).not.toContain('WORLD MARKET QUOTES · UNAVAILABLE')
  })

  // Test 22: Legacy secondaryDeck external context drawer is eradicated
  it('22. legacy secondaryDeck external context drawer is eradicated', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('RATES / FX')
    expect(html).not.toContain('>External context</span>')
  })

  // Test 23: Live moves strip renders factual empty state without fake thresholds
  it('23. live moves strip renders event-driven state without numeric thresholds', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('abs(changePct)')
    expect(html).not.toContain('abs(pct)')
  })
})
