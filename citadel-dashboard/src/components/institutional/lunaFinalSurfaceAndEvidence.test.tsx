import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import {
  CognitiveDecisionCore,
  cognitivePresentation,
  sanitizeProseAndExtractEvidence,
  type CognitiveDecisionCoreProps,
} from './CognitiveDecisionCore'
import { GeminiMarketBrainSection } from './GeminiMarketBrainSection'
import {
  LivingMarketForcesViewport,
  getVideoPlaybackPlan,
  type LivingMarketState,
} from './LivingMarketForcesViewport'

describe('Luna Final Surface & Evidence Bus Integration', () => {
  const cutoff4Props: CognitiveDecisionCoreProps = {
    state: 'CALL_DEVELOPING',
    thesisEvolution: 'STRENGTHENING',
    opportunityMaturity: 'EMERGING',
    entryWindow: 'WAIT',
    whyNow: [
      'The recorded sequence shows spot advancing from 23646.5 to 23657.7 while the same 23650 CE rose from 40.95 to 48.85 and the corresponding PE declined from 31.95 to 28.2 [evt_40bb83c1fe71abbd_SPOT_MOVE_NIFTY_INDEX_0018c6d49c3c2441]',
    ],
    whatChanged: 'Spot advanced from 23646.5 to 23657.7 with call option premium expansion.',
    previousState: 'NO_TRADE',
    setupFamily: 'PULLBACK',
    reversalWatch: {
      direction: 'PUT_TO_CALL',
      status: 'MONITORING',
    },
    optionBuyerSide: 'CALL',
    premiumConfirmation: 'DEVELOPING',
    marketStatus: 'SESSION_LAST',
    gptStatus: {
      model_id: 'gpt-5.6-luna',
      status: 'SESSION_LAST',
      analyzed_revision: 4,
      updated_at: '2026-09-08T09:05:58.298025+00:00',
      interpretation:
        'CALL is promoted only to DEVELOPING because its directional option response strengthened over three snapshots and the PE response weakened, but the final futures/basis contradiction and near-flat straddle keep noise and reversal alternatives active.',
    },
    retainedValidation: {
      status: 'VALID',
    },
    revision: 4,
    fiveHypotheses: {
      CALL: { status: 'PLAUSIBLE', why: 'Multi-snapshot CE rise' },
      PUT: { status: 'WEAKENED', why: 'PE declined' },
      NOISE: { status: 'PLAUSIBLE', why: 'Near-flat straddle' },
      REVERSAL: { status: 'UNRESOLVED', why: 'Futures basis divergence' },
    },
  }

  it('1. renders exactly ONE single Award-Motion cognitive surface without legacy secondaryDeck', () => {
    const html = renderToStaticMarkup(<GeminiMarketBrainSection />)

    // Cognitive Decision Core present exactly once
    const matches = html.match(/data-testid="cognitive-decision-core"/g)
    expect(matches).toHaveLength(1)

    // Legacy secondaryDeck sections and footers are eradicated
    expect(html).not.toContain('GEMINI 3.7 FLASH // LIVE MARKET BRAIN')
    expect(html).not.toContain('INTELLIGENCE NETWORK')
    expect(html).not.toContain('WHAT GEMINI SEES')
    expect(html).not.toContain('GEMINI HISTORY')
    expect(html).not.toContain('STORED MODEL ANALYSES')
    expect(html).not.toContain('EXTERNAL CONTEXT · NEWS &amp; EVENTS')
    expect(html).not.toContain('SAFE MODE ACTIVE')
  })

  it('2. cognitivePresentation handles SESSION_LAST without claiming current', () => {
    const pres = cognitivePresentation(cutoff4Props)
    expect(pres.current).toBe(false)
    expect(pres.isSessionLast).toBe(true)
    expect(pres.label).toBe('CALL')
    expect(pres.tone).toBe('call')
    expect(pres.context).toBe('SESSION LAST')
  })

  it('3. renders SESSION LAST in Award-Motion UI with strict non-current indicators', () => {
    const html = renderToStaticMarkup(<CognitiveDecisionCore {...cutoff4Props} />)

    // Hero displays state words accurately
    expect(html).toContain('CALL')
    expect(html).toContain('DEVELOPING')

    // Must never claim current or live
    expect(html).toContain('data-current="false"')
    expect(html).not.toContain('data-current="true"')

    // Badges and readouts enforce session last truth
    expect(html).toContain('SESSION LAST · MARKET CLOSED')
    expect(html).toContain('SESSION LAST · NOT CURRENT')
    expect(html).toContain('SESSION LAST · HISTORICAL AUDIT')
    expect(html).toContain('gpt-5.6-luna · SESSION LAST')

    // Core thesis renders Cutoff 4 reason
    expect(html).toContain('CALL is promoted only to DEVELOPING')

    // Hypotheses balance reflects all 4 hypotheses
    expect(html).toContain('CALL')
    expect(html).toContain('PLAUSIBLE')
    expect(html).toContain('PUT')
    expect(html).toContain('WEAKENED')
    expect(html).toContain('NOISE')
    expect(html).toContain('REVERSAL')
    expect(html).toContain('UNRESOLVED')
  })

  it('4. displays thesis evolution and opportunity maturity metrics accurately', () => {
    const html = renderToStaticMarkup(<CognitiveDecisionCore {...cutoff4Props} />)
    expect(html).toContain('EVOLUTION: <strong>STRENGTHENING</strong>')
    expect(html).toContain('MATURITY: <strong>EMERGING</strong>')
  })

  it('5. session rollover marks previous session as not current', () => {
    const priorSessionProps: CognitiveDecisionCoreProps = {
      ...cutoff4Props,
      marketStatus: 'LIVE',
      gptStatus: {
        ...cutoff4Props.gptStatus,
        status: 'STALE',
      },
    }
    const pres = cognitivePresentation(priorSessionProps)
    expect(pres.current).toBe(false)
    expect(pres.isSessionLast).toBe(false)
    expect(pres.label).toBe('UNAVAILABLE')
  })

  it('6. does not replace an unrecorded input with newer Oracle values', () => {
    const html = renderToStaticMarkup(<CognitiveDecisionCore {...cutoff4Props} snapshot={{ spot_ltp: 99999 }} />)
    expect(html).toContain('EXACT INPUT NOT RECORDED')
    expect(html).not.toContain('99999')
    expect(html).toContain('INDIA VIX · UNAVAILABLE')
    expect(html).toContain('MAX PAIN · NOT CANONICAL')
  })

  it('binds receipt values to the accepted revision and preserves session-last', () => {
    const receipt = { receipt_id: 'test-receipt', model: 'gpt-5.6-luna', session_id: '2026-09-08', revision: 4, cutoff: '14:35:21',
      payload: { current_facts: { spot_price: { value: 23657.7, evidence_id: 'metric:spot_price', source_time: '2026-09-08T09:05:21Z', availability: 'RECORDED' } } } }
    const html = renderToStaticMarkup(<CognitiveDecisionCore {...cutoff4Props} acceptedInputReceipt={receipt} snapshot={{ spot_ltp: 99999 }} />)
    expect(html).toContain('23657.7')
    expect(html).not.toContain('99999')
    expect(html).toContain('data-accepted-input-receipt="test-receipt"')
    expect(html).toContain('14:35:21')
    const mismatch = renderToStaticMarkup(<CognitiveDecisionCore {...cutoff4Props} acceptedInputReceipt={{ ...receipt, revision: 5 }} />)
    expect(mismatch).toContain('EXACT INPUT NOT RECORDED')
    expect(mismatch.split('</aside>')[0]).not.toContain('23657.7')
  })

  it('7. renders Center Stage with Pipeline Connector Bridge bridging evidence and decisions', () => {
    const html = renderToStaticMarkup(<CognitiveDecisionCore {...cutoff4Props} />)

    // Pipeline connector cues
    expect(html).toContain('◀')
    expect(html).toContain('LUNA EVIDENCE BUS')
    expect(html).toContain('DECISION SURFACE')
    expect(html).toContain('▶')

    // Retains existing core hero globe and synthesis hubs
    expect(html).toContain('data-motion-stage="THESIS"')
    expect(html).toContain('MARKET READ')
    expect(html).toContain('WHAT DOESN’T FIT')
  })

  it('8. renders Right Panel: LUNA OUTPUT / DECISION SURFACE with plain-English rationale and hypotheses', () => {
    const html = renderToStaticMarkup(<CognitiveDecisionCore {...cutoff4Props} />)

    // Right Panel header
    expect(html).toContain('02 // DECISION SURFACE')
    expect(html).toContain('LUNA INTERPRETED OUTPUT')
    expect(html).toContain('data-testid="luna-decision-surface"')

    // Block 1: Primary Thesis & Rationale
    expect(html).toContain('01 // PRIMARY THESIS &amp; RATIONALE')
    expect(html).toContain('PRIMARY STATE')
    expect(html).toContain('ENTRY WINDOW')
    expect(html).toContain('MARKET READ')
    expect(html).toContain('WHAT DOESN’T FIT')

    // Block 2: Cross-Validation Option Flow
    expect(html).toContain('02 // OPTION FLOW')
    expect(html).toContain('CROSS-VALIDATION')

    // Block 3: 4-Way Competing Hypotheses
    expect(html).toContain('03 // COMPETING HYPOTHESES')
    expect(html).toContain('4-WAY STATUS')
    expect(html).toContain('CALL CONTINUATION')
    expect(html).toContain('PUT EXPANSION')
    expect(html).toContain('CHOP / NOISE')
    expect(html).toContain('REVERSAL THESIS')

    // Block 4: Horizon Sensor & Reversal Posture
    expect(html).toContain('04 // REVERSAL POSTURE')
    expect(html).toContain('HORIZON SENSOR')
    expect(html).toContain('PUT → CALL')

    // Block 5: Evolution & Maturity
    expect(html).toContain('05 // EVOLUTION &amp; MATURITY')
    expect(html).toContain('THESIS EVOLUTION')
    expect(html).toContain('OPPORTUNITY MATURITY')
  })

  it('9. maps Bull/Bear Living Market Forces video playback plans for all 8 canonical states', () => {
    // 1. CALL_DEVELOPING
    const callDevPlan = getVideoPlaybackPlan('CALL_DEVELOPING', 'HEALTHY', false)
    expect(callDevPlan.targetId).toBe('vidBullPressure')
    expect(callDevPlan.startTime).toBe(11.8)

    // 2. PUT_DEVELOPING
    const putDevPlan = getVideoPlaybackPlan('PUT_DEVELOPING', 'HEALTHY', false)
    expect(putDevPlan.targetId).toBe('vidBearPressure')
    expect(putDevPlan.startTime).toBe(11.0)

    // 3. WAIT
    const waitPlan = getVideoPlaybackPlan('WAIT', 'HEALTHY', false)
    expect(waitPlan.targetId).toBe('vidBalanced')
    expect(waitPlan.startTime).toBe(0)

    // 4. REVERSAL_WATCH
    const reversalPlan = getVideoPlaybackPlan('REVERSAL_WATCH', 'HEALTHY', false)
    expect(reversalPlan.targetId).toBe('vidBalanced')
    expect(reversalPlan.startTime).toBe(0)

    // 5. ANALYZING
    const analyzingPlan = getVideoPlaybackPlan('ANALYZING', 'HEALTHY', false)
    expect(analyzingPlan.targetId).toBe('vidBalanced')

    // 6. STALE
    const stalePlan = getVideoPlaybackPlan('STALE', 'STALE', false)
    expect(stalePlan.targetId).toBe('vidBalanced')

    // 7. UNAVAILABLE
    const unavailPlan = getVideoPlaybackPlan('UNAVAILABLE', 'UNAVAILABLE', false)
    expect(unavailPlan.targetId).toBe('vidBalanced')

    // 8. SESSION_LAST (with CALL bias)
    const sessionLastCallPlan = getVideoPlaybackPlan('CALL_DEVELOPING', 'SESSION_LAST', true)
    expect(sessionLastCallPlan.targetId).toBe('vidBullPressure')
    expect(sessionLastCallPlan.startTime).toBe(26.5)

    // SESSION_LAST (with PUT bias)
    const sessionLastPutPlan = getVideoPlaybackPlan('PUT_DEVELOPING', 'SESSION_LAST', true)
    expect(sessionLastPutPlan.targetId).toBe('vidBearPressure')
    expect(sessionLastPutPlan.startTime).toBe(18.5)
  })

  it('10. renders LivingMarketForcesViewport across all 8 canonical states without crashes', () => {
    const states: Array<{ state: LivingMarketState; expectedBadge: string }> = [
      { state: 'CALL_DEVELOPING', expectedBadge: 'CALL DEVELOPING' },
      { state: 'PUT_DEVELOPING', expectedBadge: 'PUT DEVELOPING' },
      { state: 'WAIT', expectedBadge: 'WAIT' },
      { state: 'REVERSAL_WATCH', expectedBadge: 'REVERSAL WATCH' },
      { state: 'ANALYZING', expectedBadge: 'ANALYZING' },
      { state: 'STALE', expectedBadge: 'LAST KNOWN' },
      { state: 'UNAVAILABLE', expectedBadge: 'UNAVAILABLE' },
      { state: 'SESSION_LAST', expectedBadge: '· SESSION LAST · MARKET CLOSED ·' },
    ]

    for (const { state, expectedBadge } of states) {
      const isSessionLast = state === 'SESSION_LAST'
      const html = renderToStaticMarkup(
        <LivingMarketForcesViewport
          marketState={state}
          cognitiveState={state}
          operationalStatus={state === 'STALE' ? 'STALE' : state === 'UNAVAILABLE' ? 'UNAVAILABLE' : isSessionLast ? 'SESSION_LAST' : 'HEALTHY'}
          isSessionLast={isSessionLast}
          spotPrice={23657.7}
          basis={-12.4}
        />
      )
      expect(html).toContain(expectedBadge)
      expect(html).toContain('data-stage-mode')
    }
  })

  it('11. strips internal bracketed metric tokens [metric:...] out of trader-facing prose into clean natural English', () => {
    const rawProse = 'Spot holding firmly above VWAP [metric:spot_price metric:zero_gamma metric:dealer_regime metric:cvd] confirms aggressive accumulation [evt_40bb83c1fe71abbd_SPOT_MOVE_NIFTY_INDEX_0018c6d49c3c2441].'
    const result = sanitizeProseAndExtractEvidence(rawProse)
    expect(result.cleanText).toBe('Spot holding firmly above VWAP confirms aggressive accumulation.')
    expect(result.evidence).toHaveLength(1)
    expect(result.evidence[0].eventType).toBe('SPOT_MOVE')
  })
})
