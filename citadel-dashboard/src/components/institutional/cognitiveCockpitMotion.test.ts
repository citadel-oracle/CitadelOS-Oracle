import { describe, expect, it, vi } from 'vitest'
import { animateReceipt, responseReceipt } from './cognitiveCockpitMotion'

describe('Real response receipt motion', () => {
  const response = { status: 'CURRENT', updated_at: '2026-09-03T09:00:00Z', analyzed_revision: 12, response_id: 'recorded-request-id' }
  it('requires completed output timestamp and revision, never prose or age alone', () => {
    expect(responseReceipt({ status: 'CURRENT', analyzed_revision: 12 })).toBe('')
    expect(responseReceipt({ ...response, status: 'RATE_LIMITED' })).toBe('')
    expect(responseReceipt(response)).toBe('recorded-request-id:12')
  })
  it('fires finite animations on a new receipt, not identical polling or hydration', () => {
    const cancel = vi.fn()
    const animate = vi.fn(() => ({ cancel }))
    const node = { animate, querySelectorAll: () => [{ animate }] } as unknown as HTMLElement
    expect(animateReceipt(node, null, 'r1', true, false)).toEqual([])
    expect(animateReceipt(node, 'r1', 'r1', true, false)).toEqual([])
    const running = animateReceipt(node, 'r1', 'r2', true, false)
    expect(animate).toHaveBeenCalledTimes(2)
    expect(animate.mock.calls.every(call => (call as unknown[])[1] && ((call as unknown[])[1] as KeyframeAnimationOptions).iterations === 1)).toBe(true)
    running.forEach(animation => animation.cancel())
    expect(cancel).toHaveBeenCalledTimes(2)
  })
  it('first response after an unavailable state is a real receipt, not hydration', () => {
    const animate = vi.fn(() => ({ cancel: vi.fn() }))
    const node = { animate, querySelectorAll: () => [] } as unknown as HTMLElement
    expect(animateReceipt(node, '', 'first-real-response', true, false)).toHaveLength(1)
    expect(animateReceipt(node, 'first-real-response', '', true, false)).toEqual([])
    expect(animate).toHaveBeenCalledTimes(1)
  })
  it('connection receipts animate the finite path only, without flashing a rectangular node', () => {
    const animate = vi.fn(() => ({ cancel: vi.fn() }))
    const beam = { animate: vi.fn(() => ({ cancel: vi.fn() })), dataset: { beamPath: '' } }
    const node = { animate, dataset: { motionLink: 'true' }, querySelectorAll: () => [beam] } as unknown as HTMLElement
    expect(animateReceipt(node, 'r1', 'r2', true, false)).toHaveLength(1)
    expect(animate).not.toHaveBeenCalled()
    expect(beam.animate).toHaveBeenCalledWith(expect.any(Array), expect.objectContaining({ iterations: 1 }))
    const frames = (beam.animate.mock.calls[0] as unknown as [Keyframe[]])[0]
    expect(frames[0].strokeDashoffset).toBe(1)
    expect(frames.at(-1)?.strokeDashoffset).toBe(0) // one path length, not two traversals
  })
  it.each([[false, false], [true, true]])('suppresses paused and reduced motion (%s/%s)', (enabled, reduced) => {
    const animate = vi.fn()
    const node = { animate, querySelectorAll: () => [] } as unknown as HTMLElement
    expect(animateReceipt(node, 'r1', 'r2', enabled, reduced)).toEqual([])
    expect(animate).not.toHaveBeenCalled()
  })
})
