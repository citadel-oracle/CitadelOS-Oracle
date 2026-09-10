import { describe, expect, it, vi } from 'vitest'
import {
  BubblesPrimitive,
  HeatmapPrimitive,
  mapTimeToCoordinate,
  type DepthSnapshot,
  type VisualFlowEvent,
} from './FlowMapPrimitives'

describe('FlowMapPrimitives — Coordinate Mapping Adapter', () => {
  it('correctly maps intra-candle tick timestamps into candle coordinates without returning null', () => {
    const candleTimes = [
      1786074900, // 09:15:00
      1786075200, // 09:20:00
      1786075500, // 09:25:00
      1786075800, // 09:30:00
      1786076100, // 09:35:00
    ]

    const candleCoords: Record<number, number> = {
      1786074900: 100,
      1786075200: 150,
      1786075500: 200,
      1786075800: 250,
      1786076100: 300,
    }
    const mockCoordFn = (t: any) => candleCoords[Number(t)] ?? null

    // Exact bar time
    const coordExact = mapTimeToCoordinate(1786074900, candleTimes, mockCoordFn)
    expect(coordExact).toBe(100)

    // Intra-candle tick (e.g. 09:17:30 -> halfway between 09:15 and 09:20)
    const coordIntra = mapTimeToCoordinate(1786075050, candleTimes, mockCoordFn)
    expect(coordIntra).toBe(125)

    // Intra-candle tick (e.g. 09:22:30 -> halfway between 09:20 and 09:25)
    const coordIntra2 = mapTimeToCoordinate(1786075350, candleTimes, mockCoordFn)
    expect(coordIntra2).toBe(175)

    // Latest forming candle tick (09:36:00 -> 300 + 8 * 0.2 = 301.6)
    const coordForming = mapTimeToCoordinate(1786076160, candleTimes, mockCoordFn, 8)
    expect(coordForming).toBeCloseTo(301.6)
  })
})

describe('FlowMapPrimitives — BubblesPrimitive', () => {
  it('initializes with default options and manages events buffer & candle times', () => {
    const primitive = new BubblesPrimitive()
    expect(primitive.options.showBubbles).toBe(true)
    expect(primitive.events).toEqual([])

    const mockEvents: VisualFlowEvent[] = [
      {
        event_id: 'ev-1',
        time: 1786074950,
        price: 24000.0,
        observed_qty: 50,
        classified_buy_qty: 50,
        classified_sell_qty: 0,
        unclassified_qty: 0,
        side: 'BUY',
        classification_method: 'PRE_EVENT_ASK_TEST',
        signer_confidence: 0.95,
      },
      {
        event_id: 'ev-2',
        time: 1786075250,
        price: 23995.0,
        observed_qty: 80,
        classified_buy_qty: 0,
        classified_sell_qty: 80,
        unclassified_qty: 0,
        side: 'SELL',
        classification_method: 'PRE_EVENT_BID_TEST',
        signer_confidence: 0.95,
      },
      {
        event_id: 'ev-3',
        time: 1786075300,
        price: 23998.0,
        observed_qty: 120,
        classified_buy_qty: 0,
        classified_sell_qty: 0,
        unclassified_qty: 120,
        side: 'UNKNOWN',
        classification_method: 'UNCLASSIFIED_AGGREGATE',
        signer_confidence: 0.0,
        is_absorbed: true,
        is_failed_aggression: true,
      },
    ]

    const requestUpdateSpy = vi.fn()
    primitive.attached({
      chart: {} as any,
      series: {} as any,
      requestUpdate: requestUpdateSpy,
      horzScaleBehavior: {} as any,
    })

    primitive.setCandleTimes([1786074900, 1786075200, 1786075500])
    primitive.setEvents(mockEvents)
    expect(primitive.events).toHaveLength(3)
    expect(primitive.candleTimes).toHaveLength(3)
    expect(requestUpdateSpy).toHaveBeenCalledTimes(2)

    primitive.setOptions({ showBubbles: false })
    expect(primitive.options.showBubbles).toBe(false)
    expect(requestUpdateSpy).toHaveBeenCalledTimes(3)
  })

  it('draws correctly into canvas target using coordinate adapter', () => {
    const primitive = new BubblesPrimitive({ showBubbles: true })
    const mockEvents: VisualFlowEvent[] = [
      {
        event_id: 'ev-buy',
        time: 1786074920,
        price: 24000.0,
        observed_qty: 50,
        classified_buy_qty: 50,
        classified_sell_qty: 0,
        unclassified_qty: 0,
        side: 'BUY',
      },
      {
        event_id: 'ev-large-sell',
        time: 1786075220,
        price: 23990.0,
        observed_qty: 600,
        classified_buy_qty: 0,
        classified_sell_qty: 600,
        unclassified_qty: 0,
        side: 'SELL',
        is_absorbed: true,
        is_failed_aggression: true,
      },
      {
        event_id: 'ev-unknown',
        time: 1786075250,
        price: 23995.0,
        observed_qty: 25,
        classified_buy_qty: 0,
        classified_sell_qty: 0,
        unclassified_qty: 25,
        side: 'UNKNOWN',
      },
    ]

    const mockTimeScale = {
      timeToCoordinate: vi.fn((t: number) => (t === 1786074900 ? 100 : t === 1786075200 ? 200 : t === 1786075500 ? 300 : null)),
      options: () => ({ barSpacing: 8 }),
    }
    const mockSeries = {
      priceToCoordinate: vi.fn((p: number) => (p === 24000.0 ? 150 : 250)),
    }

    primitive.attached({
      chart: { timeScale: () => mockTimeScale } as any,
      series: mockSeries as any,
      requestUpdate: vi.fn(),
      horzScaleBehavior: {} as any,
    })
    primitive.setCandleTimes([1786074900, 1786075200, 1786075500])
    primitive.setEvents(mockEvents)

    const paneView = primitive.paneViews()[0]
    expect(paneView.zOrder()).toBe('top')

    const renderer = paneView.renderer()
    const ctx = {
      save: vi.fn(),
      restore: vi.fn(),
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      createRadialGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
      setLineDash: vi.fn(),
    }
    const target = {
      useBitmapCoordinateSpace: (cb: any) => cb({
        context: ctx,
        bitmapSize: { width: 800, height: 400 },
        horizontalPixelRatio: 1,
        verticalPixelRatio: 1,
      }),
    }

    renderer.draw(target as any)
    expect(ctx.save).toHaveBeenCalled()
    expect(ctx.arc).toHaveBeenCalled()
    expect(ctx.restore).toHaveBeenCalled()
  })
})

describe('FlowMapPrimitives — HeatmapPrimitive', () => {
  it('manages 5-level depth snapshots and draws heatmap colormap cells using coordinate adapter', () => {
    const heatmap = new HeatmapPrimitive({ showHeatmap: true, colormap: 'bookmap' })
    expect(heatmap.options.showHeatmap).toBe(true)

    const mockDepth: DepthSnapshot[] = [
      {
        time: 1786074950,
        bids: [
          { p: 24000, q: 300, o: 10 },
          { p: 23999, q: 200, o: 5 },
          { p: 23998, q: 150, o: 3 },
          { p: 23997, q: 500, o: 12 },
          { p: 23996, q: 100, o: 2 },
        ],
        asks: [
          { p: 24001, q: 400, o: 8 },
          { p: 24002, q: 250, o: 6 },
          { p: 24003, q: 180, o: 4 },
          { p: 24004, q: 600, o: 15 },
          { p: 24005, q: 120, o: 3 },
        ],
      },
    ]

    const mockTimeScale = {
      timeToCoordinate: vi.fn((t: number) => (t === 1786074900 ? 100 : t === 1786075200 ? 200 : null)),
      getVisibleLogicalRange: vi.fn(() => ({ from: 0, to: 100 })),
      options: () => ({ barSpacing: 8 }),
    }
    const mockSeries = {
      priceToCoordinate: vi.fn((p: number) => (24005 - p) * 10),
    }

    heatmap.attached({
      chart: { timeScale: () => mockTimeScale } as any,
      series: mockSeries as any,
      requestUpdate: vi.fn(),
      horzScaleBehavior: {} as any,
    })

    heatmap.setCandleTimes([1786074900, 1786075200])
    heatmap.setDepthSnapshots(mockDepth)
    expect(heatmap.depthSnapshots).toHaveLength(1)

    const paneView = heatmap.paneViews()[0]
    expect(paneView.zOrder()).toBe('bottom')

    const renderer = paneView.renderer()
    const ctx = {
      save: vi.fn(),
      restore: vi.fn(),
      fillRect: vi.fn(),
    }
    const target = {
      useBitmapCoordinateSpace: (cb: any) => cb({
        context: ctx,
        bitmapSize: { width: 800, height: 400 },
        horizontalPixelRatio: 1,
        verticalPixelRatio: 1,
      }),
    }

    renderer.draw(target as any)
    expect(ctx.save).toHaveBeenCalled()
    expect(ctx.fillRect).toHaveBeenCalled()
    expect(ctx.restore).toHaveBeenCalled()
  })
})
