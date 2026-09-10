import type {
  OracleEvidenceObservation,
  OracleOiWindowChange,
  OracleOptionDisplay,
  OracleOptionVobLane,
  OracleTradeRecord,
  OracleVobEpisode,
  VobTimeframe,
} from '@/dashboard/store/oracleStore'

export const UNKNOWN = 'UNKNOWN'

export const UNKNOWN_OBSERVATION: OracleEvidenceObservation = Object.freeze({
  state: UNKNOWN,
  revision: '0',
  eventTime: null,
  receiveTime: null,
  persistence: null,
  persistenceState: UNKNOWN,
  quality: UNKNOWN,
  known: false,
})

export type PnlTone = 'positive' | 'negative' | 'neutral'
export type AuraTone = 'watching' | 'building' | 'ready' | 'positive' | 'negative' | 'neutral' | 'target' | 'failed'

export function pnlTone(value: number | null | undefined): PnlTone {
  if (value === null || value === undefined || value === 0) return 'neutral'
  return value > 0 ? 'positive' : 'negative'
}

export function truthTone(value: string | null | undefined): 'fresh' | 'bad' | 'neutral' {
  if (!value) return 'neutral'
  const upper = value.toUpperCase()
  if (upper.includes('FRESH') || upper.includes('OPEN') || upper.includes('AVAILABLE')) return 'fresh'
  if (upper.includes('STALE') || upper.includes('FAILED') || upper.includes('BROKEN')) return 'bad'
  return 'neutral'
}

export function proximityLabel(option: OracleOptionDisplay): string {
  if (option.relation === 'TOUCHING') return 'TOUCHING VOB'
  if (option.insideZone === true) return 'INSIDE VOB'
  if (option.distancePoints === null) return 'UNKNOWN'
  const points = option.distancePoints.toFixed(2)
  if (option.relation === 'ABOVE') return `${points} pts ABOVE VOB`
  if (option.relation === 'BELOW') return `${points} pts BELOW VOB`
  return `${points} pts AWAY`
}

/**
 * A display-only translation of canonical state. It never manufactures a BUY:
 * BUY READY/IN TRADE/exit labels require the exact-contract Track-A trade record.
 */
export function setupProgressLabel(option: OracleOptionDisplay, trade: OracleTradeRecord | null = null): string {
  if (trade?.status === 'CLOSED') {
    const reason = trade.exitReason?.toUpperCase() ?? ''
    if (reason.includes('TARGET')) return 'TARGET HIT'
    if (reason.includes('STOP') || reason.includes('SL') || reason.includes('INVALID')) return 'SL HIT'
    return 'EXITED'
  }
  if (trade?.status === 'ACTIVE') return 'IN TRADE'
  if (option.vobSecurityId === null || option.zoneBottom === null || option.zoneTop === null) return 'NO ACTIVE VOB'
  if (option.insideZone === true || option.relation === 'TOUCHING') return 'AT ENTRY VOB'
  if (option.zoneState === 'TESTED') return 'RETESTING'
  if (option.zoneState === 'ACTIVE') return option.distancePoints === null ? 'WAITING' : 'APPROACHING ENTRY'
  return 'WAITING'
}

export function setupLaneLabel(lane: OracleOptionVobLane): string {
  if (lane.zoneBottom === null || lane.zoneTop === null) return 'WAITING'
  if (lane.state === 'TESTED') return 'RETESTING'
  if (lane.state === 'ACTIVE') return 'APPROACHING'
  return lane.state === UNKNOWN ? 'WAITING' : lane.state
}

export function formatZoneEvidence(option: OracleOptionDisplay): string {
  const details = [
    option.vobTimeframe ? `${option.vobTimeframe} VOB ${formatRange(option.zoneBottom, option.zoneTop)}` : 'NO ACTIVE VOB',
    option.zoneVolume ? `VOL ${option.zoneVolume}` : null,
    option.zonePercent === null || option.zonePercent === undefined ? null : `${formatNumber(option.zonePercent)}%`,
  ].filter(Boolean)
  return details.join(' · ')
}

export function formatSetupDistance(option: OracleOptionDisplay): string {
  if (option.distancePoints === null || option.distancePoints === undefined) return 'DIST —'
  return `DIST ${formatNumber(option.distancePoints)} pts`
}

export function magnetGeometry(option: OracleOptionDisplay): { pricePct: number; zoneStartPct: number; zoneEndPct: number } | null {
  const { premium, zoneBottom, zoneTop } = option
  if (premium === null || zoneBottom === null || zoneTop === null) return null
  const low = Math.min(zoneBottom, zoneTop)
  const high = Math.max(zoneBottom, zoneTop)
  const span = Math.max(high - low, Math.abs(premium - (low + high) / 2), 1)
  const domainLow = Math.min(low, premium) - span * 0.35
  const domainHigh = Math.max(high, premium) + span * 0.35
  const toPct = (value: number) => Math.max(4, Math.min(96, ((value - domainLow) / (domainHigh - domainLow)) * 100))
  return { pricePct: toPct(premium), zoneStartPct: toPct(low), zoneEndPct: toPct(high) }
}

export function observation(
  evidence: Readonly<Record<string, OracleEvidenceObservation>> | undefined,
  name: string
): OracleEvidenceObservation {
  if (!evidence) return UNKNOWN_OBSERVATION
  return evidence[name] ?? UNKNOWN_OBSERVATION
}

export function actionLabel(state: string, direction: string, vobState: string): string {
  if (vobState === 'BROKEN') return 'VOB BROKEN'
  if (state === 'REVERSAL_READY') return 'REVERSAL READY'
  if (state === 'REVERSAL_BUILDING') return 'REVERSAL BUILDING'
  if (state === 'REVERSAL_FAILED') return 'REVERSAL FAILED'
  if (state === 'WATCHING') return direction === 'CALL' ? 'WATCH CALL TURN' : direction === 'PUT' ? 'WATCH PUT TURN' : 'WATCH'
  return state === 'UNAVAILABLE' || state === UNKNOWN ? 'DATA WAIT' : friendlyState(state)
}

export function heroCopy(state: string, direction: string): string {
  if (state === 'REVERSAL_READY') return `${direction} reversal evidence is ready. Pullback Master remains the entry authority.`
  if (state === 'REVERSAL_BUILDING') return `${direction} control rotation is developing across parallel evidence.`
  if (state === 'REVERSAL_FAILED') return 'The prospective turn did not hold. No frontend override is applied.'
  if (state === 'WATCHING') return 'The VOB episode is valid. Oracle is watching the turn without forcing a signal.'
  return 'Waiting for a canonical backend VOB reversal episode.'
}

export function friendlyState(value: string | null | undefined): string {
  if (!value) return '—'
  return value.replaceAll('_', ' ')
}

export function friendlyArgus(value: string | null | undefined): string {
  if (!value) return UNKNOWN
  if (value === 'CONFIRMS_TARGET') return 'SUPPORTIVE'
  if (value === 'INCUMBENT_DETERIORATING') return 'IMPROVING'
  if (value === 'ADVERSE') return 'HOSTILE'
  return value === 'UNKNOWN' ? UNKNOWN : friendlyState(value)
}

export function controlLabel(direction: string, state: string): string {
  if (state === 'REVERSAL_READY') return direction === 'PUT' ? 'SELLERS IN CONTROL' : 'BUYERS IN CONTROL'
  if (state === 'REVERSAL_BUILDING') return direction === 'PUT' ? 'SELLERS RETURNING' : 'BUYERS RETURNING'
  if (state === 'REVERSAL_FAILED') return 'CONTROL ROTATION FAILED'
  return 'CONTROL UNKNOWN'
}

export function contractLabel(strike: number | null, side: string | null): string {
  return strike === null || side === null ? UNKNOWN : `${formatNumber(strike)} ${side}`
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `₹${formatNumber(value)}`
}

export function formatR(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}R`
}

export function formatRange(low: number | null | undefined, high: number | null | undefined): string {
  if (low === null || low === undefined || high === null || high === undefined) return 'NOT REPORTED'
  return `${formatNumber(low)}–${formatNumber(high)}`
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleTimeString('en-IN', { hour12: false, timeZone: 'Asia/Kolkata' })
}

export function buildStory(
  timeframeValue: VobTimeframe | null,
  touchAt: string | null,
  direction: string,
  evidence: Readonly<Record<string, OracleEvidenceObservation>> | undefined
): string[] {
  const result: string[] = []
  if (timeframeValue && touchAt) result.push(`${timeframeValue} VOB TOUCHED`)
  const failed = observation(evidence, 'failed_aggression')
  if (failed.known && failed.state === 'PRESENT') result.push(direction === 'PUT' ? 'BUYING NOT WORKING' : 'SELLING NOT WORKING')
  const opposing = observation(evidence, 'opposing_option_failure')
  if (opposing.known && opposing.state === 'FAILING') result.push(direction === 'PUT' ? 'CE LOSING POWER' : 'PE LOSING POWER')
  const target = observation(evidence, 'target_option_wakeup')
  if (target.known && target.state === 'WAKEUP') result.push(direction === 'PUT' ? 'PE WAKING UP' : 'CE WAKING UP')
  const argus = observation(evidence, 'argus_confirmation')
  if (argus.known && argus.state === 'CONFIRMS_TARGET') result.push('ARGUS CONFIRMED')
  return result.slice(0, 5).length ? result.slice(0, 5) : ['WAITING FOR CANONICAL EVIDENCE']
}

export function evidenceStory(
  direction: string,
  evidence: Readonly<Record<string, OracleEvidenceObservation>> | undefined
) {
  const failed = observation(evidence, 'failed_aggression')
  const opposing = observation(evidence, 'opposing_option_failure')
  const target = observation(evidence, 'target_option_wakeup')
  const futures = observation(evidence, 'futures_response')
  return [
    {
      label: 'FAILED AGGRESSION',
      value: failed.known ? failed.state === 'PRESENT' ? (direction === 'PUT' ? 'BUYING NOT WORKING' : 'SELLING NOT WORKING') : failed.state : UNKNOWN,
      known: failed.known,
      quality: failed.quality,
    },
    {
      label: 'OPPOSING OPTION',
      value: opposing.known ? opposing.state === 'FAILING' ? (direction === 'PUT' ? 'CE LOSING POWER' : 'PE LOSING POWER') : opposing.state : UNKNOWN,
      known: opposing.known,
      quality: opposing.quality,
    },
    {
      label: 'TARGET OPTION',
      value: target.known ? target.state === 'WAKEUP' ? (direction === 'PUT' ? 'PE WAKING UP' : 'CE WAKING UP') : target.state : UNKNOWN,
      known: target.known,
      quality: target.quality,
    },
    {
      label: 'FUTURES RESPONSE',
      value: futures.known ? futures.state : UNKNOWN,
      known: futures.known,
      quality: futures.quality,
    },
  ]
}

export function lifecycleSteps(
  episode: OracleVobEpisode | null,
  reversalState: string,
  historical = false
) {
  return [
    { label: 'VOB READY', state: episode ? 'complete' : 'pending', time: episode?.createdAt ?? null },
    { label: 'APPROACHING', state: episode?.approachAt ? 'complete' : 'pending', time: episode?.approachAt ?? null },
    { label: 'TOUCHED', state: episode?.touchAt ? 'complete' : 'pending', time: episode?.touchAt ?? null },
    { label: 'WATCHING TURN', state: reversalState === 'WATCHING' ? 'active' : ['REVERSAL_BUILDING', 'REVERSAL_READY'].includes(reversalState) ? 'complete' : 'pending', time: null },
    { label: 'REVERSAL BUILDING', state: reversalState === 'REVERSAL_BUILDING' ? 'active' : reversalState === 'REVERSAL_READY' ? 'complete' : 'pending', time: null },
    { label: 'REVERSAL READY', state: reversalState === 'REVERSAL_READY' ? 'active' : reversalState === 'REVERSAL_FAILED' ? 'failed' : 'pending', time: null },
    { label: historical ? 'TRADE ACTIVE' : 'TRADE LIVE', state: 'pending', time: null },
    { label: 'EXIT', state: episode?.vobState === 'BROKEN' ? 'failed' : 'pending', time: null },
  ]
}

export function formatDisplayTradeId(tradeId: string, timeframe?: string | null): string {
  if (!tradeId) return 'T-VOB-001'
  const tf = (timeframe || '5M').toUpperCase()
  let hash = 0
  for (let i = 0; i < tradeId.length; i++) {
    hash = ((hash << 5) - hash + tradeId.charCodeAt(i)) | 0
  }
  const seq = (Math.abs(hash) % 999) + 1
  const padded = String(seq).padStart(3, '0')
  return `T-${tf}-${padded}`
}

export interface PhotonicArgusVobViewModel {
  bias: 'CALL' | 'PUT' | 'BALANCED' | 'UNKNOWN'
  positioning:
    | 'CALL LONG BUILD'
    | 'CALL SHORT COVER'
    | 'PUT LONG BUILD'
    | 'PUT SHORT COVER'
    | 'CALL WRITE BUILD'
    | 'PUT WRITE BUILD'
    | 'MIXED'
    | 'UNKNOWN'
  buyPct: number | null
  writePct: number | null
  callWritingPct?: number | null
  putWritingPct?: number | null
  callBuyingPct?: number | null
  putBuyingPct?: number | null
  flowShift:
    | 'SELLERS → BUYERS'
    | 'BUYERS → SELLERS'
    | 'FAILED AGGRESSION'
    | 'OPTION ROTATION'
    | 'FUTURES RESPONSE'
    | 'ARGUS CONFIRMED'
    | 'UNKNOWN'
  focusStrike: number | null
  focusStrikeLabel: string
  focusStrikeCePositioning: string | null
  focusStrikePePositioning: string | null
  nifty: number | null
  bearishVob: number | null
  bullishVob: number | null
  location: 'BELOW' | 'IN_ZONE' | 'ABOVE' | 'UNKNOWN'
  timeframe: VobTimeframe | 'UNKNOWN'
  role: string | null
}

export function buildArgusVobViewModel({
  argus,
  market,
  reversal,
  vob,
}: {
  argus?: import('@/dashboard/store/oracleStore').ArgusSlice | null
  market?: import('@/dashboard/store/oracleStore').MarketSlice | null
  reversal?: import('@/dashboard/store/oracleStore').ReversalSlice | null
  vob?: import('@/dashboard/store/oracleStore').VobSlice | null
}): PhotonicArgusVobViewModel {
  // 1. Bias
  const biasRaw = argus?.bias ?? reversal?.direction ?? UNKNOWN
  const bias: PhotonicArgusVobViewModel['bias'] =
    biasRaw === 'CALL' ? 'CALL' : biasRaw === 'PUT' ? 'PUT' : biasRaw === 'BALANCED' ? 'BALANCED' : 'UNKNOWN'

  // 2. Positioning
  let positioning: PhotonicArgusVobViewModel['positioning'] = 'UNKNOWN'
  const canonicalPositioning = argus?.positioning
  if (canonicalPositioning && [
    'CALL LONG BUILD', 'CALL SHORT COVER', 'PUT LONG BUILD', 'PUT SHORT COVER',
    'CALL WRITE BUILD', 'PUT WRITE BUILD', 'MIXED',
  ].includes(canonicalPositioning)) {
    positioning = canonicalPositioning as PhotonicArgusVobViewModel['positioning']
  } else if (argus?.buyerDominancePct !== null && argus?.buyerDominancePct !== undefined) {
    positioning = 'MIXED'
  }

  // 3. Buy & Write percentages + 4-way decomposition
  const buyPct = argus?.buyerDominancePct ?? null
  const writePct = argus?.writerDominancePct ?? null
  const callWritingPct = (argus as any)?.callWritingScore ?? (argus as any)?.call_writing_score ?? null
  const putWritingPct = (argus as any)?.putWritingScore ?? (argus as any)?.put_writing_score ?? null
  const callBuyingPct = (argus as any)?.callBuyingScore ?? (argus as any)?.call_buying_score ?? null
  const putBuyingPct = (argus as any)?.putBuyingScore ?? (argus as any)?.put_buying_score ?? null

  // 4. Flow Shift (Dominant reversal / flow state)
  let flowShift: PhotonicArgusVobViewModel['flowShift'] = 'UNKNOWN'
  const failed = reversal?.evidence?.failed_aggression
  const opposing = reversal?.evidence?.opposing_option_failure
  const futures = reversal?.evidence?.futures_response
  const argusEv = reversal?.evidence?.argus_confirmation
  const revState = reversal?.state

  if (revState === 'REVERSAL_READY') {
    flowShift = bias === 'PUT' ? 'BUYERS → SELLERS' : 'SELLERS → BUYERS'
  } else if (failed?.known && failed.state === 'PRESENT') {
    flowShift = 'FAILED AGGRESSION'
  } else if (opposing?.known && opposing.state === 'FAILING') {
    flowShift = 'OPTION ROTATION'
  } else if (futures?.known && (futures.state === 'CLEAN_BULL' || futures.state === 'CLEAN_BEAR')) {
    flowShift = 'FUTURES RESPONSE'
  } else if (argusEv?.known && argusEv.state === 'CONFIRMS_TARGET') {
    flowShift = 'ARGUS CONFIRMED'
  }

  // 5. Strike Spine & Focus Strike Positioning
  const focusStrike = argus?.focusStrike ?? null
  const focusStrikeLabel = argus?.focusStrikeLabel ?? (focusStrike !== null ? 'FOCUS STRIKE' : 'STRIKE UNKNOWN')
  const focusStrikeCePositioning = argus?.focusStrikeCePositioning ?? null
  const focusStrikePePositioning = argus?.focusStrikePePositioning ?? null

  // 6. Nifty & VOB boundaries (Canonical VOB Engine Support & Resistance, fallback to ARGUS walls)
  const nifty = market?.underlying ?? null
  const supportVob = vob?.underlyingSupport ?? argus?.breakdownBelow ?? argus?.putWall ?? null
  const resistanceVob = vob?.underlyingResistance ?? argus?.breakoutAbove ?? argus?.callWall ?? null

  const bullishVob = supportVob
  const bearishVob = resistanceVob

  // 7. Location
  let location: PhotonicArgusVobViewModel['location'] = 'UNKNOWN'
  if (nifty !== null) {
    const supportZone = vob?.underlyingSupportZone
    const resistanceZone = vob?.underlyingResistanceZone
    if (supportZone && supportZone.zoneLow !== null && supportZone.zoneHigh !== null) {
      if (nifty >= supportZone.zoneLow && nifty <= supportZone.zoneHigh) {
        location = 'IN_ZONE'
      } else if (nifty < supportZone.zoneLow) {
        location = 'BELOW'
      } else if (resistanceZone && resistanceZone.zoneHigh !== null && nifty > resistanceZone.zoneHigh) {
        location = 'ABOVE'
      } else {
        location = 'IN_ZONE'
      }
    } else if (bearishVob !== null && bullishVob !== null) {
      const lower = Math.min(bearishVob, bullishVob)
      const upper = Math.max(bearishVob, bullishVob)
      if (nifty < lower) location = 'BELOW'
      else if (nifty > upper) location = 'ABOVE'
      else location = 'IN_ZONE'
    }
  }

  // 8. Timeframe & Role
  const episode = vob?.episode
  const timeframe = episode?.timeframe ?? 'UNKNOWN'
  const role = episode?.primaryRole ?? null

  return {
    bias,
    positioning,
    buyPct,
    writePct,
    callWritingPct,
    putWritingPct,
    callBuyingPct,
    putBuyingPct,
    flowShift,
    focusStrike,
    focusStrikeLabel,
    focusStrikeCePositioning,
    focusStrikePePositioning,
    nifty,
    bearishVob,
    bullishVob,
    location,
    timeframe,
    role,
  }
}

export function formatLacOi(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const inLacs = value / 100000
  return `${inLacs.toFixed(1)}L`
}

export function formatChangeOi(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const inLacs = value / 100000
  const sign = inLacs >= 0 ? '+' : ''
  return `${sign}${inLacs.toFixed(1)}L`
}

export function formatBuildup(positioning: string | null | undefined, side: 'CE' | 'PE'): string {
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

export function formatOiWindowLabel(_label: string, change: OracleOiWindowChange | null | undefined): {
  oiText: string
  priceText: string
  structureText: string
  oiPositive: boolean
} | null {
  if (!change) return null
  if (change.oiDelta === null) {
    if (change.reason) {
      return {
        oiText: change.reason.toUpperCase(),
        priceText: '',
        structureText: change.status || 'WARMING',
        oiPositive: true,
      }
    }
    return null
  }
  const oiLacs = change.oiDelta / 100000
  const sign = oiLacs >= 0 ? '+' : ''
  const pctStr = change.oiPct !== null ? ` (${change.oiPct >= 0 ? '+' : ''}${change.oiPct.toFixed(1)}%)` : ''
  const oiText = `${sign}${oiLacs.toFixed(2)}L${pctStr}`
  const priceSign = (change.priceDelta ?? 0) >= 0 ? '+' : '-'
  const absPrice = change.priceDelta !== null ? Math.abs(change.priceDelta).toFixed(2) : null
  const priceText = absPrice !== null ? `PRICE ${priceSign}₹${absPrice}` : 'PRICE —'
  const structureText = change.structure ?? '—'
  return { oiText, priceText, structureText, oiPositive: (change.oiDelta ?? 0) >= 0 }
}
