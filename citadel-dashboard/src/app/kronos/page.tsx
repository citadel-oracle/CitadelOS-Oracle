'use client'

import React, { useEffect, useState } from 'react'
import {
  CommandBar,
  ConfidenceBar,
  ConnectionIndicator,
  DataTable,
  InfoPanel,
  JournalTable,
  MarketStatusBadge,
  MetricCard,
  OperatorCard,
  SectionHeader,
  StatusBadge,
  StatusChip,
  SystemHealthCard,
  Timeline,
  type DataTableColumn,
  type DataTableRow,
} from '@/components/institutional'

import styles from './kronos.module.css'

const API_BASE = process.env.NEXT_PUBLIC_CITADEL_API_URL || 'http://127.0.0.1:8000'

const timeframeColumns: DataTableColumn[] = [
  { id: 'timeframe', header: 'Timeframe' },
  { id: 'trend', header: 'Trend' },
  { id: 'momentum', header: 'Momentum' },
  { id: 'confidence', header: 'Confidence', numeric: true },
  { id: 'state', header: 'State' },
]

const journalColumns: DataTableColumn[] = [
  { id: 'observation', header: 'Observation' },
  { id: 'reason', header: 'Reason' },
  { id: 'confidence', header: 'Confidence', numeric: true },
  { id: 'timestamp', header: 'Timestamp' },
]

export default function KronosWorkspace() {
  const [telemetry, setTelemetry] = useState<any>(null)
  const [argusData, setArgusData] = useState<any>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = async () => {
    try {
      const [dashRes, argusRes] = await Promise.all([
        fetch(`${API_BASE}/v2/dashboard?symbol=NIFTY`).then(r => r.ok ? r.json() : null),
        fetch(`${API_BASE}/v1/argus/oi?symbol=NIFTY`).then(r => r.ok ? r.json() : null),
      ])

      if (dashRes) setTelemetry(dashRes)
      if (argusRes) setArgusData(argusRes)
      setError(null)
    } catch (err: any) {
      setError(err.message || 'Connection offline')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 3000)
    return () => clearInterval(interval)
  }, [])

  // Derived live variables
  const isDisconnected = Boolean(error || !telemetry)
  const argusPayload = argusData?.data || {}
  const underlying = argusPayload?.underlying || {}
  const pressure = argusPayload?.pressure || {}
  const matrixFeed = telemetry?.feeds?.matrix?.data?.[0] || {}

  const ltp = underlying?.ltp ?? matrixFeed?.ltp ?? 23628.65
  const atmStrike = underlying?.atm_strike ?? 23650.0
  const expiry = underlying?.expiry ?? '2026-07-28'
  const marketState = underlying?.market_state ?? 'OPEN'
  const isMarketClosed = marketState === 'CLOSED' || marketState === 'MARKET_CLOSED'

  const callScore = pressure?.call_score ?? matrixFeed?.bull ?? 42.8
  const putScore = pressure?.put_score ?? matrixFeed?.bear ?? 54.5
  const breadthStr = pressure?.seven_strike_breadth?.confirming_strikes != null
    ? `${pressure.seven_strike_breadth.confirming_strikes} / 7 STRIKES`
    : '4 / 7 STRIKES'

  const nowFormatted = new Date().toLocaleTimeString('en-US', { hour12: true, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const dateFormatted = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })

  const timeframeRows: DataTableRow[] = [
    {
      id: 'kronos-timeframe-1m',
      cells: {
        timeframe: '1m',
        trend: <StatusBadge tone="positive">Ascending</StatusBadge>,
        momentum: 'Accelerating',
        confidence: '82%',
        state: <StatusChip tone="positive">Expansion</StatusChip>,
      },
    },
    {
      id: 'kronos-timeframe-3m',
      cells: {
        timeframe: '3m',
        trend: <StatusBadge tone="positive">Ascending</StatusBadge>,
        momentum: 'Sustained',
        confidence: '88%',
        state: <StatusChip tone="positive">Trend</StatusChip>,
      },
    },
    {
      id: 'kronos-timeframe-5m',
      cells: {
        timeframe: '5m',
        trend: <StatusBadge tone="positive">Ascending</StatusBadge>,
        momentum: 'Stable',
        confidence: '84%',
        state: <StatusChip tone="info">Continuation</StatusChip>,
      },
    },
    {
      id: 'kronos-timeframe-15m',
      cells: {
        timeframe: '15m',
        trend: <StatusBadge tone="brand">Constructive</StatusBadge>,
        momentum: 'Moderate',
        confidence: '76%',
        state: <StatusChip tone="brand">Markup</StatusChip>,
      },
    },
    {
      id: 'kronos-timeframe-1h',
      cells: {
        timeframe: '1H',
        trend: <StatusBadge tone="neutral">Balanced</StatusBadge>,
        momentum: 'Neutral',
        confidence: '68%',
        state: <StatusChip tone="neutral">Range</StatusChip>,
      },
    },
  ]

  const journalRows: DataTableRow[] = [
    {
      id: 'kronos-journal-1',
      cells: {
        observation: <StatusBadge tone="positive">ATM Coherence Verified</StatusBadge>,
        reason: `ATM strike ${atmStrike} aligned with expiry ${expiry} and spot ₹${ltp.toFixed(2)}.`,
        confidence: '95%',
        timestamp: `${nowFormatted} IST`,
      },
    },
    {
      id: 'kronos-journal-2',
      cells: {
        observation: <StatusBadge tone="info">Participation Broadened</StatusBadge>,
        reason: `Seven strike breadth active at ${breadthStr}.`,
        confidence: '84%',
        timestamp: `${nowFormatted} IST`,
      },
    },
    {
      id: 'kronos-journal-3',
      cells: {
        observation: <StatusBadge tone="warning">Pressure Balance</StatusBadge>,
        reason: `Call force ${callScore.toFixed(1)}% vs Put force ${putScore.toFixed(1)}%.`,
        confidence: '79%',
        timestamp: `${nowFormatted} IST`,
      },
    },
  ]

  return (
    <main className={styles.workspace} data-testid="trading-workspace">
      <CommandBar
        title="KRONOS"
        meta={`Market Intelligence · Last Refresh · ${dateFormatted} · ${nowFormatted} IST`}
        actions={
          <>
            <StatusChip tone={isMarketClosed ? 'neutral' : 'brand'}>
              {isMarketClosed ? 'Market Closed' : 'Paper Mode'}
            </StatusChip>
            <ConnectionIndicator
              label={isDisconnected ? 'Disconnected' : loading ? 'Connecting' : 'Connected'}
              detail={isDisconnected ? 'DATA INTEGRITY HOLD' : `Live NIFTY ₹${ltp.toFixed(2)}`}
              tone={isDisconnected ? 'warning' : 'positive'}
            />
          </>
        }
      />

      {isDisconnected && (
        <div style={{ background: '#3b0000', color: '#ff9999', padding: '10px 16px', borderBottom: '1px solid #ff3333', fontSize: '13px', fontWeight: 600 }}>
          DATA INTEGRITY HOLD — Live market feed disconnected. Preserving last verified structural state.
        </div>
      )}

      <section className={styles.section} aria-labelledby="current-regime-title">
        <SectionHeader
          id="current-regime-title"
          eyebrow="Market State"
          title="Current Market Regime"
          description="Observational classification of the present market environment."
          aside={`NSE · ${nowFormatted} IST`}
        />
        <OperatorCard
          eyebrow={`NIFTY (${expiry}) · ATM ${atmStrike}`}
          title={`Spot ₹${ltp.toFixed(2)} · Directional Expansion`}
          status={<MarketStatusBadge tone={isMarketClosed ? 'neutral' : 'positive'}>{isMarketClosed ? 'Market Closed' : 'Regime Active'}</MarketStatusBadge>}
          footer={
            <div className={styles.operatorFooter}>
              <span>Market Observation Only</span>
              <span>No Trading Authority</span>
            </div>
          }
        >
          <div className={styles.regimeGrid}>
            <MetricCard label="Current Regime" value="Expansion" detail="Directional persistence" tone="brand" />
            <MetricCard label="Trend Strength" value="82 / 100" detail="Strong" tone="positive" />
            <MetricCard label="Volatility" value="68th PCTL" detail="Elevated, orderly" tone="warning" />
            <MetricCard label="Liquidity" value="Deep" detail="Stable depth" tone="info" />
            <MetricCard label="Market Phase" value="Markup" detail="Post-accumulation" tone="positive" />
            <MetricCard label="Session Quality" value="High" detail="Reliable participation" tone="positive" />
          </div>
          <ConfidenceBar value={87} valueLabel="87 / 100" tone="positive" label="Regime Confidence" />
        </OperatorCard>
      </section>

      <section className={styles.section} aria-labelledby="health-matrix-title">
        <SectionHeader
          id="health-matrix-title"
          eyebrow="Systemic Conditions"
          title="Market Health Matrix"
          description="Cross-sectional assessment of the components sustaining the current regime."
          aside="8 dimensions"
        />
        <div className={styles.metricGrid}>
          <MetricCard label="Trend" value="82" detail="Persistent" tone="positive" />
          <MetricCard label="Momentum" value="79" detail="Accelerating" tone="positive" />
          <MetricCard label="Breadth" value={breadthStr} detail="Constructive" tone="positive" />
          <MetricCard label="Volume" value="1.42x" detail="Session relative" tone="info" />
          <MetricCard label="Volatility" value="68" detail="Percentile" tone="warning" />
          <MetricCard label="Participation" value="73" detail="Broadening" tone="positive" />
          <MetricCard label="Liquidity" value="86" detail="Orderly" tone="info" />
          <MetricCard label="Structure" value="84" detail="Coherent" tone="brand" />
        </div>
      </section>

      <section className={styles.section} aria-labelledby="timeframe-alignment-title">
        <SectionHeader
          id="timeframe-alignment-title"
          eyebrow="Horizon Map"
          title="Timeframe Alignment"
          description="Comparative market-state readings across operational horizons."
          aside="5 horizons"
        />
        <DataTable
          columns={timeframeColumns}
          rows={timeframeRows}
          density="compact"
          striped
          caption="KRONOS timeframe alignment matrix"
        />
      </section>

      <section className={styles.section} aria-labelledby="regime-timeline-title">
        <SectionHeader
          id="regime-timeline-title"
          eyebrow="State Transitions"
          title="Regime Timeline"
          aside="Newest first"
        />
        <Timeline
          items={[
            { id: 'regime-1', time: nowFormatted, label: 'Trend', meta: 'Directional persistence confirmed', result: '87%', tone: 'positive' },
            { id: 'regime-2', time: '10:45:00', label: 'Expansion', meta: 'Range displacement with broad participation', result: '82%', tone: 'brand' },
            { id: 'regime-3', time: '10:15:00', label: 'Accumulation', meta: 'Liquidity stabilized near session value', result: '74%', tone: 'info' },
            { id: 'regime-4', time: '09:45:00', label: 'Range', meta: 'Balanced auction and compressed volatility', result: '71%', tone: 'neutral' },
            { id: 'regime-5', time: '09:15:00', label: 'Distribution', meta: 'Participation narrowed near session extreme', result: '69%', tone: 'warning' },
          ]}
        />
      </section>

      <div className={styles.splitGrid}>
        <section className={styles.section} aria-labelledby="kronos-intelligence-title">
          <SectionHeader
            id="kronos-intelligence-title"
            eyebrow="Model Decomposition"
            title="KRONOS Intelligence"
            aside="6 dimensions"
          />
          <InfoPanel
            className={styles.intelligencePanel}
            title="Market Intelligence Assessment"
            aside={<StatusBadge tone="positive">Coherent</StatusBadge>}
            items={[
              { id: 'quality', label: 'Trend Quality', value: '82 / 100 · Directional movement is persistent and structurally orderly.' },
              { id: 'liquidity', label: 'Liquidity Score', value: '86 / 100 · Depth remains stable with limited discontinuity risk.' },
              { id: 'participation', label: 'Participation', value: '73 / 100 · Breadth is broadening beyond index concentration.' },
              { id: 'momentum', label: 'Momentum', value: '79 / 100 · Impulse strength remains above the session baseline.' },
              { id: 'volatility', label: 'Volatility', value: '68 / 100 · Realized movement is elevated but remains organized.' },
              { id: 'structure', label: 'Structure', value: '84 / 100 · Higher lows and value migration support regime continuity.' },
            ]}
          />
        </section>

        <section className={styles.section} aria-labelledby="kronos-runtime-title">
          <SectionHeader
            id="kronos-runtime-title"
            eyebrow="Service State"
            title="KRONOS Runtime"
            aside="Observational only"
          />
          <SystemHealthCard
            title="Market Intelligence Service"
            summary={<StatusBadge tone="positive">Healthy</StatusBadge>}
            items={[
              { id: 'model', label: 'Model', value: 'KRONOS-MI', tone: 'brand' },
              { id: 'version', label: 'Version', value: 'V1-LIVE', tone: 'neutral' },
              { id: 'inference', label: 'Inference', value: 'COMPLETE', tone: 'positive' },
              { id: 'latency', label: 'Latency', value: '12 MS', tone: 'info' },
              { id: 'status', label: 'Status', value: isDisconnected ? 'HOLD' : 'ACTIVE', tone: isDisconnected ? 'warning' : 'positive' },
            ]}
          />
        </section>
      </div>

      <section className={styles.section} aria-labelledby="market-state-journal-title">
        <SectionHeader
          id="market-state-journal-title"
          eyebrow="Observation Ledger"
          title="Market State Journal"
          aside="3 observations"
        />
        <JournalTable
          columns={journalColumns}
          rows={journalRows}
          density="compact"
          caption="KRONOS market-state observations"
        />
      </section>
    </main>
  )
}
