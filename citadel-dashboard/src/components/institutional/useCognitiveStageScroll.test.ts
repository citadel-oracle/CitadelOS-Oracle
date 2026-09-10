import { describe, expect, it } from 'vitest'
import { COGNITIVE_STAGE_PHASES, cognitiveStageTravel } from './useCognitiveStageScroll'

describe('Cognitive Stage scroll contract', () => {
  it('keeps the corridor short and viewport-scaled', () => {
    expect(cognitiveStageTravel(400)).toBe(620)
    expect(cognitiveStageTravel(720)).toBe(756)
    expect(cognitiveStageTravel(1400)).toBe(980)
  })

  it('reveals one ordered composition rather than separate marketing screens', () => {
    expect(COGNITIVE_STAGE_PHASES).toEqual(['EVIDENCE', 'INSTRUMENTS', 'MODELS', 'TEMPORAL'])
  })
})
