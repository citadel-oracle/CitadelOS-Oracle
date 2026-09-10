'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

const API_URL = process.env.NEXT_PUBLIC_CITADEL_API_URL ?? 'http://127.0.0.1:8000'
const REFRESH_MS = 5_000

export type MissionMode = 'ADVISE' | 'CONFIRM' | 'PAPER_AUTOPILOT' | 'DEMO_PAPER'

export interface DemoTourTrade {
  trade_number: number
  side: 'CE' | 'PE'
  lots: number
  contract: string
  lot_size: number
  quantity: number
  simulated_risk: number
  entry: number | null
  exit: number | null
  pnl: number | null
  guardian_state: string
  guardian_action: string | null
}

export interface DemoTourSession {
  status: string
  current_trade?: number
  trade_total?: number
  remaining_hold_seconds?: number | null
  trades: readonly DemoTourTrade[]
  guardian?: OracleGuardian | null
  execution_origin?: 'DEMO_PAPER'
  directional_edge?: 'NOT_CLAIMED'
  paper_only?: true
  live_trading_enabled?: false
  broker_submission?: false
}

export interface OracleMission {
  mission_id: string
  instrument_scope: string
  mode: MissionMode
  status: string
  outcome: string | null
  max_trades: number
  trades_used: number
  created_at: string
  updated_at: string
  expires_at: string
  execution_allowed: false
  safety?: Record<string, unknown>
}

export interface OpportunityGateResult {
  decision: 'CALL' | 'PUT' | 'EQUITY' | 'NO_TRADE'
  evidence_quality_score: number
  confidence_category: string
  aligned_evidence: readonly string[]
  conflicting_evidence: readonly string[]
  rejection_reasons: readonly string[]
  critical_missing_inputs: readonly string[]
  probability: null
  contract: null
  entry: null
  stop_loss: null
  targets: null
  quantity: null
  execution_allowed: false
}

export interface OracleTradePlan {
  plan_id: string
  mission_id: string
  status?: string
  underlying: string
  instrument_type: string
  contract: string
  security_id: string
  expiry: string | null
  dte: number | null
  strike: number | null
  option_type?: string | null
  lot_size: number
  ltp: number
  entry_zone: readonly number[] | Record<string, unknown>
  maximum_entry: number
  final_sl: number
  target_1: number
  target_2: number
  approved_quantity: number
  total_maximum_risk: number
  reward_risk: number
  rejection_reasons: readonly string[]
  execution_allowed: false
}

export interface OracleGuardian {
  mission_id: string
  plan_id: string
  state: string
  health: string
  reason?: string | null
  contract?: string
  security_id?: string
  approved_quantity?: number
  filled_quantity?: number
  last_quote?: number | null
  last_quote_timestamp?: string | null
  current_stop?: number
  target_1?: number
  target_2?: number
  execution_allowed: false
  execution_influence: 'ZERO'
  paper_only: true
  live_trading_enabled: false
  broker_submission: false
}

export interface OracleMissionRuntime {
  mission: OracleMission | null
  gate: OpportunityGateResult | null
  plan: OracleTradePlan | null
  guardian: OracleGuardian | null
  demoTour: DemoTourSession | null
  loading: boolean
  busyAction: string | null
  error: string | null
  stateStatus: string
  stateReason: string | null
  refresh: () => Promise<void>
  analyse: () => Promise<void>
  createPlan: () => Promise<void>
  paperExecute: () => Promise<void>
  cancel: () => Promise<void>
  exitNow: () => Promise<void>
}

interface ActiveMissionResponse {
  mission: OracleMission | null
  state: {
    status?: string
    reason?: string | null
  }
}

const messageFrom = (body: unknown, fallback: string): string => {
  if (!body || typeof body !== 'object') return fallback
  const detail = 'detail' in body ? (body as { detail?: unknown }).detail : body
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message
  }
  return fallback
}

const request = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(`${API_URL}${path}`, {
    cache: 'no-store',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(messageFrom(body, `Oracle API HTTP ${response.status}`))
  }
  return body as T
}

const newIdempotencyKey = (): string => {
  const suffix = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().replaceAll('-', '')
    : `${Date.now()}`
  return `oracle_ui_${suffix}`.slice(0, 120)
}

export function useOracleMissionRuntime(symbol: string | null): OracleMissionRuntime {
  const [mission, setMission] = useState<OracleMission | null>(null)
  const [gate, setGate] = useState<OpportunityGateResult | null>(null)
  const [plan, setPlan] = useState<OracleTradePlan | null>(null)
  const [guardian, setGuardian] = useState<OracleGuardian | null>(null)
  const [demoTour, setDemoTour] = useState<DemoTourSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [stateStatus, setStateStatus] = useState('CONNECTING')
  const [stateReason, setStateReason] = useState<string | null>(null)
  const requestInFlight = useRef(false)
  const mounted = useRef(true)

  const refresh = useCallback(async () => {
    if (requestInFlight.current) return
    requestInFlight.current = true
    try {
      const [active, demo] = await Promise.all([
        request<ActiveMissionResponse>('/v1/oracle/missions/active'),
        request<DemoTourSession>('/v1/oracle/demo-tour'),
      ])
      if (!mounted.current) return
      setMission(active.mission)
      setStateStatus(active.state.status ?? 'UNAVAILABLE')
      setStateReason(active.state.reason ?? null)
      setDemoTour(demo)
      if (!active.mission) {
        setGate(null)
        setPlan(null)
        setGuardian(null)
      } else if (guardian) {
        const nextGuardian = await request<OracleGuardian>(
          `/v1/oracle/missions/${encodeURIComponent(active.mission.mission_id)}/guardian`,
        )
        if (mounted.current) setGuardian(nextGuardian)
      }
      setError(null)
    } catch (cause) {
      if (mounted.current) {
        setStateStatus('UNAVAILABLE')
        setError(cause instanceof Error ? cause.message : 'Oracle mission state unavailable')
      }
    } finally {
      requestInFlight.current = false
      if (mounted.current) setLoading(false)
    }
  }, [guardian])

  useEffect(() => {
    mounted.current = true
    const initial = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => void refresh(), REFRESH_MS)
    return () => {
      mounted.current = false
      window.clearTimeout(initial)
      window.clearInterval(timer)
    }
  }, [refresh])

  const run = useCallback(async <T,>(
    action: string,
    operation: () => Promise<T>,
    accept: (result: T) => void,
  ) => {
    if (busyAction) return
    setBusyAction(action)
    setError(null)
    try {
      const result = await operation()
      if (mounted.current) accept(result)
    } catch (cause) {
      if (mounted.current) {
        setError(cause instanceof Error ? cause.message : `${action} failed`)
      }
    } finally {
      if (mounted.current) setBusyAction(null)
    }
  }, [busyAction])

  const analyse = useCallback(async () => {
    await run('ANALYSE', async () => {
      let activeMission = mission
      if (!activeMission) {
        if (!symbol) throw new Error('Canonical instrument scope is unavailable')
        activeMission = await request<OracleMission>('/v1/oracle/missions', {
          method: 'POST',
          body: JSON.stringify({
            idempotency_key: newIdempotencyKey(),
            instrument_scope: symbol,
            mode: 'PAPER_AUTOPILOT',
            max_trades: 1,
            timeout_seconds: 900,
          }),
        })
      }
      const result = await request<OpportunityGateResult>(
        `/v1/oracle/missions/${encodeURIComponent(activeMission.mission_id)}/evaluate`,
        { method: 'POST' },
      )
      return { mission: activeMission, gate: result }
    }, (result) => {
      setMission(result.mission)
      setGate(result.gate)
      setPlan(null)
      setGuardian(null)
    })
  }, [mission, run, symbol])

  const createPlan = useCallback(async () => {
    if (!mission) return
    await run('CREATE_PLAN', () => request<OracleTradePlan>(
      `/v1/oracle/missions/${encodeURIComponent(mission.mission_id)}/plan`,
      { method: 'POST', body: '{}' },
    ), (result) => {
      setPlan(result)
      setGuardian(null)
    })
  }, [mission, run])

  const paperExecute = useCallback(async () => {
    if (!mission) return
    await run('PAPER_EXECUTE', () => request<OracleGuardian>(
      `/v1/oracle/missions/${encodeURIComponent(mission.mission_id)}/paper-execute`,
      { method: 'POST' },
    ), setGuardian)
  }, [mission, run])

  const cancel = useCallback(async () => {
    if (!mission) return
    await run('CANCEL', () => request<OracleMission>(
      `/v1/oracle/missions/${encodeURIComponent(mission.mission_id)}/cancel`,
      { method: 'POST' },
    ), (result) => {
      setMission(result)
      setGate(null)
      setPlan(null)
      setGuardian(null)
    })
  }, [mission, run])

  const exitNow = useCallback(async () => {
    if (!mission) return
    await run('EXIT_NOW', () => request<OracleGuardian>(
      `/v1/oracle/missions/${encodeURIComponent(mission.mission_id)}/exit`,
      { method: 'POST' },
    ), setGuardian)
  }, [mission, run])

  return {
    mission,
    gate,
    plan,
    guardian,
    demoTour,
    loading,
    busyAction,
    error,
    stateStatus,
    stateReason,
    refresh,
    analyse,
    createPlan,
    paperExecute,
    cancel,
    exitNow,
  }
}
