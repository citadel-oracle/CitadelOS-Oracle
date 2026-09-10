import type { OracleOptionDisplay } from '@/dashboard/store/oracleStore'

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
