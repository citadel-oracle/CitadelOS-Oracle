'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import type {
  OracleTradeRecord,
  OracleVobEpisode,
  VobTimeframe,
} from '@/dashboard/store/oracleStore'
import {
  formatDisplayTradeId,
  formatMoney,
  formatR,
  pnlTone,
  UNKNOWN,
} from '../photonicPresentationHelpers'

export interface PhotonicTradeLedgerProps {
  activeTrades?: readonly OracleTradeRecord[]
  episodesByTimeframe?: Readonly<Record<VobTimeframe, OracleVobEpisode | null>>
  isHistorical?: boolean
}

export const PhotonicTradeLedger = memo(function PhotonicTradeLedger({
  activeTrades = [],
  episodesByTimeframe,
  isHistorical = false,
}: PhotonicTradeLedgerProps) {
  const tradeCount = activeTrades.length

  return (
    <div
      className={styles.card}
      style={{ gridColumn: '1 / -1', padding: '18px 24px' }}
      aria-label="VOB Multi-Timeframe Trade Ledger"
      id="photonic-trade-ledger"
    >
      <div className={styles.infiniteRibbonLayer} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      {/* Header Strip */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span className={styles.monoLabel} style={{ fontWeight: 700, letterSpacing: '0.08em', color: 'var(--text-white)' }}>
            MULTI-TIMEFRAME VOB TRADE LEDGER
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '8px',
              padding: '2px 6px',
              borderRadius: '3px',
              background: tradeCount > 0 ? 'rgba(0, 255, 157, 0.12)' : 'rgba(255, 255, 255, 0.05)',
              color: tradeCount > 0 ? 'var(--mint)' : 'var(--text-dim)',
              fontWeight: 700,
              border: tradeCount > 0 ? '1px solid rgba(0, 255, 157, 0.3)' : '1px solid var(--line-dim)',
            }}
          >
            {tradeCount} {tradeCount === 1 ? 'ACTIVE RECORD' : 'ACTIVE RECORDS'}
          </span>
          {isHistorical && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '8px',
                padding: '2px 6px',
                borderRadius: '3px',
                background: 'rgba(0, 240, 255, 0.1)',
                color: 'var(--cyan)',
                border: '1px solid rgba(0, 240, 255, 0.25)',
              }}
            >
              HISTORICAL REPLAY
            </span>
          )}
        </div>
        <div className={styles.monoLabel} style={{ color: 'var(--cyan)', fontSize: '8px' }}>
          CONCURRENT 1M • 3M • 5M SHADOW EXECUTION
        </div>
      </div>

      {/* Table Content */}
      {tradeCount === 0 ? (
        <div
          style={{
            padding: '24px 16px',
            textAlign: 'center',
            background: 'rgba(0, 0, 0, 0.25)',
            borderRadius: '8px',
            border: '1px dashed var(--line-dim)',
          }}
        >
          <div className={styles.monoLabel} style={{ color: 'var(--text-dim)', fontSize: '9px', marginBottom: '4px' }}>
            NO ACTIVE VOB TRADES
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '7.5px', color: 'var(--text-lo)' }}>
            Awaiting canonical 1M / 3M / 5M VOB zone pullbacks and reversal confirmations
          </div>
        </div>
      ) : (
        <div style={{ overflowX: 'auto', width: '100%' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontFamily: 'var(--font-mono)',
              fontSize: '8.5px',
            }}
          >
            <thead>
              <tr
                style={{
                  borderBottom: '1px solid var(--line-dim)',
                  color: 'var(--text-dim)',
                  textAlign: 'left',
                }}
              >
                <th style={{ padding: '6px 8px', fontWeight: 600 }}>TRADE ID</th>
                <th style={{ padding: '6px 8px', fontWeight: 600 }}>TF</th>
                <th style={{ padding: '6px 8px', fontWeight: 600 }}>STRATEGY</th>
                <th style={{ padding: '6px 8px', fontWeight: 600 }}>CONTRACT</th>
                <th style={{ padding: '6px 8px', fontWeight: 600, textAlign: 'right' }}>ENTRY</th>
                <th style={{ padding: '6px 8px', fontWeight: 600, textAlign: 'right' }}>CURRENT</th>
                <th style={{ padding: '6px 8px', fontWeight: 600, textAlign: 'center' }}>STATUS</th>
                <th style={{ padding: '6px 8px', fontWeight: 600, textAlign: 'right' }}>P&L</th>
                <th style={{ padding: '6px 8px', fontWeight: 600, textAlign: 'right' }}>R MULTIPLE</th>
              </tr>
            </thead>
            <tbody>
              {activeTrades.map((trade) => {
                const tone = pnlTone(trade.pnl)
                const isConfirmed = trade.variant === 'CONFIRMED_REVERSAL'
                const isEarly = trade.variant === 'EARLY_REVERSAL'
                const isOriginal = trade.variant === 'VOB_ONLY'

                const tf = trade.timeframe || '—'
                const tfBadgeStyle: React.CSSProperties =
                  tf === '1M'
                    ? { background: 'rgba(0, 240, 255, 0.12)', color: 'var(--cyan)', borderColor: 'rgba(0, 240, 255, 0.3)' }
                    : tf === '3M'
                    ? { background: 'rgba(255, 184, 0, 0.12)', color: 'var(--amber)', borderColor: 'rgba(255, 184, 0, 0.3)' }
                    : { background: 'rgba(0, 255, 157, 0.12)', color: 'var(--mint)', borderColor: 'rgba(0, 255, 157, 0.3)' }

                const variantBadgeStyle: React.CSSProperties = isConfirmed
                  ? { background: 'rgba(0, 255, 157, 0.14)', color: 'var(--mint)', border: '1px solid rgba(0, 255, 157, 0.35)', fontWeight: 700 }
                  : isEarly
                  ? { background: 'rgba(255, 184, 0, 0.12)', color: 'var(--amber)', border: '1px solid rgba(255, 184, 0, 0.3)' }
                  : { background: 'rgba(255, 255, 255, 0.06)', color: 'var(--text-white)', border: '1px solid var(--line-dim)' }

                const contractLabel = trade.contract.tradingSymbol
                  || (trade.contract.strike && trade.contract.optionType ? `${trade.contract.strike} ${trade.contract.optionType}` : null)
                  || trade.contract.securityId
                  || '—'

                const pnlText = trade.pnl !== null && trade.pnl !== undefined
                  ? formatMoney(trade.pnl)
                  : 'P&L NOT REPORTED'

                const rText = formatR(trade.rMultiple)
                const displayTradeId = formatDisplayTradeId(trade.tradeId, trade.timeframe)

                return (
                  <tr
                    key={trade.tradeId}
                    style={{
                      borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                      transition: 'background-color 150ms ease',
                    }}
                  >
                    {/* Trade ID */}
                    <td style={{ padding: '8px 8px', color: 'var(--text-white)' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', fontWeight: 700, letterSpacing: '0.04em', color: 'var(--cyan)' }}>
                          {displayTradeId}
                        </span>
                        <span
                          title={`CANONICAL TRADE ID: ${trade.tradeId}`}
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '7px',
                            color: 'var(--text-dim)',
                            cursor: 'help',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            maxWidth: '120px',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {trade.tradeId.length > 18 ? `${trade.tradeId.slice(0, 8)}...${trade.tradeId.slice(-6)}` : trade.tradeId}
                        </span>
                      </div>
                    </td>

                    {/* Timeframe */}
                    <td style={{ padding: '8px 8px' }}>
                      <span
                        style={{
                          padding: '1px 5px',
                          borderRadius: '3px',
                          border: '1px solid',
                          fontSize: '7.5px',
                          fontWeight: 700,
                          ...tfBadgeStyle,
                        }}
                      >
                        {tf}
                      </span>
                    </td>

                    {/* Strategy Variant */}
                    <td style={{ padding: '8px 8px' }}>
                      <span
                        style={{
                          padding: '1px 6px',
                          borderRadius: '3px',
                          fontSize: '7.5px',
                          letterSpacing: '0.04em',
                          ...variantBadgeStyle,
                        }}
                      >
                        {isConfirmed ? 'CONFIRMED' : isEarly ? 'EARLY' : 'ORIGINAL'}
                      </span>
                    </td>

                    {/* Contract */}
                    <td style={{ padding: '8px 8px', color: 'var(--text-white)' }}>
                      {contractLabel}
                    </td>

                    {/* Entry Price */}
                    <td style={{ padding: '8px 8px', textAlign: 'right', color: 'var(--text-white)' }}>
                      {formatMoney(trade.entryPrice)}
                    </td>

                    {/* Current Bid */}
                    <td style={{ padding: '8px 8px', textAlign: 'right', color: 'var(--text-white)' }}>
                      {formatMoney(trade.currentBid)}
                    </td>

                    {/* Status */}
                    <td style={{ padding: '8px 8px', textAlign: 'center' }}>
                      <span
                        style={{
                          padding: '1px 5px',
                          borderRadius: '3px',
                          fontSize: '7px',
                          fontWeight: 700,
                          background: trade.status === 'ACTIVE' ? 'rgba(0, 255, 157, 0.12)' : 'rgba(255, 255, 255, 0.05)',
                          color: trade.status === 'ACTIVE' ? 'var(--mint)' : 'var(--text-dim)',
                          border: trade.status === 'ACTIVE' ? '1px solid rgba(0, 255, 157, 0.3)' : '1px solid var(--line-dim)',
                        }}
                      >
                        {trade.status}
                      </span>
                    </td>

                    {/* P&L */}
                    <td
                      style={{
                        padding: '8px 8px',
                        textAlign: 'right',
                        fontWeight: 600,
                        color: tone === 'positive' ? 'var(--mint)' : tone === 'negative' ? 'var(--algory-red)' : 'var(--text-dim)',
                      }}
                    >
                      {pnlText}
                    </td>

                    {/* R Multiple */}
                    <td
                      style={{
                        padding: '8px 8px',
                        textAlign: 'right',
                        fontWeight: 700,
                        color: tone === 'positive' ? 'var(--mint)' : tone === 'negative' ? 'var(--algory-red)' : 'var(--text-white)',
                      }}
                    >
                      {rText}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
})
