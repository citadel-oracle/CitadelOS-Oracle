import type { OracleHorsepowerEvent, OracleOptionDisplay } from '@/dashboard/store/oracleStore'

type JsonRecord = Record<string, unknown>

const asRecord = (value: unknown): JsonRecord => value !== null && typeof value === 'object' && !Array.isArray(value)
  ? value as JsonRecord
  : {}
const asNumber = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null

const distanceToZone = (spot: number | null, low: number, high: number): number | null => {
  if (spot === null) return null
  if (spot < low) return Number((low - spot).toFixed(2))
  if (spot > high) return Number((spot - high).toFixed(2))
  return 0
}

const displayZone = (raw: JsonRecord, spot: number | null): JsonRecord | null => {
  const low = asNumber(raw.zone_low)
  const high = asNumber(raw.zone_high)
  if (low === null || high === null) return null
  const state = String(raw.state ?? raw.event ?? 'ACTIVE').toUpperCase()
  const broken = state === 'SUPPORT_BROKEN' || state === 'RESISTANCE_BROKEN'
    || state === 'SUPPORT_GONE' || state === 'RESISTANCE_OUT'
  return {
    zone_id: raw.zone_id,
    timeframe: String(raw.timeframe ?? '').toLowerCase(),
    role: raw.role ?? raw.zone_role,
    zone_low: Math.min(low, high),
    zone_high: Math.max(low, high),
    status: broken ? 'BROKEN' : 'ACTIVE',
    distance_points: distanceToZone(spot, Math.min(low, high), Math.max(low, high)),
    source_candle_timestamp: raw.resolved_at ?? raw.broken_at ?? raw.confirmed_candle ?? raw.formed_at,
    freshness: 'AVAILABLE',
  }
}

const closestZone = (rows: JsonRecord[], role: 'SUPPORT' | 'RESISTANCE', spot: number | null): JsonRecord | null => {
  const candidates = rows
    .filter((row) => String(row.role ?? row.zone_role).toUpperCase() === role)
    .map((row) => displayZone(row, spot))
    .filter((row): row is JsonRecord => row !== null)
  const active = candidates.filter((row) => row.status !== 'BROKEN')
  const eligible = active.length ? active : candidates
  return eligible.sort((left, right) => (asNumber(left.distance_points) ?? Number.MAX_VALUE) - (asNumber(right.distance_points) ?? Number.MAX_VALUE))[0] ?? null
}

/** Adapts canonical Fast Lane NIFTY Horsepower geometry for the legacy VOB view. */
export function canonicalNiftyVobPresentation(value: unknown, legacyValue?: unknown): JsonRecord {
  const projection = asRecord(value)
  const horsepower = asRecord(projection.nifty_horsepower)
  if (Object.keys(horsepower).length === 0 || horsepower.status === 'UNAVAILABLE') return asRecord(legacyValue)

  const canonicalMarket = asRecord(projection.canonical_market)
  const spot = asNumber(canonicalMarket.reference_price)
  const structureZones = Array.isArray(horsepower.structure_zones)
    ? horsepower.structure_zones.map(asRecord)
    : Array.isArray(horsepower.session_ledger) ? horsepower.session_ledger.map(asRecord) : []
  const events = Array.isArray(horsepower.events) ? horsepower.events.map(asRecord) : []
  const timeframes: JsonRecord = {}

  for (const timeframe of ['1m', '3m', '5m']) {
    const laneZones = structureZones.filter((row) => String(row.timeframe).toLowerCase() === timeframe)
    const laneEvents = [...events].reverse().filter((row) => String(row.timeframe).toLowerCase() === timeframe)
    const support = closestZone(laneZones, 'SUPPORT', spot) ?? closestZone(laneEvents, 'SUPPORT', spot)
    const resistance = closestZone(laneZones, 'RESISTANCE', spot) ?? closestZone(laneEvents, 'RESISTANCE', spot)
    const sourceLane = asRecord(asRecord(horsepower.timeframes)[timeframe])
    timeframes[timeframe] = {
      ...sourceLane,
      current_nifty_price: spot,
      nearest_bullish_support: support,
      nearest_bearish_resistance: resistance,
    }
  }

  const five = asRecord(timeframes['5m'])
  const three = asRecord(timeframes['3m'])
  const one = asRecord(timeframes['1m'])
  const recentEvents = [...events].reverse().slice(0, 8).map((row) => ({
    role: row.zone_role,
    status: row.event,
    broken_at: row.confirmed_candle,
  }))
  return {
    status: 'AVAILABLE',
    market_input_state: 'AVAILABLE',
    symbol: horsepower.instrument ?? 'NIFTY',
    current_nifty_spot: spot,
    nearest_support: five.nearest_bullish_support ?? three.nearest_bullish_support ?? one.nearest_bullish_support,
    nearest_resistance: five.nearest_bearish_resistance ?? three.nearest_bearish_resistance ?? one.nearest_bearish_resistance,
    source_1m_sync: { runtime_status: 'AVAILABLE' },
    timeframes,
    recently_broken: recentEvents,
    horsepower,
  }
}

export type PnlTone = 'positive' | 'negative' | 'neutral'
export type AuraTone = 'watching' | 'building' | 'ready' | 'positive' | 'negative' | 'neutral' | 'target' | 'failed'
export type AlertKind = 'READY' | 'ENTRY' | 'EXIT' | 'TARGET' | 'STOP' | 'BROKEN'
export { formatDisplayTradeId } from './NiftyPhotonicMaster/photonicPresentationHelpers'

export interface SemanticFrame {
  episodeId: string | null
  revision: number
  reversalState: string
  vobState: string
  direction: string
  contract: string
  premium: number | null
  timeframe: string | null
  entryTime: string | null
  exitTime: string | null
  exitReason: string | null
  pnl: number | null
}

export interface SemanticAlert {
  kind: AlertKind
  key: string
  title: string
  detail: string
  reason: string
  tone: PnlTone | 'amber'
}

export interface TrackATradeFrame {
  tradeId: string
  contract: string
  timeframe: string
  entryTime: string | null
  exitTime: string | null
  exitReason: string | null
  pnl: number | null
}

export function pnlTone(value: number | null | undefined): PnlTone {
  if (value === null || value === undefined || value === 0) return 'neutral'
  return value > 0 ? 'positive' : 'negative'
}

export function auraTone(frame: SemanticFrame): AuraTone {
  const reason = frame.exitReason?.toUpperCase() ?? ''
  if (reason.includes('TARGET')) return 'target'
  if (reason.includes('STOP') || reason.includes('INVALID')) return 'failed'
  if (frame.vobState === 'BROKEN' || frame.reversalState === 'REVERSAL_FAILED') return 'failed'
  if (frame.entryTime && !frame.exitTime) {
    const tone = pnlTone(frame.pnl)
    return tone === 'positive' ? 'positive' : tone === 'negative' ? 'negative' : 'neutral'
  }
  if (frame.reversalState === 'REVERSAL_READY') return 'ready'
  if (frame.reversalState === 'REVERSAL_BUILDING') return 'building'
  return 'watching'
}

export function proximityLabel(option: OracleOptionDisplay): string {
  if (option.relation === 'TOUCHING') return 'TOUCHING VOB'
  if (option.insideZone === true) return 'INSIDE VOB'
  if (option.distancePoints === null || option.relation === 'UNKNOWN') return 'UNKNOWN'
  const points = option.distancePoints.toFixed(2)
  if (option.relation === 'ABOVE') return `${points} pts ABOVE VOB`
  if (option.relation === 'BELOW') return `${points} pts BELOW VOB`
  return `${points} pts AWAY`
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

export function semanticAlert(previous: SemanticFrame | null, current: SemanticFrame): SemanticAlert | null {
  if (!current.episodeId) return null
  const base = `${current.episodeId}|${current.revision}`
  const detail = [current.contract, current.premium === null ? null : `₹${current.premium.toFixed(2)}`].filter(Boolean).join(' · ')
  const reason = [current.timeframe ? `${current.timeframe} PRIMARY VOB` : null, current.vobState].filter(Boolean).join(' · ')
  if (previous?.vobState !== current.vobState && current.vobState === 'BROKEN') {
    return { kind: 'BROKEN', key: `${base}|BROKEN`, title: 'VOB BROKEN', detail, reason, tone: 'negative' }
  }
  if (previous?.reversalState !== current.reversalState && current.reversalState === 'REVERSAL_READY') {
    return { kind: 'READY', key: `${base}|READY`, title: `${current.direction} ENTRY READY`, detail, reason: `${reason} · REVERSAL READY`, tone: 'amber' }
  }
  if (!previous?.entryTime && current.entryTime) {
    return { kind: 'ENTRY', key: `${base}|ENTRY`, title: `${current.direction} BUY TRIGGER`, detail, reason, tone: 'positive' }
  }
  if (!previous?.exitTime && current.exitTime) {
    const exitReason = current.exitReason?.toUpperCase() ?? 'EXIT'
    if (exitReason.includes('TARGET')) return { kind: 'TARGET', key: `${base}|TARGET`, title: 'TARGET HIT', detail, reason: exitReason, tone: 'positive' }
    if (exitReason.includes('STOP') || exitReason.includes('INVALID')) return { kind: 'STOP', key: `${base}|STOP`, title: 'STOP / EXIT', detail, reason: exitReason, tone: 'negative' }
    return { kind: 'EXIT', key: `${base}|EXIT`, title: 'EXIT TRIGGER', detail, reason: exitReason, tone: 'negative' }
  }
  return null
}

/** Entry/exit alerts use the canonical Track-A record, not reversal UI state. */
export function trackATradeAlert(previous: TrackATradeFrame | null, current: TrackATradeFrame): SemanticAlert | null {
  const detail = [current.contract, current.timeframe].filter(Boolean).join(' · ')
  if (!previous?.entryTime && current.entryTime) {
    return {
      kind: 'ENTRY', key: `${current.tradeId}|ENTRY|${current.entryTime}`,
      title: 'BUY TRIGGER', detail, reason: 'TRACK-A VOB_ONLY ENTRY', tone: 'positive',
    }
  }
  if (!previous?.exitTime && current.exitTime) {
    const reason = current.exitReason?.toUpperCase() || 'STRATEGY CLOSED'
    if (reason.includes('TARGET')) return { kind: 'TARGET', key: `${current.tradeId}|TARGET|${current.exitTime}`, title: 'TARGET HIT', detail, reason, tone: 'positive' }
    if (reason.includes('STOP') || reason.includes('SL') || reason.includes('INVALID')) return { kind: 'STOP', key: `${current.tradeId}|STOP|${current.exitTime}`, title: 'SL HIT', detail, reason, tone: 'negative' }
    return { kind: 'EXIT', key: `${current.tradeId}|EXIT|${current.exitTime}`, title: 'EXIT TRIGGER', detail, reason, tone: 'negative' }
  }
  return null
}

export function horsepowerAlert(event: OracleHorsepowerEvent): SemanticAlert {
  const positive = event.event === 'RESISTANCE_OUT' || event.event === 'SUPPORT_BACK'
  const title = `${event.instrument} ${event.timeframe} · ${event.event.replaceAll('_', ' ')}`
  return {
    kind: positive ? 'READY' : 'BROKEN',
    key: event.eventId,
    title,
    detail: `ZONE ${event.zoneId} · CLOSE ${event.close ?? '—'}`,
    reason: `CONFIRMED CANDLE ${event.confirmedCandle}`,
    tone: positive ? 'positive' : 'negative',
  }
}

export function acceptSemanticEvent(seen: Set<string>, event: SemanticAlert | null): boolean {
  if (!event || seen.has(event.key)) return false
  seen.add(event.key)
  return true
}

export function readBooleanPreference(storage: Pick<Storage, 'getItem'>, key: string, fallback = false): boolean {
  const value = storage.getItem(key)
  return value === null ? fallback : value === 'true'
}

export function writeBooleanPreference(storage: Pick<Storage, 'setItem'>, key: string, value: boolean): void {
  storage.setItem(key, String(value))
}
