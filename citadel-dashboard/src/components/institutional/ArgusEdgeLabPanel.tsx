'use client'

import { useState } from 'react'
import styles from './ArgusEdgeLabPanel.module.css'

type EdgeStrategy = {
  strategy_id: string
  name: string
  side: 'CALL' | 'PUT'
  variant: string
  version: string
  configuration_hash: string
  runtime_state: string
  trigger: string
  scores: Record<string, number>
  rejection_reasons: string[]
  next_required_condition: string
  contract: {
    trading_symbol?: string
    symbol?: string
    strike?: number
    option_type?: string
  } | null
  portfolio: {
    portfolio_id: string
    initial_capital: number
    equity: number
    open_position: Record<string, unknown> | null
    risk_cap: number
    maximum_lots: number
  }
  analytics: {
    completed_trades: number
    net_pnl: number
    average_r: number | null
    maximum_drawdown: number
    capture_ratio: number | null
    false_triggers: number
    good_skips: number
    missed_moves: number
    late_entries: number
    no_trade_correctness: number | null
  }
}

export type ArgusEdgeLabData = {
  status: string
  reason: string
  generated_at: string
  snapshot_id: string | null
  source_timestamp: string | null
  expiry?: string | null
  summary: {
    strategies: number
    capital_per_strategy: number
    total_experiment_capital: number
    open_positions: number
    completed_trades: number
    session_pnl: number
    best_strategy: string | null
    best_discipline: string | null
  }
  lanes: { CALL: EdgeStrategy[]; PUT: EdgeStrategy[] }
  leaderboard: Array<EdgeStrategy['analytics'] & { rank: number; strategy_id: string; name: string }>
  report: {
    status: string
    sessions: number
    completed_trades: number
    minimum_sessions: number
    minimum_trades: number
    regime?: string
  }
  safety: {
    paper_only: boolean
    live_trading_enabled: boolean
    broker_submission: boolean
    execution_influence: string
  }
}

export type ArgusEdgeLabPanelProps = {
  data: ArgusEdgeLabData | null | undefined
  loading?: boolean
  error?: string | null
}

const readable = (value: string | null | undefined) =>
  (value || 'UNAVAILABLE').replaceAll('_', ' ')

const money = (value: number | null | undefined) =>
  typeof value === 'number'
    ? new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
    : '—'

const score = (value: number | null | undefined) =>
  typeof value === 'number' ? value.toFixed(1) : '—'

const time = (value: string | null | undefined) => {
  if (!value) return 'AWAITING SNAPSHOT'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? 'INVALID TIMESTAMP'
    : parsed.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function StrategyCell({ row }: { row: EdgeStrategy }) {
  const live = ['TRIGGERED', 'ORDER_WORKING', 'POSITION_OPEN', 'GUARDIAN_ACTIVE'].includes(row.runtime_state)
  return (
    <article className={`${styles.strategy} ${styles[row.side.toLowerCase()]} ${live ? styles.active : ''}`}>
      <header>
        <div>
          <span>{row.variant.replaceAll('_', ' ')}</span>
          <strong title={row.strategy_id}>{row.strategy_id.split('_')[2] ?? row.strategy_id}</strong>
        </div>
        <b>{readable(row.runtime_state)}</b>
      </header>
      <div className={styles.scoreline}>
        <div><span>Edge</span><strong>{score(row.scores.edge)}</strong></div>
        <div><span>Sep</span><strong>{score(row.scores.separation)}</strong></div>
        <div><span>Ready</span><strong>{score(row.scores.readiness)}</strong></div>
        <div><span>Structure</span><strong>{score(row.scores.structure)}</strong></div>
      </div>
      <div className={styles.stateLine}>
        <span>{row.contract ? `${row.contract.strike ?? '—'} ${row.contract.option_type ?? row.side}` : readable(row.next_required_condition)}</span>
        <strong>{row.portfolio.open_position ? '1 POSITION' : readable(row.trigger)}</strong>
      </div>
      <footer>
        <span title={row.next_required_condition}>{row.analytics.completed_trades} TRADES · {row.analytics.capture_ratio == null ? 'CAPTURE —' : `CAPTURE ${(row.analytics.capture_ratio * 100).toFixed(0)}%`} · R {score(row.analytics.average_r)}</span>
        <b className={row.analytics.net_pnl < 0 ? styles.negative : row.analytics.net_pnl > 0 ? styles.positive : ''}>{money(row.analytics.net_pnl)}</b>
      </footer>
    </article>
  )
}

export function ArgusEdgeLabPanel({ data, loading = false, error = null }: ArgusEdgeLabPanelProps) {
  const [expanded, setExpanded] = useState(false)
  if (loading && !data) {
    return <section className={styles.shell} aria-label="ARGUS Edge Lab"><div className={styles.empty}>CONNECTING TO ARGUS EDGE LAB</div></section>
  }
  if (!data) {
    return <section className={styles.shell} aria-label="ARGUS Edge Lab"><div className={styles.empty}>{error ? `EDGE LAB UNAVAILABLE · ${error}` : 'EDGE LAB PROJECTION UNAVAILABLE'}</div></section>
  }
  const healthySafety = data.safety.paper_only && !data.safety.live_trading_enabled && !data.safety.broker_submission
  return (
    <section className={styles.shell} aria-label="ARGUS Edge Lab">
      <header className={styles.heading}>
        <div><span>ARGUS / LIVE-PAPER RESEARCH</span><h2>ARGUS EDGE LAB</h2></div>
        <div className={styles.headingMeta}>
          <b className={styles[data.status.toLowerCase()] ?? ''}>{readable(data.status)}</b>
          <span>SNAPSHOT {data.snapshot_id?.slice(0, 10) ?? 'PENDING'}</span>
          <span>{time(data.source_timestamp)}</span>
        </div>
      </header>

      <div className={styles.commandStrip}>
        <div><span>Experiment</span><strong>10 APEX STRATEGIES</strong><small>5 CALL · 5 PUT</small></div>
        <div><span>Virtual capital</span><strong>{money(data.summary.total_experiment_capital)}</strong><small>{money(data.summary.capital_per_strategy)} isolated</small></div>
        <div><span>Provisional regime</span><strong>{readable(data.report.regime ?? 'PENDING')}</strong><small>Post-session final</small></div>
        <div><span>Session P&amp;L</span><strong className={data.summary.session_pnl < 0 ? styles.negative : data.summary.session_pnl > 0 ? styles.positive : ''}>{money(data.summary.session_pnl)}</strong><small>Experiment only</small></div>
        <div><span>Paper book</span><strong>{data.summary.open_positions} OPEN</strong><small>{data.summary.completed_trades} completed</small></div>
        <div><span>Current leader</span><strong>{data.summary.best_strategy?.replace('ARGUS_APEX_', '') ?? 'INSUFFICIENT SAMPLE'}</strong><small>{readable(data.report.status)}</small></div>
        <div><span>Best discipline</span><strong>{data.summary.best_discipline?.replace('ARGUS_APEX_', '') ?? 'INSUFFICIENT SAMPLE'}</strong><small>No-trade quality</small></div>
        <div><span>Source freshness</span><strong className={healthySafety ? styles.positive : styles.negative}>{readable(data.status)}</strong><small>{time(data.source_timestamp)} · PAPER {healthySafety ? 'LOCKED' : 'CHECK'}</small></div>
      </div>

      <div className={styles.board}>
        <div className={`${styles.lane} ${styles.callLane}`}>
          <header><span>CALL LANE</span><strong>CE OPTION BUYERS</strong><b>{data.lanes.CALL.filter((row) => row.runtime_state === 'TRIGGERED').length} READY</b></header>
          <div>{data.lanes.CALL.map((row) => <StrategyCell key={row.strategy_id} row={row} />)}</div>
        </div>
        <div className={`${styles.lane} ${styles.putLane}`}>
          <header><span>PUT LANE</span><strong>PE OPTION BUYERS</strong><b>{data.lanes.PUT.filter((row) => row.runtime_state === 'TRIGGERED').length} READY</b></header>
          <div>{data.lanes.PUT.map((row) => <StrategyCell key={row.strategy_id} row={row} />)}</div>
        </div>
      </div>

      <button className={styles.disclosure} type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
        <span>EDGE REPORT · {readable(data.report.regime ?? 'REGIME PENDING')}</span>
        <strong>{expanded ? 'COLLAPSE' : 'OPEN LEADERBOARD'}</strong>
      </button>
      {expanded ? (
        <div className={styles.leaderboard}>
          <div className={styles.leaderHeader}><span>Rank</span><span>Strategy</span><span>Trades</span><span>Net P&amp;L</span><span>Avg R</span><span>Capture</span><span>False</span><span>Missed</span></div>
          {data.leaderboard.map((row) => (
            <div key={row.strategy_id}><b>{row.rank}</b><strong>{row.name}</strong><span>{row.completed_trades}</span><span>{money(row.net_pnl)}</span><span>{score(row.average_r)}</span><span>{row.capture_ratio == null ? '—' : `${(row.capture_ratio * 100).toFixed(1)}%`}</span><span>{row.false_triggers}</span><span>{row.missed_moves}</span></div>
          ))}
        </div>
      ) : null}
      <footer className={styles.truth}>
        <span>{readable(data.reason)}</span>
        <span>EXPIRY {data.expiry ?? 'UNAVAILABLE'}</span>
        <strong>NO LIVE ROUTING · NO CROSS-PORTFOLIO CAPITAL</strong>
      </footer>
    </section>
  )
}
