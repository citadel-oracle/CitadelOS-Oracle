import type { DashboardFeedKey, DashboardFeedMeta, DashboardProviderKind } from './index'

export interface DashboardFeedDto<T = unknown> {
  key: DashboardFeedKey
  data: T
  meta: DashboardFeedMeta
}

export interface DashboardSnapshotDto {
  schemaVersion: 1
  provider: DashboardProviderKind
  traceId: string
  generatedAt: string
  selectedSymbol: string
  feeds: DashboardFeedDto[]
}
