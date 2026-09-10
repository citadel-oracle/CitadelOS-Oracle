/**
 * CITADEL ORACLE — FLOW MAP V1 PRIMITIVES
 * 
 * Exact Bookmap-style Liquidity Heatmap and Microstructure Flow Map Renderer:
 * 1. BubblesPrimitive:
 *    - Exact OrderFlowMap 2-pass bubble philosophy
 *    - Pass 1: Subtle hollow circles (16% fill, 1px thin outline) for small trades (qty < largeQty)
 *    - Pass 2: Luminous glowing halos (r * 1.6, 35%->0% radial gradient) and core gradients for large trades (qty >= largeQty)
 *    - Event-local canonical absorption rings (amber)
 *    - Native neutral styling for UNKNOWN classification (slate)
 * 2. HeatmapPrimitive:
 *    - Horizontal screen-column binning & resampling: Eliminates 100% of additive overdraw
 *    - Real 5-level resting depth averaged per visual column
 *    - Dynamic row height derived from chart price coordinate spacing (thin 2-4px bands)
 *    - Bookmap bi-color colormap (Cyan/Teal Bids, Dark Red/Orange Asks)
 * 
 * Copyright (c) 2026 CitadelOS / OrderFlowMap Contributors.
 */

import type { BitmapCoordinatesRenderingScope, CanvasRenderingTarget2D } from 'fancy-canvas'
import type {
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'

export interface VisualFlowEvent {
  event_id: string
  time: number
  price: number
  observed_qty: number
  classified_buy_qty: number
  classified_sell_qty: number
  unclassified_qty: number
  side: 'BUY' | 'SELL' | 'UNKNOWN'
  classification_method?: string
  signer_confidence?: number
  absorption_state?: string
  is_absorbed?: boolean
  buyer_absorption?: number
  seller_absorption?: number
  is_failed_aggression?: boolean
  failed_aggression?: number
  cvd?: number
}

export interface DepthSnapshot {
  time: number
  bids: Array<{ p: number; q: number; o: number }>
  asks: Array<{ p: number; q: number; o: number }>
}

export interface FlowMapOptions {
  showBubbles: boolean
  showHeatmap: boolean
  bubMin: number
  bubMax: number
  largeQty: number
  minTrade: number
  hollowSmall: boolean
  bubScale: 'sqrt' | 'log' | 'linear'
  hmIntensity: number
  hmGamma: number
  hmMin: number
  colormap: 'bookmap' | 'inferno' | 'mono'
}

export const DEFAULT_FLOW_MAP_OPTIONS: FlowMapOptions = {
  showBubbles: true,
  showHeatmap: true,
  bubMin: 2,
  bubMax: 26,
  largeQty: 500, // NIFTY FUT: 500 qty (~7.7 lots)
  minTrade: 0,
  hollowSmall: true,
  bubScale: 'sqrt',
  hmIntensity: 1.20,
  hmGamma: 0.50,
  hmMin: 0,
  colormap: 'bookmap',
}

const TICK = 0.05
const roundTick = (p: number) => Math.round(p / TICK) * TICK
const clamp = (x: number, a: number, b: number) => (x < a ? a : x > b ? b : x)
const mix = (a: number[], b: number[], t: number) => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
]
const rgba = (c: number[], a: number) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`

function rampStops(stops: number[][], t: number): number[] {
  const clampedT = clamp(t, 0, 1)
  const n = stops.length - 1
  const i = Math.floor(clampedT * n)
  if (i >= n) return stops[n]
  return mix(stops[i], stops[i + 1], clampedT * n - i)
}

const CMAPS = {
  bookmap: {
    bid: (t: number) => rampStops([[6, 10, 16], [6, 55, 65], [20, 140, 135], [125, 225, 210], [235, 255, 250]], t),
    ask: (t: number) => rampStops([[6, 10, 16], [60, 18, 18], [170, 40, 40], [245, 140, 90], [255, 235, 200]], t),
  },
  mono: {
    bid: (t: number) => rampStops([[8, 10, 14], [55, 60, 72], [135, 145, 160], [220, 225, 235], [255, 255, 255]], t),
    ask: (t: number) => rampStops([[8, 10, 14], [55, 60, 72], [135, 145, 160], [220, 225, 235], [255, 255, 255]], t),
  },
  inferno: {
    bid: (t: number) => rampStops([[0, 0, 4], [40, 11, 84], [120, 28, 109], [200, 55, 85], [252, 135, 40], [252, 255, 164]], t),
    ask: (t: number) => rampStops([[0, 0, 4], [40, 11, 84], [120, 28, 109], [200, 55, 85], [252, 135, 40], [252, 255, 164]], t),
  },
}

const cmapColor = (side: 'bid' | 'ask', t: number, cmapName: string = 'bookmap', a: number = 0.85) => {
  const cmap = (CMAPS as Record<string, { bid: (t: number) => number[]; ask: (t: number) => number[] }>)[cmapName] || CMAPS.bookmap
  return rgba(cmap[side](t), a)
}

/**
 * Maps arbitrary tick timestamps to visual chart X coordinate across candle bars.
 */
export function mapTimeToCoordinate(
  eventTime: number,
  candleTimes: readonly number[],
  timeToCoordFn: (t: Time) => number | null,
  barSpacing: number = 8,
): number | null {
  if (!candleTimes || candleTimes.length === 0) {
    return timeToCoordFn(eventTime as UTCTimestamp)
  }

  let low = 0
  let high = candleTimes.length - 1
  let idx = -1
  while (low <= high) {
    const mid = (low + high) >> 1
    if (candleTimes[mid] <= eventTime) {
      idx = mid
      low = mid + 1
    } else {
      high = mid - 1
    }
  }

  if (idx === -1) {
    const firstCoord = timeToCoordFn(candleTimes[0] as UTCTimestamp)
    if (firstCoord === null) return null
    const dt = candleTimes.length > 1 ? candleTimes[1] - candleTimes[0] : 300
    const diff = eventTime - candleTimes[0]
    if (Math.abs(diff) > dt * 2) return null
    const nextCoord = candleTimes.length > 1 ? timeToCoordFn(candleTimes[1] as UTCTimestamp) : null
    const span = nextCoord !== null ? nextCoord - firstCoord : barSpacing
    return firstCoord + (diff / dt) * span
  }

  const cTime = candleTimes[idx]
  const cCoord = timeToCoordFn(cTime as UTCTimestamp)
  if (cCoord === null) return null

  if (idx < candleTimes.length - 1) {
    const nextTime = candleTimes[idx + 1]
    const nextCoord = timeToCoordFn(nextTime as UTCTimestamp)
    const dt = nextTime - cTime
    const frac = dt > 0 ? (eventTime - cTime) / dt : 0
    if (nextCoord !== null) {
      return cCoord + (nextCoord - cCoord) * frac
    } else {
      return cCoord + barSpacing * frac
    }
  } else {
    const dt = idx > 0 ? cTime - candleTimes[idx - 1] : 300
    const frac = dt > 0 ? (eventTime - cTime) / dt : 0
    return cCoord + barSpacing * Math.min(frac, 0.95)
  }
}

/* ========================================================================= */
/* BUBBLES PRIMITIVE RENDERER                                                */
/* ========================================================================= */

class BubblesRenderer implements IPrimitivePaneRenderer {
  private _primitive: BubblesPrimitive

  constructor(primitive: BubblesPrimitive) {
    this._primitive = primitive
  }

  draw(target: CanvasRenderingTarget2D): void {
    target.useBitmapCoordinateSpace((scope: BitmapCoordinatesRenderingScope) => {
      const { context: ctx, bitmapSize, horizontalPixelRatio: hpr, verticalPixelRatio: vpr } = scope
      const attached = this._primitive.attachedParams
      const ui = this._primitive.options
      if (!attached || !ui.showBubbles) return

      const trades = this._primitive.events
      if (!trades || trades.length === 0) return

      const chart = attached.chart
      const series = attached.series
      const ts = chart.timeScale()
      const candleTimes = this._primitive.candleTimes
      const barSpacing = ts.options().barSpacing || 8

      // Visible range bounds for fast viewport filtering
      const visibleRange = typeof ts.getVisibleRange === 'function' ? ts.getVisibleRange() : null
      const minVisTime = visibleRange ? (visibleRange.from as number) - 30 : -Infinity
      const maxVisTime = visibleRange ? (visibleRange.to as number) + 30 : Infinity

      // Binary search for visible trades
      let startIdx = 0
      let endIdx = trades.length
      if (visibleRange) {
        let l = 0, r = trades.length - 1
        while (l <= r) {
          const m = (l + r) >> 1
          if (trades[m].time >= minVisTime) {
            startIdx = m
            r = m - 1
          } else {
            l = m + 1
          }
        }
        l = startIdx
        r = trades.length - 1
        endIdx = trades.length
        while (l <= r) {
          const m = (l + r) >> 1
          if (trades[m].time <= maxVisTime) {
            endIdx = m + 1
            l = m + 1
          } else {
            r = m - 1
          }
        }
      }

      if (startIdx >= endIdx) return

      // Compute gMax over visible window
      let gMax = 1
      for (let i = startIdx; i < endIdx; i++) {
        if (trades[i].observed_qty > gMax) gMax = trades[i].observed_qty
      }

      const minR = ui.bubMin * hpr
      const maxR = ui.bubMax * hpr
      const sizeFn = (q: number) => {
        let t: number
        if (ui.bubScale === 'log') t = Math.log10(1 + q) / Math.log10(1 + gMax)
        else if (ui.bubScale === 'linear') t = q / gMax
        else t = Math.sqrt(q / gMax)
        return minR + clamp(t, 0, 1) * (maxR - minR)
      }

      ctx.save()

      // Pass 1: Small / Hollow Trades & Neutral UNKNOWN
      for (let i = startIdx; i < endIdx; i++) {
        const tr = trades[i]
        if (tr.observed_qty < ui.minTrade) continue
        const isLargeBuySell = tr.observed_qty >= ui.largeQty && (tr.side === 'BUY' || tr.side === 'SELL')
        if (isLargeBuySell) continue

        const x = mapTimeToCoordinate(tr.time, candleTimes, (t) => ts.timeToCoordinate(t as UTCTimestamp), barSpacing)
        if (x === null) continue
        const y = series.priceToCoordinate(tr.price)
        if (y === null) continue

        const xPx = x * hpr
        const yPx = y * vpr
        if (xPx < -50 || xPx > bitmapSize.width + 50) continue

        const r = sizeFn(tr.observed_qty)
        const isUnknown = tr.side === 'UNKNOWN'
        const fb = tr.side === 'BUY' ? '38,166,154' : tr.side === 'SELL' ? '239,83,80' : '148,163,184'

        ctx.beginPath()
        ctx.arc(xPx, yPx, r, 0, Math.PI * 2)
        ctx.fillStyle = isUnknown ? `rgba(${fb},0.04)` : `rgba(${fb},0.08)`
        ctx.fill()
        ctx.lineWidth = 0.8 * hpr
        ctx.strokeStyle = isUnknown ? `rgba(${fb},0.40)` : `rgba(${fb},0.70)`
        ctx.stroke()

        // Canonical Absorption Marker (Event-Local)
        if (tr.is_absorbed) {
          ctx.beginPath()
          ctx.arc(xPx, yPx, r * 1.45, 0, Math.PI * 2)
          ctx.lineWidth = 1.5 * hpr
          ctx.strokeStyle = 'rgba(245, 158, 11, 0.95)'
          ctx.stroke()
        }
      }

      // Pass 2: Large BUY / SELL Trades with Luminous Halo
      for (let i = startIdx; i < endIdx; i++) {
        const tr = trades[i]
        const isLargeBuySell = tr.observed_qty >= ui.largeQty && (tr.side === 'BUY' || tr.side === 'SELL')
        if (!isLargeBuySell) continue

        const x = mapTimeToCoordinate(tr.time, candleTimes, (t) => ts.timeToCoordinate(t as UTCTimestamp), barSpacing)
        if (x === null) continue
        const y = series.priceToCoordinate(tr.price)
        if (y === null) continue

        const xPx = x * hpr
        const yPx = y * vpr
        if (xPx < -60 || xPx > bitmapSize.width + 60) continue

        const r = sizeFn(tr.observed_qty)
        const fb = tr.side === 'BUY' ? '38,166,154' : '239,83,80'
        const halo = tr.side === 'BUY' ? '159,247,233' : '255,180,177'

        // 1. Glowing Halo Gradient
        const hg = ctx.createRadialGradient(xPx, yPx, r * 0.4, xPx, yPx, r * 1.55)
        hg.addColorStop(0, `rgba(${halo},0.35)`)
        hg.addColorStop(1, `rgba(${halo},0)`)
        ctx.fillStyle = hg
        ctx.beginPath()
        ctx.arc(xPx, yPx, r * 1.55, 0, Math.PI * 2)
        ctx.fill()

        // 2. Core Radial Gradient
        const grd = ctx.createRadialGradient(xPx, yPx, r * 0.1, xPx, yPx, r)
        grd.addColorStop(0, `rgba(${fb},1)`)
        grd.addColorStop(0.7, `rgba(${fb},0.65)`)
        grd.addColorStop(1, `rgba(${fb},0.1)`)
        ctx.fillStyle = grd
        ctx.beginPath()
        ctx.arc(xPx, yPx, r, 0, Math.PI * 2)
        ctx.fill()

        // 3. Crisp Halo Ring Stroke
        ctx.lineWidth = 1.5 * hpr
        ctx.strokeStyle = `rgb(${halo})`
        ctx.stroke()

        // Canonical Absorption Marker (Event-Local)
        if (tr.is_absorbed) {
          ctx.beginPath()
          ctx.arc(xPx, yPx, r * 1.55, 0, Math.PI * 2)
          ctx.lineWidth = 1.8 * hpr
          ctx.strokeStyle = 'rgba(245, 158, 11, 1)'
          ctx.stroke()
        }
      }

      ctx.restore()
    })
  }
}

class BubblesPaneView implements IPrimitivePaneView {
  private _renderer: BubblesRenderer

  constructor(primitive: BubblesPrimitive) {
    this._renderer = new BubblesRenderer(primitive)
  }

  zOrder(): 'normal' | 'top' | 'bottom' {
    return 'top'
  }

  renderer(): IPrimitivePaneRenderer {
    return this._renderer
  }
}

export class BubblesPrimitive implements ISeriesPrimitive<Time> {
  private _views: readonly IPrimitivePaneView[]
  private _events: VisualFlowEvent[] = []
  private _candleTimes: number[] = []
  private _options: FlowMapOptions = { ...DEFAULT_FLOW_MAP_OPTIONS }
  public attachedParams: SeriesAttachedParameter<Time> | null = null

  constructor(options?: Partial<FlowMapOptions>) {
    if (options) this._options = { ...this._options, ...options }
    this._views = [new BubblesPaneView(this)]
  }

  get events(): VisualFlowEvent[] {
    return this._events
  }

  get candleTimes(): readonly number[] {
    return this._candleTimes
  }

  get options(): FlowMapOptions {
    return this._options
  }

  setEvents(events: VisualFlowEvent[]): void {
    this._events = events
    this.requestUpdate()
  }

  setCandleTimes(times: number[]): void {
    this._candleTimes = times
    this.requestUpdate()
  }

  setOptions(options: Partial<FlowMapOptions>): void {
    this._options = { ...this._options, ...options }
    this.requestUpdate()
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this.attachedParams = param
  }

  detached(): void {
    this.attachedParams = null
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this._views
  }

  updateAllViews(): void {}

  requestUpdate(): void {
    if (this.attachedParams && this.attachedParams.requestUpdate) {
      this.attachedParams.requestUpdate()
    }
  }
}

/* ========================================================================= */
/* HEATMAP PRIMITIVE RENDERER (RESAMPLED SCREEN COLUMNS, NO OVERDRAW)        */
/* ========================================================================= */

interface ScreenColumnData {
  bids: Map<number, number>
  asks: Map<number, number>
  count: number
  xPx: number
}

class HeatmapRenderer implements IPrimitivePaneRenderer {
  private _primitive: HeatmapPrimitive

  constructor(primitive: HeatmapPrimitive) {
    this._primitive = primitive
  }

  draw(target: CanvasRenderingTarget2D): void {
    target.useBitmapCoordinateSpace((scope: BitmapCoordinatesRenderingScope) => {
      const { context: ctx, bitmapSize, horizontalPixelRatio: hpr, verticalPixelRatio: vpr } = scope
      const attached = this._primitive.attachedParams
      const ui = this._primitive.options
      if (!attached || !ui.showHeatmap) return

      const depth = this._primitive.depthSnapshots
      if (!depth || depth.length === 0) return

      const chart = attached.chart
      const series = attached.series
      const ts = chart.timeScale()
      const candleTimes = this._primitive.candleTimes
      const barSpacing = ts.options().barSpacing || 6
      const intensity = ui.hmIntensity
      const gamma = ui.hmGamma
      const hmMin = ui.hmMin
      const cmapName = ui.colormap || 'bookmap'

      // Calculate dynamic row height in bitmap pixels from current price scale spacing
      const sampleP1 = series.priceToCoordinate(24100)
      const sampleP2 = series.priceToCoordinate(24101)
      const pxPerPoint = sampleP1 !== null && sampleP2 !== null ? Math.abs(sampleP1 - sampleP2) * vpr : 2 * vpr
      // Thin, crisp Bookmap liquidity band (~2px to 4px)
      const rowH = Math.max(1.5 * vpr, Math.min(6 * vpr, Math.round(pxPerPoint * 0.90)))

      // Visible range bounds
      const visibleRange = typeof ts.getVisibleRange === 'function' ? ts.getVisibleRange() : null
      const minVisTime = visibleRange ? (visibleRange.from as number) - 30 : -Infinity
      const maxVisTime = visibleRange ? (visibleRange.to as number) + 30 : Infinity

      // Binary search visible depth slice
      let startIdx = 0
      let endIdx = depth.length
      if (visibleRange) {
        let l = 0, r = depth.length - 1
        while (l <= r) {
          const m = (l + r) >> 1
          if (depth[m].time >= minVisTime) {
            startIdx = m
            r = m - 1
          } else {
            l = m + 1
          }
        }
        l = startIdx
        r = depth.length - 1
        endIdx = depth.length
        while (l <= r) {
          const m = (l + r) >> 1
          if (depth[m].time <= maxVisTime) {
            endIdx = m + 1
            l = m + 1
          } else {
            r = m - 1
          }
        }
      }

      if (startIdx >= endIdx) return

      // Screen Column Width
      const colWidthPx = Math.max(2, Math.floor(barSpacing * hpr * 0.95))

      // 1. Resample / Bin depth snapshots into horizontal screen columns
      // This guarantees ZERO additive opacity overdraw when multiple updates share screen pixels!
      const columns = new Map<number, ScreenColumnData>()
      let maxObservedQty = 1

      for (let i = startIdx; i < endIdx; i++) {
        const d = depth[i]
        const x = mapTimeToCoordinate(d.time, candleTimes, (t) => ts.timeToCoordinate(t as UTCTimestamp), barSpacing)
        if (x === null) continue
        const xPx = Math.round(x * hpr) - Math.floor(colWidthPx / 2)
        if (xPx + colWidthPx < 0 || xPx > bitmapSize.width) continue

        const colKey = Math.floor(xPx / colWidthPx)
        let col = columns.get(colKey)
        if (!col) {
          col = { bids: new Map(), asks: new Map(), count: 0, xPx: colKey * colWidthPx }
          columns.set(colKey, col)
        }
        col.count++

        for (const lv of d.bids) {
          const p = roundTick(lv.p)
          col.bids.set(p, (col.bids.get(p) || 0) + lv.q)
          if (lv.q > maxObservedQty) maxObservedQty = lv.q
        }
        for (const lv of d.asks) {
          const p = roundTick(lv.p)
          col.asks.set(p, (col.asks.get(p) || 0) + lv.q)
          if (lv.q > maxObservedQty) maxObservedQty = lv.q
        }
      }

      if (columns.size === 0) return

      const norm = 1 / maxObservedQty

      ctx.save()

      // 2. Draw each (column, price) cell EXACTLY ONCE
      for (const [, col] of columns) {
        const colCount = col.count || 1

        // Bids (Cyan/Teal Liquidity Bands)
        for (const [p, sumQ] of col.bids) {
          const avgQ = sumQ / colCount
          if (avgQ < hmMin) continue
          const y = series.priceToCoordinate(p)
          if (y === null) continue
          let t = avgQ * norm * intensity
          t = Math.pow(clamp(t, 0, 1), gamma)
          if (t <= 0.03) continue
          ctx.fillStyle = cmapColor('bid', t, cmapName, 0.85)
          const yPx = Math.round(y * vpr) - Math.floor(rowH / 2)
          ctx.fillRect(col.xPx, yPx, colWidthPx, rowH)
        }

        // Asks (Dark Red/Orange Liquidity Bands)
        for (const [p, sumQ] of col.asks) {
          const avgQ = sumQ / colCount
          if (avgQ < hmMin) continue
          const y = series.priceToCoordinate(p)
          if (y === null) continue
          let t = avgQ * norm * intensity
          t = Math.pow(clamp(t, 0, 1), gamma)
          if (t <= 0.03) continue
          ctx.fillStyle = cmapColor('ask', t, cmapName, 0.85)
          const yPx = Math.round(y * vpr) - Math.floor(rowH / 2)
          ctx.fillRect(col.xPx, yPx, colWidthPx, rowH)
        }
      }

      ctx.restore()
    })
  }
}

class HeatmapPaneView implements IPrimitivePaneView {
  private _renderer: HeatmapRenderer

  constructor(primitive: HeatmapPrimitive) {
    this._renderer = new HeatmapRenderer(primitive)
  }

  zOrder(): 'normal' | 'top' | 'bottom' {
    return 'bottom'
  }

  renderer(): IPrimitivePaneRenderer {
    return this._renderer
  }
}

export class HeatmapPrimitive implements ISeriesPrimitive<Time> {
  private _views: readonly IPrimitivePaneView[]
  private _depthSnapshots: DepthSnapshot[] = []
  private _candleTimes: number[] = []
  private _options: FlowMapOptions = { ...DEFAULT_FLOW_MAP_OPTIONS }
  public attachedParams: SeriesAttachedParameter<Time> | null = null

  constructor(options?: Partial<FlowMapOptions>) {
    if (options) this._options = { ...this._options, ...options }
    this._views = [new HeatmapPaneView(this)]
  }

  get depthSnapshots(): DepthSnapshot[] {
    return this._depthSnapshots
  }

  get candleTimes(): readonly number[] {
    return this._candleTimes
  }

  get options(): FlowMapOptions {
    return this._options
  }

  setDepthSnapshots(depth: DepthSnapshot[]): void {
    this._depthSnapshots = depth
    this.requestUpdate()
  }

  setCandleTimes(times: number[]): void {
    this._candleTimes = times
    this.requestUpdate()
  }

  setOptions(options: Partial<FlowMapOptions>): void {
    this._options = { ...this._options, ...options }
    this.requestUpdate()
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this.attachedParams = param
  }

  detached(): void {
    this.attachedParams = null
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this._views
  }

  updateAllViews(): void {}

  requestUpdate(): void {
    if (this.attachedParams && this.attachedParams.requestUpdate) {
      this.attachedParams.requestUpdate()
    }
  }
}
