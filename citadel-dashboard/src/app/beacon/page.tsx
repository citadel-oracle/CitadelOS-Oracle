'use client'

import React, { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Activity, Cpu, Radio, ShieldCheck } from 'lucide-react'

interface BeaconState {
  system_status: string
  reasoning_status: string
  market_verdict: string | null
  developing_state: string
  why_bullets: string[]
  main_contradiction: string
  what_changed: string
  thesis_timestamp_ist: string
  feed_age_ms: number | null
  configured_model: string
  actually_invoked_model: string
  replay_mode?: boolean
  schema_version: string
}

interface HealthStripState {
  data_stream: string
  brain_worker: string
  ai_provider: string
  reasoning_state: string
  model_name: string
  last_event_time: string
  last_analysis_time: string
  last_latency_ms: number | null
  pending_events_count: number
  successful_ai_calls: number
}

interface SolDetailedState {
  beacon: BeaconState
  health_strip?: HealthStripState
  thesis?: {
    thesis_id: string
    core_narrative: string
    positioning_story: string
    oi_story: string
    flow_story: string
    option_response_story: string
    call_case: string
    put_case: string
    no_trade_case: string
    strongest_contradiction: string
    active_expectations?: Array<{
      expectation_id: string
      expected_condition: string
      invalidation_condition: string
    }>
    evaluation_history?: Array<{
      evaluation_id: string
      expectation_id: string
      result: string
      evaluation_notes: string
    }>
    data_gaps?: string[]
    evidence_references?: string[]
  }
  active_market_story?: {
    story_revision: number
    session_open_summary: string
    structure_evolution_summary: string
    flow_regime_summary: string
    positioning_summary: string
    total_events_processed: number
  }
  persistence?: {
    jsonl_health: string
    thesis_store_status: string
    baseline_store_status: string
    duckdb_health: string
    last_successful_write_utc: string
    last_persistence_error: string | null
  }
  external_context?: {
    status: string
    source_verification_status?: string
    external_context_id?: string
    last_received_ist: string
    last_source_time_ist: string
    total_items: number
    verified_items_count?: number
    unverified_items_count?: number
    conflicted_items_count?: number
    verified_sources_count: number
    data_gaps_count: number
    provider: string
    is_test_fixture: boolean
    summary_titles: string[]
    conflicted_items?: Array<{
      fact_id: string
      title: string
      spark_claim: string
      authoritative_source?: string
      authoritative_value?: string
      conflict_detail?: any
    }>
    provenance_hash?: string
  }
}

export default function BeaconPage() {
  const [beacon, setBeacon] = useState<BeaconState>({
    system_status: 'UNAVAILABLE',
    reasoning_status: 'NOT_INVOKED',
    market_verdict: null,
    developing_state: 'UNRESOLVED',
    why_bullets: ['Connecting to backend Market Brain stream...'],
    main_contradiction: 'ENGINE_INITIALIZING',
    what_changed: 'Initializing client stream.',
    thesis_timestamp_ist: '--:--:--',
    feed_age_ms: null,
    configured_model: 'gemini-3.7-flash',
    actually_invoked_model: 'NONE',
    replay_mode: false,
    schema_version: '3.2.0-beacon-gemini',
  })

  const [detailedState, setDetailedState] = useState<SolDetailedState | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [streamConnected, setStreamConnected] = useState<boolean>(false)

  useEffect(() => {
    // 1. Initial State Fetch
    const fetchState = async () => {
      try {
        const res = await fetch('http://127.0.0.1:8000/v1/oracle/sol/state')
        if (res.ok) {
          const data: SolDetailedState = await res.json()
          setDetailedState(data)
          if (data.beacon) {
            setBeacon(data.beacon)
          }
        }
      } catch {
        // Polling failure
      }
    }

    fetchState()

    // 2. Real-time SSE Stream
    let eventSource: EventSource | null = null
    try {
      eventSource = new EventSource('http://127.0.0.1:8000/v1/oracle/sol/stream')

      eventSource.addEventListener('beacon_state', (event) => {
        try {
          const newBeacon: BeaconState = JSON.parse(event.data)
          setBeacon(newBeacon)
          setStreamConnected(true)
        } catch {
          // ignore parsing error
        }
      })

      eventSource.onerror = () => {
        setStreamConnected(false)
      }

      eventSource.onopen = () => {
        setStreamConnected(true)
      }
    } catch {
      setStreamConnected(false)
    }

    const interval = setInterval(fetchState, 3000)

    return () => {
      if (eventSource) eventSource.close()
      clearInterval(interval)
    }
  }, [])

  // Badge presentation style strictly separating System Status from Market Thesis
  const getBadgeStyle = () => {
    const sys = beacon.system_status?.toUpperCase()
    const rsn = beacon.reasoning_status?.toUpperCase()
    const v = beacon.market_verdict?.toUpperCase()
    const dev = beacon.developing_state?.toUpperCase()

    if (sys === 'UNAVAILABLE') {
      return { bg: 'bg-slate-800/40 border-slate-700/50', text: 'text-slate-400', label: 'SYSTEM UNAVAILABLE' }
    }
    if (sys === 'OFF_MARKET') {
      return { bg: 'bg-slate-800/30 border-slate-700/40', text: 'text-slate-400', label: 'OFF MARKET' }
    }
    if (sys === 'DATA_DEGRADED' || sys === 'STALE') {
      return { bg: 'bg-amber-500/10 border-amber-500/30', text: 'text-amber-400', label: sys === 'STALE' ? 'STALE DATA' : 'DATA DEGRADED' }
    }
    if (rsn === 'DEGRADED_ADVISORY' || rsn === 'OUTPUT_INVALID' || rsn === 'NOT_INVOKED' || v === null) {
      return { bg: 'bg-amber-500/10 border-amber-500/30', text: 'text-amber-400', label: rsn === 'OUTPUT_INVALID' ? 'OUTPUT INVALID' : 'REASONING SUSPENDED' }
    }
    if (dev === 'CALL_DEVELOPING') {
      return { bg: 'bg-cyan-500/10 border-cyan-500/30', text: 'text-cyan-400', label: 'CALL DEVELOPING' }
    }
    if (dev === 'PUT_DEVELOPING') {
      return { bg: 'bg-purple-500/10 border-purple-500/30', text: 'text-purple-400', label: 'PUT DEVELOPING' }
    }
    if (v === 'CALL') {
      return { bg: 'bg-emerald-500/10 border-emerald-500/30', text: 'text-emerald-400', label: 'CALL' }
    }
    if (v === 'PUT') {
      return { bg: 'bg-rose-500/10 border-rose-500/30', text: 'text-rose-400', label: 'PUT' }
    }
    return { bg: 'bg-slate-800/40 border-slate-700/50', text: 'text-slate-300', label: 'NO TRADE' }
  }

  const badge = getBadgeStyle()
  const hs = detailedState?.health_strip
  const th = detailedState?.thesis

  const latestExp = th?.active_expectations && th.active_expectations.length > 0
    ? th.active_expectations[th.active_expectations.length - 1]
    : null

  const latestEval = th?.evaluation_history && th.evaluation_history.length > 0
    ? th.evaluation_history[th.evaluation_history.length - 1]
    : null

  return (
    <main className="min-h-screen bg-[#050811] text-slate-100 flex flex-col items-center justify-center p-4 font-sans antialiased select-none">
      <div className="w-[380px] bg-[#090e1c] border border-slate-800 rounded-xl shadow-2xl p-4 transition-all duration-200">
        
        {/* Top Header */}
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-2 mb-3">
          <div className="flex items-center gap-1.5 font-mono text-[11px] font-bold tracking-wider text-cyan-400">
            <span className={`inline-block w-2 h-2 rounded-full ${streamConnected ? 'bg-cyan-400 animate-pulse' : 'bg-slate-500'}`} />
            CITADEL BEACON
          </div>
          <div className="flex items-center gap-1.5 font-mono text-[10px]">
            {beacon.replay_mode && (
              <span className="px-1.5 py-0.5 rounded border bg-purple-500/10 text-purple-300 border-purple-500/20 font-bold">
                REPLAY
              </span>
            )}
            <span className="px-1.5 py-0.5 rounded border bg-slate-800/80 text-slate-300 border-slate-700">
              {beacon.thesis_timestamp_ist} IST
            </span>
          </div>
        </div>

        {/* Persistent Compact Health Strip */}
        <div className="grid grid-cols-2 gap-x-2 gap-y-1 bg-slate-900/90 border border-slate-800 rounded-lg p-2 mb-3 font-mono text-[9.5px]">
          <div className="flex justify-between">
            <span className="text-slate-400">DATA STREAM:</span>
            <span className={`font-bold ${hs?.data_stream === 'LIVE' ? 'text-emerald-400' : 'text-amber-400'}`}>
              ● {hs?.data_stream || (beacon.system_status === 'HEALTHY' ? 'LIVE' : beacon.system_status)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">BRAIN WORKER:</span>
            <span className="font-bold text-cyan-400">● {hs?.brain_worker || 'WATCHING'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">AI PROVIDER:</span>
            <span className={`font-bold ${hs?.ai_provider === 'CONNECTED' ? 'text-emerald-400' : 'text-slate-400'}`}>
              ● {hs?.ai_provider || 'IDLE'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">REASONING:</span>
            <span className="font-bold text-slate-300">{hs?.reasoning_state || 'IDLE'}</span>
          </div>
          <div className="flex justify-between col-span-2 border-t border-slate-800/60 pt-1 mt-0.5">
            <span className="text-slate-400">MODEL:</span>
            <span className="text-cyan-300 font-semibold">{beacon.configured_model.toUpperCase()}</span>
          </div>
          <div className="flex justify-between col-span-2">
            <span className="text-slate-400">LAST ANALYSIS:</span>
            <span className="text-slate-300">{hs?.last_analysis_time || beacon.thesis_timestamp_ist}</span>
          </div>
        </div>

        {/* Primary Market Verdict Card */}
        <div className={`text-center py-3.5 px-3 rounded-lg border mb-3 transition-colors ${badge.bg}`}>
          <div className="font-mono text-[9px] uppercase tracking-widest text-slate-400 mb-0.5">MARKET BRAIN VERDICT</div>
          <h1 className={`font-mono text-2xl font-extrabold tracking-wide ${badge.text}`}>
            {badge.label}
          </h1>
          <div className="font-mono text-[10px] text-slate-400 mt-1 flex items-center justify-center gap-2">
            <span>STATE: <strong className="text-slate-200">{beacon.developing_state}</strong></span>
          </div>
        </div>

        {/* Core Evidence: 3 Why Bullets */}
        <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-2.5 mb-2.5">
          <div className="font-mono text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5 flex items-center gap-1">
            <ShieldCheck className="w-3 h-3 text-cyan-400" />
            Core Thesis Evidence (Why)
          </div>
          <ul className="space-y-1 font-mono text-[11px] text-slate-200 leading-snug">
            {beacon.why_bullets && beacon.why_bullets.length > 0 ? (
              beacon.why_bullets.slice(0, 3).map((bullet, idx) => (
                <li key={idx} className="flex items-start gap-1.5">
                  <span className="text-cyan-400 select-none">•</span>
                  <span>{bullet}</span>
                </li>
              ))
            ) : (
              <li className="text-slate-400 italic">Awaiting reasoning cycle evidence...</li>
            )}
          </ul>
        </div>

        {/* Cases & Changes Grid */}
        <div className="grid grid-cols-2 gap-2 mb-2.5 font-mono text-[10px]">
          <div className="bg-emerald-950/20 border border-emerald-900/40 rounded p-2">
            <span className="text-emerald-400 font-bold block mb-0.5">BULL CASE</span>
            <span className="text-slate-300 leading-tight block">{th?.call_case || 'None'}</span>
          </div>
          <div className="bg-rose-950/20 border border-rose-900/40 rounded p-2">
            <span className="text-rose-400 font-bold block mb-0.5">BEAR CASE</span>
            <span className="text-slate-300 leading-tight block">{th?.put_case || 'None'}</span>
          </div>
        </div>

        {/* Expectation Lifecycle Box */}
        <div className="bg-slate-900/70 border border-slate-800 rounded p-2 mb-3 font-mono text-[10px] space-y-1">
          {latestEval && (
            <div className="flex justify-between items-center pb-1 border-b border-slate-800/80">
              <span className="text-slate-400">PREV EXPECTATION:</span>
              <span className={`font-bold px-1 rounded ${
                latestEval.result === 'SUPPORTED' ? 'bg-emerald-500/20 text-emerald-300' :
                latestEval.result === 'CONTRADICTED' ? 'bg-rose-500/20 text-rose-300' : 'bg-slate-800 text-slate-300'
              }`}>
                {latestEval.result}
              </span>
            </div>
          )}
          {latestExp ? (
            <>
              <div>
                <span className="text-cyan-400 font-bold">NEXT EXPECTATION: </span>
                <span className="text-slate-200">{latestExp.expected_condition}</span>
              </div>
              <div>
                <span className="text-rose-400 font-bold">INVALIDATES IF: </span>
                <span className="text-slate-300">{latestExp.invalidation_condition}</span>
              </div>
            </>
          ) : (
            <div className="text-slate-400 italic">No active pre-registered expectation.</div>
          )}
        </div>

        {/* Expand Details Toggle */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-center gap-1 py-1 text-slate-400 hover:text-cyan-300 font-mono text-[10px] uppercase tracking-wider transition-colors border-t border-slate-800 pt-2"
        >
          <span>{expanded ? 'Hide Deep Audit Drawer' : 'View Deep Audit Drawer'}</span>
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>

        {/* Expandable Drawer */}
        {expanded && (
          <div className="mt-3 pt-3 border-t border-slate-800 space-y-2.5 font-mono text-[10px] text-slate-300 max-h-[380px] overflow-y-auto pr-1">
            
            {/* Core Narrative */}
            <div className="bg-slate-900/90 border border-slate-800 rounded p-2">
              <span className="text-cyan-400 font-bold block mb-1">ACTIVE MARKET NARRATIVE</span>
              <p className="text-slate-300 leading-relaxed">{th?.core_narrative || 'Awaiting active cycle thesis...'}</p>
            </div>

            {/* Stories Grid */}
            <div className="space-y-1.5">
              <div className="bg-slate-900/60 p-1.5 rounded border border-slate-800/60">
                <span className="text-slate-400 font-bold block">OI REGIME STORY</span>
                <span className="text-slate-200">{th?.oi_story || 'None'}</span>
              </div>
              <div className="bg-slate-900/60 p-1.5 rounded border border-slate-800/60">
                <span className="text-slate-400 font-bold block">ORDER FLOW STORY</span>
                <span className="text-slate-200">{th?.flow_story || 'None'}</span>
              </div>
              <div className="bg-slate-900/60 p-1.5 rounded border border-slate-800/60">
                <span className="text-slate-400 font-bold block">OPTION RESPONSE STORY</span>
                <span className="text-slate-200">{th?.option_response_story || 'None'}</span>
              </div>
            </div>

            {/* Evidence & References */}
            <div className="bg-slate-900/60 p-2 rounded border border-slate-800/60">
              <span className="text-slate-400 font-bold block mb-1">EVIDENCE REFERENCES</span>
              <div className="flex flex-wrap gap-1">
                {th?.evidence_references && th.evidence_references.length > 0 ? (
                  th.evidence_references.map((ref, idx) => (
                    <span key={idx} className="bg-slate-800 text-slate-300 px-1 rounded text-[9px] font-mono border border-slate-700">
                      {ref}
                    </span>
                  ))
                ) : (
                  <span className="text-slate-500 italic">No explicit evidence refs attached.</span>
                )}
              </div>
            </div>

            {/* External Context (Spark) Summary */}
            <div className="bg-slate-900/90 border border-slate-800 rounded p-2 text-[9px] space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-cyan-400 font-bold flex items-center gap-1">
                  <Radio className="w-3 h-3 text-cyan-400" />
                  EXTERNAL CONTEXT (SPARK)
                </span>
                <div className="flex items-center gap-1">
                  <span
                    className={`px-1.5 py-0.5 rounded text-[8.5px] font-bold border ${
                      detailedState?.external_context?.source_verification_status === 'CONNECTED'
                        ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
                        : 'bg-amber-500/10 text-amber-300 border-amber-500/20'
                    }`}
                  >
                    SOURCE CONNECTOR: {detailedState?.external_context?.source_verification_status || 'NOT CONNECTED'}
                  </span>
                  <span
                    className={`px-1.5 py-0.5 rounded text-[8.5px] font-bold border ${
                      detailedState?.external_context?.status === 'AVAILABLE'
                        ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
                        : 'bg-slate-800 text-slate-400 border-slate-700'
                    }`}
                  >
                    SPARK: {detailedState?.external_context?.is_test_fixture
                      ? 'TEST FIXTURE'
                      : detailedState?.external_context?.status || 'UNAVAILABLE'}
                  </span>
                </div>
              </div>

              {/* Provenance Verification Counter Bar */}
              <div className="bg-slate-950/80 rounded p-1 border border-slate-800 flex items-center justify-between text-[8.5px]">
                <span className="text-slate-400">CITADEL VERIFICATION:</span>
                <div className="flex items-center gap-2 font-bold">
                  <span className="text-emerald-400">VERIFIED: {detailedState?.external_context?.verified_items_count ?? 0}</span>
                  <span className="text-slate-300">UNVERIFIED: {detailedState?.external_context?.unverified_items_count ?? 0}</span>
                  <span className={(detailedState?.external_context?.conflicted_items_count ?? 0) > 0 ? 'text-rose-400' : 'text-slate-500'}>
                    CONFLICTED: {detailedState?.external_context?.conflicted_items_count ?? 0}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-x-2 text-slate-300">
                <div>LAST RECEIVED: <strong className="text-slate-100">{detailedState?.external_context?.last_received_ist || 'NONE'}</strong></div>
                <div>LAST SOURCE TIME: <strong className="text-slate-100">{detailedState?.external_context?.last_source_time_ist || 'NONE'}</strong></div>
                <div>TOTAL CLAIMS: <strong className="text-cyan-300">{detailedState?.external_context?.total_items ?? 0}</strong></div>
                <div>AUTHENTIC VERIFIED SOURCES: <strong className="text-emerald-300">{detailedState?.external_context?.verified_sources_count ?? 0}</strong></div>
                <div>DATA GAPS: <strong className="text-amber-300">{detailedState?.external_context?.data_gaps_count ?? 0}</strong></div>
                <div>PROVIDER: <strong className="text-slate-200">{detailedState?.external_context?.provider || 'NONE'}</strong></div>
              </div>

              {/* Discrepancy / Conflict Alerts */}
              {detailedState?.external_context?.conflicted_items && detailedState.external_context.conflicted_items.length > 0 && (
                <div className="p-1.5 rounded bg-rose-950/40 border border-rose-900/60 text-[8.5px] space-y-1">
                  <span className="text-rose-300 font-bold block flex items-center gap-1">
                    ⚠️ PROVENANCE CONFLICT (AUTHORITATIVE OVERRIDE):
                  </span>
                  {detailedState.external_context.conflicted_items.map((c, idx) => (
                    <div key={idx} className="space-y-0.5 text-slate-300 border-t border-rose-900/30 pt-1">
                      <div className="font-bold text-slate-200">{c.title}</div>
                      <div className="text-rose-300">SPARK CLAIM: {c.spark_claim}</div>
                      <div className="text-emerald-300">AUTHORITATIVE ({c.authoritative_source || 'OFFICIAL'}): {c.authoritative_value}</div>
                    </div>
                  ))}
                </div>
              )}

              {detailedState?.external_context?.summary_titles && detailedState.external_context.summary_titles.length > 0 && (
                <div className="pt-1 border-t border-slate-800/80">
                  <span className="text-slate-400 font-bold block mb-0.5">CATALYSTS & CITATIONS:</span>
                  <ul className="space-y-0.5 text-slate-300">
                    {detailedState.external_context.summary_titles.map((t, idx) => (
                      <li key={idx} className="flex items-start gap-1">
                        <span className="text-cyan-400 select-none">•</span>
                        <span className="truncate">{t}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Persistence Telemetry */}
            <div className="bg-slate-950 p-2 rounded border border-slate-800 text-[9px] space-y-0.5">
              <span className="text-cyan-400 font-bold block mb-1">DURABLE MEMORY TELEMETRY</span>
              <div>EVENT STORE: <strong className="text-emerald-400">{detailedState?.persistence?.jsonl_health || 'OK'}</strong></div>
              <div>THESIS STORE: <strong className="text-emerald-400">{detailedState?.persistence?.thesis_store_status || 'OK'}</strong></div>
              <div>BASELINE STORE: <strong className="text-emerald-400">{detailedState?.persistence?.baseline_store_status || 'OK'}</strong></div>
              <div>LAST PERSISTENCE UTC: {detailedState?.persistence?.last_successful_write_utc || 'NONE'}</div>
            </div>

          </div>
        )}

      </div>
    </main>
  )
}
