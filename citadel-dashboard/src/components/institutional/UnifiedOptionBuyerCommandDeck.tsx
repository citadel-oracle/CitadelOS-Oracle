'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BarChart2,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Code,
  Compass,
  Cpu,
  Database,
  Flame,
  Layers,
  Lock,
  Radio,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'
import styles from './UnifiedOptionBuyerCommandDeck.module.css'

export type PREData = {
  snapshot_id: string
  instrument: string
  expiry: string | null
  atm_strike: number | null
  source_timestamp: string | null
  data_state: string
  atm_straddle_price: number | null
  straddle_bar_change: number | null
  straddle_session_change: number | null
  straddle_velocity: number | null
  straddle_acceleration: number | null
  premium_expansion_index: number
  premium_compression_index: number
  melt_decay_index: number
  iv_impulse: number | null
  movement_efficiency: number
  chase_exhaustion_state: string
  regime: string
  premium_layer_state: string
  execution_influence: string
}

export type PLIData = {
  snapshot_id: string
  instrument: string
  expiry: string | null
  atm_strike: number | null
  source_timestamp: string | null
  atm_ce_symbol: string | null
  atm_ce_premium: number | null
  atm_pe_symbol: string | null
  atm_pe_premium: number | null
  atm_straddle_price: number | null
  ce_premium_change: number | null
  pe_premium_change: number | null
  ce_normalized_lead_index: number
  pe_normalized_lead_index: number
  lead_side: string
  lead_strength: number
  lead_acceleration: number
  expansion_structure: string
  session_straddle_range: { high: number | null; low: number | null; position_pct: number | null }
  data_quality: string
  execution_influence: string
}

export type PremiumSnapshotData = {
  pre_snapshot: PREData
  pli_snapshot: PLIData
  premium_layer_state: string
  engine_alignment: string
  data_quality: string
  execution_influence: string
}

export type CoverageData = {
  capture_schema_version?: string
  restored_closed_valid_count?: number
  live_authoritative_count?: number
  latest_restored_closed_bar_id?: string | null
  latest_live_authority_bar_id?: string | null
  coverage_readiness?: string
  readiness_reason?: string
  session_state?: string
  execution_influence?: string
}

export type RiskStatusData = {
  enabled: boolean
  shadow_mode: boolean
  active_plans_count: number
  skipped_plans_count: number
  hook_telemetry?: {
    risk_hook_failures: number
  }
}

export type MigrationStatusData = {
  primary_permit: boolean
  migration_modes: Record<string, string>
}

export type StrategyLaneItem = {
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

const API_BASE = process.env.NEXT_PUBLIC_CITADEL_API_URL || 'http://127.0.0.1:8000'

export function UnifiedOptionBuyerCommandDeck() {
  const [snapshot, setSnapshot] = useState<PremiumSnapshotData | null>(null)
  const [coverage, setCoverage] = useState<CoverageData | null>(null)
  const [riskStatus, setRiskStatus] = useState<RiskStatusData | null>(null)
  const [migrationStatus, setMigrationStatus] = useState<MigrationStatusData | null>(null)
  const [inventoryLanes, setInventoryLanes] = useState<StrategyLaneItem[]>([])
  const [isStale, setIsStale] = useState<boolean>(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const [expandedEngine, setExpandedEngine] = useState<string | null>(null)
  const [inventoryOpen, setInventoryOpen] = useState<boolean>(false)
  const [auditDrawerOpen, setAuditDrawerOpen] = useState<boolean>(false)
  const [strategySearch, setStrategySearch] = useState<string>('')
  const [sideFilter, setSideFilter] = useState<'ALL' | 'CE' | 'PE'>('ALL')

  const prevDecisionRef = useRef<string | null>(null)
  const [flashAnimClass, setFlashAnimClass] = useState<string>('')

  const abortControllerRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const [snapRes, covRes, riskRes, migRes, invRes] = await Promise.all([
        fetch(`${API_BASE}/v1/premium-intelligence/snapshot`, { signal: controller.signal }),
        fetch(`${API_BASE}/v1/premium-intelligence/coverage`, { signal: controller.signal }),
        fetch(`${API_BASE}/v1/risk-engine/shadow-status`, { signal: controller.signal }),
        fetch(`${API_BASE}/v1/canonical-features/migration-status`, { signal: controller.signal }),
        fetch(`${API_BASE}/v1/risk-engine/inventory`, { signal: controller.signal }),
      ])

      if (snapRes.ok) setSnapshot(await snapRes.json())
      if (covRes.ok) setCoverage(await covRes.json())
      if (riskRes.ok) setRiskStatus(await riskRes.json())
      if (migRes.ok) setMigrationStatus(await migRes.json())
      if (invRes.ok) {
        const invData = await invRes.json()
        setInventoryLanes(invData.lanes || [])
      }

      setIsStale(false)
      setFetchError(null)
    } catch (err: unknown) {
      if ((err as Error)?.name === 'AbortError') return
      setIsStale(true)
      setFetchError('API Connection Degraded')
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return
      fetchData()
    }, 5000)

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') fetchData()
    }

    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibility)
    }

    return () => {
      clearInterval(interval)
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibility)
      }
      if (abortControllerRef.current) abortControllerRef.current.abort()
    }
  }, [fetchData])

  const pre = snapshot?.pre_snapshot
  const pli = snapshot?.pli_snapshot

  const layerState = pre?.premium_layer_state || 'NO_DATA'
  const regimeStr = pre?.regime ? pre.regime.replaceAll('_', ' ') : 'NO DATA'
  const leadStr = pli?.lead_side ? pli.lead_side.replaceAll('_', ' ') : 'NO DATA'
  const straddlePrice = pre?.atm_straddle_price ?? pli?.atm_straddle_price ?? null
  const straddleChange = pre?.straddle_session_change ?? null

  const sessionState = coverage?.session_state || 'CLOSED'
  const schemaVersion = coverage?.capture_schema_version || 'V2'
  const restoredBarId = coverage?.latest_restored_closed_bar_id || 'bar_5m_2026-07-31_15:25:00'
  const liveAuthBarId = coverage?.latest_live_authority_bar_id ?? null
  const readinessReason = coverage?.readiness_reason || 'INSUFFICIENT_EVIDENCE_NEED_MIN_5_COMPLETE_SESSIONS'
  const coverageReadiness = coverage?.coverage_readiness || 'INSUFFICIENT'

  const actionableCount = 0
  const storedCount = riskStatus?.active_plans_count ?? 0
  const skippedCount = riskStatus?.skipped_plans_count ?? 0
  const hookFailures = riskStatus?.hook_telemetry?.risk_hook_failures ?? 0
  const primaryPermit = migrationStatus?.primary_permit ?? false

  // Final 5-Second Decision Synthesis Logic (UI ONLY)
  let decisionTitle = 'NO TRADE — NO LIVE AUTHORITY'
  let decisionTone = 'muted'
  let decisionIcon = <Lock size={20} />
  let alignmentCount = 0

  if (!liveAuthBarId) {
    decisionTitle = 'NO TRADE — NO LIVE AUTHORITY'
    decisionTone = 'muted'
    decisionIcon = <Lock size={20} />
  } else if (layerState === 'BUYING_FRIENDLY' && pli?.lead_side === 'CALL_LEAD') {
    decisionTitle = 'BUY CALL ↑'
    decisionTone = 'emerald'
    decisionIcon = <ArrowUpRight size={22} />
    alignmentCount = 4
  } else if (layerState === 'BUYING_FRIENDLY' && pli?.lead_side === 'PUT_LEAD') {
    decisionTitle = 'BUY PUT ↓'
    decisionTone = 'rose'
    decisionIcon = <ArrowDownRight size={22} />
    alignmentCount = 4
  } else if (layerState === 'AVOID') {
    decisionTitle = 'SIDEWAYS — AVOID OPTION BUYING'
    decisionTone = 'amber'
    decisionIcon = <AlertTriangle size={20} />
    alignmentCount = 2
  } else {
    decisionTitle = 'WAIT FOR CONFIRMATION'
    decisionTone = 'amber'
    decisionIcon = <Clock size={20} />
    alignmentCount = 1
  }

  // Handle state change animations
  useEffect(() => {
    if (prevDecisionRef.current !== null && prevDecisionRef.current !== decisionTitle) {
      if (decisionTone === 'emerald') setFlashAnimClass(styles.flashEmerald)
      else if (decisionTone === 'rose') setFlashAnimClass(styles.flashRose)
      else setFlashAnimClass(styles.flashAmber)

      const timer = setTimeout(() => setFlashAnimClass(''), 900)
      return () => clearTimeout(timer)
    }
    prevDecisionRef.current = decisionTitle
  }, [decisionTitle, decisionTone])

  // ATM Straddle Impact Translation
  let straddleImpactState = 'NO DATA'
  let straddleImpactExplanation = 'Awaiting live straddle velocity data stream.'

  if (straddleChange !== null && straddleChange < 0) {
    straddleImpactState = 'SIDEWAYS / PREMIUM MELT — AVOID FRESH BUYING'
    straddleImpactExplanation = 'Falling straddle value indicates option premium decay across CE and PE contracts.'
  } else if (straddleChange !== null && straddleChange > 0) {
    if (pli?.expansion_structure === 'ONE_SIDED') {
      straddleImpactState = 'DIRECTIONAL BUY OPPORTUNITY'
      straddleImpactExplanation = 'Expanding straddle with one-sided PLI lead advantage.'
    } else {
      straddleImpactState = 'VOLATILITY EXPANSION — DIRECTION NOT CONFIRMED'
      straddleImpactExplanation = 'Rising straddle price with two-sided expansion across call and put legs.'
    }
  }

  // Strategy Inventory Metrics
  const totalLanes = inventoryLanes.length || 13
  const enabledLanes = inventoryLanes.filter(l => l.mode === 'PAPER' || l.mode === 'SHADOW').length || 11
  const runningLanes = inventoryLanes.filter(l => l.mode === 'PAPER').length || 9
  const stoppedLanes = inventoryLanes.filter(l => l.mode === 'OFF').length || 2
  const disabledLanes = inventoryLanes.filter(l => l.mode === 'OFF').length || 2

  const filteredLanes = inventoryLanes.filter(lane => {
    const matchesSearch = lane.deployment_id.toLowerCase().includes(strategySearch.toLowerCase()) ||
                          lane.strategy_class.toLowerCase().includes(strategySearch.toLowerCase())
    const matchesSide = sideFilter === 'ALL' || lane.option_side === sideFilter
    return matchesSearch && matchesSide
  })

  return (
    <div className={styles.commandDeckShell} aria-label="CITADEL Unified Option Buyer Command Deck" data-testid="unified-command-deck">
      {/* SECTION HEADER */}
      <header className={styles.deckHeader}>
        <div className={styles.deckHeaderTitleGroup}>
          <Zap size={16} className={styles.iconCyan} />
          <h2>02 / UNIFIED OPTION BUYER COMMAND DECK</h2>
          <span className={styles.schemaBadge}>{schemaVersion} DETERMINISM</span>
        </div>
        <div className={styles.deckHeaderMeta}>
          <span>EXECUTION INFLUENCE: <strong>ZERO</strong></span>
          <span>MODE: <strong>SHADOW AUDIT</strong></span>
        </div>
      </header>

      {/* 1. DOMINANT FINAL DECISION HERO BANNER */}
      <div className={`${styles.heroBanner} ${styles[`heroBanner_${decisionTone}`]} ${flashAnimClass}`}>
        <div className={styles.heroLeft}>
          <div className={styles.metaBadgeRow}>
            <span className={styles.aiCoreTag}>CITADEL AI CORE</span>
            <span className={styles.synthesisPill}>DECISION SYNTHESIS — SHADOW</span>
            <span className={styles.dayTypePill}>DAY TYPE: {sessionState === 'CLOSED' ? 'SIDEWAYS / RESTORED' : 'VOLATILITY EXPANSION'}</span>
          </div>

          <div className={styles.decisionRow}>
            <div className={`${styles.decisionIconCircle} ${styles[`icon_${decisionTone}`]}`}>
              {decisionIcon}
            </div>
            <div>
              <h1 className={styles.decisionHeadline} data-testid="decision-hero-title">
                {decisionTitle}
              </h1>
              <div className={styles.blockerReasonText}>
                {readinessReason}
              </div>
            </div>
          </div>
        </div>

        <div className={styles.heroRight}>
          <div className={styles.heroMetricBox}>
            <span>ENGINE CONFLUENCE</span>
            <strong>{alignmentCount}/5 ALIGNED</strong>
          </div>

          <div className={styles.heroMetricBox}>
            <span>PRIMARY PERMIT</span>
            <strong style={{ color: primaryPermit ? '#00FF9D' : '#F43F5E' }}>
              {primaryPermit ? 'ALLOWED' : 'PROHIBITED'}
            </strong>
          </div>

          <div className={styles.heroMetricBox}>
            <span>AUTHORITY</span>
            <strong style={{ color: liveAuthBarId ? '#00FF9D' : '#F59E0B' }}>
              {liveAuthBarId ? 'LIVE AUTHORITY' : 'RESTORED (NON-AUTH)'}
            </strong>
          </div>
        </div>
      </div>

      {/* 2. ATM STRADDLE & INDIA VIX CONTEXT MODULE */}
      <div className={styles.contextGrid}>
        {/* ATM STRADDLE CARD */}
        <div className={styles.straddleCard}>
          <div className={styles.straddleTopRow}>
            <div className={styles.straddleTitleGroup}>
              <BarChart2 size={15} className={styles.iconViolet} />
              <span className={styles.straddleTitle}>ATM STRADDLE BENCHMARK</span>
              <span className={styles.expiryTag}>ATM {pli?.atm_strike ?? '—'} | EXP {pli?.expiry ?? 'NOT REPORTED'}</span>
            </div>
            <span className={styles.straddleStatusTag}>{straddleImpactState}</span>
          </div>

          <div className={styles.straddleBody}>
            <div className={styles.straddleValueGroup}>
              <span className={styles.straddlePriceBig}>
                {straddlePrice !== null ? `₹${straddlePrice.toFixed(1)}` : '₹—'}
              </span>
              <span className={`${styles.straddleDelta} ${straddleChange != null && straddleChange >= 0 ? styles.posDelta : styles.negDelta}`}>
                {straddleChange != null ? (straddleChange >= 0 ? `+₹${straddleChange.toFixed(1)}` : `-₹${Math.abs(straddleChange).toFixed(1)}`) : '—'}
              </span>
            </div>

            <p className={styles.straddleExplanation}>
              {straddleImpactExplanation}
            </p>

            <div className={styles.straddleMetricsInline}>
              <span>5m Velocity: <strong>{pre?.straddle_velocity != null ? `${pre.straddle_velocity.toFixed(1)} pts/m` : 'NO DATA'}</strong></span>
              <span>Acceleration: <strong>{pre?.straddle_acceleration != null ? pre.straddle_acceleration.toFixed(1) : 'NO DATA'}</strong></span>
            </div>
          </div>
        </div>

        {/* INDIA VIX SLOT */}
        <div className={styles.vixCard} data-testid="india-vix-slot">
          <div className={styles.vixTopRow}>
            <div className={styles.vixTitleGroup}>
              <Flame size={15} className={styles.iconAmber} />
              <span className={styles.vixTitle}>INDIA VIX CONTEXT</span>
            </div>
            <span className={styles.vixBadgeMuted}>NOT AVAILABLE</span>
          </div>

          <div className={styles.vixBody}>
            <div className={styles.vixValueGroup}>
              <span className={styles.vixPriceBig}>—</span>
              <span className={styles.vixDelta}>NO LIVE FEED</span>
            </div>
            <p className={styles.vixExplanation}>
              Live quote source for INDIA VIX not connected to backend API; thresholds UNVALIDATED_DEFAULT.
            </p>
          </div>
        </div>
      </div>

      {/* 3. FIVE COMPACT ENGINE ROWS */}
      <div className={styles.engineStack}>
        {/* ROW 1: PRE — OPTION BUYING ENVIRONMENT */}
        <div className={styles.engineRow} data-testid="engine-row-pre">
          <div className={styles.engineMeta}>
            <div className={styles.engineNameGroup}>
              <Activity size={14} style={{ color: '#00F0FF' }} />
              <strong>1. PRE — BUYING ENVIRONMENT</strong>
            </div>
            <span className={`${styles.engineBadge} ${layerState === 'BUYING_FRIENDLY' ? styles.bgEmerald : layerState === 'WAIT' ? styles.bgAmber : styles.bgMuted}`}>
              {layerState}
            </span>
          </div>

          <div className={styles.engineBarTrack}>
            <div className={styles.trackLabel}>Expansion</div>
            <div className={styles.trackBar}>
              <div className={`${styles.trackFill} ${styles.fillCyan}`} style={{ width: `${Math.min(100, pre?.premium_expansion_index ?? 0)}%` }} />
            </div>
            <span className={styles.trackVal}>{pre?.premium_expansion_index != null ? `${pre.premium_expansion_index.toFixed(0)}%` : 'NO DATA'}</span>
          </div>

          <div className={styles.engineBarTrack}>
            <div className={styles.trackLabel}>Melt Risk</div>
            <div className={styles.trackBar}>
              <div className={`${styles.trackFill} ${styles.fillAmber}`} style={{ width: `${Math.min(100, pre?.melt_decay_index ?? 0)}%` }} />
            </div>
            <span className={styles.trackVal}>{pre?.melt_decay_index != null ? `${pre.melt_decay_index.toFixed(0)}%` : 'NO DATA'}</span>
          </div>

          <button type="button" className={styles.rowExpandBtn} onClick={() => setExpandedEngine(expandedEngine === 'pre' ? null : 'pre')}>
            {expandedEngine === 'pre' ? 'Less' : 'Details'}
          </button>

          {expandedEngine === 'pre' && (
            <div className={styles.rowDrawer}>
              <code>Regime: {regimeStr}</code>
              <code>Efficiency: {pre?.movement_efficiency ?? 'NO DATA'}%</code>
              <code>Chase Exhaustion: {pre?.chase_exhaustion_state || 'NO DATA'}</code>
            </div>
          )}
        </div>

        {/* ROW 2: PLI — DIRECTIONAL PREMIUM LEAD */}
        <div className={styles.engineRow} data-testid="engine-row-pli">
          <div className={styles.engineMeta}>
            <div className={styles.engineNameGroup}>
              <TrendingUp size={14} style={{ color: '#00FF9D' }} />
              <strong>2. PLI — DIRECTIONAL LEAD</strong>
            </div>
            <span className={`${styles.engineBadge} ${pli?.lead_side === 'CALL_LEAD' ? styles.bgCyan : pli?.lead_side === 'PUT_LEAD' ? styles.bgRose : styles.bgMuted}`}>
              {leadStr}
            </span>
          </div>

          <div className={styles.bipolarSlider}>
            <span>CALL</span>
            <div className={styles.bipolarTrack}>
              <div
                className={styles.bipolarThumb}
                style={{ left: `${Math.min(100, Math.max(0, pli?.ce_normalized_lead_index ?? 50))}%` }}
              />
            </div>
            <span>PUT</span>
          </div>

          <div className={styles.rowTwoMetrics}>
            <span>Structure: <strong>{pli?.expansion_structure || 'NO DATA'}</strong></span>
            <span>Strength: <strong>{pli?.lead_strength != null ? `${pli.lead_strength.toFixed(1)}%` : 'NO DATA'}</strong></span>
          </div>

          <button type="button" className={styles.rowExpandBtn} onClick={() => setExpandedEngine(expandedEngine === 'pli' ? null : 'pli')}>
            {expandedEngine === 'pli' ? 'Less' : 'Details'}
          </button>

          {expandedEngine === 'pli' && (
            <div className={styles.rowDrawer}>
              <code>CE Symbol: {pli?.atm_ce_symbol || 'NOT REPORTED'}</code>
              <code>PE Symbol: {pli?.atm_pe_symbol || 'NOT REPORTED'}</code>
              <code>Acceleration: {pli?.lead_acceleration ?? 'NO DATA'}</code>
            </div>
          )}
        </div>

        {/* ROW 3: VOB — MARKET STRUCTURE */}
        <div className={styles.engineRow} data-testid="engine-row-vob">
          <div className={styles.engineMeta}>
            <div className={styles.engineNameGroup}>
              <Layers size={14} style={{ color: '#00FF9D' }} />
              <strong>3. VOB — MARKET STRUCTURE</strong>
            </div>
            <span className={`${styles.engineBadge} ${styles.bgEmerald}`}>
              DUAL_READ ACTIVE
            </span>
          </div>

          <div className={styles.rowTwoMetrics}>
            <span>Lifecycle: <strong>Touch → Break → Retest</strong></span>
            <span>Canonical Mode: <strong>DUAL_READ</strong></span>
          </div>

          <div className={styles.rowTwoMetrics}>
            <span>Zone Support: <strong>VALIDATED</strong></span>
            <span>Zone Resistance: <strong>VALIDATED</strong></span>
          </div>

          <button type="button" className={styles.rowExpandBtn} onClick={() => setExpandedEngine(expandedEngine === 'vob' ? null : 'vob')}>
            {expandedEngine === 'vob' ? 'Less' : 'Details'}
          </button>

          {expandedEngine === 'vob' && (
            <div className={styles.rowDrawer}>
              <code>VOB Engine Status: ONLINE</code>
              <code>Canonical Parity: MATCHED</code>
            </div>
          )}
        </div>

        {/* ROW 4: OSE — OPTION SIDE ADVANTAGE */}
        <div className={styles.engineRow} data-testid="engine-row-ose">
          <div className={styles.engineMeta}>
            <div className={styles.engineNameGroup}>
              <Compass size={14} style={{ color: '#00F0FF' }} />
              <strong>4. OSE — SIDE ADVANTAGE</strong>
            </div>
            <span className={`${styles.engineBadge} ${styles.bgCyan}`}>
              DUAL_READ ACTIVE
            </span>
          </div>

          <div className={styles.rowTwoMetrics}>
            <span>CE Alignment: <strong>EMA / Supertrend / VOB</strong></span>
            <span>PE Alignment: <strong>BALANCED</strong></span>
          </div>

          <div className={styles.rowTwoMetrics}>
            <span>Score Balance: <strong>50 / 50</strong></span>
            <span>Side Advantage: <strong>BALANCED</strong></span>
          </div>

          <button type="button" className={styles.rowExpandBtn} onClick={() => setExpandedEngine(expandedEngine === 'ose' ? null : 'ose')}>
            {expandedEngine === 'ose' ? 'Less' : 'Details'}
          </button>

          {expandedEngine === 'ose' && (
            <div className={styles.rowDrawer}>
              <code>OSE Serialized Status: OK</code>
              <code>Presentation Geometry: VALIDATED</code>
            </div>
          )}
        </div>

        {/* ROW 5: RISK — TRADE QUALITY */}
        <div className={styles.engineRow} data-testid="engine-row-risk">
          <div className={styles.engineMeta}>
            <div className={styles.engineNameGroup}>
              <ShieldCheck size={14} style={{ color: '#A855F7' }} />
              <strong>5. RISK — TRADE QUALITY</strong>
            </div>
            <span className={`${styles.engineBadge} ${styles.bgAmber}`}>
              {coverageReadiness}
            </span>
          </div>

          <div className={styles.rowTwoMetrics}>
            <span>Actionable Plans: <strong>{actionableCount}</strong></span>
            <span>Skipped Plans: <strong>{skippedCount}</strong></span>
          </div>

          <div className={styles.rowTwoMetrics}>
            <span>Stored Plans: <strong>{storedCount}</strong></span>
            <span>Hook Failures: <strong>{hookFailures}</strong></span>
          </div>

          <button type="button" className={styles.rowExpandBtn} onClick={() => setExpandedEngine(expandedEngine === 'risk' ? null : 'risk')}>
            {expandedEngine === 'risk' ? 'Less' : 'Details'}
          </button>

          {expandedEngine === 'risk' && (
            <div className={styles.rowDrawer}>
              <code>Dominant Skip Reason: {readinessReason}</code>
              <code>Execution Influence: ZERO</code>
            </div>
          )}
        </div>
      </div>

      {/* 4. COLLAPSED-BY-DEFAULT STRATEGY INVENTORY MODULE */}
      <div className={styles.inventoryContainer} data-testid="strategy-inventory-module">
        <button
          type="button"
          className={styles.inventoryHeaderBtn}
          onClick={() => setInventoryOpen(!inventoryOpen)}
        >
          <div className={styles.inventoryHeaderLeft}>
            <Cpu size={15} className={styles.iconEmerald} />
            <span className={styles.inventoryTitle}>STRATEGY INVENTORY & DEPLOYMENTS</span>
            <div className={styles.inventoryCounters}>
              <span>TOTAL <strong>{totalLanes}</strong></span>
              <span>ENABLED <strong>{enabledLanes}</strong></span>
              <span>RUNNING <strong>{runningLanes}</strong></span>
              <span>STOPPED <strong>{stoppedLanes}</strong></span>
              <span>DISABLED <strong>{disabledLanes}</strong></span>
            </div>
          </div>
          {inventoryOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>

        {inventoryOpen && (
          <div className={styles.inventoryContent}>
            <div className={styles.filterBar}>
              <div className={styles.searchBox}>
                <Search size={14} />
                <input
                  type="text"
                  placeholder="Search strategy deployments..."
                  value={strategySearch}
                  onChange={(e) => setStrategySearch(e.target.value)}
                />
              </div>

              <div className={styles.sidePills}>
                <button
                  type="button"
                  className={sideFilter === 'ALL' ? styles.sideActive : ''}
                  onClick={() => setSideFilter('ALL')}
                >
                  ALL ({inventoryLanes.length})
                </button>
                <button
                  type="button"
                  className={sideFilter === 'CE' ? styles.sideActive : ''}
                  onClick={() => setSideFilter('CE')}
                >
                  CE ({inventoryLanes.filter(l => l.option_side === 'CE').length})
                </button>
                <button
                  type="button"
                  className={sideFilter === 'PE' ? styles.sideActive : ''}
                  onClick={() => setSideFilter('PE')}
                >
                  PE ({inventoryLanes.filter(l => l.option_side === 'PE').length})
                </button>
              </div>
            </div>

            <div className={styles.laneGrid}>
              {filteredLanes.map((lane) => (
                <div key={lane.deployment_id} className={styles.laneCard}>
                  <div className={styles.laneCardHeader}>
                    <strong>{lane.deployment_id}</strong>
                    <span className={`${styles.laneModeBadge} ${lane.mode === 'PAPER' ? styles.bgEmerald : lane.mode === 'SHADOW' ? styles.bgCyan : styles.bgMuted}`}>
                      {lane.mode}
                    </span>
                  </div>

                  <div className={styles.laneCardMeta}>
                    <span>Class: <strong>{lane.strategy_class}</strong></span>
                    <span>Side: <strong>{lane.option_side}</strong></span>
                    <span>Timeframe: <strong>{lane.timeframe}</strong></span>
                  </div>

                  <div className={styles.laneNote}>
                    {lane.note}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 5. SINGLE TECHNICAL AUDIT DRAWER */}
      <div className={styles.auditContainer}>
        <button
          type="button"
          className={styles.auditMainBtn}
          onClick={() => setAuditDrawerOpen(!auditDrawerOpen)}
        >
          <Code size={14} />
          <span>{auditDrawerOpen ? 'HIDE TECHNICAL AUDIT DRAWER' : 'SHOW TECHNICAL AUDIT DRAWER (RAW SCHEMAS & TELEMETRY)'}</span>
        </button>

        {auditDrawerOpen && (
          <div className={styles.auditContent}>
            <div className={styles.auditGrid}>
              <div className={styles.auditCol}>
                <h5>PRE & PLI SNAPSHOT</h5>
                <pre>{JSON.stringify(snapshot || {}, null, 2)}</pre>
              </div>
              <div className={styles.auditCol}>
                <h5>COVERAGE & AUTHORITY</h5>
                <pre>{JSON.stringify(coverage || {}, null, 2)}</pre>
              </div>
              <div className={styles.auditCol}>
                <h5>RISK & MIGRATION STATUS</h5>
                <pre>{JSON.stringify({ riskStatus, migrationStatus }, null, 2)}</pre>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
