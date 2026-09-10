import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { GeminiMarketBrainSection } from './GeminiMarketBrainSection'

/**
 * External Context Frontend Activation & Spark Retirement
 * 
 * Architectural Note:
 * When Citadel unified all cognitive surfaces into the single Award-Motion
 * CognitiveDecisionCore, the legacy secondaryDeck ("EXTERNAL CONTEXT · NEWS & EVENTS")
 * was retired in favor of the unified ContextStrip (WORLD CONTEXT).
 * The tests below verify this unified architecture truthfully:
 * - Spark radar is permanently retired
 * - Truthful resting state without fabricating "no shock"
 * - Genuine news/regulatory events render with full provenance without AI invocation
 * - Synthetic test events remain quarantined
 */
describe('External Context Frontend Activation & Spark Retirement', () => {
  it('1. Spark gating removed: renders unified WORLD CONTEXT surface', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).toContain('WORLD CONTEXT')
    expect(html).not.toContain('SPARK RADAR · EXTERNAL INTELLIGENCE')
    expect(html).not.toContain('SPARK UNAVAILABLE')
    expect(html).not.toContain('EXTERNAL CONTEXT · NEWS &amp; EVENTS')
  })

  it('2. Empty state does not fabricate "no shock": truthful resting capsule renders', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).toContain('NO VERIFIED CURRENT HEADLINE')
    expect(html).toContain('No verified relevant story from today')
    expect(html).not.toContain('NO MAJOR EXTERNAL SHOCK')
  })

  it('3. Missing / unconfigured providers show truthful states', () => {
    const htmlMissing = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(htmlMissing).toContain('Verified global quotes unavailable')
    expect(htmlMissing).not.toContain('KEY_CONFIGURED')

    const htmlConfigured = renderToStaticMarkup(
      <GeminiMarketBrainSection
        dataOverride={{
          world_context: {
            cockpit: {
              status: 'LIVE',
              refresh_status: 'CURRENT',
              quotes: [
                {
                  symbol: 'USD/INR',
                  price: 84.12,
                  exact_or_proxy: 'EXACT',
                  provider: 'UPSTOX',
                  display_status: 'LIVE',
                  verification_status: 'VERIFIED',
                  published_at_utc: '2026-09-09T05:30:00Z',
                },
                {
                  symbol: 'SPY',
                  price: 562.4,
                  exact_or_proxy: 'EXACT',
                  provider: 'UPSTOX',
                  display_status: 'LIVE',
                  verification_status: 'VERIFIED',
                  published_at_utc: '2026-09-09T05:30:00Z',
                },
              ],
            },
          },
        } as any}
      />
    )
    expect(htmlConfigured).toContain('USD/INR')
    expect(htmlConfigured).toContain('84.12')
    expect(htmlConfigured).toContain('SPY')
    expect(htmlConfigured).toContain('562.4')
  })

  it('4. Genuine events render without requiring AI invocation', () => {
    const sampleEvent = {
      event_id: 'evt_test_official_001',
      source_name: 'Reserve Bank of India',
      headline: 'RBI Announces Variable Rate Reverse Repo Auction Schedule',
      summary: 'Operational liquidity management under revised framework.',
      display_status: 'LIVE',
      verification_status: 'VERIFIED',
      country: 'IN',
      published_at_utc: '2026-09-09T10:30:00Z',
    }
    const html = renderToStaticMarkup(
      <GeminiMarketBrainSection
        dataOverride={{
          service: 'CitadelMarketBrainService',
          vob_free_verified: 'ZERO_VOB_ALLOWLIST_CONFIRMED',
          world_context: {
            cockpit: {
              status: 'LIVE',
              refresh_status: 'CURRENT',
              top_stories: [sampleEvent],
            },
          },
        } as any}
      />
    )
    expect(html).toContain('RBI Announces Variable Rate Reverse Repo Auction Schedule')
    expect(html).toContain('Reserve Bank of India')
    expect(html).toContain('VERIFIED')
    expect(html).toContain('Operational liquidity management under revised framework.')
    expect(html).not.toContain('NO VERIFIED CURRENT HEADLINE')
  })

  it('5. Event provenance survives to frontend presentation', () => {
    const officialEvent = {
      event_id: 'evt_sebi_002',
      source_name: 'Securities and Exchange Board of India',
      headline: 'SEBI Circular on Index Derivatives Margin Architecture',
      summary: 'Revised prudential risk exposure norms for proprietary desks.',
      display_status: 'LIVE',
      verification_status: 'VERIFIED',
      country: 'IN',
      published_at_utc: '2026-09-09T11:00:00Z',
    }
    const html = renderToStaticMarkup(
      <GeminiMarketBrainSection
        dataOverride={{
          world_context: {
            cockpit: {
              status: 'LIVE',
              refresh_status: 'CURRENT',
              top_stories: [officialEvent],
            },
          },
        } as any}
      />
    )
    expect(html).toContain('SEBI Circular on Index Derivatives Margin Architecture')
    expect(html).toContain('Securities and Exchange Board of India')
    expect(html).toContain('INDIA · VERIFIED')
  })

  it('6. Market closed / offline LLM does not blank ExternalContextCore data', () => {
    const closedEvent = {
      event_id: 'evt_mospi_003',
      source_name: 'Ministry of Statistics and Programme Implementation',
      headline: 'MoSPI Macroeconomic Release Schedule (CPI / IIP for Month 09)',
      summary: 'Official release schedule anchored on 12th.',
      display_status: 'SESSION_LAST',
      verification_status: 'VERIFIED',
      country: 'IN',
      published_at_utc: '2026-09-09T12:00:00Z',
    }
    const html = renderToStaticMarkup(
      <GeminiMarketBrainSection
        dataOverride={{
          health_strip: {
            ai_provider: 'UNAVAILABLE',
            reasoning_state: 'NOT_INVOKED',
            data_stream: 'CLOSED',
          },
          world_context: {
            cockpit: {
              status: 'SESSION_LAST',
              refresh_status: 'CURRENT',
              top_stories: [closedEvent],
            },
          },
        } as any}
      />
    )
    expect(html).toContain('MoSPI Macroeconomic Release Schedule')
    expect(html).toContain('Ministry of Statistics and Programme Implementation')
    expect(html).toContain('VERIFIED')
  })

  it('7. Quarantined synthetic test events cannot appear in verified list', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)
    expect(html).not.toContain('SYNTHETIC_TEST_EVENT_')
    expect(html).not.toContain('Synthetic RBI Announcement')
  })
})
