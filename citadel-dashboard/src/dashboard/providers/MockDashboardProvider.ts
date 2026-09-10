import { DASHBOARD_SCHEMA_VERSION, DEFAULT_SYMBOL, MOCK_EMISSION_INTERVAL_MS } from '../constants/index'
import type { DashboardDataProvider } from '../contracts'
import type { DashboardFeedMeta, DashboardSourceSnapshot } from '../types'
import { DASHBOARD_FEED_KEYS } from '../types'
import { createMockFeeds } from './mockData'

export class MockDashboardProvider implements DashboardDataProvider {
  readonly kind = 'mock' as const
  private listeners = new Set<(snapshot: DashboardSourceSnapshot) => void>()
  private timer: ReturnType<typeof setTimeout> | null = null
  private symbol = DEFAULT_SYMBOL
  private revision = 0

  start() { this.emit(); this.schedule() }
  stop() { if (this.timer) clearTimeout(this.timer); this.timer = null }
  setSymbol(symbol: string) { this.symbol = symbol; this.emit() }
  refresh() { this.emit() }
  subscribe(listener: (snapshot: DashboardSourceSnapshot) => void) { this.listeners.add(listener); return () => this.listeners.delete(listener) }

  private schedule() {
    this.timer = setTimeout(() => { this.emit(); this.schedule() }, MOCK_EMISSION_INTERVAL_MS)
  }

  private emit() {
    this.revision += 1
    const generatedAt = new Date().toISOString()
    const feedMeta = Object.fromEntries(DASHBOARD_FEED_KEYS.map((key, index) => [key, {
      health: 'HEALTHY', readiness: 'READY', latency_ms: 24 + index,
      last_updated: generatedAt, source_last_updated: generatedAt,
    }])) as Record<(typeof DASHBOARD_FEED_KEYS)[number], DashboardFeedMeta>
    const snapshot: DashboardSourceSnapshot = {
      schemaVersion: DASHBOARD_SCHEMA_VERSION, provider: this.kind,
      traceId: `mock-${generatedAt}-${this.revision}`, generatedAt, selectedSymbol: this.symbol,
      feeds: createMockFeeds(generatedAt, this.symbol, Math.sin(this.revision / 2) * 0.35), feedMeta,
    }
    this.listeners.forEach((listener) => listener(snapshot))
  }
}
