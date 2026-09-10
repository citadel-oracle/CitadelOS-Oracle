import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import { CognitiveDecisionCore } from './CognitiveDecisionCore'

describe('Multi-Model Live Shadow Specialist Cards (V1.3)', () => {
  const baseReceipt = {
    receipt_id: 'rcpt_live_shadow_123',
    model: 'gpt-5.6-luna',
    session_id: '2026-09-09',
    revision: 3418,
    cutoff: '13:35:09',
    payload: {
      current_facts: {
        spot_price: { value: 23550.0, availability: 'AVAILABLE', evidence_id: 'metric:spot_price', source_time: '13:35:09' },
        basis: { value: 24.5, availability: 'AVAILABLE', evidence_id: 'metric:basis', source_time: '13:35:09' },
        atm_strike: { value: 23550, availability: 'AVAILABLE', evidence_id: 'metric:atm_strike', source_time: '13:35:09' },
        straddle_price: { value: 245.0, availability: 'AVAILABLE', evidence_id: 'metric:straddle_price', source_time: '13:35:09' },
      },
    },
  }

  it('renders both Gemini Fast Scout and Sol Option Specialist cards in centralCognitiveStage', () => {
    const html = renderToString(
      <CognitiveDecisionCore
        revision={3418}
        state="WAIT"
        acceptedInputReceipt={baseReceipt}
        retainedValidation={{ status: 'VALID' }}
        geminiScout={{
          role: 'FAST_SCOUT',
          semantic_state: 'POSSIBLE_REVERSAL',
          headline: 'Selling increased, but price is not falling.',
          bullets: [
            'Selling increased, but price is not falling.',
            'Buyers absorbing at 23540.',
            'Straddle holding firm.',
          ],
          missing_evidence: ['flow_net_delta'],
          age_seconds: 14,
          status: 'CURRENT',
        }}
        solSpecialist={{
          role: 'OPTION_SPECIALIST',
          buying_state: 'AVOID_CHASE',
          headline: '23550 CE IV up 1.8 vol pts in 5m; premium already expanded 14%.',
          bullets: [
            '23550 CE IV up 1.8 vol pts in 5m.',
            'Premium already expanded 14%.',
            'Risk/reward poor for fresh longs here.',
          ],
          missing_evidence: [],
          age_seconds: 22,
          status: 'CURRENT',
        }}
      />
    )

    // Specialists container present
    expect(html).toContain('data-testid="cognitive-specialists-substage"')

    // Gemini card assertions
    expect(html).toContain('data-testid="gemini-scout-card"')
    expect(html).toContain('GEMINI ⚡ FAST SCOUT')
    expect(html).toContain('POSSIBLE REVERSAL')
    expect(html).toContain('Selling increased, but price is not falling.')
    expect(html).toContain('Buyers absorbing at 23540.')
    expect(html).toContain('Straddle holding firm.')
    expect(html).toContain('UPDATED 14S AGO')
    expect(html).toContain('MISSING: flow_net_delta')

    // Sol card assertions
    expect(html).toContain('data-testid="sol-option-specialist-card"')
    expect(html).toContain('SOL 🔬 OPTION SPECIALIST')
    expect(html).toContain('AVOID CHASE')
    expect(html).toContain('23550 CE IV up 1.8 vol pts in 5m; premium already expanded 14%.')
    expect(html).toContain('Risk/reward poor for fresh longs here.')
    expect(html).toContain('UPDATED 22S AGO')
  })

  it('renders standby / no current read state gracefully when live views are unpopulated', () => {
    const html = renderToString(
      <CognitiveDecisionCore
        revision={3418}
        state="WAIT"
        acceptedInputReceipt={baseReceipt}
        retainedValidation={{ status: 'VALID' }}
      />
    )

    expect(html).toContain('data-testid="cognitive-specialists-substage"')
    expect(html).toContain('GEMINI ⚡ FAST SCOUT')
    expect(html).toContain('SOL 🔬 OPTION SPECIALIST')
    expect(html).toContain('STANDBY · NO CURRENT READ')
    expect(html).toContain('No current Gemini Fast Scout read.')
    expect(html).toContain('No current Sol Option Specialist read.')
  })

  it('updates semantic and buying state tones cleanly', () => {
    const html = renderToString(
      <CognitiveDecisionCore
        revision={3419}
        state="CALL_DEVELOPING"
        acceptedInputReceipt={baseReceipt}
        retainedValidation={{ status: 'VALID' }}
        geminiScout={{
          role: 'FAST_SCOUT',
          semantic_state: 'FLOW_SHIFT',
          headline: 'Positive order flow shift confirmed.',
          bullets: ['Aggressive bids stepping higher.'],
          age_seconds: 5,
          status: 'CURRENT',
        }}
        solSpecialist={{
          role: 'OPTION_SPECIALIST',
          buying_state: 'CALL_ATTRACTIVE',
          headline: '23550 CE offers clean asymmetric risk/reward.',
          bullets: ['IV compressed at 9.8%.', 'Carry drag minimal.'],
          age_seconds: 5,
          status: 'CURRENT',
        }}
      />
    )

    expect(html).toContain('data-semantic-state="FLOW_SHIFT"')
    expect(html).toContain('data-tone="cyan"')
    expect(html).toContain('data-buying-state="CALL_ATTRACTIVE"')
    expect(html).toContain('data-tone="green"')
  })

  it('communicates exact asymmetry when Gemini is CURRENT and Sol is unpopulated', () => {
    const html = renderToString(
      <CognitiveDecisionCore
        revision={3418}
        state="CALL_DEVELOPING"
        acceptedInputReceipt={baseReceipt}
        retainedValidation={{ status: 'VALID' }}
        geminiScout={{
          role: 'FAST_SCOUT',
          semantic_state: 'FLOW_SHIFT',
          headline: 'Positive order flow shift confirmed.',
          bullets: ['Aggressive bids stepping higher.'],
          age_seconds: 4,
          status: 'CURRENT',
        }}
        solSpecialist={undefined}
      />
    )

    // Gemini card is CURRENT
    expect(html).toContain('data-testid="gemini-scout-card"')
    expect(html).toContain('FLOW SHIFT')
    expect(html).toContain('Positive order flow shift confirmed.')
    expect(html).toContain('UPDATED 4S AGO')

    // Sol card truthfully reflects STANDBY · NO CURRENT READ
    expect(html).toContain('data-testid="sol-option-specialist-card"')
    expect(html).toContain('STANDBY · NO CURRENT READ')
    expect(html).toContain('No current Sol Option Specialist read.')
  })

  it('truthfully renders PAUSED · INPUT HARDENING and historical context when Sol is paused', () => {
    const html = renderToString(
      <CognitiveDecisionCore
        revision={3418}
        state="CALL_DEVELOPING"
        acceptedInputReceipt={baseReceipt}
        retainedValidation={{ status: 'VALID' }}
        geminiScout={{
          role: 'FAST_SCOUT',
          semantic_state: 'FLOW_SHIFT',
          headline: 'Positive order flow shift confirmed.',
          bullets: ['Aggressive bids stepping higher.'],
          age_seconds: 5,
          status: 'CURRENT',
        }}
        solSpecialist={{
          role: 'OPTION_SPECIALIST',
          buying_state: 'AVOID_CHASE',
          headline: 'Historical reading preserved from earlier session.',
          bullets: ['Option economics inputs undergoing hardening.'],
          missing_evidence: ['straddle_change_15m', 'flow_net_delta'],
          age_seconds: 340,
          status: 'STALE',
          paused: true,
          display_status: 'PAUSED · INPUT HARDENING',
        }}
      />
    )

    // Gemini card remains CURRENT and ACTIVE
    expect(html).toContain('data-testid="gemini-scout-card"')
    expect(html).toContain('UPDATED 5S AGO')

    // Sol card displays PAUSED · INPUT HARDENING and HISTORICAL age, NEVER active/in-flight/current
    expect(html).toContain('data-testid="sol-option-specialist-card"')
    expect(html).toContain('PAUSED · INPUT HARDENING')
    expect(html).toContain('HISTORICAL · 340S AGO')
    expect(html).not.toContain('UPDATED 340S AGO')
  })

  it('truthfully renders PAUSED · INPUT/ARCHITECTURE HARDENING and historical context when Gemini is paused', () => {
    const html = renderToString(
      <CognitiveDecisionCore
        revision={3418}
        state="CALL_DEVELOPING"
        acceptedInputReceipt={baseReceipt}
        retainedValidation={{ status: 'VALID' }}
        geminiScout={{
          role: 'FAST_SCOUT',
          semantic_state: 'FLOW_SHIFT',
          headline: 'Historical reading preserved from earlier session.',
          bullets: ['Architecture hardening in progress.'],
          missing_evidence: [],
          age_seconds: 180,
          status: 'STALE',
          paused: true,
          display_status: 'PAUSED · INPUT/ARCHITECTURE HARDENING',
        }}
        solSpecialist={undefined}
      />
    )

    // Gemini card displays PAUSED · INPUT/ARCHITECTURE HARDENING and HISTORICAL age, NEVER active/in-flight/current
    expect(html).toContain('data-testid="gemini-scout-card"')
    expect(html).toContain('PAUSED · INPUT/ARCHITECTURE HARDENING')
    expect(html).toContain('HISTORICAL · 180S AGO')
    expect(html).not.toContain('UPDATED 180S AGO')
  })
})
