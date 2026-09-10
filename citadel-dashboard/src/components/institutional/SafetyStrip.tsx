import type { HTMLAttributes } from 'react'
import { Badge, Card, Row, Typography } from '@/design-system'

export interface CanonicalStatusData {
  overall_status: 'OFFLINE' | 'CONNECTING' | 'BLOCKED' | 'DEGRADED' | 'HEALTHY'
  operating_mode: 'PRE_MARKET' | 'MARKET_OPEN' | 'MARKET_CLOSED' | 'POST_MARKET'
  safety_status: 'SAFE' | 'BLOCKED' | 'UNSAFE' | 'UNKNOWN'
  freshness: 'FRESH' | 'AGING' | 'STALE' | 'UNAVAILABLE'
  system: {
    state: string
    reason_code: string
    plain_language_reason: string
    source_timestamp: string | null
    calculated_at: string
    age_seconds: number | null
    action_required: boolean
    recommended_action: string | null
  }
  safety: {
    state: string
    reason_code: string
    plain_language_reason: string
    source_timestamp: string | null
    calculated_at: string
    age_seconds: number | null
    action_required: boolean
    recommended_action: string | null
  }
  deployments: Array<{
    deployment_id: string
    lifecycle: 'DISABLED' | 'ENABLED' | 'STARTING' | 'RUNNING' | 'PAUSED' | 'STOPPED' | 'ERROR'
    readiness: 'READY' | 'NOT_READY' | 'BLOCKED'
    connectivity: 'CONNECTED' | 'STALE' | 'DISCONNECTED'
    freshness: string
    cursor_lag: number | null
    backlog_count: number | null
    active_interruption: string | null
    reason_code: string
    plain_language_reason: string
    source_timestamp: string | null
    calculated_at: string
    age_seconds: number | null
    action_required: boolean
    recommended_action: string | null
  }>
  deployment_counts: {
    total: number
    healthy_running: number
    stopped: number
    error: number
  }
  wording_summary: string
  action_required_issues: Array<{
    priority: number
    scope: string
    code: string
    reason: string
    recommended_action: string
  }>
  generated_at: string
}

export interface SafetyStripProps extends HTMLAttributes<HTMLDivElement> {
  canonicalStatus?: CanonicalStatusData | null
  paperOnly?: boolean
  liveTradingEnabled?: boolean | null
  brokerSubmission?: boolean | null
}

export function formatAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return 'Unavailable'
  if (seconds < 60) return `Updated ${Math.round(seconds)}s ago`
  const minutes = Math.floor(seconds / 60)
  return `Stale by ${minutes}m`
}

export function SafetyStrip({
  canonicalStatus,
  paperOnly = true,
  liveTradingEnabled = false,
  brokerSubmission = false,
  className,
  ...props
}: SafetyStripProps) {
  if (!canonicalStatus) return null

  const { safety_status, operating_mode, freshness, safety, system } = canonicalStatus

  const safetyTone =
    safety_status === 'SAFE' ? 'positive' : safety_status === 'BLOCKED' || safety_status === 'UNSAFE' ? 'negative' : 'neutral'

  const modeTone =
    operating_mode === 'MARKET_OPEN' ? 'positive' : operating_mode === 'PRE_MARKET' ? 'brand' : 'neutral'

  const freshnessTone =
    freshness === 'FRESH' ? 'positive' : freshness === 'AGING' ? 'warning' : freshness === 'STALE' ? 'warning' : 'neutral'

  return (
    <div
      {...props}
      className={className}
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 'var(--cds-space-1, 8px)',
        padding: 'var(--cds-space-1, 8px) var(--cds-space-2, 16px)',
        marginBottom: '12px',
        border: '1px solid var(--cds-color-border-subtle, rgba(255, 255, 255, 0.1))',
        borderRadius: 'var(--cds-radius-md, 6px)',
        background: 'rgba(15, 23, 42, 0.8)',
        backdropFilter: 'blur(8px)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <Badge tone={safetyTone} dot>
          SAFETY: {safety_status}
        </Badge>
        <Badge tone={paperOnly ? 'brand' : 'warning'}>
          {paperOnly ? 'PAPER ONLY' : 'REAL MARKET'}
        </Badge>
        <Badge tone={liveTradingEnabled ? 'negative' : 'neutral'}>
          LIVE TRADING: {liveTradingEnabled ? 'ENABLED' : 'DISABLED'}
        </Badge>
        <Badge tone={brokerSubmission ? 'negative' : 'neutral'}>
          BROKER SUBMISSION: {brokerSubmission ? 'ENABLED' : 'DISABLED'}
        </Badge>
        <Badge tone={modeTone}>
          MODE: {operating_mode.replace('_', ' ')}
        </Badge>
        <Badge tone={freshnessTone}>
          {formatAge(system.age_seconds)}
        </Badge>
      </div>
      <div style={{ fontSize: '0.825rem', color: 'var(--cds-color-text-subtle, #94a3b8)', fontFamily: 'var(--cds-font-sans, sans-serif)' }}>
        {safety.plain_language_reason || system.plain_language_reason}
      </div>
    </div>
  )
}

export function ActionRequiredPanel({ issues }: { issues?: CanonicalStatusData['action_required_issues'] }) {
  if (!issues || issues.length === 0) return null

  return (
    <Card
      style={{
        marginBottom: '16px',
        border: '1px solid var(--cds-color-warning, #f59e0b)',
        background: 'rgba(245, 158, 11, 0.08)',
        padding: '12px 16px',
      }}
    >
      <Typography variant="sectionTitle" style={{ color: 'var(--cds-color-warning, #f59e0b)', marginBottom: '8px' }}>
        ACTION REQUIRED ({issues.length})
      </Typography>
      <div style={{ display: 'grid', gap: '8px' }}>
        {issues.map((issue, idx) => (
          <Row key={idx} justify="between" align="center" style={{ fontSize: '0.85rem' }}>
            <span style={{ fontWeight: 600, color: '#fcd34d' }}>
              [{issue.scope}] {issue.reason}
            </span>
            <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>
              Action: {issue.recommended_action}
            </span>
          </Row>
        ))}
      </div>
    </Card>
  )
}
