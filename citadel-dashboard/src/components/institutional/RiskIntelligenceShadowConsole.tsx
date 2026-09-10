'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Code,
  Compass,
  Cpu,
  Database,
  Eye,
  Filter,
  Layers,
  Lock,
  RefreshCw,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Zap,
} from 'lucide-react'
import styles from './RiskIntelligenceShadowConsole.module.css'

export type ShadowStatusData = {
  enabled: boolean
  shadow_mode: boolean
  execution_influence: string
  active_plans_count: number
  skipped_plans_count: number
  max_plans_retention: number
  deployment_flags: Record<string, boolean>
  total_deployment_lanes: number
  enabled_lanes: string[]
  hook_telemetry?: {
    risk_hook_failures: number
    last_failure_at: string | null
    last_failure_deployment: string | null
    last_failure_type: string | null
    last_failure_message: string | null
    failure_log_tail: Array<{ at: string; deployment_id: string; type: string; message: string }>
  }
  timestamp: string
}

export type RiskPlanItem = {
  plan_id: string
  strategy_id: string
  deployment_id: string
  instrument: string
  option_symbol: string | null
  option_context?: {
    underlying_price: number | null
    underlying_structural_invalidation: number | null
    option_symbol: string | null
    option_type: string | null
    option_strike: number | null
    option_expiry: string | null
    option_premium_entry: number | null
    option_premium_stop: number | null
    option_premium_target: number | null
    option_lot_size: number | null
    translation_method?: string
    translation_confidence?: string
  } | null
  side: string
  entry_price: number
  structural_invalidation: number | null
  effective_stop: number
  maximum_risk_cap: number
  position_size: number
  target_ladder: Array<{ target_price: number; exit_ratio: number; description: string }>
  is_skipped: boolean
  skip_reason: string
  skip_details: string
  provenance: {
    shadow_mode: boolean
    execution_influence: string
    deployment_id: string
    bar_timestamp?: string | null
    evaluated_at?: string | null
    candle_id?: string | null
    candidate_status?: string
    suppression_reason?: string | null
    actionable?: boolean
    would_skip_if_enforced?: string[] | null
  }
}

export type DeploymentLaneItem = {
  deployment_id: string
  strategy_class: string
  option_side: string
  timeframe: string
  underlying: string
  mode: string
  premium_domain: boolean
  risk_engine_enabled: boolean
  note: string
}

export type ThresholdItem = {
  name: string
  value: number | null
  governance: 'LOCKED_STRATEGY_RULE' | 'UNVALIDATED_DEFAULT' | 'DISABLED' | string
  unit: string
  source: string
  calibration_note: string
}

export type MigrationStatusData = {
  primary_permit: boolean
  migration_modes: Record<string, string>
  safety: {
    legacy_authoritative: boolean
    canonical_primary_allowed: boolean
    execution_influence: string
  }
}

export type RiskIntelligenceShadowConsoleProps = {
  baseUrl?: string
  refreshIntervalMs?: number
}

const API_BASE = process.env.NEXT_PUBLIC_CITADEL_API_URL || 'http://127.0.0.1:8000'

function formatAgeSeconds(timestampStr?: string | null): string {
  if (!timestampStr) return '—'
  const ts = new Date(timestampStr).getTime()
  if (Number.isNaN(ts)) return '—'
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  return `${Math.floor(diffSec / 3600)}h ago`
}

export function RiskIntelligenceShadowConsole({
  baseUrl = API_BASE,
  refreshIntervalMs = 5000,
}: RiskIntelligenceShadowConsoleProps) {
  const [shadowStatus, setShadowStatus] = useState<ShadowStatusData | null>(null)
  const [plans, setPlans] = useState<RiskPlanItem[]>([])
  const [inventory, setInventory] = useState<DeploymentLaneItem[]>([])
  const [thresholds, setThresholds] = useState<ThresholdItem[]>([])
  const [migrationStatus, setMigrationStatus] = useState<MigrationStatusData | null>(null)

  const [loading, setLoading] = useState<boolean>(true)
  const [isStale, setIsStale] = useState<boolean>(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const [filter, setFilter] = useState<'ALL' | 'ACTIONABLE' | 'SKIPPED' | 'SUPPRESSED' | 'LANES' | 'THRESHOLDS'>('ALL')
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false)

  const [flashReady, setFlashReady] = useState<boolean>(false)
  const [lastStateChangeTime, setLastStateChangeTime] = useState<string | null>(null)
  const prevActionableRef = useRef<boolean | null>(null)
  const prevLatestPlanIdRef = useRef<string | null>(null)

  const abortControllerRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const [statusRes, plansRes, invRes, threshRes, migRes] = await Promise.all([
        fetch(`${baseUrl}/v1/risk-engine/shadow-status`, { signal: controller.signal }),
        fetch(`${baseUrl}/v1/risk-engine/plans`, { signal: controller.signal }),
        fetch(`${baseUrl}/v1/risk-engine/inventory`, { signal: controller.signal }),
        fetch(`${baseUrl}/v1/risk-engine/thresholds`, { signal: controller.signal }),
        fetch(`${baseUrl}/v1/canonical-features/migration-status`, { signal: controller.signal }),
      ])

      if (statusRes.ok) {
        const data = await statusRes.json()
        setShadowStatus(data)
      }
      if (plansRes.ok) {
        const data = await plansRes.json()
        const fetchedPlans: RiskPlanItem[] = Array.isArray(data) ? data : data.plans || []
        setPlans(fetchedPlans)
      }
      if (invRes.ok) {
        const data = await invRes.json()
        setInventory(data.lanes || [])
      }
      if (threshRes.ok) {
        const data = await threshRes.json()
        setThresholds(data.thresholds || [])
      }
      if (migRes.ok) {
        const data = await migRes.json()
        setMigrationStatus(data)
      }

      setLoading(false)
      setIsStale(false)
      setFetchError(null)
    } catch (err: unknown) {
      if ((err as Error)?.name === 'AbortError') return
      setIsStale(true)
      setFetchError('API Connection Degraded')
      setLoading(false)
    }
  }, [baseUrl])

  useEffect(() => {
    fetchData()

    const interval = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return
      fetchData()
    }, refreshIntervalMs)

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') fetchData()
    }

    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange)
    }

    return () => {
      clearInterval(interval)
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibilityChange)
      }
      if (abortControllerRef.current) abortControllerRef.current.abort()
    }
  }, [fetchData, refreshIntervalMs])

  const latestPlan = plans.length > 0 ? plans[plans.length - 1] : null
  const latestIsActionable = Boolean(
    latestPlan && !latestPlan.is_skipped && latestPlan.provenance?.actionable !== false
  )

  useEffect(() => {
    const latestPlanId = latestPlan?.plan_id || null
    if (
      (prevLatestPlanIdRef.current !== null && prevLatestPlanIdRef.current !== latestPlanId) ||
      (prevActionableRef.current !== null && prevActionableRef.current !== latestIsActionable)
    ) {
      setFlashReady(true)
      setLastStateChangeTime(new Date().toLocaleTimeString())
      const timer = setTimeout(() => setFlashReady(false), 1200)
      return () => clearTimeout(timer)
    }
    prevLatestPlanIdRef.current = latestPlanId
    prevActionableRef.current = latestIsActionable
  }, [latestPlan, latestIsActionable])

  const actionableCount = plans.filter(
    (p) => !p.is_skipped && p.provenance?.actionable !== false
  ).length

  const skippedCount = shadowStatus?.skipped_plans_count ?? plans.filter((p) => p.is_skipped).length
  const storedCount = shadowStatus?.active_plans_count ?? plans.length
  const suppressedCount = plans.filter((p) => p.provenance?.candidate_status === 'SUPPRESSED').length
  const hookFailures = shadowStatus?.hook_telemetry?.risk_hook_failures ?? 0

  const primaryPermit = migrationStatus?.primary_permit ?? false
  const canonicalModes = migrationStatus?.migration_modes || {}

  const filteredPlans = plans.filter((plan) => {
    if (filter === 'ACTIONABLE') return !plan.is_skipped && plan.provenance?.actionable !== false
    if (filter === 'SKIPPED') return plan.is_skipped
    if (filter === 'SUPPRESSED') return plan.provenance?.candidate_status === 'SUPPRESSED'
    return true
  })

  return (
    <div
      className={styles.consoleCard}
      aria-label="Risk Intelligence Shadow Console"
      data-testid="risk-intelligence-shadow-console"
    >
      {/* CONSOLE HEADER */}
      <header className={styles.consoleHeader}>
        <div className={styles.headerTitleGroup}>
          <div className={styles.shieldBadge}>
            <ShieldCheck size={20} className={styles.shieldIcon} />
          </div>
          <div>
            <div className={styles.eyebrowRow}>
              <span className={styles.eyebrowTag}>02 / RISK INTELLIGENCE</span>
              <span className={styles.shadowModeTag}>SHADOW ENGINE</span>
            </div>
            <h2 className={styles.consoleTitle}>SHADOW EXECUTION CONSOLE</h2>
          </div>
        </div>

        {/* TOP KPI COUNTER STRIP */}
        <div className={styles.kpiStrip}>
          <div className={`${styles.kpiItem} ${actionableCount > 0 ? styles.kpiActive : ''}`}>
            <span>ACTIONABLE</span>
            <strong data-testid="risk-actionable-val">{actionableCount}</strong>
          </div>
          <div className={styles.kpiItem}>
            <span>STORED</span>
            <strong data-testid="risk-stored-val">{storedCount}</strong>
          </div>
          <div className={styles.kpiItem}>
            <span>SKIPPED</span>
            <strong data-testid="risk-skipped-val">{skippedCount}</strong>
          </div>
          <div className={styles.kpiItem}>
            <span>SUPPRESSED</span>
            <strong data-testid="risk-suppressed-val">{suppressedCount}</strong>
          </div>
          <div className={`${styles.kpiItem} ${hookFailures > 0 ? styles.kpiError : ''}`}>
            <span>HOOK FAILURES</span>
            <strong data-testid="risk-failures-val">{hookFailures}</strong>
          </div>
        </div>
      </header>

      {/* SHADOW MODE BANNER */}
      <div className={styles.shadowBanner}>
        <div className={styles.bannerInfo}>
          <Shield size={16} style={{ color: '#00F0FF' }} />
          <span>SHADOW MODE ACTIVE — PLANS AUDITED IN PARALLEL WITHOUT BROKER SUBMISSION</span>
        </div>
        <div className={styles.bannerControls}>
          <span className={styles.dualReadTag}>CANONICAL: DUAL READ</span>
          <span className={styles.zeroInfluenceTag}>EXECUTION INFLUENCE: ZERO</span>
        </div>
      </div>

      {/* DOMINANT STATUS / LATEST CANDIDATE HERO */}
      <div className={`${styles.heroStatusBox} ${flashReady ? styles.flashHighlight : ''}`}>
        <div className={styles.statusMetaRow}>
          <div className={styles.statusLabelGroup}>
            <Compass size={16} className={styles.compassIcon} />
            <span>LATEST AUDITED CANDIDATE EVALUATION</span>
          </div>
          <div className={styles.statusBadgeGroup}>
            {latestPlan ? (
              latestIsActionable ? (
                <span className={styles.badgeReady} data-testid="risk-status-ready">
                  RISK PLAN READY
                </span>
              ) : latestPlan.is_skipped ? (
                <span className={styles.badgeSkipped} data-testid="risk-status-skipped">
                  SKIPPED — {latestPlan.skip_reason}
                </span>
              ) : (
                <span className={styles.badgeSuppressed} data-testid="risk-status-suppressed">
                  SUPPRESSED
                </span>
              )
            ) : (
              <span className={styles.badgeNoData} data-testid="risk-status-offline">
                OFFLINE BOOTSTRAP — ZERO ACTIONABLE PLANS
              </span>
            )}
          </div>
        </div>

        {latestPlan ? (
          <div className={styles.latestPlanGrid}>
            <div className={styles.planCol}>
              <span className={styles.planColLabel}>DEPLOYMENT ID</span>
              <strong className={styles.monoVal}>{latestPlan.deployment_id}</strong>
            </div>
            <div className={styles.planCol}>
              <span className={styles.planColLabel}>SIDE & PRICE</span>
              <strong className={styles.monoVal}>
                {latestPlan.side} @ ₹{latestPlan.entry_price.toFixed(1)}
              </strong>
            </div>
            <div className={styles.planCol}>
              <span className={styles.planColLabel}>EFFECTIVE STOP</span>
              <strong className={styles.monoVal}>
                {latestPlan.effective_stop ? `₹${latestPlan.effective_stop.toFixed(1)}` : '—'}
              </strong>
            </div>
            <div className={styles.planCol}>
              <span className={styles.planColLabel}>EVALUATED AT</span>
              <span className={styles.monoVal}>
                {formatAgeSeconds(latestPlan.provenance?.evaluated_at)}
              </span>
            </div>
          </div>
        ) : (
          <div className={styles.noPlanReason}>
            <AlertCircle size={15} style={{ color: '#94A3B8' }} />
            <span>
              NO ACTIONABLE RISK PLAN PRESENT. PRE/PLI EVIDENCE ACCUMULATING FOR LIVE MARKET SESSIONS.
            </span>
          </div>
        )}
      </div>

      {/* FILTER CONTROLS & TAB NAVIGATION */}
      <div className={styles.filterBar}>
        <div className={styles.tabGroup}>
          <button
            type="button"
            className={`${styles.tabBtn} ${filter === 'ALL' ? styles.tabActive : ''}`}
            onClick={() => setFilter('ALL')}
          >
            ALL ({plans.length})
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${filter === 'ACTIONABLE' ? styles.tabActive : ''}`}
            onClick={() => setFilter('ACTIONABLE')}
          >
            ACTIONABLE ({actionableCount})
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${filter === 'SKIPPED' ? styles.tabActive : ''}`}
            onClick={() => setFilter('SKIPPED')}
          >
            SKIPPED ({skippedCount})
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${filter === 'SUPPRESSED' ? styles.tabActive : ''}`}
            onClick={() => setFilter('SUPPRESSED')}
          >
            SUPPRESSED ({suppressedCount})
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${filter === 'LANES' ? styles.tabActive : ''}`}
            onClick={() => setFilter('LANES')}
          >
            LANES ({inventory.length})
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${filter === 'THRESHOLDS' ? styles.tabActive : ''}`}
            onClick={() => setFilter('THRESHOLDS')}
          >
            THRESHOLDS ({thresholds.length})
          </button>
        </div>

        <button
          type="button"
          className={styles.auditDrawerBtn}
          onClick={() => setDrawerOpen(!drawerOpen)}
        >
          <Code size={14} />
          <span>{drawerOpen ? 'HIDE LOGS' : 'VIEW RAW LOGS'}</span>
        </button>
      </div>

      {/* TAB CONTENT AREA */}
      <div className={styles.contentBody}>
        {filter === 'LANES' ? (
          <div className={styles.tableWrapper}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th>DEPLOYMENT ID</th>
                  <th>STRATEGY</th>
                  <th>SIDE</th>
                  <th>TIMEFRAME</th>
                  <th>RISK ENGINE</th>
                  <th>STATUS</th>
                </tr>
              </thead>
              <tbody>
                {inventory.map((lane) => (
                  <tr key={lane.deployment_id}>
                    <td><code>{lane.deployment_id}</code></td>
                    <td>{lane.strategy_class}</td>
                    <td><span className={lane.option_side === 'CE' ? styles.tagCe : styles.tagPe}>{lane.option_side}</span></td>
                    <td>{lane.timeframe}</td>
                    <td>{lane.risk_engine_enabled ? <span className={styles.txtGreen}>ENABLED</span> : 'DISABLED'}</td>
                    <td><span className={styles.txtMuted}>{lane.note}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : filter === 'THRESHOLDS' ? (
          <div className={styles.tableWrapper}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th>THRESHOLD RULE</th>
                  <th>VALUE</th>
                  <th>GOVERNANCE STATE</th>
                  <th>SOURCE</th>
                </tr>
              </thead>
              <tbody>
                {thresholds.map((t) => (
                  <tr key={t.name}>
                    <td><strong>{t.name}</strong></td>
                    <td><code>{t.value !== null ? `${t.value} ${t.unit}` : '—'}</code></td>
                    <td>
                      <span className={t.governance === 'LOCKED_STRATEGY_RULE' ? styles.govLocked : styles.govUnvalidated}>
                        {t.governance}
                      </span>
                    </td>
                    <td><small>{t.source}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className={styles.plansList}>
            {filteredPlans.length === 0 ? (
              <div className={styles.emptyPlans}>
                <Database size={18} style={{ color: '#64748B' }} />
                <span>NO RISK PLANS MATCH CURRENT FILTER ({filter})</span>
              </div>
            ) : (
              filteredPlans.map((plan) => {
                const isAct = !plan.is_skipped && plan.provenance?.actionable !== false
                return (
                  <div
                    key={plan.plan_id}
                    className={`${styles.planCard} ${isAct ? styles.planCardActionable : styles.planCardSkipped}`}
                  >
                    <div className={styles.planHeader}>
                      <div className={styles.planTitleGroup}>
                        <code>{plan.deployment_id}</code>
                        <span className={styles.sideBadge}>{plan.side}</span>
                        <span className={styles.symbolBadge}>{plan.option_symbol || plan.instrument}</span>
                      </div>
                      <span className={isAct ? styles.actBadge : styles.skipBadge}>
                        {isAct ? 'ACTIONABLE' : plan.is_skipped ? `SKIPPED: ${plan.skip_reason}` : 'SUPPRESSED'}
                      </span>
                    </div>

                    <div className={styles.planDetailsGrid}>
                      <div><span>Entry Price:</span> <strong>₹{plan.entry_price.toFixed(1)}</strong></div>
                      <div><span>Effective Stop:</span> <strong>₹{plan.effective_stop ? plan.effective_stop.toFixed(1) : '—'}</strong></div>
                      <div><span>Max Risk Cap:</span> <strong>₹{plan.maximum_risk_cap.toFixed(0)}</strong></div>
                      <div><span>Position Size:</span> <strong>{plan.position_size} qty</strong></div>
                    </div>

                    {plan.skip_details && (
                      <div className={styles.skipDetailRow}>
                        <small>REASON DETAILS: {plan.skip_details}</small>
                      </div>
                    )}
                  </div>
                )
              })
            )}
          </div>
        )}
      </div>

      {/* RAW TELEMETRY DRAWER */}
      {drawerOpen && (
        <div className={styles.rawLogDrawer}>
          <div className={styles.drawerHeader}>
            <span>RAW RISK ENGINE & HOOK TELEMETRY</span>
            <small>Updated {new Date().toLocaleTimeString()}</small>
          </div>
          <div className={styles.drawerGrid}>
            <div className={styles.drawerCol}>
              <h4>SHADOW ENGINE STATUS</h4>
              <pre>{JSON.stringify(shadowStatus || {}, null, 2)}</pre>
            </div>
            <div className={styles.drawerCol}>
              <h4>HOOK FAILURES LOG TAIL</h4>
              <pre>{JSON.stringify(shadowStatus?.hook_telemetry || {}, null, 2)}</pre>
            </div>
            <div className={styles.drawerCol}>
              <h4>CANONICAL MIGRATION STATE</h4>
              <pre>{JSON.stringify(migrationStatus || {}, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}

      {/* FOOTER */}
      <footer className={styles.consoleFooter}>
        <span>PRIMARY PERMIT: <strong style={{ color: primaryPermit ? '#00FF9D' : '#F43F5E' }}>{String(primaryPermit).toUpperCase()}</strong></span>
        <span>MODES: OSE ({canonicalModes.OSE || 'DUAL_READ'}), VOB ({canonicalModes.VOB || 'DUAL_READ'})</span>
        <span>DATA AGING: {formatAgeSeconds(shadowStatus?.timestamp)}</span>
      </footer>
    </div>
  )
}
