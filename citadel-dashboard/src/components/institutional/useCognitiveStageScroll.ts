'use client'

import { type RefObject, useEffect } from 'react'

export const COGNITIVE_STAGE_PHASES = [
  'EVIDENCE',
  'INSTRUMENTS',
  'MODELS',
  'TEMPORAL',
] as const

/** A short presentation corridor, bounded to roughly one viewport of native scroll. */
export function cognitiveStageTravel(viewportHeight: number): number {
  return Math.round(Math.min(980, Math.max(620, viewportHeight * 1.05)))
}

/**
 * Scroll is presentation only. Canonical props update React immediately and never
 * depend on this timeline. GSAP owns compositor transforms without frame-by-frame
 * React state, and the context is fully reverted on remount/navigation.
 */
export function useCognitiveStageScroll(rootRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = rootRef.current
    if (!root || typeof window === 'undefined') return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    const desktop = window.matchMedia('(min-width: 1024px) and (min-height: 800px)')
    if (reduced.matches || !desktop.matches) {
      root.dataset.scrollMode = 'static'
      return
    }

    let cancelled = false
    let revert: (() => void) | undefined
    root.dataset.scrollMode = 'loading'

    void Promise.all([import('gsap'), import('gsap/ScrollTrigger')]).then(([gsapModule, triggerModule]) => {
      if (cancelled || !rootRef.current) return
      const gsap = gsapModule.gsap
      const ScrollTrigger = triggerModule.ScrollTrigger
      gsap.registerPlugin(ScrollTrigger)

      const context = gsap.context(() => {
        const viewport = root.querySelector<HTMLElement>('[data-cognitive-stage-viewport]')
        if (!viewport) return

        const timeline = gsap.timeline({
          defaults: { ease: 'power2.out' },
          scrollTrigger: {
            id: 'citadel-cognitive-stage',
            trigger: root,
            start: 'top 85%',
            end: 'bottom 40%',
            scrub: 0.4,
            fastScrollEnd: true,
            invalidateOnRefresh: true,
          },
        })

        timeline
          .fromTo('[data-scroll-phase="CORE"]', { scale: 0.96, autoAlpha: 0.85 },
            { scale: 1, autoAlpha: 1, duration: 0.6 }, 0)
          .fromTo('[data-scroll-phase="EVIDENCE"]', { x: -16, autoAlpha: 0.75 },
            { x: 0, autoAlpha: 1, duration: 0.6 }, 0.08)
          .fromTo('[data-scroll-phase="INSTRUMENTS"]', { x: 16, autoAlpha: 0.75 },
            { x: 0, autoAlpha: 1, duration: 0.6 }, 0.08)
          .fromTo('[data-scroll-phase="TEMPORAL"]', { y: 14, autoAlpha: 0.7 },
            { y: 0, autoAlpha: 1, duration: 0.6 }, 0.25)

        root.dataset.scrollMode = 'cinematic'
        root.dataset.scrollTriggerId = 'citadel-cognitive-stage'
      }, root)

      revert = () => {
        context.revert()
        delete root.dataset.scrollTriggerId
      }
    }).catch(() => {
      // Static content remains fully usable if the presentation engine cannot load.
      root.dataset.scrollMode = 'static'
    })

    return () => {
      cancelled = true
      revert?.()
    }
  }, [rootRef])
}
