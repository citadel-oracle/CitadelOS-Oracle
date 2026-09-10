import { describe, it, expect } from 'vitest'
import {
  actionLabel,
  auraTone,
  buildArgusVobViewModel,
  buildStory,
  controlLabel,
  evidenceStory,
  formatMoney,
  formatNumber,
  formatR,
  formatRange,
  formatTime,
  friendlyArgus,
  lifecycleSteps,
  magnetGeometry,
  pnlTone,
  proximityLabel,
  truthTone,
  UNKNOWN,
  UNKNOWN_OBSERVATION,
} from './photonicPresentationHelpers'
import type { OracleEvidenceObservation, OracleOptionDisplay, OracleVobEpisode } from '@/dashboard/store/oracleStore'

describe('Photonic Canonical Data Binding & Presentation Helpers', () => {
  it('formats currency, numbers, and R multiples canonically', () => {
    expect(formatMoney(24328.45)).toBe('₹24,328.45')
    expect(formatMoney(null)).toBe('—')
    expect(formatMoney(undefined)).toBe('—')

    expect(formatNumber(24350)).toBe('24,350')
    expect(formatNumber(null)).toBe('—')

    expect(formatR(1.85)).toBe('+1.85R')
    expect(formatR(-0.45)).toBe('-0.45R')
    expect(formatR(null)).toBe('—')

    expect(formatRange(180, 192.5)).toBe('180–192.5')
    expect(formatRange(null, null)).toBe('NOT REPORTED')
  })

  it('correctly maps truth tones for data freshness and market status', () => {
    expect(truthTone('FRESH')).toBe('fresh')
    expect(truthTone('OPEN')).toBe('fresh')
    expect(truthTone('AVAILABLE')).toBe('fresh')
    expect(truthTone('STALE')).toBe('bad')
    expect(truthTone('FAILED')).toBe('bad')
    expect(truthTone('BROKEN')).toBe('bad')
    expect(truthTone('UNKNOWN')).toBe('neutral')
  })

  it('correctly maps action labels from canonical reversal states', () => {
    expect(actionLabel('WATCHING', 'CALL', 'TOUCHED')).toBe('WATCH CALL TURN')
    expect(actionLabel('WATCHING', 'PUT', 'TOUCHED')).toBe('WATCH PUT TURN')
    expect(actionLabel('REVERSAL_BUILDING', 'CALL', 'TOUCHED')).toBe('REVERSAL BUILDING')
    expect(actionLabel('REVERSAL_READY', 'CALL', 'TOUCHED')).toBe('REVERSAL READY')
    expect(actionLabel('REVERSAL_FAILED', 'CALL', 'TOUCHED')).toBe('REVERSAL FAILED')
    expect(actionLabel('WATCHING', 'CALL', 'BROKEN')).toBe('VOB BROKEN')
    expect(actionLabel('UNAVAILABLE', 'CALL', 'TOUCHED')).toBe('DATA WAIT')
  })

  it('correctly maps ARGUS confirmation state without fabricating hard gates', () => {
    expect(friendlyArgus('CONFIRMS_TARGET')).toBe('SUPPORTIVE')
    expect(friendlyArgus('INCUMBENT_DETERIORATING')).toBe('IMPROVING')
    expect(friendlyArgus('ADVERSE')).toBe('HOSTILE')
    expect(friendlyArgus('UNKNOWN')).toBe(UNKNOWN)
    expect(friendlyArgus(null)).toBe(UNKNOWN)
  })

  it('computes magnet geometry correctly for proximity sliders', () => {
    const option: OracleOptionDisplay = {
      contract: {
        securityId: 'DHAN-1234',
        tradingSymbol: 'NIFTY 24200 CE',
        expiry: '2026-08-20',
        strike: 24200,
        optionType: 'CE',
        lotSize: 75,
        source: 'DHAN',
      },
      contractStatus: 'FROZEN_EPISODE',
      quoteSecurityId: 'DHAN-1234',
      vobSecurityId: 'VOB-5M-1',
      premium: 185.5,
      bid: 185.0,
      ask: 186.0,
      quoteTimestamp: '2026-08-16T11:24:00Z',
      freshness: 'FRESH',
      quoteSource: 'DHAN_FEED',
      vobTimeframe: '5M',
      zoneTop: 192.5,
      zoneBottom: 180.0,
      zoneState: 'ACTIVE',
      zoneRole: 'SUPPORT',
      zoneSource: 'PULLBACK',
      zonePrimary: true,
      distancePoints: 5.5,
      distancePct: 2.9,
      insideZone: true,
      nearestZoneBoundary: 180.0,
      relation: 'INSIDE',
    }

    const geom = magnetGeometry(option)
    expect(geom).not.toBeNull()
    expect(geom?.pricePct).toBeGreaterThan(0)
    expect(geom?.pricePct).toBeLessThan(100)
    expect(geom?.zoneStartPct).toBeLessThan(geom?.zoneEndPct ?? 0)
  })

  it('handles null/missing options in magnet geometry gracefully', () => {
    const emptyOption: OracleOptionDisplay = {
      contract: { securityId: null, tradingSymbol: null, expiry: null, strike: null, optionType: null, lotSize: null, source: null },
      contractStatus: 'CURRENT_ITM1',
      quoteSecurityId: null,
      vobSecurityId: null,
      premium: null,
      bid: null,
      ask: null,
      quoteTimestamp: null,
      freshness: 'UNKNOWN',
      quoteSource: null,
      vobTimeframe: null,
      zoneTop: null,
      zoneBottom: null,
      zoneState: 'UNKNOWN',
      zoneRole: 'UNKNOWN',
      zoneSource: null,
      zonePrimary: false,
      distancePoints: null,
      distancePct: null,
      insideZone: null,
      nearestZoneBoundary: null,
      relation: 'UNKNOWN',
    }
    expect(magnetGeometry(emptyOption)).toBeNull()
    expect(proximityLabel(emptyOption)).toBe('UNKNOWN')
  })

  it('builds canonical market story without inventing data', () => {
    const evidence: Record<string, OracleEvidenceObservation> = {
      failed_aggression: { ...UNKNOWN_OBSERVATION, known: true, state: 'PRESENT' },
      opposing_option_failure: { ...UNKNOWN_OBSERVATION, known: true, state: 'FAILING' },
      target_option_wakeup: { ...UNKNOWN_OBSERVATION, known: true, state: 'WAKEUP' },
      argus_confirmation: { ...UNKNOWN_OBSERVATION, known: true, state: 'CONFIRMS_TARGET' },
    }
    const story = buildStory('5M', '2026-08-16T11:24:00Z', 'CALL', evidence)
    expect(story).toEqual([
      '5M VOB TOUCHED',
      'SELLING NOT WORKING',
      'PE LOSING POWER',
      'CE WAKING UP',
      'ARGUS CONFIRMED',
    ])
  })

  it('generates 8-node canonical discrete lifecycle steps', () => {
    const episode: OracleVobEpisode = {
      episodeId: 'EP-998877',
      strike: 24200,
      optionType: 'CE',
      timeframe: '5M',
      vobState: 'ACTIVE',
      zoneBottom: 180.0,
      zoneTop: 192.5,
      touchAt: '2026-08-16T11:24:00Z',
      approachAt: '2026-08-16T11:20:00Z',
      createdAt: '2026-08-16T11:15:00Z',
      vobSecurityId: 'VOB-5M-1',
    }
    const steps = lifecycleSteps(episode, 'WATCHING', false)
    expect(steps).toHaveLength(8)
    expect(steps[0].state).toBe('complete')
    expect(steps[1].state).toBe('complete')
    expect(steps[2].state).toBe('complete')
    expect(steps[3].state).toBe('active')
    expect(steps[4].state).toBe('pending')
  })

  it('maps research metrics truth: renders — when null and matches canonical properties', () => {
    const emptyResearch = {
      matchedVobs: null,
      vobAverageR: null,
      confirmedAverageR: null,
      expectancyDelta: null,
      status: 'NOT REPORTED',
    }
    expect(formatR(emptyResearch.vobAverageR)).toBe('—')
    expect(formatR(emptyResearch.confirmedAverageR)).toBe('—')
    expect(formatR(emptyResearch.expectancyDelta)).toBe('—')
    expect(emptyResearch.matchedVobs).toBeNull()

    const populatedResearch = {
      matchedVobs: 84,
      vobAverageR: 1.45,
      confirmedAverageR: 2.10,
      expectancyDelta: 0.55,
      status: 'AVAILABLE',
    }
    expect(formatR(populatedResearch.vobAverageR)).toBe('+1.45R')
    expect(formatR(populatedResearch.confirmedAverageR)).toBe('+2.10R')
    expect(formatR(populatedResearch.expectancyDelta)).toBe('+0.55R')
    expect(populatedResearch.matchedVobs).toBe(84)
  })

  it('maps canonical evidence stories without mock values when unpopulated', () => {
    const emptyEvidence: Record<string, OracleEvidenceObservation> = {}
    const evidenceRows = evidenceStory('CALL', emptyEvidence)
    expect(evidenceRows).toHaveLength(4)
    evidenceRows.forEach((row) => {
      expect(row.known).toBe(false)
      expect(row.value).toBe(UNKNOWN)
    })
  })

  it('correctly maps ARGUS Prime positioning, buyer/writer percentages, and VOB rail in buildArgusVobViewModel', () => {
    // 1. Full ARGUS Prime + VOB snapshot
    const vm = buildArgusVobViewModel({
      argus: {
        bias: 'PUT',
        regime: 'WRITER_DOMINATED',
        buyerDominancePct: 20.55,
        writerDominancePct: 79.45,
        callWritingScore: 79.45,
        putBuyingScore: 20.55,
        callBuyingScore: 0,
        putWritingScore: 0,
        breakdownBelow: 24200,
        breakoutAbove: 24300,
        callWall: 24300,
        putWall: 24200,
        positioning: 'CALL WRITE BUILD',
      },
      market: {
        symbol: 'NIFTY',
        underlying: 24240.8,
        marketStatus: 'OPEN',
        dataFreshness: 'FRESH',
        canonicalAtmStrike: 24250,
        strikeInterval: 50,
        activeCe: { securityId: '45098', tradingSymbol: null, expiry: null, strike: 24200, optionType: 'CE', lotSize: 75, source: 'DHAN' },
        activePe: { securityId: '45111', tradingSymbol: null, expiry: null, strike: 24500, optionType: 'PE', lotSize: 75, source: 'DHAN' },
        currentItmCall: {} as any,
        currentItmPut: {} as any,
        itmCall: {} as any,
        itmPut: {} as any,
      },
      reversal: {
        state: 'WATCHING',
        direction: 'PUT',
        vobState: 'TESTED',
        quality: 'AVAILABLE',
        evidence: {
          opposing_option_failure: { state: 'FAILING', revision: '1', eventTime: '2026-08-17T10:00:00Z', receiveTime: null, persistence: 5, persistenceState: 'STABLE', quality: 'HIGH', known: true },
        },
        displayScores: { vobSetup: 80, turnStrength: null, marketSupport: null, overall: null },
      },
      vob: {
        episode: {
          episodeId: 'vobep_test_1',
          vobRevision: '1',
          sourceEngine: 'OSE',
          sourceZoneId: 'z1',
          symbol: 'NIFTY',
          direction: 'PUT',
          timeframe: '5M',
          zoneTop: 104.45,
          zoneBottom: 100.70,
          createdAt: '2026-08-17T09:30:00Z',
          approachAt: '2026-08-17T09:35:00Z',
          touchAt: '2026-08-17T09:40:00Z',
          primaryRole: 'SUPPORT',
          primaryReason: '5M Demand Test',
          vobState: 'TESTED',
          contract: { securityId: '45111', tradingSymbol: 'NIFTY 24500 PE', expiry: '2026-08-18', strike: 24500, optionType: 'PE', lotSize: 75, source: 'DHAN' },
          contractFrozenAt: null,
          evidenceRevision: 1,
        },
        levels: [],
        episodesByTimeframe: { '1M': null, '3M': null, '5M': null },
        underlyingSupport: 24227.25,
        underlyingResistance: 24384.40,
        underlyingSupportZone: { zoneLow: 24227.25, zoneHigh: 24245.03 },
        underlyingResistanceZone: { zoneLow: 24373.40, zoneHigh: 24384.40 },
      },
    })

    expect(vm.bias).toBe('PUT')
    expect(vm.positioning).toBe('CALL WRITE BUILD')
    expect(vm.buyPct).toBe(20.55)
    expect(vm.writePct).toBe(79.45)
    expect(vm.flowShift).toBe('OPTION ROTATION')
    expect(vm.nifty).toBe(24240.8)
    expect(vm.bullishVob).toBe(24227.25)
    expect(vm.bearishVob).toBe(24384.40)
    expect(vm.location).toBe('IN_ZONE')
    expect(vm.timeframe).toBe('5M')
    expect(vm.role).toBe('SUPPORT')
  })

  it('truthfully handles unpopulated ARGUS and VOB fields with UNKNOWN / null', () => {
    const vm = buildArgusVobViewModel({})
    expect(vm.bias).toBe(UNKNOWN)
    expect(vm.positioning).toBe(UNKNOWN)
    expect(vm.buyPct).toBeNull()
    expect(vm.writePct).toBeNull()
    expect(vm.flowShift).toBe(UNKNOWN)
    expect(vm.nifty).toBeNull()
    expect(vm.bearishVob).toBeNull()
    expect(vm.bullishVob).toBeNull()
    expect(vm.location).toBe(UNKNOWN)
    expect(vm.timeframe).toBe(UNKNOWN)
    expect(vm.role).toBeNull()
  })

  it('evaluates location relative to VOB boundaries correctly (BELOW, ABOVE, IN_ZONE)', () => {
    const below = buildArgusVobViewModel({
      argus: { bias: 'PUT', regime: null, buyerDominancePct: null, writerDominancePct: null, callWritingScore: null, putBuyingScore: null, callBuyingScore: null, putWritingScore: null, breakdownBelow: 24200, breakoutAbove: 24300, callWall: 24300, putWall: 24200, positioning: null },
      vob: { underlyingSupport: 24227.25, underlyingResistance: 24384.40, underlyingSupportZone: { zoneLow: 24227.25, zoneHigh: 24245.03 }, underlyingResistanceZone: { zoneLow: 24373.40, zoneHigh: 24384.40 } } as any,
      market: { underlying: 24150 } as any,
    })
    expect(below.location).toBe('BELOW')

    const inSupportZone = buildArgusVobViewModel({
      vob: { underlyingSupport: 24227.25, underlyingResistance: 24384.40, underlyingSupportZone: { zoneLow: 24227.25, zoneHigh: 24245.03 }, underlyingResistanceZone: { zoneLow: 24373.40, zoneHigh: 24384.40 } } as any,
      market: { underlying: 24235 } as any,
    })
    expect(inSupportZone.location).toBe('IN_ZONE')

    const above = buildArgusVobViewModel({
      argus: { bias: 'CALL', regime: null, buyerDominancePct: null, writerDominancePct: null, callWritingScore: null, putBuyingScore: null, callBuyingScore: null, putWritingScore: null, breakdownBelow: 24200, breakoutAbove: 24300, callWall: 24300, putWall: 24200, positioning: null },
      vob: { underlyingSupport: 24227.25, underlyingResistance: 24384.40, underlyingSupportZone: { zoneLow: 24227.25, zoneHigh: 24245.03 }, underlyingResistanceZone: { zoneLow: 24373.40, zoneHigh: 24384.40 } } as any,
      market: { underlying: 24400 } as any,
    })
    expect(above.location).toBe('ABOVE')
  })

  it('dynamic CALL bias and positioning automatically update without hardcoding', () => {
    const callVm = buildArgusVobViewModel({
      argus: {
        bias: 'CALL',
        regime: 'CALL_SURGE',
        buyerDominancePct: 58.0,
        writerDominancePct: 42.0,
        callWritingScore: 30,
        putBuyingScore: 20,
        callBuyingScore: 80,
        putWritingScore: 60,
        breakdownBelow: 24200,
        breakoutAbove: 24300,
        callWall: 24300,
        putWall: 24200,
        positioning: 'CALL LONG BUILD',
      },
      market: { underlying: 24280 } as any,
    })
    expect(callVm.bias).toBe('CALL')
    expect(callVm.positioning).toBe('CALL LONG BUILD')
    expect(callVm.buyPct).toBe(58.0)
    expect(callVm.writePct).toBe(42.0)
  })

  it('Case A & B & C: verifies focus strike, CE positioning, PE positioning, and participation metrics', () => {
    // Case A: PUT bias, CALL WRITE BUILD, CE = WRITING, PE = LONG BUILD
    const caseA = buildArgusVobViewModel({
      argus: {
        bias: 'PUT',
        regime: 'WRITER_DOMINATED',
        buyerDominancePct: 21.0,
        writerDominancePct: 79.0,
        callWritingScore: 71.46,
        putBuyingScore: 21.3,
        callBuyingScore: 0.0,
        putWritingScore: 7.24,
        breakdownBelow: 24200,
        breakoutAbove: 24300,
        callWall: 24300,
        putWall: 24200,
        positioning: 'CALL WRITE BUILD',
        focusStrike: 24300,
        focusStrikeLabel: 'FOCUS STRIKE',
        focusStrikeCePositioning: 'WRITING',
        focusStrikePePositioning: 'LONG BUILD',
      },
      market: { underlying: 24264.8 } as any,
      vob: { underlyingSupport: 24227.25, underlyingResistance: 24384.40 } as any,
    })
    expect(caseA.bias).toBe('PUT')
    expect(caseA.positioning).toBe('CALL WRITE BUILD')
    expect(caseA.buyPct).toBe(21.0)
    expect(caseA.writePct).toBe(79.0)
    expect(caseA.focusStrike).toBe(24300)
    expect(caseA.focusStrikeLabel).toBe('FOCUS STRIKE')
    expect(caseA.focusStrikeCePositioning).toBe('WRITING')
    expect(caseA.focusStrikePePositioning).toBe('LONG BUILD')

    // Case B: CALL bias, CALL LONG BUILD, CE = LONG BUILD, PE = SHORT COVER
    const caseB = buildArgusVobViewModel({
      argus: {
        bias: 'CALL',
        regime: 'BUYER_DOMINATED',
        buyerDominancePct: 74.0,
        writerDominancePct: 26.0,
        callWritingScore: 10.0,
        putBuyingScore: 5.0,
        callBuyingScore: 65.0,
        putWritingScore: 20.0,
        breakdownBelow: 24200,
        breakoutAbove: 24300,
        callWall: 24300,
        putWall: 24200,
        positioning: 'CALL LONG BUILD',
        focusStrike: 24250,
        focusStrikeLabel: 'FOCUS STRIKE',
        focusStrikeCePositioning: 'LONG BUILD',
        focusStrikePePositioning: 'SHORT COVER',
      },
      market: { underlying: 24285.0 } as any,
      vob: { underlyingSupport: 24227.25, underlyingResistance: 24384.40 } as any,
    })
    expect(caseB.bias).toBe('CALL')
    expect(caseB.positioning).toBe('CALL LONG BUILD')
    expect(caseB.buyPct).toBe(74.0)
    expect(caseB.writePct).toBe(26.0)
    expect(caseB.focusStrike).toBe(24250)
    expect(caseB.focusStrikeCePositioning).toBe('LONG BUILD')
    expect(caseB.focusStrikePePositioning).toBe('SHORT COVER')

    // Case C: Mixed / Unknown state without stale fallback
    const caseC = buildArgusVobViewModel({
      argus: {
        bias: UNKNOWN,
        regime: null,
        buyerDominancePct: null,
        writerDominancePct: null,
        callWritingScore: null,
        putBuyingScore: null,
        callBuyingScore: null,
        putWritingScore: null,
        breakdownBelow: null,
        breakoutAbove: null,
        callWall: null,
        putWall: null,
        positioning: null,
        focusStrike: null,
        focusStrikeLabel: null,
        focusStrikeCePositioning: null,
        focusStrikePePositioning: null,
      },
    })
    // Case D: Live ITM-1 Dynamic Strike Rotation
    const snapshotA = {
      underlying: 24285.0, // ATM = 24300
      canonicalAtmStrike: 24300,
      strikeInterval: 50,
      currentItmCall: {
        contract: { securityId: '45100', strike: 24250, optionType: 'CE' },
        premium: 145.5,
        dayChangePct: -12.4,
      },
      currentItmPut: {
        contract: { securityId: '45105', strike: 24350, optionType: 'PE' },
        premium: 98.2,
        dayChangePct: +4.5,
      },
    }
    expect(snapshotA.currentItmCall.contract.strike).toBe(24250)
    expect(snapshotA.currentItmPut.contract.strike).toBe(24350)

    // Spot moves up across 24325 boundary -> ATM becomes 24350
    const snapshotB = {
      underlying: 24345.0, // ATM = 24350
      canonicalAtmStrike: 24350,
      strikeInterval: 50,
      currentItmCall: {
        contract: { securityId: '45102', strike: 24300, optionType: 'CE' },
        premium: 109.85,
        dayChangePct: -31.94,
      },
      currentItmPut: {
        contract: { securityId: '45107', strike: 24400, optionType: 'PE' },
        premium: 65.8,
        dayChangePct: -7.78,
      },
    }
    expect(snapshotB.currentItmCall.contract.strike).toBe(24300)
    expect(snapshotB.currentItmPut.contract.strike).toBe(24400)
    expect(snapshotB.currentItmCall.contract.strike).not.toBe(snapshotA.currentItmCall.contract.strike)
    expect(snapshotB.currentItmPut.contract.strike).not.toBe(snapshotA.currentItmPut.contract.strike)
  })
})
