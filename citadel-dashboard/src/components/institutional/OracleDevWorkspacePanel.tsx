'use client'

import React, { useState } from 'react'
import {
  BrainCircuit,
  Activity,
  Waves,
  CircleGauge,
  HeartPulse,
  TrendingUp,
  TrendingDown,
  Info,
  ShieldCheck,
  Zap,
  LayoutGrid,
  Orbit,
  ArrowRight,
  Flame,
  AlertTriangle
} from 'lucide-react'
import { useRouter } from 'next/navigation'
import type { OracleDevMissionRuntime, OracleDevReasoningData } from '@/app/oracle-development/useOracleDevMissionRuntime'
import type { DashboardFeedState, DashboardFeedMeta } from '@/dashboard/types'
import { useOracleDevChartData, type TradeMarker } from '@/app/oracle-development/useOracleDevChartData'
import { FuturesIntelligenceChart } from '@/components/chart/FuturesIntelligenceChart'

import styles from '@/app/oracle/oracle.module.css'

export interface OracleDevWorkspacePanelProps {
  devRuntime: OracleDevMissionRuntime
  riskStatus: DashboardFeedState<unknown>
  paperStatus: DashboardFeedState<unknown>
  oracleMeta?: DashboardFeedMeta
  selectedLane: '1m' | '3m' | '5m'
  setSelectedLane: (lane: '1m' | '3m' | '5m') => void
  overrideExpand?: boolean
  overrideLayers?: string[] | null
  overrideSelectedTradeId?: string | null
  forceStale?: boolean
  overrideZoom?: number | null
  overrideScroll?: number | null
  forceInsufficient?: boolean
  overrideHoverIndex?: number | 'auto' | null
}

export function OracleDevWorkspacePanel({
  devRuntime,
  riskStatus,
  paperStatus,
  oracleMeta,
  selectedLane,
  setSelectedLane,
  overrideExpand = false,
  overrideLayers = null,
  overrideSelectedTradeId = null,
  forceStale = false,
  overrideZoom = null,
  overrideScroll = null,
  forceInsufficient = false,
  overrideHoverIndex = null
}: OracleDevWorkspacePanelProps) {
  const router = useRouter()
  const { assessments, activeMission, isReplay = true, loading, busyAction, error, refresh, analyse, paperExecute, exitNow, cancel } = devRuntime

  const [highlightedStrategy, setHighlightedStrategy] = useState<string | null>(null)
  const { 
    chartData, 
    loading: chartLoading, 
    error: chartError,
    forceSync,
    syncStatus,
    syncCooldown
  } = useOracleDevChartData(selectedLane, forceStale)

  // Get active assessment details for selected lane
  const activeAssessment: OracleDevReasoningData | undefined = assessments?.[selectedLane]
  const laneStatus = activeAssessment?.lane_status

  const requiredCount = selectedLane === '1m' ? 80 : (selectedLane === '3m' ? 60 : 50)
  const isExecutionReady = chartData?.execution_ready ?? false
  const execBlocker = chartData?.execution_blocker ?? (chartData && chartData.candles.length < requiredCount ? 'INSUFFICIENT_HISTORY' : null)

  // Centering & Zooming callback when clicking a trade in the ledger
  const handleTradeClick = (t: TradeMarker) => {
    const triggerTs = parseInt(t.trigger_candle)
    if (isNaN(triggerTs)) return
    
    const candles = chartData?.candles || []
    const idx = candles.findIndex(c => c.time === triggerTs)
    if (idx === -1) return
    
    const targetZoom = 50
    const targetScroll = Math.max(0, candles.length - 1 - idx - Math.floor(targetZoom / 2))
    
    router.push(`/oracle-development?lane=${selectedLane}&selectedTrade=${t.mission_id}&scroll=${targetScroll}&zoom=${targetZoom}`)
  }

  // Lane state utilities
  const getLaneExecutionState = (lane: string) => {
    const lData = assessments?.[lane]
    const exec = lData?.execution as any
    const ready = exec ? (exec.risk_approved && exec.guardian_ready) : false
    const blocker = exec?.blocker
    if (!ready && blocker) {
      if (blocker === 'STALE_CURRENT_SESSION' || blocker === 'STALE_DATA') {
        return 'DATA_STALE'
      }
      if (blocker === 'CONTRACT_ROLLOVER_PENDING') {
        return 'ROLLOVER_PENDING'
      }
      return 'WAITING_HISTORY'
    }
    return lData?.lane_status?.state ?? 'IDLE'
  }

  const isLaneReady = (lane: string) => {
    const lData = assessments?.[lane]
    const exec = lData?.execution as any
    return exec ? (exec.risk_approved && exec.guardian_ready) : false
  }

  // Format Helper
  const formatMoney = (val: number | undefined | null) => {
    if (val === undefined || val === null) return '—'
    return `₹${val.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
  }

  // Get status color tone
  const getFactorColor = (status: string | undefined | null) => {
    if (status === 'green') return '#10b981' // emerald
    if (status === 'red') return '#ef4444'   // crimson
    if (status === 'amber') return '#fbbf24' // amber
    return '#6b7280'                         // grey (neutral)
  }

  // Radar State Resolver - uses actual backend state instead of mock defaults
  const getRadarState = (lane: string, strategyId: string): string => {
    const laneData = assessments?.[lane]
    const laneStatus = laneData?.lane_status
    
    const isCurrentStrategy = 
      laneData?.strategy_id === strategyId || 
      laneStatus?.position?.strategy_id === strategyId || 
      laneStatus?.active_setup?.strategy_id === strategyId

    if (isCurrentStrategy) {
      if (laneStatus?.position) return 'OPEN'
      
      const exec = laneData?.execution as any
      const ready = exec ? (exec.risk_approved && exec.guardian_ready) : false
      if (!ready) return 'BLOCKED'
      
      if (laneStatus?.state === 'READY_CONFIRMED') return 'READY'
      if (laneStatus?.state === 'SETUP_ARMED') return 'ARMED'
      return 'WATCH'
    }
    return 'IDLE'
  }

  // Decision Spine Stages
  const stages = ['CONTEXT', 'LOCATION', 'APPROACH', 'TRIGGER', 'MATURITY', 'ENTRY', 'GUARDIAN', 'EXIT']
  const getSpineStage = (): string => {
    if (!isExecutionReady) return 'CONTEXT'
    const state = laneStatus?.state
    const totalScore = activeAssessment?.scores?.total_score ?? 0
    const paScore = activeAssessment?.scores?.pa_score ?? 0
    const vobScore = activeAssessment?.scores?.vob_score ?? 0

    if (state === 'OPEN') return 'GUARDIAN'
    if (state === 'EXITING' || state === 'CLOSED') return 'EXIT'
    if (state === 'READY_CONFIRMED') return 'ENTRY'
    if (state === 'SETUP_ARMED') return 'TRIGGER'
    if (totalScore >= 40.0) return 'MATURITY'
    if (paScore >= 10.0 || vobScore >= 5.0) return 'APPROACH'
    if (laneStatus?.last_spot) return 'LOCATION'
    return 'CONTEXT'
  }
  const currentSpineStage = getSpineStage()

  // Group contributors into panels
  const contributors = activeAssessment?.scores?.all_contributors ?? {}
  const paFactors = Object.entries(contributors).filter(([key]) => key.startsWith('PA_'))
  const vobFactors = Object.entries(contributors).filter(([key]) => key.startsWith('VOB_') || key.startsWith('VOB'))
  const derivFactors = Object.entries(contributors).filter(([key]) => key.startsWith('DERIV_') || key.startsWith('DERIV'))
  const execFactors = Object.entries(contributors).filter(([key]) => key.startsWith('EXEC_') || key.startsWith('EXEC'))

  // Navigation action
  const navigateDashboard = (mode: 'production' | 'workspace') => {
    window.sessionStorage.setItem('citadelDashboardMode', mode)
    router.push('/')
  }

  return (
    <div className={styles.workspace} style={{ minHeight: '100vh', background: '#020408', color: '#d1d5db', fontFamily: 'var(--cds-font-sans), sans-serif', paddingBottom: '30px' }}>
      
      {/* 1. TOP NAV / HEADER */}
      <header className={styles.oracleHeader} style={{ background: '#070a10', borderBottom: '1px solid rgba(34, 211, 238, 0.15)', height: '48px', padding: '0 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <nav className={styles.oracleNav} style={{ display: 'flex', alignItems: 'center', gap: '8px', font: '600 11px var(--cds-font-mono)', letterSpacing: '0.13em' }}>
          <button type="button" style={{ background: 'none', border: 'none', color: '#4b5563', cursor: 'pointer' }} onClick={() => navigateDashboard('production')}>PROD</button>
          <span style={{ color: '#1f2937' }}>/</span>
          <button type="button" style={{ background: 'none', border: 'none', color: '#4b5563', cursor: 'pointer' }} onClick={() => navigateDashboard('workspace')}>WORKSPACE</button>
          <span style={{ color: '#1f2937' }}>/</span>
          <button type="button" style={{ background: 'none', border: 'none', color: '#4b5563', cursor: 'pointer' }} onClick={() => router.push('/oracle')}>ORACLE</button>
          <span style={{ color: '#1f2937' }}>/</span>
          <button type="button" style={{ background: 'none', border: 'none', color: '#22d3ee', textShadow: '0 0 10px rgba(34, 211, 238, 0.4)', cursor: 'pointer', fontWeight: 'bold' }}>ORACLE DEVELOPMENT</button>
        </nav>
        <div className={styles.headerIdentity} style={{ display: 'flex', alignItems: 'center', gap: '8px', font: '600 11px var(--cds-font-mono)', color: '#f3f4f6' }}>
          <Orbit size={15} style={{ color: '#22d3ee' }} />
          <span>CITADEL ORACLE DEV</span>
          <small style={{ borderLeft: '1px solid #1f2937', paddingLeft: '8px', color: '#4b5563', fontSize: '9px' }}>Experimental Research Laboratory</small>
        </div>
        <div className={styles.headerSafety} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '10px', color: '#f05264', fontWeight: 'bold', fontFamily: 'var(--cds-font-mono)' }}>
          <span>VIRTUAL PAPER ONLY</span>
          <i style={{ width: '4px', height: '4px', borderRadius: '50%', background: '#f05264', boxShadow: '0 0 6px #f05264' }} />
          <span style={{ color: '#9ca3af' }}>LIVE IMPOSSIBLE · BROKER DISABLED</span>
        </div>
      </header>

      {/* 2. RUNTIME / SAFETY STRIP */}
      <div className={styles.runtimeStrip} style={{ background: '#0a0f18', borderBottom: '1px solid rgba(255,255,255,0.03)', display: 'flex', justifyContent: 'space-between', padding: '6px 20px', fontSize: '9px', fontFamily: 'var(--cds-font-mono)', color: '#4b5563' }}>
        <div>
          REPLAY STATUS: 
          {isReplay ? (
            <strong style={{ color: '#fbbf24', marginLeft: '5px', background: 'rgba(251, 191, 36, 0.1)', padding: '2px 6px', borderRadius: '3px' }}>REPLAY MODE (FALLBACK ACTIVE)</strong>
          ) : (
            <strong style={{ color: '#34d399', marginLeft: '5px', background: 'rgba(52, 211, 153, 0.1)', padding: '2px 6px', borderRadius: '3px' }}>LIVE STREAM CONNECTED</strong>
          )}
        </div>
        <div style={{ display: 'flex', gap: '15px', flexWrap: 'wrap' }}>
          <span>ACTIVE CONTRACT: <strong style={{ color: '#d1d5db' }}>{chartData?.contract ?? 'NIFTY'} ({chartData?.security_id ?? 'N/A'})</strong></span>
          <span>EXPIRY: <strong style={{ color: '#a7f3d0' }}>{chartData?.expiry ?? 'N/A'}</strong></span>
          <span>ROLLOVER: <strong style={{ color: '#22d3ee' }}>{chartData?.rollover_status ?? 'ACTIVE'} (FRONT MONTH)</strong></span>
          <span>RESOLVED: <strong style={{ color: '#f3f4f6' }}>{chartData?.last_resolution_time && chartData.last_resolution_time !== 'N/A' && !isNaN(Date.parse(chartData.last_resolution_time)) ? new Date(chartData.last_resolution_time).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : 'N/A'}</strong></span>
          <span>MARKET: <strong style={{ color: chartData?.market_status === 'OPEN' ? '#10b981' : '#f59e0b' }}>{chartData?.market_status ?? 'CLOSED'}</strong></span>
          <span>DATA HEALTH: <strong style={{ color: (error || chartData?.last_backfill_error) ? '#ef4444' : '#10b981' }}>{(error || chartData?.last_backfill_error) ? 'DEGRADED' : 'NOMINAL'}</strong></span>
          <span>AGE: <strong style={{ color: chartData?.market_status === 'OPEN' && (chartData?.data_age_seconds && chartData.data_age_seconds > 30.0) ? '#fbbf24' : '#34d399' }}>{chartData?.market_status === 'OPEN' ? (chartData?.data_age_seconds !== undefined ? `${chartData.data_age_seconds}s` : '—') : 'NOMINAL (CLOSED)'}</strong></span>
          <span>LAST UPDATE: <strong style={{ color: '#fff' }}>{chartData?.last_timestamp && chartData.last_timestamp !== 'N/A' && !isNaN(Date.parse(chartData.last_timestamp)) ? new Date(chartData.last_timestamp).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'}</strong></span>
          <span>MODE: <strong style={{ color: '#22d3ee' }}>{chartData?.source_mode ?? 'LIVE'}</strong></span>
          {chartData?.last_backfill_error && (
            <span style={{ color: '#ef4444' }}>ERROR: <strong>{chartData.last_backfill_error}</strong></span>
          )}
        </div>
      </div>

      {/* 3. HERO / PRIMARY DECISION BANNER */}
      <div style={{ margin: '15px 20px', background: 'linear-gradient(135deg, #090e16 0%, #040609 100%)', border: '1px solid rgba(34, 211, 238, 0.12)', borderRadius: '6px', padding: '16px 20px', boxShadow: '0 4px 20px rgba(0,0,0,0.4)', position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: 0, right: 0, width: '150px', height: '150px', background: 'radial-gradient(circle, rgba(34, 211, 238, 0.05) 0%, transparent 70%)', pointerEvents: 'none' }} />
        
        <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 1fr', gap: '20px', alignItems: 'center' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ 
                padding: '2px 8px', 
                background: laneStatus?.position ? 'rgba(239, 68, 68, 0.15)' : (!isExecutionReady ? 'rgba(245, 158, 11, 0.15)' : 'rgba(34, 211, 238, 0.15)'), 
                color: laneStatus?.position ? '#ef4444' : (!isExecutionReady ? '#f59e0b' : '#22d3ee'), 
                borderRadius: '3px', 
                fontSize: '10px', 
                fontWeight: 'bold',
                fontFamily: 'var(--cds-font-mono)'
              }}>
                {laneStatus?.position ? 'EXECUTION OPEN' : (!isExecutionReady ? 'BLOCKED' : (laneStatus?.state ?? 'MONITORING'))}
              </span>
              <span style={{ fontSize: '11px', color: '#4b5563', fontFamily: 'var(--cds-font-mono)' }}>Timeframe: {selectedLane}</span>
            </div>
            
            <h2 style={{ margin: '8px 0 2px', fontSize: '22px', fontWeight: 'bold', color: '#f3f4f6', letterSpacing: '-0.02em' }}>
              {activeAssessment?.strategy_name ? `${activeAssessment.strategy_name.toUpperCase()}${!isExecutionReady ? ' (CANDIDATE)' : ''}` : 'NO ACTIVE STRATEGY'}
            </h2>
            <p style={{ margin: 0, fontSize: '12px', color: '#6b7280', fontFamily: 'var(--cds-font-mono)' }}>
              Subtype: {activeAssessment?.setup_subtype ?? 'SECOND_ENTRY_CONTINUATION'}
            </p>
          </div>

          <div style={{ borderLeft: '1px solid rgba(255,255,255,0.03)', paddingLeft: '20px' }}>
            <span style={{ display: 'block', fontSize: '9px', color: '#4b5563', textTransform: 'uppercase', fontFamily: 'var(--cds-font-mono)' }}>Active Contract</span>
            <strong style={{ fontSize: '15px', color: '#fff', fontFamily: 'var(--cds-font-mono)' }}>
              {laneStatus?.position?.symbol ? String(laneStatus.position.symbol) : (laneStatus?.last_option?.ATM_CE ? 'NIFTY ATM Contract' : '—')}
            </strong>
            <span style={{ display: 'block', fontSize: '11px', color: laneStatus?.position?.direction === 'PUT' ? '#ef4444' : '#10b981', marginTop: '2px', fontFamily: 'var(--cds-font-mono)' }}>
              {laneStatus?.position?.direction ? String(laneStatus.position.direction) : 'CALL/PUT SCOUTING'}
            </span>
          </div>

          <div style={{ borderLeft: '1px solid rgba(255,255,255,0.03)', paddingLeft: '20px' }}>
            <span style={{ display: 'block', fontSize: '9px', color: '#4b5563', textTransform: 'uppercase', fontFamily: 'var(--cds-font-mono)' }}>Segment Assessment</span>
            <strong style={{ fontSize: '18px', color: '#22d3ee', fontFamily: 'var(--cds-font-mono)' }}>
              {!isExecutionReady ? 'BLOCKED' : Number(activeAssessment?.scores?.total_score ?? 0).toFixed(2)} <span style={{ fontSize: '11px', color: '#4b5563' }}>/ 100</span>
            </strong>
            <span style={{ display: 'block', fontSize: '10px', color: '#6b7280', marginTop: '2px' }}>
              Lots: {!isExecutionReady ? '0' : (activeAssessment?.plan?.approved_lots ? String(activeAssessment.plan.approved_lots) : '1')} approved (Max {activeAssessment?.plan?.conviction_ceiling ? String(activeAssessment.plan.conviction_ceiling) : '5'})
            </span>
          </div>

          <div style={{ borderLeft: '1px solid rgba(255,255,255,0.03)', paddingLeft: '20px' }}>
            <span style={{ display: 'block', fontSize: '9px', color: '#4b5563', textTransform: 'uppercase', fontFamily: 'var(--cds-font-mono)' }}>Guardian Action</span>
            <strong style={{ fontSize: '13px', color: '#fbbf24', display: 'flex', alignItems: 'center', gap: '5px' }}>
              <TrendingDown size={14} /> {laneStatus?.position ? (laneStatus.guardian_action || 'Monitoring') : (!isExecutionReady ? execBlocker : 'Monitoring')}
            </strong>
            <span style={{ display: 'block', fontSize: '10px', color: '#6b7280', marginTop: '3px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
              {laneStatus?.position ? (laneStatus.guardian_reason || 'Active position risk tracking') : (!isExecutionReady ? `Execution blocked: ${execBlocker}` : 'No active position')}
            </span>
          </div>
        </div>
      </div>

      {/* 3.5 NIFTY FUTURES INTELLIGENCE CHART */}
      <FuturesIntelligenceChart
        data={chartData}
        loading={chartLoading}
        error={chartError}
        selectedLane={selectedLane}
        onLaneChange={setSelectedLane}
        highlightedStrategy={highlightedStrategy}
        onHighlightStrategy={setHighlightedStrategy}
        overrideExpand={overrideExpand}
        overrideLayers={overrideLayers}
        overrideSelectedTradeId={overrideSelectedTradeId}
        overrideZoom={overrideZoom}
        overrideScroll={overrideScroll}
        forceInsufficient={forceInsufficient}
        overrideHoverIndex={overrideHoverIndex}
        forceSync={forceSync}
        syncStatus={syncStatus}
        syncCooldown={syncCooldown}
      />

      {/* 4. THREE LANE COMMAND CARDS & SCORE CARD */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1.2fr', gap: '15px', padding: '0 20px', marginBottom: '15px' }}>
        {['1m', '3m', '5m'].map((lane) => {
          const lData = assessments?.[lane]
          const lStatus = lData?.lane_status
          const isActive = selectedLane === lane
          const hasPos = !!lStatus?.position

          return (
            <div 
              key={lane}
              style={{ 
                padding: '12px 15px', 
                background: isActive ? '#0b1320' : '#070a10', 
                border: isActive ? '1px solid #22d3ee' : '1px solid rgba(255,255,255,0.04)', 
                borderRadius: '6px', 
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                boxShadow: isActive ? '0 0 12px rgba(34, 211, 238, 0.15)' : 'none'
              }}
              onClick={() => setSelectedLane(lane as '1m' | '3m' | '5m')}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 'bold', fontSize: '13px', color: '#fff', display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--cds-font-mono)' }}>
                  {lane === '1m' ? <Activity size={14} style={{ color: '#ec4899' }} /> : lane === '3m' ? <Waves size={14} style={{ color: '#3b82f6' }} /> : <TrendingUp size={14} style={{ color: '#10b981' }} />}
                  {lane} LANE ({lane === '1m' ? 'Scalp' : lane === '3m' ? 'Swing' : 'Trend'})
                </span>
                <span style={{ 
                  padding: '1px 6px', 
                  borderRadius: '2px', 
                  fontSize: '9px', 
                  fontWeight: 'bold',
                  background: hasPos ? 'rgba(16, 185, 129, 0.12)' : (!isLaneReady(lane) ? 'rgba(245, 158, 11, 0.12)' : 'rgba(255,255,255,0.03)'),
                  color: hasPos ? '#10b981' : (!isLaneReady(lane) ? '#fbbf24' : '#6b7280'),
                  border: hasPos ? '1px solid rgba(16, 185, 129, 0.2)' : (!isLaneReady(lane) ? '1px solid rgba(245, 158, 11, 0.2)' : '1px solid rgba(255,255,255,0.05)')
                }}>
                  {hasPos ? 'POSITION ACTIVE' : getLaneExecutionState(lane)}
                </span>
              </div>

              {/* Lane Specs & Scores */}
              <div style={{ marginTop: '8px', fontSize: '11px', display: 'flex', justifyContent: 'space-between', color: '#9ca3af', fontFamily: 'var(--cds-font-mono)' }}>
                <span>Strategy: <strong style={{ color: isLaneReady(lane) ? '#fff' : '#fbbf24' }}>{lData?.strategy_name ? `${lData.strategy_name}${!isLaneReady(lane) ? ' (CANDIDATE)' : ''}` : '—'}</strong></span>
                <span>Type: <strong style={{ color: '#d1d5db' }}>{lData?.setup_subtype?.replace('PA_', '').replace('VOB_', '') ?? '—'}</strong></span>
              </div>

              <div style={{ marginTop: '6px', borderTop: '1px solid rgba(255,255,255,0.03)', paddingTop: '6px', display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '4px', textAlign: 'center', fontSize: '10px' }}>
                <div>
                  <span style={{ color: '#4b5563', display: 'block', scale: '0.9' }}>PA</span>
                  <strong style={{ color: '#3b82f6' }}>{Number(lData?.scores?.pa_score ?? 0).toFixed(2)}</strong>
                </div>
                <div>
                  <span style={{ color: '#4b5563', display: 'block', scale: '0.9' }}>VOB</span>
                  <strong style={{ color: '#10b981' }}>{Number(lData?.scores?.vob_score ?? 0).toFixed(2)}</strong>
                </div>
                <div>
                  <span style={{ color: '#4b5563', display: 'block', scale: '0.9' }}>DERIV</span>
                  <strong style={{ color: '#a855f7' }}>{Number(lData?.scores?.deriv_score ?? 0).toFixed(2)}</strong>
                </div>
                <div>
                  <span style={{ color: '#4b5563', display: 'block', scale: '0.9' }}>EXEC</span>
                  <strong style={{ color: '#fbbf24' }}>{!isLaneReady(lane) ? 'BLOCKED' : Number(lData?.scores?.exec_score ?? 0).toFixed(2)}</strong>
                </div>
                <div>
                  <span style={{ color: '#93c5fd', display: 'block', scale: '0.9', fontWeight: 'bold' }}>TOT</span>
                  <strong style={{ color: '#fff' }}>{!isLaneReady(lane) ? 'BLOCKED' : Number(lData?.scores?.total_score ?? 0).toFixed(2)}</strong>
                </div>
              </div>

              {/* Financial metrics */}
              <div style={{ marginTop: '6px', borderTop: '1px solid rgba(255,255,255,0.03)', paddingTop: '6px', display: 'flex', justifyContent: 'space-between', fontSize: '11px', fontFamily: 'var(--cds-font-mono)' }}>
                <span>Balance: <strong style={{ color: '#fff' }}>{formatMoney(lStatus?.balance)}</strong></span>
                {hasPos && (
                  <span>
                    PNL: <strong style={{ color: (lStatus?.position?.pnl as number) >= 0 ? '#10b981' : '#ef4444' }}>
                      {formatMoney(lStatus?.position?.pnl as number)}
                    </strong>
                  </span>
                )}
              </div>
            </div>
          )
        })}

        {/* Market Structure & Score Card */}
        <div style={{ 
          padding: '12px 15px', 
          background: '#070a10', 
          border: '1px solid rgba(34, 211, 238, 0.15)', 
          borderRadius: '6px', 
          display: 'flex', 
          flexDirection: 'column', 
          justifyContent: 'space-between',
          boxShadow: '0 4px 15px rgba(0,0,0,0.5)'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '6px', marginBottom: '6px' }}>
            <span style={{ fontWeight: 'bold', fontSize: '11px', color: '#22d3ee', display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--cds-font-mono)' }}>
              <CircleGauge size={13} style={{ color: '#22d3ee' }} />
              MARKET STRUCTURE & SCORE
            </span>
            <span style={{ fontSize: '10px', color: '#6b7280', fontFamily: 'var(--cds-font-mono)' }}>
              Weight: 100%
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
            <div style={{ textAlign: 'center', minWidth: '65px' }}>
              <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#fff', fontFamily: 'var(--cds-font-mono)', lineHeight: '1.1' }}>
                {Number(activeAssessment?.scores?.total_score ?? 0).toFixed(2)}
              </div>
              <div style={{ fontSize: '9px', color: '#4b5563', fontFamily: 'var(--cds-font-mono)' }}>/100</div>
            </div>

            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '9px', fontFamily: 'var(--cds-font-mono)' }}>
              {[
                { name: 'Price Action', val: activeAssessment?.scores?.pa_score ?? 0.0, max: 30, color: '#3b82f6', provenance: 'NIFTY SPOT & FUT' },
                { name: 'VOB Alignment', val: activeAssessment?.scores?.vob_score ?? 0.0, max: 25, color: '#10b981', provenance: 'VOB ENGINE' },
                { name: 'Derivatives', val: activeAssessment?.scores?.deriv_score ?? 0.0, max: 25, color: '#a855f7', provenance: 'OSE' },
                { name: 'Execution', val: activeAssessment?.scores?.exec_score ?? 0.0, max: 20, color: '#fbbf24', provenance: 'EXECUTION GATE' }
              ].map((comp) => {
                const pct = Math.min(100, Math.max(0, (Number(comp.val) / comp.max) * 100))
                return (
                  <div key={comp.name} title={`Provenance: ${comp.provenance}`}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#9ca3af', marginBottom: '1px' }}>
                      <span>{comp.name}</span>
                      <span>
                        <strong>{Number(comp.val).toFixed(2)}</strong>/{comp.max}
                      </span>
                    </div>
                    <div style={{ height: '4px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px', overflow: 'hidden' }}>
                      <div style={{ width: `${pct}%`, height: '100%', background: comp.color, borderRadius: '2px' }} />
                    </div>
                  </div>
                )
              })}
              {(!isExecutionReady || activeAssessment?.scores?.exec_score === 0) && (
                <div style={{ marginTop: '4px', borderTop: '1px dashed rgba(255,255,255,0.05)', paddingTop: '4px', color: '#fbbf24', fontSize: '8px', lineHeight: '1.3', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <AlertTriangle size={10} style={{ color: '#fbbf24', flexShrink: 0 }} />
                  <span>Execution score is 0.00 because the execution gate is blocked: <strong>{execBlocker || 'INSUFFICIENT_HISTORY'}</strong>.</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 4.5 ATM OPTION INTELLIGENCE CARDS */}
      <div style={{ padding: '0 20px', marginBottom: '15px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px' }}>
          
          {/* CE Strike Card */}
          <div style={{ background: '#070a10', border: '1px solid rgba(16, 185, 129, 0.15)', borderRadius: '6px', padding: '12px 15px', position: 'relative' }}>
            <span style={{ position: 'absolute', top: '10px', right: '12px', fontSize: '8px', color: '#10b981', fontWeight: 'bold', border: '1px solid rgba(16,185,129,0.3)', padding: '2px 6px', borderRadius: '3px', fontFamily: 'var(--cds-font-mono)' }}>ATM CALL INTELLIGENCE</span>
            <h3 style={{ margin: '0 0 10px', color: '#fff', fontSize: '13px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--cds-font-mono)' }}>
              <TrendingUp size={14} style={{ color: '#10b981' }} />
              ATM CE: {laneStatus?.options_info?.ATM_CE?.strike ?? '—'} CE
            </h3>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 15px', fontSize: '11px', fontFamily: 'var(--cds-font-mono)' }}>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>EXPIRY (Provenance: OSE)</span>
                <strong style={{ color: '#fff' }}>{laneStatus?.options_info?.ATM_CE?.expiry ?? '—'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>SECURITY ID (Provenance: OSE)</span>
                <strong style={{ color: '#fff' }}>{laneStatus?.options_info?.ATM_CE?.security_id ?? '—'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>PREMIUM / LTP (Provenance: ATM CE)</span>
                <strong style={{ color: '#10b981' }}>{laneStatus?.last_option?.ATM_CE?.close !== undefined ? `₹${laneStatus.last_option.ATM_CE.close}` : (laneStatus?.options_unavailable_reason ? `NOT AVAILABLE (${laneStatus.options_unavailable_reason})` : 'NOT AVAILABLE (Loading)')}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>VOB STATE</span>
                <strong style={{ color: activeAssessment?.vob?.vob_state === 'ACTIVE_ZONE' ? '#10b981' : '#fbbf24' }}>
                  {activeAssessment?.vob?.vob_state ? String(activeAssessment.vob.vob_state) : 'WAITING_DATA'}
                </strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>TIMEFRAME</span>
                <strong style={{ color: '#fff' }}>{activeAssessment?.vob?.timeframe ? String(activeAssessment.vob.timeframe) : '—'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>PRICE SPACE</span>
                <strong style={{ color: '#fff' }}>{activeAssessment?.vob?.price_space ? String(activeAssessment.vob.price_space) : '—'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>SOURCE</span>
                <strong style={{ color: '#fff' }}>{activeAssessment?.vob?.source ? String(activeAssessment.vob.source) : '—'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>FRESHNESS</span>
                <strong style={{ color: '#fbbf24' }}>{activeAssessment?.vob?.freshness ? String(activeAssessment.vob.freshness) : '—'}</strong>
              </div>
              <div style={{ gridColumn: 'span 2', borderTop: '1px dashed rgba(255,255,255,0.03)', paddingTop: '6px' }}>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>NEAREST VOB ZONE</span>
                <strong style={{ color: '#fff' }}>{activeAssessment?.vob?.proximity_desc ? String(activeAssessment.vob.proximity_desc) : 'No active VOB zone nearby'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>ZONE LIFECYCLE</span>
                <strong style={{ color: '#9ca3af' }}>{activeAssessment?.vob?.displacement_desc ? String(activeAssessment.vob.displacement_desc) : 'Neutral displacement'}</strong>
              </div>
            </div>
          </div>

          {/* PE Strike Card */}
          <div style={{ background: '#070a10', border: '1px solid rgba(239, 68, 68, 0.15)', borderRadius: '6px', padding: '12px 15px', position: 'relative' }}>
            <span style={{ position: 'absolute', top: '10px', right: '12px', fontSize: '8px', color: '#ef4444', fontWeight: 'bold', border: '1px solid rgba(239,68,68,0.3)', padding: '2px 6px', borderRadius: '3px', fontFamily: 'var(--cds-font-mono)' }}>ATM PUT INTELLIGENCE</span>
            <h3 style={{ margin: '0 0 10px', color: '#fff', fontSize: '13px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--cds-font-mono)' }}>
              <TrendingDown size={14} style={{ color: '#ef4444' }} />
              ATM PE: {laneStatus?.options_info?.ATM_PE?.strike ?? '—'} PE
            </h3>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 15px', fontSize: '11px', fontFamily: 'var(--cds-font-mono)' }}>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>EXPIRY (Provenance: OSE)</span>
                <strong style={{ color: '#fff' }}>{laneStatus?.options_info?.ATM_PE?.expiry ?? '—'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>SECURITY ID (Provenance: OSE)</span>
                <strong style={{ color: '#fff' }}>{laneStatus?.options_info?.ATM_PE?.security_id ?? '—'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>PREMIUM / LTP (Provenance: ATM PE)</span>
                <strong style={{ color: '#ef4444' }}>{laneStatus?.last_option?.ATM_PE?.close !== undefined ? `₹${laneStatus.last_option.ATM_PE.close}` : (laneStatus?.options_unavailable_reason ? `NOT AVAILABLE (${laneStatus.options_unavailable_reason})` : 'NOT AVAILABLE (Loading)')}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>VOB STATE</span>
                <strong style={{ color: activeAssessment?.vob?.vob_state === 'ACTIVE_ZONE' ? '#10b981' : '#fbbf24' }}>
                  {activeAssessment?.vob?.vob_state ? String(activeAssessment.vob.vob_state) : 'WAITING_DATA'}
                </strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>TIMEFRAME</span>
                <strong style={{ color: '#fff' }}>{activeAssessment?.vob?.timeframe ? String(activeAssessment.vob.timeframe) : '—'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>PRICE SPACE</span>
                <strong style={{ color: '#fff' }}>{activeAssessment?.vob?.price_space ? String(activeAssessment.vob.price_space) : '—'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>SOURCE</span>
                <strong style={{ color: '#fff' }}>{activeAssessment?.vob?.source ? String(activeAssessment.vob.source) : '—'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>FRESHNESS</span>
                <strong style={{ color: '#fbbf24' }}>{activeAssessment?.vob?.freshness ? String(activeAssessment.vob.freshness) : '—'}</strong>
              </div>
              <div style={{ gridColumn: 'span 2', borderTop: '1px dashed rgba(255,255,255,0.03)', paddingTop: '6px' }}>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>NEAREST VOB ZONE</span>
                <strong style={{ color: '#fff' }}>{activeAssessment?.vob?.proximity_desc ? String(activeAssessment.vob.proximity_desc) : 'No active VOB zone nearby'}</strong>
              </div>
              <div>
                <span style={{ color: '#4b5563', display: 'block', fontSize: '9px' }}>ZONE LIFECYCLE</span>
                <strong style={{ color: '#9ca3af' }}>{activeAssessment?.vob?.displacement_desc ? String(activeAssessment.vob.displacement_desc) : 'Neutral displacement'}</strong>
              </div>
            </div>
          </div>

        </div>
      </div>

      {/* 5. STRATEGY RADAR & DECISION SPINE */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 2fr', gap: '15px', padding: '0 20px', marginBottom: '15px' }}>
        
        {/* Strategy Radar Matrix */}
        <div style={{ background: '#070a10', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '12px 15px' }}>
          <h3 style={{ margin: '0 0 10px', color: '#fff', fontSize: '12px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--cds-font-mono)' }}>
            <LayoutGrid size={13} style={{ color: '#22d3ee' }} />
            STRATEGY RADAR MATRIX
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1.8fr 1fr 1fr 1fr', gap: '5px', fontSize: '10px', fontFamily: 'var(--cds-font-mono)' }}>
            <div style={{ color: '#4b5563', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '4px' }}>Strategy Identity</div>
            <div style={{ color: '#4b5563', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '4px', textAlign: 'center' }}>1m</div>
            <div style={{ color: '#4b5563', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '4px', textAlign: 'center' }}>3m</div>
            <div style={{ color: '#4b5563', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '4px', textAlign: 'center' }}>5m</div>

            {[
              { id: 'VOB_PULLBACK_REVERSAL', name: 'VOB Pullback' },
              { id: 'VOB_BREAKOUT_RETEST', name: 'VOB Breakout' },
              { id: 'PA_FAILED_BREAKOUT_TRAP', name: 'Liquidity Trap' },
              { id: 'PA_RANGE_EDGE_ROTATION', name: 'Range Rotation' }
            ].map((strat) => (
              <React.Fragment key={strat.id}>
                <div 
                  style={{ 
                    color: '#fff', 
                    fontWeight: 'bold', 
                    padding: '4px 0',
                    cursor: 'pointer',
                    textDecoration: highlightedStrategy === strat.id ? 'underline #fbbf24' : 'none'
                  }}
                  onClick={() => setHighlightedStrategy(highlightedStrategy === strat.id ? null : strat.id)}
                >
                  {strat.name}
                </div>
                {['1m', '3m', '5m'].map((tf) => {
                  const state = getRadarState(tf, strat.id)
                  const color = 
                    state === 'OPEN' ? '#ef4444' : 
                    state === 'READY' ? '#10b981' : 
                    state === 'ARMED' ? '#fbbf24' : 
                    state === 'WATCH' ? '#22d3ee' : 
                    state === 'TESTING' ? '#8b5cf6' : 
                    state === 'INVALID' ? '#dc2626' : '#4b5563'
                  return (
                    <div 
                      key={tf} 
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedLane(tf as '1m' | '3m' | '5m');
                        setHighlightedStrategy(strat.id);
                      }}
                      style={{ 
                        color, 
                        fontWeight: 'bold', 
                        textAlign: 'center', 
                        padding: '4px 0',
                        background: (selectedLane === tf && activeAssessment?.strategy_id === strat.id) ? 'rgba(34, 211, 238, 0.05)' : 'none',
                        borderRadius: '2px',
                        cursor: 'pointer'
                      }}
                    >
                      {state}
                    </div>
                  )
                })}
              </React.Fragment>
            ))}
          </div>
        </div>

        {/* Decision Spine Progress Trail */}
        <div style={{ background: '#070a10', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '12px 15px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <h3 style={{ margin: '0 0 10px', color: '#fff', fontSize: '12px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--cds-font-mono)' }}>
            <Zap size={13} style={{ color: '#fbbf24' }} />
            DECISION LIFECYCLE SPINE
          </h3>
          
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '4px', width: '100%', padding: '10px 0' }}>
            {stages.map((stage, idx) => {
              const isPassed = stages.indexOf(currentSpineStage) >= idx
              const isCurrent = currentSpineStage === stage
              return (
                <React.Fragment key={stage}>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1 }}>
                    <span style={{ 
                      width: '16px', 
                      height: '16px', 
                      borderRadius: '50%', 
                      background: isCurrent ? '#22d3ee' : isPassed ? '#10b981' : '#1f2937', 
                      border: isCurrent ? '2px solid #fff' : 'none',
                      display: 'flex', 
                      alignItems: 'center', 
                      justifyContent: 'center',
                      fontSize: '9px',
                      fontWeight: 'bold',
                      color: isPassed || isCurrent ? '#000' : '#4b5563',
                      boxShadow: isCurrent ? '0 0 8px #22d3ee' : 'none'
                    }}>
                      {idx + 1}
                    </span>
                    <span style={{ 
                      fontSize: '8px', 
                      color: isCurrent ? '#22d3ee' : isPassed ? '#f3f4f6' : '#4b5563', 
                      marginTop: '4px', 
                      fontWeight: isCurrent ? 'bold' : 'normal',
                      fontFamily: 'var(--cds-font-mono)' 
                    }}>
                      {stage}
                    </span>
                  </div>
                  {idx < stages.length - 1 && (
                    <ArrowRight size={10} style={{ color: isPassed ? '#10b981' : '#1f2937', marginTop: '-12px' }} />
                  )}
                </React.Fragment>
              )
            })}
          </div>
        </div>

      </div>

      {/* 6. INTELLIGENCE PANELS */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '15px', padding: '0 20px', marginBottom: '15px' }}>
        
        {/* PRICE ACTION Panel */}
        <div style={{ background: '#070a10', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '10px 12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '6px', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', fontWeight: 'bold', color: '#3b82f6', fontFamily: 'var(--cds-font-mono)' }}>01 / PRICE ACTION</span>
            <span style={{ fontSize: '12px', fontWeight: 'bold', color: '#fff', fontFamily: 'var(--cds-font-mono)' }}>{Number(activeAssessment?.scores?.pa_score ?? 0).toFixed(2)} <span style={{ color: '#4b5563', fontSize: '9px' }}>/30</span></span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {paFactors.length > 0 ? paFactors.map(([key, f]) => { const factor = f as { status: string; score?: number; val: string | number }; return (
              <div key={key} style={{ fontSize: '10px', borderBottom: '1px dashed rgba(255,255,255,0.02)', paddingBottom: '4px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#fff', fontWeight: 'bold' }}>{key.replace('PA_', '').replaceAll('_', ' ')}</span>
                  <span style={{ color: getFactorColor(factor.status), fontWeight: 'bold' }}>+{Number(factor.score ?? 0).toFixed(2)}</span>
                </div>
                <div style={{ color: '#6b7280', marginTop: '2px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{factor.val}</div>
              </div>
            ); }) : (
              <span style={{ color: '#4b5563', fontSize: '10px', textAlign: 'center', display: 'block', padding: '10px 0' }}>0.00 Points (Neutral/No Activity)</span>
            )}
          </div>
        </div>

        {/* VOB Panel */}
        <div style={{ background: '#070a10', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '10px 12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '6px', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', fontWeight: 'bold', color: '#10b981', fontFamily: 'var(--cds-font-mono)' }}>02 / VOB ZONES</span>
            <span style={{ fontSize: '12px', fontWeight: 'bold', color: '#fff', fontFamily: 'var(--cds-font-mono)' }}>{Number(activeAssessment?.scores?.vob_score ?? 0).toFixed(2)} <span style={{ color: '#4b5563', fontSize: '9px' }}>/25</span></span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {vobFactors.length > 0 ? vobFactors.map(([key, f]) => { const factor = f as { status: string; score?: number; val: string | number }; return (
              <div key={key} style={{ fontSize: '10px', borderBottom: '1px dashed rgba(255,255,255,0.02)', paddingBottom: '4px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#fff', fontWeight: 'bold' }}>{key.replace('VOB_', '').replaceAll('_', ' ')}</span>
                  <span style={{ color: getFactorColor(factor.status), fontWeight: 'bold' }}>+{Number(factor.score ?? 0).toFixed(2)}</span>
                </div>
                <div style={{ color: '#6b7280', marginTop: '2px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{factor.val}</div>
              </div>
            ); }) : (
              <span style={{ color: '#4b5563', fontSize: '10px', textAlign: 'center', display: 'block', padding: '10px 0' }}>0.00 Points (Neutral/No Activity)</span>
            )}
          </div>
        </div>

        {/* DERIVATIVES Panel */}
        <div style={{ background: '#070a10', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '10px 12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '6px', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', fontWeight: 'bold', color: '#a855f7', fontFamily: 'var(--cds-font-mono)' }}>03 / DERIVATIVES</span>
            <span style={{ fontSize: '12px', fontWeight: 'bold', color: '#fff', fontFamily: 'var(--cds-font-mono)' }}>{Number(activeAssessment?.scores?.deriv_score ?? 0).toFixed(2)} <span style={{ color: '#4b5563', fontSize: '9px' }}>/25</span></span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {derivFactors.length > 0 ? derivFactors.map(([key, f]) => { const factor = f as { status: string; score?: number; val: string | number }; return (
              <div key={key} style={{ fontSize: '10px', borderBottom: '1px dashed rgba(255,255,255,0.02)', paddingBottom: '4px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#fff', fontWeight: 'bold' }}>{key.replace('DERIV_', '').replaceAll('_', ' ')}</span>
                  <span style={{ color: getFactorColor(factor.status), fontWeight: 'bold' }}>+{Number(factor.score ?? 0).toFixed(2)}</span>
                </div>
                <div style={{ color: '#6b7280', marginTop: '2px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{factor.val}</div>
              </div>
            ); }) : (
              <span style={{ color: '#4b5563', fontSize: '10px', textAlign: 'center', display: 'block', padding: '10px 0' }}>0.00 Points (Neutral/No Activity)</span>
            )}
          </div>
        </div>

        {/* EXECUTION Panel */}
        <div style={{ background: '#070a10', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '10px 12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '6px', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', fontWeight: 'bold', color: '#fbbf24', fontFamily: 'var(--cds-font-mono)' }}>04 / EXECUTION GATES</span>
            <span style={{ fontSize: '12px', fontWeight: 'bold', color: '#fff', fontFamily: 'var(--cds-font-mono)' }}>{Number(activeAssessment?.scores?.exec_score ?? 0).toFixed(2)} <span style={{ color: '#4b5563', fontSize: '9px' }}>/20</span></span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {execFactors.length > 0 ? execFactors.map(([key, f]) => { const factor = f as { status: string; score?: number; val: string | number }; return (
              <div key={key} style={{ fontSize: '10px', borderBottom: '1px dashed rgba(255,255,255,0.02)', paddingBottom: '4px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#fff', fontWeight: 'bold' }}>{key.replace('EXEC_', '').replaceAll('_', ' ')}</span>
                  <span style={{ color: getFactorColor(factor.status), fontWeight: 'bold' }}>+{Number(factor.score ?? 0).toFixed(2)}</span>
                </div>
                <div style={{ color: '#6b7280', marginTop: '2px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{factor.val}</div>
              </div>
            ); }) : (
              <span style={{ color: '#4b5563', fontSize: '10px', textAlign: 'center', display: 'block', padding: '10px 0' }}>0.00 Points (Neutral/No Activity)</span>
            )}
          </div>
        </div>

      </div>

      {/* 7. GUARDIAN CONSOLE, CONTRIBUTOR MATRIX & TRADE LEDGER */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.6fr 2fr', gap: '15px', padding: '0 20px' }}>
        
        {/* Guardian Console */}
        <div style={{ background: '#070a10', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '12px 15px' }}>
          <h3 style={{ margin: '0 0 12px', color: '#fff', fontSize: '12px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '8px', fontFamily: 'var(--cds-font-mono)' }}>
            <TrendingDown size={14} style={{ color: '#22d3ee' }} />
            GUARDIAN RISK CONSOLE
          </h3>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '11px', fontFamily: 'var(--cds-font-mono)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#4b5563' }}>Strategy Managed:</span>
              <strong style={{ color: '#fff' }}>{activeAssessment?.strategy_name ?? 'LIQUIDITY TRAP'}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#4b5563' }}>Current Action:</span>
              <strong style={{ color: '#fbbf24' }}>{laneStatus?.guardian_action ?? 'Monitoring'}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#4b5563' }}>Trailing Reference:</span>
              <strong style={{ color: '#fff' }}>{laneStatus?.position?.entry_price ? formatMoney(laneStatus.position.entry_price as number) : '—'}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#4b5563' }}>Invalidation Level:</span>
              <strong style={{ color: '#ef4444' }}>{activeAssessment?.plan?.structural_sl ? formatMoney(activeAssessment.plan.structural_sl as number) : '—'}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#4b5563' }}>Next Decision:</span>
              <span style={{ color: '#22d3ee' }}>Evaluate Candle-Close SL</span>
            </div>
            <div style={{ borderTop: '1px solid rgba(255,255,255,0.03)', paddingTop: '6px', marginTop: '4px' }}>
              <span style={{ color: '#4b5563', display: 'block', marginBottom: '2px' }}>Decision Rationale:</span>
              <p style={{ margin: 0, color: '#9ca3af', lineHeight: '1.4' }}>{laneStatus?.guardian_reason ?? 'Awaiting directional trigger event.'}</p>
            </div>
          </div>
        </div>

        {/* Contributor Matrix (WHY) */}
        <div style={{ background: '#070a10', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '12px 15px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div>
            <h3 style={{ margin: '0 0 10px', color: '#fff', fontSize: '12px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '8px', fontFamily: 'var(--cds-font-mono)' }}>
              <BrainCircuit size={14} style={{ color: '#22d3ee' }} />
              CONTRIBUTOR MATRIX (WHY)
            </h3>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '10px', fontFamily: 'var(--cds-font-mono)' }}>
              {[
                {
                  name: 'Price Action',
                  impact: String(execBlocker === 'MARKET_CLOSED' ? 'MARKET CLOSED' : (activeAssessment?.price_action?.regime === 'BULL_TREND' || activeAssessment?.price_action?.regime === 'BULLISH' ? 'Strong Bullish Structure' : (activeAssessment?.price_action?.regime === 'BEAR_TREND' || activeAssessment?.price_action?.regime === 'BEARISH' ? 'Strong Bearish Structure' : (activeAssessment?.price_action?.regime === 'SIDEWAYS' ? 'Sideways Consolidation' : (activeAssessment?.price_action?.regime || 'Awaiting Data'))))),
                  weight: 30,
                  score: activeAssessment?.scores?.pa_score ?? 0.0,
                  provenance: 'NIFTY SPOT & FUT',
                  why: String(activeAssessment?.price_action?.why || 'Scouting swing high/low break levels.'),
                  status: (activeAssessment?.scores?.pa_score ?? 0.0) >= 15 ? 'green' : ((activeAssessment?.scores?.pa_score ?? 0.0) > 0 ? 'amber' : 'grey')
                },
                {
                  name: 'VOB Alignment',
                  impact: String(execBlocker === 'MARKET_CLOSED' ? 'MARKET CLOSED' : (activeAssessment?.vob?.vob_state === 'ACTIVE_ZONE' ? 'Demand Support Active' : (activeAssessment?.vob?.vob_state === 'NO_ACTIVE_ZONE' ? 'No Active Zone' : (activeAssessment?.vob?.vob_state || 'Awaiting Data')))),
                  weight: 25,
                  score: activeAssessment?.scores?.vob_score ?? 0.0,
                  provenance: 'VOB ENGINE',
                  why: String(activeAssessment?.vob?.proximity_desc || 'Monitoring distance to active support/resistance zones.'),
                  status: (activeAssessment?.scores?.vob_score ?? 0.0) >= 12 ? 'green' : ((activeAssessment?.scores?.vob_score ?? 0.0) > 0 ? 'amber' : 'grey')
                },
                {
                  name: 'Derivatives',
                  impact: String(execBlocker === 'MARKET_CLOSED' ? 'MARKET CLOSED' : (activeAssessment?.derivatives?.ssi_oic_desc ? String(activeAssessment.derivatives.ssi_oic_desc).split(',')[0] : 'Balanced Pressure')),
                  weight: 25,
                  score: activeAssessment?.scores?.deriv_score ?? 0.0,
                  provenance: 'OSE ENGINE',
                  why: String(activeAssessment?.derivatives?.options_flow_desc || 'Analyzing net flow, option walls, and order pressure.'),
                  status: (activeAssessment?.scores?.deriv_score ?? 0.0) >= 12 ? 'green' : ((activeAssessment?.scores?.deriv_score ?? 0.0) > 0 ? 'amber' : 'grey')
                },
                {
                  name: 'Execution',
                  impact: String(execBlocker === 'MARKET_CLOSED' ? 'Blocked: Market Closed' : (isExecutionReady ? 'Optimal Execution Ready' : (execBlocker ? `Blocked: ${execBlocker}` : 'Awaiting Data'))),
                  weight: 20,
                  score: activeAssessment?.scores?.exec_score ?? 0.0,
                  provenance: 'EXECUTION GATE',
                  why: isExecutionReady ? 'Integrity, freshness, and spread checks passed.' : `Execution blocked: ${execBlocker || 'INSUFFICIENT_HISTORY'}.`,
                  status: isExecutionReady ? 'green' : (execBlocker === 'MARKET_CLOSED' ? 'red' : 'amber')
                }
              ].map((row) => (
                <div key={row.name} style={{ background: '#0a0e17', border: '1px solid rgba(255,255,255,0.03)', borderRadius: '4px', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ color: '#fff', fontWeight: 'bold' }}>{row.name}</span>
                    <span style={{ color: '#6b7280', fontSize: '8px' }}>{row.provenance}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '9px' }}>
                    <span style={{ color: getFactorColor(row.status) }}>{row.impact}</span>
                    <strong style={{ color: getFactorColor(row.status) }}>{Number(row.score).toFixed(2)}/{row.weight}</strong>
                  </div>
                  <p style={{ margin: '4px 0 0', color: '#6b7280', fontSize: '8.5px', lineHeight: '1.2' }}>
                    <strong>Why:</strong> {row.why}
                  </p>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '8px', marginTop: '10px', fontWeight: 'bold', fontSize: '11px', fontFamily: 'var(--cds-font-mono)' }}>
              <span style={{ color: '#22d3ee' }}>COMPOSITE SCORE</span>
              <strong style={{ color: '#fff' }}>
                {Number(activeAssessment?.scores?.total_score ?? 0).toFixed(2)}/100
              </strong>
            </div>
          </div>
        </div>

        {/* Trade Ledger / Table */}
        <div style={{ background: '#070a10', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '12px 15px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '8px', marginBottom: '10px' }}>
            <h3 style={{ margin: 0, color: '#fff', fontSize: '12px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--cds-font-mono)' }}>
              <TrendingUp size={14} style={{ color: '#10b981' }} />
              COMPLETED PAPER LEDGER
            </h3>
            
            {/* Quick Action controls */}
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <button
                type="button"
                disabled={syncCooldown}
                style={{
                  background: syncCooldown ? 'rgba(255,255,255,0.03)' : 'rgba(251, 191, 36, 0.1)',
                  color: syncCooldown ? '#4b5563' : '#fbbf24',
                  border: `1px solid ${syncCooldown ? 'rgba(255,255,255,0.05)' : 'rgba(251, 191, 36, 0.3)'}`,
                  borderRadius: '3px',
                  padding: '4px 10px',
                  fontSize: '10px',
                  fontWeight: 'bold',
                  cursor: syncCooldown ? 'not-allowed' : 'pointer'
                }}
                onClick={() => void forceSync?.()}
              >
                {syncStatus === 'loading' ? 'Syncing...' : syncStatus === 'success' ? 'Sync Success' : syncStatus === 'failure' ? 'Sync Failed' : 'Force Sync System'}
              </button>

              {laneStatus?.position ? (
                <button 
                  type="button" 
                  style={{ background: '#dc2626', color: '#fff', border: 'none', borderRadius: '3px', padding: '4px 10px', fontSize: '10px', fontWeight: 'bold', cursor: 'pointer' }}
                  onClick={() => void exitNow()}
                >
                  Force Exit Position
                </button>
              ) : activeAssessment?.plan && activeAssessment.plan.entry_price ? (
                <div style={{ display: 'flex', gap: '5px' }}>
                  <button 
                    type="button" 
                    style={{ background: '#059669', color: '#fff', border: 'none', borderRadius: '3px', padding: '4px 10px', fontSize: '10px', fontWeight: 'bold', cursor: 'pointer' }}
                    onClick={() => void paperExecute()}
                  >
                    Execute Planned Trade
                  </button>
                  <button 
                    type="button" 
                    style={{ background: '#374151', color: '#d1d5db', border: 'none', borderRadius: '3px', padding: '4px 10px', fontSize: '10px', cursor: 'pointer' }}
                    onClick={() => void cancel()}
                  >
                    Cancel Plan
                  </button>
                </div>
              ) : (
                <button 
                  type="button" 
                  style={{ background: '#2563eb', color: '#fff', border: 'none', borderRadius: '3px', padding: '4px 10px', fontSize: '10px', fontWeight: 'bold', cursor: 'pointer' }}
                  onClick={() => void analyse()}
                >
                  Trigger Setup Assessment
                </button>
              )}
            </div>
          </div>

          {/* Trade History Table */}
          <div style={{ overflowX: 'auto', maxHeight: '180px', scrollbarWidth: 'thin' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '10px', fontFamily: 'var(--cds-font-mono)', textAlign: 'left' }}>
              <thead>
                <tr style={{ color: '#4b5563', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                  <th style={{ padding: '6px' }}>Mission ID</th>
                  <th style={{ padding: '6px' }}>Strategy (Subtype)</th>
                  <th style={{ padding: '6px' }}>Dir</th>
                  <th style={{ padding: '6px' }}>TF</th>
                  <th style={{ padding: '6px' }}>Option</th>
                  <th style={{ padding: '6px' }}>Entry/SL/Tgt (Fut)</th>
                  <th style={{ padding: '6px' }}>Premium (En/Ex)</th>
                  <th style={{ padding: '6px' }}>Status/Guardian</th>
                  <th style={{ padding: '6px', textAlign: 'right' }}>P&L</th>
                </tr>
              </thead>
              <tbody>
                {chartData?.trades && chartData.trades.length > 0 ? (
                  chartData.trades.map((t) => (
                    <tr 
                      key={t.mission_id} 
                      onClick={() => handleTradeClick(t)}
                      style={{ 
                        color: '#fff', 
                        borderBottom: '1px solid rgba(255,255,255,0.02)',
                        cursor: 'pointer',
                        background: overrideSelectedTradeId === t.mission_id ? 'rgba(34, 211, 238, 0.08)' : 'transparent'
                      }}
                    >
                      <td style={{ padding: '6px', color: '#22d3ee' }}>{t.mission_id.substring(0, 8)}</td>
                      <td style={{ padding: '6px', fontWeight: 'bold' }}>
                        {t.strategy_name} <span style={{ fontSize: '8px', color: '#6b7280', display: 'block' }}>{t.setup_subtype}</span>
                      </td>
                      <td style={{ padding: '6px', color: t.direction === 'PUT' ? '#ef4444' : '#10b981', fontWeight: 'bold' }}>{t.direction}</td>
                      <td style={{ padding: '6px' }}>{t.timeframe}</td>
                      <td style={{ padding: '6px', color: '#fbbf24' }}>{t.option_contract}</td>
                      <td style={{ padding: '6px' }}>
                        {t.entry} / <span style={{ color: '#ef4444' }}>{t.structural_sl}</span> / <span style={{ color: '#10b981' }}>{t.target}</span>
                      </td>
                      <td style={{ padding: '6px' }}>
                        {t.option_entry_premium ? `₹${t.option_entry_premium}` : '—'} / {t.option_exit_premium ? `₹${t.option_exit_premium}` : '—'}
                      </td>
                      <td style={{ padding: '6px' }}>
                        <span style={{ display: 'block', fontWeight: 'bold', color: '#fbbf24' }}>{t.guardian_action}</span>
                        <span style={{ fontSize: '8px', color: '#9ca3af' }}>{t.exit_reason}</span>
                      </td>
                      <td style={{ padding: '6px', textAlign: 'right', color: (t.pnl ?? 0) >= 0 ? '#10b981' : '#ef4444', fontWeight: 'bold' }}>
                        {t.pnl !== undefined && t.pnl !== null ? formatMoney(t.pnl) : '—'}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={9} style={{ padding: '20px', color: '#4b5563', textAlign: 'center' }}>NO REAL PAPER TRADES RECORDED</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

      </div>

    </div>
  )
}
