export function safeArgusSnapshot(data: any) {
  if (!data || typeof data !== 'object' || !data.data || typeof data.data !== 'object') {
    return { isValid: false, snapshot: null }
  }
  const snapshot = data.data
  if (!snapshot.underlying || !snapshot.verdict || !snapshot.dominance) {
    return { isValid: false, snapshot: null }
  }
  return { isValid: true, snapshot }
}

export function safeArgusStatus(data: any, error: string | null): 'Stale' | 'Closed' | 'Cached' | 'Live' {
  if (error || !data || typeof data !== 'object' || !data.data || typeof data.data !== 'object' || !data.data.underlying) {
    return 'Stale'
  }
  if (data.freshness === 'stale') return 'Stale'
  const marketState = data.data.underlying.market_state
  if (marketState && ['CLOSED', 'WEEKEND', 'PRE_MARKET'].includes(marketState)) return 'Closed'
  if (data.freshness === 'cached') return 'Cached'
  return 'Live'
}

export function safeBaselineLabel(underlying?: any): string {
  if (!underlying || typeof underlying !== 'object') return 'Unavailable'
  if (underlying.market_state && ['CLOSED', 'WEEKEND', 'PRE_MARKET'].includes(underlying.market_state) && underlying.baseline_timestamp) {
    return 'Market closed — last session snapshot'
  }
  if (!underlying.baseline_timestamp || underlying.baseline_status === 'UNAVAILABLE_OUTSIDE_SESSION') {
    return 'Intraday baseline unavailable'
  }
  const timestamp = new Date(underlying.baseline_timestamp)
  if (Number.isNaN(timestamp.getTime())) return 'Intraday baseline unavailable'
  const time = timestamp.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })
  return time === '09:15' ? 'Intraday baseline: 09:15 IST' : `Intraday baseline since ${time} IST`
}
