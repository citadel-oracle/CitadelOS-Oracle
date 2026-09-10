'use client'

import { useState, useEffect, useCallback, useRef } from 'react'

export interface OptionContractMetadata {
  strike: number
  expiry: string
  security_id: string
  symbol: string
}

export interface OptionCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface VobContext {
  vob_state: string
  proximity_desc: string
  displacement_desc: string
}

export interface FeedHeartbeat {
  last_timestamp: string
  data_age_seconds: number
  market_status: string
  source_mode: string
}

export interface FuturesChartPayload {
  contract: string
  expiry: string
  security_id: string
  timeframe: string
  rollover_status: string
  last_resolution_time: string
  candles: FuturesCandle[]
}

export interface FuturesCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  oi: number
  vwap?: number
  basis?: number
}

export interface SwingPivot {
  type: 'HIGH' | 'LOW'
  val: number
  label: string
  index: number
  time: number
}

export interface FVGZone {
  fvg_type: 'bullish' | 'bearish' | 'breakaway' | 'inversion'
  direction: 'CALL' | 'PUT'
  zone: [number, number]
  state: string
  index: number
  time: number
}

export interface VOBZone {
  id: string
  zone_high: number
  zone_low: number
  side: 'BULLISH' | 'BEARISH'
  volume_ratio: number
  displacement_strength: number
  status: string
  price_space?: 'UNDERLYING' | 'OPTION_PREMIUM'
  source?: string
  timeframe?: string
  contract?: string
  security_id?: string
}

export interface TradeMarker {
  mission_id: string
  strategy_name: string
  strategy_id: string
  setup_subtype: string
  trade_creator: 'VOB' | 'PRICE_ACTION'
  parent_setup_family: string
  timeframe: string
  direction: 'CALL' | 'PUT'
  option_contract: string
  trigger_candle: string
  score: number
  quantity_ceiling: number
  risk_approved_lots: number
  entry: number
  maximum_entry: number
  structural_sl: number
  target: number
  guardian_action: string
  exit_reason: string
  option_entry_premium?: number
  option_exit_premium?: number
  pnl?: number
  status?: string
  exit_time?: string
}

export interface ChartDataResponse {
  contract: string
  expiry: string
  security_id?: string
  source_mode?: string
  market_status?: string
  data_age_seconds?: number
  candle_count?: number
  rollover_status?: string
  last_resolution_time?: string
  options_info?: Record<string, OptionContractMetadata>
  ltp: number
  volume: number
  oi: number
  vwap: number
  basis: number
  timestamp: string
  last_timestamp?: string
  age: number
  data_source: string
  is_replay: boolean
  is_stale: boolean
  required_execution_count?: number
  execution_ready?: boolean
  execution_blocker?: string
  current_session_first_timestamp?: string
  current_session_last_timestamp?: string
  warmup_status?: string
  warmup_source?: string
  warmup_candle_count?: number
  last_backfill_attempt?: string
  last_backfill_error?: string
  is_synthetic?: boolean
  candles: FuturesCandle[]
  overlays: {
    swings: SwingPivot[]
    fvgs: FVGZone[]
    vobs: VOBZone[]
    vwap_series: number[]
    range: { high: number; low: number; mid: number }
    prev_day: { high: number; low: number; close: number }
    opening_range: { high: number; low: number }
    structure_events?: any[]
  }
  trades: TradeMarker[]
}

import { refreshScheduler } from './refreshScheduler'

export function useOracleDevChartData(timeframe: '1m' | '3m' | '5m', forceStale?: boolean) {
  const [state, setState] = useState(() => ({
    chartData: refreshScheduler.chartData,
    loading: refreshScheduler.loading,
    error: refreshScheduler.error,
    syncStatus: refreshScheduler.syncStatus,
    syncCooldown: refreshScheduler.syncCooldown
  }))

  useEffect(() => {
    refreshScheduler.setLane(timeframe)
  }, [timeframe])

  useEffect(() => {
    const unsubscribe = refreshScheduler.subscribe(() => {
      setState({
        chartData: refreshScheduler.chartData,
        loading: refreshScheduler.loading,
        error: refreshScheduler.error,
        syncStatus: refreshScheduler.syncStatus,
        syncCooldown: refreshScheduler.syncCooldown
      })
    })
    return unsubscribe
  }, [])

  const refresh = useCallback(async () => {
    refreshScheduler.setLane(timeframe)
  }, [timeframe])

  const forceSync = useCallback(async () => {
    await refreshScheduler.forceSync()
  }, [])

  return {
    chartData: state.chartData,
    loading: state.loading,
    error: state.error,
    refresh,
    forceSync,
    syncStatus: state.syncStatus,
    syncCooldown: state.syncCooldown
  }
}
