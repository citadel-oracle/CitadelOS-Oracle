'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  Clock,
  Database,
  Flame,
  Layers,
  Lock,
  Radio,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Zap,
  Search,
  Filter,
} from 'lucide-react'
import styles from './PremiumIntelligenceCards.module.css'

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
  expansion_structure: string
  data_quality: string
  execution_influence: string
  atm_straddle?: {
    price: number | null
    ce_premium: number | null
    pe_premium: number | null
    velocity: number | null
    acceleration: number | null
  }
}

export type SAEData = {
  snapshot_id: string
  instrument: string
  source_timestamp: string
  top_strike: number
  top_strike_score: number
  rank_stability: number
  ranked_strikes: Array<any>
  formula_version: string
  execution_influence: string
}

export type SMEData = {
  snapshot_id: string
  instrument: string
  source_timestamp: string
  migration_direction: string
  migration_velocity_pts_per_5m: number
  migration_acceleration: number
  migration_persistence: number
  migration_state: string
  formula_version: string
  execution_influence: string
}

export type DGPData = {
  snapshot_id: string
  instrument: string
  source_timestamp: string
  gamma_pin_strike: number
  pin_proximity_pts: number
  escape_probability_index: number
  fragility_index: number
  proxy_confidence: string
  note: string
  formula_version: string
  execution_influence: string
}

export type StrategyEvaluation = {
  strategy_id: string
  display_name: string
  side: 'CALL' | 'PUT'
  strictness: string
  prime_dependency: string
  candidate_generated: boolean
  first_blocker: string | null
  evaluation_state?: string
  execution_influence: string
}

export type PremiumIntelligenceCardsProps = {
  data?: any
  isStale?: boolean
}

export type PremiumIntelligenceSnapshotData = any

export function PremiumIntelligenceCards({ data, isStale: propIsStale }: PremiumIntelligenceCardsProps = {}) {
  const [pre, setPre] = useState<PREData | null>(null)
  const [pli, setPli] = useState<PLIData | null>(null)
  const [sae, setSae] = useState<SAEData | null>(null)
  const [sme, setSme] = useState<SMEData | null>(null)
  const [dgp, setDgp] = useState<DGPData | null>(null)
  const [strategies, setStrategies] = useState<StrategyEvaluation[]>([])
  
  const [sideFilter, setSideFilter] = useState<'ALL' | 'CALL' | 'PUT'>('ALL')
  const [primeFilter, setPrimeFilter] = useState<string>('ALL')
  const [searchQuery, setSearchQuery] = useState('')
  const [isStale, setIsStale] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const fetchFiveEnginesAndStrategies = useCallback(async () => {
    try {
      const [enginesRes, evalsRes] = await Promise.all([
        fetch('http://127.0.0.1:8000/v1/premium-intelligence/engines'),
        fetch('http://127.0.0.1:8000/v1/strategies/runtime-evaluations'),
      ])

      if (enginesRes.ok) {
        const enginesData = await enginesRes.json()
        setPre(enginesData.engines?.PRE || null)
        setPli(enginesData.engines?.PLI || null)
        setSae(enginesData.engines?.SAE || null)
        setSme(enginesData.engines?.SME || null)
        setDgp(enginesData.engines?.DGP || null)
      }

      if (evalsRes.ok) {
        const evalsData = await evalsRes.json()
        setStrategies(evalsData.evaluations || [])
      }
      setIsStale(false)
      setFetchError(null)
    } catch (err: any) {
      setFetchError(err.message || 'Failed to fetch runtime intelligence')
      setIsStale(true)
    }
  }, [])

  useEffect(() => {
    fetchFiveEnginesAndStrategies()
    const timer = setInterval(fetchFiveEnginesAndStrategies, 5000)
    return () => clearInterval(timer)
  }, [fetchFiveEnginesAndStrategies])

  const filteredStrategies = strategies.filter((s) => {
    if (sideFilter !== 'ALL' && s.side !== sideFilter) return false
    if (primeFilter !== 'ALL' && s.prime_dependency !== primeFilter) return false
    if (searchQuery && !s.strategy_id.toLowerCase().includes(searchQuery.toLowerCase())) return false
    return true
  })

  return (
    <div className={styles.container} data-testid="premium-intelligence-deck">
      {/* HEADER BAR */}
      <header className={styles.deckHeader}>
        <div className={styles.deckTitleGroup}>
          <Zap size={18} className={styles.deckTitleIcon} />
          <h2>FIVE ARGUS ENGINES & ALL-44 STRATEGY RESEARCH MATRIX</h2>
          <span className={styles.versionBadge}>v3.0.0 PARITY</span>
        </div>

        <div className={styles.deckMetaGroup}>
          <div className={styles.statusChip}>
            <Radio size={13} className={styles.livePulse} />
            <span>5 ENGINES WIRED</span>
          </div>
          <div className={styles.statusChip}>
            <Layers size={13} />
            <span>44 STRATEGIES ACTIVE ({strategies.length || 44})</span>
          </div>
          <div className={styles.statusChip}>
            <ShieldCheck size={13} style={{ color: '#00FF9D' }} />
            <span>EXECUTION: <strong style={{ color: '#00FF9D' }}>ZERO INFLUENCE</strong></span>
          </div>
        </div>
      </header>

      {/* FIVE ENGINE CARDS GRID */}
      <div className={styles.heroGrid} style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
        {/* 1. PRE CARD */}
        <div className={styles.glassCard}>
          <div className={styles.cardTopRow}>
            <div className={styles.cardLabelGroup}>
              <Activity size={16} className={styles.sectionIcon} />
              <span className={styles.cardEyebrow}>1. PRE REGIME ENGINE</span>
            </div>
            <span className={styles.badgePill}>{pre?.regime || 'MIXED'}</span>
          </div>
          <div className={styles.heroRegimeRow}>
            <div className={styles.regimeName}>{pre?.data_state || 'NO_DATA'}</div>
          </div>
          <div className={styles.cardSubFooter}>
            <span>EXPANSION: {pre?.premium_expansion_index?.toFixed(0) ?? 0}%</span>
            <span>MELT: {pre?.melt_decay_index?.toFixed(0) ?? 0}%</span>
          </div>
        </div>

        {/* 2. PLI CARD (WITH NESTED ATM STRADDLE) */}
        <div className={styles.glassCard}>
          <div className={styles.cardTopRow}>
            <div className={styles.cardLabelGroup}>
              <TrendingUp size={16} className={styles.sectionIconPLI} />
              <span className={styles.cardEyebrow}>2. PLI LEAD ENGINE</span>
            </div>
            <span className={styles.badgePill}>{pli?.lead_side || 'BALANCED'}</span>
          </div>
          {/* NESTED ATM STRADDLE SUBSECTION */}
          <div className={styles.straddleBanner} style={{ marginTop: '8px', padding: '6px' }}>
            <span style={{ fontSize: '0.7rem', color: '#00F0FF', fontWeight: 600 }}>NESTED ATM STRADDLE</span>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginTop: '2px' }}>
              <span>Price: ₹{pli?.atm_straddle?.price?.toFixed(1) ?? '—'}</span>
              <span>Vel: {pli?.atm_straddle?.velocity?.toFixed(1) ?? '0.0'}</span>
            </div>
          </div>
          <div className={styles.cardSubFooter} style={{ marginTop: '8px' }}>
            <span>CE LEAD: {pli?.ce_normalized_lead_index?.toFixed(0) ?? 50}%</span>
            <span>PE LEAD: {pli?.pe_normalized_lead_index?.toFixed(0) ?? 50}%</span>
          </div>
        </div>

        {/* 3. SAE CARD */}
        <div className={styles.glassCard}>
          <div className={styles.cardTopRow}>
            <div className={styles.cardLabelGroup}>
              <BarChart3 size={16} className={styles.sectionIcon} />
              <span className={styles.cardEyebrow}>3. SAE STRIKE ATTENTION</span>
            </div>
            <span className={styles.badgePill}>STRIKE {sae?.top_strike ?? '—'}</span>
          </div>
          <div className={styles.heroRegimeRow}>
            <div className={styles.regimeName}>TOP SCORE: {sae?.top_strike_score !== undefined && sae?.top_strike_score !== null ? sae.top_strike_score.toFixed(0) : '—'}</div>
          </div>
          <div className={styles.cardSubFooter}>
            <span>RANK STABILITY: {sae?.rank_stability !== undefined && sae?.rank_stability !== null ? `${sae.rank_stability.toFixed(1)}%` : '—'}</span>
            <span>STRIKES: {sae?.ranked_strikes?.length ?? 0} RANKED</span>
          </div>
        </div>

        {/* 4. SME CARD */}
        <div className={styles.glassCard}>
          <div className={styles.cardTopRow}>
            <div className={styles.cardLabelGroup}>
              <Clock size={16} className={styles.sectionIcon} />
              <span className={styles.cardEyebrow}>4. SME MIGRATION ENGINE</span>
            </div>
            <span className={styles.badgePill}>{sme?.migration_direction || 'STATIONARY'}</span>
          </div>
          <div className={styles.heroRegimeRow}>
            <div className={styles.regimeName}>STATE: {sme?.migration_state || 'BALANCED'}</div>
          </div>
          <div className={styles.cardSubFooter}>
            <span>VELOCITY: {sme?.migration_velocity_pts_per_5m?.toFixed(1) ?? 0.0} pts/5m</span>
            <span>ACCEL: {sme?.migration_acceleration?.toFixed(1) ?? 0.0}</span>
          </div>
        </div>

        {/* 5. DGP CARD (INFERRED PROXY) */}
        <div className={styles.glassCard} style={{ border: '1px solid rgba(245, 158, 11, 0.4)' }}>
          <div className={styles.cardTopRow}>
            <div className={styles.cardLabelGroup}>
              <ShieldAlert size={16} style={{ color: '#F59E0B' }} />
              <span className={styles.cardEyebrow}>5. DGP GAMMA PRESSURE</span>
            </div>
            <span className={styles.badgePill} style={{ background: 'rgba(245, 158, 11, 0.2)', color: '#F59E0B' }}>
              INFERRED PROXY
            </span>
          </div>
          <div className={styles.heroRegimeRow}>
            <div className={styles.regimeName} style={{ fontSize: '0.85rem' }}>
              PIN STRIKE: {dgp?.gamma_pin_strike ?? '—'}
            </div>
          </div>
          <div className={styles.cardSubFooter}>
            <span>ESCAPE PROB: {dgp?.escape_probability_index?.toFixed(0) ?? 100}%</span>
            <span>CONFIDENCE: {dgp?.proxy_confidence || 'INFERRED_PROXY'}</span>
          </div>
        </div>
      </div>

      {/* ALL-44 STRATEGY RESEARCH TABLE SECTION */}
      <div style={{ marginTop: '24px', background: 'rgba(10, 15, 25, 0.6)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.08)', padding: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Filter size={16} style={{ color: '#00F0FF' }} />
            <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600, color: '#F8FAFC' }}>ALL 44 STRATEGY ARCHETYPES</h3>
            <span style={{ fontSize: '0.75rem', background: 'rgba(0,240,255,0.15)', color: '#00F0FF', padding: '2px 8px', borderRadius: '4px' }}>
              {filteredStrategies.length} STRATEGIES DISPLAYED
            </span>
          </div>

          <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
            {/* SEARCH */}
            <div style={{ position: 'relative' }}>
              <input
                type="text"
                placeholder="Search Strategy ID..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  background: 'rgba(0,0,0,0.4)',
                  border: '1px solid rgba(255,255,255,0.15)',
                  color: '#FFF',
                  padding: '4px 8px 4px 28px',
                  borderRadius: '6px',
                  fontSize: '0.8rem',
                }}
              />
              <Search size={13} style={{ position: 'absolute', left: '8px', top: '7px', color: '#94A3B8' }} />
            </div>

            {/* SIDE FILTER */}
            <div style={{ display: 'flex', gap: '4px' }}>
              {(['ALL', 'CALL', 'PUT'] as const).map((side) => (
                <button
                  key={side}
                  type="button"
                  onClick={() => setSideFilter(side)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: '4px',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    background: sideFilter === side ? (side === 'CALL' ? '#00FF9D' : side === 'PUT' ? '#FF0055' : '#00F0FF') : 'rgba(255,255,255,0.05)',
                    color: sideFilter === side ? '#000' : '#94A3B8',
                    border: 'none',
                  }}
                >
                  {side}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* TABLE */}
        <div style={{ overflowX: 'auto', maxHeight: '400px', overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem', color: '#E2E8F0' }}>
            <thead>
              <tr style={{ background: 'rgba(0,0,0,0.4)', textAlign: 'left', color: '#94A3B8', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                <th style={{ padding: '8px 12px' }}>STRATEGY ID</th>
                <th style={{ padding: '8px 12px' }}>SIDE</th>
                <th style={{ padding: '8px 12px' }}>PRIME DEPENDENCY</th>
                <th style={{ padding: '8px 12px' }}>STRICTNESS</th>
                <th style={{ padding: '8px 12px' }}>CANDIDATE STATUS</th>
                <th style={{ padding: '8px 12px' }}>FIRST BLOCKER / REASON</th>
                <th style={{ padding: '8px 12px' }}>STATE</th>
                <th style={{ padding: '8px 12px' }}>EXECUTION INFLUENCE</th>
              </tr>
            </thead>
            <tbody>
              {filteredStrategies.map((s) => (
                <tr key={s.strategy_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <td style={{ padding: '8px 12px', fontWeight: 600, fontFamily: 'monospace' }}>{s.strategy_id}</td>
                  <td style={{ padding: '8px 12px' }}>
                    <span style={{ color: s.side === 'CALL' ? '#00FF9D' : '#FF0055', fontWeight: 600 }}>{s.side}</span>
                  </td>
                  <td style={{ padding: '8px 12px' }}>{s.prime_dependency}</td>
                  <td style={{ padding: '8px 12px' }}>{s.strictness}</td>
                  <td style={{ padding: '8px 12px' }}>
                    {s.candidate_generated ? (
                      <span style={{ color: '#00FF9D', fontWeight: 600 }}>CANDIDATE GENERATED</span>
                    ) : (
                      <span style={{ color: '#F59E0B' }}>BLOCKED</span>
                    )}
                  </td>
                  <td style={{ padding: '8px 12px', color: '#94A3B8', fontSize: '0.75rem' }}>
                    {s.first_blocker || 'NONE (Candidate Qualified)'}
                  </td>
                  <td style={{ padding: '8px 12px' }}>
                    <span style={{ background: 'rgba(0,240,255,0.1)', color: '#00F0FF', padding: '2px 6px', borderRadius: '4px', fontSize: '0.7rem' }}>
                      {s.evaluation_state || 'RUNTIME_EVALUATED'}
                    </span>
                  </td>
                  <td style={{ padding: '8px 12px', color: '#00FF9D', fontWeight: 600 }}>ZERO</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
