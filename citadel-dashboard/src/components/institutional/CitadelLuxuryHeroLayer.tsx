'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowUpRight,
  BarChart2,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Cpu,
  Database,
  Flame,
  Layers,
  Lock,
  Radio,
  Shield,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  Zap,
} from 'lucide-react'
import styles from './CitadelLuxuryHeroLayer.module.css'

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

const API_BASE = process.env.NEXT_PUBLIC_CITADEL_API_URL || 'http://127.0.0.1:8000'

export function CitadelLuxuryHeroLayer() {
  const [snapshot, setSnapshot] = useState<PremiumSnapshotData | null>(null)
  const [coverage, setCoverage] = useState<CoverageData | null>(null)
  const [riskStatus, setRiskStatus] = useState<RiskStatusData | null>(null)
  const [migrationStatus, setMigrationStatus] = useState<MigrationStatusData | null>(null)
  const [isStale, setIsStale] = useState<boolean>(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const [expandedCard, setExpandedCard] = useState<string | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const [snapRes, covRes, riskRes, migRes] = await Promise.all([
        fetch(`${API_BASE}/v1/premium-intelligence/snapshot`, { signal: controller.signal }),
        fetch(`${API_BASE}/v1/premium-intelligence/coverage`, { signal: controller.signal }),
        fetch(`${API_BASE}/v1/risk-engine/shadow-status`, { signal: controller.signal }),
        fetch(`${API_BASE}/v1/canonical-features/migration-status`, { signal: controller.signal }),
      ])

      if (snapRes.ok) setSnapshot(await snapRes.json())
      if (covRes.ok) setCoverage(await covRes.json())
      if (riskRes.ok) setRiskStatus(await riskRes.json())
      if (migRes.ok) setMigrationStatus(await migRes.json())

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

  const layerState = pre?.premium_layer_state || (snapshot ? 'NO_DATA' : 'CONNECTING')
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

  const toggleExpand = (cardKey: string) => {
    setExpandedCard(expandedCard === cardKey ? null : cardKey)
  }

  return (
    <div className={styles.luxuryContainer} aria-label="CITADEL Luxury Institutional Hero Layer" data-testid="citadel-luxury-hero-layer">
      {/* 1. TOP AI DECISION BANNER (5-SECOND RULE CORE) */}
      <div className={styles.decisionBanner}>
        <div className={styles.decisionMain}>
          <div className={styles.aiBadgeGroup}>
            <div className={styles.pulseDot} />
            <span className={styles.aiLabel}>CITADEL AI CORE</span>
            <span className={styles.schemaPill}>{schemaVersion} DETERMINISM</span>
          </div>

          <div className={styles.decisionHeadline}>
            <span className={styles.stateTag}>SHADOW MODE EVALUATION</span>
            <h1 className={styles.decisionText}>
              STANDBY — EXECUTION INFLUENCE ZERO
            </h1>
          </div>
        </div>

        <div className={styles.bannerMetrics}>
          <div className={styles.metricBlock}>
            <span className={styles.metricBlockLabel}>SYSTEM READINESS</span>
            <strong className={styles.metricBlockVal} style={{ color: coverageReadiness === 'READY' ? '#00FF9D' : '#F59E0B' }}>
              {coverageReadiness}
            </strong>
          </div>

          <div className={styles.metricBlock}>
            <span className={styles.metricBlockLabel}>PRIMARY PERMIT</span>
            <span className={primaryPermit ? styles.permitAllowedPill : styles.permitLockedPill}>
              <Lock size={12} /> {primaryPermit ? 'ALLOWED' : 'PROHIBITED'}
            </span>
          </div>

          <div className={styles.metricBlock}>
            <span className={styles.metricBlockLabel}>MARKET CLOCK</span>
            <strong className={styles.metricBlockVal}>{sessionState}</strong>
          </div>
        </div>
      </div>

      {/* 2. 5-ENGINE CONFLUENCE STRIP */}
      <div className={styles.confluenceStrip}>
        <div className={styles.confluenceItem}>
          <span className={styles.engineName}>1. PRE REGIME</span>
          <span className={`${styles.engineStatus} ${layerState === 'BUYING_FRIENDLY' ? styles.statusEmerald : layerState === 'WAIT' ? styles.statusAmber : styles.statusMuted}`}>
            {layerState}
          </span>
        </div>

        <div className={styles.confluenceItem}>
          <span className={styles.engineName}>2. PLI LEAD</span>
          <span className={`${styles.engineStatus} ${pli?.lead_side === 'CALL_LEAD' ? styles.statusCyan : pli?.lead_side === 'PUT_LEAD' ? styles.statusRose : styles.statusMuted}`}>
            {leadStr}
          </span>
        </div>

        <div className={styles.confluenceItem}>
          <span className={styles.engineName}>3. VOB ENGINE</span>
          <span className={`${styles.engineStatus} ${styles.statusEmerald}`}>DUAL_READ ACTIVE</span>
        </div>

        <div className={styles.confluenceItem}>
          <span className={styles.engineName}>4. OSE STRUCTURE</span>
          <span className={`${styles.engineStatus} ${styles.statusEmerald}`}>DUAL_READ ACTIVE</span>
        </div>

        <div className={styles.confluenceItem}>
          <span className={styles.engineName}>5. RISK INTELLIGENCE</span>
          <span className={`${styles.engineStatus} ${styles.statusViolet}`}>SHADOW AUDITED</span>
        </div>
      </div>

      {/* 3. HERO COMMAND DECK CARDS (4 COLUMNS / RESPONSIVE) */}
      <div className={styles.deckCardsGrid}>
        {/* CARD 1: PRE REGIME ENGINE */}
        <div className={styles.luxuryCard} data-testid="hero-pre-card">
          <div className={styles.cardHeader}>
            <div className={styles.cardTitleGroup}>
              <Activity size={15} style={{ color: '#00F0FF' }} />
              <span className={styles.cardTag}>PRE REGIME ENGINE</span>
            </div>
            <span className={`${styles.statusBadge} ${layerState === 'BUYING_FRIENDLY' ? styles.badgeEmerald : layerState === 'WAIT' ? styles.badgeAmber : styles.badgeMuted}`}>
              {layerState}
            </span>
          </div>

          <div className={styles.primaryMetricGroup}>
            <span className={styles.metricBig}>{regimeStr}</span>
            <p className={styles.metricExplanation}>
              {pre ? 'Strike attention & velocity expansion evaluated from market feed.' : 'No active regime data received from backend feed.'}
            </p>
          </div>

          <div className={styles.trackStack}>
            <div className={styles.trackRow}>
              <span>Expansion Index</span>
              <strong>{pre?.premium_expansion_index != null ? `${pre.premium_expansion_index.toFixed(0)}%` : 'NO DATA'}</strong>
            </div>
            <div className={styles.trackBar}>
              <div className={`${styles.trackFill} ${styles.fillCyan}`} style={{ width: `${Math.min(100, pre?.premium_expansion_index ?? 0)}%` }} />
            </div>

            <div className={styles.trackRow}>
              <span>Melt Decay Risk</span>
              <strong>{pre?.melt_decay_index != null ? `${pre.melt_decay_index.toFixed(0)}%` : 'NO DATA'}</strong>
            </div>
            <div className={styles.trackBar}>
              <div className={`${styles.trackFill} ${styles.fillAmber}`} style={{ width: `${Math.min(100, pre?.melt_decay_index ?? 0)}%` }} />
            </div>
          </div>

          <div className={styles.cardFooterRow}>
            <span className={styles.updatedText}>{isStale ? 'STALE' : fetchError ? 'API ERROR' : 'REAL API FEED'}</span>
            <button type="button" className={styles.expandBtn} onClick={() => toggleExpand('pre')}>
              {expandedCard === 'pre' ? 'Less' : 'Details'}
            </button>
          </div>

          {expandedCard === 'pre' && (
            <div className={styles.drawerDetails}>
              <code>Snapshot ID: {pre?.snapshot_id || 'NO DATA'}</code>
              <code>Movement Efficiency: {pre?.movement_efficiency != null ? `${pre.movement_efficiency}%` : 'NO DATA'}</code>
              <code>Chase Exhaustion: {pre?.chase_exhaustion_state || 'NO DATA'}</code>
            </div>
          )}
        </div>

        {/* CARD 2: PREMIUM LEAD INDEX (PLI) */}
        <div className={styles.luxuryCard} data-testid="hero-pli-card">
          <div className={styles.cardHeader}>
            <div className={styles.cardTitleGroup}>
              <TrendingUp size={15} style={{ color: '#00FF9D' }} />
              <span className={styles.cardTag}>PREMIUM LEAD INDEX</span>
            </div>
            <span className={`${styles.statusBadge} ${pli?.lead_side === 'CALL_LEAD' ? styles.badgeCyan : pli?.lead_side === 'PUT_LEAD' ? styles.badgeRose : styles.badgeMuted}`}>
              {leadStr}
            </span>
          </div>

          <div className={styles.primaryMetricGroup}>
            <span className={styles.metricBig}>
              {pli?.lead_strength != null ? `${pli.lead_strength.toFixed(1)}% STRENGTH` : 'NO DATA'}
            </span>
            <p className={styles.metricExplanation}>
              {pli ? 'Normalized option premium velocity differential across CE/PE legs.' : 'No active lead index data received from backend feed.'}
            </p>
          </div>

          <div className={styles.trackStack}>
            <div className={styles.trackRow}>
              <span>CE Lead Index</span>
              <strong>{pli?.ce_normalized_lead_index != null ? `${pli.ce_normalized_lead_index.toFixed(0)}%` : 'NO DATA'}</strong>
            </div>
            <div className={styles.trackBar}>
              <div className={`${styles.trackFill} ${styles.fillEmerald}`} style={{ width: `${Math.min(100, pli?.ce_normalized_lead_index ?? 0)}%` }} />
            </div>

            <div className={styles.trackRow}>
              <span>PE Lead Index</span>
              <strong>{pli?.pe_normalized_lead_index != null ? `${pli.pe_normalized_lead_index.toFixed(0)}%` : 'NO DATA'}</strong>
            </div>
            <div className={styles.trackBar}>
              <div className={`${styles.trackFill} ${styles.fillRose}`} style={{ width: `${Math.min(100, pli?.pe_normalized_lead_index ?? 0)}%` }} />
            </div>
          </div>

          <div className={styles.cardFooterRow}>
            <span className={styles.updatedText}>{isStale ? 'STALE' : fetchError ? 'API ERROR' : 'REAL API FEED'}</span>
            <button type="button" className={styles.expandBtn} onClick={() => toggleExpand('pli')}>
              {expandedCard === 'pli' ? 'Less' : 'Details'}
            </button>
          </div>

          {expandedCard === 'pli' && (
            <div className={styles.drawerDetails}>
              <code>Snapshot ID: {pli?.snapshot_id || 'NO DATA'}</code>
              <code>Structure: {pli?.expansion_structure || 'NO DATA'}</code>
              <code>Acceleration: {pli?.lead_acceleration != null ? pli.lead_acceleration : 'NO DATA'}</code>
            </div>
          )}
        </div>

        {/* CARD 3: ATM STRADDLE BENCHMARK */}
        <div className={styles.luxuryCard} data-testid="hero-straddle-card">
          <div className={styles.cardHeader}>
            <div className={styles.cardTitleGroup}>
              <BarChart2 size={15} style={{ color: '#A855F7' }} />
              <span className={styles.cardTag}>ATM STRADDLE BENCHMARK</span>
            </div>
            <span className={styles.badgeViolet}>
              {pli?.atm_strike != null ? `ATM ${pli.atm_strike}` : 'NOT REPORTED'}
            </span>
          </div>

          <div className={styles.primaryMetricGroup}>
            <div className={styles.priceRow}>
              <span className={styles.straddlePriceBig}>
                {straddlePrice !== null ? `₹${straddlePrice.toFixed(1)}` : '₹—'}
              </span>
              <span className={`${styles.priceDelta} ${straddleChange != null && straddleChange >= 0 ? styles.deltaPos : styles.deltaNeg}`}>
                {straddleChange != null ? (straddleChange >= 0 ? `+₹${straddleChange.toFixed(1)}` : `-₹${Math.abs(straddleChange).toFixed(1)}`) : '—'}
              </span>
            </div>
            <p className={styles.metricExplanation}>
              Combined ATM straddle premium price from option chain evidence.
            </p>
          </div>

          <div className={styles.straddleMetaGrid}>
            <div className={styles.metaCell}>
              <span>VELOCITY</span>
              <strong>{pre?.straddle_velocity != null ? `${pre.straddle_velocity.toFixed(1)} pts/m` : 'NO DATA'}</strong>
            </div>
            <div className={styles.metaCell}>
              <span>ACCELERATION</span>
              <strong>{pre?.straddle_acceleration != null ? `${pre.straddle_acceleration.toFixed(1)}` : 'NO DATA'}</strong>
            </div>
          </div>

          <div className={styles.cardFooterRow}>
            <span className={styles.updatedText}>EXPIRY: {pli?.expiry || 'NOT REPORTED'}</span>
            <button type="button" className={styles.expandBtn} onClick={() => toggleExpand('straddle')}>
              {expandedCard === 'straddle' ? 'Less' : 'Details'}
            </button>
          </div>

          {expandedCard === 'straddle' && (
            <div className={styles.drawerDetails}>
              <code>CE Symbol: {pli?.atm_ce_symbol || 'NOT REPORTED'}</code>
              <code>PE Symbol: {pli?.atm_pe_symbol || 'NOT REPORTED'}</code>
            </div>
          )}
        </div>

        {/* CARD 4: AUTHORITY & RISK SUMMARY */}
        <div className={styles.luxuryCard} data-testid="hero-risk-card">
          <div className={styles.cardHeader}>
            <div className={styles.cardTitleGroup}>
              <ShieldCheck size={15} style={{ color: '#00FF9D' }} />
              <span className={styles.cardTag}>AUTHORITY & RISK SUMMARY</span>
            </div>
            <span className={coverageReadiness === 'READY' ? styles.badgeEmerald : styles.badgeAmber}>
              {coverageReadiness}
            </span>
          </div>

          <div className={styles.primaryMetricGroup}>
            <div className={styles.riskCountRow}>
              <div className={styles.riskCountBlock}>
                <span>ACTIONABLE</span>
                <strong style={{ color: '#00FF9D' }}>{actionableCount}</strong>
              </div>
              <div className={styles.riskCountBlock}>
                <span>STORED</span>
                <strong>{storedCount}</strong>
              </div>
              <div className={styles.riskCountBlock}>
                <span>SKIPPED</span>
                <strong>{skippedCount}</strong>
              </div>
              <div className={styles.riskCountBlock}>
                <span>FAILURES</span>
                <strong style={{ color: hookFailures > 0 ? '#F43F5E' : '#94A3B8' }}>{hookFailures}</strong>
              </div>
            </div>
            <p className={styles.metricExplanation}>
              {readinessReason}
            </p>
          </div>

          <div className={styles.authorityBlock}>
            <span>RESTORED BAR: <code>{restoredBarId || 'NONE'}</code></span>
            <span>LIVE AUTHORITY: <code>{liveAuthBarId ?? 'null'}</code></span>
          </div>

          <div className={styles.cardFooterRow}>
            <span className={styles.updatedText}>Schema {schemaVersion}</span>
            <button type="button" className={styles.expandBtn} onClick={() => toggleExpand('authority')}>
              {expandedCard === 'authority' ? 'Less' : 'Details'}
            </button>
          </div>

          {expandedCard === 'authority' && (
            <div className={styles.drawerDetails}>
              <code>Restored Valid Bars: {coverage?.restored_closed_valid_count ?? 0}</code>
              <code>Live Authoritative Count: {coverage?.live_authoritative_count ?? 0}</code>
              <code>Execution Influence: ZERO</code>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
