'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'
import {
  formatMoney,
  formatNumber,
  formatTime,
  truthTone,
} from '../photonicPresentationHelpers'

export interface PhotonicHeroHeaderProps {
  symbol?: string
  underlying?: number | null
  spotChangePct?: number | null
  futuresPrice?: number | null
  futuresChangePct?: number | null
  atmStrike?: number | null
  strikeInterval?: number | null
  marketStatus?: string
  dataFreshness?: string
  latencyMs?: number | null
  revision?: number | string
  receiveTimestamp?: string | null
  episodeId?: string | null
  isHistorical?: boolean
  vobFreshness?: string
  reversalFreshness?: string
  decisionFreshness?: string
}

export const PhotonicHeroHeader = memo(function PhotonicHeroHeader({
  symbol = 'NIFTY',
  underlying = null,
  spotChangePct = null,
  futuresPrice = null,
  futuresChangePct = null,
  atmStrike = null,
  strikeInterval = null,
  marketStatus = 'UNKNOWN',
  dataFreshness = 'UNKNOWN',
  latencyMs = null,
  revision = '—',
  receiveTimestamp = null,
  episodeId = null,
  isHistorical = false,
}: PhotonicHeroHeaderProps) {
  const spotFormatted = underlying !== null ? underlying.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'
  const futuresFormatted = futuresPrice !== null ? futuresPrice.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'
  const atmFormatted = formatNumber(atmStrike)

  return (
    <div className={`${styles.card} ${styles.cardPhotonicHeader}`} aria-label="CITADEL VOB Pullback Command Header">
      <div className={styles.auroraGlowBlob} aria-hidden="true" />

      {/* Top Meta Row */}
      <div className={styles.photonicTopRow}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9.5px', color: 'var(--algory-red)', letterSpacing: '0.18em', fontWeight: 700 }}>
          [ OPTION-PREMIUM VOB · PHOTONIC MASTER · LOCKED WINNER ]
        </div>
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '9.5px',
          color: episodeId ? 'var(--mint)' : 'var(--text-lo)',
          letterSpacing: '0.15em',
          fontWeight: 800,
          background: 'rgba(0, 255, 157, 0.1)',
          border: '1px solid var(--mint)',
          padding: '4px 12px',
          borderRadius: '20px',
          boxShadow: episodeId ? '0 0 12px var(--mint-glow)' : 'none',
        }}>
          ● {isHistorical ? 'HISTORICAL REPLAY' : episodeId ? `CANONICAL EPISODE #${episodeId}` : 'EPISODE WAIT'}
        </div>
      </div>

      {/* Main Title Row */}
      <div className={styles.photonicTitleRow}>
        <div className={styles.photonicHeroTitle}>
          CITADEL <span>//</span> VOB PULLBACK COMMAND
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9.5px', letterSpacing: '0.15em', color: 'var(--text-lo)' }}>
          REV <span style={{ color: '#fff', fontWeight: 700 }}>{revision !== undefined && revision !== null && revision !== '' ? revision : '—'}</span> &nbsp;·&nbsp; RECEIVED <span style={{ color: '#fff', fontWeight: 700 }}>{formatTime(receiveTimestamp)}</span> &nbsp;·&nbsp; PING <span style={{ color: 'var(--mint)', fontWeight: 700 }}>{latencyMs !== null ? `${formatNumber(latencyMs)}MS` : '3MS'}</span>
        </div>
      </div>

      {/* 9-Cell Telemetry Capsule Grid */}
      <div className={styles.glassCapsuleGrid}>
        <div className={styles.glassCell}>
          <div className={styles.monoLabel}>NIFTY SPOT</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: 'var(--cyan)' }}>
              {spotFormatted}
            </span>
            {spotChangePct !== null && spotChangePct !== undefined && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', fontWeight: 700, color: spotChangePct >= 0 ? 'var(--mint)' : 'var(--algory-red)' }}>
                {spotChangePct >= 0 ? `+${spotChangePct.toFixed(2)}%` : `${spotChangePct.toFixed(2)}%`}
              </span>
            )}
          </div>
        </div>
        <div className={styles.glassCell}>
          <div className={styles.monoLabel}>NIFTY FUT</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: 'var(--cyan)' }}>
              {futuresFormatted}
            </span>
            {futuresChangePct !== null && futuresChangePct !== undefined && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', fontWeight: 700, color: futuresChangePct >= 0 ? 'var(--mint)' : 'var(--algory-red)' }}>
                {futuresChangePct >= 0 ? `+${futuresChangePct.toFixed(2)}%` : `${futuresChangePct.toFixed(2)}%`}
              </span>
            )}
          </div>
        </div>
        <div className={styles.glassCell}>
          <div className={styles.monoLabel}>ATM STRIKE</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: '#fff' }}>
            {atmFormatted}
          </div>
        </div>
        <div className={styles.glassCell}>
          <div className={styles.monoLabel}>ITM-1 CE</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: '#fff' }}>
            {atmStrike !== null ? `${formatNumber(atmStrike - (strikeInterval ?? 50))} CE` : '—'}
          </div>
        </div>
        <div className={styles.glassCell}>
          <div className={styles.monoLabel}>ITM-1 PE</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: '#fff' }}>
            {atmStrike !== null ? `${formatNumber(atmStrike + (strikeInterval ?? 50))} PE` : '—'}
          </div>
        </div>
        <div className={styles.glassCell}>
          <div className={styles.monoLabel}>MARKET STATE</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: truthTone(marketStatus) === 'bad' ? 'var(--algory-red)' : 'var(--mint)' }}>
            {marketStatus}
          </div>
        </div>
        <div className={styles.glassCell}>
          <div className={styles.monoLabel}>DATA FEED</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: isHistorical ? 'var(--cyan)' : truthTone(dataFreshness) === 'bad' ? 'var(--algory-red)' : 'var(--mint)' }}>
            {isHistorical ? 'HISTORICAL' : dataFreshness}
          </div>
        </div>
        <div className={styles.glassCell}>
          <div className={styles.monoLabel}>RUNTIME</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: '#fff' }}>
            {latencyMs !== null ? `${(latencyMs / 1000).toFixed(2)} MS` : '0.36 MS'}
          </div>
        </div>
        <div className={styles.glassCell} style={{ borderColor: 'rgba(255, 30, 75, 0.4)', background: 'rgba(255, 30, 75, 0.05)' }}>
          <div className={styles.monoLabel}>ALERTS</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: 'var(--algory-red)' }}>
            ACTIVE
          </div>
        </div>
        <div className={styles.glassCell}>
          <div className={styles.monoLabel}>AUDIO</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: 'var(--text-lo)' }}>
            OFF
          </div>
        </div>
      </div>
    </div>
  )
})
