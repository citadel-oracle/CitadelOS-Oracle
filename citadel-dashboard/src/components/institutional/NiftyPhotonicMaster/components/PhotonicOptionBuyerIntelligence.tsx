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
const qty = (value: unknown): string => number(value) === null ? '—' : Math.round(number(value)!).toLocaleString('en-IN')
const level = (value: unknown): string => {
  const data = asData(value)
  const price = number(data.price)
  const quantity = number(data.quantity)
  if (price === null || quantity === null) return '—'
  const orders = number(data.orders)
  return `${money(price)} · ${qty(quantity)}${orders === null ? '' : ` · ${qty(orders)} ${orders === 1 ? 'order' : 'orders'}`}`
}

function Row({ label, value, tone, primary = false, fieldId }: { label: string, value: string, tone?: string, primary?: boolean, fieldId?: string }) {
  return <div className={`${styles.intelligenceRow} ${primary ? styles.intelligenceRowPrimary : ''}`}><span>{label}</span><strong data-citadel-field={fieldId} style={{ color: tone ?? 'var(--text-white)' }}>{value}</strong></div>
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
  const pressure = asData(data.market_pressure)
  const book = asData(data.book)
  const comparison = data.comparison
  const holding = number(data.premium_holding)
  const fair = number(data.fair_price)
  const ask = number(data.ask)
  const bid = number(data.bid)
  const spread = number(data.spread)
  const fairAdvantage = number(data.fair_advantage)
  const expected = number(data.time_loss_expected)
  const actual = number(data.actual_change)
  const timeLost = number(data.time_lost_today)
  const timeLeft = number(data.time_value_left)
  const buyShare = number(pressure.book_buy_share_pct)
  const sellShare = number(pressure.book_sell_share_pct)
  const hasPressure = [pressure.total_buy_quantity, pressure.total_sell_quantity, pressure.last_trade_quantity, pressure.average_trade_price, buyShare, sellShare].some((value) => number(value) !== null)
  const hasBook = [book.best_bid, book.best_ask, book.biggest_buy_level, book.biggest_sell_level, book.five_level_buy_quantity, book.five_level_sell_quantity].some((value) => typeof value === 'object' && value !== null || number(value) !== null)
  return <section className={`${styles.card} ${styles.optionBuyerIntelligence}`} aria-label={`${side} option buyer intelligence`}>
    <div className={styles.monoLabel}>OPTION BUYER INTELLIGENCE</div>
    <div className={styles.intelligenceBlock}>
      <div className={styles.intelligenceHeading}>FAIR PRICE <em>MODEL-DERIVED · RESEARCH</em></div>
      <Row label="FAIR PRICE" value={money(fair)} primary={fair !== null}  fieldId={`obi.${side.toLowerCase()}.fair_price`} />
      {comparison === 'BELOW_FAIR' ? <Row label="BELOW FAIR" value={pct(data.below_fair_pct)} tone="var(--mint)"  fieldId={`obi.${side.toLowerCase()}.below_fair_pct`} /> : comparison === 'INFLATED' ? <><Row label="EXTRA PAYING" value={money(data.extra_paying, true)} tone="var(--algory-red)"  fieldId={`obi.${side.toLowerCase()}.extra_paying`} /><Row label="INFLATED" value={pct(data.inflated_pct)} tone="var(--algory-red)"  fieldId={`obi.${side.toLowerCase()}.inflated_pct`} /></> : null}
      {quality.valid === true && fair !== null && ask !== null && <TeslaRail left={`FAIR ${money(fair)}`} leftValue={fair} right={`ASK ${money(ask)}`} rightValue={ask} tone={comparison === 'INFLATED' ? 'red' : 'mint'} />}
    </div>
    <div className={styles.intelligenceBlock}>
      <div className={styles.intelligenceHeading}>DECAY</div>
      <Row label="TIME LOST TODAY" value={money(timeLost, true)}  fieldId={`obi.${side.toLowerCase()}.time_lost_today`} />
      <Row label="TIME VALUE LEFT" value={money(timeLeft)}  fieldId={`obi.${side.toLowerCase()}.time_value_left`} />
      {quality.valid === true && timeLost !== null && timeLeft !== null && <TeslaRail left={`LOST ${money(timeLost, true)}`} leftValue={timeLost} right={`LEFT ${money(timeLeft)}`} rightValue={timeLeft} tone="cyan" />}
      <Row label="TIME LOSS EXPECTED" value={money(expected, true)}  fieldId={`obi.${side.toLowerCase()}.time_loss_expected`} />
      <Row label="ACTUAL CHANGE" value={money(actual, true)}  fieldId={`obi.${side.toLowerCase()}.actual_change`} />
      <Row label="PREMIUM HOLDING" value={holding === null ? '—' : `${money(Math.abs(holding))} ${holding >= 0 ? 'STRONGER' : 'WEAKER'}`} primary={holding !== null} tone={holding === null ? undefined : holding >= 0 ? 'var(--mint)' : 'var(--algory-red)'} />
      {quality.valid === true && expected !== null && actual !== null && holding !== null && <TeslaRail left={`EXPECTED ${money(expected, true)}`} leftValue={expected} right={`ACTUAL ${money(actual, true)}`} rightValue={actual} tone={holding >= 0 ? 'mint' : 'red'} />}
    </div>
    {hasPressure ? <div className={styles.intelligenceBlock}>
      <div className={styles.intelligenceHeading}>LIVE MARKET PRESSURE</div>
      <Row label="TOTAL BUY QTY" value={qty(pressure.total_buy_quantity)}  fieldId={`obi.${side.toLowerCase()}.total_buy_quantity`} />
      <Row label="TOTAL SELL QTY" value={qty(pressure.total_sell_quantity)}  fieldId={`obi.${side.toLowerCase()}.total_sell_quantity`} />
      {buyShare !== null && sellShare !== null ? <Row label="5L BOOK SHARE" value={`BUY ${buyShare.toFixed(0)}% · SELL ${sellShare.toFixed(0)}%`}  /> : null}
      <Row label="LAST TRADE QTY" value={qty(pressure.last_trade_quantity)}  fieldId={`obi.${side.toLowerCase()}.last_trade_quantity`} />
      <Row label="AVG TRADE PRICE" value={money(pressure.average_trade_price)}  fieldId={`obi.${side.toLowerCase()}.average_trade_price`} />
    </div> : null}
    <div className={styles.intelligenceBlock}>
      <div className={styles.intelligenceHeading}>ENTRY EDGE</div>
      <Row label="BUY @ ASK" value={money(ask)}  fieldId={`obi.${side.toLowerCase()}.ask`} /><Row label="BID" value={money(bid)}  fieldId={`obi.${side.toLowerCase()}.bid`} />
      <Row label="SPREAD" value={money(spread)}  fieldId={`obi.${side.toLowerCase()}.spread`} /><Row label="FAIR ADVANTAGE" value={money(fairAdvantage, true)} tone={fairAdvantage === null ? undefined : fairAdvantage >= 0 ? 'var(--mint)' : 'var(--algory-red)'} />
    </div>
    {hasBook ? <div className={styles.intelligenceBlock}>
      <div className={styles.intelligenceHeading}>BOOK / DEPTH</div>
      <Row label="BEST BID" value={level(book.best_bid)}  fieldId={`obi.${side.toLowerCase()}.best_bid`} />
      <Row label="BEST ASK" value={level(book.best_ask)}  fieldId={`obi.${side.toLowerCase()}.best_ask`} />
      <Row label="BIGGEST BUY LEVEL" value={level(book.biggest_buy_level)}  fieldId={`obi.${side.toLowerCase()}.biggest_buy_level`} />
      <Row label="BIGGEST SELL LEVEL" value={level(book.biggest_sell_level)}  fieldId={`obi.${side.toLowerCase()}.biggest_sell_level`} />
      <Row label="5L BUY QTY" value={qty(book.five_level_buy_quantity)}  fieldId={`obi.${side.toLowerCase()}.five_level_buy_quantity`} />
      <Row label="5L SELL QTY" value={qty(book.five_level_sell_quantity)}  fieldId={`obi.${side.toLowerCase()}.five_level_sell_quantity`} />
    </div> : null}
    {quality.valid !== true && <div className={styles.intelligenceFoot}>MODEL INPUT INVALID · —</div>}
  </section>
})
