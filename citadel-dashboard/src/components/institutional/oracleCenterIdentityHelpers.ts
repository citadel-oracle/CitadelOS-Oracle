export interface ReadableOptionIdentity {
  underlying: string
  strike: number | null
  optionType: 'CALL' | 'PUT' | null
  expiry: string | null
  timeframe: string
  humanTitle: string
  humanSubtitle: string
  rawSymbol: string
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
  source: 'STRUCTURED_CANONICAL' | 'RAW_FALLBACK_PARSER' | 'FALLBACK_UNAVAILABLE'
}

export interface CenterDisplayIdentity {
  title: string
  subtitle: string
  technicalFooter: string
  rawSymbol: string
  normalizedSymbol: string
  exchange: string
  timeframe: string
  instrumentType: string
  identityStatus: 'AVAILABLE' | 'UNAVAILABLE'
  chartFreshness: string
  isExactOption: boolean
}

export interface CenterDecisionDisplay {
  actionLabel: string
  side: string
  decisionStatus: string
  freshness: string
}

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

export function formatIndianNumber(val: number | null | undefined): string {
  if (val === null || val === undefined || !Number.isFinite(val)) return 'NOT REPORTED'
  return val.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

export function formatExpiryDate(dateStr: string | null | undefined): string | null {
  if (!dateStr || typeof dateStr !== 'string') return null
  const clean = dateStr.trim()
  // Check ISO format YYYY-MM-DD
  const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(clean)
  if (isoMatch) {
    const year = isoMatch[1]
    const monthIdx = parseInt(isoMatch[2], 10) - 1
    const day = parseInt(isoMatch[3], 10)
    if (monthIdx >= 0 && monthIdx < 12) {
      return `${day} ${MONTHS[monthIdx]} ${year}`
    }
  }
  return clean
}

export function formatReadableOptionIdentity({
  underlying,
  strike,
  optionSide,
  expiry,
  rawSymbol,
  timeframe = '5m',
}: {
  underlying?: string | null
  strike?: number | null
  optionSide?: string | null
  expiry?: string | null
  rawSymbol?: string | null
  timeframe?: string
}): ReadableOptionIdentity {
  const cleanRaw = (rawSymbol || '').replace(/^NSE:|^BSE:/i, '').trim()

  // Priority 1: Structured canonical metadata
  if (underlying && strike !== undefined && strike !== null && optionSide) {
    const sideUpper = String(optionSide).toUpperCase()
    const side = (sideUpper === 'CE' || sideUpper === 'CALL') ? 'CALL' : (sideUpper === 'PE' || sideUpper === 'PUT') ? 'PUT' : null
    if (side) {
      const strikeFormatted = formatIndianNumber(strike)
      const humanTitle = `${underlying.toUpperCase()} ${strikeFormatted} ${side}`
      const formattedExpiry = formatExpiryDate(expiry)
      const humanSubtitle = formattedExpiry ? `${formattedExpiry} · ${timeframe}` : `${timeframe}`
      return {
        underlying: underlying.toUpperCase(),
        strike,
        optionType: side,
        expiry: formattedExpiry,
        timeframe,
        humanTitle,
        humanSubtitle,
        rawSymbol: cleanRaw || `${underlying}${strike}${side}`,
        confidence: 'HIGH',
        source: 'STRUCTURED_CANONICAL',
      }
    }
  }

  // Priority 3: Verified Raw Symbol Fallback Parser
  // Matches NSE index option symbols like NIFTY260811C24500, BANKNIFTY260811P55000, SENSEX260811P79500
  const parseMatch = /^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)$/i.exec(cleanRaw)
  if (parseMatch) {
    const parsedUnderlying = parseMatch[1].toUpperCase()
    const yy = parseMatch[2]
    const mmIdx = parseInt(parseMatch[3], 10) - 1
    const dd = parseInt(parseMatch[4], 10)
    const sideChar = parseMatch[5].toUpperCase()
    const parsedStrike = parseInt(parseMatch[6], 10)

    if (mmIdx >= 0 && mmIdx < 12) {
      const parsedSide = sideChar === 'C' ? 'CALL' : 'PUT'
      const formattedExpiry = `${dd} ${MONTHS[mmIdx]} 20${yy}`
      const strikeFormatted = formatIndianNumber(parsedStrike)
      const humanTitle = `${parsedUnderlying} ${strikeFormatted} ${parsedSide}`
      const humanSubtitle = `${formattedExpiry} · ${timeframe}`

      return {
        underlying: parsedUnderlying,
        strike: parsedStrike,
        optionType: parsedSide,
        expiry: formattedExpiry,
        timeframe,
        humanTitle,
        humanSubtitle,
        rawSymbol: cleanRaw,
        confidence: 'HIGH',
        source: 'RAW_FALLBACK_PARSER',
      }
    }
  }

  // Priority Fallback: Malformed or unparseable symbol
  return {
    underlying: underlying ? underlying.toUpperCase() : 'NOT REPORTED',
    strike: strike ?? null,
    optionType: null,
    expiry: null,
    timeframe,
    humanTitle: cleanRaw || 'NOT REPORTED',
    humanSubtitle: `OPTION DETAILS UNAVAILABLE · ${timeframe}`,
    rawSymbol: cleanRaw || 'NOT REPORTED',
    confidence: 'LOW',
    source: 'FALLBACK_UNAVAILABLE',
  }
}

export function deriveCenterDisplayIdentity({
  chartState,
  exactOption,
  fallbackSymbol,
}: {
  chartState?: any
  exactOption?: any
  fallbackSymbol?: string
}): CenterDisplayIdentity {
  const symbolObj = chartState?.symbol
  const rawSymbol = symbolObj?.raw_symbol ?? chartState?.raw_symbol ?? ''
  const normalizedSymbol = symbolObj?.normalized_symbol ?? chartState?.normalized_symbol ?? fallbackSymbol ?? ''
  const exchange = symbolObj?.exchange ?? chartState?.exchange ?? 'NSE'
  const timeframe = chartState?.timeframe ?? '5m'
  const chartFreshness = chartState?.freshness ?? 'NOT REPORTED'

  const isChartAvailable = chartState?.availability === 'AVAILABLE' || Boolean(normalizedSymbol && normalizedSymbol !== 'NOT REPORTED')

  // Check structured option metadata on chartState.option OR exactOption.exact_contract
  const csOption = chartState?.option
  const exactContract = exactOption?.exact_contract

  const isExactOption = symbolObj?.route === 'EXACT_OPTION'
    || Boolean(csOption?.strike !== undefined)
    || Boolean(exactContract?.strike !== undefined)

  let title = 'NOT REPORTED'
  let subtitle = `${timeframe}`
  let technicalFooter = normalizedSymbol || 'NOT REPORTED'
  let instrumentType = 'UNDERLYING INDEX'

  if (isExactOption) {
    instrumentType = 'EXACT OPTION'
    // Prefer chartState.option for current epoch to prevent stale exactOption leakage
    const optStruct = (csOption?.strike !== undefined ? csOption : exactContract) || {}
    const formattedOpt = formatReadableOptionIdentity({
      underlying: optStruct.underlying ?? 'NIFTY',
      strike: optStruct.strike,
      optionSide: optStruct.option_side,
      expiry: optStruct.expiry,
      rawSymbol: normalizedSymbol || optStruct.trading_symbol || rawSymbol,
      timeframe,
    })

    title = formattedOpt.humanTitle
    subtitle = formattedOpt.humanSubtitle
    technicalFooter = formattedOpt.rawSymbol
  } else if (normalizedSymbol && normalizedSymbol !== 'NOT REPORTED') {
    title = normalizedSymbol
    technicalFooter = normalizedSymbol
    const route = symbolObj?.route ?? ''
    if (route === 'UNDERLYING_STOCK') {
      instrumentType = 'UNDERLYING STOCK'
      subtitle = `UNDERLYING STOCK · ${timeframe}`
    } else if (route === 'EXACT_OPTION') {
      instrumentType = 'EXACT OPTION'
      subtitle = `EXACT OPTION · ${timeframe}`
    } else {
      instrumentType = 'UNDERLYING INDEX'
      subtitle = `UNDERLYING INDEX · ${timeframe}`
    }
  }

  const identityStatus: 'AVAILABLE' | 'UNAVAILABLE' = (isChartAvailable && title !== 'NOT REPORTED') ? 'AVAILABLE' : 'UNAVAILABLE'

  return {
    title,
    subtitle,
    technicalFooter,
    rawSymbol,
    normalizedSymbol: normalizedSymbol || 'NOT REPORTED',
    exchange,
    timeframe,
    instrumentType,
    identityStatus,
    chartFreshness,
    isExactOption,
  }
}

export function deriveCenterDecisionDisplay({
  decision,
  runtimeGate,
  oracleMeta,
  marketState,
}: {
  decision?: any
  runtimeGate?: any
  oracleMeta?: any
  marketState?: string
}): CenterDecisionDisplay {
  const rawAction = decision?.action ?? runtimeGate?.decision
  const freshness = decision?.freshness ?? 'NOT REPORTED'

  let actionLabel = 'SCANNING PERSONAL STRATEGIES'
  const sig = decision?.personal_strategy_signal ?? decision?.eye_oracle_projection?.data?.personal_strategy_signal

  if (sig) {
    const st = String(sig.state).toUpperCase()
    const label = sig.short_label || 'PERSONAL STRATEGY'
    if (st === 'DETECTED') {
      actionLabel = `${label} DETECTED`
    } else if (st === 'CONFIRMED') {
      actionLabel = `${label} CONFIRMED`
    } else if (st === 'BLOCKED') {
      actionLabel = `${label} CONFIRMED • RISK BLOCKED`
    } else if (st === 'PARTIAL') {
      actionLabel = `${label} • ${sig.match_count}/${sig.match_total} CONDITIONS`
    } else if (st === 'MISSING_RULE') {
      actionLabel = `${label} • RULE INCOMPLETE`
    } else if (st === 'DEPLOYED') {
      actionLabel = `${label} DEPLOYED • ${sig.direction}`
    } else if (st === 'MANAGING') {
      actionLabel = `${label} • GUARDIAN MANAGING`
    } else if (st === 'EXITED') {
      actionLabel = `${label} EXITED`
    } else if (st === 'SCANNING') {
      actionLabel = `SCANNING PERSONAL STRATEGIES`
    } else {
      actionLabel = `${label} • ${st}`
    }
  } else if (marketState === 'POST_MARKET') {
    actionLabel = 'POST MARKET'
  } else if (rawAction) {
    const norm = String(rawAction).toUpperCase().replaceAll('_', ' ')
    if (norm === 'BUY') {
      actionLabel = 'BUY TRIGGER CONFIRMED'
    } else if (norm === 'WAIT') {
      actionLabel = 'WAIT FOR CONFIRMATION'
    } else if (norm === 'NO TRADE') {
      actionLabel = 'NO TRADE'
    } else if (norm === 'MANAGE') {
      actionLabel = 'MANAGE ACTIVE POSITION'
    } else if (norm === 'EXIT') {
      actionLabel = 'EXIT STRUCTURE FAILED'
    } else if (norm === 'UNAVAILABLE') {
      actionLabel = 'SCANNING PERSONAL STRATEGIES'
    } else {
      actionLabel = norm
    }
  }


  const marketDirection = decision?.market_thesis?.direction
  let side = 'NO CLEAN EDGE'
  if (marketDirection) {
    const normDir = String(marketDirection).toUpperCase()
    if (['BULLISH', 'CALL', 'CE'].includes(normDir)) {
      side = 'CALL SIDE'
    } else if (['BEARISH', 'PUT', 'PE'].includes(normDir)) {
      side = 'PUT SIDE'
    } else if (['RANGING', 'SIDEWAYS', 'MIXED', 'NEUTRAL'].includes(normDir)) {
      side = 'SIDEWAYS / MIXED'
    }
  }

  const decisionStatus = decision?.availability ?? (rawAction ? 'EVALUATED' : 'UNAVAILABLE')

  return {
    actionLabel,
    side,
    decisionStatus,
    freshness,
  }
}
