import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { CitadelLiveIsland, type LiveIslandState } from './CitadelLiveIsland'

describe('Citadel Live Island Component Tests', () => {
  it('renders nominal idle state with authoritative visual classes', () => {
    const html = renderToStaticMarkup(<CitadelLiveIsland />)
    expect(html).toContain('data-testid="citadel-live-island"')
    expect(html).toContain('CITADEL ORACLE · ALL REGIMES NOMINAL')
    expect(html).toContain('oracle-island-pill')
    expect(html).toContain('oracle-island-hero')
    expect(html).toContain('spine-bias-pip')
  })

  it('renders active scalar hero event with correct bias and trend channels', () => {
    const mockState: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 1,
      activeEvents: [
        {
          id: 'vix_surge_1',
          type: 'vix_spike',
          title: 'INDIA VIX SHOCK',
          shortTitle: 'VIX SHOCK',
          currentValue: '17.4',
          previousValue: '14.2',
          secondaryValue: '+22.5%',
          numericTrend: 'UP',
          eventBias: 'BEARISH',
          severity: 'CRITICAL',
          phase: 'IMPACT',
          archetype: 'scalar',
          archetypeData: {
            oldVal: '14.2',
            newVal: '17.4',
            change: '+22.5%',
            rateText: 'ACCELERATING',
          },
          acceleration: 0.88,
        },
      ],
      memoryEvents: [],
    }

    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={mockState} />)
    expect(html).toContain('INDIA VIX SHOCK')
    expect(html).toContain('scalar-stage')
    expect(html).toContain('scalar-new-val')
    expect(html).toContain('bias-bearish')
    expect(html).toContain('orb-bearish')
    expect(html).toContain('+22.5%')
    expect(html).toContain('ACCELERATING')
  })

  it('renders contradiction notch when event bias opposes spine bias', () => {
    const mockState: LiveIslandState = {
      spineBias: 'bull',
      burstCount: 2,
      activeEvents: [
        {
          id: 'pcr_break_1',
          type: 'pcr_shift',
          title: 'PCR SKEW COLLAPSE',
          shortTitle: 'PCR COLLAPSE',
          currentValue: '0.71',
          previousValue: '0.94',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH', // Opposes bull spine
          severity: 'HIGH',
          phase: 'IMPACT',
          archetype: 'scalar',
        },
      ],
      memoryEvents: [],
    }

    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={mockState} />)
    expect(html).toContain('split-bias-notch')
    expect(html).toContain('burst-counter-badge')
    expect(html).toContain('+2 BURST')
  })

  it('renders polarity flip, companions, and temporal memory echoes', () => {
    const mockState: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 0,
      activeEvents: [
        {
          id: 'gex_flip_1',
          type: 'gex_flip',
          title: 'ZERO-GEX TRANSITION',
          shortTitle: 'GEX FLIP',
          currentValue: '-0.8B',
          previousValue: '+1.2B',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'CRITICAL',
          phase: 'IMPACT',
          archetype: 'polarity',
          archetypeData: {
            prevPole: '+GEX',
            prevVal: '+1.2B',
            currPole: '-GEX',
            currVal: '-0.8B',
          },
        },
        {
          id: 'companion_pcr',
          type: 'pcr_shift',
          title: 'PCR SKEW',
          shortTitle: 'PCR 0.71',
          currentValue: '0.71',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'HIGH',
          phase: 'SETTLED',
          archetype: 'scalar',
        },
      ],
      memoryEvents: [
        {
          id: 'memory_vix',
          type: 'vix_spike',
          title: 'INDIA VIX',
          shortTitle: 'VIX 17.4',
          currentValue: '17.4',
          numericTrend: 'UP',
          eventBias: 'BEARISH',
          severity: 'HIGH',
          phase: 'MEMORY',
          archetype: 'scalar',
        },
      ],
    }

    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={mockState} />)
    // Polarity visuals
    expect(html).toContain('polarity-stage')
    expect(html).toContain('+GEX')
    expect(html).toContain('-GEX')
    expect(html).toContain('polarity-zero-pip')

    // Companion
    expect(html).toContain('island-satellites-cluster')
    expect(html).toContain('oracle-island-companion')
    expect(html).toContain('PCR 0.71')

    // Memory Plane
    expect(html).toContain('island-memory-plane')
    expect(html).toContain('temporal-memory-footprint')
    expect(html).toContain('VIX 17.4')
  })

  it('renders dual_sided, level, and impulse archetypes accurately', () => {
    const dualState: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 0,
      activeEvents: [
        {
          id: 'dual_1',
          type: 'oi_shift',
          title: 'OPTION OI DIVERGENCE',
          shortTitle: 'OI SHIFT',
          currentValue: '+34%',
          numericTrend: 'UP',
          eventBias: 'BEARISH',
          severity: 'HIGH',
          phase: 'IMPACT',
          archetype: 'dual_sided',
          archetypeData: {
            leftSide: 'CALL ΔOI',
            leftVal: '-18%',
            rightSide: 'PUT ΔOI',
            rightVal: '+34%',
            dominantSide: 'right',
          },
        },
      ],
      memoryEvents: [],
    }
    const htmlDual = renderToStaticMarkup(<CitadelLiveIsland initialState={dualState} />)
    expect(htmlDual).toContain('dual-sided-stage')
    expect(htmlDual).toContain('is-dominant')
    expect(htmlDual).toContain('CALL ΔOI')
    expect(htmlDual).toContain('PUT ΔOI')

    const impulseState: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 0,
      activeEvents: [
        {
          id: 'impulse_1',
          type: 'gamma_blast',
          title: 'GAMMA VELOCITY SPIKE',
          shortTitle: 'GAMMA BLAST',
          currentValue: '4.8x',
          numericTrend: 'UP',
          eventBias: 'RISK',
          severity: 'CRITICAL',
          phase: 'IMPACT',
          archetype: 'impulse',
          archetypeData: { blastIntensity: '4.8x' },
        },
      ],
      memoryEvents: [],
    }
    const htmlImpulse = renderToStaticMarkup(<CitadelLiveIsland initialState={impulseState} />)
    expect(htmlImpulse).toContain('impulse-stage')
    expect(htmlImpulse).toContain('is-impulse-active')
    expect(htmlImpulse).toContain('IMPULSE')
    expect(htmlImpulse).toContain('4.8x')
  })

  // ---------------------------------------------------------------------------
  // 10 Deterministic Visual Active-State Parity Tests
  // ---------------------------------------------------------------------------
  it('1. State: GEX Hero (Polarity crossing with +GEX to -GEX and pip)', () => {
    const state: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 0,
      activeEvents: [
        {
          id: 'gex',
          type: 'gex_flip',
          title: 'GEX Regime Flip',
          shortTitle: 'GEX + → -',
          currentValue: '-15.0Cr',
          previousValue: '+45.0Cr',
          secondaryValue: 'GAMMA REGIME FLIP',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'CRITICAL',
          phase: 'IMPACT',
          archetype: 'polarity',
          archetypeData: {
            prevPole: '+GEX',
            prevVal: '+45.0Cr',
            currPole: '-GEX',
            currVal: '-15.0Cr',
            isCrossing: true,
          },
        },
      ],
      memoryEvents: [],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('GEX Regime Flip')
    expect(html).toContain('polarity-stage')
    expect(html).toContain('+45.0Cr')
    expect(html).toContain('-15.0Cr')
    expect(html).toContain('polarity-zero-pip')
  })

  it('2. State: Gamma Blast Hero (Impulse with blast intensity)', () => {
    const state: LiveIslandState = {
      spineBias: 'bull',
      burstCount: 0,
      activeEvents: [
        {
          id: 'gamma_blast',
          type: 'gamma_blast',
          title: 'Gamma Blast',
          shortTitle: 'Γ BLAST 4.8x',
          currentValue: '4.8x',
          secondaryValue: 'ONE-SHOT IMPULSE (ARMED)',
          numericTrend: 'UP',
          eventBias: 'BULLISH',
          severity: 'CRITICAL',
          phase: 'IMPACT',
          archetype: 'impulse',
          archetypeData: { blastIntensity: '4.8x' },
        },
      ],
      memoryEvents: [],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('Gamma Blast')
    expect(html).toContain('is-impulse-active')
    expect(html).toContain('4.8x')
    expect(html).toContain('ONE-SHOT IMPULSE (ARMED)')
  })

  it('3. State: OI Shift Hero (Dual-sided CALL vs PUT ΔOI)', () => {
    const state: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 0,
      activeEvents: [
        {
          id: 'oi_shift',
          type: 'oi_shift',
          title: 'Session OI Shift',
          shortTitle: 'Session ΔOI Shift',
          currentValue: 'C:+12,000 P:+85,000',
          secondaryValue: 'OFFICIAL 1D ΔOI',
          numericTrend: 'UP',
          eventBias: 'BEARISH',
          severity: 'MEDIUM',
          phase: 'IMPACT',
          archetype: 'dual_sided',
          archetypeData: {
            leftSide: 'CALL ΔOI',
            leftVal: '+12,000',
            rightSide: 'PUT ΔOI',
            rightVal: '+85,000',
            dominantSide: 'right',
          },
        },
      ],
      memoryEvents: [],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('dual-sided-stage')
    expect(html).toContain('CALL ΔOI')
    expect(html).toContain('+12,000')
    expect(html).toContain('PUT ΔOI')
    expect(html).toContain('+85,000')
  })

  it('4. State: VIX Companion (Rendered in satellite cluster)', () => {
    const state: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 0,
      activeEvents: [
        {
          id: 'gex',
          type: 'gex',
          title: 'GEX Flip',
          shortTitle: 'GEX FLIP',
          currentValue: '-15Cr',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'CRITICAL',
          phase: 'IMPACT',
          archetype: 'polarity',
        },
        {
          id: 'vix',
          type: 'vix',
          title: 'India VIX Shock',
          shortTitle: 'VIX ↑ 17.50',
          currentValue: '17.50',
          numericTrend: 'UP',
          eventBias: 'BEARISH',
          severity: 'HIGH',
          phase: 'IMPACT',
          archetype: 'scalar',
        },
      ],
      memoryEvents: [],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('island-satellites-cluster')
    expect(html).toContain('VIX ↑ 17.50')
  })

  it('5. State: PCR Companion (Rendered in satellite cluster with bias orb)', () => {
    const state: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 0,
      activeEvents: [
        {
          id: 'gex',
          type: 'gex',
          title: 'GEX Flip',
          shortTitle: 'GEX FLIP',
          currentValue: '-15Cr',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'CRITICAL',
          phase: 'IMPACT',
          archetype: 'polarity',
        },
        {
          id: 'pcr',
          type: 'pcr',
          title: 'PCR Surge',
          shortTitle: 'PCR 1.10',
          currentValue: '1.10',
          numericTrend: 'UP',
          eventBias: 'BULLISH',
          severity: 'MEDIUM',
          phase: 'SETTLED',
          archetype: 'scalar',
        },
      ],
      memoryEvents: [],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('PCR 1.10')
    expect(html).toContain('orb-bullish')
  })

  it('6. State: 1 Hero + 3 Companions (Full active capacity)', () => {
    const state: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 0,
      activeEvents: [
        {
          id: 'hero',
          type: 'gex',
          title: 'GEX Hero',
          shortTitle: 'GEX',
          currentValue: '-10Cr',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'CRITICAL',
          phase: 'IMPACT',
          archetype: 'polarity',
        },
        {
          id: 'sat1',
          type: 'vix',
          title: 'VIX Companion',
          shortTitle: 'VIX ↑ 17.2',
          currentValue: '17.2',
          numericTrend: 'UP',
          eventBias: 'BEARISH',
          severity: 'HIGH',
          phase: 'IMPACT',
          archetype: 'scalar',
        },
        {
          id: 'sat2',
          type: 'pcr',
          title: 'PCR Companion',
          shortTitle: 'PCR 0.85',
          currentValue: '0.85',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'MEDIUM',
          phase: 'SETTLED',
          archetype: 'scalar',
        },
        {
          id: 'sat3',
          type: 'max_pain',
          title: 'Max Pain Companion',
          shortTitle: 'MP 24500',
          currentValue: '24500',
          numericTrend: 'FLAT',
          eventBias: 'NEUTRAL',
          severity: 'MEDIUM',
          phase: 'SETTLED',
          archetype: 'level',
        },
      ],
      memoryEvents: [],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('GEX Hero')
    expect(html).toContain('VIX ↑ 17.2')
    expect(html).toContain('PCR 0.85')
    expect(html).toContain('MP 24500')
  })

  it('7. State: Memory States (3 memory footprints rendered in temporal plane)', () => {
    const state: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 0,
      activeEvents: [
        {
          id: 'hero',
          type: 'gex',
          title: 'GEX Hero',
          shortTitle: 'GEX',
          currentValue: '-10Cr',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'CRITICAL',
          phase: 'IMPACT',
          archetype: 'polarity',
        },
      ],
      memoryEvents: [
        {
          id: 'mem1',
          type: 'vix',
          title: 'India VIX',
          shortTitle: 'VIX 16.4',
          currentValue: '16.4',
          numericTrend: 'UP',
          eventBias: 'BEARISH',
          severity: 'HIGH',
          phase: 'MEMORY',
          archetype: 'scalar',
        },
        {
          id: 'mem2',
          type: 'pcr',
          title: 'PCR Shift',
          shortTitle: 'PCR 0.92',
          currentValue: '0.92',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'MEDIUM',
          phase: 'MEMORY',
          archetype: 'scalar',
        },
        {
          id: 'mem3',
          type: 'dominance',
          title: 'Buyers Dominance',
          shortTitle: 'Buyers +6pp',
          currentValue: '56%',
          numericTrend: 'UP',
          eventBias: 'BULLISH',
          severity: 'MEDIUM',
          phase: 'MEMORY',
          archetype: 'scalar',
        },
      ],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('island-memory-plane')
    expect(html).toContain('VIX 16.4')
    expect(html).toContain('PCR 0.92')
    expect(html).toContain('Buyers +6pp')
  })

  it('8. State: Contradiction State (Counter-bias buildup vs Spine with split notch)', () => {
    const state: LiveIslandState = {
      spineBias: 'bear', // Master Spine is RED / BEAR
      burstCount: 0,
      activeEvents: [
        {
          id: 'buildup',
          type: 'buildup',
          title: 'Strike 24500 CE Buildup',
          shortTitle: '24500 CE LONG BUILDUP',
          currentValue: 'LONG BUILDUP',
          secondaryValue: 'STRIKE REGIME SHIFT',
          numericTrend: 'UP',
          eventBias: 'BULLISH', // Counter-bias!
          severity: 'MEDIUM',
          phase: 'IMPACT',
          archetype: 'level',
        },
      ],
      memoryEvents: [],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('split-bias-notch')
    expect(html).toContain('Strike 24500 CE Buildup')
    expect(html).toContain('LONG BUILDUP')
  })

  it('9. State: Hero Takeover (Critical GEX evicts prior hero to companion)', () => {
    const state: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 0,
      activeEvents: [
        {
          id: 'gex',
          type: 'gex',
          title: 'GEX Polarity Flip',
          shortTitle: 'GEX + → -',
          currentValue: '-20Cr',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'CRITICAL',
          phase: 'IMPACT',
          archetype: 'polarity',
        },
        {
          id: 'vix_prior_hero',
          type: 'vix',
          title: 'India VIX Shock',
          shortTitle: 'VIX 18.2',
          currentValue: '18.2',
          numericTrend: 'UP',
          eventBias: 'BEARISH',
          severity: 'HIGH',
          phase: 'SETTLED',
          archetype: 'scalar',
        },
      ],
      memoryEvents: [],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('GEX Polarity Flip')
    expect(html).toContain('VIX 18.2')
  })

  it('10. State: Acceleration State (Particular option premium acceleration with kinetic sweep)', () => {
    const state: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 1,
      activeEvents: [
        {
          id: 'prem_accel',
          type: 'premium_accel',
          title: '24100 PE Premium Surge',
          shortTitle: '24100 PE ⇈ +24%',
          currentValue: '62.0',
          secondaryValue: 'PREMIUM ACCELERATION (PE)',
          numericTrend: 'UP',
          eventBias: 'BEARISH',
          severity: 'HIGH',
          phase: 'IMPACT',
          archetype: 'impulse',
          acceleration: 1.45,
          archetypeData: {
            blastIntensity: '+24%',
            rateText: 'ACCELERATING',
          },
        },
      ],
      memoryEvents: [],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('24100 PE Premium Surge')
    expect(html).toContain('+24%')
    expect(html).toContain('--rate-energy-duration')
    expect(html).toContain('ACCELERATING')
  })

  it('enables audio alerts by default with clean streamlined pill UI (no toggle button)', () => {
    const html = renderToStaticMarkup(<CitadelLiveIsland />)
    expect(html).not.toContain('island-alert-toggle')
  })

  it('renders heuristic participant badge for dominance and buyer/writer events', () => {
    const state: LiveIslandState = {
      spineBias: 'bear',
      burstCount: 1,
      activeEvents: [
        {
          id: 'buyers_writers',
          family: 'dominance',
          title: 'Writers Dominance',
          shortTitle: 'Writers +8.2pp',
          currentValue: '72.4%',
          numericTrend: 'DOWN',
          eventBias: 'BEARISH',
          severity: 'HIGH',
          phase: 'IMPACT',
          archetype: 'scalar',
          archetypeData: { change: '-8.2pp' },
        },
      ],
      memoryEvents: [],
    }
    const html = renderToStaticMarkup(<CitadelLiveIsland initialState={state} />)
    expect(html).toContain('heuristic-participant-badge')
    expect(html).toContain('HEURISTIC')
  })
})

