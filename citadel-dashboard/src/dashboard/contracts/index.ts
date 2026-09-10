import type { DashboardSourceSnapshot } from '../types'

export interface DashboardDataProvider {
  readonly kind: 'mock' | 'rest' | 'websocket' | 'replay' | 'historical'
  start(): void
  stop(): void
  setSymbol(symbol: string): void
  refresh(): void
  subscribe(listener: (snapshot: DashboardSourceSnapshot) => void): () => void
}

export interface DashboardRepository {
  connect(listener: (snapshot: DashboardSourceSnapshot) => void): () => void
  setSymbol(symbol: string): void
  refresh(): void
}

export interface DhanDataContract { subscribeCompletedCandles(symbols: string[]): () => void; getQuote(symbol: string): Promise<unknown> }
export interface PaperEngineContract { readSummary(): Promise<unknown>; readPositions(): Promise<unknown> }
export interface DeploymentEngineContract { readDeployments(): Promise<unknown> }
export interface ExecutionEngineContract { readOrders(): Promise<unknown>; readFills(): Promise<unknown> }
export interface JournalContract { readLatest(limit: number): Promise<unknown> }
export interface TimelineContract { readLatest(limit: number): Promise<unknown> }
export interface RiskEngineContract { readRisk(): Promise<unknown> }
export interface HealthEngineContract { readHealth(): Promise<unknown> }
export interface StrategyRuntimeContract { readRuntimeState(): Promise<unknown> }
export interface NotificationsContract { readNotifications(): Promise<unknown> }
