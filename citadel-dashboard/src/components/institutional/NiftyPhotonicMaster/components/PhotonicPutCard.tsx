'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import type { OracleContractIdentity, OracleOptionDisplay, OracleTradeRecord } from '@/dashboard/store/oracleStore'
import { PhotonicOptionVobSection } from './PhotonicOptionVobSection'
import {
  contractLabel,
  formatBuildup,
  formatChangeOi,
  formatLacOi,
  formatMoney,
  formatOiWindowLabel,
  formatTime,
  UNKNOWN,
} from '../photonicPresentationHelpers'

export interface PhotonicPutCardProps {
  option?: OracleOptionDisplay | null
  currentItm1?: OracleContractIdentity | null
  target?: boolean
  geometry?: { pricePct: number; zoneStartPct: number; zoneEndPct: number } | null
  isHistorical?: boolean
  trade?: OracleTradeRecord | null
}

export const PhotonicPutCard = memo(function PhotonicPutCard({
  option = null,
  target = false,
  geometry = null,
  trade = null,
}: PhotonicPutCardProps) {
  const premium = option?.premium ?? null
  const strike = option?.contract ? contractLabel(option.contract.strike, option.contract.optionType) : UNKNOWN
  const frozen = option?.contractStatus === 'FROZEN_EPISODE'

  return (
    <div
      className={`${styles.card} ${styles.profitCard} ${styles.cardPut} ${target ? styles.surgePut : ''}`}
      data-target={target}
      aria-label="Frozen Put Option Card"
    >
      <div className={`${styles.infiniteRibbonLayer} ${styles.reverseRibbon}`} aria-hidden="true" />
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />

      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '14px', gap: '8px' }}>
        <div className={styles.monoLabel} style={{ color: 'var(--algory-red)' }}>
          {frozen ? 'FROZEN PUT [PE]' : 'CURRENT ITM-1 PUT [PE]'}
        </div>
        {(() => {
          const resolver = option?.resolverEvent
          const lastMeaningful = (resolver as any)?.last_meaningful_event || (resolver as any)?.lastMeaningfulEvent
          const defaultLabel = frozen ? 'FROZEN EPISODE PE' : 'ACTIVE RESOLVER'
          const label = resolver?.label || defaultLabel
          const variant = resolver?.variant || 'amber'
          const variantClass = variant === 'mint' ? styles.pillMint : variant === 'red' ? styles.pillRed : variant === 'amber' ? styles.pillAmber : styles.pillCyan
          const isFresh = resolver?.confluenceState === 'FULL_FRESH'
          return (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '3px' }}>
              <div
                key={resolver?.pulseKey || 'default_pe_resolver'}
                className={`${styles.pill} ${variantClass}`}
                title={resolver?.sourceEventTime ? `Event time: ${resolver.sourceEventTime}` : undefined}
                style={isFresh ? { boxShadow: variant === 'mint' ? '0 0 14px var(--mint-glow)' : variant === 'red' ? '0 0 14px var(--algory-red-glow)' : undefined } : undefined}
              >
                ▲ {label}
              </div>
              {lastMeaningful && (label.startsWith('ACTIVE RESOLVER') || lastMeaningful.is_previous_contract || lastMeaningful.isPreviousContract) ? (
                <div
                  style={{
                    fontSize: '8px',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--cyan)',
                    background: 'rgba(0,240,255,0.06)',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    border: '1px solid rgba(0,240,255,0.25)',
                    whiteSpace: 'nowrap',
                  }}
                  title={`Event Time: ${lastMeaningful.event_timestamp || lastMeaningful.eventTimestamp || 'N/A'}`}
                >
                  {(lastMeaningful.context_badge || lastMeaningful.contextBadge)
                    ? `LAST: ${lastMeaningful.context_badge || lastMeaningful.contextBadge} · ${lastMeaningful.label}`
                    : `LAST EVENT: ${lastMeaningful.label}`}
                </div>
              ) : null}
            </div>
          )
        })()}
      </div>

      <div className={styles.title} style={{ fontSize: '26px', marginBottom: '8px' }}>
        {strike}
      </div>

      {/* Hero Price with Daily % Change */}
      <div className={styles.heroPrice} style={{ marginBottom: '12px', color: 'var(--algory-red)', display: 'flex', alignItems: 'baseline', gap: '8px' }}>
        <span>{formatMoney(premium)}</span>
        {option?.dayChangePct !== null && option?.dayChangePct !== undefined ? (
          <span style={{ fontSize: '13px', color: option.dayChangePct >= 0 ? 'var(--mint)' : 'var(--algory-red)', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
            {option.dayChangePct >= 0 ? `+${option.dayChangePct.toFixed(2)}%` : `${option.dayChangePct.toFixed(2)}%`} TODAY
          </span>
        ) : option?.distancePct !== null && option?.distancePct !== undefined ? (
          <span style={{ fontSize: '13px', color: 'var(--algory-red)', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
            {option.distancePct >= 0 ? `+${option.distancePct.toFixed(2)}%` : `${option.distancePct.toFixed(2)}%`}
          </span>
        ) : null}
      </div>

      {/* Canonical Option Open Interest, ΔOI & Derived Positioning Box */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          marginBottom: '14px',
          background: 'rgba(255, 30, 75, 0.04)',
          padding: '8px 12px',
          borderRadius: '8px',
          border: '1px solid var(--line-dim)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
            <span className={styles.monoLabel} style={{ color: 'var(--text-mid)', fontSize: '9px' }}>OI</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 800, color: '#fff' }}>
              {formatLacOi(option?.oi)}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
            <span className={styles.monoLabel} style={{ color: 'var(--text-lo)', fontSize: '9px' }}>
              {option?.openingOi ? `OPEN ${formatLacOi(option.openingOi)} → ` : ''}
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
                fontWeight: 700,
                color: (option?.changeOi ?? 0) >= 0 ? 'var(--mint)' : 'var(--algory-red)',
              }}
            >
              {formatChangeOi(option?.changeOi)}
            </span>
          </div>
        </div>

        {/* 5M / 15M OI Window Rows — always visible */}
        {(() => {
          const w5 = formatOiWindowLabel('5M', option?.oi5mChange)
          const w15 = formatOiWindowLabel('15M', option?.oi15mChange)
          return (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '4px' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
                  <span className={styles.monoLabel} style={{ color: 'var(--text-mid)', fontSize: '9px' }}>5M TACTICAL</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', fontWeight: 700, color: w5 ? (w5.oiPositive ? 'var(--mint)' : 'var(--algory-red)') : 'var(--text-lo)' }}>
                    {w5 ? w5.oiText : '—'}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
                  {w5 ? (
                    <>
                      <span className={styles.monoLabel} style={{ fontSize: '9px', color: 'var(--text-lo)' }}>{w5.priceText}</span>
                      <span className={styles.monoLabel} style={{ fontSize: '9px', fontWeight: 800, color: 'var(--cyan)', letterSpacing: '0.04em' }}>{w5.structureText}</span>
                    </>
                  ) : null}
                </div>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '4px' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
                  <span className={styles.monoLabel} style={{ color: 'var(--text-mid)', fontSize: '9px' }}>15M CONFIRMATION</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', fontWeight: 700, color: w15 ? (w15.oiPositive ? 'var(--mint)' : 'var(--algory-red)') : 'var(--text-lo)' }}>
                    {w15 ? w15.oiText : '—'}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
                  {w15 ? (
                    <>
                      <span className={styles.monoLabel} style={{ fontSize: '9px', color: 'var(--text-lo)' }}>{w15.priceText}</span>
                      <span className={styles.monoLabel} style={{ fontSize: '9px', fontWeight: 800, color: 'var(--cyan)', letterSpacing: '0.04em' }}>{w15.structureText}</span>
                    </>
                  ) : null}
                </div>
              </div>
            </>
          )
        })()}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '4px' }}>
          <span className={styles.monoLabel} style={{ fontSize: '9px', color: 'var(--text-mid)' }}>
            {option?.positioningFormula ?? 'PRICE ↑ + OI ↑'}
          </span>
          <span
            className={styles.monoLabel}
            style={{
              fontSize: '9.5px',
              fontWeight: 800,
              color: 'var(--algory-red)',
              letterSpacing: '0.04em',
            }}
          >
            {option?.derivedPositioning ?? formatBuildup(option?.positioning, 'PE')}
          </span>
        </div>
      </div>

      {/* Bid / Ask */}
      <div style={{ display: 'flex', gap: '24px', fontFamily: 'var(--font-mono)', fontSize: '11px', marginBottom: '16px' }}>
        <div><span style={{ color: 'var(--text-lo)' }}>BID</span> <span style={{ color: 'var(--text-white)', fontWeight: 700 }}>{formatMoney(option?.bid)}</span></div>
        <div><span style={{ color: 'var(--text-lo)' }}>ASK</span> <span style={{ color: 'var(--text-white)', fontWeight: 700 }}>{formatMoney(option?.ask)}</span></div>
      </div>

      {/* Telemetry / Quote timestamp */}
      <div className={styles.monoLabel} style={{ marginBottom: '20px' }}>
        <span style={{ color: option?.freshness === 'STALE' ? 'var(--algory-red)' : 'var(--mint)', fontWeight: 700 }}>● {option?.freshness ?? 'LIVE'}</span> <span style={{ color: 'var(--text-lo)' }}>{formatTime(option?.quoteTimestamp)} &nbsp;·&nbsp; TICK {option?.contract.securityId ?? '—'}</span>
      </div>

      <PhotonicOptionVobSection side="PE" option={option} trade={trade} geometry={geometry} />
    </div>
  )
})
