'use client'

import { ChartDataResponse } from './useOracleDevChartData'
import { OracleDevReasoningData } from './useOracleDevMissionRuntime'

type Listener = () => void

const API_URL = process.env.NEXT_PUBLIC_CITADEL_API_URL ?? 'http://127.0.0.1:8000'

class RefreshScheduler {
  private listeners: Set<Listener> = new Set()
  private inFlightReasoning = false
  private inFlightChart = false
  private timer: any = null
  private abortController: AbortController | null = null

  // Shared state
  public chartData: ChartDataResponse | null = null
  public assessments: Record<string, OracleDevReasoningData> | null = null
  public activeMission: any | null = null
  public error: string | null = null
  public loading = true
  public syncStatus: 'idle' | 'loading' | 'success' | 'failure' = 'idle'
  public syncCooldown = false
  public currentLane: '1m' | '3m' | '5m' = '1m'

  // Metadata caches for lightweight deduplication
  private lastChartMeta = { last_timestamp: '', candle_count: 0, blocker: '', execution_ready: false }
  private lastReasoningMeta = { generated_at: '' }

  constructor() {
    if (typeof window !== 'undefined') {
      this.start()
    }
  }

  public subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  private notify() {
    this.listeners.forEach(l => {
      try {
        l()
      } catch (err) {
        console.error('Error calling listener:', err)
      }
    })
  }

  public start() {
    if (this.timer) return
    this.scheduleNextTick()
  }

  public stop() {
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
    if (this.abortController) {
      this.abortController.abort()
      this.abortController = null
    }
  }

  public setLane(lane: '1m' | '3m' | '5m') {
    if (this.currentLane !== lane) {
      this.currentLane = lane
      // Lane change aborts active requests and triggers immediate fetch
      if (this.abortController) {
        this.abortController.abort()
      }
      this.abortController = new AbortController()
      this.inFlightChart = false
      this.inFlightReasoning = false
      this.lastChartMeta = { last_timestamp: '', candle_count: 0, blocker: '', execution_ready: false }
      this.lastReasoningMeta = { generated_at: '' }
      
      this.runCycle()
    }
  }

  public async forceSync() {
    if (this.syncCooldown) return
    this.syncCooldown = true
    this.syncStatus = 'loading'
    this.notify()

    try {
      const res = await fetch(`${API_URL}/v1/oracle-development/sync?timeframe=${this.currentLane}`, {
        method: 'POST',
        signal: this.abortController?.signal
      })
      if (!res.ok) {
        throw new Error(`Sync failed with status ${res.status}`)
      }
      this.syncStatus = 'success'
      this.lastChartMeta = { last_timestamp: '', candle_count: 0, blocker: '', execution_ready: false }
      this.lastReasoningMeta = { generated_at: '' }
      await this.runCycle()
    } catch (err) {
      this.syncStatus = 'failure'
      this.error = err instanceof Error ? err.message : 'Force sync failed'
    } finally {
      this.notify()
      setTimeout(() => {
        this.syncStatus = 'idle'
        this.notify()
      }, 3000)
      setTimeout(() => {
        this.syncCooldown = false
        this.notify()
      }, 5000)
    }
  }

  private scheduleNextTick() {
    if (this.timer) clearTimeout(this.timer)
    this.timer = setTimeout(async () => {
      await this.runCycle()
      this.scheduleNextTick()
    }, 1500)
  }

  private async runCycle() {
    if (!this.abortController) {
      this.abortController = new AbortController()
    }
    const signal = this.abortController.signal

    // Enforce maximum one in-flight request per cycle (no overlap)
    if (this.inFlightChart || this.inFlightReasoning) {
      return
    }

    this.inFlightChart = true
    this.inFlightReasoning = true

    let chartUpdated = false
    let reasoningUpdated = false

    try {
      // 1. Concurrently fetch Chart Data (which is fast and must not deadlock)
      const chartPromise = fetch(`${API_URL}/v1/oracle-development/chart-data?timeframe=${this.currentLane}`, { signal })
        .then(async (res) => {
          if (res.ok) {
            const data: ChartDataResponse = await res.json()
            const newMeta = {
              last_timestamp: data.last_timestamp || '',
              candle_count: data.candle_count || 0,
              blocker: data.execution_blocker || '',
              execution_ready: data.execution_ready || false
            }
            if (
              newMeta.last_timestamp !== this.lastChartMeta.last_timestamp ||
              newMeta.candle_count !== this.lastChartMeta.candle_count ||
              newMeta.blocker !== this.lastChartMeta.blocker ||
              newMeta.execution_ready !== this.lastChartMeta.execution_ready ||
              !this.chartData
            ) {
              this.lastChartMeta = newMeta
              this.chartData = data
              chartUpdated = true
            }
          }
        })
        .catch((err) => {
          if (err.name !== 'AbortError') {
            console.error('Chart data fetch error:', err.message, err.stack)
          }
        })

      // 2. Concurrently fetch Reasoning with a strict timeout (e.g. 1200ms) to bypass backend deadlocks
      const reasoningController = new AbortController()
      const reasoningTimeout = setTimeout(() => reasoningController.abort(), 1200)
      const reasoningPromise = fetch(`${API_URL}/v1/oracle-development/reasoning`, { signal: reasoningController.signal })
        .then(async (res) => {
          clearTimeout(reasoningTimeout)
          if (res.ok) {
            const resData = await res.json()
            const parsed: Record<string, OracleDevReasoningData> = {}
            let latestGeneratedAt = ''

            if (Array.isArray(resData)) {
              resData.forEach((a: OracleDevReasoningData) => {
                parsed[a.timeframe] = a
                if (a.timeframe === this.currentLane) {
                  latestGeneratedAt = a.generated_at
                }
              })
            } else if (resData && typeof resData === 'object') {
              Object.entries(resData).forEach(([tf, a]: [string, any]) => {
                parsed[tf] = a
                if (tf === this.currentLane) {
                  latestGeneratedAt = a.generated_at
                }
              })
            }

            if (latestGeneratedAt !== this.lastReasoningMeta.generated_at || !this.assessments) {
              this.lastReasoningMeta = { generated_at: latestGeneratedAt }
              this.assessments = parsed
              reasoningUpdated = true
            }
          }
        })
        .catch((err) => {
          clearTimeout(reasoningTimeout)
          if (err.name !== 'AbortError') {
            console.warn('Reasoning fetch bypassed:', err)
          }
        })

      // 3. Concurrently fetch Active Mission with a strict timeout (e.g. 1200ms)
      const missionController = new AbortController()
      const missionTimeout = setTimeout(() => missionController.abort(), 1200)
      const missionPromise = fetch(`${API_URL}/v1/oracle-development/missions/active`, { signal: missionController.signal })
        .then(async (res) => {
          clearTimeout(missionTimeout)
          if (res.ok) {
            const resData = await res.json()
            let activeMission = null

            if (Array.isArray(resData)) {
              activeMission = resData.find((m: any) => m.timeframe === this.currentLane) || null
            } else if (resData && typeof resData === 'object') {
              if (resData.mission) {
                activeMission = resData.mission
              } else if (resData.timeframe === this.currentLane) {
                activeMission = resData
              }
            }

            if (JSON.stringify(activeMission) !== JSON.stringify(this.activeMission)) {
              this.activeMission = activeMission
              reasoningUpdated = true
            }
          }
        })
        .catch((err) => {
          clearTimeout(missionTimeout)
          if (err.name !== 'AbortError') {
            console.warn('Active mission fetch bypassed:', err)
          }
        })

      // Wait for all promises (even if some are rejected/aborted, they catch internally)
      await Promise.all([chartPromise, reasoningPromise, missionPromise])

      this.loading = false
      this.error = null

      if (chartUpdated || reasoningUpdated) {
        this.notify()
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        this.error = err.message || 'Error fetching update cycle'
        this.notify()
      }
    } finally {
      this.inFlightChart = false
      this.inFlightReasoning = false
    }
  }
}

export const refreshScheduler = new RefreshScheduler()
