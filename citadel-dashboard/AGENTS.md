# CITADEL OS — Agent Instructions

## 1. Project identity
CITADEL OS is an institutional trading operating system, not a retail trading dashboard. Preserve its professional, data-dense terminal philosophy.

## 2. Verified frontend architecture
Preserve this established flow:

`DashboardDataProvider → InMemoryDashboardRepository → DashboardDataAdapter → DashboardStore → memoized selectors → React UI`

Do not bypass, duplicate, or collapse these layers.

## 3. Provider selection
- `MockDashboardProvider` is selected only when `NEXT_PUBLIC_CITADEL_DATA_MODE` is exactly `"mock"`.
- `RestDashboardProvider` is selected for every other value.
- The current configured mode is REST.

## 4. Routes and render modes
- `/`: Production, Development, and Trading Workspace modes.
- Production and Development share the common master-dashboard render branch; their paper-engine projection differs.
- Trading Workspace renders `TradingWorkspace` separately.
- `/strategy-lab/[strategyId]`: read-only Strategy Lab research/runtime detail.
- `/kronos`: static observational KRONOS workspace.
- `/oracle`: static advisory Oracle workspace.
- `ProductionTerminal` is retained only as an inert rollback reference.

## 5. Data ownership
- The backend is the source of truth; the UI is presentation-only.
- Dashboard components must not fetch backend data directly. Extend the existing provider architecture instead. The Strategy Lab detail route is the existing route-specific GET exception.
- Preserve `Provider → Repository → Adapter → Store → Selectors → UI`.
- Widgets must consume centralized provider-originated state; do not give components independent business-data ownership.

## 6. Network and execution boundary
- The frontend currently performs only GET requests.
- `RestDashboardProvider` reads `/v2/dashboard`.
- Strategy Lab reads `/v1/strategy-lab/strategies/{strategyId}`.
- REST polling exists; no frontend WebSocket implementation currently exists.
- No frontend broker execution, order placement, or backend trading-state mutation exists.
- Do not introduce POST, PATCH, PUT, DELETE, broker-routing, or execution paths unless explicitly requested.

## 7. Intelligence boundaries
- KRONOS Alpha and Chronos2 are shadow/advisory projections with zero execution influence in the frontend contract.
- AEGIS is advisory-only and has `execution_permission: false`.
- Personal Oracle, ARGUS, ATHENA, and HERMES must not be assumed to have execution authority.
- Order & Fill Operations is audit-only and read-only.
- Do not let intelligence widgets filter, delay, suppress, reject, or block trades unless actual backend code explicitly requires it and the user specifically requests that behavior.
- UI wording such as WAIT, STOP, RISK, AUTHORIZATION, or FINAL DECISION does not itself establish execution authority.

## 8. High-risk files
Do not casually modify:

- `src/app/page.tsx`
- `src/app/globals.css`
- `src/app/trading-workspace.module.css`
- `src/dashboard/providers/RestDashboardProvider.ts`
- `src/dashboard/adapters/DashboardDataAdapter.ts`
- `src/dashboard/store/DashboardStore.ts`
- `src/dashboard/contexts/DashboardContext.tsx`
- `src/dashboard/types/index.ts`
- `src/dashboard/providers/mockData.ts`
- `src/design-system/tokens.css`
- `src/design-system/primitives.tsx`

## 9. UI lock
- Preserve the current institutional design.
- Never redesign, resize, restyle, rename, or reorganize UI unless explicitly requested.
- Active Deployments, Active Positions, Execution Timeline, and Latest Journal are approved Trading Workspace implementations.
- Preserve fonts, density, hierarchy, colors, spacing, and the dark terminal aesthetic.
- Prefer improving existing modules over rebuilding them.

## 10. Working rules
1. Inspect the relevant implementation before editing.
2. Make the smallest isolated change and touch the fewest files.
3. Never refactor unrelated code or rewrite working code.
4. Never create duplicate stores, providers, adapters, selectors, or component systems.
5. Never rename or move files without explicit approval.
6. Preserve strict TypeScript and existing architecture.
7. After implementation, run build, type-check, and lint without installing packages.
8. Stop and report if the required scope expands beyond the request.
9. Do not modify strategy logic or add execution permissions unless explicitly requested.

## 11. Known frontend facts
- Some mock feeds are null despite being assigned healthy metadata.
- `isRefreshing` is not currently driven correctly by the store/provider flow.
- `.env.example` uses `fixtures`, but that value does not select `MockDashboardProvider`; only exact `mock` does.
- REST failure preserves the last successful snapshot as stale; first-load failure publishes unavailable/null feeds.
- Symbol changes and manual refresh request another read-only dashboard projection.

## 12. Explicit unknowns
Backend strategy execution, Dhan ingestion, Paper Engine mutation, risk-veto enforcement, kill-switch enforcement, and intelligence influence cannot be proven from this frontend repository. Never invent or assume these behaviors. Inspect the relevant backend implementation before making any claim or change involving them.

## 13. Current project status
- Frontend UI and architecture are substantially complete.
- REST dashboard binding is implemented.
- Live-market and backend execution correctness still require backend inspection and market-hours verification.
