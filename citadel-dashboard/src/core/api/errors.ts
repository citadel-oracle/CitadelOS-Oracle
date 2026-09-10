/**
 * @module        @core/api/errors
 * @responsibility Canonical error taxonomy for the transport layer.
 * @dependencies  none
 * @usedBy        @core/api/http, @core/api/ws, @core/api/adapter
 */
export class AppError extends Error {
  readonly code: string
  readonly cause?: unknown
  constructor(code: string, message: string, cause?: unknown) {
    super(message)
    this.name = 'AppError'
    this.code = code
    this.cause = cause
  }
}

export class HttpError extends AppError {
  readonly status: number
  readonly body: unknown
  constructor(message: string, status: number, body?: unknown) {
    super('HTTP_ERROR', message)
    this.name = 'HttpError'
    this.status = status
    this.body = body
  }
}

export class WsError extends AppError {
  constructor(message: string, cause?: unknown) {
    super('WS_ERROR', message, cause)
    this.name = 'WsError'
  }
}

export interface RetryPolicy {
  readonly maxAttempts: number
  readonly baseDelayMs: number
  readonly maxDelayMs: number
}

export const defaultRetryPolicy: RetryPolicy = Object.freeze({
  maxAttempts: 3,
  baseDelayMs: 500,
  maxDelayMs:  5000,
})