export type OseWheelState =
  | 'ULTRA BEARISH'
  | 'BEARISH'
  | 'NEUTRAL'
  | 'NEUTRAL / MIXED'
  | 'BULLISH'
  | 'ULTRA BULLISH'
  | 'INSUFFICIENT HISTORY'

const wheelPositions: Record<string, number> = {
  'ULTRA BEARISH': 8,
  BEARISH: 29,
  NEUTRAL: 50,
  'NEUTRAL / MIXED': 50,
  BULLISH: 71,
  'ULTRA BULLISH': 92,
}

export const wheelPosition = (state: OseWheelState | string): number => wheelPositions[state] ?? 50

export const wheelArcPath = (start: number, end: number, radius = 82): string => {
  const point = (position: number) => {
    const angle = Math.PI - (Math.PI * position / 100)
    return {
      x: 100 + radius * Math.cos(angle),
      y: 82 - radius * Math.sin(angle),
    }
  }
  const from = point(start)
  const to = point(end)
  return `M${from.x.toFixed(3)} ${from.y.toFixed(3)} A${radius} ${radius} 0 0 1 ${to.x.toFixed(3)} ${to.y.toFixed(3)}`
}

export const wheelNeedle = (state: OseWheelState | string, radius = 68) => {
  const position = wheelPosition(state)
  const angle = Math.PI - (Math.PI * position / 100)
  return {
    position,
    x: 100 + radius * Math.cos(angle),
    y: 82 - radius * Math.sin(angle),
  }
}

export const trendRingNeedle = (state: OseWheelState | string, radius = 34) => {
  const position = wheelPosition(state)
  const angle = (Math.PI * (position * 2.8 - 140)) / 180
  return {
    position,
    x: 70 + radius * Math.sin(angle),
    y: 58 - radius * Math.cos(angle),
  }
}

export const duelMarkerPosition = (ceScore: number, peScore: number): number => {
  const ce = Math.max(0, Number.isFinite(ceScore) ? ceScore : 0)
  const pe = Math.max(0, Number.isFinite(peScore) ? peScore : 0)
  const total = ce + pe
  return total === 0 ? 50 : Math.max(0, Math.min(100, (pe / total) * 100))
}

export const flowMarkerPosition = duelMarkerPosition

const semicirclePoint = (position: number, radius: number, centerX: number, centerY: number) => {
  const angle = Math.PI - (Math.PI * position / 100)
  return { x: centerX + radius * Math.cos(angle), y: centerY - radius * Math.sin(angle) }
}

export const precisionArcPath = (start: number, end: number, radius: number) => {
  const from = semicirclePoint(start, radius, 120, 124)
  const to = semicirclePoint(end, radius, 120, 124)
  return `M${from.x.toFixed(3)} ${from.y.toFixed(3)} A${radius} ${radius} 0 0 1 ${to.x.toFixed(3)} ${to.y.toFixed(3)}`
}

export const precisionWheelNeedle = (state: OseWheelState | string, radius = 82) => {
  const point = semicirclePoint(wheelPosition(state), radius, 120, 124)
  return { position: wheelPosition(state), ...point }
}

export const precisionTick = (position: number, major = false) => {
  const outer = semicirclePoint(position, 107, 120, 124)
  const inner = semicirclePoint(position, major ? 99 : 102, 120, 124)
  return { x1: inner.x, y1: inner.y, x2: outer.x, y2: outer.y }
}

export const trendInstrumentNeedle = (state: OseWheelState | string, radius = 52) => {
  const position = wheelPosition(state)
  const angle = (Math.PI * (position * 2.8 - 140)) / 180
  return {
    position,
    x: 105 + radius * Math.sin(angle),
    y: 82 - radius * Math.cos(angle),
  }
}

export const energyDashOffset = (state: OseWheelState | string): number => 100 - wheelPosition(state)

export interface OseLifecycleFlags {
  supply_break: boolean
  demand_break: boolean
  bullish_retest: boolean
  bearish_retest: boolean
}

export const latestLifecycleSummary = (structure: OseLifecycleFlags): string => {
  if (structure.bullish_retest) return 'Latest: Supply broken → bullish retest held'
  if (structure.bearish_retest) return 'Latest: Demand broken → bearish continuation'
  if (structure.supply_break) return 'Latest: Supply broken'
  if (structure.demand_break) return 'Latest: Demand broken'
  return 'Latest: No confirmed break'
}
