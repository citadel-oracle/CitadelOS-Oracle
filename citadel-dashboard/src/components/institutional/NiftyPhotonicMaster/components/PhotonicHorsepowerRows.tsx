'use client'

import React, { memo, useEffect, useRef, useState } from 'react'
import type { OracleHorsepowerProjection } from '@/dashboard/store/oracleStore'
import styles from '../NiftyPhotonicMaster.module.css'

const laneText = (value: string | undefined): string => ({
  SUPPORT_GONE: 'SUPPORT GONE · 1X WEAK',
  DOUBLE_SUPPORT_GONE: 'DOUBLE SUPPORT GONE · 2X WEAK',
  SUPPORT_BACK: 'SUPPORT BACK · HORSEPOWER RETURNING ↑',
  RESISTANCE_OUT: 'RESISTANCE OUT · 1X POWER',
  DOUBLE_RESISTANCE_OUT: 'DOUBLE RESISTANCE OUT · 2X HORSEPOWER',
  BREAKOUT_LOST: 'BREAKOUT LOST · HORSEPOWER LOST ↓',
  NEUTRAL: 'NEUTRAL',
}[value ?? ''] ?? 'NEUTRAL')

const eventTone = (value: string): 'positive' | 'negative' | 'neutral' => {
  if (value.includes('SUPPORT_GONE') || value.includes('BREAKOUT_LOST') || value.includes('WEAK')) return 'negative'
  if (value.includes('RESISTANCE_OUT') || value.includes('SUPPORT_BACK') || value.includes('HORSEPOWER')) return 'positive'
  return 'neutral'
}

export const PhotonicHorsepowerRows = memo(function PhotonicHorsepowerRows({
  horsepower,
  label,
}: {
  horsepower?: OracleHorsepowerProjection | null
  label: string
}) {
  const seen = useRef<Set<string> | null>(null)
  const [flash, setFlash] = useState<'positive' | 'negative' | null>(null)
  const [double, setDouble] = useState(false)

  useEffect(() => {
    const events = horsepower?.events ?? []
    if (seen.current === null) {
      seen.current = new Set(events.map((event) => event.eventId))
      return
    }
    const fresh = events.filter((event) => !seen.current?.has(event.eventId))
    for (const event of fresh) seen.current.add(event.eventId)
    const latest = [...fresh].reverse().find((event) => event.notificationEligible)
    if (!latest) return
    setFlash(eventTone(latest.event) === 'negative' ? 'negative' : 'positive')
    setDouble((horsepower?.combined ?? '').includes('2X') || latest.event.includes('DOUBLE'))
  }, [horsepower])

  const one = horsepower?.pulse1m ?? 'NEUTRAL'
  const three = laneText(horsepower?.timeframes['3m']?.status)
  const five = laneText(horsepower?.timeframes['5m']?.status)
  const combined = horsepower?.combined ?? 'IDLE'
  const combinedTone = eventTone(combined)
  const color = combinedTone === 'negative' ? 'var(--algory-red)'
    : combinedTone === 'positive' ? 'var(--mint)' : 'var(--text-lo)'
  const flashClass = flash === 'positive' ? styles.horsepowerFlashGreen
    : flash === 'negative' ? styles.horsepowerFlashRed : ''
  const allEvents = horsepower?.events ?? []
  const latestEvent = allEvents.length > 0 ? allEvents[allEvents.length - 1] : null

  const tf1 = horsepower?.timeframes?.['1m']
  const tf3 = horsepower?.timeframes?.['3m']
  const tf5 = horsepower?.timeframes?.['5m']

  return <div
    className={`${styles.optionVobTruthGrid} ${styles.horsepowerGrid} ${flashClass} ${double ? styles.horsepowerFlashDouble : ''}`}
    aria-label={`${label} VOB horsepower`}
    data-vob-horsepower={label}
    onAnimationEnd={() => { setFlash(null); setDouble(false) }}
  >
    <div className={styles.tileFlashAura} aria-hidden="true" />
    <div>
      <span>1M PULSE {tf1 ? `(${tf1.supportBroken}S/${tf1.resistanceBroken}R)` : ''}</span>
      <strong>{one}</strong>
    </div>
    <div>
      <span>3M POWER {tf3 ? `(${tf3.supportBroken}S/${tf3.resistanceBroken}R)` : ''}</span>
      <strong>{three}</strong>
    </div>
    <div>
      <span>5M POWER {tf5 ? `(${tf5.supportBroken}S/${tf5.resistanceBroken}R)` : ''}</span>
      <strong>{five}</strong>
    </div>
    <div>
      <span>SESSION STRUCTURE</span>
      <strong style={{ color }}>{combined}</strong>
    </div>
    {latestEvent ? (
      <div style={{ gridColumn: '1 / -1', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '2px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '7.5px', color: 'var(--text-lo)', fontFamily: 'var(--font-mono)' }}>
          LATEST STRUCTURAL EVENT
        </span>
        <strong style={{ fontSize: '8px', fontFamily: 'var(--font-mono)', color: eventTone(latestEvent.event) === 'positive' ? 'var(--mint)' : eventTone(latestEvent.event) === 'negative' ? 'var(--algory-red)' : 'var(--text-lo)' }}>
          {latestEvent.event.replace(/_/g, ' ')} · {latestEvent.timeframe} {latestEvent.confirmedCandle ? `· ${latestEvent.confirmedCandle.slice(-8)}` : ''}
        </strong>
      </div>
    ) : null}
  </div>
})
