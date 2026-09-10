'use client'

import { Badge, Card, SectionHeader as DesignSectionHeader } from '@/design-system'
import workspaceStyles from '@/app/trading-workspace.module.css'

export interface ClosedTradeItem {
  trade_id: string
  position_id: string
  deployment_id: string
  strategy: string
  timeframe: string
  contract: string
  held_security_id: string
  entry_time: string
  entry_price: number
  exit_time: string
  exit_price: number
  quantity: number
  realized_pnl: number
  pnl_classification: string
  exit_reason: string
  holding_duration_seconds: number | null
  status: 'WINNING' | 'LOSING' | 'BREAKEVEN'
  order_chain: {
    signal_id?: string
    order_id?: string
    fill_id?: string
    position_id?: string
    lineage?: string[]
  }
  calculated_at: string
  option_contract?: {
    underlying?: string
    expiry?: string
    strike?: number
    option_type?: string
    lot_size?: number
    trading_symbol?: string
  }
}

export interface TodaysClosedTradesData {
  summary: {
    completed_trades: number
    wins: number
    losses: number
    breakeven: number
    win_rate: number
    gross_realized_pnl: number
    pnl_scope: string
    last_calculated_at: string
    exchange_date: string
  }
  trades: ClosedTradeItem[]
}

const price = (value: number) => `₹${value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const istTime = (value: string) => new Date(value).toLocaleTimeString('en-IN', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
  timeZone: 'Asia/Kolkata',
}).toUpperCase()

const duration = (seconds: number | null) => {
  if (seconds == null) return 'Not reported'
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remainder = total % 60
  return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${remainder}s` : `${remainder}s`
}

export function TodaysClosedTradesPanel({
  data,
  verifiedTime,
}: {
  data?: TodaysClosedTradesData | null
  verifiedTime?: string
}) {
  const trades = data?.trades ?? []
  const summary = data?.summary
  const realized = summary?.gross_realized_pnl ?? 0
  const realizedTone = realized > 0 ? workspaceStyles.closedPositive : realized < 0 ? workspaceStyles.closedNegative : workspaceStyles.closedNeutral

  return (
    <Card
      as="section"
      unstyled
      className={`panel workspace-unified-section ${workspaceStyles.panel} ${workspaceStyles.closedPanel}`}
      aria-label="Today Closed Positions"
    >
      <DesignSectionHeader
        as="div"
        unstyled
        className="section-heading"
        eyebrowClassName="section-eyebrow"
        eyebrow={<>03B / Trading Workspace<span className="status-dot live" title="Telemetry State: Live" /></>}
        title="Today Closed Positions"
        asideClassName="section-aside"
        aside={
          <div className={workspaceStyles.closedHeaderSummary}>
            <span>Closed <strong>{trades.length}</strong></span>
            <i />
            <span>Wins <strong className={workspaceStyles.closedPositive}>{summary?.wins ?? 0}</strong></span>
            <span>Losses <strong className={workspaceStyles.closedNegative}>{summary?.losses ?? 0}</strong></span>
            <i />
            <span>Realized <strong className={realizedTone}>{price(realized)}</strong></span>
            <Badge unstyled className={workspaceStyles.closedPaperBadge}>Paper only</Badge>
          </div>
        }
      />

      {trades.length === 0 ? (
        <div className={`workspace-unified-empty ${workspaceStyles.emptyState}`} role="status">
          <strong>NO POSITIONS CLOSED TODAY</strong>
          <span>{verifiedTime ? `Session data verified at ${verifiedTime}` : 'All registered strategies remain in the current session ledger.'}</span>
        </div>
      ) : (
        <div className={workspaceStyles.closedLedger} role="table" aria-label="Today closed paper trade ledger">
          <div className={workspaceStyles.closedLedgerHeader} role="row">
            <span role="columnheader">Instrument</span>
            <span role="columnheader">Strategy</span>
            <span role="columnheader">Lifecycle</span>
            <span role="columnheader">Qty / Lots</span>
            <span role="columnheader">Entry Avg → Exit Avg</span>
            <span role="columnheader">Exit</span>
            <span role="columnheader">Realized P&amp;L</span>
          </div>

          {trades.map((trade) => {
            const option = trade.option_contract
            const underlying = option?.underlying ?? 'NIFTY'
            const strike = option?.strike == null ? null : Number.isInteger(option.strike) ? option.strike.toFixed(0) : String(option.strike)
            const optionType = option?.option_type ?? (/_(CE|PE)_/.exec(trade.deployment_id)?.[1] ?? '')
            const readableContract = strike && optionType ? `${underlying} ${strike} ${optionType}` : trade.contract
            const expiry = option?.expiry
              ? new Date(`${option.expiry}T00:00:00+05:30`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' })
              : 'Expiry not reported'
            const expirySymbol = option?.expiry
              ? new Date(`${option.expiry}T00:00:00+05:30`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' }).toUpperCase()
              : ''
            const tradingSymbol = option?.trading_symbol ?? ([underlying, expirySymbol, strike, optionType].filter(Boolean).join(' ') || trade.contract)
            const quantity = trade.quantity > 0 ? trade.quantity : option?.lot_size ?? 0
            const lots = option?.lot_size && quantity ? quantity / option.lot_size : null
            const pnlTone = trade.realized_pnl > 0 ? workspaceStyles.closedPositive : trade.realized_pnl < 0 ? workspaceStyles.closedNegative : workspaceStyles.closedNeutral
            const reasonTone = trade.exit_reason.includes('TARGET') ? workspaceStyles.closedReasonPositive : trade.exit_reason.includes('STOP') ? workspaceStyles.closedReasonNegative : workspaceStyles.closedReasonNeutral

            return (
              <article className={workspaceStyles.closedTradeRow} data-trade-id={trade.trade_id} key={trade.trade_id} role="row">
                <div className={workspaceStyles.closedIdentity} role="cell">
                  <strong>{readableContract}</strong>
                  <small>{expiry} · {tradingSymbol}</small>
                </div>
                <div className={workspaceStyles.closedStrategy} role="cell">
                  <Badge unstyled>{trade.strategy}</Badge>
                  <small>{trade.timeframe}</small>
                </div>
                <div className={workspaceStyles.closedLifecycle} role="cell">
                  <strong>{istTime(trade.entry_time)} <i>→</i> {istTime(trade.exit_time)}</strong>
                  <small>{duration(trade.holding_duration_seconds)}</small>
                </div>
                <div className={workspaceStyles.closedQuantity} role="cell">
                  <strong>{quantity || '—'}</strong>
                  <small>{lots == null ? 'Lots not reported' : `${lots.toLocaleString('en-IN')} lot${lots === 1 ? '' : 's'}`}</small>
                </div>
                <div className={workspaceStyles.closedPrices} role="cell">
                  <strong>{price(trade.entry_price)} <i>→</i> {price(trade.exit_price)}</strong>
                  <small>Average fill</small>
                </div>
                <div className={workspaceStyles.closedExit} role="cell">
                  <Badge unstyled className={reasonTone}>{trade.exit_reason}</Badge>
                  <Badge unstyled className={workspaceStyles.closedPaperBadge}>Paper</Badge>
                </div>
                <strong className={`${workspaceStyles.closedPnl} ${pnlTone}`} role="cell">
                  {trade.realized_pnl > 0 ? '+' : trade.realized_pnl < 0 ? '−' : ''}{price(Math.abs(trade.realized_pnl))}
                </strong>
              </article>
            )
          })}
        </div>
      )}
    </Card>
  )
}
