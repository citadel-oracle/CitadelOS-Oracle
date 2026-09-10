'use client'

import { Badge, Card, SectionHeader as DesignSectionHeader } from '@/design-system'
import styles from './NiftyVOBPanel.module.css'
import { buildVobAxisGeometry, type VobAxisGeometry } from './vobAxisGeometry'

export interface VOBZoneItem {
  zone_id: string
  symbol: string
  timeframe: string
  side: 'BULLISH' | 'BEARISH'
  role: 'SUPPORT' | 'RESISTANCE'
  zone_low: number
  zone_high: number
  origin_candle_time: string
  confirmation_candle_time: string
  origin_volume_formatted: string
  volume_ratio: number
  displacement_strength: number
  touch_count: number
  first_tested_time: string | null
  last_tested_time: string | null
  distance_points: number
  distance_percent: number
  strength_score: number
  status: 'ACTIVE' | 'TESTED' | 'WEAKENING' | 'BROKEN'
  broken_at: string | null
  calculated_at: string
  source_candle_timestamp: string
  freshness: string
  confluence_info?: {
    is_confluent: boolean
    tier: string
    overlapping_timeframes: string[]
  }
}

export interface ConfluenceItem {
  side: 'BULLISH' | 'BEARISH'
  tier: 'STRONG' | 'VERY STRONG' | 'ULTRA STRONG'
  confluence_score: number
  overlap_low: number
  overlap_high: number
  participating_timeframes: string[]
  distance_points: number
  distance_percent: number
}

export interface VOBTimeframeData {
  timeframe: string
  current_nifty_price: number | null
  nearest_bullish_support: VOBZoneItem | null
  nearest_bearish_resistance: VOBZoneItem | null
  recently_broken: VOBZoneItem[]
  evaluated_through?: string | null
}

export interface NiftyVOBData {
  symbol?: string
  current_nifty_spot?: number | null
  execution_influence?: number
  advisory_only?: boolean
  calculated_at?: string
  nearest_support?: VOBZoneItem | null
  nearest_resistance?: VOBZoneItem | null
  strongest_support?: VOBZoneItem | null
  strongest_resistance?: VOBZoneItem | null
  strongest_confluence?: {
    bullish: ConfluenceItem | null
    bearish: ConfluenceItem | null
  }
  source_1m_sync?: {
    latest_completed_1m?: string | null
    latest_evaluated_1m?: string | null
    latest_persisted_1m?: string | null
    runtime_status?: string | null
    backlog_count?: number | null
    evaluated_at?: string | null
    source?: string | null
  }
  timeframes?: Record<string, VOBTimeframeData>
  status?: string
  reason?: string
}

type TimeframeKey = '1m' | '3m' | '5m' | '15m' | '1h'
type Bias = 'BULLISH' | 'BEARISH' | 'NEUTRAL' | 'UNAVAILABLE'
type StrengthTier = 'ULTRA STRONG' | 'VERY STRONG' | 'STRONG' | 'MODERATE' | 'WEAK'
type AxisEventKind = 'TOUCH' | 'BREAK' | 'RETEST'

interface AxisEvent {
  key: string
  kind: AxisEventKind
  side: 'SUPPORT' | 'RESISTANCE'
  glyph: '●' | '◇' | '↶'
  label: string
  position: number
  lane: number
}

const TIMEFRAMES: TimeframeKey[] = ['1m', '3m', '5m', '15m', '1h']

const formatPrice = (value: number | null | undefined) => value == null
  ? 'Unavailable'
  : value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const formatTimestamp = (value: string | null | undefined) => value
  ? new Date(value).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' }).toUpperCase()
  : 'Unavailable'

const zoneRange = (zone: VOBZoneItem | null | undefined) => zone
  ? `${formatPrice(zone.zone_low)}–${formatPrice(zone.zone_high)}`
  : 'Unavailable'

const timeframeLabel = (timeframe: TimeframeKey) => timeframe === '1h' ? '1H' : timeframe.toUpperCase()

function buildAxisEvents(
  geometry: VobAxisGeometry | null,
  support: VOBZoneItem | null | undefined,
  resistance: VOBZoneItem | null | undefined,
  brokenZones: VOBZoneItem[],
): AxisEvent[] {
  if (!geometry) return []
  const events: AxisEvent[] = []
  const addInteractionEvents = (zone: VOBZoneItem | null | undefined, side: AxisEvent['side']) => {
    if (!zone) return
    const midpoint = (zone.zone_low + zone.zone_high) / 2
    const position = geometry.position(midpoint)
    if (position < 0 || position > 100) return
    if (zone.touch_count > 0 && zone.first_tested_time) {
      events.push({
        key: `${zone.zone_id}-touch`,
        kind: 'TOUCH',
        side,
        glyph: '●',
        label: `${side} touched ${zone.touch_count} time${zone.touch_count === 1 ? '' : 's'} · ${formatTimestamp(zone.last_tested_time ?? zone.first_tested_time)}`,
        position,
        lane: 0,
      })
    }
    if (zone.touch_count > 1 && zone.first_tested_time && zone.last_tested_time && zone.first_tested_time !== zone.last_tested_time) {
      events.push({
        key: `${zone.zone_id}-retest`,
        kind: 'RETEST',
        side,
        glyph: '↶',
        label: `${side} retested · ${formatTimestamp(zone.last_tested_time)}`,
        position,
        lane: 0,
      })
    }
  }
  addInteractionEvents(support, 'SUPPORT')
  addInteractionEvents(resistance, 'RESISTANCE')
  brokenZones.forEach((zone) => {
    if (!zone.broken_at) return
    const position = geometry.position((zone.zone_low + zone.zone_high) / 2)
    if (position < 0 || position > 100) return
    events.push({
      key: `${zone.zone_id}-break`,
      kind: 'BREAK',
      side: zone.role,
      glyph: '◇',
      label: `${zone.role} broken · ${formatTimestamp(zone.broken_at)}`,
      position,
      lane: 0,
    })
  })
  const lanePositions: number[][] = []
  return events.map((event) => {
    let lane = lanePositions.findIndex((positions) => positions.every((position) => Math.abs(position - event.position) >= 12))
    if (lane < 0) {
      lane = lanePositions.length
      lanePositions.push([])
    }
    lanePositions[lane].push(event.position)
    return { ...event, lane }
  })
}

function proximityBias(timeframe: VOBTimeframeData | undefined): Bias {
  if (!timeframe) return 'UNAVAILABLE'
  const support = timeframe.nearest_bullish_support
  const resistance = timeframe.nearest_bearish_resistance
  if (support && !resistance) return 'BULLISH'
  if (resistance && !support) return 'BEARISH'
  if (!support && !resistance) return 'NEUTRAL'
  if (support && resistance) {
    const supportDistance = Math.abs(support.distance_points)
    const resistanceDistance = Math.abs(resistance.distance_points)
    if (supportDistance < resistanceDistance) return 'BULLISH'
    if (resistanceDistance < supportDistance) return 'BEARISH'
  }
  return 'NEUTRAL'
}

function zoneTone(zone: VOBZoneItem | null | undefined) {
  if (!zone) return styles.zoneUnavailable
  const roleTone = zone.role === 'SUPPORT' ? styles.zoneSupport : styles.zoneResistance
  if (zone.status === 'BROKEN') return `${roleTone} ${styles.zoneBroken}`
  if (zone.status === 'WEAKENING') return `${roleTone} ${styles.zoneWeakening}`
  if (zone.status === 'TESTED') return `${roleTone} ${styles.zoneTested}`
  return roleTone
}

function lifecycleTone(status: VOBZoneItem['status'] | 'UNAVAILABLE') {
  if (status === 'ACTIVE') return styles.lifecycleActive
  if (status === 'TESTED') return styles.lifecycleTested
  if (status === 'WEAKENING') return styles.lifecycleWeakening
  if (status === 'BROKEN') return styles.lifecycleBroken
  return styles.lifecycleUnknown
}

function strengthTier(zone: VOBZoneItem | null | undefined): StrengthTier | null {
  const tier = zone?.confluence_info?.tier?.toUpperCase()
  if (tier === 'ULTRA STRONG' || tier === 'VERY STRONG' || tier === 'STRONG' || tier === 'MODERATE' || tier === 'WEAK') return tier
  return null
}

function strengthTone(tier: string | null | undefined) {
  const normalized = tier?.toUpperCase()
  if (normalized === 'ULTRA STRONG' || normalized === 'VERY STRONG') return styles.strengthUltra
  if (normalized === 'STRONG') return styles.strengthStrong
  if (normalized === 'MODERATE') return styles.strengthModerate
  return styles.strengthWeak
}

function statusTone(status: string) {
  const normalized = status.toUpperCase()
  if (normalized === 'LIVE' || normalized === 'ACTIVE') return styles.statusLive
  if (normalized === 'CATCHING_UP' || normalized === 'TESTED' || normalized === 'WEAKENING') return styles.statusWarning
  if (normalized === 'DEGRADED' || normalized === 'BROKEN') return styles.statusDanger
  return styles.statusNeutral
}

export function NiftyVOBPanel({
  data,
  verifiedTime,
}: {
  data?: NiftyVOBData | null
  verifiedTime?: string
}) {
  const timeframes = data?.timeframes ?? {}
  const visibleTimeframes = TIMEFRAMES.filter((timeframe) => {
    const timeframeData = timeframes[timeframe]
    return Boolean(timeframeData?.nearest_bullish_support || timeframeData?.nearest_bearish_resistance)
  })
  const spot = data?.current_nifty_spot ?? null
  const support = data?.strongest_support ?? data?.nearest_support ?? null
  const resistance = data?.strongest_resistance ?? data?.nearest_resistance ?? null
  const sourceSync = data?.source_1m_sync
  const runtimeState = sourceSync?.runtime_status ?? data?.status ?? (data ? 'UNAVAILABLE' : 'UNAVAILABLE')
  const runtimeReason = data?.reason ?? (data ? null : 'VOB_PROJECTION_UNAVAILABLE')
  const biases = TIMEFRAMES.map((timeframe) => proximityBias(timeframes[timeframe]))
  const bullishCount = biases.filter((bias) => bias === 'BULLISH').length
  const bearishCount = biases.filter((bias) => bias === 'BEARISH').length
  const neutralCount = biases.filter((bias) => bias === 'NEUTRAL').length
  const directional = bullishCount === bearishCount ? 'NEUTRAL' : bullishCount > bearishCount ? 'BULLISH' : 'BEARISH'
  const nearestZone = [data?.nearest_support, data?.nearest_resistance]
    .filter((zone): zone is VOBZoneItem => Boolean(zone))
    .sort((left, right) => Math.abs(left.distance_points) - Math.abs(right.distance_points))[0] ?? null
  const confluences = [data?.strongest_confluence?.bullish, data?.strongest_confluence?.bearish]
    .filter((item): item is ConfluenceItem => Boolean(item))
    .sort((left, right) => right.confluence_score - left.confluence_score)
  const strongestConfluence = confluences[0] ?? null
  const strongestConfluenceTimeframes = strongestConfluence?.participating_timeframes.map((item) => item.toUpperCase()).join(' + ') ?? 'Unavailable'
  const evaluatedThrough = TIMEFRAMES.map((timeframe) => timeframe === '1m'
    ? sourceSync?.latest_evaluated_1m
    : timeframes[timeframe]?.evaluated_through).filter(Boolean).sort().at(-1)
  const brokenZones = Array.from(new Map(
    Object.values(timeframes).flatMap((timeframe) => timeframe.recently_broken ?? []).map((zone) => [zone.zone_id, zone]),
  ).values()).filter((zone) => zone.status === 'BROKEN').sort((left, right) => (right.broken_at ?? '').localeCompare(left.broken_at ?? '')).slice(0, 3)
  const axisGeometry = buildVobAxisGeometry(spot, data?.nearest_support, data?.nearest_resistance)
  const axisEvents = buildAxisEvents(axisGeometry, data?.nearest_support, data?.nearest_resistance, brokenZones)

  return (
    <Card as="section" unstyled className={`panel workspace-unified-section ${styles.panel}`} aria-label="NIFTY VOB Structure">
      <DesignSectionHeader
        as="div"
        unstyled
        className="section-heading"
        eyebrowClassName="section-eyebrow"
        eyebrow={<>01B / Trading Workspace<span className={`status-dot ${runtimeState === 'LIVE' ? 'live' : ''}`} title={`VOB runtime: ${runtimeState}`} /></>}
        title="NIFTY VOB Structure"
        asideClassName="section-aside"
        aside={
          <div className={styles.headerAside}>
            <span>Spot <strong>{formatPrice(spot)}</strong></span><i />
            <span>Support <strong className={styles.positive}>{zoneRange(support)}</strong></span><i />
            <span>Resistance <strong className={styles.negative}>{zoneRange(resistance)}</strong></span>
            <Badge unstyled className={statusTone(runtimeState)}>{runtimeState}</Badge>
          </div>
        }
      />

      <div className={styles.contextLine}>
        <span>Advisory only · Execution influence {data?.execution_influence ?? 0}%</span>
        <span>Evaluated through <strong>{formatTimestamp(evaluatedThrough)}</strong></span>
        <span>Calculated <strong>{formatTimestamp(data?.calculated_at)}</strong></span>
        {verifiedTime ? <span>Dashboard verified <strong>{verifiedTime}</strong></span> : null}
      </div>

      <div className={styles.intelligenceStrip} aria-label="VOB intelligence summary">
        <div><span>Dominant bias</span><strong className={directional === 'BULLISH' ? styles.positive : directional === 'BEARISH' ? styles.negative : ''}>{data ? directional : 'Unavailable'}</strong></div>
        <div><span>Bullish TFs</span><strong className={styles.positive}>{bullishCount}</strong></div>
        <div><span>Bearish TFs</span><strong className={styles.negative}>{bearishCount}</strong></div>
        <div><span>Neutral TFs</span><strong>{neutralCount}</strong></div>
        <div><span>Nearest support</span><strong>{data?.nearest_support ? `${Math.abs(data.nearest_support.distance_points).toFixed(1)} pts` : 'Unavailable'}</strong></div>
        <div><span>Nearest resistance</span><strong>{data?.nearest_resistance ? `${Math.abs(data.nearest_resistance.distance_points).toFixed(1)} pts` : 'Unavailable'}</strong></div>
        <div><span>Strongest confluence</span><strong>{strongestConfluenceTimeframes}</strong></div>
        <div><span>Runtime</span><strong className={statusTone(runtimeState)}>{runtimeState}</strong></div>
      </div>

      {runtimeReason ? <div className={styles.runtimeNotice} role="status">{runtimeReason}</div> : null}

      <div className={styles.nearestZoneStrip}>
        <span>Nearest actionable zone</span>
        <strong className={nearestZone?.role === 'SUPPORT' ? styles.positive : nearestZone?.role === 'RESISTANCE' ? styles.negative : ''}>
          {nearestZone ? `${timeframeLabel(nearestZone.timeframe.toLowerCase() as TimeframeKey)} ${nearestZone.role} · ${zoneRange(nearestZone)}` : 'Unavailable'}
        </strong>
        <Badge unstyled className={statusTone(nearestZone?.status ?? 'UNAVAILABLE')}>{nearestZone?.status ?? 'UNAVAILABLE'}</Badge>
        <small>{nearestZone ? `${Math.abs(nearestZone.distance_points).toFixed(1)} points from spot` : 'No current zone distance reported'}</small>
      </div>

      <div className={styles.centralAxis} aria-label="Nearest support spot resistance axis">
        <div className={styles.axisLabels}>
          <div><span>Nearest support</span><strong className={styles.positive}>{zoneRange(data?.nearest_support)}</strong><small>{data?.nearest_support ? `${timeframeLabel(data.nearest_support.timeframe.toLowerCase() as TimeframeKey)} · ${Math.abs(data.nearest_support.distance_points).toFixed(1)} pts` : 'Unavailable'}</small></div>
          <div><span>Live spot</span><strong>{formatPrice(spot)}</strong><small>{runtimeState}</small></div>
          <div><span>Nearest resistance</span><strong className={styles.negative}>{zoneRange(data?.nearest_resistance)}</strong><small>{data?.nearest_resistance ? `${timeframeLabel(data.nearest_resistance.timeframe.toLowerCase() as TimeframeKey)} · ${Math.abs(data.nearest_resistance.distance_points).toFixed(1)} pts` : 'Unavailable'}</small></div>
        </div>
        {axisGeometry ? (
          <div className={styles.axisTrack} aria-label="Live VOB price axis with zone interaction history">
            <i className={styles.axisBaseline} aria-hidden="true" />
            <i
              className={`${styles.axisBand} ${styles.axisSupport}`}
              style={{ left: `${axisGeometry.supportStart}%`, width: `${axisGeometry.supportWidth}%` }}
              title={`Support ${zoneRange(data?.nearest_support)}`}
              aria-hidden="true"
            />
            <i
              className={`${styles.axisBand} ${styles.axisResistance}`}
              style={{ left: `${axisGeometry.resistanceStart}%`, width: `${axisGeometry.resistanceWidth}%` }}
              title={`Resistance ${zoneRange(data?.nearest_resistance)}`}
              aria-hidden="true"
            />
            <b
              className={styles.axisSpot}
              style={{ left: `${axisGeometry.spot}%` }}
              title={`Live spot ${formatPrice(spot)}`}
              aria-label={`Live spot ${formatPrice(spot)}`}
            />
            {axisEvents.map((event) => (
              <span
                className={`${styles.axisEvent} ${event.kind === 'TOUCH' ? styles.axisEventTouch : event.kind === 'BREAK' ? styles.axisEventBreak : styles.axisEventRetest} ${event.side === 'SUPPORT' ? styles.axisEventSupport : styles.axisEventResistance}`}
                data-axis-event={event.kind.toLowerCase()}
                key={event.key}
                style={{ left: `${event.position}%`, top: `${2 + event.lane * 12}px` }}
                title={event.label}
                aria-label={event.label}
                role="img"
              >
                <b aria-hidden="true">{event.glyph}</b><em>{event.kind}</em>
              </span>
            ))}
          </div>
        ) : <div className={styles.axisUnavailable}>Price axis unavailable</div>}
        <div className={styles.axisLegend} aria-label="VOB event legend"><span><b>●</b>Touch</span><span><b>◇</b>Break</span><span><b>↶</b>Retest</span></div>
      </div>

      <div className={styles.timeframeRows} role="table" aria-label="VOB timeframe matrix">
        <div className={styles.timeframeHeader} role="row">
          <span role="columnheader">Timeframe</span><span role="columnheader">Structure axis</span><span role="columnheader">Distance</span><span role="columnheader">Touches / Strength</span><span role="columnheader">Lifecycle</span><span role="columnheader">Evaluated through</span>
        </div>
        {visibleTimeframes.map((timeframe) => {
          const timeframeData = timeframes[timeframe]
          const bias = proximityBias(timeframeData)
          const evaluated = timeframe === '1m' ? sourceSync?.latest_evaluated_1m : timeframeData?.evaluated_through
          const bucketState = timeframe === '1m' ? sourceSync?.runtime_status ?? 'UNAVAILABLE' : evaluated ? 'COMPLETED' : 'UNAVAILABLE'
          const supportZone = timeframeData?.nearest_bullish_support
          const resistanceZone = timeframeData?.nearest_bearish_resistance
          const supportStrength = strengthTier(supportZone)
          const resistanceStrength = strengthTier(resistanceZone)
          const rowAxisGeometry = buildVobAxisGeometry(spot, supportZone, resistanceZone)
          const isNearestActionable = nearestZone?.timeframe.toLowerCase() === timeframe
          const hasUltraConfluence = [supportStrength, resistanceStrength].some((tier) => tier === 'ULTRA STRONG' || tier === 'VERY STRONG')
          const zones = [supportZone, resistanceZone].filter((zone): zone is VOBZoneItem => Boolean(zone))
          const isBroken = zones.length > 0 && zones.every((zone) => zone.status === 'BROKEN')
          return (
            <article
              className={`${styles.timeframeRow} ${bias === 'BULLISH' ? styles.rowBullish : bias === 'BEARISH' ? styles.rowBearish : styles.rowNeutral} ${isNearestActionable ? styles.rowActionable : ''} ${hasUltraConfluence ? styles.rowUltra : ''} ${isBroken ? styles.rowBroken : ''}`}
              data-timeframe={timeframe}
              key={timeframe}
              role="row"
            >
              <div className={styles.rowIdentity} role="cell">
                <strong>{timeframeLabel(timeframe)}</strong>
                <Badge unstyled className={bias === 'BULLISH' ? styles.biasBullish : bias === 'BEARISH' ? styles.biasBearish : styles.biasNeutral}>{bias}</Badge>
              </div>
              <div className={styles.rowStructure} role="cell">
                {rowAxisGeometry ? (
                  <div className={styles.rowTrack} aria-label={`${timeframeLabel(timeframe)} live spot structure axis`}>
                    <i className={styles.rowBaseline} aria-hidden="true" />
                    <i className={`${styles.rowBand} ${styles.rowSupport}`} style={{ left: `${rowAxisGeometry.supportStart}%`, width: `${rowAxisGeometry.supportWidth}%` }} aria-hidden="true" />
                    <i className={`${styles.rowBand} ${styles.rowResistance}`} style={{ left: `${rowAxisGeometry.resistanceStart}%`, width: `${rowAxisGeometry.resistanceWidth}%` }} aria-hidden="true" />
                    <b className={styles.rowSpot} data-row-spot={timeframe} style={{ left: `${rowAxisGeometry.spot}%` }} title={`${timeframeLabel(timeframe)} live spot ${formatPrice(spot)}`} aria-label={`${timeframeLabel(timeframe)} live spot ${formatPrice(spot)}`} />
                  </div>
                ) : <div className={styles.rowAxisUnavailable}>Structure axis unavailable</div>}
                <div className={styles.rowRanges}><strong className={zoneTone(supportZone)}>{zoneRange(supportZone)}</strong><strong className={zoneTone(resistanceZone)}>{zoneRange(resistanceZone)}</strong></div>
              </div>
              <div className={styles.rowDistance} role="cell"><strong className={styles.positive}>SUP {supportZone ? `${Math.abs(supportZone.distance_points).toFixed(1)} pts` : '—'}</strong><strong className={styles.negative}>RES {resistanceZone ? `${Math.abs(resistanceZone.distance_points).toFixed(1)} pts` : '—'}</strong></div>
              <div className={styles.rowActivity} role="cell">
                <div className={`${styles.sideMetric} ${styles.sideSupport}`}>
                  <span><b>SUP</b><em>{supportZone ? supportZone.touch_count : '—'} touches</em></span>
                  <span className={styles.sideStrength}><i aria-hidden="true"><b style={{ width: `${Math.max(0, Math.min(100, supportZone?.strength_score ?? 0))}%` }} /></i><strong>{supportZone ? `${supportZone.strength_score.toFixed(0)}%` : '—'}</strong><Badge unstyled className={strengthTone(supportStrength)} aria-label={`Support strength ${supportStrength ?? 'not reported'}`}>{supportStrength ?? 'Not reported'}</Badge></span>
                </div>
                <div className={`${styles.sideMetric} ${styles.sideResistance}`}>
                  <span><b>RES</b><em>{resistanceZone ? resistanceZone.touch_count : '—'} touches</em></span>
                  <span className={styles.sideStrength}><i aria-hidden="true"><b style={{ width: `${Math.max(0, Math.min(100, resistanceZone?.strength_score ?? 0))}%` }} /></i><strong>{resistanceZone ? `${resistanceZone.strength_score.toFixed(0)}%` : '—'}</strong><Badge unstyled className={strengthTone(resistanceStrength)} aria-label={`Resistance strength ${resistanceStrength ?? 'not reported'}`}>{resistanceStrength ?? 'Not reported'}</Badge></span>
                </div>
              </div>
              <div className={styles.rowLifecycle} role="cell">
                <Badge unstyled className={lifecycleTone(supportZone?.status ?? 'UNAVAILABLE')}>S {supportZone?.status ?? 'N/A'}</Badge>
                <Badge unstyled className={lifecycleTone(resistanceZone?.status ?? 'UNAVAILABLE')}>R {resistanceZone?.status ?? 'N/A'}</Badge>
              </div>
              <div className={styles.rowEvaluated} role="cell"><strong>{formatTimestamp(evaluated)}</strong><Badge unstyled className={statusTone(bucketState)}>{bucketState}</Badge></div>
            </article>
          )
        })}
      </div>

      <div className={styles.confluenceStrip} aria-label="Strongest VOB confluence">
        <div className={styles.stripLabel}><span>Strongest confluence</span><strong>{strongestConfluenceTimeframes}</strong></div>
        {[data?.strongest_confluence?.bullish, data?.strongest_confluence?.bearish].map((item, index) => (
          <div className={`${styles.confluenceItem} ${item?.side === 'BULLISH' ? styles.confluenceBullish : item?.side === 'BEARISH' ? styles.confluenceBearish : ''}`} key={item?.side ?? `unavailable-${index}`}>
            <Badge unstyled className={item?.side === 'BULLISH' ? styles.biasBullish : item?.side === 'BEARISH' ? styles.biasBearish : styles.biasNeutral}>{item?.side ?? 'Unavailable'}</Badge>
            <Badge unstyled className={strengthTone(item?.tier)}>{item?.tier ?? 'Unavailable'}</Badge>
            <strong>{item ? `${formatPrice(item.overlap_low)}–${formatPrice(item.overlap_high)}` : 'Unavailable'}</strong>
            <span className={styles.confluenceMeta}>{item ? `${item.participating_timeframes.map((entry) => entry.toUpperCase()).join(' + ')} · ${item.confluence_score.toFixed(0)}% · ${Math.abs(item.distance_points).toFixed(1)} pts` : 'No confluence reported'}</span>
          </div>
        ))}
      </div>

      <div className={styles.auditTable} role="table" aria-label="Recent broken VOB zones">
        <div className={styles.auditHeader} role="row"><span role="columnheader">Recent broken zones ({brokenZones.length})</span><span role="columnheader">Zone</span><span role="columnheader">Broken at</span></div>
        <div className={styles.auditRows}>
          {brokenZones.length ? brokenZones.map((zone) => (
            <div className={styles.auditRow} data-zone-id={zone.zone_id} key={zone.zone_id} role="row">
              <span role="cell"><Badge unstyled className={styles.statusDanger}>{timeframeLabel(zone.timeframe.toLowerCase() as TimeframeKey)}</Badge><i className={styles.auditBreakMarker} aria-hidden="true">◇</i><em>Break</em><b>{zone.role}</b></span>
              <strong className={zone.side === 'BULLISH' ? styles.positive : styles.negative} role="cell">{zoneRange(zone)}</strong>
              <span role="cell">{formatTimestamp(zone.broken_at)}</span>
            </div>
          )) : <div className={styles.auditEmpty} role="row"><span role="cell">No broken zones reported for the current projection.</span></div>}
        </div>
      </div>
    </Card>
  )
}
