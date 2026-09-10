/**
 * @module        @core/api/contracts/primitives
 * @responsibility Universal domain primitives shared by all engines/modules.
 * @dependencies  none
 * @usedBy        every domain module + engine
 */
export type Bias        = 'BULLISH' | 'BEARISH' | 'NEUTRAL'
export type Signal      = 'BUY' | 'SELL' | 'WAIT' | 'AVOID'
export type RiskState   = 'SAFE' | 'CAUTION' | 'LOCKED'
export type TradingMode = 'PAPER' | 'LIVE'
export type Tone        = 'bull' | 'bear' | 'warn' | 'neutral' | 'purple' | 'blue'

export interface ResourceState<T> {
  data: T | null
  loading: boolean
  error: Error | null
  connected: boolean
}