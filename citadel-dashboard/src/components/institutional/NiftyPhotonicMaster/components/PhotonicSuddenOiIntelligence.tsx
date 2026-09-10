'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'

type JsonRecord = Readonly<Record<string, unknown>>

export interface PhotonicSuddenOiIntelligenceProps {
  intelligence?: JsonRecord | null
}

export interface PhotonicSuddenOiSideCardProps extends PhotonicSuddenOiIntelligenceProps {
  side: 'CALL' | 'PUT'
}

export interface SuddenOiAlertFrame {
  eventId: string
  eventType: string
  side: string
  title: string
  detail: string
}

export function suddenOiAlertFrames(intelligence: JsonRecord | null | undefined): SuddenOiAlertFrame[] {
  const sudden = record(intelligence?.sudden_oi)
  const events = Array.isArray(sudden.alerts) ? sudden.alerts.map(record) : []
  return events.flatMap((event) => {
    const eventId = typeof event.event_id === 'string' ? event.event_id : null
    const title = typeof event.title === 'string' ? event.title : null
    if (!eventId || !title) return []
    return [{
      eventId,
      eventType: text(event.event_type),
      side: text(event.side),
      title,
      detail: typeof event.detail === 'string' ? event.detail : '',
    }]
  })
}

export const PhotonicSuddenOiIntelligence = memo(function PhotonicSuddenOiIntelligence({
  intelligence = null,
}: PhotonicSuddenOiIntelligenceProps) {
  return (
    <section className={styles.suddenOiModule} aria-label="Sudden OI Intelligence">
      <div className={styles.suddenOiCards}>
        <PhotonicSuddenOiSideCard side="CALL" intelligence={intelligence} />
        <PhotonicSuddenOiSideCard side="PUT" intelligence={intelligence} />
      </div>
      <PhotonicSuddenOiSharedContext intelligence={intelligence} />
    </section>
  )
})

export const PhotonicSuddenOiSideCard = memo(function PhotonicSuddenOiSideCard({
  side,
  intelligence = null,
}: PhotonicSuddenOiSideCardProps) {
  const sudden = record(intelligence?.sudden_oi)
  return <SuddenOiSideCard side={side} data={record(sudden[side])} />
})

export const PhotonicSuddenOiSharedContext = memo(function PhotonicSuddenOiSharedContext({
  intelligence = null,
}: PhotonicSuddenOiIntelligenceProps) {
  const sudden = record(intelligence?.sudden_oi)
  const price = record(sudden.price_oi_response)
  const book = record(sudden.nifty_book)
  const release = record(sudden.activity_release)
  return (
    <section className={`${styles.card} ${styles.suddenOiShared}`} aria-label="Sudden OI shared context">
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />
      <div className={styles.suddenOiSharedGrid}>
        <SharedBlock title="PRICE ↔ OI RESPONSE">
          <Metric label="NIFTY" value={formatPoints(number(price.nifty_price_change_2m), ' / 2m')} />
          <Metric label="Price Speed" value={formatPercent(number(price.price_speed_percentile))} />
          <Metric label="CALL OI" value={formatPercent(number(price.call_oi_percentile))} />
          <Metric label="CALL Timing" value={text(price.call_timing)} />
          <Metric label="PUT OI" value={formatPercent(number(price.put_oi_percentile))} />
          <Metric label="PUT Timing" value={text(price.put_timing)} />
          <Metric label="READ" value={text(price.read)} tone="cyan" strong />
        </SharedBlock>
        <SharedBlock title="NIFTY BOOK">
          <Metric label="Pressure" value={bookPressure(book)} tone={bookTone(text(book.direction))} strong />
          <Metric label="MLOFI" value={formatSigned(number(book.mlofi))} />
          <div className={styles.suddenOiScope}>{text(book.scope)}</div>
        </SharedBlock>
        <SharedBlock title="ACTIVITY RELEASE">
          <Metric label="Price Speed" value={formatPercent(number(release.price_speed_percentile))} />
          <Metric label="OI Activity" value={formatPercent(number(release.oi_activity_percentile))} />
          <Metric label="Straddle Activity" value={formatPercent(number(release.straddle_activity_percentile))} />
          <Metric label="Book Pressure" value={bookPressure({ direction: release.book_pressure_direction, pressure_x: release.book_pressure_x })} />
          <Metric label="READ" value={text(release.read)} tone="amber" strong />
        </SharedBlock>
      </div>
    </section>
  )
})

function SuddenOiSideCard({ side, data }: { side: 'CALL' | 'PUT'; data: JsonRecord }) {
  const isCall = side === 'CALL'
  const top = record(data.top_strike)
  const breadth = record(data.breadth)
  const current = number(data.current_5m_activity)
  const previous = number(data.previous_5m_activity)
  const normal = number(data.normal_5m_activity)
  const vsNormal = number(data.current_to_normal_x)
  const recent = Array.isArray(data.recent_5m_activity)
    ? data.recent_5m_activity.map(record).filter((item) => number(item.activity) !== null).slice(-5)
    : []
  const priorHigh = number(data.previous_session_high)
  const percentile = number(data.percentile)
  const extreme = data.new_session_extreme === true
  const status = text(data.status)
  const warming = status === 'WARMING' || status === 'PARTIAL_SESSION'
  const unavailable = status === 'UNAVAILABLE' || status === '—'
  const squeeze = top.squeeze === true
  const validCount = number(breadth.valid) ?? 0
  const hasEvidence = validCount > 0
  const eventKey = `${text(data.window_closed_at)}:${extreme ? 'EXTREME' : 'NORMAL'}:${text(top.security_id)}`
  const attention = extreme || squeeze
  const semanticTone: Tone = warming || attention ? 'amber' : unavailable ? 'cyan' : 'cyan'
  const cardClass = `${styles.card} ${isCall ? styles.cardCall : styles.cardPut} ${warming || attention ? styles.breatheAmber : styles.breatheStandby} ${extreme ? styles.suddenOiExtreme : ''}`
  const semanticColor = colorForTone(semanticTone)
  const state = hasEvidence ? text(data.state_label) : '—'

  return (
    <article key={eventKey} className={cardClass} data-sudden-oi-side={side}>
      <div className={styles.cardInnerMask} aria-hidden="true" />
      <div className={styles.tileHoverPool} aria-hidden="true" />
      {extreme ? <div className={styles.tileFlashAura} aria-hidden="true" /> : null}
      <div className={`${styles.hudCorner} ${styles.hudTl}`} />
      <div className={`${styles.hudCorner} ${styles.hudTr}`} />
      <div className={`${styles.hudCorner} ${styles.hudBl}`} />
      <div className={`${styles.hudCorner} ${styles.hudBr}`} />

      <div className={styles.suddenOiHeader}>
        <div className={styles.monoLabel} style={{ color: isCall ? 'var(--mint)' : 'var(--algory-red)' }}>
          SUDDEN OI · {side} · ATM ±2
        </div>
        <span className={`${styles.pill} ${statusClass(status)}`}>{status}</span>
      </div>

      <div className={styles.suddenOiHeroBlock}>
        <div>
          <span className={styles.monoLabel}>CURRENT 5M ACTIVITY</span>
          <strong className={styles.suddenOiHeroValue} style={{ color: semanticColor }}>{formatActivity(current)}</strong>
        </div>
        <div className={styles.suddenOiPercentileHero}>
          <strong style={{ color: semanticColor }}>{formatPercent(percentile)}</strong>
          <span>PERCENTILE</span>
        </div>
      </div>

      <div className={styles.suddenOiComparisonGrid}>
        <MiniMetric label="PREVIOUS 5M" value={formatActivity(previous)} />
        <MiniMetric label="NORMAL 5M" value={formatActivity(normal)} />
        <MiniMetric label="VS NORMAL" value={formatMultiple(vsNormal)} />
        <MiniMetric label="SESSION HIGH" value={formatSessionHigh(priorHigh, current, extreme)} tone={attention ? 'amber' : undefined} />
      </div>

      <div className={styles.intelligenceRail} aria-label={`${side} OI percentile`}>
        <div className={styles.intelligenceRailLabels}><span>PERCENTILE</span><strong>{formatPercent(percentile)}</strong></div>
        <div className={styles.teslaTrack}>
          <div className={styles.teslaFill} style={{ width: `${clamp(percentile)}%` }} />
        </div>
      </div>

      <div className={styles.suddenOiPositioning}>
        <div>
          <span className={styles.monoLabel}>POSITIONING</span>
          <strong className={styles.suddenOiState}>{state}</strong>
        </div>
        <div className={styles.suddenOiBreadth}>
          <span>BREADTH</span>
          <strong>{integer(breadth.count)}/{integer(breadth.total)}</strong>
        </div>
      </div>
      <div className={styles.intelligenceRail} aria-label={`${side} OI breadth`}>
        <div className={styles.teslaTrack}>
          <div className={styles.teslaFill} style={{ width: `${breadthWidth(breadth)}%` }} />
        </div>
      </div>
      {!warming && !unavailable ? (
        <div className={styles.suddenOiRead}>
          <span className={`${styles.pill} ${attention ? styles.pillAmber : styles.pillCyan}`}>{extreme ? '🔥 ' : ''}{text(data.read)}</span>
        </div>
      ) : null}

      <div className={styles.suddenOiDivider} />
      <div className={styles.monoLabel}>TOP STRIKE</div>
      <div className={`${styles.title} ${styles.suddenOiStrikeHero}`}>{formatStrike(number(top.strike), text(top.option_type))}</div>
      <div className={styles.suddenOiStrikeGrid}>
        <MiniMetric label="5M OI" value={formatActivity(number(top.activity_5m))} />
        <MiniMetric label="PERCENTILE" value={formatPercent(number(top.percentile))} />
      </div>
      <div className={styles.suddenOiStrikeState}>
        <span className={`${styles.pill} ${hasEvidence ? styles.pillCyan : styles.pillAmber}`}>{hasEvidence ? text(top.state) : '—'}</span>
      </div>
      <div
        key={`${text(top.security_id)}:${text(data.window_closed_at)}:${top.new_5m_high === true}:${top.squeeze === true}`}
        className={`${styles.horsepowerGrid} ${top.new_5m_high === true ? styles.horsepowerFlashRed : ''} ${top.squeeze === true ? styles.horsepowerFlashDouble : ''}`}
      >
        {top.new_5m_high === true ? <div className={styles.tileFlashAura} aria-hidden="true" /> : null}
        <div className={styles.suddenOiEventPills}>
          {top.squeeze === true ? <span className={`${styles.pill} ${styles.pillAmber}`}>⚡ {side} SHORT-COVERING SURGE</span> : null}
          {top.new_5m_high === true ? <span className={`${styles.pill} ${styles.pillAmber}`}>NEW 5M HIGH</span> : top.security_id ? <span className={`${styles.pill} ${styles.pillCyan}`}>NO STRIKE RECORD</span> : null}
        </div>
      </div>
      <SessionActivityTrack
        side={side}
        items={recent}
        sessionHigh={priorHigh}
        currentExtreme={extreme}
      />
      <div className={styles.suddenOiFoot}>WINDOW {formatClock(text(data.window_closed_at))} · {integer(breadth.valid)}/5 VALID</div>
    </article>
  )
}

function SessionActivityTrack({
  side,
  items,
  sessionHigh,
  currentExtreme,
}: {
  side: 'CALL' | 'PUT'
  items: JsonRecord[]
  sessionHigh: number | null
  currentExtreme: boolean
}) {
  const peak = Math.max(0, ...items.map((item) => number(item.activity) ?? 0))
  return (
    <div className={styles.suddenOiTrack} aria-label={`${side} session 5M activity track`}>
      <div className={styles.monoLabel}>SESSION 5M TRACK</div>
      {items.length ? items.map((item, index) => {
        const activity = number(item.activity)
        const latest = index === items.length - 1
        const record = activity !== null && (
          activity === sessionHigh || (latest && currentExtreme)
        )
        return (
          <div className={styles.suddenOiTrackRow} key={`${text(item.window_timestamp)}:${activity}`}>
            <span>{formatClock(text(item.window_timestamp))}</span>
            <div className={styles.teslaTrack}>
              <div
                className={record ? styles.teslaFill : styles.teslaFillMint}
                style={{ width: `${peak > 0 && activity !== null ? Math.max(4, (activity / peak) * 100) : 0}%` }}
              />
            </div>
            <strong>{formatActivity(activity)}</strong>
          </div>
        )
      }) : <div className={styles.suddenOiTrackEmpty}>—</div>}
    </div>
  )
}

type Tone = 'mint' | 'red' | 'cyan' | 'amber'

function MiniMetric({ label, value, tone }: { label: string; value: string; tone?: Tone }) {
  return <div className={styles.suddenOiMiniMetric}><span>{label}</span><strong style={{ color: colorForTone(tone) }}>{value}</strong></div>
}

function SharedBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className={styles.suddenOiSharedBlock}><div className={styles.intelligenceHeading}>{title}</div>{children}</div>
}

function Metric({ label, value, tone, strong = false }: { label: string; value: string; tone?: Tone; strong?: boolean }) {
  return <div className={`${styles.intelligenceRow} ${strong ? styles.intelligenceRowPrimary : ''}`}><span>{label}</span><strong style={{ color: colorForTone(tone) }}>{value}</strong></div>
}

function record(value: unknown): JsonRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {}
}

function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function text(value: unknown): string {
  return typeof value === 'string' && value.length > 0 ? value : '—'
}

function integer(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.trunc(value)) : '—'
}

function formatActivity(value: number | null): string {
  if (value === null) return '—'
  const absolute = Math.abs(value)
  if (absolute >= 100_000) return `${(value / 100_000).toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')}L`
  if (absolute >= 1_000) return `${(value / 1_000).toFixed(1).replace(/\.0$/, '')}K`
  return value.toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

function formatMultiple(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(2)}X`
}

function formatPercent(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(value % 1 === 0 ? 0 : 1)}%`
}

function formatPoints(value: number | null, suffix = ''): string {
  return value === null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1).replace(/\.0$/, '')} pts${suffix}`
}

function formatSigned(value: number | null): string {
  return value === null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')}`
}

function formatSessionHigh(prior: number | null, current: number | null, extreme: boolean): string {
  if (prior === null) return '—'
  return extreme && current !== null ? `${formatActivity(prior)} → ${formatActivity(current)} ↑` : formatActivity(prior)
}

function formatStrike(strike: number | null, side: string): string {
  return strike === null ? '—' : `${strike.toLocaleString('en-IN', { maximumFractionDigits: 0 })} ${side === 'CE' || side === 'PE' ? side : ''}`.trim()
}

function formatClock(value: string): string {
  if (value === '—') return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function clamp(value: number | null): number {
  return value === null ? 0 : Math.max(0, Math.min(100, value))
}

function breadthWidth(value: JsonRecord): number {
  const count = number(value.count)
  const total = number(value.total)
  return count === null || total === null || total <= 0 ? 0 : clamp((count / total) * 100)
}

function colorForTone(tone?: Tone): string {
  return tone === 'mint' ? 'var(--mint)' : tone === 'red' ? 'var(--algory-red)' : tone === 'cyan' ? 'var(--cyan)' : tone === 'amber' ? 'var(--amber)' : 'var(--text-white)'
}

function bookTone(direction: string): Tone {
  return direction === 'BUY' ? 'mint' : direction === 'SELL' ? 'red' : 'cyan'
}

function statusClass(status: string): string {
  return status === 'LIVE' ? styles.pillMint : status === 'WARMING' || status === 'PARTIAL_SESSION' ? styles.pillAmber : styles.pillCyan
}

function bookPressure(value: JsonRecord): string {
  const direction = text(value.direction)
  const pressure = number(value.pressure_x)
  if (direction === '—' || direction === 'UNAVAILABLE') return '—'
  return `NIFTY ${direction} BOOK PRESSURE${pressure === null ? '' : ` ${pressure.toFixed(1)}X`}`
}
