'use client'

import {
  useOracleStore,
} from '@/dashboard/store/oracleStore'

import {
  actionLabel,
  buildArgusVobViewModel,
  buildStory,
  controlLabel,
  evidenceStory,
  heroCopy,
  lifecycleSteps,
  magnetGeometry,
  observation,
  proximityLabel,
} from '../photonicPresentationHelpers'

export function usePhotonicCanonicalState() {
  const market = useOracleStore((state) => state.market)
  const vob = useOracleStore((state) => state.vob)
  const reversal = useOracleStore((state) => state.reversal)
  const trade = useOracleStore((state) => state.trade)
  const research = useOracleStore((state) => state.research)
  const runtime = useOracleStore((state) => state.runtime)
  const replay = useOracleStore((state) => state.replay)
  const argusSlice = useOracleStore((state) => state.argus)

  const isHistorical = replay.mode === 'HISTORICAL_REPLAY'
  const direction = reversal.direction
  const reversalState = reversal.state
  const vobState = reversal.vobState
  const scores = reversal.displayScores
  const episode = vob.episode

  // Resolver ITM-1 Call & Put
  const currentItmCall = market.currentItmCall
  const currentItmPut = market.currentItmPut
  const activeCe = market.activeCe
  const activePe = market.activePe

  // Current cards must derive every displayed VOB field from the same exact
  // resolver identity as their quote; legacy/frozen option slots are separate.
  const callGeometry = magnetGeometry(currentItmCall)
  const putGeometry = magnetGeometry(currentItmPut)
  const targetOption = direction === 'PUT' ? currentItmPut : currentItmCall
  const proximity = proximityLabel(targetOption)
  const currentTrackATrade = (securityId: string | null) => trade.activeTrades.find((item) => (
    item.variant === 'VOB_ONLY' && item.contract.securityId === securityId
  )) ?? null

  // Canonical ARGUS + VOB View Model
  const viewModel = buildArgusVobViewModel({ argus: argusSlice, market, reversal, vob })

  // Computed stories & steps
  const story = buildStory(episode?.timeframe ?? null, episode?.touchAt ?? null, direction, reversal.evidence)
  const evidenceRows = evidenceStory(direction, reversal.evidence)
  const steps = lifecycleSteps(episode, reversalState, isHistorical)
  const action = actionLabel(reversalState, direction, vobState)
  const heroDescription = heroCopy(reversalState, direction)
  const control = controlLabel(direction, reversalState)

  return {
    header: {
      symbol: market.symbol || 'NIFTY',
      underlying: market.underlying,
      spotChangePct: market.spotChangePct,
      futuresPrice: market.futuresPrice,
      futuresChangePct: market.futuresChangePct,
      atmStrike: market.canonicalAtmStrike,
      strikeInterval: market.strikeInterval,
      marketStatus: market.marketStatus,
      dataFreshness: market.dataFreshness,
      latencyMs: runtime.latencyMs,
      revision: runtime.revision,
      receiveTimestamp: runtime.receiveTimestamp,
      episodeId: episode?.episodeId ?? null,
      isHistorical,
      vobFreshness: runtime.vobFreshness,
      reversalFreshness: runtime.reversalFreshness,
      decisionFreshness: runtime.decisionFreshness,
    },
    resolver: {
      underlying: market.underlying,
      atmStrike: market.canonicalAtmStrike,
      strikeInterval: market.strikeInterval,
      marketStatus: market.marketStatus,
      pcr: market.pcr,
      openingPcr: market.openingPcr,
      deltaPcr: market.deltaPcr,
      deltaPcrPct: market.deltaPcrPct,
      changePcr: market.changePcr,
      currentItmCall,
      currentItmPut,
      isHistorical,
    },
    callCard: {
      option: currentItmCall,
      currentItm1: activeCe,
      target: direction === 'CALL',
      geometry: callGeometry,
      isHistorical,
      trade: currentTrackATrade(currentItmCall.contract.securityId),
      intelligence: market.buyerIntelligence,
    },
    putCard: {
      option: currentItmPut,
      currentItm1: activePe,
      target: direction === 'PUT',
      geometry: putGeometry,
      isHistorical,
      trade: currentTrackATrade(currentItmPut.contract.securityId),
      intelligence: market.buyerIntelligence,
    },
    heroWheel: {
      state: reversalState,
      direction,
      quality: reversal.quality,
      vobState,
      scores,
      action,
      heroDescription,
      argusState: reversal.evidence.argus_confirmation?.state ?? 'UNKNOWN',
      viewModel,
      proximity,
      intelligence: market.buyerIntelligence,
    },
    marketStory: {
      story,
      turnStrength: scores.turnStrength,
    },
    recovery: {
      direction,
      state: reversalState,
      turnStrength: scores.turnStrength,
      control,
      failed: observation(reversal.evidence, 'failed_aggression'),
      flow: observation(reversal.evidence, 'order_flow_rotation'),
      futures: observation(reversal.evidence, 'futures_response'),
    },
    argus: {
      argus: observation(reversal.evidence, 'argus_confirmation'),
      flow: observation(reversal.evidence, 'order_flow_rotation'),
      oi: observation(reversal.evidence, 'oi_context'),
      futures: observation(reversal.evidence, 'futures_response'),
      marketSupport: scores.marketSupport,
    },
    evidence: {
      rows: evidenceRows,
    },
    matchedPnl: {
      baseline: trade.variants.VOB_ONLY ?? null,
      early: trade.variants.EARLY_REVERSAL ?? null,
      confirmed: trade.variants.CONFIRMED_REVERSAL ?? null,
    },
    tradeLedger: {
      activeTrades: trade.activeTrades,
      episodesByTimeframe: vob.episodesByTimeframe,
      isHistorical,
    },
    vobLevels: {
      levels: vob.levels,
      episodeId: episode?.episodeId ?? null,
    },
    lifecycle: {
      steps,
    },
    scoreboard: {
      research,
    },
  }
}
