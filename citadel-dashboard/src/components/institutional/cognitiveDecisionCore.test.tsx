import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { buildCognitiveTimeline, CognitiveDecisionCore, CognitiveDrawer, cognitivePresentation, verifiedWorldReceiptEligible, type CognitiveDecisionCoreProps } from './CognitiveDecisionCore'

const current: CognitiveDecisionCoreProps = {
  retainedValidation: { status: 'VALID' },
  revision: 12, state: 'PUT', entryWindow: 'READY', marketStatus: 'LIVE',
  gptStatus: { status: 'CURRENT', analyzed_revision: 12 },
}
const render = (props: CognitiveDecisionCoreProps = {}) => renderToStaticMarkup(<CognitiveDecisionCore {...props} />)

describe('Cognitive UI modernization: presentation-only contract', () => {
  it('does not substitute current VIX/contracts or invent specialist conclusions without a receipt', () => {
    const html = render({...current, snapshot: {india_vix: 91.23, atm_strike: 12345},
      callContract: {strike:12345, securityId:'current-only', ltp:99}, optionBuyerSide:'CALL'})
    expect(html).not.toContain('91.23')
    expect(html).not.toContain('12345 CE')
    expect(html).not.toContain('CALL_ATTRACTIVE')
    expect(html).not.toContain('ACTIVE MONITORING')
  })
  it('animates world receipts only when the current receipt contains verified displayable context', () => {
    expect(verifiedWorldReceiptEligible({ status: 'LIVE', refresh_status: 'CURRENT', refresh_receipt_id: 'poll-only' })).toBe(false)
    expect(verifiedWorldReceiptEligible({ status: 'LIVE', refresh_status: 'CURRENT', refresh_receipt_id: 'verified', headline: {
      headline: 'Verified fixture', source_name: 'TEST', display_status: 'LIVE', verification_status: 'VERIFIED',
    } })).toBe(true)
    expect(verifiedWorldReceiptEligible({ status: 'STALE', refresh_status: 'CURRENT', refresh_receipt_id: 'stale', headline: {
      headline: 'Verified fixture', source_name: 'TEST', display_status: 'LIVE', verification_status: 'VERIFIED',
    } })).toBe(false)
  })
  it.each([
    ['CALL', 'CALL', 'call'], ['PUT', 'PUT', 'put'],
    ['CALL_DEVELOPING', 'CALL', 'call'], ['PUT_DEVELOPING', 'PUT', 'put'],
    ['NO_TRADE', 'NO TRADE', 'wait'],
  ])('renders explicit %s without inventing readiness', (state, label, tone) => {
    const result = cognitivePresentation({ ...current, state, entryWindow: undefined })
    expect(result).toMatchObject({ label, tone, current: true, entry: 'UNAVAILABLE' })
  })
  it.each(['RATE_LIMITED', 'UNAVAILABLE', 'STALE', 'OUTPUT_INVALID', 'TIMEOUT'])(
    '%s primary is unavailable, never no trade or ready', status => {
      const props = { ...current, gptStatus: { status } }
      expect(cognitivePresentation(props)).toMatchObject({ label: 'UNAVAILABLE', entry: 'UNAVAILABLE', lastKnown: 'PUT' })
      expect(render(props)).toContain('data-current="false">UNAVAILABLE</h3>')
      expect(render(props)).not.toContain('data-selected="true"')
    },
  )
  it('retains session last without making it current', () => {
    const html = render({ ...current, marketStatus: 'OFF_MARKET' })
    expect(html).toContain('MARKET CLOSED')
    expect(html).toContain('LAST KNOWN')
    expect(html).not.toContain('data-current="true"')
  })
  it('unavailable broker evidence overrides retained closed/current analysis without inventing a market verdict', () => {
    for (const marketStatus of ['LIVE', 'OFF_MARKET']) {
      const props = { ...current, marketStatus, marketDataUnavailable: true }
      expect(cognitivePresentation(props)).toMatchObject({ current: false, label: 'UNAVAILABLE',
        context: 'MARKET DATA UNAVAILABLE · LIVE-DATA PENDING', lastKnown: 'PUT' })
      const html = render(props)
      expect(html).toContain('LIVE-DATA PENDING')
      expect(html).not.toContain('data-current="true"')
      expect(html).not.toContain('SESSION COMPLETE')
    }
  })
  it('transport failure overrides a previous ready view', () => {
    expect(cognitivePresentation({ ...current, transportUnavailable: true }))
      .toMatchObject({ label: 'UNAVAILABLE', context: 'CONNECTION LOST', lastKnown: 'PUT' })
  })
  it('different analyzed revision cannot present a current view', () => {
    expect(cognitivePresentation({ ...current, gptStatus: { status: 'CURRENT', analyzed_revision: 11 } }))
      .toMatchObject({ current: false, context: 'REVISION MISMATCH' })
  })
  it('unknown and missing states never default to NO TRADE', () => {
    for (const state of [null, undefined, 'BAD_OUTPUT', 'AWAITING']) {
      expect(cognitivePresentation({ ...current, state }).label).toBe('UNAVAILABLE')
    }
  })
  it('Gemini failure does not gate the primary GPT view', () => {
    expect(cognitivePresentation({ ...current, geminiStatus: { status: 'UNAVAILABLE' } }).current).toBe(true)
  })
  it('does not turn age or latency into a healthy status', () => {
    const html = render({ ...current, gptStatus: { age_seconds: 1, status: 'RATE_LIMITED', latency_ms: 0 } })
    expect(html).toContain('RATE LIMITED')
    expect(html).not.toContain('HEALTHY')
    expect(html).not.toContain('CONSENSUS')
  })
  it('missing text, comparison and reversal assessment stay explicitly missing', () => {
    const html = render(current)
    expect(html).toContain('No change summary supplied.')
    expect(html).toContain('No contradiction supplied.')
    expect(html).not.toContain('NONE DETECTED')
    expect(html).not.toContain('Bullish order flow corroborated')
    expect(html).not.toContain('UNFAVOURABLE')
  })
  it('shows only three why-now lines and preserves canonical text', () => {
    const html = render({ ...current, whyNow: ['Recorded cause one.', 'Recorded cause two.', 'Recorded cause three.', 'Fourth cause.'] })
    expect(html).toContain('Recorded cause three.')
    expect(html).not.toContain('Fourth cause.')
  })
  it('retains disagreement text, with no consensus invention', () => {
    const html = render({ ...current, modelTension: 'Solitary analyst challenges prior continuation view.' })
    expect(html).toContain('Solitary analyst challenges prior continuation view.')
    expect(html).not.toContain('QWEN → GPT ← GEMINI')
    expect(html).not.toContain('CONSENSUS')
  })
  it('missing same-contract change is not rendered as zero', () => {
    const html = render({ callContract: { strike: 23850, securityId: 'recorded-contract', ltp: null } })
    expect(html).toMatch(/SAME-CONTRACT CHANGE<\/dt><dd>—<\/dd>/)
    expect(html).not.toContain('0.0 pts')
  })
  it('numeric zero survives presentation when actually supplied', () => {
    const fact = (value: string | number) => ({value, evidence_id:'synthetic', source_time:'2026-09-03T08:00:00Z', availability:'RECORDED'})
    const html = render({ ...current, acceptedInputReceipt: {receipt_id:'test-receipt', revision:12,
      model:'gpt-5.6-luna', session_id:'2026-09-03', cutoff:'13:30:00',
      payload: {current_facts: {atm_strike:fact(23850), ce_atm_security_id:fact('recorded-contract'), ce_atm_premium:fact(0)}}} })
    expect(html).toMatch(/PRICE<\/dt><dd>0.00<\/dd>/)
  })
  it('secondary drawers are collapsed, keyboard-operable and inert initially', () => {
    const html = renderToStaticMarkup(<CognitiveDrawer title="Analysis" meta="Recorded"><a href="#evidence">Evidence</a></CognitiveDrawer>)
    expect(html).toContain('type="button"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain('aria-controls=')
    expect(html).toContain('inert=""')
    expect(html).toContain('aria-hidden="true"')
  })
  it('missing revision cannot render current even when telemetry says CURRENT', () => {
    expect(cognitivePresentation({ ...current, revision: undefined }).current).toBe(false)
  })
  it('role revision mismatch stays stale rather than displaying CURRENT', () => {
    const html = render({ ...current, gptStatus: { status: 'CURRENT', analyzed_revision: 1 } })
    expect(html).toContain('REVISION MISMATCH')
    expect(html).not.toContain('data-current="true"')
  })
  it('reversal direction and stage come directly from backend fields', () => {
    const html = render({ ...current, state: 'REVERSAL_WATCH', entryWindow: 'WAIT',
      reversalWatch: { direction: 'PUT_TO_CALL', status: 'DEVELOPING', why_not_confirmed: 'Recorded contradiction.' } })
    expect(html).toContain('PUT → CALL')
    expect(html).toContain('Recorded contradiction.')
  })
  it('source tier and healthy connection never self-promote a headline to verified', () => {
    const html = render({ worldContext: { events: [{ event_id: 'recorded', headline: 'Recorded headline',
      source_name: 'Recorded source', verification_tier: 'TIER_A_OFFICIAL', freshness: 'FRESH' }] } })
    expect(html).toContain('NO VERIFIED CURRENT HEADLINE')
    expect(html).not.toContain('Recorded headline')
    expect(html).not.toContain('>VERIFIED')
  })
  it.each(['LIVE', 'SESSION_LAST', 'STALE'])('keeps external %s label and exact instrument identity', data_age => {
    const html = render({ worldContext: { cockpit: { status: data_age, refresh_status: 'CURRENT',
      quotes: [{ symbol: 'SPY', price: 0, display_status: data_age, exact_or_proxy: 'PROXY', verification_status: 'VERIFIED' }] } } })
    expect(html).toContain(data_age.replaceAll('_', ' '))
    if (data_age !== 'STALE') {
      expect(html).toContain('SPY')
      expect(html).toContain('PROXY')
      expect(html).toContain('0.00')
    } else expect(html).not.toContain('0.00')
    expect(html).not.toContain('S&P futures')
  })
  it('keeps raw radar batches and generic calendars out of the primary news slot', () => {
    const html = render({ worldContext: { events: [
      { event_id: 'batch', headline: 'Raw batch metadata', verification_tier: 'TIER_C_GLOBAL_RADAR', published_at: '2026-09-03T13:30:00Z' },
      { event_id: 'calendar', headline: 'Generic monthly calendar', event_type: 'MACRO_DATA_CALENDAR' },
      { event_id: 'older', headline: 'Earlier reported news', published_at: '2026-09-03T11:00:00Z' },
      { event_id: 'latest', headline: 'Latest reported news', published_at: '2026-09-03T12:00:00Z' },
    ] } })
    expect(html).not.toContain('Latest reported news') // raw items are never a main-surface fallback
    expect(html).not.toContain('Raw batch metadata')
    expect(html).not.toContain('Generic monthly calendar')
  })
  it('never manufactures a clock time or current quote status from a date-only observation', () => {
    const html = render({ worldContext: { quotes: [{ symbol: 'USD/INR', price: 0,
      data_age: 'LIVE', provider_timestamp: '2026-09-03' }] } })
    expect(html).toContain('Verified global quotes unavailable')
    expect(html).not.toContain('05:30')
    expect(html).not.toContain('>LIVE<')
  })
  it('suppresses rejected legacy state, reasons, triggers and model prose', () => {
    const html = render({ ...current, marketStatus: 'OFF_MARKET', retainedValidation: { status: 'REJECTED' },
      whyNow: ['Aggressive call OI build suggests hidden bullish pressure.'], watchNext: ['Legacy trigger'],
      gptStatus: { status: 'REJECTED', interpretation: 'Old unsupported opinion' } })
    expect(html).toContain('LEGACY ANALYSIS REJECTED BY CURRENT SEMANTIC FIREWALL')
    expect(html).toContain('MARKET CLOSED')
    expect(html).not.toContain('hidden bullish pressure')
    expect(html).not.toContain('Old unsupported opinion')
    expect(html).not.toContain('Legacy trigger')
    expect(html).not.toContain('LAST VALID')
    expect(html).not.toContain('LAST ACCEPTED REASONS')
    expect(html).not.toContain('LAST KNOWN / NOT CURRENT')
  })
  it.each(['STALE', 'REJECTED', 'UNAVAILABLE', 'PAUSED'])('closed model %s is not upgraded to last valid', status => {
    const html = render({ ...current, marketStatus: 'OFF_MARKET', gptStatus: { status, interpretation: 'Recorded text' } })
    expect(html).toContain(status)
    expect(html).not.toContain('LAST VALID · PAUSED')
  })
  it('missing semantic validation cannot render an old deployment current', () => {
    expect(cognitivePresentation({ ...current, retainedValidation: undefined }).current).toBe(false)
  })

  it('builds a sparse chronology only from timestamped accepted outputs and verified context', () => {
    const timeline = buildCognitiveTimeline({
      qwenStatus: { status: 'CURRENT', updated_at: '2026-09-03T09:41:00Z', analyzed_revision: 12,
        response_id: 'q-12', interpretation: 'Accepted Qwen observation.' },
      gptStatus: { status: 'REJECTED', updated_at: '2026-09-03T09:42:00Z', interpretation: 'Rejected text.' },
      worldContext: { cockpit: { status: 'LIVE', refresh_status: 'CURRENT', headline: {
        headline: 'Verified recorded context.', source_name: 'Recorded source', display_status: 'LIVE',
        verification_status: 'VERIFIED', retrieved_at_utc: '2026-09-03T09:43:00Z',
      } } },
    })
    expect(timeline.map(event => event.source)).toEqual(['QWEN', 'WORLD'])
    expect(timeline.map(event => event.label)).not.toContain('Rejected text.')
  })

  it('renders the same cognitive core for every canonical state', () => {
    for (const state of ['CALL', 'PUT', 'CALL_DEVELOPING', 'PUT_DEVELOPING', 'NO_TRADE', 'REVERSAL_WATCH']) {
      const html = render({ ...current, state })
      expect(html).toContain('data-motion-stage="THESIS"')
      expect(html).toContain('COGNITIVE STAGE')
    }
  })
})
