'use client'

import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Maximize2, Minimize2, Check, RotateCcw, ZoomIn, ArrowRight } from 'lucide-react'
import { createChart, LineStyle, CrosshairMode, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts'
import type { ChartDataResponse, FuturesCandle, TradeMarker } from '@/app/oracle-development/useOracleDevChartData'

class ZonePrimitive {
  private _zones: any[] = [];
  private _chart: any = null;
  private _series: any = null;
  private _paneViews: any[] = [];

  constructor(zones: any[]) {
    this._zones = zones;
    this._paneViews = [
      {
        renderer: () => ({
          draw: (target: any) => {
            if (!this._chart || !this._series) return;
            target.useMediaCoordinateSpace((scope: any) => {
              const ctx = scope.context;
              const timeScale = this._chart.timeScale();

              this._zones.forEach(zone => {
                const xStart = zone.start_time !== null && zone.start_time !== undefined ? timeScale.timeToCoordinate(zone.start_time) : null;
                const xEnd = zone.end_time !== null && zone.end_time !== undefined ? timeScale.timeToCoordinate(zone.end_time) : null;
                const yHigh = this._series.priceToCoordinate(zone.zone_high);
                const yLow = this._series.priceToCoordinate(zone.zone_low);

                if (xStart === null || yHigh === null || yLow === null) return;

                const x = xStart;
                const width = (xEnd === null || xEnd === undefined ? scope.mediaSize.width : xEnd) - xStart;
                const y = yHigh;
                const height = yLow - yHigh;

                ctx.save();
                ctx.fillStyle = zone.color || 'rgba(34, 211, 238, 0.06)';
                ctx.fillRect(x, y, width, height);

                ctx.strokeStyle = zone.borderColor || 'rgba(34, 211, 238, 0.3)';
                ctx.lineWidth = 1;
                ctx.strokeRect(x, y, width, height);

                if (zone.label) {
                  ctx.fillStyle = zone.borderColor || '#9ca3af';
                  ctx.font = '9px var(--cds-font-mono)';
                  ctx.textBaseline = 'middle';
                  ctx.fillText(zone.label, x + 6, y + height / 2);
                }
                ctx.restore();
              });
            });
          }
        })
      }
    ];
  }

  updateZones(zones: any[]) {
    this._zones = zones;
  }

  attached(param: any) {
    this._chart = param.chart;
    this._series = param.series;
  }

  detached() {
    this._chart = null;
    this._series = null;
  }

  update() {}

  paneViews() {
    return this._paneViews;
  }
}

interface FuturesIntelligenceChartProps {
  data: ChartDataResponse | null
  loading: boolean
  error: string | null
  selectedLane: '1m' | '3m' | '5m'
  onLaneChange: (lane: '1m' | '3m' | '5m') => void
  highlightedStrategy: string | null
  onHighlightStrategy: (strategyId: string | null) => void
  overrideExpand?: boolean
  overrideLayers?: string[] | null
  overrideSelectedTradeId?: string | null
  overrideZoom?: number | null
  overrideScroll?: number | null
  forceInsufficient?: boolean
  overrideHoverIndex?: number | 'auto' | null
  forceSync?: () => Promise<void>
  syncStatus?: 'idle' | 'loading' | 'success' | 'failure'
  syncCooldown?: boolean
}

export function FuturesIntelligenceChart({
  data,
  loading,
  error,
  selectedLane,
  onLaneChange,
  highlightedStrategy,
  onHighlightStrategy,
  overrideExpand = false,
  overrideLayers = null,
  overrideSelectedTradeId = null,
  overrideZoom = null,
  overrideScroll = null,
  forceInsufficient = false,
  overrideHoverIndex = null,
  forceSync,
  syncStatus = 'idle',
  syncCooldown = false
}: FuturesIntelligenceChartProps) {
  const [isExpanded, setIsExpanded] = useState(overrideExpand)
  const chartHeight = isExpanded ? 360 : 220
  const volHeight = 50
  const bottomAxisHeight = 25
  const totalHeight = chartHeight + volHeight + bottomAxisHeight
  const [layers, setLayers] = useState({
    VWAP: true,
    FVG: true,
    VOB: true,
    VOLUME: true,
    TRADES: true,
    GUARDIAN: true,
    STRUCTURE: true
  })

  const containerRef = useRef<HTMLDivElement | null>(null)
  const [chartReady, setChartReady] = useState(false)

  // Stable refs for chart and series instances
  const chartInstanceRef = useRef<any>(null)
  const candlestickSeriesRef = useRef<any>(null)
  const lastFvgsStrRef = useRef<string>('')
  const lastVobsStrRef = useRef<string>('')
  const vwapSeriesRef = useRef<any>(null)
  const volumeSeriesRef = useRef<any>(null)
  const fvgPrimitiveRef = useRef<any>(null)
  const vobPrimitiveRef = useRef<any>(null)
  const markersPluginRef = useRef<any>(null)
  const priceLinesRef = useRef<any[]>([])

  const lastTimeframeRef = useRef<string>('')
  const lastContractRef = useRef<string>('')
  const lastCandleCountRef = useRef<number>(0)
  const lastLayersRef = useRef<any>({})

  const chartContainerRef = useCallback((node: HTMLDivElement | null) => {
    if (node !== null) {
      if (chartInstanceRef.current) return // Already initialized

      const chart = createChart(node, {
        width: node.clientWidth || 800,
        height: totalHeight,
        layout: {
          background: { color: '#040711' },
          textColor: '#9ca3af',
          fontFamily: 'var(--cds-font-mono)',
        },
        grid: {
          vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
          horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
        },
        crosshair: {
          mode: CrosshairMode.Normal,
          vertLine: {
            color: 'rgba(255, 255, 255, 0.25)',
            width: 1,
            style: LineStyle.Dashed,
            labelBackgroundColor: '#0f172a',
          },
          horzLine: {
            color: 'rgba(255, 255, 255, 0.25)',
            width: 1,
            style: LineStyle.Dashed,
            labelBackgroundColor: '#0f172a',
          },
        },
        localization: {
          timeFormatter: (time: any) => {
            let timestamp: number;
            if (typeof time === 'number') {
              timestamp = time;
            } else {
              return '';
            }
            const date = new Date(timestamp * 1000);
            return new Intl.DateTimeFormat('en-IN', {
              timeZone: 'Asia/Kolkata',
              year: 'numeric',
              month: 'short',
              day: '2-digit',
              hour: '2-digit',
              minute: '2-digit',
              hour12: false
            }).format(date);
          }
        },
        timeScale: {
          borderColor: 'rgba(255, 255, 255, 0.08)',
          timeVisible: true,
          secondsVisible: false,
          rightOffset: 5,
          barSpacing: 6,
          tickMarkFormatter: (time: any, tickMarkType: any, locale: string) => {
            let timestamp: number;
            if (typeof time === 'number') {
              timestamp = time;
            } else if (time && typeof time === 'object' && 'timestamp' in time) {
              timestamp = (time as any).timestamp;
            } else {
              return '';
            }
            const date = new Date(timestamp * 1000);
            if (tickMarkType === 0 || tickMarkType === 1) {
              return new Intl.DateTimeFormat('en-IN', {
                timeZone: 'Asia/Kolkata',
                day: '2-digit',
                month: 'short'
              }).format(date);
            }
            return new Intl.DateTimeFormat('en-IN', {
              timeZone: 'Asia/Kolkata',
              hour: '2-digit',
              minute: '2-digit',
              hour12: false
            }).format(date);
          }
        },
      })

      chartInstanceRef.current = chart

      const candlestickSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#10b981',
        downColor: '#ef4444',
        borderUpColor: '#10b981',
        borderDownColor: '#ef4444',
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
      })
      candlestickSeriesRef.current = candlestickSeries

      const vwapSeries = chart.addSeries(LineSeries, {
        color: '#a855f7',
        lineWidth: 2,
        priceLineVisible: false,
      })
      vwapSeriesRef.current = vwapSeries

      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: {
          type: 'volume',
        },
        priceScaleId: 'volume-scale',
      })
      volumeSeriesRef.current = volumeSeries

      chart.priceScale('volume-scale').applyOptions({
        visible: false,
      })

      volumeSeries.priceScale().applyOptions({
        scaleMargins: {
          top: 0.8,
          bottom: 0,
        },
      })

      fvgPrimitiveRef.current = new ZonePrimitive([])
      vobPrimitiveRef.current = new ZonePrimitive([])
      candlestickSeries.attachPrimitive(fvgPrimitiveRef.current)
      candlestickSeries.attachPrimitive(vobPrimitiveRef.current)

      // Initialize the series markers plugin for v5
      const markersPlugin = createSeriesMarkers(candlestickSeries, [])
      markersPluginRef.current = markersPlugin

      chart.subscribeCrosshairMove((param: any) => {
        if (!param || !param.time || param.point === undefined) {
          setHoverIndex(null)
          setHoverX(null)
          setHoverY(null)
          return
        }
        
        const hoverTime = param.time
        const list = candlesRef.current
        const idx = list.findIndex((c: any) => c.time === hoverTime)
        if (idx !== -1) {
          setHoverIndex(idx)
          setHoverX(param.point.x)
          setHoverY(param.point.y)
        } else {
          setHoverIndex(null)
          setHoverX(null)
          setHoverY(null)
        }
      })

      chart.subscribeClick((param: any) => {
        if (!param || !param.time || param.point === undefined) {
          setSelectedTrade(null)
          return
        }
        
        const timeVal = param.time
        const t = visibleTradesRef.current.find((x: any) => parseInt(x.trigger_candle) === timeVal)
        if (t) {
          setSelectedTrade({
            trade: t,
            x: param.point.x,
            y: param.point.y
          })
        } else {
          setSelectedTrade(null)
        }
      })

      setChartReady(true)
    } else {
      if (chartInstanceRef.current) {
        chartInstanceRef.current.remove()
        chartInstanceRef.current = null
      }
      candlestickSeriesRef.current = null
      vwapSeriesRef.current = null
      volumeSeriesRef.current = null
      fvgPrimitiveRef.current = null
      vobPrimitiveRef.current = null
      markersPluginRef.current = null
      setChartReady(false)
    }
  }, [totalHeight])
  const [containerWidth, setContainerWidth] = useState(1100)

  // React state for hover tooltip
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const [hoverX, setHoverX] = useState<number | null>(null)
  const [hoverY, setHoverY] = useState<number | null>(null)
  const [selectedTrade, setSelectedTrade] = useState<{ trade: TradeMarker; x: number; y: number } | null>(null)



  // ResizeObserver for responsive width
  useEffect(() => {
    if (!containerRef.current) return
    const resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        if (entry.contentRect.width) {
          setContainerWidth(Math.floor(entry.contentRect.width))
        }
      }
    })
    resizeObserver.observe(containerRef.current)
    return () => resizeObserver.disconnect()
  }, [])

  const candles = data?.candles || []
  const overlays = data?.overlays || {
    swings: [],
    fvgs: [],
    vobs: [],
    vwap_series: [],
    range: { high: 0, low: 0, mid: 0 },
    prev_day: { high: 0, low: 0, close: 0 },
    opening_range: { high: 0, low: 0 }
  }
  const { swings = [], fvgs = [], vobs = [], range = { high: 0, low: 0, mid: 0 }, prev_day = { high: 0, low: 0, close: 0 }, opening_range = { high: 0, low: 0 }, structure_events = [] } = overlays
  const trades = data?.trades || []

  const requiredCount = selectedLane === '1m' ? 80 : (selectedLane === '3m' ? 60 : 50)
  const isInsufficientHistory = forceInsufficient || (candles.length < requiredCount)



  const visibleTrades = React.useMemo(() => {
    if (!highlightedStrategy) return trades
    return trades.filter(t => t.strategy_id === highlightedStrategy)
  }, [trades, highlightedStrategy])

  // Refs for callbacks
  const candlesRef = useRef<any[]>([])
  const visibleTradesRef = useRef<any[]>([])

  useEffect(() => {
    candlesRef.current = candles
  }, [candles])

  useEffect(() => {
    visibleTradesRef.current = visibleTrades
  }, [visibleTrades])

  // Sync state override
  useEffect(() => {
    setIsExpanded(overrideExpand)
  }, [overrideExpand])

  useEffect(() => {
    if (overrideLayers) {
      setLayers({
        VWAP: overrideLayers.includes('VWAP'),
        VOB: overrideLayers.includes('VOB'),
        FVG: overrideLayers.includes('FVG'),
        VOLUME: overrideLayers.includes('VOLUME'),
        TRADES: overrideLayers.includes('TRADES'),
        GUARDIAN: overrideLayers.includes('GUARDIAN'),
        STRUCTURE: overrideLayers.includes('STRUCTURE')
      })
    }
  }, [overrideLayers])

  // Handle resizing
  useEffect(() => {
    if (chartInstanceRef.current) {
      const w = containerWidth > 24 ? containerWidth - 24 : 800
      chartInstanceRef.current.resize(w, totalHeight)
    }
  }, [containerWidth, totalHeight])

  // Handle data updates
  useEffect(() => {
    if (!chartReady || !chartInstanceRef.current || !candlestickSeriesRef.current || candles.length === 0) return

    const chart = chartInstanceRef.current
    const series = candlestickSeriesRef.current
    const vwapSeries = vwapSeriesRef.current
    const volumeSeries = volumeSeriesRef.current

    const tfChanged = lastTimeframeRef.current !== selectedLane
    const contractChanged = lastContractRef.current !== data?.contract
    const countDecreased = candles.length < lastCandleCountRef.current
    const layersChanged = lastLayersRef.current.VOLUME !== layers.VOLUME || lastLayersRef.current.VWAP !== layers.VWAP
    const needsReset = tfChanged || contractChanged || countDecreased || layersChanged || lastCandleCountRef.current === 0

    const formattedCandles = candles.map((c: any) => ({
      time: Number(c.time),
      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close)
    }))

    const formattedVolume = candles.map((c: any) => ({
      time: Number(c.time),
      value: Number(c.volume || 0),
      color: Number(c.close) >= Number(c.open) ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)'
    }))

    const formattedVwap = candles
      .filter((c: any) => c.vwap !== undefined && c.vwap !== null)
      .map((c: any) => ({
        time: Number(c.time),
        value: Number(c.vwap)
      }))

    if (needsReset) {
      series.setData(formattedCandles)
      
      if (layers.VOLUME) {
        volumeSeries.setData(formattedVolume)
      } else {
        volumeSeries.setData([])
      }

      if (layers.VWAP) {
        vwapSeries.setData(formattedVwap)
      } else {
        vwapSeries.setData([])
      }

      chart.timeScale().fitContent()

      lastTimeframeRef.current = selectedLane
      lastContractRef.current = data?.contract || ''
      lastLayersRef.current = { VOLUME: layers.VOLUME, VWAP: layers.VWAP }
    } else {
      const lastIndex = lastCandleCountRef.current - 1
      for (let i = lastIndex; i < candles.length; i++) {
        const c = candles[i]
        
        series.update({
          time: Number(c.time),
          open: Number(c.open),
          high: Number(c.high),
          low: Number(c.low),
          close: Number(c.close)
        })

        if (layers.VOLUME) {
          volumeSeries.update({
            time: Number(c.time),
            value: Number(c.volume || 0),
            color: Number(c.close) >= Number(c.open) ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)'
          })
        }

        if (layers.VWAP && c.vwap !== undefined && c.vwap !== null) {
          vwapSeries.update({
            time: Number(c.time),
            value: Number(c.vwap)
          })
        }
      }
    }

    lastCandleCountRef.current = candles.length
  }, [chartReady, candles, selectedLane, data?.contract, layers.VOLUME, layers.VWAP])

  // Handle primitives updates
  useEffect(() => {
    if (!chartReady || !candlestickSeriesRef.current || !fvgPrimitiveRef.current || !vobPrimitiveRef.current) return

    const parseSafeTime = (dateStr: string) => {
      if (!dateStr || dateStr === 'N/A') return null;
      const parsed = Date.parse(dateStr);
      return isNaN(parsed) ? null : parsed / 1000;
    }

    // 1. Process FVG (last 3 active underlying only, chronologically sorted)
    let mappedFvgs: any[] = []
    if (layers.FVG) {
      const activeFvgs = fvgs
        .filter((f: any) => f.price_space === 'UNDERLYING' && (f.lifecycle === 'OPEN' || f.lifecycle === 'PARTIALLY_MITIGATED'))
        .map((f: any) => {
          const startTime = f.time || parseSafeTime(f.created_at) || 0;
          return {
            start_time: startTime,
            end_time: null,
            zone_high: Number(f.zone_high),
            zone_low: Number(f.zone_low),
            color: f.direction === 'CALL' ? 'rgba(16, 185, 129, 0.05)' : 'rgba(239, 68, 68, 0.05)',
            borderColor: f.direction === 'CALL' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
            label: `${f.direction === 'CALL' ? 'BULLISH FVG' : 'BEARISH FVG'} (${Number(f.zone_low).toFixed(1)}-${Number(f.zone_high).toFixed(1)}) [${f.lifecycle}]`
          };
        })
      
      // Sort by start_time descending, slice top 3, then restore chronological order (ascending)
      activeFvgs.sort((a, b) => b.start_time - a.start_time)
      const top3Fvgs = activeFvgs.slice(0, 3)
      top3Fvgs.sort((a, b) => a.start_time - b.start_time)
      mappedFvgs = top3Fvgs
    }

    // 2. Process VOB (last 3 active underlying only, chronologically sorted)
    let mappedVobs: any[] = []
    if (layers.VOB) {
      const activeVobs = vobs
        .filter((v: any) => v.price_space === 'UNDERLYING' && (v.status === 'ACTIVE' || v.status === 'TESTED'))
        .map((v: any) => {
          const startTime = parseSafeTime(v.created_at) || (candles[0]?.time || 0);
          const provenanceText = selectedLane === '1m' ? '3m VOB context' : `${v.timeframe || selectedLane} VOB`;
          return {
            start_time: startTime,
            end_time: null,
            zone_high: Number(v.zone_high),
            zone_low: Number(v.zone_low),
            color: v.side === 'BULLISH' ? 'rgba(59, 130, 246, 0.05)' : 'rgba(245, 158, 11, 0.05)',
            borderColor: v.side === 'BULLISH' ? 'rgba(59, 130, 246, 0.2)' : 'rgba(245, 158, 11, 0.2)',
            label: `${v.side === 'BULLISH' ? 'DEMAND VOB' : 'SUPPLY VOB'} (${Number(v.zone_low).toFixed(1)}-${Number(v.zone_high).toFixed(1)}) [${v.status}] (${provenanceText})`
          };
        })

      // Sort by start_time descending, slice top 3, then restore chronological order (ascending)
      activeVobs.sort((a, b) => b.start_time - a.start_time)
      const top3Vobs = activeVobs.slice(0, 3)
      top3Vobs.sort((a, b) => a.start_time - b.start_time)
      mappedVobs = top3Vobs
    }

    const mappedFvgsStr = JSON.stringify(mappedFvgs)
    const mappedVobsStr = JSON.stringify(mappedVobs)
    
    if (lastFvgsStrRef.current !== mappedFvgsStr) {
      fvgPrimitiveRef.current.updateZones(mappedFvgs)
      lastFvgsStrRef.current = mappedFvgsStr
    }
    if (lastVobsStrRef.current !== mappedVobsStr) {
      vobPrimitiveRef.current.updateZones(mappedVobs)
      lastVobsStrRef.current = mappedVobsStr
    }

    candlestickSeriesRef.current.applyOptions({})
  }, [chartReady, fvgs, vobs, layers.FVG, layers.VOB, candles])

  // Handle trade and structure markers
  useEffect(() => {
    if (!chartReady || !candlestickSeriesRef.current || !markersPluginRef.current) return

    const tradeMarkers = layers.TRADES ? visibleTrades.map((t: any) => {
      const timeVal = parseInt(t.trigger_candle)
      const isCALL = t.direction === 'CALL'
      const isExit = t.exit_reason !== 'OPEN'
      
      return {
        time: timeVal,
        position: isExit ? (isCALL ? 'aboveBar' : 'belowBar') : (isCALL ? 'belowBar' : 'aboveBar'),
        color: isExit ? '#fbbf24' : (isCALL ? '#10b981' : '#ef4444'),
        shape: isExit ? 'diamond' : (isCALL ? 'arrowUp' : 'arrowDown'),
        text: isExit ? `EXIT (${t.exit_reason})` : `${t.direction} ENTRY`,
        size: 1.5
      }
    }).filter((m: any) => !isNaN(m.time)) : []

    const structureMarkers = layers.STRUCTURE ? structure_events.map((se: any) => {
      const timeVal = parseInt(se.time)
      const isCALL = se.direction === 'CALL'
      
      let position: 'aboveBar' | 'belowBar' = isCALL ? 'belowBar' : 'aboveBar'
      let color = '#3b82f6'
      let shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown' | 'diamond' = 'circle'
      let label = se.event_type
      
      if (se.event_type === 'BOS') {
        color = isCALL ? '#10b981' : '#ef4444'
        shape = 'circle'
        position = isCALL ? 'aboveBar' : 'belowBar'
      } else if (se.event_type === 'CHOCH') {
        color = isCALL ? '#059669' : '#dc2626'
        shape = 'square'
        position = isCALL ? 'aboveBar' : 'belowBar'
      } else if (se.event_type === 'SWEEP') {
        color = '#fbbf24'
        shape = isCALL ? 'arrowUp' : 'arrowDown'
        position = isCALL ? 'belowBar' : 'aboveBar'
      } else if (se.event_type === 'RETEST') {
        color = '#8b5cf6'
        shape = 'diamond'
        position = isCALL ? 'belowBar' : 'aboveBar'
      } else if (se.event_type === 'TRAP') {
        color = '#ec4899'
        shape = 'circle'
        position = isCALL ? 'aboveBar' : 'belowBar'
      } else if (se.event_type === 'BREAKOUT') {
        color = '#3b82f6'
        shape = isCALL ? 'arrowUp' : 'arrowDown'
        position = isCALL ? 'aboveBar' : 'belowBar'
      } else if (se.event_type === 'ACCEPTANCE') {
        color = '#06b6d4'
        shape = 'square'
        position = isCALL ? 'aboveBar' : 'belowBar'
      }

      return {
        time: timeVal,
        position: position,
        color: color,
        shape: shape,
        text: `${label} (${Number(se.level).toFixed(1)})`,
        size: 1.0
      }
    }).filter((m: any) => !isNaN(m.time)) : []

    const allMarkers = [...tradeMarkers, ...structureMarkers]
    allMarkers.sort((a: any, b: any) => a.time - b.time)

    markersPluginRef.current.setMarkers(allMarkers)
  }, [chartReady, visibleTrades, structure_events, layers.TRADES, layers.STRUCTURE])

  // Handle Guardian lines
  useEffect(() => {
    if (!chartReady || !candlestickSeriesRef.current) return

    priceLinesRef.current.forEach(line => candlestickSeriesRef.current.removePriceLine(line))
    priceLinesRef.current = []

    if (layers.GUARDIAN) {
      visibleTrades.forEach((t: any) => {
        if (t.exit_reason === 'OPEN') {
          const slLine = candlestickSeriesRef.current.createPriceLine({
            price: Number(t.structural_sl),
            color: 'rgba(239, 68, 68, 0.7)',
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: `SL: ${t.structural_sl}`
          })
          const tpLine = candlestickSeriesRef.current.createPriceLine({
            price: Number(t.target),
            color: 'rgba(16, 185, 129, 0.7)',
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: `Target: ${t.target}`
          })
          priceLinesRef.current.push(slLine, tpLine)
        }
      })
    }
  }, [visibleTrades, layers.GUARDIAN])

  const handleLatest = () => {
    if (chartInstanceRef.current) {
      chartInstanceRef.current.timeScale().scrollToRealtime()
    }
  }

  const handleFit = () => {
    if (chartInstanceRef.current) {
      chartInstanceRef.current.timeScale().fitContent()
    }
  }

  const handleResetPriceScale = () => {
    if (candlestickSeriesRef.current) {
      candlestickSeriesRef.current.priceScale().applyOptions({
        autoScale: true,
      })
    }
  }

  const isFixture = data?.source_mode === 'TEST_FIXTURE'
  const activeHoverCandle = hoverIndex !== null ? candles[hoverIndex] : null

  return (
    <div 
      ref={containerRef}
      style={{
        margin: '12px 20px',
        background: '#040711',
        border: '1px solid rgba(34, 211, 238, 0.15)',
        borderRadius: '6px',
        padding: '12px',
        boxShadow: '0 4px 30px rgba(0,0,0,0.6)',
        position: 'relative',
        width: 'auto'
      }}
    >
      {/* 1. SLIM COMMAND STRIP / METADATA */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.04)', paddingBottom: '8px', marginBottom: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <strong style={{ fontSize: '13px', color: '#fff', fontFamily: 'var(--cds-font-mono)' }}>
            {data?.contract || 'NIFTY Futures'}
          </strong>
          <span style={{ fontSize: '10px', color: '#6b7280', fontFamily: 'var(--cds-font-mono)' }}>
            Expiry: {data?.expiry || '—'}
          </span>
          <strong style={{ fontSize: '15px', color: '#fff', fontFamily: 'var(--cds-font-mono)' }}>
            {data?.ltp && typeof data.ltp === 'number' ? data.ltp.toLocaleString('en-IN') : '—'}
          </strong>
          <span style={{ 
            fontSize: '11px', 
            color: typeof data?.basis === 'number' && data.basis >= 0 ? '#10b981' : '#ef4444',
            fontFamily: 'var(--cds-font-mono)'
          }}>
            Basis: {data?.basis && typeof data.basis === 'number' ? `${data.basis > 0 ? '+' : ''}${data.basis.toFixed(2)} pts` : '—'}
          </span>
        </div>

        {/* CONTROLS BUTTONS */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {isFixture && (
            <span style={{
              padding: '2px 6px',
              borderRadius: '2px',
              fontSize: '9px',
              fontWeight: 'bold',
              fontFamily: 'var(--cds-font-mono)',
              background: 'rgba(249, 115, 22, 0.1)',
              color: '#f97316',
              border: '1px solid rgba(249, 115, 22, 0.2)'
            }}>
              TEST FIXTURE
            </span>
          )}

          {data && (
            <span style={{
              padding: '2px 6px',
              borderRadius: '2px',
              fontSize: '9px',
              fontWeight: 'bold',
              fontFamily: 'var(--cds-font-mono)',
              background: data.is_stale ? 'rgba(251, 191, 36, 0.1)' : data.is_replay ? 'rgba(59, 130, 246, 0.1)' : 'rgba(16, 185, 129, 0.1)',
              color: data.is_stale ? '#fbbf24' : data.is_replay ? '#3b82f6' : '#10b981',
              border: `1px solid ${data.is_stale ? 'rgba(251, 191, 36, 0.2)' : data.is_replay ? 'rgba(59, 130, 246, 0.2)' : 'rgba(16, 185, 129, 0.2)'}`
            }}>
              {data.is_stale ? 'FEED STALE (BLOCKED)' : data.is_replay ? 'REPLAY MODE' : 'LIVE FEED'}
            </span>
          )}

          {/* Timeframe Selector */}
          <div style={{ display: 'flex', background: '#0a0f1d', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '3px', padding: '1px' }}>
            {(['1m', '3m', '5m'] as const).map(tf => (
              <button
                key={tf}
                onClick={() => onLaneChange(tf)}
                style={{
                  padding: '2px 8px',
                  background: selectedLane === tf ? 'rgba(34, 211, 238, 0.12)' : 'transparent',
                  border: 'none',
                  color: selectedLane === tf ? '#22d3ee' : '#6b7280',
                  borderRadius: '2px',
                  fontSize: '10px',
                  fontWeight: 'bold',
                  cursor: 'pointer',
                  fontFamily: 'var(--cds-font-mono)'
                }}
              >
                {tf}
              </button>
            ))}
          </div>

          {/* LATEST Button */}
          <button
            onClick={handleLatest}
            style={{
              padding: '4px 8px',
              background: '#0a0f1d',
              border: '1px solid rgba(255,255,255,0.06)',
              borderRadius: '3px',
              color: '#9ca3af',
              fontSize: '10px',
              fontWeight: 'bold',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}
            title="Scroll to latest candlestick"
          >
            <ArrowRight size={10} /> LATEST
          </button>

          {/* FIT Button */}
          <button
            onClick={handleFit}
            style={{
              padding: '4px 8px',
              background: '#0a0f1d',
              border: '1px solid rgba(255,255,255,0.06)',
              borderRadius: '3px',
              color: '#9ca3af',
              fontSize: '10px',
              fontWeight: 'bold',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}
            title="Fit all candles on screen"
          >
            <ZoomIn size={10} /> FIT
          </button>

          {/* RESET PRICE SCALE Button */}
          <button
            onClick={handleResetPriceScale}
            style={{
              padding: '4px 8px',
              background: '#0a0f1d',
              border: '1px solid rgba(255,255,255,0.06)',
              borderRadius: '3px',
              color: '#9ca3af',
              fontSize: '10px',
              fontWeight: 'bold',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}
            title="Reset vertical price scale"
          >
            <RotateCcw size={10} /> RESET PRICE SCALE
          </button>

          {/* Compact / Expand Toggle */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            style={{
              padding: '5px',
              background: '#0a0f1d',
              border: '1px solid rgba(255,255,255,0.06)',
              borderRadius: '3px',
              color: '#9ca3af',
              cursor: 'pointer'
            }}
          >
            {isExpanded ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
          </button>
        </div>
      </div>

      {/* 2. LAYER TOGGLES & LEGEND STRIP */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px', fontSize: '9px' }}>
        {(Object.keys(layers) as Array<keyof typeof layers>).map(layer => (
          <button
            key={layer}
            onClick={() => setLayers(p => ({ ...p, [layer]: !p[layer] }))}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              padding: '2px 8px',
              background: layers[layer] ? 'rgba(34, 211, 238, 0.05)' : '#070a13',
              border: `1px solid ${layers[layer] ? 'rgba(34, 211, 238, 0.2)' : 'rgba(255,255,255,0.04)'}`,
              borderRadius: '2px',
              color: layers[layer] ? '#22d3ee' : '#4b5563',
              fontWeight: 'bold',
              cursor: 'pointer'
            }}
          >
            <span style={{
              width: '8px',
              height: '8px',
              borderRadius: '1px',
              border: `1px solid ${layers[layer] ? '#22d3ee' : '#4b5563'}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: layers[layer] ? '#22d3ee' : 'transparent'
            }}>
              {layers[layer] && <Check size={6} color="#040711" strokeWidth={5} />}
            </span>
            {layer}
          </button>
        ))}

        {/* Legend Panel */}
        <div style={{ borderLeft: '1px solid rgba(255,255,255,0.08)', paddingLeft: '8px', display: 'flex', alignItems: 'center', gap: '10px', color: '#4b5563', fontFamily: 'var(--cds-font-mono)' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}><i style={{ display: 'inline-block', width: '8px', height: '2px', background: '#a855f7' }} /> VWAP</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}><i style={{ display: 'inline-block', width: '8px', height: '6px', background: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.4)' }} /> Demand VOB</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}><i style={{ display: 'inline-block', width: '8px', height: '6px', background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.3)' }} /> Supply VOB</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}><i style={{ display: 'inline-block', width: '8px', height: '6px', background: 'rgba(34, 211, 238, 0.12)', border: '1px solid rgba(34, 211, 238, 0.4)' }} /> FVG</span>

          <span style={{ borderLeft: '1px solid rgba(255,255,255,0.08)', paddingLeft: '8px', color: fvgs.filter((f: any) => f.price_space === 'UNDERLYING' && (f.lifecycle === 'OPEN' || f.lifecycle === 'PARTIALLY_MITIGATED')).length > 0 ? '#10b981' : '#6b7280' }}>
            {fvgs.filter((f: any) => f.price_space === 'UNDERLYING' && (f.lifecycle === 'OPEN' || f.lifecycle === 'PARTIALLY_MITIGATED')).length > 0 ? 'FVG: ACTIVE' : 'NO ACTIVE FVG'}
          </span>
          <span style={{ borderLeft: '1px solid rgba(255,255,255,0.08)', paddingLeft: '8px', color: vobs.filter((v: any) => v.price_space === 'UNDERLYING' && (v.status === 'ACTIVE' || v.status === 'TESTED')).length > 0 ? '#3b82f6' : '#6b7280' }}>
            {vobs.filter((v: any) => v.price_space === 'UNDERLYING' && (v.status === 'ACTIVE' || v.status === 'TESTED')).length > 0 ? (selectedLane === '1m' ? 'VOB: ACTIVE (3m VOB context)' : 'VOB: ACTIVE') : 'NO ACTIVE VOB'}
          </span>
        </div>
      </div>

      {/* 2.5 COMPACT AMBER BANNER */}
      {(!data?.execution_ready || isInsufficientHistory) && candles.length > 0 && (
        <div style={{
          background: 'rgba(251, 191, 36, 0.08)',
          border: '1px solid rgba(251, 191, 36, 0.25)',
          borderRadius: '4px',
          padding: '8px 12px',
          marginBottom: '8px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: '11px',
          color: '#fbbf24',
          fontFamily: 'var(--cds-font-mono)',
          boxShadow: '0 2px 10px rgba(251, 191, 36, 0.05)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{
              display: 'inline-block',
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              background: '#fbbf24',
              boxShadow: '0 0 8px #fbbf24',
            }} />
            <strong>
              {data?.execution_blocker === 'MARKET_CLOSED'
                ? `EXECUTION BLOCKED — MARKET_CLOSED`
                : `WARMING UP — EXECUTION BLOCKED — ${data?.execution_blocker || 'INSUFFICIENT_HISTORY'} — ${candles.length}/${requiredCount}`}
            </strong>
          </div>
          <div style={{ color: '#fbbf24', opacity: 0.8, fontSize: '10px' }}>
            Source: {data?.warmup_source || (data?.is_replay ? 'Dhan Replay' : 'Dhan Live')} ({data?.warmup_status || 'LOADING'})
            {data?.last_backfill_error && ` | Error: ${data.last_backfill_error}`}
          </div>
        </div>
      )}

      {/* 3. CANVAS OR DATA_UNAVAILABLE VIEWPORT */}
      {candles.length === 0 ? (
        <div style={{
          height: `${totalHeight}px`,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#040711',
          border: '1px solid rgba(239, 68, 68, 0.15)',
          borderRadius: '4px',
          color: '#ef4444',
          fontFamily: 'var(--cds-font-mono)',
          padding: '20px',
          textAlign: 'center',
          gap: '8px'
        }}>
          <div style={{ fontSize: '14px', fontWeight: 'bold', letterSpacing: '1px' }}>DATA_UNAVAILABLE</div>
          <div style={{ fontSize: '11px', color: '#9ca3af', maxWidth: '500px' }}>
            No genuine NIFTY Futures candle data is available from the backend.
          </div>
          
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1.2fr 1fr',
            gap: '6px 16px',
            fontSize: '10px',
            color: '#6b7280',
            background: 'rgba(255,255,255,0.02)',
            padding: '12px 18px',
            borderRadius: '4px',
            border: '1px solid rgba(255,255,255,0.04)',
            marginTop: '8px',
            textAlign: 'left'
          }}>
            <span>Warmup Status:</span> <strong style={{ color: '#fbbf24' }}>{data?.warmup_status || 'NOT_STARTED'}</strong>
            <span>Warmup Source:</span> <strong style={{ color: '#fff' }}>{data?.warmup_source || 'Dhan Intraday API'}</strong>
            <span>Last Attempt:</span> <strong style={{ color: '#fff' }}>{data?.last_backfill_attempt || 'Never'}</strong>
            <span>Error Detail:</span> <strong style={{ color: '#ef4444' }}>{data?.last_backfill_error || 'No candles retrieved (Market Closed or API offline)'}</strong>
          </div>
          
          <button
            onClick={() => void forceSync?.()}
            disabled={syncCooldown}
            style={{
              marginTop: '12px',
              padding: '6px 16px',
              background: syncCooldown ? 'rgba(255,255,255,0.05)' : 'rgba(239, 68, 68, 0.1)',
              border: `1px solid ${syncCooldown ? 'rgba(255,255,255,0.08)' : 'rgba(239, 68, 68, 0.3)'}`,
              color: syncCooldown ? '#4b5563' : '#ef4444',
              borderRadius: '3px',
              fontSize: '10px',
              fontWeight: 'bold',
              cursor: syncCooldown ? 'not-allowed' : 'pointer'
            }}
          >
            {syncStatus === 'loading' ? 'SYNCING...' : syncStatus === 'success' ? 'SYNC SUCCESS' : syncStatus === 'failure' ? 'SYNC FAILED' : 'FORCE SYNC SYSTEM'}
          </button>
        </div>
      ) : (
        <div style={{ position: 'relative', width: '100%', height: `${totalHeight}px` }}>
          {loading && (
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(4,7,17,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10, color: '#22d3ee', fontSize: '11px', fontFamily: 'var(--cds-font-mono)' }}>
              LOADING FITTING SCALES...
            </div>
          )}
          
          <div
            ref={chartContainerRef}
            style={{ 
              width: '100%',
              height: `${totalHeight}px`,
              borderRadius: '4px',
              border: '1px solid rgba(34, 211, 238, 0.15)',
              overflow: 'hidden'
            }}
          />

          {/* FLOATING CROSSHAIR TOOLTIP */}
          {activeHoverCandle && hoverX !== null && hoverY !== null && (
            <div 
              style={{
                position: 'absolute',
                top: '10px',
                left: hoverX > containerWidth / 2 ? '15px' : `${containerWidth - 200}px`,
                width: '180px',
                background: 'rgba(4, 7, 17, 0.95)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: '4px',
                padding: '8px',
                boxShadow: '0 4px 15px rgba(0,0,0,0.5)',
                zIndex: 40,
                fontFamily: 'var(--cds-font-mono)',
                fontSize: '10px',
                color: '#d1d5db',
                pointerEvents: 'none'
              }}
            >
              <div style={{ color: '#fff', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '3px', marginBottom: '5px' }}>
                IST: {new Date(activeHoverCandle.time * 1000).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '3px' }}>
                <span>Open:</span> <strong style={{ color: '#fff' }}>{Number(activeHoverCandle.open).toFixed(1)}</strong>
                <span>High:</span> <strong style={{ color: '#10b981' }}>{Number(activeHoverCandle.high).toFixed(1)}</strong>
                <span>Low:</span> <strong style={{ color: '#ef4444' }}>{Number(activeHoverCandle.low).toFixed(1)}</strong>
                <span>Close:</span> <strong style={{ color: '#fff' }}>{Number(activeHoverCandle.close).toFixed(1)}</strong>
                <span>VWAP:</span> <strong style={{ color: '#a855f7' }}>{activeHoverCandle.vwap !== undefined && activeHoverCandle.vwap !== null ? Number(activeHoverCandle.vwap).toFixed(1) : '—'}</strong>
                <span>Volume:</span> <strong style={{ color: '#fff' }}>{typeof activeHoverCandle.volume === 'number' ? activeHoverCandle.volume.toLocaleString('en-IN') : '—'}</strong>
                <span>OI:</span> <strong style={{ color: '#fff' }}>{typeof activeHoverCandle.oi === 'number' ? activeHoverCandle.oi.toLocaleString('en-IN') : '—'}</strong>
              </div>
            </div>
          )}

          {/* CLICKED TRADE MARKER POPOVER */}
          {selectedTrade && (
            <div 
              style={{
                position: 'absolute',
                top: `${Math.max(10, selectedTrade.y - 135)}px`,
                left: `${Math.min(containerWidth - 300, Math.max(20, selectedTrade.x - 140))}px`,
                width: '270px',
                background: '#090f1d',
                border: '1px solid rgba(245, 158, 11, 0.4)',
                borderRadius: '4px',
                padding: '10px',
                boxShadow: '0 8px 30px rgba(0,0,0,0.8)',
                zIndex: 50
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '4px', marginBottom: '5px' }}>
                <strong style={{ fontSize: '11px', color: '#fbbf24' }}>{selectedTrade.trade.strategy_name}</strong>
                <span style={{ fontSize: '8px', padding: '1px 4px', borderRadius: '2px', background: selectedTrade.trade.direction === 'CALL' ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)', color: selectedTrade.trade.direction === 'CALL' ? '#10b981' : '#ef4444' }}>
                  {selectedTrade.trade.direction}
                </span>
              </div>
              
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 10px', fontSize: '9px', color: '#9ca3af', fontFamily: 'var(--cds-font-mono)' }}>
                <div>
                  <span>Creator:</span> <strong style={{ color: '#fff' }}>{selectedTrade.trade.trade_creator}</strong>
                </div>
                <div>
                  <span>Subtype:</span> <strong style={{ color: '#fff', fontSize: '8px' }}>{selectedTrade.trade.setup_subtype}</strong>
                </div>
                <div>
                  <span>Score:</span> <strong style={{ color: '#22d3ee' }}>{selectedTrade.trade.score} / 100</strong>
                </div>
                <div>
                  <span>Option:</span> <strong style={{ color: '#fff', fontSize: '8px' }}>{selectedTrade.trade.option_contract}</strong>
                </div>
                <div>
                  <span>Entry:</span> <strong style={{ color: '#fff' }}>{selectedTrade.trade.entry}</strong>
                </div>
                <div>
                  <span>SL:</span> <strong style={{ color: '#ef4444' }}>{selectedTrade.trade.structural_sl}</strong>
                </div>
                <div>
                  <span>Target:</span> <strong style={{ color: '#10b981' }}>{selectedTrade.trade.target}</strong>
                </div>
                <div>
                  <span>Guardian:</span> <strong style={{ color: '#fbbf24' }}>{selectedTrade.trade.guardian_action}</strong>
                </div>
              </div>
              
              <button 
                onClick={() => setSelectedTrade(null)} 
                style={{
                  width: '100%',
                  marginTop: '8px',
                  padding: '3px 0',
                  background: 'rgba(255,255,255,0.05)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  color: '#e5e7eb',
                  fontSize: '9px',
                  cursor: 'pointer',
                  borderRadius: '2px'
                }}
              >
                DISMISS
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
