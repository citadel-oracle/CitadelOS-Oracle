'use client'

import React, { memo } from 'react'
import styles from '../NiftyPhotonicMaster.module.css'

type Data = Readonly<Record<string, unknown>>
const asData = (value: unknown): Data => value && typeof value === 'object' ? value as Data : {}
const number = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null
const money = (value: unknown, signed = false): string => {
  const parsed = number(value)
  if (parsed === null) return '—'
  return `${signed && parsed > 0 ? '+' : ''}₹${parsed.toFixed(2)}`
}
const pct = (value: unknown): string => number(value) === null ? '—' : `${number(value)!.toFixed(2)}%`

function Row({ label, value, tone, primary = false }: { label: string, value: string, tone?: string, primary?: boolean }) {
  return <div className={`${styles.intelligenceRow} ${primary ? styles.intelligenceRowPrimary : ''}`}><span>{label}</span><strong style={{ color: tone ?? 'var(--text-white)' }}>{value}</strong></div>
}

function TeslaRail({ left, leftValue, right, rightValue, tone = 'mint' }: { left: string, leftValue: number, right: string, rightValue: number, tone?: 'mint' | 'red' | 'cyan' }) {
  const total = Math.abs(leftValue) + Math.abs(rightValue)
  const leftPct = total > 0 ? Math.max(3, Math.min(97, (Math.abs(leftValue) / total) * 100)) : 50
  return <div className={styles.intelligenceRail} aria-label={`${left} versus ${right}`} data-obi-rail>
    <div className={styles.intelligenceRailLabels}><span>{left}</span><span>{right}</span></div>
    <div className={styles.teslaTrack}>
      <div className={`${styles.teslaFill} ${tone === 'mint' ? styles.teslaFillMint : tone === 'red' ? styles.teslaFillRed : ''}`} style={{ width: `${leftPct}%` }} />
      <div className={`${styles.teslaHead} ${tone === 'red' ? styles.headRed : ''}`} style={{ left: `calc(${leftPct}% - 8px)` }} />
    </div>
  </div>
}

export interface PhotonicOptionBuyerIntelligenceProps { intelligence?: Data | null; side: 'CE' | 'PE' }

export const PhotonicOptionBuyerIntelligence = memo(function PhotonicOptionBuyerIntelligence({ intelligence, side }: PhotonicOptionBuyerIntelligenceProps) {
  const root = asData(intelligence)
  const data = asData(root[side])
  const quality = asData(data.quality)
  const flow = asData(data.flow)
  const book = asData(data.book)
  const comparison = data.comparison
  const holding = number(data.premium_holding)
  const fair = number(data.fair_price)
  const ask = number(data.ask)
  const bid = number(data.bid)
  const expected = number(data.time_loss_expected)
  const actual = number(data.actual_change)
  const timeLost = number(data.time_lost_today)
  const timeLeft = number(data.time_value_left)
  const edgeAfterCosts = number(data.edge_after_costs)
  const entryExitCost = number(data.entry_exit_cost)
  const hasFlow = number(flow.buying_volume) !== null && number(flow.selling_volume) !== null && number(flow.imbalance) !== null
  return <section className={`${styles.card} ${styles.optionBuyerIntelligence}`} aria-label={`${side} option buyer intelligence`}>
    <div className={styles.monoLabel}>OPTION BUYER INTELLIGENCE</div>
    <div className={styles.intelligenceBlock}>
      <div className={styles.intelligenceHeading}>FAIR PRICE <em>MODEL-DERIVED · RESEARCH</em></div>
      <Row label="FAIR PRICE" value={money(fair)} primary={fair !== null} />
      {comparison === 'BELOW_FAIR' ? <Row label="BELOW FAIR" value={pct(data.below_fair_pct)} tone="var(--mint)" /> : comparison === 'INFLATED' ? <><Row label="EXTRA PAYING" value={money(data.extra_paying, true)} tone="var(--algory-red)" /><Row label="INFLATED" value={pct(data.inflated_pct)} tone="var(--algory-red)" /></> : <Row label="FAIR STATUS" value="—" />}
      {fair !== null && ask !== null && <TeslaRail left={`FAIR ${money(fair)}`} leftValue={fair} right={`ASK ${money(ask)}`} rightValue={ask} tone={comparison === 'INFLATED' ? 'red' : 'mint'} />}
    </div>
    <div className={styles.intelligenceBlock}>
      <div className={styles.intelligenceHeading}>DECAY</div>
      <Row label="TIME LOST TODAY" value={money(timeLost, true)} />
      <Row label="TIME VALUE LEFT" value={money(timeLeft)} />
      {timeLost !== null && timeLeft !== null && <TeslaRail left={`LOST ${money(timeLost, true)}`} leftValue={timeLost} right={`LEFT ${money(timeLeft)}`} rightValue={timeLeft} tone="cyan" />}
      <Row label="TIME LOSS EXPECTED" value={money(expected, true)} />
      <Row label="ACTUAL CHANGE" value={money(actual, true)} />
      <Row label="PREMIUM HOLDING" value={holding === null ? '—' : `${money(Math.abs(holding))} ${holding >= 0 ? 'STRONGER' : 'WEAKER'}`} primary={holding !== null} tone={holding === null ? undefined : holding >= 0 ? 'var(--mint)' : 'var(--algory-red)'} />
      {expected !== null && actual !== null && holding !== null && <TeslaRail left={`EXPECTED ${money(expected, true)}`} leftValue={expected} right={`ACTUAL ${money(actual, true)}`} rightValue={actual} tone={holding >= 0 ? 'mint' : 'red'} />}
    </div>
    <div className={styles.intelligenceBlock}>
      <div className={styles.intelligenceHeading}>FLOW DYNAMICS</div>
      <Row label="BUYING VOL" value={money(flow.buying_volume)} /><Row label="SELLING VOL" value={money(flow.selling_volume)} />
      <Row label="NET FLOW" value={money(flow.net_flow, true)} /><Row label="IMBALANCE" value={pct(flow.imbalance)} /><Row label="ACTIVITY × NORMAL" value={String(flow.activity_normal ?? '—')} />
      {!hasFlow && <div className={styles.intelligenceUnavailable}>FLOW TAPE UNAVAILABLE · —</div>}
    </div>
    <div className={styles.intelligenceBlock}>
      <div className={styles.intelligenceHeading}>ENTRY EDGE</div>
      <Row label="BUY @ ASK" value={money(ask)} /><Row label="BID" value={money(bid)} />
      <Row label="SPREAD" value={ask !== null && bid !== null ? money(ask - bid) : '—'} /><Row label="ENTRY + EXIT COST" value={money(entryExitCost)} /><Row label="MY BUY PRICE" value="—" /><Row label="EDGE AFTER COSTS" value={money(edgeAfterCosts, true)} />
      {fair !== null && ask !== null && bid !== null && entryExitCost !== null && edgeAfterCosts !== null && <TeslaRail left={`ASK ${money(ask)}`} leftValue={ask} right={`FAIR ${money(fair)}`} rightValue={fair} tone={edgeAfterCosts >= 0 ? 'mint' : 'red'} />}
    </div>
    <div className={styles.intelligenceBlock}>
      <div className={styles.intelligenceHeading}>BOOK / VOLUME</div>
      <Row label="BIGGEST BUY ORDERS" value={String(book.biggest_buy_orders ?? '—')} /><Row label="BIGGEST SELL ORDERS" value={String(book.biggest_sell_orders ?? '—')} />
      <Row label="MOST TRADED PRICE" value={money(book.most_traded_price)} /><Row label="CURRENT vs MOST TRADED" value={String(book.current_vs_most_traded ?? '—')} /><Row label="MY BUY PRICE" value={money(book.my_buy_price)} />
    </div>
    {quality.valid !== true && <div className={styles.intelligenceFoot}>MODEL INPUT INVALID · —</div>}
  </section>
})
