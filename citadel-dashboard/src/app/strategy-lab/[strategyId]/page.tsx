'use client'

import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useEffect, useState } from 'react'

const API_URL = process.env.NEXT_PUBLIC_CITADEL_API_URL ?? 'http://127.0.0.1:8000'

type StrategyDetail = {
  status: string
  strategy: {
    strategy_id: string
    state: string
    health: string
    readiness: string
    reason: string
    paper_only: true
    live_trading_enabled: false
    broker_submission: false
    metadata: {
      name: string
      version: string
      author: string
      input_type: string
      supported_markets: string[]
      supported_timeframes: string[]
      rr: number | null
      risk_model: string
      status: string
      deployment_date: string
    }
  }
  overview: Record<string, unknown>
  statistics: Record<string, unknown>
  journal: unknown[]
  replay: unknown[]
  evidence: unknown[]
  trades: unknown[]
  equity_curve: unknown[]
  parameters: Record<string, unknown>
  logs: unknown[]
  order_ledger: unknown[]
  fill_ledger: unknown[]
}

function pretty(value: unknown) {
  return JSON.stringify(value, null, 2)
}

function valueLabel(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 3 }).format(value)
  if (typeof value === 'string') return value
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE'
  return '—'
}

export default function StrategyLabDetailPage() {
  const params = useParams<{ strategyId: string }>()
  const strategyId = decodeURIComponent(params.strategyId)
  const [detail, setDetail] = useState<StrategyDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const load = async () => {
      try {
        const response = await fetch(`${API_URL}/v1/strategy-lab/strategies/${encodeURIComponent(strategyId)}`, { cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error(response.status === 404 ? 'Strategy runtime not found' : `Backend returned HTTP ${response.status}`)
        const payload = await response.json() as StrategyDetail
        if (active) { setDetail(payload); setError(null) }
      } catch (reason) {
        if (active && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Strategy Lab unavailable')
      }
    }
    void load()
    const interval = window.setInterval(load, 5_000)
    return () => { active = false; controller.abort(); window.clearInterval(interval) }
  }, [strategyId])

  if (!detail) {
    return <main className="strategy-lab-detail"><nav className="strategy-lab-detail-nav"><Link href="/">← CITADEL dashboard</Link></nav><section className="strategy-lab-detail-card"><h2>Strategy Lab</h2><pre>{error ?? 'Loading authoritative research record…'}</pre></section></main>
  }

  const metadata = detail.strategy.metadata
  const statistics = detail.statistics
  const statKeys = ['completed_trades', 'win_rate', 'profit_factor', 'expectancy', 'rr', 'mfe', 'mae', 'net_pnl', 'drawdown', 'sharpe']

  return (
    <main className="strategy-lab-detail">
      <nav className="strategy-lab-detail-nav"><Link href="/">← CITADEL dashboard</Link><a href="#logs">Logs ↓</a></nav>
      <header className="strategy-lab-detail-header">
        <div><span>STRATEGY LAB / RESEARCH RECORD</span><h1>{metadata.name}</h1><p>v{metadata.version} · {metadata.author} · {metadata.input_type.replaceAll('_', ' ')}</p></div>
        <strong>{detail.strategy.state} · {detail.strategy.health}</strong>
      </header>

      {error && <section className="strategy-lab-detail-card"><h2>Projection warning</h2><pre>{error}</pre></section>}

      <div className="strategy-lab-detail-grid">
        <section className="strategy-lab-detail-card"><h2>Overview</h2><pre>{pretty({ strategy_id: detail.strategy.strategy_id, readiness: detail.strategy.readiness, reason: detail.strategy.reason, paper_only: detail.strategy.paper_only, live_trading_enabled: detail.strategy.live_trading_enabled, broker_submission: detail.strategy.broker_submission, metadata, overview: detail.overview })}</pre></section>
        <section className="strategy-lab-detail-card"><h2>Statistics</h2><div className="strategy-lab-detail-stats">{statKeys.map((key) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{valueLabel(statistics[key])}</strong></div>)}</div></section>
        <section className="strategy-lab-detail-card"><h2>Parameters</h2><pre>{pretty(detail.parameters)}</pre></section>
        <section className="strategy-lab-detail-card"><h2>Equity curve</h2><pre>{pretty(detail.equity_curve)}</pre></section>
        <section className="strategy-lab-detail-card wide"><h2>Trade list</h2><pre>{pretty(detail.trades)}</pre></section>
        <section className="strategy-lab-detail-card"><h2>Journal</h2><pre>{pretty(detail.journal)}</pre></section>
        <section className="strategy-lab-detail-card"><h2>Replay</h2><pre>{pretty(detail.replay)}</pre></section>
        <section className="strategy-lab-detail-card wide"><h2>Evidence</h2><pre>{pretty(detail.evidence)}</pre></section>
        <section className="strategy-lab-detail-card"><h2>Order ledger</h2><pre>{pretty(detail.order_ledger)}</pre></section>
        <section className="strategy-lab-detail-card"><h2>Fill ledger</h2><pre>{pretty(detail.fill_ledger)}</pre></section>
        <section className="strategy-lab-detail-card wide" id="logs"><h2>Logs</h2><pre>{pretty(detail.logs)}</pre></section>
      </div>
    </main>
  )
}
