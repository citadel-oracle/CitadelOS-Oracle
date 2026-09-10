type UnknownRecord = Record<string, unknown>

const NOT_REPORTED = 'NOT REPORTED'

const record = (value: unknown): UnknownRecord =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as UnknownRecord
    : {}

const text = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value.trim() : null

const finite = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const identity = (value: unknown): string | null => {
  const valueText = text(value)
  if (valueText) return valueText.toUpperCase()
  const valueNumber = finite(value)
  return valueNumber === null ? null : String(valueNumber)
}

const sameIdentity = (left: unknown, right: unknown): boolean => {
  const normalizedLeft = identity(left)
  const normalizedRight = identity(right)
  return normalizedLeft !== null && normalizedRight !== null && normalizedLeft === normalizedRight
}

export interface ArgusSpineRow {
  label: string
  strike: number | null
  ceLoad: number | null
  peLoad: number | null
  flowState: string
  structuralRole: string
  ceAcceleration: number | null
  peAcceleration: number | null
  ceFlow: string
  peFlow: string
}

export interface ArgusProviderProjection {
  state: string
  verdict: string
  providerLineageAvailable: boolean
  exactContractLineageAvailable: boolean
  underlying: string
  expiry: string
  securityId: string
  sourceTimestamp: string
  sourceEventTime: string
  timestampSemantics: string
  snapshotId: string
  producerRevision: string
  chainTimeframe: 'OPTION_CHAIN'
  callPressure: number | null
  putPressure: number | null
  breadth: string
  persistence: string
  pcr: number | null
  pcrTrend: string
  straddleState: string
  ceBuyWriteSplit: string
  peBuyWriteSplit: string
  bestStackStrike: number | null
  supportStrike: number | null
  resistanceStrike: number | null
  highestLoadStrike: number | null
  highestLoadCe: number | null
  highestLoadPe: number | null
  highestLoadRole: string
  fastestAccelerationStrike: number | null
  fastestAccelerationCe: number | null
  fastestAccelerationPe: number | null
  flowType: string
  gammaStrike: number | null
  wallMagnet: string
  gammaBlast: string
  proposedContract: string
  trigger: string
  invalidation: string
  chaseRisk: string
  canonicalRead: string
  canonicalWhy: string
  compactSpine: ArgusSpineRow[]
  fullSpine: ArgusSpineRow[]
}

export const buildArgusProviderProjection = ({
  envelope,
  tactical,
  exactContract,
  chartOption,
  currentUnderlying,
}: {
  envelope: unknown
  tactical: unknown
  exactContract: unknown
  chartOption: unknown
  currentUnderlying: unknown
}): ArgusProviderProjection => {
  void envelope
  const tacticalRecord = record(tactical)
  const prime = record(tacticalRecord.argus_prime)
  const presentation = record(prime.canonical_presentation)
  const pressure = record(tacticalRecord.pressure)
  const breadth = record(tacticalRecord.breadth)
  const persistence = record(tacticalRecord.persistence)
  const exact = record(exactContract)
  const chart = record(chartOption)
  const actionCard = record(prime.action_card)
  const gammaBlast = record(prime.expiry_gamma_blast)
  const livePcr = record(prime.live_pcr)
  const gammaRegime = record(prime.gamma_regime)

  const state = text(presentation.state)?.toUpperCase() ?? 'UNAVAILABLE'
  const sourceTimestamp = text(presentation.observation_timestamp)
  const sourceEventTime = text(presentation.source_event_time)
  const snapshotId = text(
    presentation.snapshot_id,
  )
  const tacticalSymbol = text(tacticalRecord.symbol)
  const tacticalExpiry = text(tacticalRecord.expiry)
  const activeUnderlying = text(currentUnderlying)
  const chartExpiry = text(chart.expiry)
  const providerLineageAvailable = Boolean(
    tacticalSymbol && tacticalExpiry && sourceTimestamp && snapshotId
      && (!activeUnderlying || tacticalSymbol.toUpperCase() === activeUnderlying.toUpperCase())
      && (!chartExpiry || sameIdentity(tacticalExpiry, chartExpiry)),
  )

  const pressureRows = Array.isArray(pressure.strikes) ? pressure.strikes.map(record) : []
  const exactStrike = finite(exact.strike)
  const exactSide = text(exact.option_side)
  const exactSecurityId = identity(exact.security_id)
  const chartSecurityId = identity(chart.security_id)
  const exactPressureRow = pressureRows.find((row) => finite(row.strike) === exactStrike)
  const exactPressureLeg = exactPressureRow && exactSide ? record(exactPressureRow[exactSide.toUpperCase()]) : {}
  const exactContractLineageAvailable = Boolean(
    providerLineageAvailable
      && exactStrike !== null
      && ['CE', 'PE'].includes(String(exactSide ?? '').toUpperCase())
      && exactSecurityId
      && chartSecurityId
      && exactSecurityId === chartSecurityId
      && sameIdentity(exactPressureLeg.security_id, exactSecurityId)
      && sameIdentity(exact.expiry, tacticalExpiry)
      && sameIdentity(chartExpiry, tacticalExpiry),
  )

  const projectRow = (row: UnknownRecord): ArgusSpineRow => {
    return {
      label: text(row.label) ?? NOT_REPORTED,
      strike: finite(row.strike),
      ceLoad: finite(row.ce_load),
      peLoad: finite(row.pe_load),
      flowState: text(row.flow_state) ?? NOT_REPORTED,
      structuralRole: text(row.structural_role) ?? NOT_REPORTED,
      ceAcceleration: finite(row.ce_acceleration),
      peAcceleration: finite(row.pe_acceleration),
      ceFlow: text(row.ce_flow) ?? NOT_REPORTED,
      peFlow: text(row.pe_flow) ?? NOT_REPORTED,
    }
  }

  const fullSpine = Array.isArray(presentation.full_spine)
    ? presentation.full_spine.map(record).map(projectRow)
    : []
  const compactSpine = Array.isArray(presentation.compact_spine)
    ? presentation.compact_spine.map(record).map(projectRow)
    : []

  const gammaProxy = record(prime.gamma_regime).proxy === true || gammaBlast.gamma_proxy === true
  const wallMagnet = record(presentation.wall_magnet)
  const highestProjected = projectRow(record(presentation.highest_load))
  const fastestProjected = projectRow(record(presentation.fastest_acceleration))

  return {
    state,
    verdict: providerLineageAvailable ? text(presentation.verdict) ?? NOT_REPORTED : NOT_REPORTED,
    providerLineageAvailable,
    exactContractLineageAvailable,
    underlying: providerLineageAvailable ? tacticalSymbol ?? NOT_REPORTED : NOT_REPORTED,
    expiry: providerLineageAvailable ? tacticalExpiry ?? NOT_REPORTED : NOT_REPORTED,
    securityId: exactContractLineageAvailable ? exactSecurityId ?? NOT_REPORTED : NOT_REPORTED,
    sourceTimestamp: providerLineageAvailable ? sourceTimestamp ?? NOT_REPORTED : NOT_REPORTED,
    sourceEventTime: providerLineageAvailable ? sourceEventTime ?? NOT_REPORTED : NOT_REPORTED,
    timestampSemantics: providerLineageAvailable ? text(tacticalRecord.timestamp_semantics) ?? NOT_REPORTED : NOT_REPORTED,
    snapshotId: providerLineageAvailable ? snapshotId ?? NOT_REPORTED : NOT_REPORTED,
    producerRevision: identity(presentation.producer_revision) ?? NOT_REPORTED,
    chainTimeframe: 'OPTION_CHAIN',
    callPressure: providerLineageAvailable ? finite(pressure.call_score ?? pressure.call_normalized) : null,
    putPressure: providerLineageAvailable ? finite(pressure.put_score ?? pressure.put_normalized) : null,
    breadth: providerLineageAvailable
      ? `${finite(breadth.call_confirming_strikes) ?? NOT_REPORTED}C · ${finite(breadth.put_confirming_strikes) ?? NOT_REPORTED}P`
      : NOT_REPORTED,
    persistence: providerLineageAvailable
      ? `${text(persistence.direction) ?? NOT_REPORTED} · ${finite(persistence.consecutive_confirmations) ?? NOT_REPORTED}/${finite(persistence.required_count) ?? NOT_REPORTED}`
      : NOT_REPORTED,
    pcr: providerLineageAvailable ? finite(livePcr.oi_pcr) : null,
    pcrTrend: providerLineageAvailable ? text(livePcr.trend) ?? NOT_REPORTED : NOT_REPORTED,
    straddleState: providerLineageAvailable ? text(prime.straddle_state) ?? NOT_REPORTED : NOT_REPORTED,
    ceBuyWriteSplit: NOT_REPORTED,
    peBuyWriteSplit: NOT_REPORTED,
    bestStackStrike: providerLineageAvailable ? finite(presentation.best_stack_strike) : null,
    supportStrike: providerLineageAvailable ? finite(presentation.support_strike) : null,
    resistanceStrike: providerLineageAvailable ? finite(presentation.resistance_strike) : null,
    highestLoadStrike: providerLineageAvailable ? highestProjected.strike : null,
    highestLoadCe: providerLineageAvailable ? highestProjected.ceLoad : null,
    highestLoadPe: providerLineageAvailable ? highestProjected.peLoad : null,
    highestLoadRole: providerLineageAvailable ? highestProjected.structuralRole : NOT_REPORTED,
    fastestAccelerationStrike: providerLineageAvailable ? fastestProjected.strike : null,
    fastestAccelerationCe: providerLineageAvailable ? fastestProjected.ceAcceleration : null,
    fastestAccelerationPe: providerLineageAvailable ? fastestProjected.peAcceleration : null,
    flowType: providerLineageAvailable ? text(presentation.flow_type) ?? NOT_REPORTED : NOT_REPORTED,
    gammaStrike: providerLineageAvailable ? finite(presentation.gamma_strike ?? gammaRegime.strongest_strike) : null,
    wallMagnet: providerLineageAvailable
      ? `WALL ${finite(wallMagnet.wall) ?? NOT_REPORTED} · MAGNET ${finite(wallMagnet.magnet) ?? NOT_REPORTED}`
      : NOT_REPORTED,
    gammaBlast: providerLineageAvailable
      ? `${text(gammaBlast.state ?? gammaBlast.phase) ?? NOT_REPORTED}${gammaProxy ? ' · PROXY' : ''}`
      : NOT_REPORTED,
    proposedContract: providerLineageAvailable ? text(presentation.proposed_contract) ?? NOT_REPORTED : NOT_REPORTED,
    trigger: providerLineageAvailable ? text(prime.trigger ?? actionCard.trigger) ?? NOT_REPORTED : NOT_REPORTED,
    invalidation: providerLineageAvailable ? text(prime.invalidation_text ?? prime.invalidation ?? actionCard.invalidation) ?? NOT_REPORTED : NOT_REPORTED,
    chaseRisk: providerLineageAvailable ? text(gammaBlast.chase_risk) ?? NOT_REPORTED : NOT_REPORTED,
    canonicalRead: providerLineageAvailable ? text(presentation.canonical_read) ?? NOT_REPORTED : NOT_REPORTED,
    canonicalWhy: providerLineageAvailable ? text(presentation.canonical_why) ?? NOT_REPORTED : NOT_REPORTED,
    compactSpine: providerLineageAvailable ? compactSpine : [],
    fullSpine: providerLineageAvailable ? fullSpine : [],
  }
}
