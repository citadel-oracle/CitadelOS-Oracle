export interface VobAxisZone {
  zone_low: number
  zone_high: number
}

export interface VobAxisGeometry {
  supportStart: number
  supportWidth: number
  spot: number
  resistanceStart: number
  resistanceWidth: number
  position: (value: number) => number
}

const BELOW_SUPPORT_END = 10
const SUPPORT_END = 26
const RESISTANCE_START = 74
const RESISTANCE_END = 90

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value))

const mapSegment = (
  value: number,
  priceStart: number,
  priceEnd: number,
  visualStart: number,
  visualEnd: number,
) => {
  if (priceEnd <= priceStart) return visualStart
  const progress = clamp((value - priceStart) / (priceEnd - priceStart), 0, 1)
  return visualStart + progress * (visualEnd - visualStart)
}

export function buildVobAxisGeometry(
  spot: number | null,
  support: VobAxisZone | null | undefined,
  resistance: VobAxisZone | null | undefined,
): VobAxisGeometry | null {
  if (spot == null || !Number.isFinite(spot) || !support || !resistance) return null
  const supportLow = Math.min(support.zone_low, support.zone_high)
  const supportHigh = Math.max(support.zone_low, support.zone_high)
  const resistanceLow = Math.min(resistance.zone_low, resistance.zone_high)
  const resistanceHigh = Math.max(resistance.zone_low, resistance.zone_high)
  if (![supportLow, supportHigh, resistanceLow, resistanceHigh].every(Number.isFinite) || supportHigh >= resistanceLow) return null

  const structuralSpan = Math.max(
    resistanceLow - supportHigh,
    supportHigh - supportLow,
    resistanceHigh - resistanceLow,
    1,
  )
  const lowerBound = supportLow - structuralSpan
  const upperBound = resistanceHigh + structuralSpan
  const position = (value: number) => {
    if (!Number.isFinite(value)) return 0
    if (value <= supportLow) return mapSegment(value, lowerBound, supportLow, 0, BELOW_SUPPORT_END)
    if (value <= supportHigh) return mapSegment(value, supportLow, supportHigh, BELOW_SUPPORT_END, SUPPORT_END)
    if (value <= resistanceLow) return mapSegment(value, supportHigh, resistanceLow, SUPPORT_END, RESISTANCE_START)
    if (value <= resistanceHigh) return mapSegment(value, resistanceLow, resistanceHigh, RESISTANCE_START, RESISTANCE_END)
    return mapSegment(value, resistanceHigh, upperBound, RESISTANCE_END, 100)
  }

  return {
    supportStart: BELOW_SUPPORT_END,
    supportWidth: SUPPORT_END - BELOW_SUPPORT_END,
    spot: position(spot),
    resistanceStart: RESISTANCE_START,
    resistanceWidth: RESISTANCE_END - RESISTANCE_START,
    position,
  }
}
