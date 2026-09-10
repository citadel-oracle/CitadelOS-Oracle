import type { DashboardRepository } from '../contracts'
import { DEFAULT_SYMBOL } from '../constants'
import type { DashboardSections, DashboardState } from '../models/entities'
import { DASHBOARD_FEED_KEYS } from '../types'
import { DashboardDataAdapter } from '../adapters/DashboardDataAdapter'

const emptySections: DashboardSections = {
  header: { system: '', mode: '', strategy: '', lastUpdate: '', autoRefresh: true, refreshIntervalMs: 0 }, marketSession: { state: 'closed', marketOpen: false, exchange: '', timezone: '', reason: '' },
  deploymentSummary: { deployed: 0, running: 0, healthy: 0, openPositions: 0 }, activeDeployments: [], activePositions: [], executionTimeline: [], latestJournal: [],
  paperEngineSummary: { orders: 0, fills: 0, open: 0, closed: 0, rejected: 0, cancelled: 0, realizedPnl: 0, unrealizedPnl: 0 },
  systemHealth: { backend: 'unknown', scheduler: 'unknown', projection: 'unknown', paperEngine: 'unknown' }, connectionStatus: { state: 'offline', lastUpdate: '', source: '' }, latency: { currentMs: 0, averageMs: 0, maximumMs: 0 },
  risk: { usedPercent: 0, exposure: 0, dailyLimit: 0, state: 'unknown' }, capital: { initial: 0, current: 0, available: 0, equity: 0 }, exposure: { gross: 0, net: 0, openPositions: 0 }, performance: { realizedPnl: 0, unrealizedPnl: 0, totalPnl: 0, wins: 0, losses: 0, winRate: 0 },
  notifications: [], runtimeStatus: { manager: 'waiting', scheduler: 'waiting', processedCandles: 0, duplicateSuppression: true }, footer: { product: '', build: '', telemetry: '' },
}

export class DashboardStore {
  private listeners = new Set<() => void>()
  private disconnect: (() => void) | null = null
  private state: DashboardState = { feeds: Object.fromEntries(DASHBOARD_FEED_KEYS.map((key) => [key, { data: null, error: null, lastUpdated: null, loading: true }])) as DashboardState['feeds'], feedMeta: {}, forecastProjectionMeta: null, sections: emptySections, selectedSymbol: DEFAULT_SYMBOL, isRefreshing: false, revision: 0 }
  constructor(private readonly repository: DashboardRepository, private readonly adapter: DashboardDataAdapter) {}
  getSnapshot = () => this.state
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener) }
  start() { if (!this.disconnect) this.disconnect = this.repository.connect((snapshot) => { this.state = this.adapter.toState(snapshot, this.state); this.emit() }) }
  stop() { this.disconnect?.(); this.disconnect = null }
  setSymbol(symbol: string) { this.repository.setSymbol(symbol) }
  refresh() { this.repository.refresh() }
  updateSection<K extends keyof DashboardSections>(section: K, value: DashboardSections[K]) {
    this.state = { ...this.state, sections: { ...this.state.sections, [section]: value }, revision: this.state.revision + 1 }
    this.emit()
  }
  private emit() { this.listeners.forEach((listener) => listener()) }
}
