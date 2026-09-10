/**
 * @module        @core/api/contracts/envelopes
 * @responsibility Transport envelopes (REST wrapper + WS frame + pagination).
 * @dependencies  none
 * @usedBy        @core/api/http, @core/api/ws, @core/api/adapter
 */
export interface ApiResponse<T> {
  data: T
  meta?: { ts: number; requestId?: string }
}

export interface WsFrame<T = unknown> {
  topic: string
  payload: T
  ts: number
}

export interface Cursor<T> {
  items: T[]
  nextCursor: string | null
  total?: number
}