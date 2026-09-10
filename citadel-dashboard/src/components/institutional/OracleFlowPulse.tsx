'use client'

import { memo, useCallback, useLayoutEffect, useRef, useState, type CSSProperties, type SyntheticEvent } from 'react'
import { LiquidGlassRail, type RailAccent } from './OracleArgusPrime01C'
import styles from './OracleFlowPulse.module.css'

type JsonRecord = Record<string, unknown>
const record = (value: unknown): JsonRecord => value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {}
const text = (value: unknown, fallback = 'UNAVAILABLE'): string => typeof value === 'string' && value.trim() ? value : fallback
const finite = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null
const money = (value: unknown): string => finite(value) === null ? 'UNAVAILABLE' : `₹${finite(value)!.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const level = (value: unknown): string => finite(value) === null ? 'UNAVAILABLE' : finite(value)!.toLocaleString('en-IN', { maximumFractionDigits: 2 })
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const API_URL = process.env.NEXT_PUBLIC_CITADEL_API_URL ?? 'http://127.0.0.1:8000'
const clamp = (value: number): number => Math.max(4, Math.min(96, value))
const timeIST = (value: unknown): string => {
  if (typeof value !== 'string') return 'UNAVAILABLE'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'UNAVAILABLE' : parsed.toLocaleTimeString('en-IN', { hour12: false, timeZone: 'Asia/Kolkata' })
}

const ladderPosition = (value: number | null, values: number[]): string => {
  if (value === null || values.length < 2) return '50%'
  const low = Math.min(...values)
  const high = Math.max(...values)
  if (high <= low) return '50%'
  return `${8 + ((value - low) / (high - low)) * 84}%`
}

const railPosition = (family: 'value' | 'flow' | 'tape' | 'response', state: string): number | null => {
  const normalized = state.toUpperCase()
  if (family === 'value') return normalized === 'LOWER' ? 18 : normalized === 'HIGHER' ? 82 : normalized === 'FLAT' ? 50 : null
  if (family === 'flow') return normalized.startsWith('SELLING') ? 18 : normalized.startsWith('BUYING') ? 82 : normalized === 'MIXED' ? 50 : null
  if (family === 'tape') return normalized === 'QUIET' ? 18 : normalized === 'SLOWING' ? 36 : normalized.includes('FAST') ? 82 : null
  return normalized.includes('HOLDING AGAINST') ? 18 : normalized.includes('FALLING WITH') || normalized.includes('RISING WITH') ? 82 : normalized.includes('MIXED') || normalized.includes('NOT CLEAN') ? 50 : null
}

const valuePosition = (current: number | null, val: number | null, vah: number | null): number | null => {
  if (current === null || val === null || vah === null || vah <= val) return null
  return clamp(16 + ((current - val) / (vah - val)) * 68)
}

const flowPosition = (flow: JsonRecord): number | null => {
  const buy = finite(flow.buy_volume)
  const sell = finite(flow.sell_volume)
  if (buy === null || sell === null || buy + sell <= 0) return 50
  return clamp(8 + (buy / (buy + sell)) * 84)
}

const tone = (side: string | null, state: string): RailAccent => state.includes('INVALID') ? 'magenta' : side === 'CE' ? 'cyan' : side === 'PE' ? 'amber' : 'violet'
const actionLabel = (state: string): string => {
  if (state === 'NO TRADE') return 'NO TRADE'
  if (state.startsWith('EARLY BUY ')) return state
  if (state.startsWith('BUY ') && state.includes('CONFIRMED')) return state
  if (state.includes('PROTECT')) return 'PROTECT'
  if (state.includes('EXIT') || state.includes('INVALID')) return 'EXIT'
  if (state === 'HOLD' || state === 'RUNNER') return 'HOLD'
  return 'WATCH'
}

const meterEnds = {
  value: ['LOWER', 'FLAT', 'HIGHER'],
  flow: ['SELL', 'MIXED', 'BUY'],
  response: ['ABSORBED', 'MIXED', 'WORKING'],
  tape: ['QUIET', 'STEADY', 'FAST'],
} as const

export interface OracleFlowPulseProps { feed: unknown }

export const OracleFlowPulse = memo(function OracleFlowPulse({ feed }: OracleFlowPulseProps) {
  const data = record(record(feed).data)
  const pulse = record(data.flow_pulse)
  const futures = record(pulse.futures)
  const option = record(pulse.option)
  const profile = record(pulse.profile)
  const flow = record(pulse.flow)
  const levels = record(pulse.levels)
  const semantic = record(pulse.semantic)
  const liveHealth = record(pulse.live_health)
  const keyLevel = record(pulse.key_level)
  const nextLevel = record(pulse.next_level)
  const openRange = record(pulse.open_range)
  const frontendTransport = record(pulse.frontend_transport)
  const state = text(pulse.state, 'WATCH · DATA PARTIAL')
  const action = text(pulse.headline, actionLabel(state))
  const model = text(pulse.model, 'MODEL BUILDING')
  const side = text(pulse.side, text(option.option_type, '')) || null
  const accent = tone(side, state)
  const optionReady = option.status === 'AVAILABLE' && finite(option.ask) !== null
  const contract = finite(option.strike) === null || !side ? 'OPTION QUOTE WAIT' : `${level(option.strike)} ${side}`
  const valueState = text(semantic.market, 'BALANCED ↔')
  const flowState = text(pulse.flow_state)
  const pressureState = text(semantic.pressure, 'QUIET')
  const tapeState = text(semantic.speed, 'QUIET')
  const reaction = text(semantic.result, 'FLOW NOT CLEAN ENOUGH')
  const sourceTimestamp = text(pulse.source_timestamp)
  const quality = text(pulse.data_quality)
  const trigger = finite(futures.trigger)
  const invalidation = finite(futures.invalidation)
  const target1 = finite(futures.target_1)
  const target2 = finite(futures.target_2)
  const current = finite(futures.ltp)
  const ladderValues = [trigger, invalidation, target1, target2, current].filter((value): value is number => value !== null)
  const ladderReady = trigger !== null && invalidation !== null && current !== null
  const surfaceRef = useRef<HTMLElement>(null)
  useLayoutEffect(() => {
    const node = surfaceRef.current
    if (!node) return
    node.dataset.domCommitEpochMs = String(Date.now())
    node.dataset.browserReceiveEpochMs = String(frontendTransport.browser_receive_epoch_ms ?? '')
    window.dispatchEvent(new CustomEvent('citadel:oracle-dom-commit', { detail: {
      surface: 'FLOW_PULSE', action_revision: pulse.action_revision,
      semantic_revision: pulse.semantic_revision, headline: action,
      market: valueState, pressure: pressureState, result: reaction, speed: tapeState,
      futures_ltp: current, source_timestamp: sourceTimestamp,
      browser_receive_epoch_ms: frontendTransport.browser_receive_epoch_ms,
      dom_commit_epoch_ms: Date.now(),
    } }))
  }, [
    action, current, frontendTransport.browser_receive_epoch_ms, pressureState,
    pulse.action_revision, pulse.semantic_revision, reaction, sourceTimestamp,
    tapeState, valueState,
  ])
  const meterPositions = {
    value: valuePosition(current, finite(profile.val), finite(profile.vah)),
    flow: flowPosition(flow),
    tape: railPosition('tape', tapeState),
    response: railPosition('response', reaction),
  }
  const particleCount = Math.min(14, Math.max(0, Number(flow.buy_bursts ?? 0) + Number(flow.sell_bursts ?? 0) + Number(flow.unknown_bursts ?? 0)))

  return (
    <section ref={surfaceRef} className={styles.surface} data-oracle-flow-pulse data-state={state} data-side={side ?? 'NONE'} data-snapshot-id={text(pulse.snapshot_id, '')} data-action-revision={String(pulse.action_revision ?? '')} data-semantic-revision={String(pulse.semantic_revision ?? '')} data-live-health={text(liveHealth.status, 'DATA STALE')}>
      <header className={styles.header}>
        <div><span>ARGUS / VIDEO-METHOD FUTURES AUTHORITY</span><h2>ARGUS FLOW PULSE</h2></div>
        <div className={styles.truth} title={`Last packet age ${String(liveHealth.last_packet_age_ms ?? '—')} ms · semantic r${String(liveHealth.last_semantic_revision ?? '—')} · action r${String(liveHealth.last_action_revision ?? '—')}`}><b data-health={text(liveHealth.status)}>{text(liveHealth.status, quality)}</b><span>{sourceTimestamp}</span><em>ADVISORY · INFLUENCE ZERO</em></div>
      </header>
      <div className={styles.hero}>
        <div className={styles.command}><h3>{action}</h3><span>{model}</span><p>{text(pulse.story, 'NO VIDEO MODEL')}</p></div>
        <div className={styles.action}>
          <div><span>TRIGGER</span><b>{text(futures.trigger_text, trigger === null ? `FUT AT ${level(futures.ltp)}` : `FUT ${side === 'CE' ? 'ABOVE' : 'BELOW'} ${level(trigger)}`)}</b></div>
          <div><span>BUY</span><b>{optionReady ? `${contract} @ ${money(option.ask)}` : side ? 'FUT SETUP READY · OPTION QUOTE WAIT' : 'WAIT'}</b></div>
          <div><span>EXIT IF</span><b>{invalidation === null ? '—' : `FUT ${side === 'CE' ? 'BELOW' : 'ABOVE'} ${level(invalidation)}`}</b></div>
          <div><span>TARGET 1</span><b>{target1 === null ? '—' : level(target1)}</b></div>
          <div><span>TARGET 2</span><b>{target2 === null ? '—' : level(target2)}</b></div>
          <div><span>HOLD</span><b>{side ? `WHILE MARKET STAYS ${side === 'PE' ? 'LOWER' : 'HIGHER'}` : '—'}</b></div>
        </div>
      </div>
      <div className={styles.priceLadder} data-levels-locked={ladderReady ? 'true' : 'false'}>
        <div className={styles.ladderHead}><span>FUTURES STRUCTURAL LADDER</span><b>{ladderReady ? `LIVE FUT ${level(current)}` : 'NO LEVELS LOCKED'}</b></div>
        <div className={styles.ladderCanvas}>
          <i className={styles.ladderTrack} />
          {invalidation !== null && <i className={styles.invalidMarker} style={{ left: ladderPosition(invalidation, ladderValues) }}><b>STOP</b><span>{level(invalidation)}</span></i>}
          {trigger !== null && <i className={`${styles.ladderMarker} ${styles.entryMarker}`} style={{ left: ladderPosition(trigger, ladderValues) }}><b>ENTRY</b><span>{level(trigger)}</span></i>}
          {target1 !== null && <i className={`${styles.ladderMarker} ${styles.targetMarker}`} style={{ left: ladderPosition(target1, ladderValues) }}><b>T1</b><span>{level(target1)}</span></i>}
          {target2 !== null && <i className={`${styles.ladderMarker} ${styles.targetMarker} ${styles.targetTwo}`} style={{ left: ladderPosition(target2, ladderValues) }}><b>T2</b><span>{level(target2)}</span></i>}
          {current !== null && <i className={styles.liveMarker} style={{ left: ladderPosition(current, ladderValues) }}><b>NOW</b><span>{level(current)}</span></i>}
          {particleCount > 0 && <div className={styles.activityParticles} data-flow={flowState} aria-label={`${particleCount} genuine recent execution bursts`}>
            {Array.from({ length: particleCount }, (_, index) => <i key={index} style={{ '--particle-delay': `${index * -.31}s`, '--particle-duration': `${1.8 + (index % 3) * .35}s` } as CSSProperties} />)}
          </div>}
        </div>
        <div className={styles.optionQuote}><span>OPTION EXECUTION</span><b>{optionReady ? `${contract} · BID ${money(option.bid)} / ASK ${money(option.ask)}` : 'OPTION QUOTE UNAVAILABLE'}</b></div>
      </div>
      <div className={styles.rails}>
        {([
          ['MARKET', 'value', valueState, valueState.includes('HIGHER') ? 'cyan' : valueState.includes('LOWER') ? 'amber' : 'violet'],
          ['PRESSURE', 'flow', pressureState, pressureState.startsWith('BUYERS') ? 'cyan' : pressureState.startsWith('SELLERS') ? 'amber' : 'violet'],
          ['RESULT', 'response', reaction, accent],
          ['SPEED', 'tape', tapeState, accent],
        ] as const).map(([labelName, family, value, railAccent]) => (
          <div className={styles.rail} key={family} data-meter-revision={family === 'value' ? String(profile.revision ?? '') : String(pulse.revision ?? '')}><div><span>{labelName}</span><b>{value}</b></div><LiquidGlassRail position={meterPositions[family]} state={finite(pulse.revision) === null ? 'UNAVAILABLE' : 'LIVE'} accent={railAccent} bipolar ariaLabel={`${labelName} ${value}`} /><small><i>{meterEnds[family][0]}</i><i>{meterEnds[family][1]}</i><i>{meterEnds[family][2]}</i></small></div>
        ))}
      </div>
      <div className={styles.context}>
        <div><span>KEY LEVEL</span><b>{text(keyLevel.label, text(pulse.area, 'LEVELS BUILDING'))}</b><small>{text(keyLevel.state, 'FAR')}</small></div>
        <div><span>NEXT LEVEL</span><b>{text(nextLevel.name, 'NONE NEARBY')} {finite(nextLevel.price) === null ? '' : level(nextLevel.price)}</b><small>{finite(nextLevel.distance_points) === null ? text(nextLevel.state, 'FAR') : `${level(nextLevel.distance_points)} PTS AWAY · ${text(nextLevel.state, 'FAR')}`}</small></div>
        <div><span>WHAT HAPPENED</span><b>{text(pulse.what_happened, 'WATCHING MARKET-GENERATED LEVELS')}</b></div>
        <div><span>OPEN RANGE</span><b>{text(openRange.label, levels.opening_range_available === true ? `OPEN RANGE ${level(levels['OR LOW'])}–${level(levels['OR HIGH'])} · SET` : 'OPEN RANGE BUILDING')}</b></div>
        <div><span>MARKET PROFILE</span><b>VAL {level(profile.val)} · POC {level(profile.poc)} · VAH {level(profile.vah)}</b><small>SELL {level(flow.sell_volume)} · UNKNOWN {level(flow.unknown_volume)} · BUY {level(flow.buy_volume)}</small></div>
      </div>
      <footer><span>FUTURES DECIDES · OPTION EXECUTES AT ASK / MARKS AT BID</span><span>NO PRIME / GAMMA / QUALITY SCORE AUTHORITY</span></footer>
    </section>
  )
})

export const FlowPulsePaperLedger = memo(function FlowPulsePaperLedger({ feed }: OracleFlowPulseProps) {
  const data = record(record(feed).data)
  const pulse = record(data.flow_pulse)
  const episodes = list(pulse.paper_episodes).map(record).sort((left, right) => {
    const leftOpen = !['EXITED', 'INVALIDATED'].includes(text(left.state))
    const rightOpen = !['EXITED', 'INVALIDATED'].includes(text(right.state))
    return Number(rightOpen) - Number(leftOpen) || text(right.start_time).localeCompare(text(left.start_time))
  })
  const entryCount = episodes.reduce((count, episode) => count + list(episode.entry_legs).length, 0)
  const optionPnl = episodes.reduce((sum, episode) => sum + list(episode.entry_legs).map(record).reduce((legSum, leg) => legSum + (finite(leg.pnl_option_points) ?? 0), 0), 0)
  const [history, setHistory] = useState<JsonRecord | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const fetchHistory = useCallback(async (session?: string) => {
    setHistoryError(null)
    try {
      const query = session ? `?session=${encodeURIComponent(session)}` : ''
      const response = await fetch(`${API_URL}/v1/oracle/flow-pulse/paper-history${query}`, { cache: 'no-store' })
      if (!response.ok) throw new Error(`HTTP_${response.status}`)
      setHistory(record(await response.json()))
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : 'HISTORY_UNAVAILABLE')
    }
  }, [])
  const loadHistory = useCallback(async (event: SyntheticEvent<HTMLDetailsElement>) => {
    if (!event.currentTarget.open || history !== null || historyError !== null) return
    await fetchHistory()
  }, [fetchHistory, history, historyError])
  return (
    <details className={styles.paperLedger} data-flow-pulse-paper-ledger onToggle={(event) => void loadHistory(event)}>
      <summary><span>FLOW PULSE LAB</span><b>TODAY · {episodes.length} EPISODE{episodes.length === 1 ? '' : 'S'} · {entryCount} ENTRIES · {level(optionPnl)} PTS P&amp;L</b></summary>
      <div className={styles.paperLedgerBody}>
        <header><div><span>IMMUTABLE ADVISORY PAPER EVIDENCE</span><h3>TODAY</h3></div><b>NO BROKER · INFLUENCE ZERO</b></header>
        {episodes.length === 0 ? <p>NO ACTIONABLE FLOW PULSE PAPER ENTRY RECORDED</p> : <div className={styles.paperRows}>
          {episodes.map((episode) => {
            const legs = list(episode.entry_legs).map(record)
            const primary = legs[0] ?? {}
            return <article key={text(episode.episode_id)}>
              <div><span>{text(episode.model).replaceAll('_', ' ')} · {text(episode.direction)}</span><b>{timeIST(primary.entry_time)} · {level(primary.strike)} {text(episode.direction)} @ {money(primary.entry_ask)}</b>{legs.slice(1).map((leg) => <small key={text(leg.trade_id)}>+ {text(leg.entry_type)} {level(leg.strike)} {text(leg.direction)} @ {money(leg.entry_ask)}</small>)}</div>
              <dl><div><dt>ASK / LIVE BID–ASK</dt><dd>{money(primary.entry_ask)} / {money(primary.live_bid)}–{money(primary.live_ask)}</dd></div><div><dt>CURRENT FUT / EXIT IF</dt><dd>{level(episode.futures_current_price)} / {level(episode.futures_invalidation)}</dd></div><div><dt>T1 / T2</dt><dd>{level(episode.futures_target_1)} / {level(episode.futures_target_2)}</dd></div><div><dt>P&amp;L / MFE / MAE</dt><dd>{level(primary.pnl_option_points)} / {level(primary.mfe)} / {level(primary.mae)} pts</dd></div><div><dt>RR / REALIZED R</dt><dd>{level(primary.structural_rr)} / {level(primary.realized_r)}</dd></div><div><dt>ACTUAL EXIT / BID</dt><dd>{timeIST(primary.exit_time)} / {money(primary.exit_bid)}</dd></div><div><dt>STATUS</dt><dd>{text(episode.state)}</dd></div></dl>
            </article>
          })}
        </div>}
        <section className={styles.history}><h3>HISTORY</h3>{historyError ? <p>{historyError}</p> : history === null ? <p>LOADING INDEXED SESSIONS…</p> : <><p>{list(history.sessions).length} STORED SESSION{list(history.sessions).length === 1 ? '' : 'S'} · {list(history.entry_legs).length} LATEST LEG RECORDS</p><select aria-label="Flow Pulse paper history session" value={text(history.selected_session, '')} onChange={(event) => void fetchHistory(event.target.value)}>{list(history.sessions).map((session) => <option key={String(session)} value={String(session)}>{String(session)}</option>)}</select></>}</section>
      </div>
    </details>
  )
})
