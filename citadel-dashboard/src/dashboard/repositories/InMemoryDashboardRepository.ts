import type { DashboardDataProvider, DashboardRepository } from '../contracts'
import type { DashboardSourceSnapshot } from '../types'

export class InMemoryDashboardRepository implements DashboardRepository {
  constructor(private readonly provider: DashboardDataProvider) {}
  connect(listener: (snapshot: DashboardSourceSnapshot) => void) {
    const unsubscribe = this.provider.subscribe(listener)
    this.provider.start()
    return () => { unsubscribe(); this.provider.stop() }
  }
  setSymbol(symbol: string) { this.provider.setSymbol(symbol) }
  refresh() { this.provider.refresh() }
}
