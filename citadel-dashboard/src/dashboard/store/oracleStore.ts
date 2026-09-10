'use client'

import { useStore } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'
import { createStore } from 'zustand/vanilla'

import type { DashboardSourceSnapshot } from '../types'

type JsonRecord = Record<string, unknown>
export type VobTimeframe = '1M' | '3M' | '5M'
export type VobSource = 'PULLBACK' | 'OSE' | 'CURRENT_ITM'

export interface OracleContractIdentity {
  securityId: string | null
  tradingSymbol: string | null
  expiry: string | null
  strike: number | null
  optionType: 'CE' | 'PE' | null
  lotSize: number | null
  source: string | null
}

export interface OracleVobEpisode {
  episodeId: string
  vobRevision: string
  sourceEngine: string
  sourceZoneId: string
  symbol: string
  direction: string
  timeframe: VobTimeframe | null
  zoneTop: number | null
  zoneBottom: number | null
  createdAt: string | null
  approachAt: string | null
  touchAt: string | null
  primaryRole: string
  primaryReason: string
  vobState: string
  contract: OracleContractIdentity
  contractFrozenAt: string | null
  evidenceRevision: number | null
}

export interface OracleVobLevel {
  timeframe: VobTimeframe
  sourceLineage: readonly VobSource[]
  reportedSource: VobSource | null
  alignment: string
  zoneTop: number | null
  zoneBottom: number | null
  state: string
  touchAt: string | null
  role: string
  primary: boolean
  episodeId: string | null
}

export interface OracleEvidenceObservation {
  state: string
  revision: string
  eventTime: string | null
  receiveTime: string | null
  persistence: number | null
  persistenceState: string
  quality: string
  known: boolean
}

export interface OracleShadowVariant {
  variant: 'VOB_ONLY' | 'EARLY_REVERSAL' | 'CONFIRMED_REVERSAL'
  contractSecurityId: string | null
  entryTime: string | null
  entryAsk: number | null
  initialSl: number | null
  target: number | null
  currentBid: number | null
  exitBid: number | null
  exitTime: string | null
  exitReason: string | null
  mfe: number | null
  mae: number | null
  r: number | null
  pnl: number | null
  confirmationDelay: number | null
  moveLostBeforeConfirmation: number | null
  evidenceMissing: readonly string[]
  postHoc: boolean
}

export interface OracleTradeRecord {
  tradeId: string
  episodeId: string
  timeframe: VobTimeframe | null
  variant: 'VOB_ONLY' | 'EARLY_REVERSAL' | 'CONFIRMED_REVERSAL'
  direction: string | null
  contract: OracleContractIdentity
  entryPrice: number | null
  entryTime: string | null
  exitTime: string | null
  exitReason: string | null
  currentBid: number | null
  stopLoss: number | null
  target: number | null
  status: 'ACTIVE' | 'CLOSED' | 'ELIGIBLE' | string
  pnl: number | null
  rMultiple: number | null
  mfe: number | null
  mae: number | null
}

export interface OracleOptionDisplay {
  contract: OracleContractIdentity
  contractStatus: string
  quoteSecurityId: string | null
  vobSecurityId: string | null
  premium: number | null
  bid: number | null
  ask: number | null
  quoteTimestamp: string | null
  freshness: string
  quoteSource: string | null
  vobTimeframe: VobTimeframe | null
  zoneTop: number | null
  zoneBottom: number | null
  zoneState: string
  zoneRole: string
  zoneSource: string | null
  zonePrimary: boolean
  /** Display metadata published by the canonical VOB engine for the exact contract. */
  zoneVolume?: string | null
  zonePercent?: number | null
  vobLanes?: readonly OracleOptionVobLane[]
  distancePoints: number | null
  distancePct: number | null
  insideZone: boolean | null
  nearestZoneBoundary: number | null
  relation: string
  dayPriceChange: number | null
  previousClose: number | null
  openingPrice: number | null
  dayChangePct: number | null
  oi: number | null
  openingOi: number | null
  changeOi: number | null
  changeOiPct: number | null
  positioning: string | null
  derivedPositioning: string | null
  positioningFormula: string | null
  positioningAgreement: string | null
  oi5mChange: OracleOiWindowChange | null
  oi15mChange: OracleOiWindowChange | null
  resolverEvent?: OracleResolverEvent | null
  horsepower?: OracleHorsepowerProjection | null
}

export interface OracleResolverLastMeaningfulEvent {
  securityId: string | null
  strike: string | null
  side: string | null
  label: string | null
  oiX: number | null
  flowX: number | null
  variant: string | null
  confluenceState: string | null
  eventTimestamp: string | null
  eventPrice: number | null
  eventOi: number | null
  reason: string | null
  isPreviousContract: boolean
  contextBadge: string | null
  ageSeconds: number | null
}

export interface OracleResolverEvent {
  label: string | null
  semanticDirection: string | null
  variant: 'mint' | 'red' | 'amber' | 'cyan' | string | null
  confluenceState: 'IDLE' | 'MIXED' | 'PARTIAL' | 'ALIGNED_SETTLED' | 'FULL_FRESH' | string | null
  pulseKey: string | null
  sourceEventTime: string | null
  heldPrevious: boolean
  lastMeaningfulEvent?: OracleResolverLastMeaningfulEvent | null
}

export interface OracleOiWindowChange {
  oiDelta: number | null
  oiPct: number | null
  priceDelta: number | null
  structure: string | null
  status?: string | null
  reason?: string | null
}

export interface OracleHorsepowerEvent {
  eventId: string
  instrument: string
  timeframe: string
  event: string
  zoneId: string
  confirmedCandle: string
  close: number | null
  notificationEligible: boolean
}

export interface OracleHorsepowerLane {
  status: string
  eventId: string | null
  supportBroken: number
  resistanceBroken: number
}

export interface OracleHorsepowerProjection {
  instrument: string
  sessionId: string | null
  timeframes: Readonly<Record<string, OracleHorsepowerLane>>
  combined: string
  pulse1m: string
  events: readonly OracleHorsepowerEvent[]
  continuity: string
  bootstrapMs: number | null
}

export interface OracleOptionVobLane {
  timeframe: VobTimeframe
  state: string
  role: string
  zoneTop: number | null
  zoneBottom: number | null
  zoneVolume: string | null
  zonePercent: number | null
  distancePoints: number | null
  distancePercent: number | null
}

export interface MarketSlice {
  symbol: string
  underlying: number | null
  canonicalAtmStrike: number | null
  strikeInterval: number | null
  marketStatus: string
  dataFreshness: string
  spotChangePct: number | null
  futuresPrice: number | null
  futuresChangePct: number | null
  pcr: number | null
  openingPcr: number | null
  deltaPcr: number | null
  deltaPcrPct: number | null
  changePcr: number | null
  activeCe: OracleContractIdentity
  activePe: OracleContractIdentity
  currentItmCall: OracleOptionDisplay
  currentItmPut: OracleOptionDisplay
  itmCall: OracleOptionDisplay
  itmPut: OracleOptionDisplay
  frozenEpisodeCall: OracleOptionDisplay | null
  frozenEpisodePut: OracleOptionDisplay | null
  buyerIntelligence: Readonly<Record<string, unknown>>
}

export interface VobSlice {
  episode: OracleVobEpisode | null
  levels: readonly OracleVobLevel[]
  episodesByTimeframe: Readonly<Record<VobTimeframe, OracleVobEpisode | null>>
  underlyingSupport: number | null
  underlyingResistance: number | null
  underlyingSupportZone: { zoneLow: number | null; zoneHigh: number | null } | null
  underlyingResistanceZone: { zoneLow: number | null; zoneHigh: number | null } | null
  underlyingHorsepower: OracleHorsepowerProjection | null
}

export interface ReversalSlice {
  state: string
  direction: string
  vobState: string
  quality: string
  evidence: Readonly<Record<string, OracleEvidenceObservation>>
  displayScores: Readonly<{ vobSetup: number | null; turnStrength: number | null; marketSupport: number | null; overall: number | null }>
}

export interface TradeSlice {
  entryRef: number | null
  slRef: number | null
  targetRef: number | null
  currentRef: number | null
  rr: number | null
  authority: string
  contract: OracleContractIdentity
  variants: Readonly<Record<string, OracleShadowVariant | null>>
  activeTrades: readonly OracleTradeRecord[]
}

export interface RuntimeSlice {
  revision: number
  schemaVersion: number | null
  sourceTimestamp: string | null
  receiveTimestamp: string | null
  vobFreshness: string
  reversalFreshness: string
  decisionFreshness: string
  latencyMs: number | null
  ignoredStaleRevisions: number
}

export interface ResearchSlice {
  matchedVobs: number | null
  vobAverageR: number | null
  confirmedAverageR: number | null
  expectancyDelta: number | null
  status: string
}

export interface ArgusSlice {
  bias: string
  regime: string | null
  buyerDominancePct: number | null
  writerDominancePct: number | null
  callWritingScore: number | null
  putBuyingScore: number | null
  callBuyingScore: number | null
  putWritingScore: number | null
  breakdownBelow: number | null
  breakoutAbove: number | null
  callWall: number | null
  putWall: number | null
  positioning: string | null
  focusStrike: number | null
  focusStrikeCePositioning: string | null
  focusStrikePePositioning: string | null
  focusStrikeLabel: string | null
}

export interface OracleHistoricalReplayFrame {
  snapshot: DashboardSourceSnapshot
  timestamp: string
  date: string
  contract: string
  timeframe: string
  episodeId: string
}

export interface ReplaySlice {
  mode: 'LIVE' | 'HISTORICAL_REPLAY'
  frames: readonly OracleHistoricalReplayFrame[]
  index: number
}

export interface OracleStoreState {
  market: MarketSlice
  vob: VobSlice
  reversal: ReversalSlice
  trade: TradeSlice
  runtime: RuntimeSlice
  research: ResearchSlice
  argus: ArgusSlice
  replay: ReplaySlice
  ingestSnapshot: (snapshot: DashboardSourceSnapshot, receivedAt?: string, source?: 'LIVE' | 'REPLAY') => void
  loadHistoricalReplay: (frames: readonly OracleHistoricalReplayFrame[]) => void
  stepHistoricalReplay: (index: number) => void
  exitHistoricalReplay: () => void
  reset: () => void
}

const UNKNOWN = 'UNKNOWN'
const emptyContract = (): OracleContractIdentity => ({
  securityId: null, tradingSymbol: null, expiry: null, strike: null,
  optionType: null, lotSize: null, source: null,
})
const emptyBuyerIntelligence = (): Readonly<Record<string, unknown>> => ({ status: 'UNAVAILABLE' })

const emptyLevels = (): readonly OracleVobLevel[] => ([
  levelShell('1M', ['PULLBACK']),
  levelShell('3M', ['PULLBACK', 'OSE']),
  levelShell('5M', ['OSE']),
])

const emptyEpisodesByTimeframe = (): Readonly<Record<VobTimeframe, OracleVobEpisode | null>> => ({
  '1M': null,
  '3M': null,
  '5M': null,
})

const emptyOptionDisplay = (): OracleOptionDisplay => ({
  contract: emptyContract(), contractStatus: UNKNOWN,
  quoteSecurityId: null, vobSecurityId: null,
  premium: null, bid: null, ask: null, quoteTimestamp: null,
  freshness: UNKNOWN, quoteSource: null,
  vobTimeframe: null, zoneTop: null, zoneBottom: null,
  zoneState: UNKNOWN, zoneRole: UNKNOWN, zoneSource: null, zonePrimary: false,
  distancePoints: null, distancePct: null, insideZone: null,
  nearestZoneBoundary: null, relation: UNKNOWN,
  dayPriceChange: null, previousClose: null, openingPrice: null, dayChangePct: null,
  oi: null, openingOi: null, changeOi: null, changeOiPct: null,
  positioning: null, derivedPositioning: null, positioningFormula: null, positioningAgreement: null,
  oi5mChange: null, oi15mChange: null,
  horsepower: null,
})

const emptyArgus = (): ArgusSlice => ({
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
  focusStrikeCePositioning: null,
  focusStrikePePositioning: null,
  focusStrikeLabel: null,
})

const emptyReplay = (): ReplaySlice => ({ mode: 'LIVE', frames: [], index: -1 })

const initialSlices = () => ({
  market: {
    symbol: 'NIFTY', underlying: null, marketStatus: UNKNOWN, dataFreshness: UNKNOWN,
    canonicalAtmStrike: null, strikeInterval: null,
    spotChangePct: null, futuresPrice: null, futuresChangePct: null,
    pcr: null, openingPcr: null, deltaPcr: null, deltaPcrPct: null, changePcr: null,
    activeCe: emptyContract(), activePe: emptyContract(),
    currentItmCall: emptyOptionDisplay(), currentItmPut: emptyOptionDisplay(),
    itmCall: emptyOptionDisplay(), itmPut: emptyOptionDisplay(),
    frozenEpisodeCall: null, frozenEpisodePut: null,
    buyerIntelligence: emptyBuyerIntelligence(),
  } satisfies MarketSlice,
  vob: {
    episode: null,
    levels: emptyLevels(),
    episodesByTimeframe: emptyEpisodesByTimeframe(),
    underlyingSupport: null,
    underlyingResistance: null,
    underlyingSupportZone: null,
    underlyingResistanceZone: null,
    underlyingHorsepower: null,
  } satisfies VobSlice,
  reversal: {
    state: UNKNOWN, direction: UNKNOWN, vobState: UNKNOWN, quality: UNKNOWN,
    evidence: {},
    displayScores: { vobSetup: null, turnStrength: null, marketSupport: null, overall: null },
  } satisfies ReversalSlice,
  trade: {
    entryRef: null, slRef: null, targetRef: null, currentRef: null, rr: null,
    authority: 'PULLBACK_MASTER', contract: emptyContract(), variants: {},
    activeTrades: [],
  } satisfies TradeSlice,
  runtime: {
    revision: -1, schemaVersion: null, sourceTimestamp: null, receiveTimestamp: null,
    vobFreshness: UNKNOWN, reversalFreshness: UNKNOWN, decisionFreshness: UNKNOWN,
    latencyMs: null, ignoredStaleRevisions: 0,
  } satisfies RuntimeSlice,
  research: {
    matchedVobs: null, vobAverageR: null, confirmedAverageR: null,
    expectancyDelta: null, status: 'NOT REPORTED',
  } satisfies ResearchSlice,
  argus: emptyArgus() satisfies ArgusSlice,
})

export const createOracleStore = () => createStore<OracleStoreState>()(subscribeWithSelector((set, get) => ({
  ...initialSlices(),
  replay: emptyReplay(),
  ingestSnapshot: (snapshot, receivedAt = new Date().toISOString(), source = 'LIVE') => {
    if (get().replay.mode === 'HISTORICAL_REPLAY' && source !== 'REPLAY') return
    const feeds = snapshot.feeds
    const vobFeed = record(feeds.vob_reversal)
    const projection = record(vobFeed.data ?? feeds.vob_reversal ?? record(feeds.oracle).vob)
    const market = parseMarket(feeds, snapshot.selectedSymbol, projection)
    const incomingRevision = integer(projection.revision)
    const incomingEpisode = record(projection.episode)
    const incomingEpisodeId = stringOrNull(incomingEpisode.episode_id)
    const currentEpisode = get().vob.episode
    const sameEpisode = incomingEpisodeId === (currentEpisode?.episodeId ?? null)
    const olderEpisode = incomingEpisodeId !== null && currentEpisode !== null && !sameEpisode
      && timestamp(incomingEpisode.created_at) < timestamp(currentEpisode.createdAt)
    const previousMarket = get().market
    const nextMarket = reuseMarket(previousMarket, market)
    const marketChanged = nextMarket !== previousMarket
    const meta = snapshot.feedMeta?.vob_reversal
    const nextArgus = parseArgus(feeds.argus)

    if (incomingRevision === null) {
      const missingFreshness = text(meta?.freshness ?? meta?.health)
      const runtime = {
        ...get().runtime,
        receiveTimestamp: receivedAt,
        vobFreshness: missingFreshness,
        reversalFreshness: missingFreshness,
        decisionFreshness: missingFreshness,
        latencyMs: number(meta?.latency_ms),
      }
      set({ ...(marketChanged ? { market: nextMarket } : {}), argus: reuseSlice(get().argus, nextArgus), runtime })
      return
    }

    if ((sameEpisode && incomingRevision <= get().runtime.revision) || olderEpisode) {
      if (marketChanged) set({ market: nextMarket })
      set({ argus: reuseSlice(get().argus, nextArgus) })
      if (incomingRevision < get().runtime.revision || olderEpisode) {
        set((state) => ({ runtime: { ...state.runtime, ignoredStaleRevisions: state.runtime.ignoredStaleRevisions + 1 } }))
      }
      return
    }

    const episode = parseEpisode(projection.episode)
    const episodesByTimeframe = parseEpisodesByTimeframe(projection.episodes_by_timeframe)
    const frozenEpisode = episode && currentEpisode?.episodeId === episode.episodeId
      ? { ...episode, contract: currentEpisode.contract, contractFrozenAt: currentEpisode.contractFrozenAt }
      : episode
    const evidence = parseEvidence(projection.evidence)
    const trade = parseTrade(projection, frozenEpisode, episodesByTimeframe)
    const levels = parseLevels(feeds.options_structure, frozenEpisode, projection)
    const sourceTimestamp = latestCanonicalTimestamp(frozenEpisode, evidence)
    const displayScores = record(projection.display_scores)
    const previous = get()
    const underlying = parseUnderlyingVob(feeds)
    const nextVob: VobSlice = {
      episode: reuseSlice(previous.vob.episode, frozenEpisode),
      levels: reuseSlice(previous.vob.levels, levels),
      episodesByTimeframe: reuseSlice(previous.vob.episodesByTimeframe, episodesByTimeframe),
      underlyingSupport: underlying.underlyingSupport,
      underlyingResistance: underlying.underlyingResistance,
      underlyingSupportZone: underlying.underlyingSupportZone,
      underlyingResistanceZone: underlying.underlyingResistanceZone,
      underlyingHorsepower: parseHorsepower(projection.nifty_horsepower),
    }
    const nextReversal: ReversalSlice = {
      state: text(projection.reversal_state),
      direction: text(projection.direction),
      vobState: text(projection.vob_state),
      quality: text(projection.quality),
      evidence,
      displayScores: {
        vobSetup: number(displayScores.vob_setup),
        turnStrength: number(displayScores.turn_strength),
        marketSupport: number(displayScores.market_support),
        overall: number(displayScores.overall),
      },
    }
    const nextResearch = parseResearch(projection)
    set({
      market: marketChanged ? nextMarket : previous.market,
      vob: reuseSlice(previous.vob, nextVob),
      reversal: reuseSlice(previous.reversal, nextReversal),
      trade: reuseSlice(previous.trade, trade),
      argus: reuseSlice(previous.argus, nextArgus),
      runtime: {
        revision: incomingRevision,
        schemaVersion: integer(projection.schema_version),
        sourceTimestamp,
        receiveTimestamp: receivedAt,
        vobFreshness: text(meta?.freshness ?? meta?.health),
        reversalFreshness: text(projection.quality),
        decisionFreshness: text(projection.quality),
        latencyMs: number(meta?.latency_ms),
        ignoredStaleRevisions: get().runtime.ignoredStaleRevisions,
      },
      research: reuseSlice(previous.research, nextResearch),
    })
  },
  loadHistoricalReplay: (frames) => {
    if (frames.length === 0) return
    const ordered = [...frames].sort((left, right) => timestamp(left.timestamp) - timestamp(right.timestamp))
    const frame = ordered[0]
    set({ ...initialSlices(), replay: { mode: 'HISTORICAL_REPLAY', frames: ordered, index: 0 } })
    get().ingestSnapshot(frame.snapshot, frame.timestamp, 'REPLAY')
  },
  stepHistoricalReplay: (index) => {
    const replay = get().replay
    if (replay.mode !== 'HISTORICAL_REPLAY' || replay.frames.length === 0) return
    const nextIndex = Math.max(0, Math.min(replay.frames.length - 1, Math.trunc(index)))
    const frame = replay.frames[nextIndex]
    set({ ...initialSlices(), replay: { ...replay, index: nextIndex } })
    get().ingestSnapshot(frame.snapshot, frame.timestamp, 'REPLAY')
  },
  exitHistoricalReplay: () => set({ ...initialSlices(), replay: emptyReplay() }),
  reset: () => set({ ...initialSlices(), replay: emptyReplay() }),
})))

export const oracleStoreApi = createOracleStore()
export const defaultOracleStore = oracleStoreApi
export const useOracleStore = <T>(selector: (state: OracleStoreState) => T): T => useStore(oracleStoreApi, selector)
export const ingestOracleDashboardSnapshot = (snapshot: DashboardSourceSnapshot, receivedAt?: string): void => {
  oracleStoreApi.getState().ingestSnapshot(snapshot, receivedAt)
}
export const loadOracleHistoricalReplay = (frames: readonly OracleHistoricalReplayFrame[]): void => {
  oracleStoreApi.getState().loadHistoricalReplay(frames)
}
export const stepOracleHistoricalReplay = (index: number): void => {
  oracleStoreApi.getState().stepHistoricalReplay(index)
}
export const exitOracleHistoricalReplay = (): void => {
  oracleStoreApi.getState().exitHistoricalReplay()
}

export function computeDerivedPositioning(
  dayPriceChange: number | null,
  changeOi: number | null,
  side: 'CE' | 'PE'
): {
  verdict: string
  formula: string
  priceDirection: 'UP' | 'DOWN' | 'FLAT'
  oiDirection: 'UP' | 'DOWN' | 'FLAT'
} {
  const priceDir: 'UP' | 'DOWN' | 'FLAT' = dayPriceChange === null || Math.abs(dayPriceChange) < 0.01
    ? 'FLAT'
    : dayPriceChange > 0 ? 'UP' : 'DOWN'

  const oiDir: 'UP' | 'DOWN' | 'FLAT' = changeOi === null || Math.abs(changeOi) === 0
    ? 'FLAT'
    : changeOi > 0 ? 'UP' : 'DOWN'

  const priceSymbol = priceDir === 'UP' ? 'PRICE ↑' : priceDir === 'DOWN' ? 'PRICE ↓' : 'PRICE —'
  const oiSymbol = oiDir === 'UP' ? 'OI ↑' : oiDir === 'DOWN' ? 'OI ↓' : 'OI —'
  const formula = `${priceSymbol} + ${oiSymbol}`

  let verdict = 'UNKNOWN'
  if (priceDir === 'UP' && oiDir === 'UP') {
    verdict = `${side === 'CE' ? 'CALL' : 'PUT'} LONG BUILD`
  } else if (priceDir === 'DOWN' && oiDir === 'UP') {
    verdict = `${side === 'CE' ? 'CALL' : 'PUT'} SHORT BUILD`
  } else if (priceDir === 'UP' && oiDir === 'DOWN') {
    verdict = `${side === 'CE' ? 'CALL' : 'PUT'} SHORT COVER`
  } else if (priceDir === 'DOWN' && oiDir === 'DOWN') {
    verdict = `${side === 'CE' ? 'CALL' : 'PUT'} LONG UNWIND`
  } else if (oiDir === 'UP') {
    verdict = 'OI BUILDING — PRICE NEUTRAL'
  } else if (oiDir === 'DOWN') {
    verdict = 'OI UNWINDING — PRICE NEUTRAL'
  }

  return { verdict, formula, priceDirection: priceDir, oiDirection: oiDir }
}

function formatBuildup(positioning: string | null | undefined, side: 'CE' | 'PE'): string {
  if (!positioning || positioning === UNKNOWN) return `${side} STRUCTURE`
  const norm = positioning.toUpperCase().replace(/_/g, ' ')
  if (norm.includes('SHORT BUILD')) return `${side === 'CE' ? 'CALL' : 'PUT'} SHORT BUILD`
  if (norm.includes('LONG BUILD')) return `${side === 'CE' ? 'CALL' : 'PUT'} LONG BUILD`
  if (norm.includes('SHORT COVER')) return `${side === 'CE' ? 'CALL' : 'PUT'} SHORT COVER`
  if (norm.includes('LONG UNWIND') || norm.includes('UNWIND')) return `${side === 'CE' ? 'CALL' : 'PUT'} LONG UNWIND`
  if (norm.includes('WRIT')) return `${side === 'CE' ? 'CALL' : 'PUT'} WRITING`
  if (norm.includes('BUY')) return `${side === 'CE' ? 'CALL' : 'PUT'} BUYING`
  return norm
}

function extractItm1FromArgus(
  argusData: JsonRecord,
  spotPrice: number | null,
): { CE: JsonRecord; PE: JsonRecord; canonicalMarket: JsonRecord } {
  const underlying = record(argusData.underlying)
  const atmStrike = number(underlying.atm_strike)
  const referencePrice = spotPrice ?? number(underlying.ltp)
  const totals = record(argusData.totals)
  const livePcr = record(argusData.live_pcr)

  // Canonical Current PCR
  const pcr = number(totals.pcr) ?? number(livePcr.oi_pcr)

  // Opening PCR / Baseline PCR Calculation
  const peOi = number(totals.pe_oi)
  const ceOi = number(totals.ce_oi)
  const dayPeChangeOi = number(totals.day_pe_change_oi ?? totals.pe_change_oi ?? totals.intraday_pe_change_oi)
  const dayCeChangeOi = number(totals.day_ce_change_oi ?? totals.ce_change_oi ?? totals.intraday_ce_change_oi)

  let openingPcr = number(totals.baseline_pcr ?? totals.opening_pcr ?? totals.session_pcr_baseline)
  if (openingPcr === null && peOi !== null && ceOi !== null && dayPeChangeOi !== null && dayCeChangeOi !== null) {
    const openingPeOi = peOi - dayPeChangeOi
    const openingCeOi = ceOi - dayCeChangeOi
    if (openingCeOi > 0) {
      openingPcr = Number((openingPeOi / openingCeOi).toFixed(4))
    }
  }

  let deltaPcr: number | null = null
  let deltaPcrPct: number | null = null
  if (pcr !== null && openingPcr !== null && openingPcr > 0) {
    deltaPcr = Number((pcr - openingPcr).toFixed(4))
    deltaPcrPct = Number((((pcr - openingPcr) / openingPcr) * 100).toFixed(2))
  }

  const changePcr = deltaPcr ?? number(totals.change_pcr) ?? number(totals.day_change_pcr)

  const canonicalMarket: JsonRecord = {
    atm_strike: atmStrike,
    reference_price: referencePrice,
    strike_interval: null,
    pcr,
    opening_pcr: openingPcr,
    delta_pcr: deltaPcr,
    delta_pcr_pct: deltaPcrPct,
    change_pcr: changePcr,
  }
  if (atmStrike === null) return { CE: {}, PE: {}, canonicalMarket }

  const rows = (Array.isArray(argusData.atm_window) ? argusData.atm_window : [])
    .map((r) => record(r))
    .filter((r) => number(r.strike) !== null)

  const ceRow = rows
    .filter((r) => (number(r.strike) ?? atmStrike) < atmStrike)
    .sort((a, b) => (number(b.strike) ?? -Infinity) - (number(a.strike) ?? -Infinity))[0]

  const peRow = rows
    .filter((r) => (number(r.strike) ?? atmStrike) > atmStrike)
    .sort((a, b) => (number(a.strike) ?? Infinity) - (number(b.strike) ?? Infinity))[0]

  if (!ceRow || !peRow) return { CE: {}, PE: {}, canonicalMarket }

  const ceStrike = number(ceRow.strike)
  const peStrike = number(peRow.strike)
  if (ceStrike === null || peStrike === null) return { CE: {}, PE: {}, canonicalMarket }
  const ceDelta = atmStrike - ceStrike
  const peDelta = peStrike - atmStrike
  if (ceDelta > 0 && peDelta > 0 && Math.abs(ceDelta - peDelta) <= 0.001) {
    canonicalMarket.strike_interval = ceDelta
  }

  const expiry = stringOrNull(underlying.expiry)
  const result: { CE: JsonRecord; PE: JsonRecord; canonicalMarket: JsonRecord } = { CE: {}, PE: {}, canonicalMarket }

  for (const side of ['CE', 'PE'] as const) {
    const row = side === 'CE' ? ceRow : peRow
    const strike = side === 'CE' ? ceStrike : peStrike
    const leg = record(row[side.toLowerCase()])
    const securityId = stringId(leg.security_id)
    if (!securityId) continue

    const ltp = number(leg.ltp)
    const dayPriceChange = number(leg.day_price_change ?? leg.price_change)
    const previousClose = number(leg.previous_close ?? leg.baseline_ltp)
    let dayChangePct: number | null = null
    if (dayPriceChange !== null && previousClose !== null && previousClose > 0) {
      dayChangePct = Number(((dayPriceChange / previousClose) * 100).toFixed(2))
    } else if (ltp !== null && previousClose !== null && previousClose > 0) {
      dayChangePct = Number((((ltp - previousClose) / previousClose) * 100).toFixed(2))
    }

    const oi = number(leg.oi)
    const openingOi = number(leg.baseline_oi ?? leg.previous_oi ?? leg.session_baseline_oi) ?? (oi !== null && number(leg.day_change_oi) !== null ? oi - (number(leg.day_change_oi) ?? 0) : null)
    const changeOi = number(leg.day_change_oi ?? leg.change_oi ?? leg.intraday_change_oi) ?? (oi !== null && openingOi !== null ? oi - openingOi : null)
    let changeOiPct: number | null = null
    if (changeOi !== null && openingOi !== null && openingOi > 0) {
      changeOiPct = Number(((changeOi / openingOi) * 100).toFixed(2))
    }

    const positioning = stringOrNull(leg.day_positioning ?? leg.positioning ?? leg.day_activity ?? leg.activity)
    const effectivePriceDelta = dayPriceChange ?? (ltp !== null && previousClose !== null ? ltp - previousClose : null)
    const derived = computeDerivedPositioning(effectivePriceDelta, changeOi, side)
    const dhanVerdict = positioning ? formatBuildup(positioning, side) : null
    let agreement: 'AGREED' | 'CONFLICT' | 'NOT_REPORTED' = 'NOT_REPORTED'
    if (dhanVerdict && derived.verdict !== 'UNKNOWN') {
      const normDhan = dhanVerdict.replace(/CALL|PUT|\s+/g, '').toUpperCase()
      const normDerived = derived.verdict.replace(/CALL|PUT|\s+/g, '').toUpperCase()
      agreement = normDhan.includes(normDerived) || normDerived.includes(normDhan) ? 'AGREED' : 'CONFLICT'
    }

    result[side] = {
      contract: {
        security_id: securityId,
        strike,
        option_type: side,
        expiry,
        source: 'ARGUS_OPTION_CHAIN_RESOLVER',
      },
      quote: {
        security_id: securityId,
        strike,
        option_type: side,
        ltp,
        bid: number(leg.top_bid_price),
        ask: number(leg.top_ask_price),
        day_price_change: dayPriceChange,
        previous_close: previousClose,
        opening_price: previousClose,
        day_change_pct: dayChangePct,
        oi,
        opening_oi: openingOi,
        change_oi: changeOi,
        change_oi_pct: changeOiPct,
        positioning,
        derived_positioning: derived.verdict,
        positioning_formula: derived.formula,
        positioning_agreement: agreement,
        source: 'ARGUS_DHAN_OPTION_CHAIN',
        timestamp: stringOrNull(underlying.source_event_time ?? underlying.fetched_at ?? underlying.receipt_timestamp),
      },
    }
  }
  return result
}

function enrichOptionRecord(
  target: JsonRecord,
  fallback: JsonRecord,
): JsonRecord {
  if (Object.keys(target).length === 0) return fallback
  if (Object.keys(fallback).length === 0) return target

  const targetContract = record(target.contract)
  const fallbackContract = record(fallback.contract)
  const targetQuote = record(target.quote)
  const fallbackQuote = record(fallback.quote)

  const contract = Object.keys(targetContract).length > 0 ? targetContract : fallbackContract
  const quote = {
    ...fallbackQuote,
    ...targetQuote,
    oi: targetQuote.oi ?? fallbackQuote.oi,
    opening_oi: targetQuote.opening_oi ?? fallbackQuote.opening_oi,
    change_oi: targetQuote.change_oi ?? targetQuote.day_change_oi ?? fallbackQuote.change_oi,
    day_change_oi: targetQuote.day_change_oi ?? targetQuote.change_oi ?? fallbackQuote.day_change_oi,
    change_oi_pct: targetQuote.change_oi_pct ?? fallbackQuote.change_oi_pct,
    positioning: targetQuote.positioning ?? targetQuote.day_positioning ?? fallbackQuote.positioning,
    day_positioning: targetQuote.day_positioning ?? targetQuote.positioning ?? fallbackQuote.day_positioning,
    derived_positioning: targetQuote.derived_positioning ?? fallbackQuote.derived_positioning,
    positioning_formula: targetQuote.positioning_formula ?? fallbackQuote.positioning_formula,
    positioning_agreement: targetQuote.positioning_agreement ?? fallbackQuote.positioning_agreement,
    day_price_change: targetQuote.day_price_change ?? fallbackQuote.day_price_change,
    previous_close: targetQuote.previous_close ?? fallbackQuote.previous_close,
    opening_price: targetQuote.opening_price ?? fallbackQuote.opening_price ?? targetQuote.previous_close ?? fallbackQuote.previous_close,
    day_change_pct: targetQuote.day_change_pct ?? fallbackQuote.day_change_pct,
  }

  return {
    ...target,
    contract,
    quote,
  }
}

function parseMarket(feeds: DashboardSourceSnapshot['feeds'], selectedSymbol: string, projection: JsonRecord): MarketSlice {
  const oracleEnvelope = record(feeds.oracle)
  const oraclePayload = record(oracleEnvelope.data)
  const oracle = Object.keys(oraclePayload).length > 0 ? oraclePayload : oracleEnvelope
  const features = record(oracle.input_features)
  const optionContracts = record(projection.option_contracts)
  const frozenEpisodeContracts = record(projection.frozen_episode_contracts)
  const canonicalMarket = record(projection.canonical_market)

  const futuresChart = record(feeds.futures_chart)
  const futuresData = record(futuresChart.data ?? feeds.futures_chart)
  const futuresPrice = number(futuresData.current_price) ?? number(record(futuresData.forming_candle).close)
  const candles = Array.isArray(futuresData.candles) ? futuresData.candles : []
  const firstCandle = record(candles[0])
  const dayOpen = number(firstCandle.open)
  let futuresChangePct: number | null = null
  if (futuresPrice !== null && dayOpen !== null && dayOpen > 0) {
    futuresChangePct = Number((((futuresPrice - dayOpen) / dayOpen) * 100).toFixed(2))
  }

  const argus = record(feeds.argus)
  const argusPayload = record(argus.data)
  const argusData = Object.keys(record(argusPayload.data)).length > 0 ? record(argusPayload.data) : (Object.keys(argusPayload).length > 0 ? argusPayload : argus)
  const argusUnderlying = record(argusData.underlying)
  const argusTacticalEdge = record(argusData.tactical_edge)
  const argusPrime = record(argusTacticalEdge.argus_prime)
  const argusDecision = record(argusTacticalEdge.decision)
  const oracleSessionStatus = text(features.session_status)
  const argusMarketState = text(argusUnderlying.market_state ?? argusPrime.market_state ?? argusDecision.market_state)
  const marketStatus = oracleSessionStatus !== 'UNAVAILABLE' && oracleSessionStatus !== UNKNOWN
    ? oracleSessionStatus
    : (argusMarketState === 'CLOSED' ? 'MARKET_CLOSED' : argusMarketState)
  const spotPrice = number(canonicalMarket.reference_price) ?? number(features.close) ?? number(argusUnderlying.ltp)
  const spotBaseline = number(argusUnderlying.baseline_ltp) ?? number(features.vwap)
  let spotChangePct: number | null = null
  if (spotPrice !== null && spotBaseline !== null && spotBaseline > 0) {
    spotChangePct = Number((((spotPrice - spotBaseline) / spotBaseline) * 100).toFixed(2))
  }

  const itmFromArgus = extractItm1FromArgus(argusData, spotPrice)
  const rawCurrentItm1 = record(projection.current_itm1_contracts)
  const currentCe = enrichOptionRecord(record(rawCurrentItm1.CE), record(itmFromArgus.CE))
  const currentPe = enrichOptionRecord(record(rawCurrentItm1.PE), record(itmFromArgus.PE))
  const activeCe = parseContract(record(currentCe.contract))
  const activePe = parseContract(record(currentPe.contract))

  const totals = record(argusData.totals)
  const pcr = number(canonicalMarket.pcr) ?? number(totals.pcr) ?? number(record(argus.totals).pcr) ?? number(record(argusData.live_pcr).oi_pcr) ?? number(itmFromArgus.canonicalMarket.pcr)
  const openingPcr = number(canonicalMarket.opening_pcr) ?? number(itmFromArgus.canonicalMarket.opening_pcr)
  const deltaPcr = (pcr !== null && openingPcr !== null) ? Number((pcr - openingPcr).toFixed(4)) : (number(canonicalMarket.delta_pcr) ?? number(itmFromArgus.canonicalMarket.delta_pcr))
  const deltaPcrPct = (deltaPcr !== null && openingPcr !== null && openingPcr > 0) ? Number(((deltaPcr / openingPcr) * 100).toFixed(2)) : (number(canonicalMarket.delta_pcr_pct) ?? number(itmFromArgus.canonicalMarket.delta_pcr_pct))
  const changePcr = deltaPcr ?? number(canonicalMarket.change_pcr) ?? number(totals.change_pcr) ?? number(totals.day_change_pcr) ?? number(itmFromArgus.canonicalMarket.change_pcr)
  const canonicalAtmStrike = number(canonicalMarket.atm_strike) ?? number(itmFromArgus.canonicalMarket.atm_strike)
  const strikeInterval = number(canonicalMarket.strike_interval) ?? number(itmFromArgus.canonicalMarket.strike_interval)

  const currentItmCall = parseOptionDisplay(currentCe, activeCe, 'CURRENT_ITM1')
  const currentItmPut = parseOptionDisplay(currentPe, activePe, 'CURRENT_ITM1')
  const frozenEpisodeCall = Object.keys(frozenEpisodeContracts).length > 0 ? parseOptionDisplay(record(frozenEpisodeContracts.CE), activeCe, 'FROZEN_EPISODE') : null
  const frozenEpisodePut = Object.keys(frozenEpisodeContracts).length > 0 ? parseOptionDisplay(record(frozenEpisodeContracts.PE), activePe, 'FROZEN_EPISODE') : null
  const buyerFeed = record(record(feeds).option_buyer_intelligence)
  const buyerPayload = record(buyerFeed.data)
  const buyerIntelligence = Object.keys(buyerPayload).length > 0 ? buyerPayload : buyerFeed

  // ── Merge 5M / 15M OI window data & Resolver Event from OBI into current ITM option displays ──
  const obiCe = record(buyerIntelligence.CE)
  const obiPe = record(buyerIntelligence.PE)
  currentItmCall.oi5mChange = parseOiWindowChange(record(obiCe.oi_5m_change))
  currentItmCall.oi15mChange = parseOiWindowChange(record(obiCe.oi_15m_change))
  currentItmCall.resolverEvent = parseResolverEvent(record(obiCe.resolver_event))
  currentItmPut.oi5mChange = parseOiWindowChange(record(obiPe.oi_5m_change))
  currentItmPut.oi15mChange = parseOiWindowChange(record(obiPe.oi_15m_change))
  currentItmPut.resolverEvent = parseResolverEvent(record(obiPe.resolver_event))

  return {
    symbol: text(oracle.symbol, selectedSymbol || 'NIFTY'),
    underlying: spotPrice,
    canonicalAtmStrike,
    strikeInterval,
    marketStatus,
    dataFreshness: text(oracle.data_status),
    spotChangePct,
    futuresPrice,
    futuresChangePct,
    pcr,
    openingPcr,
    deltaPcr,
    deltaPcrPct,
    changePcr,
    activeCe,
    activePe,
    currentItmCall,
    currentItmPut,
    itmCall: parseOptionDisplay(record(optionContracts.CE), activeCe, text(record(optionContracts.CE).contract_status, 'CURRENT_ITM1')),
    itmPut: parseOptionDisplay(record(optionContracts.PE), activePe, text(record(optionContracts.PE).contract_status, 'CURRENT_ITM1')),
    frozenEpisodeCall,
    frozenEpisodePut,
    buyerIntelligence,
  }
}

function parseResolverEvent(value: JsonRecord): OracleResolverEvent | null {
  if (!value || Object.keys(value).length === 0) return null
  const label = stringOrNull(value.label)
  const semanticDirection = stringOrNull(value.semantic_direction)
  const variant = stringOrNull(value.variant)
  const confluenceState = stringOrNull(value.confluence_state)
  const pulseKey = stringOrNull(value.pulse_key)
  const sourceEventTime = stringOrNull(value.source_event_time)
  const heldPrevious = value.held_previous === true

  const rawLm = record(value.last_meaningful_event)
  let lastMeaningfulEvent: OracleResolverLastMeaningfulEvent | null = null
  if (Object.keys(rawLm).length > 0) {
    lastMeaningfulEvent = {
      securityId: stringOrNull(rawLm.security_id),
      strike: stringOrNull(rawLm.strike),
      side: stringOrNull(rawLm.side),
      label: stringOrNull(rawLm.label),
      oiX: number(rawLm.oi_x),
      flowX: number(rawLm.flow_x),
      variant: stringOrNull(rawLm.variant),
      confluenceState: stringOrNull(rawLm.confluence_state),
      eventTimestamp: stringOrNull(rawLm.event_timestamp),
      eventPrice: number(rawLm.event_price),
      eventOi: number(rawLm.event_oi),
      reason: stringOrNull(rawLm.reason),
      isPreviousContract: rawLm.is_previous_contract === true,
      contextBadge: stringOrNull(rawLm.context_badge),
      ageSeconds: number(rawLm.age_seconds),
    }
  }

  if (label === null && variant === null && lastMeaningfulEvent === null) return null
  return {
    label,
    semanticDirection,
    variant,
    confluenceState,
    pulseKey,
    sourceEventTime,
    heldPrevious,
    lastMeaningfulEvent,
  }
}

function parseOiWindowChange(value: JsonRecord): OracleOiWindowChange | null {
  if (!value || Object.keys(value).length === 0) return null
  const oiDelta = number(value.oi_delta)
  const oiPct = number(value.oi_pct)
  const priceDelta = number(value.price_delta)
  const structure = stringOrNull(value.structure)
  const status = stringOrNull(value.status)
  const reason = stringOrNull(value.reason)
  if (oiDelta === null && oiPct === null && priceDelta === null && structure === null && status === null) return null
  return { oiDelta, oiPct, priceDelta, structure, status, reason }
}

function parseOptionDisplay(value: JsonRecord, fallbackContract: OracleContractIdentity, fallbackStatus = UNKNOWN): OracleOptionDisplay {
  const quote = record(value.quote)
  const publishedVob = record(value.vob)
  const distance = record(value.distance)
  const parsedContract = parseContract(record(value.contract))
  const contract = parsedContract.securityId ? parsedContract : fallbackContract
  const quoteSecurityId = stringId(quote.security_id)
  const quoteMatchesContract = quoteSecurityId === null || quoteSecurityId === contract.securityId
  const publishedVobSecurityId = stringId(publishedVob.security_id)
  // CURRENT cards may only consume a VOB generated for their exact resolver identity.
  // A missing/mismatched identity is deliberately shown as not reported, never as a
  // fallback from an expired, OSE-anchor, or frozen episode contract.
  const hasCanonicalVob = publishedVobSecurityId !== null
    ? publishedVobSecurityId === contract.securityId
    : fallbackStatus !== 'CURRENT_ITM1' && Object.keys(publishedVob).length > 0
  const vob = hasCanonicalVob ? publishedVob : {}
  const primaryLane = hasCanonicalVob ? parsePrimaryOptionVobLane(vob) : null
  return {
    contract,
    contractStatus: text(value.contract_status, fallbackStatus),
    quoteSecurityId,
    vobSecurityId: hasCanonicalVob ? (publishedVobSecurityId ?? contract.securityId) : null,
    premium: quoteMatchesContract ? number(quote.ltp) : null,
    bid: quoteMatchesContract ? number(quote.bid) : null,
    ask: quoteMatchesContract ? number(quote.ask) : null,
    quoteTimestamp: stringOrNull(quote.timestamp), freshness: text(quote.freshness, quote.timestamp ? 'RECEIVED' : 'UNAVAILABLE'),
    quoteSource: stringOrNull(quote.source),
    vobTimeframe: timeframe(vob.timeframe),
    zoneTop: number(vob.zone_top), zoneBottom: number(vob.zone_bottom),
    zoneState: text(vob.state), zoneRole: text(vob.role),
    zoneSource: stringOrNull(vob.source), zonePrimary: vob.primary === true,
    zoneVolume: primaryLane?.zoneVolume ?? null,
    zonePercent: primaryLane?.zonePercent ?? null,
    vobLanes: hasCanonicalVob ? parseOptionVobLanes(vob) : [],
    distancePoints: number(distance.distance_to_zone_points) ?? primaryLane?.distancePoints ?? null,
    distancePct: number(distance.distance_to_zone_pct) ?? primaryLane?.distancePercent ?? null,
    insideZone: typeof distance.inside_zone === 'boolean' ? distance.inside_zone : null,
    nearestZoneBoundary: number(distance.nearest_zone_boundary),
    relation: text(distance.relation),
    dayPriceChange: number(quote.day_price_change),
    previousClose: number(quote.previous_close),
    openingPrice: number(quote.opening_price ?? quote.previous_close),
    dayChangePct: number(quote.day_change_pct),
    oi: number(quote.oi),
    openingOi: number(quote.opening_oi ?? quote.baseline_oi ?? quote.previous_oi),
    changeOi: number(quote.day_change_oi ?? quote.change_oi ?? quote.changeOi ?? quote.intraday_change_oi),
    changeOiPct: number(quote.change_oi_pct ?? quote.changeOiPct),
    positioning: stringOrNull(quote.day_positioning ?? quote.positioning ?? quote.day_activity ?? quote.activity),
    derivedPositioning: stringOrNull(quote.derived_positioning),
    positioningFormula: stringOrNull(quote.positioning_formula),
    positioningAgreement: stringOrNull(quote.positioning_agreement),
    oi5mChange: null,
    oi15mChange: null,
    horsepower: parseHorsepower(vob.horsepower),
  }
}

function parseHorsepower(value: unknown): OracleHorsepowerProjection | null {
  const raw = record(value)
  const instrument = stringOrNull(raw.instrument)
  if (!instrument || text(raw.status) === 'UNAVAILABLE') return null
  const rawTimeframes = record(raw.timeframes)
  const timeframes: Record<string, OracleHorsepowerLane> = {}
  for (const key of ['1m', '3m', '5m']) {
    const lane = record(rawTimeframes[key])
    timeframes[key] = {
      status: text(lane.status, 'NEUTRAL'),
      eventId: stringOrNull(lane.event_id),
      supportBroken: integer(lane.support_broken) ?? 0,
      resistanceBroken: integer(lane.resistance_broken) ?? 0,
    }
  }
  const events = (Array.isArray(raw.events) ? raw.events : []).flatMap((value) => {
    const event = record(value)
    const eventId = stringOrNull(event.event_id)
    const zoneId = stringOrNull(event.zone_id)
    const confirmedCandle = stringOrNull(event.confirmed_candle)
    if (!eventId || !zoneId || !confirmedCandle) return []
    return [{
      eventId,
      instrument: text(event.instrument, instrument),
      timeframe: text(event.timeframe),
      event: text(event.event),
      zoneId,
      confirmedCandle,
      close: number(event.close),
      notificationEligible: event.notification_eligible === true,
    } satisfies OracleHorsepowerEvent]
  })
  return {
    instrument,
    sessionId: stringOrNull(raw.session_id),
    timeframes,
    combined: text(raw.combined, 'IDLE'),
    pulse1m: text(raw.pulse_1m, 'NEUTRAL'),
    events,
    continuity: text(raw.continuity),
    bootstrapMs: number(raw.bootstrap_ms),
  }
}

function parsePrimaryOptionVobLane(vob: JsonRecord): OracleOptionVobLane | null {
  const zoneId = stringOrNull(vob.zone_id)
  const lane = record(record(vob.timeframes)[String(vob.timeframe ?? '').toLowerCase()])
  for (const candidate of [record(lane.demand), record(lane.supply)]) {
    if (zoneId && stringOrNull(candidate.zone_id) === zoneId) return parseOptionVobLane(String(vob.timeframe), candidate, lane)
  }
  return null
}

function parseOptionVobLanes(vob: JsonRecord): readonly OracleOptionVobLane[] {
  return ['1m', '3m', '5m'].map((key) => {
    const lane = record(record(vob.timeframes)[key])
    const candidates = [record(lane.demand), record(lane.supply)].filter((candidate) => Object.keys(candidate).length > 0)
    const selected = candidates.find((candidate) => text(candidate.status) === 'ACTIVE')
      ?? candidates.find((candidate) => text(candidate.status) === 'TESTED')
      ?? candidates[0]
      ?? {}
    return parseOptionVobLane(key, selected, lane)
  })
}

function parseOptionVobLane(value: string, zone: JsonRecord, lane: JsonRecord): OracleOptionVobLane {
  return {
    timeframe: timeframe(value) ?? '1M',
    state: text(zone.status, text(lane.state)),
    role: text(zone.role),
    zoneTop: number(zone.zone_high),
    zoneBottom: number(zone.zone_low),
    zoneVolume: stringOrNull(zone.origin_volume_formatted),
    zonePercent: number(zone.volume_ratio) === null ? null : Number((number(zone.volume_ratio)! * 100).toFixed(2)),
    distancePoints: number(zone.distance_points),
    distancePercent: number(zone.distance_percent),
  }
}

function parseEpisode(value: unknown): OracleVobEpisode | null {
  const episode = record(value)
  const episodeId = stringOrNull(episode.episode_id)
  if (!episodeId) return null
  return {
    episodeId,
    vobRevision: text(episode.vob_revision),
    sourceEngine: text(episode.source_engine),
    sourceZoneId: text(episode.source_zone_id),
    symbol: text(episode.symbol, 'NIFTY'),
    direction: text(episode.direction),
    timeframe: timeframe(episode.timeframe),
    zoneTop: number(episode.zone_top),
    zoneBottom: number(episode.zone_bottom),
    createdAt: stringOrNull(episode.created_at),
    approachAt: stringOrNull(episode.approach_at),
    touchAt: stringOrNull(episode.touch_at),
    primaryRole: text(episode.primary_role),
    primaryReason: text(episode.primary_reason),
    vobState: text(episode.vob_state),
    contract: parseContract(record(episode.contract_identity)),
    contractFrozenAt: stringOrNull(episode.contract_frozen_at),
    evidenceRevision: integer(episode.evidence_revision),
  }
}

function parseEpisodesByTimeframe(value: unknown): Readonly<Record<VobTimeframe, OracleVobEpisode | null>> {
  const map = record(value)
  return {
    '1M': parseEpisode(map['1m'] ?? map['1M']),
    '3M': parseEpisode(map['3m'] ?? map['3M']),
    '5M': parseEpisode(map['5m'] ?? map['5M']),
  }
}

function parseEvidence(value: unknown): Readonly<Record<string, OracleEvidenceObservation>> {
  return Object.fromEntries(Object.entries(record(value)).map(([key, item]) => {
    const row = record(item)
    return [key, {
      state: text(row.state), revision: text(row.revision, '0'),
      eventTime: stringOrNull(row.event_time), receiveTime: stringOrNull(row.receive_time),
      persistence: integer(row.persistence), persistenceState: text(row.persistence_state),
      quality: text(row.quality), known: row.known === true,
    } satisfies OracleEvidenceObservation]
  }))
}

function parseTrade(
  projection: JsonRecord,
  episode: OracleVobEpisode | null,
  episodesByTf: Readonly<Record<VobTimeframe, OracleVobEpisode | null>>,
): TradeSlice {
  const authority = record(projection.authority)
  const shadow = record(projection.shadow)
  const variants = Object.fromEntries(['VOB_ONLY', 'EARLY_REVERSAL', 'CONFIRMED_REVERSAL'].map((variant) => [
    variant,
    parseShadowVariant(variant as OracleShadowVariant['variant'], shadow[variant]),
  ]))
  const activeTrades = parseActiveTrades(projection.all_shadow_trades, episodesByTf, episode, shadow)
  return {
    entryRef: number(projection.entry_ref), slRef: number(projection.sl_ref),
    targetRef: number(projection.target_ref), currentRef: number(projection.current_ref),
    rr: number(projection.rr),
    authority: text(authority.entry_sl_target_one_use_trail, 'PULLBACK_MASTER'),
    contract: episode?.contract ?? emptyContract(), variants,
    activeTrades,
  }
}

function parseShadowVariant(variant: OracleShadowVariant['variant'], value: unknown): OracleShadowVariant | null {
  const row = record(value)
  if (!Object.keys(row).length) return null
  return {
    variant,
    contractSecurityId: stringOrNull(row.contract_security_id),
    entryTime: stringOrNull(row.entry_time), entryAsk: number(row.entry_ask),
    initialSl: number(row.initial_sl), target: number(row.target), currentBid: number(row.current_bid),
    exitBid: number(row.exit_bid), exitTime: stringOrNull(row.exit_time), exitReason: stringOrNull(row.exit_reason),
    mfe: number(row.mfe), mae: number(row.mae), r: number(row.r), pnl: number(row.pnl),
    confirmationDelay: number(row.confirmation_delay), moveLostBeforeConfirmation: number(row.move_lost_before_confirmation),
    evidenceMissing: Array.isArray(row.evidence_missing) ? row.evidence_missing.map(String) : [],
    postHoc: row.post_hoc === true,
  }
}

function parseActiveTrades(
  allShadowValue: unknown,
  episodesByTf: Readonly<Record<VobTimeframe, OracleVobEpisode | null>>,
  primaryEpisode: OracleVobEpisode | null,
  shadowFallback: JsonRecord,
): readonly OracleTradeRecord[] {
  const allShadow = record(allShadowValue)
  const episodesById = new Map<string, OracleVobEpisode>()
  if (primaryEpisode?.episodeId) episodesById.set(primaryEpisode.episodeId, primaryEpisode)
  for (const ep of Object.values(episodesByTf)) {
    if (ep?.episodeId) episodesById.set(ep.episodeId, ep)
  }

  const records: OracleTradeRecord[] = []
  const hasAllShadow = Object.keys(allShadow).length > 0
  const sources: [string, JsonRecord][] = hasAllShadow
    ? Object.entries(allShadow).map(([epId, val]) => [epId, record(val)])
    : (primaryEpisode?.episodeId ? [[primaryEpisode.episodeId, shadowFallback]] : [])

  for (const [epId, variantsRecord] of sources) {
    const variants = record(variantsRecord)
    const ep = episodesById.get(epId)
    for (const [variantName, data] of Object.entries(variants)) {
      const row = record(data)
      if (!Object.keys(row).length) continue
      const variant = variantName as OracleShadowVariant['variant']
      if (variant !== 'VOB_ONLY' && variant !== 'EARLY_REVERSAL' && variant !== 'CONFIRMED_REVERSAL') continue
      const entryAsk = number(row.entry_ask ?? row.entry_price)
      const tf = timeframe(row.timeframe ?? ep?.timeframe)
      const tradeId = text(row.trade_id, `${epId}_${variant}`)
      const exitTime = stringOrNull(row.exit_time)
      const status = exitTime ? 'CLOSED' : entryAsk !== null ? 'ACTIVE' : 'ELIGIBLE'
      const contract = ep?.contract ?? (row.contract_security_id ? {
        securityId: stringOrNull(row.contract_security_id),
        tradingSymbol: null,
        expiry: stringOrNull(row.contract_expiry),
        strike: null,
        optionType: null,
        lotSize: null,
        source: null,
      } : emptyContract())

      records.push({
        tradeId,
        episodeId: epId,
        timeframe: tf,
        variant,
        direction: ep?.direction ?? null,
        contract,
        entryPrice: entryAsk,
        entryTime: stringOrNull(row.entry_time),
        exitTime,
        exitReason: stringOrNull(row.exit_reason),
        currentBid: number(row.current_bid),
        stopLoss: number(row.initial_sl ?? row.stop_loss),
        target: number(row.target),
        status,
        pnl: number(row.pnl),
        rMultiple: number(row.r ?? row.r_multiple),
        mfe: number(row.mfe),
        mae: number(row.mae),
      })
    }
  }

  return records.sort((a, b) => {
    const timeA = timestamp(a.entryTime)
    const timeB = timestamp(b.entryTime)
    if (timeA !== timeB) return timeB - timeA
    return a.tradeId.localeCompare(b.tradeId)
  })
}

function parseLevels(
  optionsValue: unknown,
  episode: OracleVobEpisode | null,
  projection: JsonRecord,
): readonly OracleVobLevel[] {
  const options = record(optionsValue)
  const contracts = record(options.contracts)
  const side = episode?.contract.optionType
  const currentItm = record(projection.current_itm1_contracts)
  const current = side ? record(currentItm[side]) : {}
  const currentContract = record(current.contract)
  const currentVob = record(current.vob)
  const exactCurrentVob = stringId(currentVob.security_id) !== null
    && stringId(currentVob.security_id) === stringId(currentContract.security_id)
    ? currentVob
    : {}
  const currentTimeframes = record(exactCurrentVob.timeframes)
  const structures = Object.keys(currentTimeframes).length
    ? currentTimeframes
    : side ? record(record(contracts[side]).structures) : {}
  const levels = [...emptyLevels()]
  for (const name of ['1M', '3M', '5M'] as const) {
    const structure = record(structures[name.toLowerCase()])
    const demand = record(structure.demand)
    if (!Object.keys(demand).length) continue
    const index = name === '1M' ? 0 : name === '3M' ? 1 : 2
    levels[index] = {
      ...levels[index], reportedSource: Object.keys(currentTimeframes).length ? 'CURRENT_ITM' : 'OSE',
      zoneTop: number(demand.zone_high), zoneBottom: number(demand.zone_low),
      state: text(demand.status), touchAt: stringOrNull(demand.last_tested_time ?? demand.first_tested_time),
      role: text(demand.role),
    }
  }
  const episodeMatchesCurrent = Boolean(
    episode
    && stringId(episode.contract.securityId) !== null
    && stringId(episode.contract.securityId) === stringId(currentContract.security_id),
  )
  if (episode?.timeframe && (!Object.keys(currentTimeframes).length || episodeMatchesCurrent)) {
    const index = episode.timeframe === '1M' ? 0 : episode.timeframe === '3M' ? 1 : 2
    levels[index] = {
      ...levels[index],
      reportedSource: episode.sourceEngine.includes('OPTIONS_STRUCTURE') ? 'OSE' : 'PULLBACK',
      zoneTop: episode.zoneTop, zoneBottom: episode.zoneBottom, state: episode.vobState,
      touchAt: episode.touchAt, role: episode.primaryRole, primary: true, episodeId: episode.episodeId,
    }
  }
  return levels
}

function parseUnderlyingVob(feeds: DashboardSourceSnapshot['feeds']) {
  const lab = record(feeds.strategy_lab)
  const execution = record(lab.execution ?? lab.data)
  const niftyVob = record(execution.nifty_vob ?? record(feeds.oracle).vob)
  const timeframes = record(niftyVob.timeframes)
  const vob5m = record(timeframes['5m'] ?? timeframes['5M'])
  const vob3m = record(timeframes['3m'] ?? timeframes['3M'])
  const vob15m = record(timeframes['15m'] ?? timeframes['15M'])

  const nearestSupport = record(vob5m.nearest_bullish_support ?? niftyVob.nearest_support ?? vob3m.nearest_bullish_support ?? vob15m.nearest_bullish_support)
  const nearestResistance = record(vob5m.nearest_bearish_resistance ?? niftyVob.nearest_resistance ?? vob3m.nearest_bearish_resistance ?? vob15m.nearest_bearish_resistance)

  const supportLow = number(nearestSupport.zone_low)
  const supportHigh = number(nearestSupport.zone_high)
  const resistanceLow = number(nearestResistance.zone_low)
  const resistanceHigh = number(nearestResistance.zone_high)

  return {
    underlyingSupport: supportLow ?? supportHigh ?? null,
    underlyingResistance: resistanceHigh ?? resistanceLow ?? null,
    underlyingSupportZone: (supportLow !== null || supportHigh !== null) ? { zoneLow: supportLow, zoneHigh: supportHigh } : null,
    underlyingResistanceZone: (resistanceLow !== null || resistanceHigh !== null) ? { zoneLow: resistanceLow, zoneHigh: resistanceHigh } : null,
  }
}

function parseResearch(projection: JsonRecord): ResearchSlice {
  const aggregate = record(projection.research_summary)
  return {
    matchedVobs: integer(aggregate.matched_vobs),
    vobAverageR: number(aggregate.vob_average_r),
    confirmedAverageR: number(aggregate.confirmed_average_r),
    expectancyDelta: number(aggregate.expectancy_delta),
    status: Object.keys(aggregate).length ? text(aggregate.status, 'AVAILABLE') : 'NOT REPORTED',
  }
}

function cleanPositioning(raw: string | null | undefined): string | null {
  if (!raw) return null
  const upper = raw.toUpperCase().replaceAll('_', ' ')
  if (upper.includes('WRIT')) return 'WRITING'
  if (upper.includes('LONG BUILD') || upper.includes('BUY')) return 'LONG BUILD'
  if (upper.includes('SHORT COVER')) return 'SHORT COVER'
  if (upper.includes('SHORT BUILD')) return 'SHORT BUILD'
  if (upper.includes('UNWIND')) return 'LONG UNWIND'
  return upper
}

function parseArgus(value: unknown): ArgusSlice {
  const argusFeed = record(value)
  const argusData = record(argusFeed.data)
  const verdict = record(argusData.verdict)
  const dominance = record(argusData.dominance)
  const tacticalEdge = record(argusData.tactical_edge)
  const walls = record(argusData.walls)
  const breakdownBelow = number(verdict.breakdown_below) ?? number(record(verdict.put_wall).strike)
  const breakoutAbove = number(verdict.breakout_above) ?? number(record(verdict.call_wall).strike)
  const biasRaw = text(verdict.bias).toUpperCase()
  const bias = biasRaw.includes('BEAR') || biasRaw === 'PUT' ? 'PUT' : biasRaw.includes('BULL') || biasRaw === 'CALL' ? 'CALL' : biasRaw === 'BALANCED' ? 'BALANCED' : biasRaw.includes('RANGE') ? 'RANGE BOUND' : biasRaw

  let positioning: string | null = null
  const dominant = stringOrNull(tacticalEdge.dominant_positioning)
  if (dominant) {
    positioning = dominant
  } else {
    const callWriting = number(dominance.call_writing_score) ?? 0
    const putBuying = number(dominance.put_buying_score) ?? 0
    const callBuying = number(dominance.call_buying_score) ?? 0
    const putWriting = number(dominance.put_writing_score) ?? 0
    if (callWriting > 50 && callWriting >= putBuying && callWriting >= callBuying && callWriting >= putWriting) {
      positioning = 'CALL WRITE BUILD'
    } else if (putBuying > 50 && putBuying >= callWriting && putBuying >= callBuying && putBuying >= putWriting) {
      positioning = 'PUT LONG BUILD'
    } else if (callBuying > 50 && callBuying >= callWriting && callBuying >= putBuying && callBuying >= putWriting) {
      positioning = 'CALL LONG BUILD'
    } else if (putWriting > 50 && putWriting >= callWriting && putWriting >= putBuying && putWriting >= callBuying) {
      positioning = 'PUT WRITE BUILD'
    } else if (dominance.buyer_dominance_percentage !== undefined && dominance.writer_dominance_percentage !== undefined) {
      positioning = 'MIXED'
    }
  }

  const prime = record(tacticalEdge.argus_prime)
  const presentation = record(prime.canonical_presentation)
  const highestLoad = record(presentation.highest_load)
  const bestStack = number(presentation.best_stack_strike)
  const focusStrike = number(highestLoad.strike) ?? bestStack ?? number(record(walls.highest_ce_oi).strike) ?? number(record(verdict.call_wall).strike) ?? number(tacticalEdge.anchor) ?? null
  const focusStrikeLabel = focusStrike !== null ? 'FOCUS STRIKE' : null

  let focusStrikeCePositioning: string | null = null
  let focusStrikePePositioning: string | null = null

  if (focusStrike !== null) {
    const pressure = record(tacticalEdge.pressure)
    const strikes = Array.isArray(pressure.strikes) ? pressure.strikes.map(record) : []
    const match = strikes.find((row) => number(row.strike) === focusStrike)
    if (match) {
      const ce = record(match.CE)
      const pe = record(match.PE)
      focusStrikeCePositioning = cleanPositioning(text(ce.activity) ?? text(ce.positioning))
      focusStrikePePositioning = cleanPositioning(text(pe.activity) ?? text(pe.positioning))
    }

    if (!focusStrikeCePositioning || !focusStrikePePositioning) {
      const fullSpine = Array.isArray(presentation.full_spine) ? presentation.full_spine.map(record) : []
      const spineMatch = fullSpine.find((row) => number(row.strike) === focusStrike)
      if (spineMatch) {
        if (!focusStrikeCePositioning) focusStrikeCePositioning = cleanPositioning(text(spineMatch.ce_flow))
        if (!focusStrikePePositioning) focusStrikePePositioning = cleanPositioning(text(spineMatch.pe_flow))
      }
    }
  }

  return {
    bias,
    regime: stringOrNull(verdict.regime),
    buyerDominancePct: number(dominance.buyer_dominance_percentage),
    writerDominancePct: number(dominance.writer_dominance_percentage),
    callWritingScore: number(dominance.call_writing_score),
    putBuyingScore: number(dominance.put_buying_score),
    callBuyingScore: number(dominance.call_buying_score),
    putWritingScore: number(dominance.put_writing_score),
    breakdownBelow,
    breakoutAbove,
    callWall: number(record(verdict.call_wall).strike) ?? breakoutAbove,
    putWall: number(record(verdict.put_wall).strike) ?? breakdownBelow,
    positioning,
    focusStrike,
    focusStrikeCePositioning,
    focusStrikePePositioning,
    focusStrikeLabel,
  }
}

function latestCanonicalTimestamp(episode: OracleVobEpisode | null, evidence: Readonly<Record<string, OracleEvidenceObservation>>): string | null {
  const values = [episode?.touchAt, episode?.approachAt, episode?.createdAt,
    ...Object.values(evidence).flatMap((item) => [item.eventTime, item.receiveTime])]
    .filter((item): item is string => typeof item === 'string' && Number.isFinite(Date.parse(item)))
  if (!values.length) return null
  return values.reduce((latest, value) => Date.parse(value) > Date.parse(latest) ? value : latest)
}

function parseContract(value: JsonRecord): OracleContractIdentity {
  const option = stringOrNull(value.option_type)?.toUpperCase()
  return {
    securityId: stringId(value.security_id), tradingSymbol: stringOrNull(value.trading_symbol ?? value.symbol),
    expiry: stringOrNull(value.expiry), strike: number(value.strike),
    optionType: option === 'CE' || option === 'PE' ? option : null,
    lotSize: integer(value.lot_size), source: stringOrNull(value.source ?? value.instrument_source),
  }
}

function levelShell(timeframeValue: VobTimeframe, sourceLineage: readonly VobSource[]): OracleVobLevel {
  return {
    timeframe: timeframeValue, sourceLineage, reportedSource: null, alignment: UNKNOWN,
    zoneTop: null, zoneBottom: null, state: UNKNOWN, touchAt: null, role: UNKNOWN,
    primary: false, episodeId: null,
  }
}

function marketSignature(value: MarketSlice): string {
  return [
    value.symbol,
    value.underlying,
    value.marketStatus,
    value.dataFreshness,
    value.spotChangePct,
    value.futuresPrice,
    value.futuresChangePct,
    value.pcr,
    value.openingPcr,
    value.deltaPcr,
    value.deltaPcrPct,
    value.changePcr,
    value.canonicalAtmStrike,
    value.strikeInterval,
    contractSignature(value.activeCe),
    contractSignature(value.activePe),
    optionSignature(value.currentItmCall),
    optionSignature(value.currentItmPut),
    optionSignature(value.itmCall),
    optionSignature(value.itmPut),
    String(value.buyerIntelligence.source_timestamp ?? value.buyerIntelligence.status ?? ''),
  ].join('|')
}

function reuseMarket(current: MarketSlice, next: MarketSlice): MarketSlice {
  if (marketSignature(current) === marketSignature(next)) return current
  return {
    ...next,
    activeCe: reuseSlice(current.activeCe, next.activeCe),
    activePe: reuseSlice(current.activePe, next.activePe),
    currentItmCall: reuseSlice(current.currentItmCall, next.currentItmCall),
    currentItmPut: reuseSlice(current.currentItmPut, next.currentItmPut),
    itmCall: reuseSlice(current.itmCall, next.itmCall),
    itmPut: reuseSlice(current.itmPut, next.itmPut),
  }
}

function optionSignature(value: OracleOptionDisplay): string {
  return [
    contractSignature(value.contract),
    value.contractStatus,
    value.quoteSecurityId,
    value.vobSecurityId,
    value.premium,
    value.bid,
    value.ask,
    value.quoteTimestamp,
    value.freshness,
    value.quoteSource,
    value.vobTimeframe,
    value.zoneTop,
    value.zoneBottom,
    value.zoneState,
    value.zoneRole,
    value.zoneSource,
    value.zonePrimary,
    value.distancePoints,
    value.distancePct,
    value.insideZone,
    value.nearestZoneBoundary,
    value.relation,
    value.dayPriceChange,
    value.previousClose,
    value.openingPrice,
    value.dayChangePct,
    value.oi,
    value.openingOi,
    value.changeOi,
    value.changeOiPct,
    value.positioning,
    value.derivedPositioning,
    value.positioningFormula,
    value.positioningAgreement,
    JSON.stringify(value.horsepower ?? {}),
  ].join('|')
}

function contractSignature(value: OracleContractIdentity): string {
  return [value.securityId, value.tradingSymbol, value.expiry, value.strike, value.optionType, value.lotSize, value.source].join('|')
}

function reuseSlice<T>(current: T, next: T): T {
  return JSON.stringify(current) === JSON.stringify(next) ? current : next
}

function timeframe(value: unknown): VobTimeframe | null {
  const normalized = String(value ?? '').toUpperCase()
  return normalized === '1M' || normalized === '3M' || normalized === '5M' ? normalized : null
}
function record(value: unknown): JsonRecord { return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {} }
function stringOrNull(value: unknown): string | null { return typeof value === 'string' && value.trim() ? value.trim() : null }
function stringId(value: unknown): string | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'string' && value.trim().length > 0) return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return null
}
function text(value: unknown, fallback = UNKNOWN): string { return stringOrNull(value) ?? fallback }
function number(value: unknown): number | null { return typeof value === 'number' && Number.isFinite(value) ? value : null }
function integer(value: unknown): number | null { const result = number(value); return result === null ? null : Math.trunc(result) }
function timestamp(value: unknown): number { const parsed = typeof value === 'string' ? Date.parse(value) : Number.NaN; return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY }
