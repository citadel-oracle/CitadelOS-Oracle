// Isolated visual/interaction test. No API client, market owner, or provider is imported.
import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { CognitiveDecisionCore, type CognitiveDecisionCoreProps } from '../../src/components/institutional/CognitiveDecisionCore'

const labels = ['Market closed', 'CALL', 'PUT', 'CALL developing', 'PUT developing', 'NO TRADE', 'Reversal watch', 'Disagreement', 'Gemini unavailable', 'World fresh', 'World unavailable', 'External stale', 'Legacy rejected', 'Model stale', 'Model paused', 'Last valid']
const demoSequence = ['NO TRADE', 'PUT developing', 'PUT', 'Reversal watch', 'CALL developing', 'CALL']
const nativeAnimate = Element.prototype.animate
const motions: string[] = []
Element.prototype.animate = function (...args) {
  const stage = this.closest('[data-motion-stage]')?.getAttribute('data-motion-stage')
  if (stage) {
    motions.push(stage)
    document.dispatchEvent(new CustomEvent('fixture-motion', { detail: [...motions] }))
  }
  return nativeAnimate.apply(this, args)
}

function Preview() {
  const [selected, setSelected] = useState('Market closed')
  const [revision, setRevision] = useState(12)
  const [refreshRevision, setRefreshRevision] = useState(1)
  const [qwenReceipt, setQwenReceipt] = useState(1)
  const [geminiReceipt, setGeminiReceipt] = useState(1)
  const [autoDemo, setAutoDemo] = useState(false)
  const [motionLog, setMotionLog] = useState<string[]>([])
  useEffect(() => {
    const handler = (event: Event) => setMotionLog((event as CustomEvent<string[]>).detail)
    document.addEventListener('fixture-motion', handler)
    return () => document.removeEventListener('fixture-motion', handler)
  }, [])
  useEffect(() => {
    if (!autoDemo) return
    let index = 0
    const timer = window.setInterval(() => {
      setSelected(demoSequence[index % demoSequence.length])
      setRevision(value => value + 1)
      index += 1
    }, 2600)
    return () => window.clearInterval(timer)
  }, [autoDemo])
  const state = selected === 'PUT' || selected === 'Disagreement' ? 'PUT' :
    selected === 'NO TRADE' ? 'NO_TRADE' : selected === 'Reversal watch' ? 'REVERSAL_WATCH' :
    selected === 'CALL developing' ? 'CALL_DEVELOPING' : selected === 'PUT developing' ? 'PUT_DEVELOPING' : 'CALL'
  const closed = ['Market closed', 'Legacy rejected', 'Model stale', 'Model paused', 'Last valid'].includes(selected)
  const stamp = new Date(Date.UTC(2026, 8, 3, 9, 0, revision)).toISOString()
  const receipt = { status: 'CURRENT', analyzed_revision: revision, updated_at: stamp, response_id: `fixture-response-${revision}`, age_seconds: 4 }
  const props: CognitiveDecisionCoreProps = {
    retainedValidation: { status: selected === 'Legacy rejected' ? 'REJECTED' : 'VALID' },
    rejectedHistory: selected === 'Legacy rejected' ? { market_story: 'Aggressive call OI build suggests hidden bullish pressure. HISTORICAL FIXTURE.' } : undefined,
    revision, state, previousState: state === 'PUT' ? 'CALL_DEVELOPING' : 'NO_TRADE',
    marketStatus: closed ? 'OFF_MARKET' : 'LIVE', entryWindow: state.includes('DEVELOPING') ? 'APPROACHING' : ['NO_TRADE', 'REVERSAL_WATCH'].includes(state) ? 'WAIT' : 'READY',
    setupFamily: state === 'NO_TRADE' ? 'TRANSITION / CONFLICT' : 'CONTINUATION',
    whyNow: ['Underlying pressure is improving, but needs follow-through.', 'The same option contract is confirming the latest move.', 'The opposing case remains visible in the evidence.'],
    whatChanged: 'A new response replaced the previous interpretation.',
    watchNext: ['Watch whether the next move holds above the recorded level.'],
    viewBreaksIf: ['The idea weakens if price reverses and the premium stops confirming.'],
    optionBuyerSide: state.includes('PUT') ? 'PUT_FAVOURABLE' : state === 'NO_TRADE' ? 'BOTH_POOR' : 'CALL_FAVOURABLE',
    premiumConfirmation: state === 'NO_TRADE' ? 'DIVERGING' : 'CONFIRMING',
    reversalWatch: { direction: selected === 'Reversal watch' || selected === 'Disagreement' ? 'PUT_TO_CALL' : 'NONE',
      status: selected === 'Reversal watch' ? 'DEVELOPING' : 'NONE', first_contradiction: 'The prior move is losing follow-through.', why_not_confirmed: 'The opposing premium has not confirmed the reversal.' },
    qwenStatus: { ...receipt, response_id: `fixture-qwen-${revision}-${qwenReceipt}`, interpretation: 'The prior move is losing follow-through.', earliest_contradiction: 'Price is no longer extending with the flow.' },
    gptStatus: { ...receipt, status: selected === 'Legacy rejected' ? 'REJECTED' : selected === 'Model stale' ? 'STALE' : selected === 'Model paused' ? 'PAUSED' : selected === 'Last valid' ? 'LAST_VALID' : 'CURRENT', interpretation: 'Keep the current view until the opposing move is confirmed.' },
    geminiStatus: selected === 'Gemini unavailable' ? { status: 'UNAVAILABLE' } : { ...receipt, response_id: `fixture-gemini-${revision}-${geminiReceipt}`, interpretation: 'Premium response is weaker than the underlying move.', challenge: 'Watch for a move without premium confirmation.' },
    agreementStatus: selected === 'Disagreement' ? 'DISAGREEMENT' : 'ALIGNED',
    modelTension: selected === 'Disagreement' ? 'Qwen flags a reversal; GPT has not confirmed it.' : 'The recorded models agree on the current interpretation.',
    fiveHypotheses: { call_continuation: { status: 'SUPPORTED', why: 'Fixture hypothesis — presentation only.' } },
    worldContext: { cockpit: { status: selected === 'External stale' ? 'STALE' : selected === 'World unavailable' ? 'UNAVAILABLE' : 'LIVE',
      refresh_status: selected === 'External stale' ? 'STALE' : 'CURRENT', refresh_receipt_id: `isolated-refresh-${refreshRevision}`,
      last_successful_refresh_at: stamp, poll_cadence_seconds: 300, refresh_age_seconds: 4,
      headline: ['External stale', 'World unavailable'].includes(selected) ? null : {
        headline: 'Visual fixture: a verified event with source and receipt times.', source_name: 'TEST FIXTURE · NOT NEWS',
        published_at_utc: stamp, retrieved_at_utc: stamp, display_status: 'LIVE', age_seconds: 4, verification_status: 'VERIFIED' }, quotes: [] } },
  }
  return <main style={{ maxWidth: 1320, margin: '20px auto', padding: '0 20px', color: '#d4e3e5', fontFamily: 'Arial,sans-serif' }}>
    <header style={{ border: '1px solid #806628', padding: 12, marginBottom: 16, fontSize: 11 }}>
      ISOLATED UI FIXTURES · NOT LIVE MARKET DATA · ZERO PROVIDER CALLS
      <nav style={{ display: 'flex', flexWrap: 'wrap', gap: 7, marginTop: 10 }}>
        {labels.map(label => <button key={label} onClick={() => { setSelected(label); setRevision(value => value + 1) }}
          style={{ background: selected === label ? '#26464a' : '#111b22', border: '1px solid #3d545c', color: '#d5e3e5', padding: '6px 10px', cursor: 'pointer' }}>{label}</button>)}
        <button onClick={() => setRevision(value => value + 1)}>New response</button>
        <button onClick={() => setQwenReceipt(value => value + 1)}>Qwen receipt</button>
        <button onClick={() => setGeminiReceipt(value => value + 1)}>Gemini receipt</button>
        <button onClick={() => setRefreshRevision(value => value + 1)}>External refresh</button>
        <button onClick={() => setAutoDemo(value => !value)}>{autoDemo ? 'Stop auto demo' : 'Start auto demo'}</button>
        <button onClick={() => setMotionLog([...motions])}>Same receipt</button>
      </nav>
      <output aria-label="Animation proof" style={{ display: 'block', marginTop: 8 }}>Actual animate calls: {motionLog.length} · {motionLog.slice(-8).join(' / ') || 'none'}</output>
    </header>
    <section style={{ height: 150, display: 'grid', placeItems: 'center', border: '1px solid #273d42', marginBottom: 12,
      background: 'radial-gradient(ellipse,#12262a,#030607)' }}>LIVING MARKET FORCES · PROTECTED BOUNDARY</section>
    <CognitiveDecisionCore {...props} />
    <section style={{ height: 150, display: 'grid', placeItems: 'center', border: '1px solid #5a3c19', marginTop: 12,
      background: 'radial-gradient(ellipse,#24180b,#030607)' }}>VOB PULLBACK COMMAND · PROTECTED BOUNDARY</section>
  </main>
}
createRoot(document.getElementById('root')!).render(<Preview />)
