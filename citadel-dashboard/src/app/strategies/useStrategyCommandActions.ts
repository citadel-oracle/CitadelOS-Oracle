'use client'

import { useCallback, useState } from 'react'
import { useDashboardActions } from '@/dashboard'

const API_URL = process.env.NEXT_PUBLIC_CITADEL_API_URL ?? 'http://127.0.0.1:8000'

const request = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(`${API_URL}${path}`, {
    cache: 'no-store',
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : body
    const message = detail && typeof detail === 'object' && 'message' in detail
      ? String(detail.message)
      : `Strategies API HTTP ${response.status}`
    throw new Error(message)
  }
  return body as T
}

export function useStrategyCommandActions() {
  const dashboard = useDashboardActions()
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [receipt, setReceipt] = useState<Record<string, unknown> | null>(null)

  const run = useCallback(async <T,>(action: string, operation: () => Promise<T>) => {
    if (busyAction) return null
    setBusyAction(action)
    setError(null)
    try {
      const result = await operation()
      dashboard.refresh()
      return result
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `${action} failed`)
      return null
    } finally {
      setBusyAction(null)
    }
  }, [busyAction, dashboard])

  const saveDraft = useCallback((payload: Record<string, unknown>) => run(
    'SAVE_AS_DRAFT',
    () => request<Record<string, unknown>>('/v1/strategies/deployments/draft', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  ), [run])

  const deploy = useCallback(async (instanceId: string, configurationHash: string) => {
    const result = await run('DEPLOY', () => request<Record<string, unknown>>(
      `/v1/strategies/deployments/${encodeURIComponent(instanceId)}/deploy`,
      { method: 'POST', body: JSON.stringify({ configuration_hash: configurationHash }) },
    ))
    if (result) setReceipt(result)
    return result
  }, [run])

  const duplicate = useCallback((instanceId: string) => run(
    'DUPLICATE_INSTANCE',
    () => request<Record<string, unknown>>(
      `/v1/strategies/deployments/${encodeURIComponent(instanceId)}/duplicate`,
      { method: 'POST', body: '{}' },
    ),
  ), [run])

  const pause = useCallback((instanceId: string) => run(
    'PAUSE',
    () => request<Record<string, unknown>>(
      `/v1/strategies/deployments/${encodeURIComponent(instanceId)}/pause`,
      { method: 'POST' },
    ),
  ), [run])

  const resume = useCallback((instanceId: string) => run(
    'RESUME',
    () => request<Record<string, unknown>>(
      `/v1/strategies/deployments/${encodeURIComponent(instanceId)}/resume`,
      { method: 'POST' },
    ),
  ), [run])

  const rollback = useCallback(async (instanceId: string) => {
    const result = await run('ROLLBACK', () => request<Record<string, unknown>>(
      `/v1/strategies/deployments/${encodeURIComponent(instanceId)}/rollback`,
      { method: 'POST' },
    ))
    if (result) setReceipt(result)
    return result
  }, [run])

  const acknowledge = useCallback((notificationId: string) => run(
    'ACKNOWLEDGE_NOTIFICATION',
    () => request<Record<string, unknown>>(
      `/v1/strategies/notifications/${encodeURIComponent(notificationId)}/acknowledge`,
      { method: 'POST' },
    ),
  ), [run])

  return {
    busyAction,
    error,
    receipt,
    dismissReceipt: () => setReceipt(null),
    showReceipt: (value: Record<string, unknown>) => setReceipt(value),
    saveDraft,
    deploy,
    duplicate,
    pause,
    resume,
    rollback,
    acknowledge,
  }
}
