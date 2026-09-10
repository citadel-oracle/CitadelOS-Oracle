'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { OptionContractMetadata } from './useOracleDevChartData'

const API_URL = process.env.NEXT_PUBLIC_CITADEL_API_URL ?? 'http://127.0.0.1:8000'
const REFRESH_MS = 3_000

export interface FuturesContractMetadata {
  security_id: string
  symbol: string
  lot_size: number
  expiry: string
  segment: string
  instrument: string
}

export interface OracleDevLaneStatus {
  timeframe: string
  state: string
  active_setup: Record<string, unknown> | null
  position: Record<string, unknown> | null
  balance: number
  position_history: readonly Record<string, unknown>[]
  guardian_action: string
  guardian_reason: string
  last_spot: Record<string, unknown> | null
  last_futures: Record<string, unknown> | null
  last_option: Record<string, any>
  options_info?: Record<string, OptionContractMetadata>
  futures_info?: FuturesContractMetadata
  options_unavailable_reason?: string | null
}

export interface OracleDevReasoningData {
  timeframe: string
  generated_at: string
  scores: {
    total_score: number
    pa_score: number
    vob_score: number
    deriv_score: number
    exec_score: number
    all_contributors: Record<string, Record<string, unknown>>
  }
  price_action: Record<string, unknown>
  vob: Record<string, unknown>
  derivatives: Record<string, unknown>
  execution: Record<string, unknown>
  setup_family: string | null
  plan: Record<string, unknown>
  lane_status: OracleDevLaneStatus
  strategy_id?: string
  strategy_name?: string
  trade_creator?: string
  setup_subtype?: string
}

export interface OracleDevMission {
  mission_id: string
  symbol: string
  timeframe: string
  parent_setup_family: string
  trade_creator: string
  direction: string
  status: string
  created_at: string
  updated_at: string
}

export interface OracleDevMissionRuntime {
  assessments: Record<string, OracleDevReasoningData> | null
  activeMission: OracleDevMission | null
  isReplay: boolean
  loading: boolean
  busyAction: string | null
  error: string | null
  refresh: () => Promise<void>
  analyse: () => Promise<void>
  paperExecute: () => Promise<void>
  exitNow: () => Promise<void>
  cancel: () => Promise<void>
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
    throw new Error(messageFrom(body, `Oracle Dev API HTTP ${response.status}`))
  }
  return body as T
}

import { refreshScheduler } from './refreshScheduler'

export function useOracleDevMissionRuntime(symbol: string | null, selectedLane: '1m' | '3m' | '5m' = '3m'): OracleDevMissionRuntime {
  const [state, setState] = useState(() => ({
    assessments: refreshScheduler.assessments,
    activeMission: refreshScheduler.activeMission,
    error: refreshScheduler.error,
    loading: refreshScheduler.loading
  }))

  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [errorLocal, setErrorLocal] = useState<string | null>(null)
  const mounted = useRef(true)

  const { assessments, activeMission, loading } = state
  const error = state.error || errorLocal
  const isReplay = refreshScheduler.chartData?.is_replay || false

  useEffect(() => {
    refreshScheduler.setLane(selectedLane)
  }, [selectedLane])

  useEffect(() => {
    const unsubscribe = refreshScheduler.subscribe(() => {
      setState({
        assessments: refreshScheduler.assessments,
        activeMission: refreshScheduler.activeMission,
        error: refreshScheduler.error,
        loading: refreshScheduler.loading
      })
    })
    return unsubscribe
  }, [])

  const refresh = useCallback(async () => {
    refreshScheduler.setLane(selectedLane)
  }, [selectedLane])

  const run = useCallback(async <T,>(
    action: string,
    operation: () => Promise<T>,
    accept: (result: T) => void,
  ) => {
    if (busyAction) return
    setBusyAction(action)
    setErrorLocal(null)
    try {
      const result = await operation()
      if (mounted.current) accept(result)
    } catch (cause) {
      if (mounted.current) {
        setErrorLocal(cause instanceof Error ? cause.message : `${action} failed`)
      }
    } finally {
      if (mounted.current) setBusyAction(null)
    }
  }, [busyAction])

  const analyse = useCallback(async () => {
    await run('ANALYSE', async () => {
      let active = activeMission
      if (!active) {
        active = await request<OracleDevMission>('/v1/oracle-development/missions', {
          method: 'POST',
          body: JSON.stringify({
            symbol: symbol ?? 'NIFTY',
            timeframe: '3m',
            parent_setup_family: 'PA Breakout',
            trade_creator: 'PriceAction',
            direction: 'CALL',
            reference_time: new Date().toISOString()
          })
        })
      }
      // Trigger evaluate route
      await request(`/v1/oracle-development/missions/${encodeURIComponent(active.mission_id)}/evaluate`, {
        method: 'POST'
      })
      // Trigger plan route
      await request(`/v1/oracle-development/missions/${encodeURIComponent(active.mission_id)}/plan`, {
        method: 'POST'
      })
      return active
    }, (result) => {
      refreshScheduler.activeMission = result
      refreshScheduler['notify']()
      void refresh()
    })
  }, [activeMission, run, symbol, refresh])

  const paperExecute = useCallback(async () => {
    if (!activeMission) return
    await run('PAPER_EXECUTE', async () => {
      return request<Record<string, unknown>>(
        `/v1/oracle-development/missions/${encodeURIComponent(activeMission.mission_id)}/paper-execute`,
        { method: 'POST' },
      )
    }, () => {
      void refresh()
    })
  }, [activeMission, run, refresh])

  const exitNow = useCallback(async () => {
    if (!activeMission) return
    await run('EXIT_NOW', async () => {
      return request<Record<string, unknown>>(
        `/v1/oracle-development/missions/${encodeURIComponent(activeMission.mission_id)}/exit`,
        { method: 'POST' },
      )
    }, () => {
      void refresh()
    })
  }, [activeMission, run, refresh])

  const cancel = useCallback(async () => {
    if (!activeMission) return
    await run('CANCEL', async () => {
      return request<Record<string, unknown>>(
        `/v1/oracle-development/missions/${encodeURIComponent(activeMission.mission_id)}/cancel`,
        { method: 'POST' }
      )
    }, () => {
      refreshScheduler.activeMission = null
      refreshScheduler['notify']()
      void refresh()
    })
  }, [activeMission, run, refresh])

  return {
    assessments,
    activeMission,
    isReplay,
    loading,
    busyAction,
    error,
    refresh,
    analyse,
    paperExecute,
    exitNow,
    cancel
  }
}
