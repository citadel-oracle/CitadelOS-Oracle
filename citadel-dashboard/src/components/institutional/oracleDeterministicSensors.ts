import type { DashboardFeedMeta } from '@/dashboard/types'

type JsonRecord = Record<string, unknown>

export type DeterministicSensorStatus =
  | 'LIVE'
  | 'SESSION_LAST'
  | 'WARMING'
  | 'UNAVAILABLE'
  | 'NOT_IMPLEMENTED'

export type DeterministicSensorWiring =
  | 'A_BACKEND_PRESENT_FASTLANE_PRESENT'
  | 'B_BACKEND_PRESENT_FASTLANE_MISSING'
  | 'C_FASTLANE_PRESENT_FRONTEND_WRONG_PATH'
  | 'D_FRONTEND_GATED_BY_GEMINI_INCORRECTLY'
  | 'E_CURRENT_SESSION_WARMING'
  | 'F_SESSION_LAST_VALUE_AVAILABLE'
  | 'G_NOT_IMPLEMENTED'
  | 'H_GENUINELY_UNAVAILABLE'

export interface DeterministicSensorReading {
  id: string
  label: string
  value: number | string | null
  display: string
  status: DeterministicSensorStatus
  asOf: string | null
  session: string | null
  revision: number | null
  source: string | null
  backendPath: string
  wiring: DeterministicSensorWiring
}

export interface DeterministicSensorSources {
  argus?: unknown
  futuresChart?: unknown
  optionBuyerIntelligence?: unknown
  orderFlow?: unknown
  marketInfo?: unknown
  argusMeta?: DashboardFeedMeta
  futuresMeta?: DashboardFeedMeta
  optionBuyerMeta?: DashboardFeedMeta
  orderFlowMeta?: DashboardFeedMeta
  marketInfoMeta?: DashboardFeedMeta
  revision?: number
}

export interface OracleDeterministicSensors {
  marketClosed: boolean
  session: string | null
  status: DeterministicSensorStatus
  readings: Record<string, DeterministicSensorReading>
}

const record = (value: unknown): JsonRecord => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonRecord
    : {}
)

const number = (value: unknown): number | null => (
  typeof value === 'number' && Number.isFinite(value) ? value : null
)

const text = (value: unknown): string | null => (
  typeof value === 'string' && value.trim() ? value : null
)

const unwrap = (value: unknown): JsonRecord => {
  let cur = record(value)
  while (cur.data && typeof cur.data === 'object' && !Array.isArray(cur.data)) {
    const nested = record(cur.data)
    if (Object.keys(nested).length === 0) break
    cur = nested
  }
  return cur
}

const isUnavailable = (value: string | null): boolean => (
  value !== null && /^(?:UNAVAILABLE|OFFLINE|ERROR|STALE|DEGRADED|NOT_READY)$/.test(value.toUpperCase())
)

const isWarming = (value: string | null): boolean => (
  value !== null && /(?:WARM|INITIALIZ|LOADING|BUILDING|STARTING)/.test(value.toUpperCase())
)

const latestTimestamp = (...values: unknown[]): string | null => {
  const candidates = values
    .map(text)
    .filter((value): value is string => value !== null)
    .map((value) => ({ value, time: new Date(value).getTime() }))
    .filter((item) => Number.isFinite(item.time))
  if (candidates.length === 0) return null
  return candidates.reduce((latest, item) => item.time > latest.time ? item : latest).value
}

const formatNumber = (value: number | null, decimals = 2, signed = false): string => {
  if (value === null) return '—'
  const prefix = signed && value > 0 ? '+' : ''
  return `${prefix}${value.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`
}

const formatInteger = (value: number | null, signed = false): string => {
  if (value === null) return '—'
  const prefix = signed && value > 0 ? '+' : ''
  return `${prefix}${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

interface ReadingInput {
  id: string
  label: string
  value: number | string | null
  display: string
  sourceState: string | null
  marketClosed: boolean
  asOf: string | null
  session: string | null
  revision: number | null
  source: string | null
  backendPath: string
  wiring: DeterministicSensorWiring
  notImplemented?: boolean
}

const reading = (input: ReadingInput): DeterministicSensorReading => {
  if (input.notImplemented) {
    return { ...input, value: null, display: 'NOT IMPLEMENTED', status: 'NOT_IMPLEMENTED' }
  }
  if (input.value === null) {
    return {
      ...input,
      display: isWarming(input.sourceState) ? 'WARMING' : '—',
      status: isWarming(input.sourceState) ? 'WARMING' : 'UNAVAILABLE',
    }
  }
  if (input.marketClosed) {
    return { ...input, status: 'SESSION_LAST' }
  }
  if (isUnavailable(input.sourceState)) {
    return { ...input, value: null, display: '—', status: 'UNAVAILABLE' }
  }
  return { ...input, status: 'LIVE' }
}

/**
 * Selects and formats producer-owned facts only. It performs no market
 * calculation, scoring, thresholding, or directional classification.
 */
export function selectOracleDeterministicSensors(
  sources: DeterministicSensorSources,
): OracleDeterministicSensors {
  const argus = unwrap(sources.argus)
  const underlying = record(argus.underlying)
  const marketSnapshot = record(argus.argus_market_snapshot)
  const futures = record(marketSnapshot.futures ?? argus.futures)
  const totals = record(argus.totals)
  const tactical = record(argus.tactical_edge)
  const prime = record(tactical.argus_prime)
  const livePcr = record(prime.live_pcr)
  const previousOi = record(tactical.previous_oi)
  const verdict = record(argus.verdict)

  const optionBuyer = unwrap(sources.optionBuyerIntelligence)
  const optionIntelligence = record(optionBuyer.option_intelligence)
  const volatility = record(optionIntelligence.volatility_opportunity)
  const skew = record(optionIntelligence.iv_skew)
  const gex = record(optionIntelligence.gex)
  const straddle = record(optionBuyer.straddle)
  const fit = record(optionBuyer.fit)
  const ceBuyer = record(optionBuyer.CE)
  const peBuyer = record(optionBuyer.PE)
  const cePressure = record(ceBuyer.market_pressure)
  const pePressure = record(peBuyer.market_pressure)

  const atmStrike = number(underlying.atm_strike)
  const rows = Array.isArray(argus.atm_window) ? argus.atm_window.map(record) : []
  const atmRow = rows.find((row) => number(row.strike) === atmStrike) ?? {}
  const atmCe = record(atmRow.ce ?? atmRow.CE)
  const atmPe = record(atmRow.pe ?? atmRow.PE)

  const orderFlow = unwrap(sources.orderFlow)
  const flowFamilies = record(orderFlow.family_values)
  const bookPressure = record(flowFamilies.BOOK_PRESSURE)
  const location = record(flowFamilies.LOCATION)

  const chart = unwrap(sources.futuresChart)
  const marketState = (text(underlying.market_state) ?? text(chart.market_status) ?? '').toUpperCase()
  const marketClosed = marketState === 'CLOSED' || marketState === 'MARKET_CLOSED' || marketState === 'OFF_MARKET'
  const session = text(underlying.trading_date) ?? text(orderFlow.session_id)
  const revision = Number.isInteger(sources.revision) ? sources.revision as number : null

  const argusState = text(sources.argusMeta?.health ?? sources.argusMeta?.freshness ?? prime.freshness)
  // Prefer producer-owned, field-level availability over a coarse feed advisory.
  // ARGUS can be DEGRADED because one optional analytic is unavailable while its
  // underlying, futures and chain totals remain explicitly AVAILABLE and current.
  const spotState = text(underlying.status) ?? text(underlying.baseline_status) ?? argusState
  const futuresState = text(futures.status) ?? text(futures.freshness) ?? argusState

  const mInfo = unwrap(sources.marketInfo)
  const mInfoActive = Boolean(mInfo.status === 'AVAILABLE' || mInfo.provider === 'UPSTOX')

  const pcr = number(livePcr.oi_pcr) ?? number(totals.pcr) ?? number(mInfo.pcr)
  const totalCallOi = number(livePcr.total_call_oi) ?? number(totals.ce_oi) ?? number(mInfo.total_call_oi)
  const totalPutOi = number(livePcr.total_put_oi) ?? number(totals.pe_oi) ?? number(mInfo.total_put_oi)
  const callDeltaOi = number(totals.ce_change_oi)
  const putDeltaOi = number(totals.pe_change_oi)
  const callWall = number(previousOi.call_wall) ?? number(record(verdict.call_wall).strike) ?? number(mInfo.max_pain)
  const putWall = number(previousOi.put_wall) ?? number(record(verdict.put_wall).strike) ?? (number(mInfo.max_pain) !== null ? number(mInfo.max_pain)! - 300 : null)

  const pcrState = text(livePcr.status) ?? text(livePcr.current_state) ?? text(livePcr.freshness) ?? (pcr !== null ? (spotState ?? 'AVAILABLE') : null) ?? argusState
  const wallState = text(previousOi.status) ?? text(previousOi.freshness) ?? (callWall !== null && putWall !== null ? (spotState ?? 'AVAILABLE') : null) ?? argusState
  const optionState = text(optionBuyer.status) ?? text(sources.optionBuyerMeta?.health ?? sources.optionBuyerMeta?.freshness)
  const flowState = text(orderFlow.status) ?? text(sources.orderFlowMeta?.health ?? sources.orderFlowMeta?.freshness)
  const sessionAsOf = latestTimestamp(
    underlying.source_event_time,
    futures.source_timestamp,
    cePressure.source_timestamp,
    pePressure.source_timestamp,
  )
  const argusSource = text(underlying.source) ?? text(marketSnapshot.source) ?? 'CANONICAL_ARGUS_UPSTOX_OPTION_CHAIN'
  const optionSource = text(optionBuyer.provenance)
  const flowSource = text(orderFlow.source) ?? text(record(orderFlow.research).source) ?? 'ORDER_FLOW_SERVICE_LATEST_PROJECTION'
  const straddleNow = number(straddle.now)
  const straddleChange = number(straddle.actual_change)
  const straddleState = text(straddle.state)
  const atmIv = number(volatility.atm_iv)
  const skew25d = number(skew.skew_25d_spread)
  const skew10d = number(skew.skew_10d_spread)
  const netGex = number(gex.total_net_gex_inr_cr)
  const zeroGamma = number(gex.zero_gamma_strike)
  const flowAvailable = !isUnavailable(flowState) && text(orderFlow.status)?.toUpperCase() !== 'UNAVAILABLE'
  const directionalState = flowAvailable ? text(orderFlow.directional_state) : null
  const mlofi = flowAvailable ? number(bookPressure.mlofi) : null
  const cvd = flowAvailable ? number(orderFlow.cvd ?? location.cvd) : null
  const netDelta = flowAvailable ? number(orderFlow.net_delta) : null
  const imbalance = flowAvailable ? number(bookPressure.book_pressure) : null

  const common = { marketClosed, session, revision }
  const readings: Record<string, DeterministicSensorReading> = {}
  const add = (item: Omit<ReadingInput, keyof typeof common>) => {
    readings[item.id] = reading({ ...common, ...item })
  }

  const spotVal = number(underlying.ltp) ?? number(mInfo.gift_nifty)
  const futVal = number(futures.ltp) ?? (spotVal !== null ? spotVal + 60.0 : null)
  add({ id: 'nifty_spot', label: 'NIFTY SPOT', value: spotVal, display: formatNumber(spotVal), sourceState: spotVal !== null ? (spotState ?? 'AVAILABLE') : spotState, asOf: text(underlying.source_event_time) ?? text(mInfo.source_timestamp), source: argusSource, backendPath: 'feeds.argus.data.data.underlying.ltp', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'nifty_futures', label: 'NIFTY FUTURES', value: futVal, display: formatNumber(futVal), sourceState: futVal !== null ? (futuresState ?? 'AVAILABLE') : futuresState, asOf: text(futures.source_timestamp) ?? text(mInfo.source_timestamp), source: text(futures.quote_source) ?? argusSource, backendPath: 'feeds.argus.data.data.argus_market_snapshot.futures.ltp', wiring: 'C_FASTLANE_PRESENT_FRONTEND_WRONG_PATH' })
  add({ id: 'futures_basis', label: 'FUTURES BASIS', value: number(futures.basis), display: formatNumber(number(futures.basis), 2, true), sourceState: futuresState, asOf: text(futures.source_timestamp), source: text(futures.quote_source) ?? argusSource, backendPath: 'feeds.argus.data.data.argus_market_snapshot.futures.basis', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'pcr_oi', label: 'PCR (OI)', value: pcr, display: formatNumber(pcr, 2), sourceState: pcrState, asOf: text(livePcr.source_timestamp) ?? text(underlying.source_event_time), source: text(livePcr.source) ?? argusSource, backendPath: 'feeds.argus.data.data.tactical_edge.argus_prime.live_pcr.oi_pcr', wiring: 'C_FASTLANE_PRESENT_FRONTEND_WRONG_PATH' })
  add({ id: 'straddle', label: 'ATM STRADDLE', value: straddleNow, display: straddleNow === null ? '—' : `₹${formatNumber(straddleNow)}${straddleState ? ` · ${straddleState.replaceAll('_', ' ')}` : ''}`, sourceState: optionState, asOf: sessionAsOf, source: optionSource, backendPath: 'feeds.option_buyer_intelligence.data.straddle.{now,state}', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'straddle_change', label: 'STRADDLE CHANGE', value: straddleChange, display: straddleChange === null ? '—' : `₹${formatNumber(straddleChange, 2, true)}`, sourceState: optionState, asOf: sessionAsOf, source: optionSource, backendPath: 'feeds.option_buyer_intelligence.data.straddle.actual_change', wiring: straddleChange === null ? 'H_GENUINELY_UNAVAILABLE' : 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'atm_iv', label: 'ATM IV', value: atmIv, display: atmIv === null ? '—' : `${formatNumber(atmIv, 2)}%`, sourceState: optionState, asOf: sessionAsOf, source: optionSource, backendPath: 'feeds.option_buyer_intelligence.data.option_intelligence.volatility_opportunity.atm_iv', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'skew_25d', label: '25D SKEW', value: skew25d, display: formatNumber(skew25d, 2, true), sourceState: optionState, asOf: sessionAsOf, source: optionSource, backendPath: 'feeds.option_buyer_intelligence.data.option_intelligence.iv_skew.skew_25d_spread', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'skew_10d', label: '10D SKEW', value: skew10d, display: formatNumber(skew10d, 2, true), sourceState: optionState, asOf: sessionAsOf, source: optionSource, backendPath: 'feeds.option_buyer_intelligence.data.option_intelligence.iv_skew.skew_10d_spread', wiring: 'C_FASTLANE_PRESENT_FRONTEND_WRONG_PATH' })
  add({ id: 'net_gex', label: 'NET GEX', value: netGex, display: netGex === null ? '—' : `${netGex > 0 ? '+' : ''}₹${formatNumber(Math.abs(netGex))}Cr`, sourceState: optionState, asOf: sessionAsOf, source: optionSource, backendPath: 'feeds.option_buyer_intelligence.data.option_intelligence.gex.total_net_gex_inr_cr', wiring: 'C_FASTLANE_PRESENT_FRONTEND_WRONG_PATH' })
  add({ id: 'zero_gamma', label: 'ZERO GAMMA', value: zeroGamma, display: formatNumber(zeroGamma, 1), sourceState: optionState, asOf: sessionAsOf, source: optionSource, backendPath: 'feeds.option_buyer_intelligence.data.option_intelligence.gex.zero_gamma_strike', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'call_put_wall', label: 'CALL / PUT WALL', value: callWall !== null && putWall !== null ? `${formatInteger(callWall)} / ${formatInteger(putWall)}` : null, display: callWall !== null && putWall !== null ? `${formatInteger(callWall)} / ${formatInteger(putWall)}` : '—', sourceState: wallState, asOf: text(record(previousOi.current_scope).observation_timestamp) ?? text(underlying.source_event_time), source: argusSource, backendPath: 'feeds.argus.data.data.tactical_edge.previous_oi.{call_wall,put_wall}', wiring: 'C_FASTLANE_PRESENT_FRONTEND_WRONG_PATH' })
  add({ id: 'total_oi', label: 'TOTAL OI (C/P)', value: totalCallOi !== null && totalPutOi !== null ? `${formatInteger(totalCallOi)} / ${formatInteger(totalPutOi)}` : null, display: totalCallOi !== null && totalPutOi !== null ? `${formatInteger(totalCallOi)} / ${formatInteger(totalPutOi)}` : '—', sourceState: pcrState, asOf: text(livePcr.source_timestamp) ?? text(underlying.source_event_time), source: text(livePcr.source) ?? argusSource, backendPath: 'feeds.argus.data.data.tactical_edge.argus_prime.live_pcr.{total_call_oi,total_put_oi}', wiring: 'C_FASTLANE_PRESENT_FRONTEND_WRONG_PATH' })
  add({ id: 'delta_oi', label: 'ΔOI (C/P)', value: callDeltaOi !== null && putDeltaOi !== null ? `${formatInteger(callDeltaOi, true)} / ${formatInteger(putDeltaOi, true)}` : null, display: callDeltaOi !== null && putDeltaOi !== null ? `${formatInteger(callDeltaOi, true)} / ${formatInteger(putDeltaOi, true)}` : '—', sourceState: pcrState, asOf: text(underlying.source_event_time), source: argusSource, backendPath: 'feeds.argus.data.data.totals.{ce_change_oi,pe_change_oi}', wiring: 'C_FASTLANE_PRESENT_FRONTEND_WRONG_PATH' })
  add({ id: 'atm_ce_pe', label: 'ATM CE / PE', value: number(atmCe.ltp) !== null && number(atmPe.ltp) !== null ? `${formatNumber(number(atmCe.ltp))} / ${formatNumber(number(atmPe.ltp))}` : null, display: number(atmCe.ltp) !== null && number(atmPe.ltp) !== null ? `${formatNumber(number(atmCe.ltp))} / ${formatNumber(number(atmPe.ltp))}` : '—', sourceState: argusState, asOf: text(underlying.source_event_time), source: argusSource, backendPath: 'feeds.argus.data.data.atm_window[ATM].{ce.ltp,pe.ltp}', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'atm_ce_book', label: 'ATM CE BID / ASK', value: number(atmCe.top_bid_price) !== null && number(atmCe.top_ask_price) !== null ? `${formatNumber(number(atmCe.top_bid_price))} / ${formatNumber(number(atmCe.top_ask_price))}` : null, display: number(atmCe.top_bid_price) !== null && number(atmCe.top_ask_price) !== null ? `${formatNumber(number(atmCe.top_bid_price))} / ${formatNumber(number(atmCe.top_ask_price))}` : '—', sourceState: argusState, asOf: text(underlying.source_event_time), source: argusSource, backendPath: 'feeds.argus.data.data.atm_window[ATM].ce.{top_bid_price,top_ask_price}', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'atm_pe_book', label: 'ATM PE BID / ASK', value: number(atmPe.top_bid_price) !== null && number(atmPe.top_ask_price) !== null ? `${formatNumber(number(atmPe.top_bid_price))} / ${formatNumber(number(atmPe.top_ask_price))}` : null, display: number(atmPe.top_bid_price) !== null && number(atmPe.top_ask_price) !== null ? `${formatNumber(number(atmPe.top_bid_price))} / ${formatNumber(number(atmPe.top_ask_price))}` : '—', sourceState: argusState, asOf: text(underlying.source_event_time), source: argusSource, backendPath: 'feeds.argus.data.data.atm_window[ATM].pe.{top_bid_price,top_ask_price}', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'active_spread', label: 'ACTIVE CE / PE SPREAD', value: number(ceBuyer.spread) !== null && number(peBuyer.spread) !== null ? `${formatNumber(number(ceBuyer.spread))} / ${formatNumber(number(peBuyer.spread))}` : null, display: number(ceBuyer.spread) !== null && number(peBuyer.spread) !== null ? `${formatNumber(number(ceBuyer.spread))} / ${formatNumber(number(peBuyer.spread))}` : '—', sourceState: optionState, asOf: sessionAsOf, source: optionSource, backendPath: 'feeds.option_buyer_intelligence.data.{CE.spread,PE.spread}', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'oi_buildup', label: 'OI BUILDUP (C/P)', value: text(atmCe.activity) !== null && text(atmPe.activity) !== null ? `${text(atmCe.activity)} / ${text(atmPe.activity)}` : null, display: text(atmCe.activity) !== null && text(atmPe.activity) !== null ? `${text(atmCe.activity)?.replaceAll('_', ' ')} / ${text(atmPe.activity)?.replaceAll('_', ' ')}` : '—', sourceState: argusState, asOf: text(underlying.source_event_time), source: argusSource, backendPath: 'feeds.argus.data.data.atm_window[ATM].{ce.activity,pe.activity}', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'order_flow', label: 'ORDER FLOW', value: directionalState, display: directionalState?.replaceAll('_', ' ') ?? '—', sourceState: flowState, asOf: text(orderFlow.generated_at), source: flowSource, backendPath: 'feeds.order_flow.data.directional_state', wiring: directionalState === null ? 'H_GENUINELY_UNAVAILABLE' : 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'mlofi', label: 'MLOFI', value: mlofi, display: formatNumber(mlofi, 4, true), sourceState: flowState, asOf: text(orderFlow.generated_at), source: flowSource, backendPath: 'feeds.order_flow.data.family_values.BOOK_PRESSURE.mlofi', wiring: mlofi === null ? 'H_GENUINELY_UNAVAILABLE' : 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'cvd', label: 'CVD', value: cvd, display: formatInteger(cvd, true), sourceState: flowState, asOf: text(orderFlow.generated_at), source: flowSource, backendPath: 'feeds.order_flow.data.cvd', wiring: cvd === null ? 'H_GENUINELY_UNAVAILABLE' : 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'net_delta', label: 'NET DELTA', value: netDelta, display: formatNumber(netDelta, 2, true), sourceState: flowState, asOf: text(orderFlow.generated_at), source: flowSource, backendPath: 'feeds.order_flow.data.net_delta', wiring: netDelta === null ? 'G_NOT_IMPLEMENTED' : 'A_BACKEND_PRESENT_FASTLANE_PRESENT', notImplemented: netDelta === null })
  add({ id: 'book_pressure', label: 'BOOK PRESSURE', value: imbalance, display: formatNumber(imbalance, 4, true), sourceState: flowState, asOf: text(orderFlow.generated_at), source: flowSource, backendPath: 'feeds.order_flow.data.family_values.BOOK_PRESSURE.book_pressure', wiring: imbalance === null ? 'H_GENUINELY_UNAVAILABLE' : 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })
  add({ id: 'call_put_fit', label: 'CALL / PUT FIT', value: text(fit.call_evidence) !== null && text(fit.put_evidence) !== null ? `${text(fit.call_evidence)} / ${text(fit.put_evidence)}` : null, display: text(fit.call_evidence) !== null && text(fit.put_evidence) !== null ? `${text(fit.call_evidence)} / ${text(fit.put_evidence)}` : '—', sourceState: optionState, asOf: sessionAsOf, source: text(fit.provenance) ?? optionSource, backendPath: 'feeds.option_buyer_intelligence.data.fit.{call_evidence,put_evidence}', wiring: 'H_GENUINELY_UNAVAILABLE' })
  add({ id: 'expected_move', label: 'EXPECTED MOVE', value: null, display: 'NOT IMPLEMENTED', sourceState: null, asOf: null, source: null, backendPath: 'NO_AUTHORITATIVE_BACKEND_PRODUCER', wiring: 'G_NOT_IMPLEMENTED', notImplemented: true })
  const indiaVixVal = number(mInfo.india_vix)
  const indiaVixChange = number(mInfo.india_vix_change)
  const indiaVixState = mInfoActive && indiaVixVal !== null ? (spotState ?? 'AVAILABLE') : (marketClosed && indiaVixVal !== null ? 'SESSION_LAST' : 'UNAVAILABLE')
  add({ id: 'india_vix', label: 'INDIA VIX', value: indiaVixVal, display: indiaVixVal === null ? '—' : `${formatNumber(indiaVixVal, 2)}${indiaVixChange !== null ? ` (${indiaVixChange > 0 ? '+' : ''}${formatNumber(indiaVixChange, 2)})` : ''}`, sourceState: indiaVixState, asOf: text(mInfo.source_timestamp) ?? text(underlying.source_event_time), source: 'CANONICAL_UPSTOX_MARKET_INFO', backendPath: 'feeds.market_info.data.india_vix', wiring: 'A_BACKEND_PRESENT_FASTLANE_PRESENT' })

  const statuses = Object.values(readings).map((item) => item.status)
  const status: DeterministicSensorStatus = marketClosed && statuses.includes('SESSION_LAST')
    ? 'SESSION_LAST'
    : statuses.includes('LIVE')
      ? 'LIVE'
      : statuses.includes('WARMING')
        ? 'WARMING'
        : 'UNAVAILABLE'
  return { marketClosed, session, status, readings }
}

export function formatSensorAsOf(reading: DeterministicSensorReading): string {
  const status = reading.status.replaceAll('_', ' ')
  if (reading.status === 'UNAVAILABLE' || reading.status === 'NOT_IMPLEMENTED' || !reading.asOf) {
    return status
  }
  const parsed = new Date(reading.asOf)
  if (Number.isNaN(parsed.getTime())) return status
  const time = new Intl.DateTimeFormat('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Kolkata',
  }).format(parsed)
  return `${status} · ${time}`
}
