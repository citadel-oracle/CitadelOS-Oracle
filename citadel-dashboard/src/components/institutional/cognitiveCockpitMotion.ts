/** Receipt-driven presentation only. Never infer a model execution from prose or polling. */
export interface ResponseReceipt {
  status?: string
  response_id?: string | null
  updated_at?: string | null
  analyzed_revision?: number | null
}
export function responseReceipt(model?: ResponseReceipt): string {
  if (model?.status !== 'CURRENT' || model.analyzed_revision == null ||
      !model.updated_at || !Number.isFinite(Date.parse(model.updated_at))) return ''
  return `${model.response_id || model.updated_at}:${model.analyzed_revision}`
}

export function animateReceipt(node: HTMLElement | null, previous: string | null, next: string,
  enabled: boolean, reduced: boolean, kind: 'model' | 'state' | 'tension' = 'model') {
  if (!node?.animate || previous === null || !next || previous === next || !enabled || reduced) return []
  const frames: Keyframe[] = kind === 'state' ? [
    { opacity: 0.55, transform: 'translateY(8px)', filter: 'blur(2px)' },
    { opacity: 1, transform: 'translateY(0)', filter: 'blur(0)' },
  ] : [
    { boxShadow: 'inset 0 0 0 1px transparent' },
    { boxShadow: 'inset 0 0 0 1px currentColor, 0 0 28px -12px currentColor', offset: 0.3 },
    { boxShadow: 'inset 0 0 0 1px transparent' },
  ]
  // A connection emits only its travelling packet, never a rectangular card flash.
  const animation = node.dataset?.motionLink === 'true' ? null : node.animate(frames, { duration: kind === 'state' ? 450 : 1300, iterations: 1, easing: 'ease-out' })
  const beams = [...node.querySelectorAll<HTMLElement>('[data-receipt-beam]')].map(beam => {
    const reverse = beam.dataset?.direction === 'reverse'
    const path = beam.dataset?.beamPath != null
    const keyframes: Keyframe[] = path ? [
      { strokeDashoffset: reverse ? -1 : 1, opacity: 0 },
      { opacity: 1, offset: 0.18 },
      { strokeDashoffset: 0, opacity: 1, offset: 0.78 },
      { strokeDashoffset: 0, opacity: 0 },
    ] : [
      { transform: `translateX(${reverse ? '110%' : '-110%'})`, opacity: 0 },
      { transform: 'translateX(0)', opacity: 1, offset: 0.5 },
      { transform: `translateX(${reverse ? '-110%' : '110%'})`, opacity: 0 },
    ]
    return beam.animate(keyframes, { duration: 1300, iterations: 1, easing: 'ease-in-out' })
  })
  return animation ? [animation, ...beams] : beams
}
