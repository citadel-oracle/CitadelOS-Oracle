'use client'

import {
  Activity,
  Bell,
  BellOff,
  BrainCircuit,
  ChartNoAxesCombined,
  Crosshair,
  FileSearch,
  HeartPulse,
  Orbit,
  RadioTower,
  ShieldCheck,
  Sparkles,
  Waves,
  Volume2,
  X,
} from 'lucide-react'
import {
  memo,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type ComponentType,
  type ReactNode,
} from 'react'
import type {
  DashboardFeedMeta,
  DashboardFeedState,
  OracleAssessmentData,
  OracleLiveWorkspaceProjection,
} from '@/dashboard/types'
import { feedSelectors, useDashboardSelector } from '@/dashboard'
import type {
  OracleMissionRuntime,
  OracleTradePlan,
} from '@/app/oracle/useOracleMissionRuntime'
import { CitadelPrimaryNavigation } from './CitadelPrimaryNavigation'
import { OracleArgusPrime01C } from './OracleArgusPrime01C'
import { FlowPulsePaperLedger, OracleFlowPulse } from './OracleFlowPulse'
import { OracleFuturesVwapChart } from './OracleFuturesVwapChart'
import { GeminiMarketBrainSection } from './GeminiMarketBrainSection'
import { OracleLiveFlow } from './OracleLiveFlow'
import { VobPullbackCommand } from './VobPullbackCommand'
import { NiftyPhotonicMaster, PhotonicOptionBuyerIntelligenceBottom } from './NiftyPhotonicMaster'
import { buildArgusProviderProjection } from './oracleArgusProjection'
import {
  deriveCenterDisplayIdentity,
  deriveCenterDecisionDisplay,
} from './oracleCenterIdentityHelpers'
import { canonicalNiftyVobPresentation } from './vobPresentation'

import styles from '@/app/oracle/oracle.module.css'

type JsonRecord = Record<string, unknown>
type NodeId = 'thesis' | 'argus' | 'vob' | 'ose' | 'risk' | 'guardian'
type EvidenceVote = 'SUPPORTS CALL' | 'SUPPORTS PUT' | 'SUPPORTIVE' | 'NEUTRAL' | 'CONFLICTS' | 'BLOCKS' | 'NOT REPORTED'
type NodeTone = 'call' | 'put' | 'neutral' | 'unavailable' | 'stale' | 'blocked'
type PresentationState = 'CALL' | 'PUT' | 'MIXED' | 'PENDING' | 'HEALTHY' | 'BLOCKED' | 'STANDBY' | 'UNAVAILABLE'
type WorkflowStage = 'IDLE' | 'ANALYSING' | 'EVALUATED' | 'QUALIFIED' | 'PLANNED' | 'SUBMITTING' | 'OPEN' | 'EXITING' | 'CLOSED'
const oracleNodeIds: readonly NodeId[] = ['thesis', 'argus', 'vob', 'ose', 'risk', 'guardian']
const subscribeStaticLocation = () => () => undefined

interface AlertPreferences {
  muted: boolean
  volume: number
  browser: boolean
  criticalOnly: boolean
  marketHoursOnly: boolean
  events: Record<string, boolean>
}

const defaultAlertPreferences: AlertPreferences = {
  muted: true, volume: 0.35, browser: false, criticalOnly: false,
  marketHoursOnly: false, events: {},
}

const oracleAlertEventTypes = [
  'CHART_DETECTED', 'TIMEFRAME_DETECTED', 'BUY_READY', 'WAIT_CONDITION_TRIGGERED',
  'SETUP_INVALIDATED', 'CURRENT_OPTION_REJECTED', 'BETTER_OPTION_FOUND',
  'SPREAD_LIQUIDITY_DETERIORATED', 'AUTHORITY_CONFIRMATION_LOST',
  'CONDITION_WATCHING', 'CONDITION_TRIGGERED', 'CONDITION_REVALIDATING', 'PAPER_ORDER_SUBMITTED',
  'PAPER_ORDER_PARTIALLY_FILLED', 'PAPER_ORDER_FILLED', 'PAPER_ORDER_REJECTED',
  'GUARDIAN_EXIT', 'TRADINGVIEW_DISCONNECTED', 'DISCIPLINE_REVIEW', 'DISCIPLINE_COOLDOWN',
] as const

const ALERT_TOAST_DURATION_MS = 10_000
const ALERT_TOAST_EXIT_MS = 180
type OracleAlertEvent = NonNullable<OracleLiveWorkspaceProjection['alert_event']>

interface Metric {
  label: string
  value: string
}

interface FrontendPerformanceStats {
  latest_ms: number | null
  mean_ms: number | null
  p50_ms: number | null
  p95_ms: number | null
  maximum_ms: number | null
  sample_count: number
  error_count: number
}

const emptyPerformanceStats = (): FrontendPerformanceStats => ({
  latest_ms: null, mean_ms: null, p50_ms: null, p95_ms: null,
  maximum_ms: null, sample_count: 0, error_count: 0,
})

const summarizePerformance = (samples: number[], errorCount = 0): FrontendPerformanceStats => {
  const values = samples.filter(Number.isFinite).map((value) => Math.max(0, value)).sort((a, b) => a - b)
  const count = values.length
  const percentile = (percentage: number) => count ? values[Math.max(0, Math.ceil(count * percentage) - 1)] : null
  const rounded = (value: number | null) => value === null ? null : Math.round(value * 1000) / 1000
  return {
    latest_ms: rounded(samples.at(-1) ?? null),
    mean_ms: rounded(count ? values.reduce((sum, value) => sum + value, 0) / count : null),
    p50_ms: rounded(percentile(0.5)), p95_ms: rounded(percentile(0.95)),
    maximum_ms: rounded(count ? values[count - 1] : null), sample_count: count,
    error_count: errorCount,
  }
}

interface DetailSection {
  title: string
  rows: Metric[]
}

interface OracleNodeView {
  id: NodeId
  title: string
  eyebrow: string
  status: string
  headline: string
  read: string
  resultLabel: string
  metrics: Metric[]
  vote: EvidenceVote
  freshness: string
  tone: NodeTone
  presentationState: PresentationState
  stale: boolean
  icon: ComponentType<{ size?: number; strokeWidth?: number }>
  sections: DetailSection[]
  positionRail?: { stop: number; entry: number; live: number; target: number }
  pillVariant: 'empty' | 'neutral' | 'negative' | 'positive' | 'neutralDimmed' | 'negativeDimmed' | 'positiveDimmed'
}

export interface OracleWorkspacePanelProps {
  oracle: DashboardFeedState<OracleAssessmentData>
  argus: DashboardFeedState<unknown>
  riskStatus: DashboardFeedState<unknown>
  paperStatus: DashboardFeedState<unknown>
  strategyLab: DashboardFeedState<unknown>
  strategies: DashboardFeedState<unknown>
  eyeOracleProjection?: DashboardFeedState<unknown>
  futuresChart: DashboardFeedState<unknown>
  fusionShadow: DashboardFeedState<unknown>
  optionsStructure?: DashboardFeedState<unknown>
  vobReversal?: DashboardFeedState<unknown>
  orderFlow: DashboardFeedState<unknown>
  optionBuyerIntelligence: DashboardFeedState<unknown>
  marketInfo?: DashboardFeedState<unknown>
  dashboardRevision?: number
  sensorFeedMeta: {
    argus?: DashboardFeedMeta
    futuresChart?: DashboardFeedMeta
    optionBuyerIntelligence?: DashboardFeedMeta
    orderFlow?: DashboardFeedMeta
    marketInfo?: DashboardFeedMeta
  }
  oracleMeta?: DashboardFeedMeta
  missionRuntime: OracleMissionRuntime
}


const record = (value: unknown): JsonRecord =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonRecord
    : {}

const text = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value : null

const finite = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const display = (value: unknown): string => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
  }
  if (typeof value === 'boolean') return value ? 'YES' : 'NO'
  return text(value) ?? 'NOT REPORTED'
}

const displayList = (value: unknown): string => (
  Array.isArray(value) && value.length
    ? value.map(display).join(' + ')
    : display(value)
)

const money = (value: unknown): string => {
  const amount = finite(value)
  return amount === null
    ? 'NOT REPORTED'
    : `₹${amount.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

const formatTime = (value: unknown): string => {
  const raw = text(value)
  if (!raw) return 'NOT REPORTED'
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return raw
  return parsed.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: 'Asia/Kolkata',
    timeZoneName: 'short',
  })
}

const formatAge = (value: unknown): string => {
  const seconds = finite(value)
  if (seconds === null) return 'NOT REPORTED'
  if (seconds < 1) return '<1s'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds / 3600)}h`
}

const ageBetween = (value: unknown, reference: unknown): string => {
  const raw = text(value)
  const referenceRaw = text(reference)
  if (!raw || !referenceRaw) return 'NOT REPORTED'
  const timestamp = new Date(raw).getTime()
  const referenceTimestamp = new Date(referenceRaw).getTime()
  if (!Number.isFinite(timestamp) || !Number.isFinite(referenceTimestamp)) return 'NOT REPORTED'
  return formatAge(Math.max(0, (referenceTimestamp - timestamp) / 1000))
}

const arrayText = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : []

const zone = (value: unknown): string => {
  const item = record(value)
  const low = finite(item.zone_low)
  const high = finite(item.zone_high)
  if (low === null || high === null) return 'NOT REPORTED'
  return `${display(low)}–${display(high)}`
}

const compact = (value: unknown, fallback = 'NOT REPORTED'): string =>
  (text(value) ?? fallback).replaceAll('_', ' ')

const isStale = (value: unknown): boolean =>
  ['STALE', 'DEGRADED', 'CACHED'].includes(String(value ?? '').toUpperCase())

const isUnavailableState = (value: unknown): boolean =>
  ['UNAVAILABLE', 'CONNECTING', 'DETECTING', 'LOADING_CONTEXT', 'NOT REPORTED'].includes(String(value ?? '').toUpperCase())

const directionalVote = (value: unknown): EvidenceVote => {
  const normalized = String(value ?? '').toUpperCase()
  if (['CALL', 'CE', 'BULLISH', 'ULTRA BULLISH'].includes(normalized) || normalized.includes('CALL ADVANTAGE') || normalized.includes('CALL ALIGNED')) return 'SUPPORTS CALL'
  if (['PUT', 'PE', 'BEARISH', 'ULTRA BEARISH'].includes(normalized) || normalized.includes('PUT ADVANTAGE') || normalized.includes('PUT ALIGNED')) return 'SUPPORTS PUT'
  if (['NEUTRAL', 'BALANCED', 'EQUITY', 'NO_TRADE', 'NO TRADE', 'NO CLEAN SIDE', 'NO CLEAN ADVANTAGE'].includes(normalized)) return 'NEUTRAL'
  if (['CONFLICT', 'CONFLICTS', 'MIXED'].includes(normalized)) return 'CONFLICTS'
  return 'NOT REPORTED'
}

const toneFor = (status: unknown, vote: EvidenceVote = 'NOT REPORTED'): NodeTone => {
  const normalized = String(status ?? '').toUpperCase()
  if (['ERROR', 'FAILED', 'REJECTED', 'BLOCKED', 'CORRUPT_FAIL_CLOSED', 'RECONCILIATION_REQUIRED'].includes(normalized)) return 'blocked'
  if (isUnavailableState(normalized)) return 'unavailable'
  if (vote === 'SUPPORTS CALL') return 'call'
  if (vote === 'SUPPORTS PUT') return 'put'
  if (vote === 'SUPPORTIVE') return 'call'
  if (vote === 'BLOCKS') return 'blocked'
  if (vote === 'CONFLICTS' || vote === 'NEUTRAL') return 'neutral'
  if (isStale(normalized) || ['SUBMITTING', 'EXITING', 'PLANNED', 'ACTIVE'].includes(normalized)) return 'stale'
  if (['LIVE', 'READY', 'HEALTHY', 'AVAILABLE', 'OPEN', 'CLOSED', 'ACCEPTED'].includes(normalized)) return 'neutral'
  return 'unavailable'
}

const presentationFor = (vote: EvidenceVote, status: unknown, fallback: PresentationState = 'UNAVAILABLE'): PresentationState => {
  const normalized = String(status ?? '').toUpperCase()
  if (['ERROR', 'FAILED', 'REJECTED', 'BLOCKED', 'CORRUPT_FAIL_CLOSED', 'RECONCILIATION_REQUIRED'].includes(normalized) || vote === 'BLOCKS') return 'BLOCKED'
  if (vote === 'SUPPORTS CALL') return 'CALL'
  if (vote === 'SUPPORTS PUT') return 'PUT'
  if (vote === 'SUPPORTIVE') return 'HEALTHY'
  if (vote === 'CONFLICTS') return 'MIXED'
  if (vote === 'NEUTRAL') return 'PENDING'
  return isUnavailableState(normalized) ? 'UNAVAILABLE' : fallback
}

const feedState = (feed: DashboardFeedState<unknown>, canonical: unknown): string =>
  feed.loading && !feed.data
    ? 'CONNECTING'
    : text(canonical) ?? (feed.data ? 'AVAILABLE' : feed.error ? 'UNAVAILABLE' : 'UNAVAILABLE')

const workflowStage = (runtime: OracleMissionRuntime): WorkflowStage => {
  if (runtime.busyAction === 'ANALYSE') return 'ANALYSING'
  const guardian = runtime.guardian?.state?.toUpperCase()
  if (guardian === 'SUBMITTING' || guardian === 'RECONCILIATION_REQUIRED') return 'SUBMITTING'
  if (guardian === 'OPEN') return 'OPEN'
  if (guardian === 'EXITING') return 'EXITING'
  if (guardian === 'CLOSED') return 'CLOSED'
  if (runtime.plan) return 'PLANNED'
  if (runtime.gate?.decision && runtime.gate.decision !== 'NO_TRADE') return 'QUALIFIED'
  if (runtime.gate) return 'EVALUATED'
  return 'IDLE'
}

const statusClass = (tone: NodeTone): string =>
  `${styles.nodeStatus} ${styles[`tone_${tone}`]}`

const nodeClass = (node: OracleNodeView): string =>
  `${styles.engineNode} ${styles[`node_${node.id}`]} ${styles[`nodeTone_${node.tone}`]}`

const freshnessBadge = (node: OracleNodeView): string => {
  if (node.stale) return 'STALE'
  const normalized = node.status.toUpperCase()
  if (normalized.includes('CONNECTING') || normalized.includes('LOADING')) return 'CONNECTING'
  if (normalized.includes('UNAVAILABLE') || normalized.includes('NOT REPORTED')) return 'UNAVAILABLE'
  if (normalized.includes('DEGRADED')) return 'DEGRADED'
  if (normalized.includes('FAILED') || normalized.includes('REJECTED')) return 'FAILED'
  if (normalized.includes('FRESH') || normalized.includes('LIVE') || normalized.includes('AVAILABLE') || normalized.includes('HEALTHY')) return 'LIVE'
  return node.status
}

const compactPresentation = (node: OracleNodeView | undefined): string => {
  if (!node) return 'UNAVAILABLE'
  const label: Record<PresentationState, string> = {
    CALL: 'CALL', PUT: 'PUT', MIXED: 'MIXED', PENDING: 'WAIT', HEALTHY: 'CLEAR',
    BLOCKED: 'BLOCKED', STANDBY: 'STANDBY', UNAVAILABLE: 'UNAVAILABLE',
  }
  return `${label[node.presentationState]}${node.stale ? ' · STALE' : ''}`
}

function resolvePillVariant(
  text: ReactNode,
  nodeId?: NodeId,
  stale?: boolean,
  vobSupport?: any,
  vobResistance?: any
): 'empty' | 'neutral' | 'negative' | 'positive' | 'neutralDimmed' | 'negativeDimmed' | 'positiveDimmed' {
  const str = String(text).toUpperCase()

  if (
    str.includes('UNAVAILABLE') ||
    str.includes('NOT REPORTED') ||
    str.includes('NO ACTIVE POSITION') ||
    str.includes('STANDBY') ||
    str.includes('UNKNOWN') ||
    str.includes('INSUFFICIENT EVIDENCE') ||
    str.includes('RISK ELIGIBILITY UNAVAILABLE')
  ) {
    return 'empty'
  }

  let baseColor: 'empty' | 'neutral' | 'negative' | 'positive' = 'empty'

  if (nodeId === 'vob') {
    const isResistance = str.includes('RESISTANCE')
    const isSupport = str.includes('SUPPORT')

    if (isResistance) {
      const status = String(vobResistance?.status || '').toUpperCase()
      if (!vobResistance || !vobResistance.status || vobResistance.status === 'UNAVAILABLE' || isUnavailableState(vobResistance.status)) {
        baseColor = 'empty'
      } else if (status === 'BROKEN') {
        baseColor = 'positive'
      } else if (['ACTIVE', 'TESTED', 'WEAKENING'].includes(status)) {
        baseColor = 'negative'
      }
    } else if (isSupport) {
      const status = String(vobSupport?.status || '').toUpperCase()
      if (!vobSupport || !vobSupport.status || vobSupport.status === 'UNAVAILABLE' || isUnavailableState(vobSupport.status)) {
        baseColor = 'empty'
      } else if (status === 'BROKEN') {
        baseColor = 'negative'
      } else if (['ACTIVE', 'TESTED', 'WEAKENING'].includes(status)) {
        baseColor = 'positive'
      }
    }
  } else {
    if (
      str.includes('NEUTRAL') ||
      str.includes('BALANCED') ||
      str.includes('WAIT') ||
      str.includes('REVIEW') ||
      str.includes('COOLDOWN') ||
      str.includes('PENDING')
    ) {
      baseColor = 'neutral'
    } else if (
      str.includes('BEARISH') ||
      str.includes('BLOCKED') ||
      str.includes('MIXED') ||
      str.includes('FAILED') ||
      str.includes('WARNING') ||
      str.includes('DENIED') ||
      str.includes('REJECTED') ||
      str.includes('NEGATIVE') ||
      str.includes('PUT')
    ) {
      baseColor = 'negative'
    } else if (
      str.includes('BULLISH') ||
      str.includes('CALL') ||
      str.includes('HEALTHY') ||
      str.includes('CLEAR') ||
      str.includes('ALLOWED') ||
      str.includes('ACTIVE') ||
      str.includes('TRENDING') ||
      str.includes('POSITIVE')
    ) {
      baseColor = 'positive'
    }
  }

  if (baseColor === 'empty') return 'empty'

  if (stale) {
    if (baseColor === 'positive') return 'positiveDimmed'
    if (baseColor === 'negative') return 'negativeDimmed'
    if (baseColor === 'neutral') return 'neutralDimmed'
  }

  return baseColor
}

function StatusPill({ children, variant, style }: { children: ReactNode; variant: 'negative' | 'positive' | 'neutral' | 'empty' | 'neutralDimmed' | 'negativeDimmed' | 'positiveDimmed'; style?: CSSProperties }) {
  const variantClass = {
    negative: styles.statusPillNegative,
    positive: styles.statusPillPositive,
    neutral: styles.statusPillNeutral,
    empty: styles.statusPillEmpty,
    negativeDimmed: styles.statusPillNegativeDimmed,
    positiveDimmed: styles.statusPillPositiveDimmed,
    neutralDimmed: styles.statusPillNeutralDimmed,
  }[variant]

  return (
    <strong className={`${styles.statusPill} ${variantClass}`} style={style}>
      {children}
    </strong>
  )
}

function Badge({ children, variant = 'neutral', onClick, title }: { children: ReactNode; variant?: 'neutral' | 'positive' | 'negative'; onClick?: () => void; title?: string }) {
  const variantClass = {
    neutral: '',
    positive: styles.badgePositive,
    negative: styles.badgeNegative,
  }[variant]

  if (onClick) {
    return (
      <button type="button" className={`${styles.badge} ${variantClass}`} onClick={onClick} title={title}>
        {children}
      </button>
    )
  }
  return (
    <span className={`${styles.badge} ${variantClass}`} title={title}>
      {children}
    </span>
  )
}

function PositionRail({ rail }: { rail: NonNullable<OracleNodeView['positionRail']> }) {
  const span = rail.target - rail.stop
  if (!(span > 0)) return null
  const clamp = (value: number) => Math.max(0, Math.min(100, value))
  const style = {
    '--entry-position': `${clamp(((rail.entry - rail.stop) / span) * 100)}%`,
    '--live-position': `${clamp(((rail.live - rail.stop) / span) * 100)}%`,
  } as CSSProperties
  return (
    <div className={styles.positionRail} style={style} aria-label={`Stop ${rail.stop}, entry ${rail.entry}, live ${rail.live}, target ${rail.target}`}>
      <span>SL</span><i data-rail-entry /><i data-rail-live /><span>ENTRY</span><span>LIVE</span><span>T1</span>
    </div>
  )
}

const EngineNode = memo(function EngineNode({
  node,
  selected,
  onSelect,
}: {
  node: OracleNodeView
  selected: boolean
  onSelect: (id: NodeId) => void
}) {
  const Icon = node.icon
  return (
    <button
      type="button"
      className={nodeClass(node)}
      data-engine-node={node.id}
      data-evidence-vote={node.vote}
      data-presentation-state={node.presentationState}
      data-stale={node.stale}
      data-selected={selected}
      aria-haspopup="dialog"
      aria-expanded={selected}
      aria-controls="oracle-inspection-drawer"
      onClick={() => onSelect(node.id)}
    >
      <div className={styles.nodeTopline}>
        <span className={styles.nodeEyebrow}>{node.eyebrow}</span>
        <span className={styles.nodeIcon} aria-hidden="true"><Icon size={17} strokeWidth={1.6} /></span>
      </div>
      <div className={styles.nodeTitleRow}>
        <h2>{node.title}</h2>
        <span className={statusClass(node.stale ? 'stale' : node.tone)}><i aria-hidden="true" />{freshnessBadge(node)}</span>
      </div>
      <StatusPill variant={node.pillVariant}>
        {node.headline}
      </StatusPill>
      <div className={styles.nodeMetrics}>
        {node.metrics.slice(0, 2).map((metric) => (
          <span key={metric.label}><b>{metric.label}</b><i>{metric.value}</i></span>
        ))}
      </div>
      {node.metrics.length > 2 && (
        <div className={styles.nodeSpine}>
          {node.metrics.slice(2, 5).map((metric) => (
            <span key={metric.label}><b>{metric.label}</b><i>{metric.value}</i></span>
          ))}
        </div>
      )}
      {node.positionRail && <PositionRail rail={node.positionRail} />}
      <p className={styles.nodeRead}><b>READ</b>{node.read}</p>
      <div className={styles.nodeEvidence}>
        <span data-vote={node.vote}>{compactPresentation(node)}</span>
        <small>AGE {node.freshness}</small>
      </div>
    </button>
  )
})

function FlowMap({
  nodes,
  stage,
  selectedId,
}: {
  nodes: OracleNodeView[]
  stage: WorkflowStage
  selectedId: NodeId | null
}) {
  interface ConnectorGeometry { id: NodeId; path: string; provider: [number, number]; hub: [number, number] }
  const [viewport, setViewport] = useState({ width: 1200, height: 760 })
  const [connectors, setConnectors] = useState<ConnectorGeometry[]>([])
  const svgRef = useRef<SVGSVGElement>(null)

  useLayoutEffect(() => {
    const container = svgRef.current?.closest<HTMLElement>('[data-oracle-graph]')
    if (!container) return
    const measure = () => {
      const containerRect = container.getBoundingClientRect()
      const hubElement = container.querySelector<HTMLElement>('[data-oracle-hub-core]')
      if (!hubElement || containerRect.width <= 0 || containerRect.height <= 0) return
      const hubRect = hubElement.getBoundingClientRect()
      const hubCenter = {
        x: hubRect.left - containerRect.left + hubRect.width / 2,
        y: hubRect.top - containerRect.top + hubRect.height / 2,
      }
      const measured = oracleNodeIds.flatMap((nodeId): ConnectorGeometry[] => {
        const element = container.querySelector<HTMLElement>(`[data-engine-node="${nodeId}"]`)
        if (!element) return []
        const rect = element.getBoundingClientRect()
        const left = rect.left - containerRect.left
        const top = rect.top - containerRect.top
        const right = left + rect.width
        const bottom = top + rect.height
        const provider: Record<NodeId, { x: number; y: number }> = {
          thesis: { x: right, y: top + rect.height / 2 },
          argus: { x: right - 22, y: bottom },
          vob: { x: left + 22, y: bottom },
          ose: { x: left, y: top + rect.height / 2 },
          risk: { x: left + 22, y: top },
          guardian: { x: right - 22, y: top },
        }
        const hubAngle: Record<NodeId, number> = {
          thesis: Math.PI,
          argus: Math.PI * 1.25,
          vob: Math.PI * 1.75,
          ose: 0,
          risk: Math.PI * 0.25,
          guardian: Math.PI * 0.75,
        }
        const hubRadius = Math.max(1, Math.min(hubRect.width, hubRect.height) / 2)
        const angle = hubAngle[nodeId]
        const hub = {
          x: hubCenter.x + Math.cos(angle) * hubRadius,
          y: hubCenter.y + Math.sin(angle) * hubRadius,
        }
        const providerPoint = provider[nodeId]
        const pathDx = hub.x - providerPoint.x
        const pathDy = hub.y - providerPoint.y
        const path = `M ${providerPoint.x.toFixed(2)} ${providerPoint.y.toFixed(2)} C ${(providerPoint.x + pathDx * 0.36).toFixed(2)} ${(providerPoint.y + pathDy * 0.24).toFixed(2)}, ${(providerPoint.x + pathDx * 0.68).toFixed(2)} ${(providerPoint.y + pathDy * 0.82).toFixed(2)}, ${hub.x.toFixed(2)} ${hub.y.toFixed(2)}`
        return [{ id: nodeId, path, provider: [providerPoint.x, providerPoint.y], hub: [hub.x, hub.y] }]
      })
      setViewport({ width: containerRect.width, height: containerRect.height })
      setConnectors(measured)
    }
    const observer = new ResizeObserver(measure)
    observer.observe(container)
    const animationFrame = requestAnimationFrame(() => {
      measure()
      container.querySelectorAll<HTMLElement>('[data-engine-node], [data-oracle-hub-core]').forEach((item) => observer.observe(item))
    })
    window.addEventListener('resize', measure)
    return () => {
      cancelAnimationFrame(animationFrame)
      observer.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [])

  const nodeFor = (id: NodeId) => nodes.find((node) => node.id === id)
  const centerX = viewport.width / 2
  const centerY = viewport.height * 0.53
  return (
    <svg ref={svgRef} className={styles.flowMap} viewBox={`0 0 ${viewport.width} ${viewport.height}`} preserveAspectRatio="none" aria-hidden="true" data-workflow-stage={stage}>
      <defs>
        <filter id="oracle-cable-glow" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <g className={styles.constellation}>
        <circle cx={centerX} cy={centerY} r={Math.min(270, viewport.width * 0.22)} />
        <circle cx={centerX} cy={centerY} r={Math.min(192, viewport.width * 0.15)} />
      </g>
      <g className={styles.evidenceEdges}>
        {connectors.map(({ id, path, provider, hub }, index) => {
          const node = nodeFor(id)
          const vote = node?.vote ?? 'NOT REPORTED'
          return (
          <g key={id} data-vote={vote} data-stale={node?.stale ?? false} data-presentation-state={node?.presentationState ?? 'UNAVAILABLE'}>
            <path
              className={styles.edgeCore}
              d={path}
              data-edge-node={id}
              data-vote={vote}
              data-stale={node?.stale ?? false}
              data-presentation-state={node?.presentationState ?? 'UNAVAILABLE'}
              data-selected={selectedId === id}
            />
            <path
              className={styles.edgeHighlight}
              d={path}
              data-edge-highlight={id}
              data-vote={vote}
              data-stale={node?.stale ?? false}
              data-presentation-state={node?.presentationState ?? 'UNAVAILABLE'}
              data-selected={selectedId === id}
            />
            <circle className={styles.providerAnchor} cx={provider[0]} cy={provider[1]} r="4" data-vote={vote} data-provider-anchor={id} />
            <circle className={styles.hubAnchor} cx={hub[0]} cy={hub[1]} r="4" data-vote={vote} data-hub-anchor={id} />
            <circle className={styles.flowParticle} r="2.6" data-vote={vote} data-stale={node?.stale ?? false}>
              <animateMotion dur={`${5.4 + index * 0.24}s`} begin={`${index * -0.7}s`} repeatCount="indefinite" path={path} />
            </circle>
          </g>
        )})}
      </g>
    </svg>
  )
}

function MissionHub({
  assessment,
  runtime,
  oracleMeta,
  nodes,
  onProof,
  personalSignal,
}: {
  assessment: OracleAssessmentData | null
  runtime: OracleMissionRuntime
  oracleMeta?: DashboardFeedMeta
  nodes: OracleNodeView[]
  onProof: () => void
  personalSignal?: Record<string, any> | null
}) {
  const live = assessment?.live_workspace
  const liveDecision = live?.decision
  const exactOption = liveDecision?.exact_option
  const decision = liveDecision?.action ?? live?.sync_state ?? runtime.gate?.decision ?? 'NOT REPORTED'
  const stage = workflowStage(runtime)
  const missionState = runtime.mission?.status ?? 'NO ACTIVE MISSION'
  const reasonCodes = arrayText(liveDecision?.reason_codes)
  const conflict = reasonCodes[0]
    ?? runtime.gate?.rejection_reasons[0]
    ?? runtime.gate?.critical_missing_inputs[0]
    ?? liveDecision?.risk_conflict
    ?? oracleMeta?.stale_reason
    ?? 'NOT REPORTED'
  const identity = deriveCenterDisplayIdentity({
    chartState: live?.chart_state,
    exactOption,
    fallbackSymbol: assessment?.symbol,
  })

  const decisionDisplay = deriveCenterDecisionDisplay({
    decision: liveDecision,
    runtimeGate: runtime.gate,
    oracleMeta,
    marketState: String(live?.sync_state ?? liveDecision?.action) === 'POST_MARKET' ? 'POST_MARKET' : undefined,
  })

  const decisionTone = toneFor(decision, directionalVote(decision))
  const contract = identity.title
  const contractDisplay = identity.title
  const quote = record(record(exactOption).quote)
  const quotePrice = money(quote.ask ?? quote.ltp)
  const priceDisplay = identity.isExactOption
    ? `${quotePrice !== 'NOT REPORTED' ? quotePrice + ' · ' : ''}${identity.subtitle}`
    : identity.subtitle

  const marketSide = decisionDisplay.side
  const actionLabel = decisionDisplay.actionLabel
  const entry = personalSignal?.entry_band?.map ? personalSignal.entry_band.map(money).join('–') :
    exactOption?.executable_entry_band?.map(money).join('–')
    ?? liveDecision?.entry_band?.map(money).join('–')
    ?? 'NOT REPORTED'
  const stop = personalSignal?.structural_sl ?? liveDecision?.structural_stop?.level ?? exactOption?.premium_invalidation?.level ?? liveDecision?.premium_stop
  const authoritativeTargets = personalSignal?.informational_targets ? Object.values(personalSignal.informational_targets) : liveDecision?.natural_targets?.map((target: any) => target.level).filter((value: any): value is number => typeof value === 'number')
  const targets = authoritativeTargets?.length
    ? authoritativeTargets.map(money).join(' · ')
    : liveDecision?.targets?.length ? liveDecision.targets.map(money).join(' · ') : 'NOT REPORTED'
  const rr = liveDecision?.resulting_rr?.length ? liveDecision.resulting_rr.map(display).join(' · ') : 'NOT REPORTED'
  const principles = record(liveDecision?.why_proof).principle
  const principle = Array.isArray(principles)
    ? principles.map(record)[0]
    : null
  const knowledgeSentence = arrayText(record(live?.personal_oracle?.second_brain?.explainability).why)[0]
    ?? text(principle?.paraphrase)
    ?? 'NOT REPORTED'
  const providerOrder: NodeId[] = ['thesis', 'argus', 'vob', 'ose', 'risk', 'guardian']
  const trigger = display(liveDecision?.trigger)
  return (
    <section className={styles.oracleHub} aria-label="Oracle mission hub" data-oracle-hub data-decision={decision}>
      <div className={styles.hubOrbit} aria-hidden="true"><span /><span /><span /></div>
      <div className={`${styles.hubCore} ${styles[`hubTone_${decisionTone}`]}`} data-oracle-hub-core>
        <div className={styles.hubMark}><Sparkles size={18} strokeWidth={1.5} /></div>
        <span className={styles.hubKicker}>{missionState} · {stage}</span>
        <h1  title={contract}>{contractDisplay}</h1>
        <span className={styles.hubPremium}>{priceDisplay}</span>
        <strong className={styles.hubSide} >{marketSide}</strong>
        <div className={styles.hubAction} >{actionLabel}</div>
        <div className={styles.hubSymbol}>
          <span >{identity.technicalFooter}</span>
          <i aria-hidden="true" />
          <span>{identity.chartFreshness}</span>
        </div>
      </div>
      <div className={styles.hubDetails}>
        <span className={styles.cornerTop} aria-hidden="true" />
        <span className={styles.cornerBottom} aria-hidden="true" />
        <div className={styles.hubMode}>
          <Badge onClick={onProof} title="WHY / WHY NOT / PROOF">WHY / PROOF</Badge>
          <Badge>ADVISORY ONLY</Badge>
          <Badge>NO ORDER SENT</Badge>
          <Badge variant="negative">EXECUTION AUTHORITY FALSE</Badge>
        </div>
        <div className={styles.hubAlignments} aria-label="Provider evidence alignment">
          {providerOrder.map((id) => {
            const node = nodes.find((item) => item.id === id)
            return <span key={id} data-vote={node?.vote ?? 'NOT REPORTED'} data-presentation-state={node?.presentationState ?? 'UNAVAILABLE'} data-stale={node?.stale ?? false}><i aria-hidden="true" /><b>{id === 'guardian' ? 'GUARDIAN' : id.toUpperCase()}</b><em>{compactPresentation(node)}</em></span>
          })}
        </div>
        {/* Personal Strategy Signal Block - Full Width Visual Parity with VOB/OSE */}
        <StatusPill
          variant={
            !personalSignal ? 'empty' :
            (personalSignal.display_tone as any) ||
            (['DETECTED', 'CONFIRMED', 'DEPLOYED', 'MANAGING'].includes(personalSignal.state as string) ? 'positive' :
             ['BLOCKED', 'INVALIDATED', 'MISSING_DATA', 'MISSING_RULE'].includes(personalSignal.state as string) ? 'negative' :
             ['PARTIAL', 'WAIT', 'SCANNING'].includes(personalSignal.state as string) ? 'neutral' : 'empty')
          }
          style={{
            width: '100%',
            marginTop: 10,
            boxSizing: 'border-box',
            display: 'flex',
            justifyContent: 'flex-start',
            alignItems: 'center',
            textTransform: 'uppercase',
            whiteSpace: 'normal',
            lineHeight: 1.3,
          }}
        >
          {String(
            personalSignal?.display_text ||
            (!personalSignal ? 'STRATEGY DATA • UNAVAILABLE' :
             personalSignal.state === 'SCANNING' ? 'SCANNING PERSONAL STRATEGIES' :
             personalSignal.state === 'PARTIAL' ? `${personalSignal.short_label || 'STRATEGY'} • ${personalSignal.satisfied_conditions?.length || 0}/${personalSignal.match_total || 2} CONDITIONS` :
             personalSignal.state === 'DETECTED' ? `${personalSignal.short_label || 'STRATEGY'} DETECTED` :
             personalSignal.state === 'CONFIRMED' ? `${personalSignal.short_label || 'STRATEGY'} CONFIRMED` :
             personalSignal.state === 'BLOCKED' ? `${personalSignal.short_label || 'STRATEGY'} • DATA BLOCKED` :
             personalSignal.state === 'MISSING_RULE' ? `${personalSignal.short_label || 'STRATEGY'} • RULE INCOMPLETE` :
             personalSignal.state === 'DEPLOYED' ? `${personalSignal.short_label || 'STRATEGY'} • DEPLOYED` :
             personalSignal.state === 'MANAGING' ? `${personalSignal.short_label || 'STRATEGY'} • GUARDIAN MANAGING` :
             personalSignal.state === 'EXITED' ? `${personalSignal.short_label || 'STRATEGY'} • EXITED` :
             personalSignal.state)
          )}
        </StatusPill>
        <dl className={styles.hubMetrics}>
          <div><dt>Entry band</dt><dd  title={entry}>{entry}</dd></div>
          <div><dt>Structural SL</dt><dd >{money(stop)}</dd></div>
          <div><dt>Natural targets</dt><dd  title={targets}>{targets}</dd></div>
          <div><dt>RR after costs</dt><dd >{rr}</dd></div>
          <div><dt>Setup quality</dt><dd >{display(liveDecision?.setup_quality)} · NOT PROBABILITY</dd></div>
          <div><dt>Costs</dt><dd >{money(liveDecision?.costs)}</dd></div>
        </dl>
        <div className={styles.hubKnowledge}><b>KNOWLEDGE</b><span>{knowledgeSentence}</span></div>
        <div className={styles.hubConflict} title={String(conflict)}><b>MAIN BLOCKER</b><span>{compact(conflict)}</span></div>
        <div className={styles.hubFreshness}>CHART {live?.chart_state?.freshness ?? 'NOT REPORTED'} · DECISION {liveDecision?.freshness ?? 'NOT REPORTED'} · PREMIUM {exactOption?.freshness ?? 'NOT REPORTED'} · MISSING {liveDecision?.missing_evidence?.length ?? 0}</div>
        <span className={styles.hubAuthority} >ADVISORY ONLY · NO ORDER SENT · EXECUTION AUTHORITY FALSE</span>
      </div>
    </section>
  )
}

function InspectionDrawer({
  node,
  onClose,
}: {
  node: OracleNodeView | null
  onClose: () => void
}) {
  useEffect(() => {
    if (!node) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [node, onClose])

  if (!node) return null
  const Icon = node.icon
  return (
    <aside
      id="oracle-inspection-drawer"
      className={styles.inspectionDrawer}
      role="dialog"
      aria-modal="false"
      aria-labelledby="oracle-drawer-title"
      data-drawer-node={node.id}
    >
      <header className={styles.drawerHeader}>
        <div className={styles.drawerIdentity}>
          <span className={styles.nodeIcon}><Icon size={18} strokeWidth={1.6} /></span>
          <div><small>{node.eyebrow}</small><h2 id="oracle-drawer-title">{node.title}</h2></div>
        </div>
        <button type="button" className={styles.drawerClose} onClick={onClose} aria-label="Close inspection drawer">
          <X size={17} />
        </button>
      </header>
      <div className={styles.drawerVerdict}>
        <span className={statusClass(node.tone)}><i aria-hidden="true" />{node.status}</span>
        <strong>{node.headline}</strong>
        <div><span data-vote={node.vote}>{node.vote}</span><small>FRESHNESS AGE {node.freshness}</small></div>
      </div>
      <div className={styles.drawerBody}>
        {node.sections.map((section) => (
          <section key={section.title} className={styles.drawerSection}>
            <h3>{section.title}</h3>
            <dl>
              {section.rows.map((row) => (
                <div key={`${section.title}-${row.label}`}><dt>{row.label}</dt><dd>{row.value}</dd></div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </aside>
  )
}

function CommandControls({
  runtime,
  canonicalAvailable,
}: {
  runtime: OracleMissionRuntime
  canonicalAvailable: boolean
}) {
  const active = runtime.mission?.status === 'ACTIVE'
  const directional = runtime.gate !== null && runtime.gate.decision !== 'NO_TRADE'
  const canPlan = active && directional && !runtime.plan
  const canExecute = active
    && Boolean(runtime.plan)
    && ['CONFIRM', 'PAPER_AUTOPILOT'].includes(runtime.mission?.mode ?? '')
    && !runtime.guardian
  const guardianOpen = runtime.guardian?.state === 'OPEN'
  const cancellable = active && !['SUBMITTING', 'OPEN', 'EXITING', 'RECONCILIATION_REQUIRED'].includes(runtime.guardian?.state ?? '')
  const busy = runtime.busyAction !== null

  return (
    <section className={styles.commandDeck} aria-label="Oracle mission controls">
      <div className={styles.commandSafety}>
        <span className={styles.paperLock}><ShieldCheck size={15} /> Paper mode</span>
        <span className={styles.liveLock}>LIVE LOCKED</span>
        <span>MAX 1 TRADE</span>
      </div>
      <div className={styles.controlGroup}>
        <button type="button" className={styles.primaryControl} disabled={busy || !canonicalAvailable || (active && runtime.guardian !== null)} onClick={() => void runtime.analyse()}>
          <BrainCircuit size={16} />{runtime.busyAction === 'ANALYSE' ? 'Analysing…' : active ? 'Analyse again' : 'Analyse'}
        </button>
        <button type="button" disabled={busy || !canPlan} onClick={() => void runtime.createPlan()}>
          <FileSearch size={16} />{runtime.busyAction === 'CREATE_PLAN' ? 'Creating…' : 'Create Plan'}
        </button>
        <button type="button" disabled={busy || !canExecute} onClick={() => void runtime.paperExecute()}>
          <RadioTower size={16} />{runtime.busyAction === 'PAPER_EXECUTE' ? 'Submitting…' : 'Paper Execute'}
        </button>
        <button type="button" disabled={busy || !cancellable} onClick={() => void runtime.cancel()}>
          <Crosshair size={16} />{runtime.busyAction === 'CANCEL' ? 'Cancelling…' : 'Reject / Cancel'}
        </button>
        <button type="button" className={styles.exitControl} disabled={busy || !guardianOpen} onClick={() => void runtime.exitNow()}>
          <HeartPulse size={16} />{runtime.busyAction === 'EXIT_NOW' ? 'Exiting…' : 'Exit Now'}
        </button>
      </div>
      <div className={styles.commandMessage} role="status" aria-live="polite">
        {runtime.error
          ? <span className={styles.commandError}>{runtime.error}</span>
          : runtime.loading
            ? 'Connecting to durable Oracle mission state…'
            : runtime.stateReason ?? 'Controls unlock only when canonical backend state permits.'}
      </div>
    </section>
  )
}

function DismissibleAlertToast({ alert, onDismiss }: { alert: OracleAlertEvent; onDismiss: () => void }) {
  const [phase, setPhase] = useState<'visible' | 'leaving'>('visible')
  const timeout = useRef<number | null>(null)
  const exitTimeout = useRef<number | null>(null)
  const remaining = useRef(ALERT_TOAST_DURATION_MS)
  const startedAt = useRef(0)

  const clearDismissTimer = () => {
    if (timeout.current !== null) window.clearTimeout(timeout.current)
    timeout.current = null
  }
  const dismiss = () => {
    if (phase === 'leaving') return
    clearDismissTimer()
    setPhase('leaving')
    exitTimeout.current = window.setTimeout(onDismiss, ALERT_TOAST_EXIT_MS)
  }
  const resume = () => {
    if (phase === 'leaving' || timeout.current !== null) return
    startedAt.current = performance.now()
    timeout.current = window.setTimeout(dismiss, remaining.current)
  }
  const pause = () => {
    if (timeout.current === null) return
    remaining.current = Math.max(0, remaining.current - (performance.now() - startedAt.current))
    clearDismissTimer()
  }

  useEffect(() => {
    remaining.current = ALERT_TOAST_DURATION_MS
    resume()
    return () => {
      clearDismissTimer()
      if (exitTimeout.current !== null) window.clearTimeout(exitTimeout.current)
    }
  // A new deduplication key starts one independent ten-second lifecycle.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alert.deduplication_key])

  return (
    <div
      className={styles.alertToast}
      data-alert-toast
      data-alert-key={alert.deduplication_key}
      data-phase={phase}
      data-severity={alert.severity}
      onMouseEnter={pause}
      onMouseLeave={resume}
      onFocus={pause}
      onBlur={resume}
      role="status"
    >
      <Bell size={14} />
      <strong>{alert.event_type.replaceAll('_', ' ')}</strong>
      <span>{alert.message}</span>
      <button type="button" onClick={dismiss} aria-label="Dismiss alert"><X size={13} /></button>
    </div>
  )
}

function OracleAlertOverlay({ live }: { live: OracleLiveWorkspaceProjection | undefined }) {
  const alert = live?.alert_event
  const [preferences, setPreferences] = useState<AlertPreferences>(defaultAlertPreferences)
  const [history, setHistory] = useState<OracleAlertEvent[]>([])
  const [activeToast, setActiveToast] = useState<OracleAlertEvent | null>(null)
  const [hydrated, setHydrated] = useState(false)
  const [limitation, setLimitation] = useState<string | null>(null)
  const seen = useRef<Record<string, number>>({})
  const persistedKeys = useRef(new Set<string>())

  useEffect(() => {
    queueMicrotask(() => {
      try {
        const storedPreferences = window.localStorage.getItem('citadel-oracle-alert-preferences-v1')
        const storedHistory = window.localStorage.getItem('citadel-oracle-alert-history-v1')
        if (storedPreferences) setPreferences({ ...defaultAlertPreferences, ...JSON.parse(storedPreferences) as AlertPreferences })
        if (storedHistory) {
          const parsed = (JSON.parse(storedHistory) as OracleAlertEvent[]).slice(0, 50)
          parsed.forEach((item) => persistedKeys.current.add(item.deduplication_key))
          setHistory(parsed)
        }
      } catch { setLimitation('ALERT STORAGE UNAVAILABLE') }
      setHydrated(true)
    })
  }, [])

  const update = (next: AlertPreferences) => {
    setPreferences(next)
    try { window.localStorage.setItem('citadel-oracle-alert-preferences-v1', JSON.stringify(next)) } catch { setLimitation('ALERT PREFERENCES STORAGE UNAVAILABLE') }
  }

  useEffect(() => {
    if (!alert || !hydrated) return
    const now = Date.now()
    const last = seen.current[alert.event_type] ?? 0
    if (seen.current[alert.deduplication_key] || persistedKeys.current.has(alert.deduplication_key) || now - last < alert.cooldown_seconds * 1000) return
    seen.current[alert.deduplication_key] = now
    seen.current[alert.event_type] = now
    persistedKeys.current.add(alert.deduplication_key)
    setHistory((current) => {
      const nextHistory = [alert, ...current.filter((item) => item.deduplication_key !== alert.deduplication_key)].slice(0, 50)
      try { window.localStorage.setItem('citadel-oracle-alert-history-v1', JSON.stringify(nextHistory)) } catch { queueMicrotask(() => setLimitation('ALERT HISTORY STORAGE UNAVAILABLE')) }
      return nextHistory
    })
    const ist = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
    const minutes = ist.getHours() * 60 + ist.getMinutes()
    const inMarketHours = ist.getDay() >= 1 && ist.getDay() <= 5 && minutes >= 555 && minutes <= 930
    const enabled = preferences.events[alert.event_type] !== false
      && (!preferences.criticalOnly || alert.severity === 'CRITICAL')
      && (!preferences.marketHoursOnly || inMarketHours)
    if (!enabled) return
    queueMicrotask(() => setActiveToast(alert))
    if (preferences.browser) {
      if ('Notification' in window && Notification.permission === 'granted') new Notification('CITADEL ORACLE', { body: alert.message, tag: alert.deduplication_key })
      else queueMicrotask(() => setLimitation(`BROWSER NOTIFICATIONS ${'Notification' in window ? Notification.permission.toUpperCase() : 'UNAVAILABLE'} · IN-APP ACTIVE`))
    }
    if (!preferences.muted) {
      try {
        const AudioContextClass = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
        if (!AudioContextClass) throw new Error('UNAVAILABLE')
        const context = new AudioContextClass()
        const oscillator = context.createOscillator()
        const gain = context.createGain()
        oscillator.frequency.value = alert.severity === 'CRITICAL' ? 880 : 620
        gain.gain.value = Math.max(0, Math.min(1, preferences.volume))
        oscillator.connect(gain); gain.connect(context.destination)
        oscillator.start(); oscillator.stop(context.currentTime + 0.12)
        oscillator.onended = () => void context.close()
      } catch { queueMicrotask(() => setLimitation('SOUND BLOCKED BY BROWSER · IN-APP ACTIVE')) }
    }
  // History is intentionally excluded: processing one event must not retrigger itself.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alert?.deduplication_key, hydrated, preferences])

  const requestBrowser = async () => {
    if (!('Notification' in window)) { setLimitation('BROWSER NOTIFICATIONS UNAVAILABLE · IN-APP ACTIVE'); return }
    const permission = await Notification.requestPermission()
    update({ ...preferences, browser: permission === 'granted' })
    setLimitation(permission === 'granted' ? null : `BROWSER NOTIFICATIONS ${permission.toUpperCase()} · IN-APP ACTIVE`)
  }

  return (
    <aside className={styles.alertOverlay} aria-label="Oracle alerts" data-oracle-alerts>
      {activeToast && <DismissibleAlertToast key={activeToast.deduplication_key} alert={activeToast} onDismiss={() => setActiveToast(null)} />}
      <details>
        <summary><Bell size={13} /> ALERTS · {preferences.muted ? 'MUTED' : 'ACTIVE'} · {history.length}</summary>
        <div className={styles.alertControls}>
          <button type="button" onClick={() => update({ ...preferences, muted: !preferences.muted })}>{preferences.muted ? <BellOff size={13} /> : <Volume2 size={13} />}{preferences.muted ? 'Unmute' : 'Mute'}</button>
          <button type="button" onClick={() => void requestBrowser()}>Browser {preferences.browser ? 'on' : 'off'}</button>
          <label>Volume <input aria-label="Alert volume" type="range" min="0" max="1" step="0.05" value={preferences.volume} onChange={(event) => update({ ...preferences, volume: Number(event.target.value) })} /></label>
          <label><input type="checkbox" checked={preferences.criticalOnly} onChange={(event) => update({ ...preferences, criticalOnly: event.target.checked })} /> Critical only</label>
          <label><input type="checkbox" checked={preferences.marketHoursOnly} onChange={(event) => update({ ...preferences, marketHoursOnly: event.target.checked })} /> Market hours only</label>
          <details className={styles.alertEventPreferences}>
            <summary>Per-event preferences</summary>
            {oracleAlertEventTypes.map((eventType) => <label key={eventType}><input type="checkbox" checked={preferences.events[eventType] !== false} onChange={(event) => update({ ...preferences, events: { ...preferences.events, [eventType]: event.target.checked } })} /> {eventType.replaceAll('_', ' ')}</label>)}
          </details>
          {limitation && <small>{limitation}</small>}
          <ol data-alert-history>{history.slice(0, 8).map((item) => <li key={item.deduplication_key} data-alert-history-key={item.deduplication_key}><b>{item.event_type.replaceAll('_', ' ')}</b><span>{formatTime(item.generated_at)}</span></li>)}</ol>
        </div>
      </details>
    </aside>
  )
}

function PlanReadout({ plan, live }: { plan: OracleTradePlan | null; live?: OracleLiveWorkspaceProjection }) {
  const decision = live?.decision
  const entry = decision?.exact_option?.executable_entry_band?.length
    ? decision.exact_option.executable_entry_band.map(money).join('–')
    : decision?.entry_band?.length ? decision.entry_band.map(money).join('–') : null
  const targets = decision?.targets?.length ? decision.targets.map(money).join(' · ') : null
  const rr = decision?.resulting_rr?.length ? decision.resulting_rr.map(display).join(' · ') : null
  return (
    <aside className={styles.missionReadout} aria-label="Oracle canonical readout">
      <div><span>Trigger</span><strong>{decision?.trigger ?? 'NOT REPORTED'}</strong></div>
      <div><span>Executable entry</span><strong>{plan ? money(plan.maximum_entry) : entry ?? 'NOT REPORTED'}</strong></div>
      <div><span>Structural SL</span><strong>{plan ? money(plan.final_sl) : money(decision?.exact_option?.premium_invalidation?.level ?? decision?.premium_stop)}</strong></div>
      <div><span>Natural targets</span><strong>{plan ? `${money(plan.target_1)} · ${money(plan.target_2)}` : targets ?? 'NOT REPORTED'}</strong></div>
      <div><span>Resulting R / R</span><strong>{plan ? display(plan.reward_risk) : rr ?? 'NOT REPORTED'}</strong></div>
      <div><span>Mode / authority</span><strong>PAPER · FALSE</strong></div>
    </aside>
  )
}

const FlowPulseStoreBridge = memo(function FlowPulseStoreBridge({
  visualFixture,
  initialLabOpen,
}: {
  visualFixture: string | null
  initialLabOpen: boolean
}) {
  const orderFlow = useDashboardSelector(feedSelectors.orderFlow) as DashboardFeedState<unknown>
  return <>
    <OracleLiveFlow feed={orderFlow} visualFixture={visualFixture} initialLabOpen={initialLabOpen} />
    <OracleFlowPulse feed={orderFlow} />
    <FlowPulsePaperLedger feed={orderFlow} />
  </>
})

export function OracleWorkspacePanel({
  oracle,
  argus,
  riskStatus,
  paperStatus,
  strategyLab,
  strategies,
  eyeOracleProjection,
  futuresChart,
  optionsStructure: optionsStructureFeed,
  vobReversal: vobReversalFeed,
  orderFlow,
  optionBuyerIntelligence,
  marketInfo,
  dashboardRevision,
  sensorFeedMeta,
  oracleMeta,
  missionRuntime,
}: OracleWorkspacePanelProps) {
  const [selectedId, setSelectedId] = useState<NodeId | null>(null)
  const [pageVisible, setPageVisible] = useState(true)
  const graphRef = useRef<HTMLElement>(null)
  const assessment = oracle.data
  const flowFixture = useSyncExternalStore(
    subscribeStaticLocation,
    () => process.env.NODE_ENV !== 'production'
      ? new URLSearchParams(window.location.search).get('flowFixture')
      : null,
    () => null,
  )
  const argus01cFixture = useSyncExternalStore(
    subscribeStaticLocation,
    () => process.env.NODE_ENV !== 'production'
      ? new URLSearchParams(window.location.search).get('argus01cFixture')
      : null,
    () => null,
  )
  const flowLabOpen = useSyncExternalStore(
    subscribeStaticLocation,
    () => process.env.NODE_ENV !== 'production'
      && new URLSearchParams(window.location.search).get('flowLab') === 'open',
    () => false,
  )
  const vobUiMode = useSyncExternalStore(
    subscribeStaticLocation,
    () => new URLSearchParams(window.location.search).get('vobUi'),
    () => null,
  )
  const live = assessment?.live_workspace
  const liveDecision = live?.decision
  const canonicalOracleFreshness = oracleMeta?.freshness ?? liveDecision?.freshness ?? live?.sync_state ?? 'UNAVAILABLE'
  const eyeData = record(eyeOracleProjection?.data)
  const eyeStructure = record(eyeData.structure)
  const eyeSetup = record(eyeData.setup_projection)
  const eyeTradePlan = record(eyeData.trade_plan)
  const eyeEntry = record(eyeTradePlan.entry_geometry)
  const eyeStop = record(eyeTradePlan.structural_stop)
  const eyeTargets = Array.isArray(eyeTradePlan.natural_targets) ? eyeTradePlan.natural_targets.map(record) : []
  const eyeThesis = record(eyeData.market_thesis)
  const exactOption = liveDecision?.exact_option

  const exactOptionData = record(exactOption)
  const exactQuote = record(exactOptionData.quote)
  const liveChart = live?.chart_state
  const tradingViewContextStatus = liveChart?.availability === 'AVAILABLE'
    ? (liveChart.freshness === 'FRESH' ? 'LIVE' : liveChart.freshness)
    : (live?.sync_state ?? 'DETECTING')
  const tradingViewContextAge = live?.health.state_age_seconds ?? oracleMeta?.freshness_age_seconds
  const livePhase5 = live?.phase5
  const secondBrain = record(live?.personal_oracle?.second_brain)
  const discipline = record(secondBrain.discipline)
  const explainability = record(secondBrain.explainability)
  const personalSignalContainer = record(eyeData.personal_strategy_signal)
  const personalSignal = personalSignalContainer?.primary_signal ? record(personalSignalContainer.primary_signal) : null
  const disciplineWarnings = Array.isArray(discipline.warnings)
    ? discipline.warnings.map((item) => display(record(item).code)).filter((item) => item !== 'NOT REPORTED')
    : []
  const whyProof = record(liveDecision?.why_proof)
  const currentEvidence = record(whyProof.current_evidence)
  const historicalEvidence = record(whyProof.historical_evidence)
  const historicalStatistics = record(historicalEvidence.statistics)
  const proofPrinciples = Array.isArray(whyProof.principle) ? whyProof.principle.map(record) : []
  const proofConflicts = Array.isArray(whyProof.principle_conflicts) ? whyProof.principle_conflicts.map(record) : []
  const argusEnvelope = record(argus.data)
  const argusData = record(argusEnvelope.data)
  const tactical = record(argusData.tactical_edge)
  const argusUnderlying = record(argusData.underlying)
  const argusProvider = buildArgusProviderProjection({
    envelope: argusEnvelope,
    tactical,
    exactContract: exactOption?.exact_contract,
    chartOption: liveChart?.option,
    currentUnderlying: liveChart?.instrument.underlying,
  })
  const risk = record(riskStatus.data)
  const riskLimits = record(risk.limits)
  const paper = record(paperStatus.data)
  const lab = record(strategyLab.data)
  const strategiesData = record(strategies.data)
  const deployedInstances = Array.isArray(strategiesData.oracle_instances)
    ? strategiesData.oracle_instances.map(record)
    : []
  const labStatus = record(lab.status)
  const execution = record(lab.execution)
  const vob = canonicalNiftyVobPresentation(vobReversalFeed?.data, execution.nifty_vob)
  const vobSync = record(vob.source_1m_sync)
  const vobTimeframes = record(vob.timeframes)
  const vob3m = record(vobTimeframes['3m'])
  const vob5m = record(vobTimeframes['5m'])
  const vob15m = record(vobTimeframes['15m'])
  const vobSupport = record(vob5m.nearest_bullish_support ?? vob.nearest_support ?? vob3m.nearest_bullish_support ?? vob15m.nearest_bullish_support)
  const vobResistance = record(vob5m.nearest_bearish_resistance ?? vob.nearest_resistance ?? vob3m.nearest_bearish_resistance ?? vob15m.nearest_bearish_resistance)
  const supportDist = typeof vobSupport.distance_points === 'number' ? vobSupport.distance_points : null
  const resistanceDist = typeof vobResistance.distance_points === 'number' ? vobResistance.distance_points : null
  // Direct OSE Fast-Lane/SSE publication is authoritative for its own
  // timestamp and revision.  The Strategy Lab copy remains a legacy fallback.
  const directOptionsStructure = record(optionsStructureFeed?.data)
  const optionsStructure = Object.keys(directOptionsStructure).length
    ? directOptionsStructure
    : record(execution.options_structure)
  const optionsDuel = record(optionsStructure.duel)
  const optionsContracts = record(optionsStructure.contracts)
  const optionsCe = record(optionsContracts.CE)
  const optionsPe = record(optionsContracts.PE)
  const optionsCeContract = record(optionsCe.contract)
  const optionsPeContract = record(optionsPe.contract)
  const optionsCeSsi = record(optionsCe.ssi)
  const optionsPeSsi = record(optionsPe.ssi)
  const optionsCeTrend = record(optionsCe.trend)
  const optionsPeTrend = record(optionsPe.trend)
  const optionsFlow = record(optionsStructure.option_flow)
  const stage = workflowStage(missionRuntime)
  const frontendSamples = useRef({ event_receipt: [] as number[], state_update: [] as number[], visible_render: [] as number[] })
  const [frontendPerformance, setFrontendPerformance] = useState({
    event_receipt: emptyPerformanceStats(), state_update: emptyPerformanceStats(), visible_render: emptyPerformanceStats(),
  })

  useEffect(() => {
    const update = () => setPageVisible(document.visibilityState !== 'hidden')
    update()
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])

  useEffect(() => {
    const receivedAt = live?.frontend_transport?.received_at_epoch_ms
    if (!receivedAt) return
    const receiptLatency = live?.frontend_transport?.event_receipt_ms
    if (typeof receiptLatency === 'number' && Number.isFinite(receiptLatency)) {
      frontendSamples.current.event_receipt.push(receiptLatency)
      frontendSamples.current.event_receipt = frontendSamples.current.event_receipt.slice(-256)
    }
    const stateLatency = Math.max(0, Date.now() - receivedAt)
    frontendSamples.current.state_update.push(stateLatency)
    frontendSamples.current.state_update = frontendSamples.current.state_update.slice(-256)
    const frame = requestAnimationFrame(() => {
      const renderLatency = Math.max(0, Date.now() - receivedAt)
      frontendSamples.current.visible_render.push(renderLatency)
      frontendSamples.current.visible_render = frontendSamples.current.visible_render.slice(-256)
      setFrontendPerformance({
        event_receipt: summarizePerformance(frontendSamples.current.event_receipt),
        state_update: summarizePerformance(frontendSamples.current.state_update),
        visible_render: summarizePerformance(frontendSamples.current.visible_render),
      })
    })
    return () => cancelAnimationFrame(frame)
  }, [live?.content_hash, live?.frontend_transport?.event_receipt_ms, live?.frontend_transport?.received_at_epoch_ms])

  const nodes: OracleNodeView[] = (() => {
    const oracleState = oracle.loading && !assessment
      ? 'CONNECTING'
      : assessment
        ? canonicalOracleFreshness
        : oracle.error ? 'UNAVAILABLE' : canonicalOracleFreshness
    const oracleDirection = liveDecision?.market_thesis?.direction ?? assessment?.directional_bias
    const oracleVote = isUnavailableState(oracleState) ? 'NOT REPORTED' : directionalVote(oracleDirection)
    const argusState = argus.loading
      ? 'CONNECTING'
      : argusProvider.providerLineageAvailable
        ? argusProvider.state
        : feedState(argus, argusProvider.state)
    const argusDirection = argusProvider.verdict
    const argusVote = isUnavailableState(argusState) ? 'NOT REPORTED' : directionalVote(argusDirection)
    const vobLineage = record(record(liveDecision?.provider_lineage).VOB)
    const vobProviderFreshness = (typeof vobLineage.freshness === 'string' ? vobLineage.freshness : null)
      ?? (vob.market_input_state === 'LIVE' ? 'FRESH' : typeof vob.market_input_state === 'string' ? vob.market_input_state : 'UNAVAILABLE')
    const vobState = isStale(vobProviderFreshness)
      ? 'STALE'
      : (vob.market_input_state === 'LIVE' ? 'LIVE' : display(vob.status ?? vobSync.runtime_status ?? 'AVAILABLE'))
    const vobConfluence = record(vob.strongest_confluence)
    const vobBullishConfluence = record(vobConfluence.bullish)
    const vobBearishConfluence = record(vobConfluence.bearish)
    const vobDirection = Object.keys(vobBullishConfluence).length && Object.keys(vobBearishConfluence).length
      ? 'MIXED'
      : vobBullishConfluence.side ?? vobBearishConfluence.side ?? vobConfluence.direction ?? vob.dominant_bias
    const vobVote = isUnavailableState(vobState) ? 'NOT REPORTED' : directionalVote(vobDirection)
    const oseState = display(optionsStructure.source_freshness ?? optionsStructure.status ?? exactOption?.freshness ?? exactOption?.status)
    const oseClassification = display(optionsDuel.state ?? record(optionsStructure.structural_read).headline)
    const oseVote = isUnavailableState(oseState)
      ? 'NOT REPORTED'
      : oseClassification.includes('CALL')
        ? 'SUPPORTS CALL'
        : oseClassification.includes('PUT')
          ? 'SUPPORTS PUT'
          : oseClassification.includes('BALANCED') || oseClassification.includes('NO CLEAN')
            ? 'NEUTRAL'
            : 'NOT REPORTED'
    const disciplineAction = display(discipline.recommendation ?? live?.personal_oracle.cooldown_status ?? 'UNAVAILABLE')
    const riskState = feedState(riskStatus, risk.state_health ?? risk.status)
    const riskAvailable = risk.risk_state_available === true
      && !['UNAVAILABLE', 'DEGRADED', 'CONNECTING'].includes(riskState.toUpperCase())
    const riskBlocked = risk.kill_switch_active === true || !riskAvailable
    const riskVote: EvidenceVote = riskBlocked
      ? 'BLOCKS'
      : disciplineWarnings.length || ['WAIT', 'REVIEW', 'COOLDOWN'].includes(disciplineAction)
        ? 'NEUTRAL'
        : 'SUPPORTIVE'
    const paperState = feedState(paperStatus, paper.state_health ?? paper.status)
    const guardianState = livePhase5?.guardian_action ?? missionRuntime.guardian?.state ?? 'STANDBY'
    const freshnessAge = formatAge(oracleMeta?.freshness_age_seconds)
    const quoteAge = ageBetween(exactQuote.source_timestamp ?? exactOptionData.source_timestamp, live?.generated_timestamp)
    const exactIdentity = exactOption?.exact_contract.trading_symbol ?? liveDecision?.displayed_option ?? 'NOT REPORTED'
    const exactArgus = record(exactOption?.confirmations?.argus)
    const exactArgusAvailable = argusProvider.exactContractLineageAvailable && Boolean(text(exactArgus.status))
    const exactArgusValue = (value: unknown) => exactArgusAvailable ? display(value) : 'NOT REPORTED'
    const spineMetric = (row: typeof argusProvider.compactSpine[number]): string => (
      row.strike === null
        ? 'NOT REPORTED'
        : `${display(row.strike)} · CE ${display(row.ceLoad)} / PE ${display(row.peLoad)}`
    )
    const fullSpineRows = argusProvider.fullSpine.map((row) => ({
      label: row.label,
      value: `${spineMetric(row)} · ${compact(row.flowState)} · ${compact(row.structuralRole)}`,
    }))
    const exactSpread = finite(exactQuote.spread_pct)
    const warningValue = (needle: string) => disciplineWarnings.find((item) => item.includes(needle)) ?? 'NOT REPORTED'
    const completedEvidence = arrayText(currentEvidence.supporting_facts)
    const proofConflictText = arrayText(currentEvidence.conflicts)
    const principleRows = proofPrinciples.flatMap((item) => [
      { label: display(item.card_id), value: `${display(item.source)} · ${display(item.exact_locator)}` },
      { label: 'Relevance / failure', value: `${display(item.relevance)} · ${displayList(item.failure_conditions)}` },
    ])
    const firstNaturalTarget = eyeTargets.length > 0
      ? { level: eyeTargets[0].price, type: eyeTargets[0].target_type }
      : liveDecision?.natural_targets?.find((target) => typeof target.level === 'number')
    const structuralStop = eyeStop.sl_price !== undefined && eyeStop.sl_price !== null
      ? { level: eyeStop.sl_price, type: eyeStop.sl_type }
      : liveDecision?.structural_stop
    const thesisHeadline = text(eyeData.price_action_summary) ?? (oracleDirection
      ? `${String(oracleDirection).toUpperCase() === 'BULLISH' ? '↑' : String(oracleDirection).toUpperCase() === 'BEARISH' ? '↓' : '↔'} ${compact(oracleDirection)} · ${compact(assessment?.regime)}`
      : 'INSUFFICIENT EVIDENCE')
    const touchStrength = (value: unknown): string => {
      const touches = finite(value)
      if (touches === null) return 'NOT REPORTED'
      if (touches === 0) return 'FRESH / STRONGEST'
      if (touches === 1) return 'WEAKENED'
      if (touches === 2) return 'WEAK'
      return 'EXHAUSTED'
    }
    const trendRead = (value: JsonRecord): string => {
      const above = value.above_ema_50
      const supertrend = text(value.supertrend_direction)
      const bar = finite(value.close)
      return `EMA50 ${above === true ? '↑' : above === false ? '↓' : 'NOT REPORTED'} · ST ${supertrend === 'POSITIVE' ? '↑' : supertrend === 'NEGATIVE' ? '↓' : 'NOT REPORTED'} · BAR ${bar === null ? 'NOT REPORTED' : money(bar)}`
    }
    const guardianVote: EvidenceVote = livePhase5?.position_id
      ? ['FAILED_SAFE', 'RECONCILIATION_REQUIRED', 'EXIT'].includes(String(guardianState).toUpperCase()) ? 'BLOCKS' : 'SUPPORTIVE'
      : 'NOT REPORTED'
    const recentVobEvents = Array.isArray(vob5m.recently_broken) ? vob5m.recently_broken.map(record) : []
    const latestVobEvent = recentVobEvents[0]
    const vobSpot = finite(vob5m.current_nifty_price ?? vob.current_nifty_spot)
    const vobLocation = vobSpot === null
      ? 'PRICE NOT REPORTED'
      : `PRICE ${display(vobSpot)} · ${vobSpot > (finite(vobSupport.zone_high) ?? vobSpot) && vobSpot < (finite(vobResistance.zone_low) ?? vobSpot) ? 'BETWEEN ZONES' : 'AT ZONE'}`
    const staleSuffix = (label: string, state: unknown): string => isStale(state) ? `${label} · STALE` : label
    const acceleration = (value: unknown): string => {
      const amount = finite(value)
      if (amount === null) return 'NOT REPORTED'
      const absolute = Math.abs(amount)
      if (absolute >= 10_000_000) return `${(amount / 10_000_000).toFixed(2)}Cr`
      if (absolute >= 100_000) return `${(amount / 100_000).toFixed(2)}L`
      return amount.toLocaleString('en-IN', { maximumFractionDigits: 0 })
    }
    const vobEventRead = latestVobEvent
      ? `LATEST ${display(latestVobEvent.role)} ${display(latestVobEvent.status)} · ${ageBetween(latestVobEvent.broken_at, live?.generated_timestamp)} AGO · NEXT NOT REPORTED`
      : `${vobLocation} · NEXT NOT REPORTED`
    const noTradesToday = finite(paper.trades_taken_today) === 0
    const guardianEntry = finite(record(livePhase5?.order).average_fill_price)
    const guardianLive = finite(missionRuntime.guardian?.last_quote)
    const guardianStop = finite(missionRuntime.guardian?.current_stop)
    const guardianTarget = finite(missionRuntime.guardian?.target_1)
    const positionRail = guardianEntry !== null && guardianLive !== null && guardianStop !== null && guardianTarget !== null
      ? { entry: guardianEntry, live: guardianLive, stop: guardianStop, target: guardianTarget }
      : undefined
    return [
      {
        id: 'thesis',
        title: 'Market Thesis',
        eyebrow: 'Context + analyst',
        status: oracleState,
        headline: thesisHeadline,
        read: text(eyeData.why) ?? liveDecision?.why ?? oracle.error ?? oracleMeta?.stale_reason ?? 'INSUFFICIENT EVIDENCE',

        resultLabel: staleSuffix(oracleVote === 'SUPPORTS CALL'
            ? 'CALL ALIGNED'
            : oracleVote === 'SUPPORTS PUT'
              ? 'PUT ALIGNED'
              : oracleVote === 'CONFLICTS' || oracleVote === 'NEUTRAL'
                ? 'MIXED / PULLBACK'
                : 'NO CLEAN STRUCTURE', oracleState),
        metrics: [
          { label: '15m / 5m / 3m', value: `${vob15m.nearest_bullish_support ? '15M SUP' : vob15m.nearest_bearish_resistance ? '15M RES' : '15M'} · ${vob5m.nearest_bullish_support ? '5M SUP' : vob5m.nearest_bearish_resistance ? '5M RES' : '5M'} · ${vob3m.nearest_bullish_support ? '3M SUP' : vob3m.nearest_bearish_resistance ? '3M RES' : '3M'}` },
          { label: 'Location', value: display(liveDecision?.market_thesis?.location_quality ?? record(assessment).location_quality) },
          { label: 'Structure / liquidity / FVG', value: display(record(liveDecision?.market_thesis).structure_state ?? (vobBullishConfluence.tier ? `${vobBullishConfluence.tier} CONFLUENCE` : 'VOB ACTIVE')) },
          { label: 'Confirm', value: display(liveDecision?.trigger ?? 'CONFIRMED') },
          { label: 'Invalid / target', value: `${structuralStop?.level === null || structuralStop?.level === undefined ? display(liveDecision?.structural_invalidation) : display(structuralStop.level)} / ${display(firstNaturalTarget?.level)}` },
        ],
        vote: oracleVote,
        freshness: freshnessAge,
        tone: toneFor(oracleState, oracleVote),
        presentationState: presentationFor(oracleVote, oracleState, 'PENDING'),
        stale: isStale(oracleState),
        pillVariant: resolvePillVariant(thesisHeadline, 'thesis', isStale(oracleState)),
        icon: FileSearch,
        sections: [
          { title: 'Current thesis', rows: [
            { label: 'Detected instrument', value: `${display(liveChart?.symbol.normalized_symbol)} · ${display(liveChart?.instrument.security_id)}` },
            { label: 'Direction', value: display(eyeStructure.directional_structure ?? assessment?.directional_bias) },
            { label: 'Regime', value: display(assessment?.regime) },
            { label: 'HTF alignment 1D / 4H / 1H / 15m', value: `${display(record(record(assessment).htf_context)['1D'] ?? 'AVAILABLE')} / ${display(record(record(assessment).htf_context)['4H'] ?? 'AVAILABLE')} / ${display(record(record(assessment).htf_context)['1H'] ?? 'AVAILABLE')} / ${display(eyeStructure.htf_alignment_state ?? record(record(assessment).htf_context)['15m'] ?? 'AVAILABLE')}` },
            { label: 'Current location', value: display(liveDecision?.market_thesis?.location_quality) },
            { label: 'Active setup', value: display(eyeSetup.family ?? liveDecision?.setup_family ?? liveDecision?.reason_codes?.[0]) },
            { label: 'Trigger status', value: display(eyeSetup.lifecycle ?? liveDecision?.trigger) },
            { label: 'Structural invalidation', value: `${display(structuralStop?.type ?? liveDecision?.structural_invalidation)} · ${display(structuralStop?.level)}` },

            { label: 'Setup quality (not probability)', value: display(liveDecision?.setup_quality) },
            { label: 'Main conflict', value: proofConflictText[0] ?? display(liveDecision?.risk_conflict) },
            { label: 'Missing evidence', value: liveDecision?.missing_evidence.join(' · ') || 'NONE REPORTED' },
          ] },
          { title: 'Truth lineage', rows: [
            { label: 'Authority', value: 'OracleDecisionEnvelope + AnalysisSnapshot' },
            { label: 'Instrument / timeframe', value: `${display(liveChart?.symbol.normalized_symbol)} / ${display(liveChart?.timeframe)}` },
            { label: 'Source timestamp', value: formatTime(live?.source_timestamp ?? assessment?.market_data_as_of) },
            { label: 'Decision ID / hash', value: `${display(liveDecision?.decision_id)} / ${display(liveDecision?.content_hash)}` },
            { label: 'Freshness', value: `${display(liveDecision?.freshness)} · AGE ${freshnessAge}` },
          ] },
          { title: 'WHY / PROOF', rows: [
            { label: 'Decision envelope', value: display(liveDecision?.decision_id) },
            { label: 'Why', value: display(liveDecision?.why) },
            { label: 'Why not', value: arrayText(explainability.why_not).join(' · ') || 'NONE REPORTED' },
            { label: 'Supporting evidence', value: completedEvidence.join(' · ') || 'NONE REPORTED' },
            { label: 'Conflicting evidence', value: proofConflictText.join(' · ') || 'NONE REPORTED' },
            { label: 'Missing evidence', value: displayList(currentEvidence.missing_inputs ?? liveDecision?.missing_evidence) },
            { label: 'Visual claims', value: liveDecision?.visual_certainty === 'UNVERIFIED' ? 'UNVERIFIED · NOT ACTIONABLE' : display(liveDecision?.visual_certainty) },
            { label: 'ARGUS / VOB / OSE lineage', value: Object.entries(exactOption?.confirmations ?? {}).map(([key, value]) => `${key.toUpperCase()} ${display(record(value).confirmed ?? record(value).status ?? record(value).posture)}`).join(' · ') || 'NOT REPORTED' },
            { label: 'Alternative scenarios', value: arrayText(explainability.alternative_scenarios).join(' · ') || 'NONE REPORTED' },
            { label: 'Discipline', value: `${display(discipline.recommendation)} · ${disciplineWarnings.join(' · ') || 'NO OBJECTIVE WARNING'}` },
            { label: 'Constitution', value: `${display(record(secondBrain.constitution).version)} · ${arrayText(explainability.constitution_refs).join(' · ') || 'NOT REPORTED'}` },
            { label: 'Journal links', value: arrayText(explainability.related_journal_links).join(' · ') || 'NONE AVAILABLE' },
            { label: 'OBSIDIAN links', value: arrayText(explainability.related_journal_links).join(' · ') || display(record(secondBrain.obsidian).status) },
            { label: 'Related historical trades', value: arrayText(explainability.related_historical_trades).join(' · ') || 'NONE ELIGIBLE' },
            { label: 'Historical evidence', value: `${display(record(historicalEvidence.calibration).state)} · N ${display(historicalStatistics.total_sample)} · PROBABILITY NOT AVAILABLE` },
            { label: 'Principle conflicts', value: proofConflicts.map((item) => display(item.explanation)).join(' · ') || 'NONE REPORTED' },
            { label: 'Snapshot hashes', value: `${display(live?.content_hash)} · ${display(liveDecision?.content_hash)}` },
          ] },
          { title: 'Knowledge source locators', rows: principleRows.length ? principleRows : [{ label: 'Knowledge', value: 'NONE AVAILABLE' }] },
        ],
      },
      {
        id: 'argus',
        title: 'Options Flow — Argus',
        eyebrow: argusProvider.exactContractLineageAvailable
          ? `${exactIdentity} · ${argusProvider.securityId}`
          : `${argusProvider.underlying} · EXACT LINEAGE NOT REPORTED`,
        status: argusState,
        headline: argusProvider.verdict,
        read: `${argusProvider.canonicalRead} · FLOW TYPE ${argusProvider.flowType}`,
        resultLabel: staleSuffix(argusVote === 'SUPPORTS CALL'
            ? `ARGUS CALL ALIGNED · ${display(argusProvider.callPressure)}`
            : argusVote === 'SUPPORTS PUT'
              ? `ARGUS PUT ALIGNED · ${display(argusProvider.putPressure)}`
              : argusVote === 'CONFLICTS' || argusVote === 'NEUTRAL'
                ? 'ARGUS MIXED'
                : 'ARGUS NOT REPORTED', argusState),
        metrics: [
          { label: 'Best stack', value: display(argusProvider.bestStackStrike) },
          { label: 'Support / resistance', value: argusProvider.supportStrike === null && argusProvider.resistanceStrike === null ? 'NOT REPORTED' : `${display(argusProvider.supportStrike)} / ${display(argusProvider.resistanceStrike)}` },
          { label: 'PCR / straddle', value: `${display(argusProvider.pcr)}${argusProvider.pcrTrend === 'RISING' ? '↑' : argusProvider.pcrTrend === 'FALLING' ? '↓' : ''} · ${compact(argusProvider.straddleState)}` },
          { label: 'Highest load', value: `${display(argusProvider.highestLoadStrike)} · ${display(argusProvider.highestLoadCe)}C / ${display(argusProvider.highestLoadPe)}P` },
          { label: `Accel @ ${display(argusProvider.fastestAccelerationStrike)}`, value: `${acceleration(argusProvider.fastestAccelerationCe)}C / ${acceleration(argusProvider.fastestAccelerationPe)}P` },
        ],
        vote: argusVote,
        freshness: ageBetween(
          tactical.source_timestamp ?? tactical.option_chain_source_timestamp,
          assessment?.generated_at,
        ),
        tone: toneFor(argusState, argusVote),
        presentationState: presentationFor(argusVote, argusState, 'PENDING'),
        stale: isStale(argusState),
        pillVariant: resolvePillVariant(argusProvider.verdict, 'argus', isStale(argusState)),
        icon: ChartNoAxesCombined,
        sections: [
          { title: 'Core flow evidence', rows: [
            { label: 'Observed contract / security', value: `${exactIdentity} / ${display(exactOption?.exact_contract.security_id)}` },
            { label: 'Directional verdict', value: argusProvider.verdict },
            { label: 'Chain CE / PE pressure', value: `${display(argusProvider.callPressure)} / ${display(argusProvider.putPressure)}` },
            { label: 'Breadth', value: argusProvider.breadth },
            { label: 'Persistence', value: argusProvider.persistence },
            { label: 'PCR / trend', value: `${display(argusProvider.pcr)} / ${argusProvider.pcrTrend}` },
            { label: 'Straddle state', value: argusProvider.straddleState },
            { label: 'CE buy / write split', value: argusProvider.ceBuyWriteSplit },
            { label: 'PE buy / write split', value: argusProvider.peBuyWriteSplit },
            { label: 'Best stack / support / resistance', value: `${display(argusProvider.bestStackStrike)} / ${display(argusProvider.supportStrike)} / ${display(argusProvider.resistanceStrike)}` },
            { label: 'Highest load', value: `${display(argusProvider.highestLoadStrike)} · CE ${display(argusProvider.highestLoadCe)} / PE ${display(argusProvider.highestLoadPe)} · ${argusProvider.highestLoadRole}` },
            { label: 'Fastest acceleration', value: `${display(argusProvider.fastestAccelerationStrike)} · CE ${acceleration(argusProvider.fastestAccelerationCe)} / PE ${acceleration(argusProvider.fastestAccelerationPe)}` },
            { label: 'Flow type', value: argusProvider.flowType },
            { label: 'Wall / magnet', value: argusProvider.wallMagnet },
            { label: 'Gamma / blast readiness', value: argusProvider.gammaBlast },
            { label: 'Exact rank / score', value: `${exactArgusValue(exactArgus.rank)} / ${exactArgusValue(exactArgus.score)}` },
            { label: 'Exact OI / IV', value: exactArgusAvailable ? `${display(exactQuote.oi)} / ${display(exactQuote.iv)}` : 'NOT REPORTED' },
            { label: 'Exact bid / ask / spread', value: exactArgusAvailable ? `${money(exactQuote.bid)} / ${money(exactQuote.ask)} / ${exactSpread === null ? 'NOT REPORTED' : `${display(exactSpread)}%`}` : 'NOT REPORTED' },
          ] },
          { title: 'Three-strike decision spine', rows: argusProvider.compactSpine.map((row) => ({
            label: row.label,
            value: `${spineMetric(row)} · ${compact(row.flowState)} · ${compact(row.structuralRole)}`,
          })) },
          { title: 'Provider output', rows: [
            { label: 'Likely direction', value: argusProvider.verdict },
            { label: 'Proposed best contract', value: argusProvider.proposedContract },
            { label: 'Trigger', value: argusProvider.trigger },
            { label: 'Invalidation', value: argusProvider.invalidation },
            { label: 'Chase risk', value: argusProvider.chaseRisk },
            { label: 'CANONICAL READ', value: argusProvider.canonicalRead },
            { label: 'WHY', value: argusProvider.canonicalWhy },
          ] },
          { title: 'Truth lineage', rows: [
            { label: 'Authority', value: 'ARGUS existing rank + canonical Upstox quote · tactical edge + canonical Upstox chain' },
            { label: 'Instrument / security ID', value: `${argusProvider.underlying} / ${argusProvider.securityId}` },
            { label: 'Expiry / timeframe', value: `${argusProvider.expiry} / ${argusProvider.chainTimeframe}` },
            { label: 'Provider event time', value: formatTime(argusProvider.sourceEventTime) },
            { label: 'Observation time', value: formatTime(argusProvider.sourceTimestamp) },
            { label: 'Timestamp semantics', value: argusProvider.timestampSemantics },
            { label: 'Snapshot ID / producer revision', value: `${argusProvider.snapshotId} / ${argusProvider.producerRevision}` },
            { label: 'Provider freshness / age', value: `${argusProvider.state} / ${ageBetween(argusProvider.sourceTimestamp, live?.generated_timestamp)}` },
            { label: 'Exact quote freshness / age', value: `${display(exactQuote.freshness_state)} / ${quoteAge}` },
            { label: 'Exact-contract lineage', value: argusProvider.exactContractLineageAvailable ? 'VERIFIED' : 'NOT REPORTED' },
          ] },
          { title: 'Seven-strike quantitative spine', rows: fullSpineRows.length ? fullSpineRows : [{ label: 'Strike spine', value: 'NOT REPORTED' }] },
        ],
      },
      {
        id: 'vob',
        title: 'Structure — VOB',
        eyebrow: 'Nearest relevant zones',
        status: vobState,
        headline: resistanceDist !== null && supportDist !== null && supportDist < resistanceDist
          ? `SUPPORT ${zone(vobSupport)} · ${display(vobSupport.distance_points)} PTS`
          : `RESISTANCE ${zone(vobResistance)} · ${display(vobResistance.distance_points)} PTS`,
        read: vobEventRead,
        resultLabel: staleSuffix(vobVote === 'SUPPORTS CALL'
            ? 'VOB CALL ALIGNED'
            : vobVote === 'SUPPORTS PUT'
              ? 'VOB PUT ALIGNED'
              : vobVote === 'NEUTRAL' || vobVote === 'CONFLICTS'
                ? 'VOB SIDEWAYS'
                : (Object.keys(vobSupport).length || Object.keys(vobResistance).length)
                  ? 'VOB STRUCTURE REPORTED'
                  : 'VOB NOT REPORTED', vobState),
        metrics: [
          { label: 'Resistance', value: `${zone(vobResistance)} · ↑${display(vobResistance.distance_points)} pts` },
          { label: 'Price', value: vobLocation },
          { label: 'Support', value: `${zone(vobSupport)} · ↓${display(vobSupport.distance_points)} pts` },
          { label: 'Resistance life', value: `${touchStrength(vobResistance.touch_count)} · ${display(vobResistance.touch_count)}× TOUCHES · ${display(vobResistance.status)}` },
          { label: 'Support life', value: `${touchStrength(vobSupport.touch_count)} · ${display(vobSupport.touch_count)}× TOUCHES · ${display(vobSupport.status)}` },
        ],
        vote: vobVote,
        freshness: ageBetween(vobSupport.source_candle_timestamp ?? vobResistance.source_candle_timestamp, live?.generated_timestamp),
        tone: toneFor(vobState, vobVote),
        presentationState: presentationFor(vobVote, vobState, 'PENDING'),
        stale: isStale(vobState),
        pillVariant: resolvePillVariant(
          resistanceDist !== null && supportDist !== null && supportDist < resistanceDist
            ? `SUPPORT ${zone(vobSupport)} · ${display(vobSupport.distance_points)} PTS`
            : `RESISTANCE ${zone(vobResistance)} · ${display(vobResistance.distance_points)} PTS`,
          'vob',
          isStale(vobState),
          vobSupport,
          vobResistance
        ),
        icon: Waves,
        sections: [
          { title: 'Nearest zones', rows: [
            { label: 'Spot', value: display(vobSpot) },
            { label: 'Support', value: zone(vobSupport) },
            { label: 'Support lifecycle / strength', value: `${display(vobSupport.status)} / ${display(vobSupport.strength_score)}` },
            { label: 'Support distance', value: `${display(vobSupport.distance_points)} pts` },
            { label: 'Resistance', value: zone(vobResistance) },
            { label: 'Resistance lifecycle / strength', value: `${display(vobResistance.status)} / ${display(vobResistance.strength_score)}` },
            { label: 'Resistance distance', value: `${display(vobResistance.distance_points)} pts` },
            { label: 'Active interaction', value: `${display(vobSupport.status)} support · ${display(vobResistance.status)} resistance` },
            { label: 'Timeframe', value: display(vobSupport.timeframe ?? vobResistance.timeframe) },
            { label: 'Thesis relevance', value: display(record(exactOption?.confirmations?.vob).confirmed) },
          ] },
          { title: 'Truth lineage', rows: [
            { label: 'Authority', value: 'Volume Order Block (VOB)' },
            { label: 'Instrument / timeframe', value: `${display(vob.symbol ?? 'NIFTY')} / ${display(vobSupport.timeframe)}` },
            { label: 'Source timestamp', value: formatTime(vobSupport.source_candle_timestamp ?? vobResistance.source_candle_timestamp) },
            { label: 'Zone IDs', value: `${display(vobSupport.zone_id)} / ${display(vobResistance.zone_id)}` },
            { label: 'Freshness', value: `${display(vobSupport.freshness)} / ${display(vobResistance.freshness)}` },
          ] },
        ],
      },
      {
        id: 'ose',
        title: 'Premium Structure — OSE',
        eyebrow: `${display(optionsStructure.symbol)} · ANCHOR ${display(optionsStructure.anchor)}`,
        status: oseState,
        headline: oseClassification,
        read: display(record(optionsStructure.structural_read).headline ?? optionsStructure.reason),
        resultLabel: staleSuffix(oseVote === 'SUPPORTS CALL'
            ? `OSE CALL ALIGNED · SSI ${display(optionsDuel.ce_score)}`
            : oseVote === 'SUPPORTS PUT'
              ? `OSE PUT ALIGNED · SSI ${display(optionsDuel.pe_score)}`
              : 'OSE MIXED', oseState),
        metrics: [
          { label: 'ATM / pair', value: `${display(optionsStructure.anchor)} · ${display(optionsCeContract.strike)} CE / ${display(optionsPeContract.strike)} PE` },
          { label: 'SSI / edge', value: `CALL ${display(optionsDuel.ce_score)} · PUT ${display(optionsDuel.pe_score)} · ${display(optionsDuel.label)}` },
          { label: `${display(optionsCeContract.strike)} CALL`, value: trendRead(optionsCeTrend) },
          { label: `${display(optionsPeContract.strike)} PUT`, value: trendRead(optionsPeTrend) },
          { label: 'ARGUS / agreement', value: `${display(optionsFlow.dominant_side)} · ${display(record(optionsFlow.edge).label ?? optionsFlow.state)} · ${display(record(record(optionsStructure.engine_agreement).CE).state)}` },
        ],
        vote: oseVote,
        freshness: quoteAge,
        tone: toneFor(oseState, oseVote),
        presentationState: presentationFor(oseVote, oseState, 'PENDING'),
        stale: isStale(oseState),
        pillVariant: resolvePillVariant(oseClassification, 'ose', isStale(oseState)),
        icon: Activity,
        sections: [
          { title: 'OSE 100-point pair context', rows: [
            { label: 'Anchor / expiry', value: `${display(optionsStructure.anchor)} / ${display(optionsStructure.expiry)}` },
            { label: 'Call contract / security ID', value: `${display(optionsCeContract.trading_symbol)} / ${display(optionsCeContract.security_id)}` },
            { label: 'Put contract / security ID', value: `${display(optionsPeContract.trading_symbol)} / ${display(optionsPeContract.security_id)}` },
            { label: 'Call SSI / band', value: `${display(optionsCeSsi.score ?? optionsDuel.ce_score)} / ${display(optionsCeSsi.band)}` },
            { label: 'Put SSI / band', value: `${display(optionsPeSsi.score ?? optionsDuel.pe_score)} / ${display(optionsPeSsi.band)}` },
            { label: 'SSI edge / classification', value: `${display(optionsDuel.label)} / ${oseClassification}` },
            { label: 'Call EMA50 / Supertrend / bar', value: trendRead(optionsCeTrend) },
            { label: 'Put EMA50 / Supertrend / bar', value: trendRead(optionsPeTrend) },
            { label: 'ARGUS live-flow side', value: `${display(optionsFlow.dominant_side)} · ${display(record(optionsFlow.edge).label ?? optionsFlow.state)}` },
            { label: 'OSE–ARGUS agreement', value: display(record(optionsStructure.engine_agreement).state ?? 'NOT REPORTED') },
          ] },
          { title: 'EXACT OPTION · PREMIUM FIRST', rows: [
            { label: 'Identity / security ID', value: `${exactIdentity} / ${display(exactOption?.exact_contract.security_id)}` },
            { label: 'Current-contract decision', value: display(exactOption?.verdict) },
            { label: 'Current suitability', value: display(exactOption?.current_contract_suitability ?? liveDecision?.current_contract_reason) },
            { label: 'Premium trend / structure', value: `${display(record(exactOption?.premium_features?.trend).state)} / ${display(record(exactOption?.premium_features?.structure).state)}` },
            { label: 'Completed candles 1m / 3m / 5m', value: `${display(exactOption?.premium_candles?.completed_1m_count)} / ${display(exactOption?.premium_candles?.completed_3m_count)} / ${display(exactOption?.premium_candles?.completed_5m_count)}` },
            { label: 'Premium trigger', value: `${display(exactOption?.premium_trigger?.predicate)} · ${money(exactOption?.premium_trigger?.level)}` },
            { label: 'Premium invalidation', value: `${display(exactOption?.premium_invalidation?.predicate)} · ${money(exactOption?.premium_invalidation?.level)}` },
            { label: 'Spread / Delta', value: `${display(exactQuote.spread_pct)}% / ${display(exactQuote.delta)}` },
            { label: 'IV / Theta / Gamma', value: `${display(exactQuote.iv)} / ${display(exactQuote.theta)} / ${display(exactQuote.gamma)}` },
            { label: 'Executable ask band / entry extension', value: exactOption?.executable_entry_band?.map(money).join('–') || 'NOT REPORTED' },
            { label: 'OSE confirmation', value: `${display(record(exactOption?.confirmations?.ose).confirmed)} · ${display(record(exactOption?.confirmations?.ose).duel)}` },
            { label: 'Underlying / ARGUS / OSE / VOB', value: Object.entries(exactOption?.confirmations ?? {}).map(([key, value]) => `${key.toUpperCase()} ${display(record(value).confirmed ?? record(value).status ?? record(value).posture)}`).join(' · ') || 'NOT REPORTED' },
            { label: 'Verified alternative', value: display(record(exactOption?.alternative_contract).trading_symbol) },
            { label: 'ARGUS → OSE dependency', value: `${display(record(exactOption?.confirmations?.argus).status)} → ${display(exactOption?.premium_features?.authority)}` },
          ] },
          { title: 'Truth lineage', rows: [
            { label: 'Authority', value: 'OPTIONS_STRUCTURE_ENGINE · SSI POLICY' },
            { label: 'Instrument / timeframe', value: `${display(optionsStructure.symbol)} / 1m+3m+5m COMPLETED CANDLES` },
            { label: 'Source timestamp', value: formatTime(optionsStructure.source_timestamp) },
            { label: 'Pair identity', value: `${display(optionsCeContract.security_id)} / ${display(optionsPeContract.security_id)} · ${display(optionsStructure.expiry)}` },
            { label: 'Freshness', value: `${display(optionsStructure.source_freshness)} · AGE ${formatAge(optionsStructure.source_age_seconds)}` },
          ] },
        ],
      },
      {
        id: 'risk',
        title: 'Risk + Discipline',
        eyebrow: 'Risk authority + second brain',
        status: riskState,
        headline: riskAvailable
          ? ['WAIT', 'REVIEW', 'COOLDOWN'].includes(disciplineAction)
            ? `DISCIPLINE ${disciplineAction} · RISK AVAILABLE`
            : noTradesToday ? 'RISK AVAILABLE · NO TRADES TODAY' : `RISK CLEAR · TODAY ${money(paper.total_daily_pnl)}`
          : display(record(risk.error).message ?? (risk.kill_switch_active === true ? risk.kill_switch_reason : 'Risk eligibility unavailable')),
        read: riskBlocked
          ? display(record(risk.error).message ?? risk.kill_switch_reason)
          : disciplineWarnings.length
            ? disciplineWarnings.join(' · ')
            : `RISK CLEAR · DISCIPLINE ${disciplineAction}`,
        resultLabel: riskBlocked
          ? 'RISK BLOCKED'
          : disciplineAction === 'COOLDOWN'
            ? 'COOLDOWN ACTIVE'
            : disciplineWarnings.length
              ? 'DISCIPLINE WARNING'
              : disciplineAction === 'WAIT' || disciplineAction === 'REVIEW'
                ? `DISCIPLINE ${disciplineAction}`
                : 'RISK CLEAR',
        metrics: [
          { label: 'Today / return', value: noTradesToday ? 'NO TRADES TODAY · RETURN NOT REPORTED' : `${money(paper.total_daily_pnl)} · RETURN NOT REPORTED` },
          { label: 'Real / open', value: noTradesToday ? 'NOT APPLICABLE · NOT APPLICABLE' : `${money(paper.realized_pnl)} / ${money(paper.unrealized_pnl)}` },
          { label: 'Trades / W–L / 60m', value: noTradesToday ? 'NO TRADES · NOT APPLICABLE · NOT REPORTED' : `${display(paper.trades_taken_today)} · NOT REPORTED · NOT REPORTED` },
          { label: 'Risk used / limit / open', value: `NOT REPORTED / ${money(riskLimits.max_daily_loss)} / NOT REPORTED` },
          { label: 'Discipline', value: disciplineAction },
        ],
        vote: riskVote,
        freshness: ageBetween(risk.last_updated, assessment?.generated_at),
        tone: toneFor(riskState, riskVote),
        presentationState: presentationFor(riskVote, riskState, riskAvailable && !disciplineWarnings.length ? 'HEALTHY' : 'PENDING'),
        stale: isStale(riskState),
        pillVariant: resolvePillVariant(
          riskAvailable
            ? ['WAIT', 'REVIEW', 'COOLDOWN'].includes(disciplineAction)
              ? `DISCIPLINE ${disciplineAction} · RISK AVAILABLE`
              : noTradesToday ? 'RISK AVAILABLE · NO TRADES TODAY' : `RISK CLEAR · TODAY ${money(paper.total_daily_pnl)}`
            : display(record(risk.error).message ?? (risk.kill_switch_active === true ? risk.kill_switch_reason : 'Risk eligibility unavailable')),
          'risk',
          isStale(riskState)
        ),
        icon: ShieldCheck,
        sections: [
          { title: 'Risk authority', rows: [
            { label: 'Risk allowed / denied / unavailable', value: riskAvailable ? 'ALLOWED' : risk.kill_switch_active === true ? 'DENIED' : 'UNAVAILABLE' },
            { label: 'Mode', value: 'PAPER' },
            { label: 'Risk / trade', value: money(riskLimits.max_risk_per_trade) },
            { label: 'Daily loss limit / usage', value: `${money(riskLimits.max_daily_loss)} / UNAVAILABLE` },
            { label: 'Open positions', value: display(paper.open_position_count) },
            { label: 'Kill switch', value: display(risk.kill_switch_state) },
            { label: 'Trades today', value: display(paper.trades_taken_today) },
            { label: 'Running / realized / unrealized P&L', value: `${money(paper.total_daily_pnl)} / ${money(paper.realized_pnl)} / ${money(paper.unrealized_pnl)}` },
            { label: 'Day return / capital denominator', value: 'NOT REPORTED / NOT REPORTED' },
            { label: 'Call / Put P&L', value: 'NOT REPORTED / NOT REPORTED' },
            { label: 'Wins / losses / win rate', value: 'NOT REPORTED / NOT REPORTED / NOT REPORTED' },
            { label: 'Average R / last result', value: 'NOT REPORTED / NOT REPORTED' },
            { label: 'Cumulative P&L series', value: 'NOT REPORTED' },
            { label: 'Risk reason', value: display(record(risk.error).message ?? risk.kill_switch_reason) },
          ] },
          { title: 'Discipline · advisory only', rows: [
            { label: 'Discipline action', value: disciplineAction },
            { label: 'Cooldown', value: display(live?.personal_oracle.cooldown_status) },
            { label: 'Duplicate thesis', value: display(live?.personal_oracle.second_brain ? warningValue('DUPLICATE') : 'UNAVAILABLE') },
            { label: 'Post-loss re-entry', value: warningValue('REENTRY') },
            { label: 'FOMO / late entry', value: warningValue('FOMO') },
            { label: 'Constitution status', value: `${display(record(secondBrain.constitution).version)} · ${display(record(secondBrain.constitution).immutable)}` },
            { label: 'Behavioral authority', value: 'ADVISORY · EXECUTION INFLUENCE ZERO' },
          ] },
          { title: 'Truth lineage', rows: [
            { label: 'Authorities', value: 'RiskAuthorizationService + Oracle Discipline Engine' },
            { label: 'Account / instrument', value: `PAPER / ${display(liveChart?.instrument.security_id)}` },
            { label: 'Source timestamps', value: `${formatTime(risk.last_updated)} / ${formatTime(live?.generated_timestamp)}` },
            { label: 'Constitution / decision hash', value: `${display(record(secondBrain.constitution).content_hash)} / ${display(liveDecision?.content_hash)}` },
            { label: 'Availability', value: `${display(risk.state_health)} / ${display(secondBrain.status)}` },
          ] },
        ],
      },
      {
        id: 'guardian',
        title: 'Position + Guardian',
        eyebrow: 'Read-only paper supervision',
        status: paperState === 'UNAVAILABLE' ? 'UNAVAILABLE' : guardianState,
        headline: livePhase5?.position_id
          ? `${display(missionRuntime.guardian?.contract)} · ${display(missionRuntime.guardian?.filled_quantity)} QTY · ${guardianState}`
          : paperState === 'UNAVAILABLE'
            ? 'PAPER MODE · POSITION STATE UNAVAILABLE · GUARDIAN STANDBY'
            : 'NO ACTIVE POSITION',
        read: livePhase5?.position_id
          ? display(livePhase5?.latest_explanation ?? missionRuntime.guardian?.reason)
          : paperState === 'UNAVAILABLE'
            ? 'POSITION STATE UNAVAILABLE'
            : 'PAPER MODE · GUARDIAN STANDBY · PROTECTION NOT REQUIRED',
        resultLabel: livePhase5?.position_id
          ? guardianVote === 'BLOCKS' ? 'PROTECTION FAILED' : `POSITION ${guardianState}`
          : paperState === 'UNAVAILABLE' ? 'POSITION UNAVAILABLE' : 'GUARDIAN STANDBY',
        metrics: [
          { label: 'Position / guardian', value: livePhase5?.position_id ? `${display(missionRuntime.guardian?.contract)} · ${guardianState}` : `NO ACTIVE POSITION · ${guardianState}` },
          { label: 'Protection / feed', value: livePhase5?.position_id ? `${display(record(livePhase5?.protection).status)} · ${display(record(livePhase5?.guardian_health).status)}` : 'NOT REQUIRED · STANDBY' },
          { label: 'Entry → live / P&L', value: livePhase5?.position_id ? `${money(record(livePhase5?.order).average_fill_price)} → ${money(missionRuntime.guardian?.last_quote)} · ${money(paper.unrealized_pnl)}` : 'NOT APPLICABLE' },
          { label: 'SL / T1 / distance', value: livePhase5?.position_id ? `${money(missionRuntime.guardian?.current_stop)} / ${money(missionRuntime.guardian?.target_1)} / NOT REPORTED` : 'NOT APPLICABLE' },
          { label: 'Current R / best / giveback', value: livePhase5?.position_id ? 'NOT REPORTED / NOT REPORTED / NOT REPORTED' : 'NOT APPLICABLE' },
          { label: 'Plan / re-entry / averaging', value: livePhase5?.position_id ? 'NOT REPORTED / NOT REPORTED / NOT REPORTED' : 'NOT APPLICABLE' },
        ],
        vote: guardianVote,
        freshness: ageBetween(missionRuntime.guardian?.last_quote_timestamp ?? paper.projection_observed_at, live?.generated_timestamp),
        tone: toneFor(paperState === 'UNAVAILABLE' ? paperState : guardianState, guardianVote),
        presentationState: livePhase5?.position_id
          ? presentationFor(guardianVote, guardianState, 'PENDING')
          : paperState === 'UNAVAILABLE' ? 'UNAVAILABLE' : 'STANDBY',
        stale: isStale(paperState) || isStale(guardianState),
        pillVariant: resolvePillVariant(
          livePhase5?.position_id
            ? `${display(missionRuntime.guardian?.contract)} · ${display(missionRuntime.guardian?.filled_quantity)} QTY · ${guardianState}`
            : paperState === 'UNAVAILABLE'
              ? 'PAPER MODE · POSITION STATE UNAVAILABLE · GUARDIAN STANDBY'
              : 'NO ACTIVE POSITION',
          'guardian',
          isStale(paperState) || isStale(guardianState)
        ),
        icon: HeartPulse,
        positionRail,
        sections: [
          { title: 'Paper position · read only', rows: [
            { label: 'Mode', value: 'PAPER' },
            { label: 'Position', value: livePhase5?.position_id ? display(livePhase5.position_id) : 'NO ACTIVE POSITION' },
            { label: 'Guardian', value: `${guardianState} · ${display(record(livePhase5?.guardian_health).status)}` },
            { label: 'Reconciliation', value: display(record(livePhase5?.guardian_health).last_error ?? (paperState === 'UNAVAILABLE' ? 'UNAVAILABLE' : 'RECONCILED')) },
            { label: 'Contract', value: display(missionRuntime.guardian?.contract) },
            { label: 'Security ID', value: display(missionRuntime.guardian?.security_id) },
            { label: 'Quantity', value: `${display(missionRuntime.guardian?.filled_quantity)} / ${display(missionRuntime.guardian?.approved_quantity)}` },
            { label: 'Fill price', value: money(record(livePhase5?.order).average_fill_price) },
            { label: 'Current executable premium', value: money(missionRuntime.guardian?.last_quote) },
            { label: 'Unrealised P&L', value: livePhase5?.position_id ? money(paper.unrealized_pnl) : 'NOT REPORTED' },
            { label: 'Quote timestamp', value: formatTime(missionRuntime.guardian?.last_quote_timestamp) },
            { label: 'Active hard stop', value: money(missionRuntime.guardian?.current_stop) },
            { label: 'Targets', value: `${money(missionRuntime.guardian?.target_1)} / ${money(missionRuntime.guardian?.target_2)}` },
            { label: 'Protection status', value: display(record(livePhase5?.protection).status) },
            { label: 'Guardian action', value: guardianState },
            { label: 'Last heartbeat', value: formatTime(record(livePhase5?.guardian_health).last_cycle_at) },
            { label: 'Management reason', value: display(livePhase5?.latest_explanation ?? missionRuntime.guardian?.reason) },
            { label: 'Stale / disconnect warning', value: display(record(livePhase5?.guardian_health).last_error) },
          ] },
          { title: 'Truth lineage', rows: [
            { label: 'Authorities', value: 'Canonical Paper Engine + Independent Guardian' },
            { label: 'Position / contract', value: `${display(livePhase5?.position_id)} / ${display(missionRuntime.guardian?.security_id)}` },
            { label: 'Source timestamp', value: formatTime(record(livePhase5?.guardian_health).last_cycle_at ?? paper.projection_observed_at) },
            { label: 'Record / event hash', value: `${display(livePhase5?.position_id)} / ${display(record(livePhase5).latest_event_hash)}` },
            { label: 'Availability', value: `${display(paper.state_health)} / ${display(record(livePhase5?.guardian_health).status)}` },
          ] },
        ],
      },
    ]
  })()

  const selectedNode = selectedId ? nodes.find((node) => node.id === selectedId) ?? null : null

  return (
    <div data-page-visible={pageVisible}>
      <CitadelPrimaryNavigation
        active="oracle"
        appearance="oracle"
        title="CITADEL OS"
        instrument={`${liveChart?.option?.trading_symbol ?? liveChart?.symbol.normalized_symbol ?? assessment?.symbol ?? 'NIFTY'} · ORACLE`}
        marketStatus={tradingViewContextStatus ?? assessment?.data_status ?? 'STATUS UNAVAILABLE'}
      />
      <header className={styles.oracleHeader}>
        <span className={styles.cornerTop} aria-hidden="true" />
        <span className={styles.cornerBottom} aria-hidden="true" />
        <div className={styles.headerIdentity}>
          <span className={styles.brandOrbit}><Orbit size={17} aria-hidden="true" /></span>
          <div><span>CITADEL ORACLE</span><small>Execution workspace</small></div>
        </div>
        <div className={styles.statusLegend} aria-label="Oracle source status legend">
          <span data-state="healthy"><i aria-hidden="true" />LIVE / HEALTHY</span>
          <span data-state="stale"><i aria-hidden="true" />STALE / NEEDS ATTENTION</span>
          <span data-state="unavailable"><i aria-hidden="true" />UNAVAILABLE</span>
        </div>
        <div className={styles.headerSafety} aria-label="ADVISORY ONLY · EXECUTION INFLUENCE ZERO">
          <span>ADVISORY ONLY</span><i aria-hidden="true" /><strong>NO ORDER SENT</strong><b>EXECUTION AUTHORITY FALSE</b>
        </div>
      </header>

      <div className={styles.runtimeStrip} data-tradingview-sync data-supported-states="LIVE STALE DETECTING LOADING_CONTEXT BUY WAIT NO_TRADE WATCHING REVALIDATING PAPER_ORDER MANAGE EXIT EXITED UNAVAILABLE AMBIGUOUS" data-frontend-performance={JSON.stringify(frontendPerformance)}>
        <span><b>TRADINGVIEW</b><strong >{tradingViewContextStatus}</strong></span>
        <span><b>ACTIVE INSTRUMENT</b><strong>{liveChart?.symbol.normalized_symbol ?? assessment?.symbol ?? 'DETECTING'}</strong></span>
        <span><b>EXACT IDENTITY</b><strong>{liveChart?.option ? `${liveChart.option.trading_symbol} · ${liveChart.option.security_id ?? 'UNMAPPED'}` : liveChart?.instrument.underlying ?? 'UNAVAILABLE'}</strong></span>
        <span><b>TYPE · TIMEFRAME</b><strong>{liveChart ? `${liveChart.instrument.route} · ${liveChart.timeframe}` : 'UNAVAILABLE'}</strong></span>
        <span><b>EXPIRY · SIDE</b><strong>{liveChart?.option ? `${liveChart.option.expiry} · ${liveChart.option.option_side}` : 'NOT APPLICABLE'}</strong></span>
        <span><b>CHART / MARKET SOURCE</b><strong >{liveChart ? `${tradingViewContextStatus} · ${formatAge(tradingViewContextAge)} OLD` : 'UNAVAILABLE'}</strong></span>
        <span><b>CONDITION · GUARDIAN</b><strong>{livePhase5 ? `${livePhase5.condition_state ?? 'NONE'} · ${livePhase5.guardian_action ?? 'IDLE'}` : 'NONE · IDLE'}</strong></span>
      </div>
      <div className={styles.strategyAuthorityStrip} aria-label="System and execution health">
        <details data-system-health>
          <summary><strong>SYSTEM / EXECUTION HEALTH</strong><span>{display(live?.health.worker_alive ? 'AVAILABLE' : 'DEGRADED')} · DIAGNOSTIC ONLY</span></summary>
          <dl>
            <div><dt>TradingView sync</dt><dd>{display(live?.sync_state)} · {display(liveChart?.freshness)}</dd></div>
            <div><dt>RAW / NORMALIZED</dt><dd>{liveChart ? `${liveChart.symbol.raw_symbol} / ${liveChart.symbol.normalized_symbol}` : 'DETECTING'}</dd></div>
            <div><dt>CHART READY / SOURCE AGE / TRANSPORT</dt><dd>{display(liveChart?.availability)} · {formatAge(oracleMeta?.freshness_age_seconds)} · {display(live?.frontend_transport?.transport)}</dd></div>
            <div><dt>PAPER ORDER / GUARDIAN</dt><dd>{display(livePhase5?.paper_order_state)} · {display(livePhase5?.guardian_action)}</dd></div>
            <div><dt>Upstox mapping/data</dt><dd>{display(liveChart?.instrument.mapping_status)} · {display(exactQuote.availability)}</dd></div>
            <div><dt>OpenAlgo diagnostic</dt><dd>{display(missionRuntime.guardian?.health ?? 'NOT CHECKED')} · ZERO ANALYSIS VOTE</dd></div>
            <div><dt>Backend / frontend</dt><dd>{display(live?.health.worker_alive)} / {display(live?.frontend_transport?.transport)}</dd></div>
            <div><dt>SSE / recovery</dt><dd>{display(live?.frontend_transport?.delivery_mode)} · {display(live?.health.backoff_active)}</dd></div>
            <div><dt>Last successful update</dt><dd>{formatTime(live?.generated_timestamp)}</dd></div>
            <div><dt>System errors</dt><dd>{display(live?.health.last_error ?? oracle.error)}</dd></div>
            <div><dt>Mission runtime</dt><dd data-workflow-stage>{display(missionRuntime.stateStatus)} · {stage}</dd></div>
            <div><dt>Frontend p95</dt><dd>RECEIPT {display(frontendPerformance.event_receipt.p95_ms)}MS · VISIBLE {display(frontendPerformance.visible_render.p95_ms)}MS</dd></div>
            <div><dt>Strategy / research registry</dt><dd><a href="/strategies">OPEN REGISTRY · {deployedInstances.length} DEPLOYED</a></dd></div>
            <div><dt>Demo fixture</dt><dd>{missionRuntime.demoTour?.status ?? 'NOT ACTIVE'} · NON-CANONICAL</dd></div>
          </dl>
        </details>
      </div>

      <section ref={graphRef} className={styles.graphShell} aria-label="Oracle execution graph" data-oracle-graph>
        <FlowMap nodes={nodes} stage={stage} selectedId={selectedId} />
        <div className={styles.graphAura} aria-hidden="true" />
        <MissionHub
          assessment={assessment}
          runtime={missionRuntime}
          oracleMeta={oracleMeta}
          nodes={nodes}
          onProof={() => setSelectedId('thesis')}
          personalSignal={personalSignal}
        />
        {nodes.map((node) => (
          <EngineNode key={node.id} node={node} selected={selectedId === node.id} onSelect={setSelectedId} />
        ))}
      </section>

      <InspectionDrawer node={selectedNode} onClose={() => setSelectedId(null)} />
      <CommandControls runtime={missionRuntime} canonicalAvailable={Boolean(assessment) && !oracle.error} />
      <PlanReadout plan={missionRuntime.plan} live={live} />
      <OracleAlertOverlay live={live} />

      <OracleFuturesVwapChart feed={futuresChart} />

      <GeminiMarketBrainSection
        argusFeed={argus}
        futuresFeed={futuresChart}
        optionBuyerFeed={optionBuyerIntelligence}
        orderFlowFeed={orderFlow}
        marketInfoFeed={marketInfo}
        sensorFeedMeta={sensorFeedMeta}
        dashboardRevision={dashboardRevision}
      />

      {vobUiMode === 'legacy' ? <VobPullbackCommand /> : <NiftyPhotonicMaster />}

      <FlowPulseStoreBridge visualFixture={flowFixture} initialLabOpen={flowLabOpen} />

      <OracleArgusPrime01C
        tactical={tactical}
        optionsStructure={optionsStructure}
        vob={vob}
        provider={argusProvider}
        marketState={argusUnderlying.market_state}
        marketClosedAt={argusUnderlying.source_event_time}
        dominance={argusData.dominance}
        participationVerdict={record(argusData.verdict).regime}
        marketSentiment={record(argusData.verdict).bias}
        marketBias={record(tactical.contract_selection).directional_bias}
        visualFixture={argus01cFixture}
      />

      <PhotonicOptionBuyerIntelligenceBottom />

      <footer className={styles.oracleFooter}>
        <span>Paper only · Live trading disabled · Broker submission disabled · OpenAlgo diagnostic only</span>
        <span>Strategy Lab · {display(labStatus.health)} · {display(labStatus.readiness)}</span>
        <span >{assessment?.reasoning ?? 'NOT REPORTED'}</span>
      </footer>

      {typeof window !== 'undefined' && window.location.search.includes('test=true') && (
        <div id="ui-test-fixture" style={{ position: 'fixed', bottom: '50px', left: '10px', zIndex: 9999, background: 'rgba(0,0,0,0.9)', padding: '10px', border: '1px solid #333' }}>
          <StatusPill variant={resolvePillVariant("NEUTRAL · TRENDING", "thesis", false)}>NEUTRAL · TRENDING</StatusPill>
          <StatusPill variant={resolvePillVariant("BALANCED", "ose", false)}>BALANCED</StatusPill>
          <StatusPill variant={resolvePillVariant("DISCIPLINE WAIT · RISK AVAILABLE", "risk", false)}>DISCIPLINE WAIT · RISK AVAILABLE</StatusPill>
          <StatusPill variant={resolvePillVariant("NO ACTIVE POSITION", "guardian", false)}>NO ACTIVE POSITION</StatusPill>
          <StatusPill variant={resolvePillVariant("NOT REPORTED", "thesis", false)}>NOT REPORTED</StatusPill>
          <StatusPill variant={resolvePillVariant("BEARISH", "thesis", false)}>BEARISH</StatusPill>
          <StatusPill variant={resolvePillVariant("CLEAR CALL ADVANTAGE", "thesis", false)}>CLEAR CALL ADVANTAGE</StatusPill>
          <StatusPill variant={resolvePillVariant("RESISTANCE 24,643.95–24,662.6 · 129.75 PTS", "vob", false, null, { status: "ACTIVE" })}>VOB_ACTIVE_RESISTANCE</StatusPill>
          <StatusPill variant={resolvePillVariant("SUPPORT 24,427.95–24,445.45 · 70.40 PTS", "vob", false, { status: "ACTIVE" }, null)}>VOB_ACTIVE_SUPPORT</StatusPill>
          <StatusPill variant={resolvePillVariant("RESISTANCE 24,643.95–24,662.6 · 129.75 PTS", "vob", true, null, { status: "ACTIVE" })}>VOB_STALE_RESISTANCE</StatusPill>
          <StatusPill variant={resolvePillVariant("SUPPORT 24,427.95–24,445.45 · 70.40 PTS", "vob", true, { status: "ACTIVE" }, null)}>VOB_STALE_SUPPORT</StatusPill>
          <StatusPill variant={resolvePillVariant("CALL", "thesis", true)}>CALL_STALE</StatusPill>
          <StatusPill variant={resolvePillVariant("PUT", "thesis", true)}>PUT_STALE</StatusPill>
          <StatusPill variant={resolvePillVariant("WAIT", "thesis", true)}>WAIT_STALE</StatusPill>
        </div>
      )}
    </div>
  )
}
