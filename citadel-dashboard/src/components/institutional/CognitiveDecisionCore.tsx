'use client'

import React, { memo, useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import styles from './CognitiveDecisionCore.module.css'
import { animateReceipt, responseReceipt } from './cognitiveCockpitMotion'
import { useCognitiveStageScroll } from './useCognitiveStageScroll'
import type { OracleDeterministicSensors } from './oracleDeterministicSensors'
import { CitadelLiveIsland } from './CitadelLiveIsland'

/** Preserve the complete accepted wording; never paraphrase a model's caveats away. */
function GlanceRead({ text }: { text: string }) {
  return <details className={styles.glanceRead}>
    <summary><span>{text}</span><small>Full read</small></summary>
    <p>{text}</p>
  </details>
}

export interface CognitiveModelView {
  age_seconds?: number | null
  response_id?: string | null
  reason?: string | null
  status?: string
  analyzed_revision?: number | null
  updated_at?: string | null
  continuation_status?: string
  earliest_contradiction?: string
  interpretation?: string
  challenge?: string
  reversal_risk?: string
  latency_ms?: number
  tokens?: number
  cached_tokens?: number
  model_id?: string
}

export interface GeminiScoutView {
  model_id?: string
  role?: string
  status?: string
  semantic_state?: 'POSSIBLE_REVERSAL' | 'FLOW_SHIFT' | 'FAILED_PRESSURE' | 'ABSORPTION' | 'CONTROL_STABLE' | 'UNKNOWN' | string
  headline?: string
  bullets?: string[]
  missing_evidence?: string[]
  deserves_luna_review?: boolean
  unsupported_inference_flag?: boolean
  unsupported_inference_reason?: string | null
  age_seconds?: number | null
  updated_at?: string | null
  receipt_id?: string | null
  revision?: number | null
  in_flight?: boolean
  paused?: boolean
  pause_reason?: string
  display_status?: string
}

export interface SolOptionSpecialistView {
  model_id?: string
  role?: string
  status?: string
  buying_state?: 'CALL_ATTRACTIVE' | 'PUT_ATTRACTIVE' | 'WAIT' | 'AVOID_CHASE' | 'UNRESOLVED' | string
  headline?: string
  bullets?: string[]
  missing_evidence?: string[]
  direction_vs_trade_quality_conflict?: boolean
  age_seconds?: number | null
  updated_at?: string | null
  receipt_id?: string | null
  revision?: number | null
  in_flight?: boolean
  paused?: boolean
  pause_reason?: string
  display_status?: string
  readiness_checklist?: Record<string, any>
}

export interface CockpitWorldContext {
  cockpit?: {
    status: string
    refresh_status?: string
    refresh_receipt_id?: string | null
    last_successful_refresh_at?: string | null
    refresh_age_seconds?: number | null
    poll_cadence_seconds?: number
    unavailable_reason?: string | null
    headline?: {
      headline: string
      source_name: string
      display_status: string
      verification_status: string
      published_at_utc?: string
      retrieved_at_utc?: string
      age_seconds?: number | null
    } | null
    top_stories?: Array<{
      event_id: string
      headline: string
      summary?: string
      country?: string
      source_name: string
      display_status: string
      verification_status: string
      published_at_utc?: string
      retrieved_at_utc?: string
      age_seconds?: number | null
    }>
    quotes?: Array<{
      symbol: string
      price: number | null
      exact_or_proxy?: string
      provider?: string
      display_status: string
      verification_status: string
      published_at_utc?: string
      retrieved_at_utc?: string
      age_seconds?: number | null
    }>
  }
  health?: { last_poll_at?: string; poll_cadence_seconds?: number; running?: boolean }
  events?: Array<{
    event_id: string
    headline: string
    summary?: string
    source_name?: string
    published_at?: string
    retrieved_at?: string
    verification_status?: string
    verification_tier?: string
    freshness?: string
    event_type?: string
    scheduled_at?: string
    country?: string
  }>
  quotes?: Array<{
    symbol: string
    display_name?: string
    price?: number | null
    change_percent?: number | null
    exact_or_proxy?: string
    proxy_for?: string
    data_age?: string
    market_status?: string
    provider?: string
    provider_timestamp?: string
    retrieved_at?: string
  }>
}

interface OptionContract {
  strike: number
  securityId: string
  ltp: number | null
  sameContractDelta?: number | null
  spread?: number | null
  iv?: number | null
}

export interface CognitiveDecisionCoreProps {
  acceptedInputReceipt?: {
    receipt_id: string; model: string; session_id: string; revision: number; cutoff: string
    payload: {
      current_facts?: Record<string, { value: string | number | boolean | null; evidence_id: string | null; source_time: string | null; availability: string }>
      timeline?: unknown[]; previous_model_view?: unknown
    }
  } | null
  retainedValidation?: { status: string; reason?: string | null }
  rejectedHistory?: Record<string, unknown> | null
  revision?: number
  state?: string | null
  entryWindow?: string | null
  marketStatus?: string
  transportUnavailable?: boolean
  marketDataUnavailable?: boolean
  whyNow?: string[]
  reversalWatch?: {
    direction?: string
    status?: string
    first_contradiction?: string
    what_failed?: string
    premium_confirmation?: string
    why_not_confirmed?: string
    what_still_opposes?: string
    invalidation_pivot?: number | string | null
    trigger_level?: number | string | null
  }
  optionBuyerSide?: string | null
  premiumConfirmation?: string | null
  modelTension?: string | null
  callContract?: OptionContract
  putContract?: OptionContract
  fiveHypotheses?: Record<string, { status: string; plausibility?: string; why?: string; premium_confirmation?: string } | string>
  qwenStatus?: CognitiveModelView
  gptStatus?: CognitiveModelView
  geminiStatus?: CognitiveModelView
  geminiScout?: GeminiScoutView
  solSpecialist?: SolOptionSpecialistView
  unseenEventsCount?: number
  whatChanged?: string
  evidenceReferences?: string[]
  previousState?: string | null
  setupFamily?: string | null
  agreementStatus?: string
  watchNext?: string[]
  viewBreaksIf?: string[]
  missingConfirmation?: string[]
  thesisEvolution?: string | null
  opportunityMaturity?: string | null
  worldContext?: CockpitWorldContext
  deterministicSensors?: OracleDeterministicSensors | null
  snapshot?: {
    spot_ltp?: number | null; futures_ltp?: number | null; futures_basis?: number | null
    atm_strike?: number | null; atm_iv?: number | null; skew_25d?: number | null
    vwap?: number | null; zero_gamma?: number | null; pcr_oi?: number | null
    max_pain?: number | null; net_gex?: number | null; sudden_oi?: number | null
    buildup?: string | null; dealer_regime?: string | null
    india_vix?: number | null
    kinematics?: { velocity?: number | string | null; acceleration?: number | string | null; concentration?: number | null }
  } | null
}

const STATES: Record<string, { label: string; tone: string }> = {
  CALL: { label: 'CALL', tone: 'call' },
  CALL_DEVELOPING: { label: 'CALL', tone: 'call' },
  PUT: { label: 'PUT', tone: 'put' },
  PUT_DEVELOPING: { label: 'PUT', tone: 'put' },
  WAIT: { label: 'WAIT', tone: 'wait' },
  NO_TRADE: { label: 'NO TRADE', tone: 'wait' },
  REVERSAL_WATCH: { label: 'REVERSAL WATCH', tone: 'wait' },
}

const human = (value?: string | null) => value?.replaceAll('_', ' ') || 'UNAVAILABLE'
const numeric = (value?: number | null, digits = 2) =>
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
const formatNumber = (value?: number | null, decimals = 2, signed = false): string => {
  if (value == null || !Number.isFinite(value)) return '—'
  const prefix = signed && value > 0 ? '+' : ''
  return `${prefix}${value.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`
}

const formatFactValue = (key: string, rawVal: unknown): string => {
  if (rawVal == null) return 'UNAVAILABLE'
  if (typeof rawVal === 'number' && Number.isFinite(rawVal)) {
    if (key === 'basis') {
      const prefix = rawVal > 0 ? '+' : ''
      return `${prefix}${rawVal.toFixed(2)} pts`
    }
    if (key === 'spot_price' || key === 'futures_price' || key === 'session_vwap' || key === 'zero_gamma') {
      return rawVal.toFixed(2)
    }
    if (key === 'ce_atm_premium' || key === 'pe_atm_premium' || key === 'straddle_price') {
      return rawVal.toFixed(2)
    }
    if (key === 'atm_iv') {
      return `${rawVal.toFixed(2)}%`
    }
    if (key === 'pcr_oi') {
      return rawVal.toFixed(2)
    }
    if (key === 'total_net_gex_inr_cr') {
      return `${rawVal > 0 ? '+' : ''}₹${rawVal.toFixed(2)}Cr`
    }
    if (key === 'skew_25d' || key === 'skew_10d' || key === 'mlofi_5l') {
      const prefix = rawVal > 0 ? '+' : ''
      return `${prefix}${rawVal.toFixed(2)}`
    }
    if (key === 'cvd') {
      const prefix = rawVal > 0 ? '+' : ''
      return `${prefix}${Math.round(rawVal)}`
    }
    if (key === 'atm_strike') {
      return String(Math.round(rawVal))
    }
    return String(rawVal)
  }
  return String(rawVal)
}

const plain = (value?: string | null, fallback = 'Not supplied') =>
  !value || ['NONE', 'UNRESOLVED', 'NOT_APPLICABLE'].includes(value.toUpperCase()) ? fallback : human(value)

export interface ExtractedEvidenceItem {
  id: string
  rawId: string
  eventType: string
  instrument: string
  timestamp?: string
  rawValue?: string
}

export function sanitizeProseAndExtractEvidence(text: string): {
  cleanText: string
  evidence: ExtractedEvidenceItem[]
} {
  if (!text) return { cleanText: '', evidence: [] }
  const evidence: ExtractedEvidenceItem[] = []

  // Extract bracketed raw event IDs: e.g. [evt_... evt_...]
  const cleanText = text
    .replace(/\[\s*(evt_[^\]]+)\s*\]/g, (_match, inner) => {
      const rawIds = inner.trim().split(/\s+/)
      for (const raw of rawIds) {
        if (!raw.startsWith('evt_')) continue
        const parts = raw.split('_')
        const baseId = parts[0] + '_' + (parts[1] || '').substring(0, 16)
        let eventType = 'MARKET_EVENT'
        let instrument = 'NIFTY'
        if (raw.includes('SPOT_MOVE')) {
          eventType = 'SPOT_MOVE'
          instrument = 'NIFTY INDEX'
        } else if (raw.includes('FUTURES_MOVE')) {
          eventType = 'FUTURES_MOVE'
          instrument = 'NIFTY FUTURES'
        } else if (raw.includes('SENSORIUM_DELTA')) {
          eventType = 'SENSORIUM_DELTA'
          instrument = 'NIFTY SENSORIUM'
        } else if (raw.includes('CLOSED_OI_BUILDUP')) {
          eventType = 'CLOSED_OI_BUILDUP'
          instrument = parts.slice(4, 7).join(' ') || 'OPTION STRIKE'
        } else if (raw.includes('CLOSED_OI_DELTA')) {
          eventType = 'CLOSED_OI_DELTA'
          instrument = parts.slice(4, 7).join(' ') || 'OPTION STRIKE'
        } else if (raw.includes('BASIS_SHIFT')) {
          eventType = 'BASIS_SHIFT'
          instrument = 'NIFTY BASIS'
        } else if (raw.includes('STRADDLE_CHANGE')) {
          eventType = 'STRADDLE_CHANGE'
          instrument = 'NIFTY STRADDLE'
        } else if (raw.includes('VOLATILITY_SURFACE_SHIFT')) {
          eventType = 'VOLATILITY_SURFACE_SHIFT'
          instrument = 'VOL SURFACE'
        }
        evidence.push({
          id: baseId,
          rawId: raw,
          eventType,
          instrument,
        })
      }
      return ''
    })
    .replace(/\[\s*(?:(?:metric|rel|coverage|sensor|provenance|fact|evidence):|evt_|token:)[^\]]*\]/gi, '')
    .replace(/\s+([.,;:!?])/g, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim()

  return { cleanText, evidence }
}

/** Presentation only: no age thresholds or state/readiness inference from market numbers. */
export function cognitivePresentation(props: CognitiveDecisionCoreProps) {
  const explicit = props.state ? STATES[props.state] : undefined
  const marketCurrent = props.marketStatus === 'LIVE' || props.marketStatus === 'HEALTHY'
  const providerCurrent = props.gptStatus?.status === 'CURRENT'
  const revisionMatches =
    props.revision != null &&
    props.gptStatus?.analyzed_revision != null &&
    props.revision === props.gptStatus.analyzed_revision
  const validated = props.retainedValidation?.status === 'VALID'
  const current = Boolean(
    validated &&
      explicit &&
      marketCurrent &&
      providerCurrent &&
      revisionMatches &&
      !props.transportUnavailable &&
      !props.marketDataUnavailable
  )
  const closed = ['OFF_MARKET', 'MARKET_CLOSED', 'SESSION_LAST'].includes(props.marketStatus || '')
  const isSessionLast = Boolean(
    !current &&
      !props.transportUnavailable &&
      !props.marketDataUnavailable &&
      (props.gptStatus?.status === 'SESSION_LAST' || props.marketStatus === 'SESSION_LAST' || closed) &&
      explicit
  )
  const isUpdating = Boolean(
    !current &&
      !isSessionLast &&
      !props.transportUnavailable &&
      !props.marketDataUnavailable &&
      validated &&
      explicit &&
      (props.gptStatus?.status === 'UPDATING' || props.gptStatus?.status === 'IN_FLIGHT')
  )
  return {
    current,
    isSessionLast,
    isUpdating,
    label: (isSessionLast || current || isUpdating) ? explicit!.label : 'UNAVAILABLE',
    tone: (isSessionLast || current || isUpdating) ? explicit!.tone : 'unavailable',
    context: props.marketDataUnavailable
      ? 'MARKET DATA UNAVAILABLE · LIVE-DATA PENDING'
      : props.transportUnavailable
      ? 'CONNECTION LOST'
      : isSessionLast
      ? (props.marketStatus === 'OFF_MARKET' || props.marketStatus === 'MARKET_CLOSED' ? 'MARKET CLOSED' : 'SESSION LAST')
      : isUpdating
      ? 'UPDATING · LAST ACCEPTED READ'
      : closed
      ? 'MARKET CLOSED'
      : !validated
      ? props.retainedValidation?.status === 'REJECTED'
        ? 'ANALYSIS REJECTED'
        : 'ANALYSIS NOT VALIDATED'
      : !revisionMatches
      ? 'REVISION MISMATCH'
      : !providerCurrent
      ? human(props.gptStatus?.status)
      : human(props.marketStatus),
    lastKnown: validated && !current ? explicit?.label : undefined,
    entry: (current || isSessionLast || isUpdating) && props.entryWindow ? human(props.entryWindow) : 'UNAVAILABLE',
  }
}

function useReceiptPulse(identity: string, enabled: boolean, kind: 'model' | 'state' | 'tension' = 'model') {
  const ref = useRef<HTMLDivElement>(null)
  const previous = useRef<string | null>(null)
  const reduced = useReducedMotion()
  useEffect(() => {
    const animations = animateReceipt(ref.current, previous.current, identity, enabled, Boolean(reduced), kind)
    previous.current = identity
    return () => animations.forEach((animation) => animation.cancel())
  }, [identity, enabled, reduced, kind])
  return ref
}

const timeLabel = (value?: string | null) => {
  if (!value || !Number.isFinite(Date.parse(value))) return 'TIME NOT REPORTED'
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value} · TIME NOT REPORTED`
  return (
    new Intl.DateTimeFormat('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      day: '2-digit',
      month: 'short',
    }).format(new Date(value)) + ' IST'
  )
}

const clockLabel = (value: string) =>
  new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))

export interface CognitiveTimelineEvent {
  id: string
  at: string
  source: string
  label: string
}

/** Sparse by design: only timestamped accepted/current outputs and verified context appear. */
export function buildCognitiveTimeline(props: CognitiveDecisionCoreProps): CognitiveTimelineEvent[] {
  const events: CognitiveTimelineEvent[] = []
  const addModel = (source: string, model?: CognitiveModelView) => {
    if (!model?.updated_at || !Number.isFinite(Date.parse(model.updated_at))) return
    if (!['CURRENT', 'LAST_VALID', 'SESSION_LAST'].includes(model.status || '')) return
    const rawLabel = model.interpretation || model.continuation_status
    const cleanLabel = rawLabel ? sanitizeProseAndExtractEvidence(rawLabel).cleanText : undefined
    events.push({
      id: `${source}:${responseReceipt(model) || model.updated_at}`,
      at: model.updated_at,
      source,
      label: plain(cleanLabel, `${source} analysis accepted`),
    })
  }
  addModel('QWEN', props.qwenStatus)
  addModel('GPT', props.gptStatus)
  addModel('GEMINI', props.geminiStatus)
  const headline = props.worldContext?.cockpit?.headline
  if (
    headline?.verification_status === 'VERIFIED' &&
    headline.retrieved_at_utc &&
    Number.isFinite(Date.parse(headline.retrieved_at_utc)) &&
    ['LIVE', 'SESSION_LAST'].includes(headline.display_status)
  ) {
    events.push({
      id: `WORLD:${headline.retrieved_at_utc}:${headline.headline}`,
      at: headline.retrieved_at_utc,
      source: 'WORLD',
      label: headline.headline,
    })
  }
  return events.sort((a, b) => Date.parse(a.at) - Date.parse(b.at)).slice(-5)
}

export function verifiedWorldReceiptEligible(context?: CockpitWorldContext['cockpit']): boolean {
  if (!context || !['LIVE', 'SESSION_LAST'].includes(context.status) || context.refresh_status !== 'CURRENT')
    return false
  const verifiedHeadline =
    context.headline?.verification_status === 'VERIFIED' &&
    ['LIVE', 'SESSION_LAST'].includes(context.headline.display_status)
  const verifiedQuote = (context.quotes || []).some(
    (quote) =>
      quote.verification_status === 'VERIFIED' && ['LIVE', 'SESSION_LAST'].includes(quote.display_status)
  )
  return Boolean(verifiedHeadline || verifiedQuote)
}

export function CognitiveDrawer({
  title,
  meta,
  children,
}: {
  title: string
  meta?: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const id = React.useId()
  const reduced = useReducedMotion()
  return (
    <section className={styles.drawer} data-open={open}>
      <button
        type="button"
        className={styles.drawerTrigger}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={styles.drawerTitle}>{title}</span>
        <span className={styles.drawerMeta}>{meta}</span>
        <span className={styles.chevron} aria-hidden="true">
          +
        </span>
      </button>
      <motion.div
        id={id}
        initial={false}
        animate={{ height: open ? 'auto' : 0, opacity: open ? 1 : 0 }}
        transition={{ duration: reduced ? 0 : 0.22, ease: 'easeOut' }}
        className={styles.drawerClip}
        inert={!open}
        aria-hidden={!open}
      >
        <div className={styles.drawerBody}>{children}</div>
      </motion.div>
    </section>
  )
}



const cleanStorySummary = (val?: string | null) => {
  if (!val) return null
  const cleaned = val
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&#8377;/g, '₹')
    .replace(/\s+/g, ' ')
    .trim()
  if (!cleaned || cleaned.length < 10 || cleaned.startsWith('Auction Results') || cleaned.startsWith('T-Bill')) {
    return null
  }
  return cleaned.length > 140 ? `${cleaned.slice(0, 140)}…` : cleaned
}

const ContextStrip = memo(function ContextStrip({ world }: { world?: CockpitWorldContext }) {
  const context = world?.cockpit
  const usable = context && ['LIVE', 'SESSION_LAST'].includes(context.status) && context.refresh_status === 'CURRENT'
  const latest =
    usable &&
    context.headline?.verification_status === 'VERIFIED' &&
    ['LIVE', 'SESSION_LAST'].includes(context.headline.display_status)
      ? context.headline
      : null
  const stories = usable
    ? context.top_stories
        ?.filter(
          (story) =>
            story.verification_status === 'VERIFIED' && ['LIVE', 'SESSION_LAST'].includes(story.display_status)
        )
        .slice(0, 2)
    : []
  const quotes = usable
    ? (context.quotes || []).filter(
        (quote) =>
          quote.verification_status === 'VERIFIED' &&
          ['LIVE', 'SESSION_LAST'].includes(quote.display_status) &&
          ['USD/INR', 'BTC/USD', 'SPY', 'QQQ'].includes(quote.symbol)
      )
    : []
  const refreshRef = useReceiptPulse(context?.refresh_receipt_id || '', verifiedWorldReceiptEligible(context))
  const age = (seconds?: number | null) =>
    typeof seconds === 'number' ? `${Math.floor(seconds / 60)}m old` : 'AGE UNKNOWN'
  return (
    <section ref={refreshRef} className={styles.contextStrip} aria-label="Global context brief" data-motion-stage="EXTERNAL_REFRESH">
      <div className={styles.contextLabel}>
        <span>WORLD CONTEXT</span>
        <b>{human(context?.status)}</b>
      </div>
      <div className={styles.contextHeadline}>
        {stories?.length ? (
          stories.map((story) => (
            <article key={story.event_id}>
              <small>
                {story.country === 'IN' ? 'INDIA' : 'GLOBAL'} · VERIFIED · {story.source_name} · {human(story.display_status)}
              </small>
              <p>{story.headline}</p>
              <time>
                {timeLabel(story.published_at_utc)} · {age(story.age_seconds)}
              </time>
              {cleanStorySummary(story.summary) ? <span>{cleanStorySummary(story.summary)}</span> : null}
            </article>
          ))
        ) : (
          <>
            <small>
              {stories === undefined && latest
                ? `VERIFIED · ${latest.source_name} · ${human(latest.display_status)}`
                : 'NO VERIFIED CURRENT HEADLINE'}
            </small>
            <p>
              {stories === undefined
                ? latest?.headline || context?.unavailable_reason
                : context?.unavailable_reason || 'No verified relevant story from today. Source details remain available.'}
            </p>
          </>
        )}
      </div>
      <div className={styles.contextQuotes}>
        {quotes.length ? (
          quotes.map((quote) => (
            <div key={quote.symbol}>
              <span>
                {quote.symbol}
                <small>{quote.exact_or_proxy || 'TYPE UNKNOWN'}</small>
              </span>
              <strong>{numeric(quote.price)}</strong>
              <em>
                {human(quote.display_status)} · {age(quote.age_seconds)}
              </em>
            </div>
          ))
        ) : (
          <span>Verified global quotes unavailable</span>
        )}
      </div>
    </section>
  )
})

export const CognitiveDecisionCore = memo(function CognitiveDecisionCore(input: CognitiveDecisionCoreProps) {
  const reduced = useReducedMotion()
  const rootRef = useRef<HTMLElement>(null)
  useCognitiveStageScroll(rootRef)

  const approved = input.retainedValidation?.status === 'VALID'
  const rejected = input.retainedValidation?.status === 'REJECTED'
  const muteModel = (model?: CognitiveModelView): CognitiveModelView | undefined =>
    model
      ? {
          ...model,
          status: rejected && (model.interpretation || model.status === 'REJECTED') ? 'REJECTED' : 'UNAVAILABLE',
          interpretation: undefined,
          continuation_status: undefined,
          challenge: undefined,
          earliest_contradiction: undefined,
        }
      : undefined

  const props: CognitiveDecisionCoreProps = approved
    ? input
    : {
        ...input,
        state: null,
        entryWindow: null,
        whyNow: [],
        whatChanged: undefined,
        watchNext: [],
        viewBreaksIf: [],
        missingConfirmation: [],
        previousState: null,
        optionBuyerSide: null,
        premiumConfirmation: null,
        reversalWatch: undefined,
        fiveHypotheses: {},
        modelTension: null,
        agreementStatus: 'UNAVAILABLE',
        thesisEvolution: undefined,
        opportunityMaturity: undefined,
        qwenStatus: muteModel(input.qwenStatus),
        gptStatus: muteModel(input.gptStatus),
        geminiStatus: muteModel(input.geminiStatus),
      }

  const p = cognitivePresentation(props)
  const isCurrentRead = p.current
  const closed = p.context === 'MARKET CLOSED'
  const primaryReceipt = approved && input.acceptedInputReceipt?.revision === input.revision ? responseReceipt(props.gptStatus) : ''
  const stateRef = useReceiptPulse(primaryReceipt ? props.state || '' : '', p.current, 'state')
  const receipt = approved && input.acceptedInputReceipt?.revision === input.revision
    ? input.acceptedInputReceipt : null
  const facts = receipt?.payload.current_facts ?? {}
  const numberFact = (key: string) => typeof facts[key]?.value === 'number' ? facts[key].value as number : null
  const snapshot = {
    futures_basis: numberFact('basis'),
    net_gex: numberFact('total_net_gex_inr_cr'),
    india_vix: numberFact('india_vix'),
  }
  const atmStrikeVal = typeof facts['atm_strike']?.value === 'number'
    ? Math.round(facts['atm_strike'].value as number)
    : null
  const receivedContract = (side: 'ce' | 'pe'): OptionContract | undefined => {
    const securityId = facts[`${side}_atm_security_id`]?.value
    const strike = numberFact('atm_strike')
    return securityId != null && strike != null
      ? { securityId: String(securityId), strike, ltp: numberFact(`${side}_atm_premium`) }
      : undefined
  }

  // Multi-Model Live Shadow Presentation (V1.3)
  const fallbackLabel = receipt ? 'STANDBY · NO CURRENT READ' : 'NO ACCEPTED INPUT RECEIPT'
  const fallbackGeminiHeadline = receipt ? 'No current Gemini Fast Scout read.' : 'No accepted input receipt recorded.'
  const fallbackSolHeadline = receipt ? 'No current Sol Option Specialist read.' : 'No accepted input receipt recorded.'

  const isGeminiPaused = props.geminiScout?.paused === true
  const isGeminiInFlight = !isGeminiPaused && props.geminiScout?.in_flight === true
  const isSolPaused = props.solSpecialist?.paused === true
  const isSolInFlight = !isSolPaused && props.solSpecialist?.in_flight === true

  const geminiState = props.geminiScout?.semantic_state || (receipt ? 'STANDBY' : 'UNAVAILABLE')
  const geminiHeadline = props.geminiScout?.headline || fallbackGeminiHeadline
  const geminiBullets = (props.geminiScout?.bullets && props.geminiScout.bullets.length > 0)
    ? props.geminiScout.bullets
    : []
  const geminiMissing = props.geminiScout?.missing_evidence || []
  const geminiAge = props.geminiScout?.age_seconds
  const geminiFreshnessLabel = isGeminiPaused
    ? (geminiAge != null ? `HISTORICAL · ${Math.round(geminiAge)}S AGO` : 'HISTORICAL CONTEXT ONLY')
    : isGeminiInFlight
    ? 'IN FLIGHT · WAITING FOR RUNTIME EMISSION'
    : geminiAge != null
    ? (props.geminiScout?.status === 'STALE' ? `STALE · ${Math.round(geminiAge)}S AGO` : `UPDATED ${Math.round(geminiAge)}S AGO`)
    : (props.geminiScout?.status ? human(props.geminiScout.status) : fallbackLabel)
  const geminiTone = isGeminiPaused
    ? 'amber'
    : (geminiState === 'POSSIBLE_REVERSAL' || geminiState === 'FAILED_PRESSURE')
    ? 'amber'
    : (geminiState === 'FLOW_SHIFT' || geminiState === 'ABSORPTION')
    ? 'cyan'
    : 'neutral'
  const geminiPillLabel = isGeminiPaused
    ? (props.geminiScout?.display_status || 'PAUSED · INPUT/ARCHITECTURE HARDENING')
    : isGeminiInFlight
    ? 'IN FLIGHT'
    : props.geminiScout?.semantic_state
    ? (props.geminiScout.status === 'STALE' ? `${human(props.geminiScout.semantic_state)} · STALE` : human(props.geminiScout.semantic_state))
    : (props.geminiScout?.status ? human(props.geminiScout.status) : (receipt ? 'STANDBY · NO CURRENT READ' : 'UNAVAILABLE'))

  const solState = props.solSpecialist?.buying_state || (receipt ? 'STANDBY' : 'UNAVAILABLE')
  const solHeadline = props.solSpecialist?.headline || fallbackSolHeadline
  const solBullets = (props.solSpecialist?.bullets && props.solSpecialist.bullets.length > 0)
    ? props.solSpecialist.bullets
    : []
  const solMissing = props.solSpecialist?.missing_evidence || []
  const solAge = props.solSpecialist?.age_seconds
  const solFreshnessLabel = isSolPaused
    ? (solAge != null ? `HISTORICAL · ${Math.round(solAge)}S AGO` : 'HISTORICAL CONTEXT ONLY')
    : isSolInFlight
    ? 'IN FLIGHT · WAITING FOR RUNTIME EMISSION'
    : solAge != null
    ? (props.solSpecialist?.status === 'STALE' ? `STALE · ${Math.round(solAge)}S AGO` : `UPDATED ${Math.round(solAge)}S AGO`)
    : (props.solSpecialist?.status ? human(props.solSpecialist.status) : fallbackLabel)
  const solTone = isSolPaused
    ? 'amber'
    : (solState === 'CALL_ATTRACTIVE')
    ? 'green'
    : (solState === 'PUT_ATTRACTIVE')
    ? 'red'
    : (solState === 'AVOID_CHASE')
    ? 'amber'
    : 'neutral'
  const solPillLabel = isSolPaused
    ? (props.solSpecialist?.display_status || 'PAUSED · INPUT HARDENING')
    : isSolInFlight
    ? 'IN FLIGHT'
    : props.solSpecialist?.buying_state
    ? (props.solSpecialist.status === 'STALE' ? `${human(props.solSpecialist.buying_state)} · STALE` : human(props.solSpecialist.buying_state))
    : (props.solSpecialist?.status ? human(props.solSpecialist.status) : (receipt ? 'STANDBY · NO CURRENT READ' : 'UNAVAILABLE'))

  // Compatibility invariants for Phase 1/2 Evidence Purity

  // Competing Hypotheses helper: strictly derived from Luna output, never inferred from state
  const getHypothesisStatus = (id: string): string => {
    if (!props.fiveHypotheses) return 'UNREPORTED'
    const entry =
      props.fiveHypotheses[id] ||
      (id === 'NOISE' ? props.fiveHypotheses['CHOP'] || props.fiveHypotheses['NO_TRADE'] : undefined)
    if (!entry) return 'UNREPORTED'
    const rawStatus = typeof entry === 'string' ? entry : entry.status || entry.plausibility
    if (!rawStatus) return 'UNREPORTED'
    const upper = String(rawStatus).toUpperCase()
    if (['SUPPORTED', 'PLAUSIBLE', 'WEAKENED', 'CONTRADICTED', 'UNRESOLVED', 'UNREPORTED'].includes(upper)) {
      return upper
    }
    return human(upper)
  }

  const reasons = props.whyNow?.slice(0, 3) || []
  const timeline = buildCognitiveTimeline(props)

  // Derive Hero display words
  const isAnalyzing = props.gptStatus?.status === 'ANALYZING'
  const isSessionLast = p.isSessionLast
  let word1 = 'UNAVAILABLE'
  let word2 = ''
  let readiness = 'UNAVAILABLE'

  if (isAnalyzing) {
    word1 = 'ANALYZING'
    word2 = 'EVIDENCE'
    readiness = 'INFERENCE IN-FLIGHT'
  } else if (p.current || isSessionLast) {
    if (props.state === 'CALL_DEVELOPING') {
      word1 = 'CALL'
      word2 = 'DEVELOPING'
      readiness = isSessionLast ? 'SESSION LAST · MARKET CLOSED' : 'DEVELOPING'
    } else if (props.state === 'PUT_DEVELOPING') {
      word1 = 'PUT'
      word2 = 'DEVELOPING'
      readiness = isSessionLast ? 'SESSION LAST · MARKET CLOSED' : 'DEVELOPING'
    } else if (props.state === 'CALL') {
      word1 = 'CALL'
      word2 = props.entryWindow === 'READY' ? 'READY' : 'ACTIVE'
      readiness = isSessionLast ? 'SESSION LAST · MARKET CLOSED' : props.entryWindow === 'READY' ? 'READY' : 'APPROACHING'
    } else if (props.state === 'PUT') {
      word1 = 'PUT'
      word2 = props.entryWindow === 'READY' ? 'READY' : 'ACTIVE'
      readiness = isSessionLast ? 'SESSION LAST · MARKET CLOSED' : props.entryWindow === 'READY' ? 'READY' : 'APPROACHING'
    } else if (props.state === 'REVERSAL_WATCH') {
      word1 = 'REVERSAL'
      word2 = 'WATCH'
      readiness = isSessionLast ? 'SESSION LAST · MARKET CLOSED' : 'MONITORING'
    } else {
      word1 = 'WAIT'
      word2 = 'MONITORING'
      readiness = isSessionLast ? 'SESSION LAST · MARKET CLOSED' : 'MONITORING'
    }
  } else {
    word1 = 'UNAVAILABLE'
    word2 = p.lastKnown ? `LAST: ${p.lastKnown}` : closed ? 'PAUSED' : 'PENDING'
    readiness = p.context
  }

  // Thesis & Counter-case copy (Truth-enforced: ZERO fabricated fallback prose)
  const defaultThesis =
    props.gptStatus?.interpretation ||
    (closed && !isSessionLast
      ? 'SESSION CLOSED · NO CURRENT COGNITIVE THESIS'
      : (p.current || isSessionLast)
      ? 'NO ACCEPTED SYNTHESIS THESIS REPORTED'
      : isAnalyzing
      ? 'COGNITIVE REASONING IN PROGRESS'
      : 'NO ACCEPTED EVIDENCE')

  const state = props.state
  const isAwaiting = !props.state && !p.current
  const displayState = isAwaiting ? 'AWAITING LIVE COGNITIVE STATE' : (state || 'NO_TRADE')
  const ceDisplay = receivedContract('ce') ? `${receivedContract('ce')!.strike} CE` : 'AWAITING REAL CE CONTRACT'
  const peDisplay = receivedContract('pe') ? `${receivedContract('pe')!.strike} PE` : 'AWAITING REAL PE CONTRACT'

  const counterCase =
    props.viewBreaksIf?.[0] ||
    props.reversalWatch?.why_not_confirmed ||
    props.reversalWatch?.first_contradiction ||
    props.reversalWatch?.what_failed ||
    props.reversalWatch?.what_still_opposes ||
    'NO ACCEPTED COUNTER-CASE REPORTED'

  // Sanitize prose and extract discrete evidence items
  const sanitizedDefaultThesis = sanitizeProseAndExtractEvidence(defaultThesis)
  const sanitizedReasons = reasons.map((r) => sanitizeProseAndExtractEvidence(r))
  const sanitizedBreaks = (props.viewBreaksIf || []).map((b) => sanitizeProseAndExtractEvidence(b))
  const sanitizedWatch = (props.watchNext || []).map((w) => sanitizeProseAndExtractEvidence(w))
  const sanitizedWhatChanged = sanitizeProseAndExtractEvidence(props.whatChanged || '')
  const sanitizedCounterCase = sanitizeProseAndExtractEvidence(counterCase)

  // Combined and deduplicated extracted evidence items
  const allExtractedEvidence: ExtractedEvidenceItem[] = [
    ...sanitizedDefaultThesis.evidence,
    ...sanitizedReasons.flatMap((r) => r.evidence),
    ...sanitizedBreaks.flatMap((b) => b.evidence),
    ...sanitizedWatch.flatMap((w) => w.evidence),
    ...sanitizedWhatChanged.evidence,
    ...sanitizedCounterCase.evidence,
  ]
  const uniqueEvidence = Array.from(
    new Map(allExtractedEvidence.map((item) => [item.rawId, item])).values()
  )

  const cleanActiveThesis = sanitizedDefaultThesis.cleanText
  const cleanCounterCase = sanitizedCounterCase.cleanText
  const cleanReasons = sanitizedReasons.map((r) => r.cleanText).filter(Boolean)
  const cleanBreaks = sanitizedBreaks.map((b) => b.cleanText).filter(Boolean)
  const cleanWatch = sanitizedWatch.map((w) => w.cleanText).filter(Boolean)
  const cleanWhatChanged = sanitizedWhatChanged.cleanText

  const isDuplicateReason = cleanReasons.length === 1 && cleanReasons[0].trim() === cleanActiveThesis.trim()
  const isDuplicateBreak = cleanBreaks.length === 1 && cleanBreaks[0].trim() === cleanCounterCase.trim()

  // Option flow agreement (Truth-enforced: discrete qualitative, ZERO invented percentages)
  const flowAgreement = props.premiumConfirmation
    ? human(props.premiumConfirmation)
    : (p.current || isSessionLast)
    ? 'NOT REPORTED'
    : 'UNRESOLVED'

  // Reversal Posture (Truth-enforced: real backend fields only, ZERO hardcoded pivots)
  const reversal = props.reversalWatch
  const reversalLabel =
    reversal?.direction === 'PUT_TO_CALL'
      ? 'PUT → CALL'
      : reversal?.direction === 'CALL_TO_PUT'
      ? 'CALL → PUT'
      : 'DIRECTION NOT REPORTED'
  const reversalPosture = reversal?.status
    ? human(reversal.status)
    : props.state === 'REVERSAL_WATCH'
    ? 'ACTIVE ALERT'
    : 'NOT REPORTED'
  const reversalPivot = reversal?.invalidation_pivot != null
    ? numeric(typeof reversal.invalidation_pivot === 'number' ? reversal.invalidation_pivot : parseFloat(String(reversal.invalidation_pivot)), 2)
    : reversal?.trigger_level != null
    ? numeric(typeof reversal.trigger_level === 'number' ? reversal.trigger_level : parseFloat(String(reversal.trigger_level)), 2)
    : 'NOT REPORTED'

  // Canvas Refs & Interactive Animation
  const topographyCanvasRef = useRef<HTMLCanvasElement>(null)
  const globeCanvasRef = useRef<HTMLCanvasElement>(null)
  const irisRef = useRef<HTMLDivElement>(null)

  // A real new accepted receipt transfers energy once. Hydration is not a receipt.
  const previousIrisReceipt = useRef(primaryReceipt)
  useEffect(() => {
    const previous = previousIrisReceipt.current
    previousIrisReceipt.current = primaryReceipt
    if (!previous || !primaryReceipt || previous === primaryReceipt || !isCurrentRead || reduced) return
    const animation = irisRef.current?.animate([
      { transform: 'scale(1)', opacity: 0.5 },
      { transform: 'scale(1.18)', opacity: 0.85 },
      { transform: 'scale(1)', opacity: 0.5 },
    ], { duration: 650, easing: 'ease-out' })
    const packet = rootRef.current?.querySelector('[data-input-packet]')?.animate([
      { strokeDashoffset: 1, opacity: 0 },
      { opacity: 1, offset: 0.15 },
      { strokeDashoffset: -1, opacity: 0 },
    ], { duration: 1300, easing: 'ease-in-out', iterations: 1 })
    return () => { animation?.cancel(); packet?.cancel() }
  }, [primaryReceipt, isCurrentRead, reduced])

  // Topography Waveform Canvas Loop
  useEffect(() => {
    const canvas = topographyCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationId: number
    let time = 0
    const resize = () => {
      canvas.width = canvas.offsetWidth || 1200
      canvas.height = canvas.offsetHeight || 600
    }
    resize()
    window.addEventListener('resize', resize)

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      time += 0.0028
      const w = canvas.width
      const h = canvas.height
      const numLines = 9
      const stepY = h / (numLines + 1)
      const strokeColor = props.state?.startsWith('PUT')
        ? 'rgba(255, 72, 98, 0.08)'
        : props.state === 'REVERSAL_WATCH'
        ? 'rgba(255, 190, 107, 0.08)'
        : isCurrentRead
        ? 'rgba(65, 237, 156, 0.065)'
        : 'rgba(130, 149, 153, 0.035)'

      ctx.lineWidth = 1
      for (let i = 1; i <= numLines; i++) {
        const baseY = stepY * i
        ctx.beginPath()
        ctx.strokeStyle = strokeColor
        for (let x = 0; x <= w; x += 36) {
          const wave1 = Math.sin(x * 0.003 + time + i * 0.4) * 22
          const wave2 = Math.cos(x * 0.006 - time * 0.7) * 11
          const y = baseY + wave1 + wave2
          if (x === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        }
        ctx.stroke()
      }
      if (!reduced) animationId = requestAnimationFrame(draw)
    }
    animationId = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(animationId)
      window.removeEventListener('resize', resize)
    }
  }, [props.state, isCurrentRead, reduced])

  // Holographic Intelligence Globe Canvas Loop
  useEffect(() => {
    const canvas = globeCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationId: number
    const GLOBE_NODES_COUNT = 136
    const globeNodes: Array<{ x: number; y: number; z: number; baseRadius: number; isHub: boolean; pulsePhase: number }> = []
    const goldenRatio = (1 + Math.sqrt(5)) / 2
    const angleIncrement = Math.PI * 2 * goldenRatio

    for (let i = 0; i < GLOBE_NODES_COUNT; i++) {
      const t = i / GLOBE_NODES_COUNT
      const inclination = Math.acos(1 - 2 * t)
      const azimuth = angleIncrement * i
      const x = Math.sin(inclination) * Math.cos(azimuth)
      const y = Math.sin(inclination) * Math.sin(azimuth)
      const z = Math.cos(inclination)
      const isHub = i % 9 === 0
      const baseRadius = isHub ? 2.6 : i % 3 === 0 ? 1.8 : 1.15
      globeNodes.push({ x, y, z, baseRadius, isHub, pulsePhase: Math.random() * Math.PI * 2 })
    }

    const globeEdges: Array<{ i: number; j: number; dist: number }> = []
    for (let i = 0; i < globeNodes.length; i++) {
      for (let j = i + 1; j < globeNodes.length; j++) {
        const dx = globeNodes[i].x - globeNodes[j].x
        const dy = globeNodes[i].y - globeNodes[j].y
        const dz = globeNodes[i].z - globeNodes[j].z
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz)
        if (dist < 0.38) globeEdges.push({ i, j, dist })
      }
    }

    let yaw = 0
    const pitch = 0.32
    const cosP = Math.cos(pitch)
    const sinP = Math.sin(pitch)

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      yaw += isSessionLast ? 0.0006 : 0.0024
      const cosY = Math.cos(yaw)
      const sinY = Math.sin(yaw)

      const R = 124 * 2
      const cx = canvas.width / 2
      const cy = canvas.height / 2
      const D = 420 * 2

      const isReversal = props.state === 'REVERSAL_WATCH'
      const isPut = props.state?.startsWith('PUT')
      const nodePrimary = isSessionLast
        ? 'rgba(245, 158, 11, '
        : isPut
        ? 'rgba(255, 72, 98, '
        : isReversal
        ? 'rgba(255, 190, 107, '
        : isCurrentRead
        ? 'rgba(65, 237, 156, '
        : 'rgba(130, 149, 153, '
      const nodeSecondary = isSessionLast
        ? 'rgba(180, 130, 60, '
        : isPut
        ? 'rgba(217, 38, 98, '
        : isReversal
        ? 'rgba(255, 190, 107, '
        : isCurrentRead
        ? 'rgba(87, 213, 211, '
        : 'rgba(70, 87, 93, '

      // Inner volumetric shading
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, R)
      grad.addColorStop(0, 'rgba(2, 6, 10, 0.45)')
      grad.addColorStop(0.7, 'rgba(4, 10, 16, 0.22)')
      grad.addColorStop(0.92, nodeSecondary + '0.06)')
      grad.addColorStop(1.0, nodePrimary + '0.18)')
      ctx.fillStyle = grad
      ctx.beginPath()
      ctx.arc(cx, cy, R, 0, Math.PI * 2)
      ctx.fill()

      // Latitude Parallels
      const latAngles = [Math.PI * 0.25, Math.PI * 0.1, -Math.PI * 0.1, -Math.PI * 0.25]
      ctx.lineWidth = 0.9
      for (const lat of latAngles) {
        const rLat = Math.cos(lat) * R
        const yLat = Math.sin(lat) * R
        ctx.beginPath()
        let first = true
        for (let s = 0; s <= 36; s++) {
          const lon = (s / 36) * Math.PI * 2
          const x0 = Math.cos(lon) * rLat
          const z0 = Math.sin(lon) * rLat
          const y1 = yLat * cosP - z0 * sinP
          const z1 = yLat * sinP + z0 * cosP
          const x2 = x0 * cosY + z1 * sinY
          const z2 = -x0 * sinY + z1 * cosY
          const scale = D / (D - z2)
          const px = cx + x2 * scale
          const py = cy + y1 * scale
          if (first) {
            ctx.moveTo(px, py)
            first = false
          } else {
            ctx.lineTo(px, py)
          }
        }
        ctx.strokeStyle = nodeSecondary + '0.05)'
        ctx.stroke()
      }

      // Projected Nodes
      const projected = globeNodes.map((node, idx) => {
        node.pulsePhase += 0.016
        const y1 = node.y * cosP - node.z * sinP
        const z1 = node.y * sinP + node.z * cosP
        const x2 = node.x * cosY + z1 * sinY
        const z2 = -node.x * sinY + z1 * cosY
        const scale = D / (D - z2 * R)
        const px = cx + x2 * R * scale
        const py = cy + y1 * R * scale
        const distFromCenter = Math.hypot(px - cx, py - cy)
        const mask = distFromCenter < 125 ? Math.max(0.18, distFromCenter / 125) : 1.0
        return { ...node, px, py, scale, z3: z2, mask, idx }
      })

      // Geodesic telemetry connections
      ctx.lineWidth = 1.0
      for (const edge of globeEdges) {
        const p1 = projected[edge.i]
        const p2 = projected[edge.j]
        const avgZ = (p1.z3 + p2.z3) / 2
        const edgeAlpha = (avgZ > 0 ? 0.08 + 0.2 * avgZ : 0.02 + 0.04 * (1 + avgZ)) * Math.min(p1.mask, p2.mask)
        if (edgeAlpha > 0.008) {
          ctx.strokeStyle = nodeSecondary + edgeAlpha.toFixed(3) + ')'
          ctx.beginPath()
          ctx.moveTo(p1.px, p1.py)
          ctx.lineTo(p2.px, p2.py)
          ctx.stroke()
        }
      }

      // Draw Nodes
      for (const p of projected) {
        const zNorm = p.z3
        const alpha = (zNorm > 0 ? 0.35 + 0.65 * zNorm : 0.08 + 0.18 * (1 + zNorm)) * p.mask
        if (alpha > 0.02) {
          const color = isReversal
            ? p.x < -0.05
              ? 'rgba(65, 237, 156, '
              : p.x > 0.05
              ? 'rgba(255, 72, 98, '
              : 'rgba(255, 190, 107, '
            : p.isHub
            ? nodePrimary
            : nodeSecondary
          const pulse = 1.0 + Math.sin(p.pulsePhase) * 0.16
          const radius = p.baseRadius * p.scale * (zNorm > 0 ? pulse : 1.0)
          ctx.fillStyle = color + alpha.toFixed(2) + ')'
          ctx.beginPath()
          ctx.arc(p.px, p.py, Math.max(0.75, radius), 0, Math.PI * 2)
          ctx.fill()
        }
      }

      if (!reduced) animationId = requestAnimationFrame(draw)
    }
    animationId = requestAnimationFrame(draw)

    return () => cancelAnimationFrame(animationId)
  }, [props.state, isCurrentRead, isSessionLast, reduced])

  // Dynamic Luna Model ID & Status (Truth-enforced: no hardcoded active strings)
  const runtimeModelId = props.gptStatus?.model_id === 'gpt-5.6-luna' ? 'gpt-5.6-luna' : props.gptStatus?.model_id || null
  const lunaStatus = isAnalyzing
    ? 'ANALYZING'
    : isSessionLast
    ? 'SESSION LAST'
    : props.gptStatus?.status
    ? human(props.gptStatus.status)
    : props.transportUnavailable
    ? 'PROVIDER UNAVAILABLE'
    : closed
    ? 'SESSION LAST'
    : p.current
    ? 'CURRENT'
    : 'UNAVAILABLE'

  const statusText = runtimeModelId ? `${runtimeModelId} · ${lunaStatus}` : lunaStatus
  const lunaStatusClass =
    lunaStatus === 'CURRENT' || lunaStatus === 'ANALYZING'
      ? styles.deskStatusPillActive
      : lunaStatus === 'STALE' || lunaStatus === 'SESSION LAST'
      ? styles.deskStatusPillStale
      : styles.deskStatusPillInactive

  return (
    <section
      ref={rootRef}
      className={styles.deck}
      data-testid="cognitive-decision-core"
      data-tone={p.tone}
      data-state={props.state}
      data-session-last={isSessionLast}
      data-citadel-revision={props.revision}
      aria-label="Oracle Cognitive Intelligence"
    >
      {/* 1. State-Aware Full Atmospheric Background System */}
      <div className={styles.viewportAtmosphere} aria-hidden="true" />
      <canvas ref={topographyCanvasRef} className={styles.topographyCanvas} aria-hidden="true" />
      <div className={styles.tactileGrain} aria-hidden="true" />
      <div className={styles.technicalLatitude} aria-hidden="true" />

      {/* 2. Top Global Strip */}
      <header className={styles.globalStrip}>
        <div className={styles.stripMeta}>
          <div className={styles.brandMark}>
            <span className={styles.brandDot} />
            CITADEL // LUNA COGNITIVE STAGE
          </div>
          <span className={styles.sessionBadge}>SESSION // NSE INTRADAY</span>
          <span className={styles.paperBadge}>SHADOW · PAPER MODE</span>
        </div>

        <div className={styles.stripStatus}>
          <div className={styles.statusBadge}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--accent)' }} />
            <span>LATENCY: {numeric(props.gptStatus?.latency_ms, 0)}ms</span>
          </div>
          <div className={styles.statusBadge}>
            <span>ANALYST:</span>
            <strong style={{ color: 'var(--accent)', marginLeft: 4 }}>
              {runtimeModelId || 'COGNITIVE ENGINE'}
            </strong>
          </div>
        </div>
      </header>

      {/* 3. Open De-Dashboarded Cinematic Stage */}
      <main className={styles.stageContainer} data-cognitive-stage-viewport data-accepted-input-receipt={receipt?.receipt_id ?? undefined}>
        {/* SVG Layer for Finite Traveling Energy Packet Beams */}
        <svg className={styles.receiptSvgOverlay} viewBox="0 0 1000 600" preserveAspectRatio="none" aria-hidden="true">
          <path data-input-packet d="M 100 160 C 300 160 340 210 500 210 S 700 160 900 160" pathLength="1" strokeDasharray="0.04 1" className={styles.receiptPacketPath} stroke="var(--cyan)" />
        </svg>

        {/* LEFT COLUMN: 01 // EVIDENCE BUS (What Luna Received) */}
        <aside
          className={`${styles.spatialColumn} ${styles.evidenceBusPanel}`}
          data-scroll-phase="EVIDENCE"
          data-testid="luna-evidence-bus"
        >
          <div className={styles.openGroupHeader}>
            <div className={styles.openGroupTitle}>
              <span className={styles.indicatorBar} style={{ background: 'var(--cyan)' }} />
              01 // LUNA EVIDENCE BUS · TEMPORAL OBSERVER
            </div>
            <span>{receipt ? (p.isSessionLast ? 'LAST ACCEPTED INPUT · INGESTION RECEIPT' : 'ACCEPTED INPUT · INGESTION RECEIPT') : 'INGESTION RECEIPT · EXACT INPUT NOT RECORDED'}</span>
          </div>
          {receipt ? <>
            <div className={styles.receiptHeaderRow} data-input-receipt={receipt.receipt_id}>
              <span>PROVENANCE · {receipt.cutoff} IST</span>
              <span>r{receipt.revision} CANONICAL</span>
            </div>
            {(() => {
              return ([
                ['UNDERLYING', ['spot_price', 'futures_price', 'basis', 'session_vwap']],
                ['OPTION RESPONSE', ['ce_atm_premium', 'pe_atm_premium', 'straddle_price', 'atm_iv']],
                ['POSITIONING & REGIME', ['pcr_oi', 'total_net_gex_inr_cr', 'zero_gamma', 'skew_25d']],
                ['ORDER FLOW & MICROSTRUCTURE', ['dealer_regime', 'cvd', 'mlofi_5l', 'skew_10d']],
              ] as const).map(([title, keys]) => <section className={styles.evidenceBlock} key={title}>
                <div className={styles.evidenceBlockHeader}><span>{title}</span><span>AS SENT</span></div>
                <div className={styles.evidenceGrid}>{keys.map(key => <div className={styles.evidenceItem} key={key}>
                  <span className={styles.evidenceLabel}>{({
                    spot_price: 'SPOT', futures_price: 'FUTURES', basis: 'BASIS', session_vwap: 'VWAP',
                    ce_atm_premium: 'CALL PREMIUM', pe_atm_premium: 'PUT PREMIUM',
                    straddle_price: atmStrikeVal ? `SPOT ATM STRADDLE · ${atmStrikeVal}` : 'ATM STRADDLE',
                    atm_iv: 'ATM IV', pcr_oi: 'PCR', total_net_gex_inr_cr: 'NET GEX', zero_gamma: 'ZERO GAMMA', skew_25d: '25-DELTA SKEW',
                    dealer_regime: 'DEALER REGIME', cvd: 'CVD (DELTA)', mlofi_5l: '5L MLOFI', skew_10d: '10-DELTA SKEW',
                  } as Record<string, string>)[key] || human(key)}</span>
                  <span className={`${styles.evidenceValue} ${
                    key === 'basis' ? ((typeof facts['basis']?.value === 'number' && facts['basis'].value > 0) ? styles.evidenceValueCyan : styles.evidenceValueRed) :
                    key === 'total_net_gex_inr_cr' ? ((typeof facts['total_net_gex_inr_cr']?.value === 'number' && facts['total_net_gex_inr_cr'].value > 0) ? styles.evidenceValueGreen : styles.evidenceValueRed) :
                    key === 'cvd' ? ((typeof facts['cvd']?.value === 'number' && facts['cvd'].value > 0) ? styles.evidenceValueGreen : styles.evidenceValueRed) :
                    ''
                  }`}>{formatFactValue(key, facts[key]?.value)}</span>
                </div>)}</div>
              </section>)
            })()}
            <details className={styles.evidenceBlock}>
              <summary>Exact input · contracts, changes & provenance</summary>
              <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 11 }}>{JSON.stringify(receipt, null, 2)}</pre>
            </details>
          </> : <section className={styles.evidenceBlock}>
            <p>The saved read has no exact input receipt. Newer Oracle prices are not substituted here.</p>
          </section>}
          <div className={styles.receiptHeaderRow}>
            <span>INDIA VIX · {snapshot?.india_vix != null ? snapshot.india_vix : 'UNAVAILABLE'}</span>
            <span>MAX PAIN · {typeof facts['max_pain']?.value === 'number' ? facts['max_pain'].value : 'NOT CANONICAL'}</span>
          </div>
          <div className={styles.receiptHeaderRow} style={{ marginTop: 4 }}>
            <span>CE: {ceDisplay}</span>
            <span>PE: {peDisplay}</span>
          </div>
        </aside>

        {/* CENTER STAGE: Master Cognitive Aperture & Intelligence Globe */}
        <section className={styles.centralCognitiveStage} data-scroll-phase="CORE">
          {/* Top Pill Sensor Anchor: Directly above orbital */}
          <div className={styles.pillOrbitalAnchor} data-testid="live-island-orbital-anchor">
            <CitadelLiveIsland />
          </div>

          {/* Center Stage Pipeline Bridge */}
          <div className={styles.pipelineBridgeRow} aria-hidden="true">
            <div className={styles.pipelineBridgeLeft}>
              <span>◀</span> LUNA EVIDENCE BUS
            </div>
            <div className={styles.pipelineBridgeLine} />
            <div className={styles.pipelineBridgeRight}>
              DECISION SURFACE <span>▶</span>
            </div>
          </div>
          {/* Central Aperture Lens Viewport */}
          <div ref={stateRef} className={styles.apertureFocalViewport} data-motion-stage="THESIS" data-current={p.current}>
            {/* Optical Breathing Iris Core */}
            <div ref={irisRef} className={styles.opticalLensIris} aria-hidden="true" />

            {/* 2.5D Holographic Intelligence Globe Canvas */}
            <canvas
              ref={globeCanvasRef}
              className={styles.intelligenceGlobeCanvas}
              width={720}
              height={720}
              aria-hidden="true"
            />

            {/* Layered Radial Astronomical Gyroscope SVG */}
            <svg className={styles.apertureLayeredSvg} viewBox="0 0 360 360" aria-hidden="true">
              <g className={styles.gyroRingOuter}>
                <circle cx="180" cy="180" r="164" className={styles.ringTrackPrimary} />
                <circle cx="180" cy="180" r="156" className={styles.ringTrackSecondary} />
              </g>

              <circle
                cx="180"
                cy="180"
                r="142"
                className={styles.lensRefractionRim}
                strokeDasharray="80 180"
                strokeDashoffset="40"
              />

              <circle
                cx="180"
                cy="180"
                r="134"
                className={styles.dynamicConsensusArc}
                strokeDasharray={props.state?.startsWith('CALL') ? '580 260' : props.state?.startsWith('PUT') ? '480 340' : '260 580'}
                strokeDashoffset="0"
              />

              <circle
                cx="180"
                cy="180"
                r="134"
                className={`${styles.reversalAsymmetricArc} ${props.state === 'REVERSAL_WATCH' ? styles.reversalAsymmetricArcActive : ''}`}
                transform="rotate(180 180 180)"
              />

              <g className={styles.gyroRingInner}>
                <circle cx="180" cy="180" r="108" className={styles.ringTrackSecondary} />
              </g>
            </svg>

            {/* Core Focal Readout: TIER 1 DOMINANT HERO */}
            <div className={styles.coreFocalReadout}>
              <div className={styles.readinessKickerBadge}>· {readiness} ·</div>

              {isSessionLast && (
                <div className={styles.sessionLastKickerBadge}>
                  LAST ACCEPTED // SESSION CLOSED
                </div>
              )}

              {/* Dominant 60px Variable Display Hero */}
              <h3
                className={styles.heroStateDisplay}
                data-citadel-field="cognitive.primary.state"
                data-current={p.current}
              >
                {!p.current && !isAnalyzing && !isSessionLast ? (
                  'UNAVAILABLE'
                ) : (
                  <>
                    <span className={styles.stateWordLine}>
                      <span className={styles.stateWordInner}>{word1}</span>
                    </span>
                    {word2 && (
                      <span className={styles.stateWordLine}>
                        <span className={styles.stateWordInner}>{word2}</span>
                      </span>
                    )}
                  </>
                )}
              </h3>

              <div className={styles.flowAgreementTag}>
                {isSessionLast
                  ? 'SESSION LAST · NOT CURRENT'
                  : p.current
                  ? (flowAgreement === 'NOT REPORTED' ? 'DIRECTIONAL DELTA NOT REPORTED' : `FLOW ${flowAgreement}`)
                  : 'CONFIRMATION UNAVAILABLE'}
              </div>
              <strong
                data-citadel-field="cognitive.primary.entry"
                className={`${styles.entryWindowDisplay} ${isSessionLast ? styles.entryWindowClosed : ''}`}
              >
                {isSessionLast ? 'SESSION LAST' : p.current ? p.entry : 'NOT READY'}
              </strong>
              {isSessionLast && (
                <div className={styles.sessionLastSubtext}>
                  AS OF 15:30 IST · HISTORICAL ARCHIVE
                </div>
              )}
            </div>
          </div>

          {p.lastKnown ? (
            <p className={styles.lastKnown}>
              LAST KNOWN <b>{human(props.state)}</b>
              <span>NOT CURRENT · {timeLabel(props.gptStatus?.updated_at)}</span>
            </p>
          ) : null}

          {/* Compact Aperture Subbar */}
          <div className={styles.apertureSubbar}>
            <div className={styles.apertureSubItem}>
              <span className={styles.apertureSubLabel}>BASIS</span>
              <span className={styles.apertureSubVal}>
                {(snapshot?.futures_basis != null ? formatNumber(snapshot.futures_basis, 2, true) : '—')}
              </span>
            </div>
            <div className={styles.apertureSubDivider} />
            <div className={styles.apertureSubItem}>
              <span className={styles.apertureSubLabel}>
                {atmStrikeVal ? `STRADDLE (${atmStrikeVal})` : 'STRADDLE'}
              </span>
              <span className={styles.apertureSubVal}>
                {(numberFact('straddle_price') ?? '—')}
              </span>
            </div>
            <div className={styles.apertureSubDivider} />
            <div className={styles.apertureSubItem}>
              <span className={styles.apertureSubLabel}>NET GEX</span>
              <span className={styles.apertureSubVal}>
                {(snapshot?.net_gex != null ? `${snapshot.net_gex > 0 ? '+' : ''}₹${snapshot.net_gex}Cr` : '—')}
              </span>
            </div>
          </div>

          {/* Multi-Model Live Shadow Specialist Cards (V1.3) */}
          <div className={styles.specialistsSubstage} data-testid="cognitive-specialists-substage">
            {/* Gemini ⚡ Fast Scout */}
            <div
              className={`${styles.specialistCard} ${styles.geminiCard}`}
              data-testid="gemini-scout-card"
              data-specialist="gemini"
              data-semantic-state={geminiState}
            >
              <div className={styles.specialistCardHeader}>
                <span className={styles.specialistCardTitle}>
                  GEMINI ⚡ FAST SCOUT
                </span>
                <span
                  className={styles.specialistStatusPill}
                  data-tone={geminiTone}
                >
                  {geminiPillLabel}
                </span>
              </div>
              <div className={styles.specialistHeadline}>
                {geminiHeadline}
              </div>
              {geminiBullets.length > 0 && (
                <ul className={styles.specialistBulletList}>
                  {geminiBullets.map((b, i) => (
                    <li key={i} className={styles.specialistBulletItem}>
                      {b}
                    </li>
                  ))}
                </ul>
              )}
              <div className={styles.specialistCardFooter}>
                <span>{geminiFreshnessLabel}</span>
                {geminiMissing.length > 0 && (
                  <span className={styles.specialistMissingTag}>
                    {`MISSING: ${geminiMissing.join(', ')}`}
                  </span>
                )}
              </div>
            </div>

            {/* Sol 🔬 Option Specialist */}
            <div
              className={`${styles.specialistCard} ${styles.solCard}`}
              data-testid="sol-option-specialist-card"
              data-specialist="sol"
              data-buying-state={solState}
            >
              <div className={styles.specialistCardHeader}>
                <span className={styles.specialistCardTitle}>
                  SOL 🔬 OPTION SPECIALIST
                </span>
                <span
                  className={styles.specialistStatusPill}
                  data-tone={solTone}
                >
                  {solPillLabel}
                </span>
              </div>
              <div className={styles.specialistHeadline}>
                {solHeadline}
              </div>
              {solBullets.length > 0 && (
                <ul className={styles.specialistBulletList}>
                  {solBullets.map((b, i) => (
                    <li key={i} className={styles.specialistBulletItem}>
                      {b}
                    </li>
                  ))}
                </ul>
              )}
              <div className={styles.specialistCardFooter}>
                <span>{solFreshnessLabel}</span>
                {solMissing.length > 0 && (
                  <span className={styles.specialistMissingTag}>
                    {`MISSING: ${solMissing.join(', ')}`}
                  </span>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* RIGHT COLUMN: 02 // DECISION SURFACE (What Luna Concluded) */}
        <aside
          className={`${styles.crossValidationColumn} ${styles.decisionSurfacePanel}`}
          data-scroll-phase="INSTRUMENTS"
          data-testid="luna-decision-surface"
        >
          <div className={styles.openGroupHeader}>
            <div className={styles.openGroupTitle}>
              <span className={styles.indicatorBar} style={{ background: 'var(--violet)' }} />
              02 // DECISION SURFACE
            </div>
            <span>LUNA INTERPRETED OUTPUT</span>
          </div>

          {/* Group 1: Primary Thesis & Rationale */}
          <section className={styles.decisionBlock}>
            <div className={styles.evidenceBlockHeader}>
              <span className={styles.evidenceBlockTitle}>
                <span className={styles.categoryDotAccent} />
                01 // PRIMARY THESIS &amp; RATIONALE
              </span>
              <span>{isCurrentRead ? 'ACCEPTED READ' : 'LAST ACCEPTED READ'}</span>
            </div>

            <div className={styles.evidenceGrid}>
              <div className={styles.evidenceItem}>
                <span className={styles.evidenceLabel}>PRIMARY STATE</span>
                <span className={`${styles.evidenceValue} ${props.state?.startsWith('CALL') ? styles.evidenceValueGreen : props.state?.startsWith('PUT') ? styles.evidenceValueRed : styles.evidenceValueCyan}`}>
                  {props.state ? human(props.state) : 'UNAVAILABLE'}
                </span>
              </div>
              <div className={styles.evidenceItem}>
                <span className={styles.evidenceLabel}>ENTRY WINDOW</span>
                <span className={styles.evidenceValue}>
                  {isSessionLast ? 'SESSION LAST' : p.current ? p.entry : 'NOT READY'}
                </span>
              </div>
            </div>

            <div className={styles.decisionWhyBox}>
              <div className={styles.decisionWhyTitle}>
                MARKET READ
              </div>
              {rejected ? (
                <div style={{ color: 'var(--red)', fontSize: 12, fontWeight: 700, padding: '4px 0' }}>
                  <strong>LEGACY ANALYSIS REJECTED BY CURRENT SEMANTIC FIREWALL</strong>
                </div>
              ) : (
                <>
                  <GlanceRead text={cleanActiveThesis} />
                  {cleanReasons.length > 0 && !isDuplicateReason && (
                    <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.05)', paddingTop: 6 }}>
                      {cleanReasons.map((line, idx) => (
                        <div
                          key={`${idx}:${line}`}
                          style={{ marginBottom: idx < cleanReasons.length - 1 ? 4 : 0, fontSize: 11.5, color: 'var(--text-t3)', cursor: 'pointer' }}
                        >
                          <GlanceRead text={human(line)} />
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            <div className={styles.decisionWatchBox}>
              <div className={styles.decisionWatchTitle}>WHAT CHANGED</div>
              <GlanceRead text={
                cleanWhatChanged && !(cleanWhatChanged.startsWith('Revision ') && cleanWhatChanged.includes('analyzed.'))
                  ? cleanWhatChanged
                  : 'No change summary supplied.'
              } />
            </div>

            <div className={styles.decisionBreaksBox}>
              <div className={styles.decisionBreaksTitle}>
                WHAT DOESN’T FIT
              </div>
              <GlanceRead text={
                cleanCounterCase && cleanCounterCase !== 'NO ACCEPTED COUNTER-CASE REPORTED'
                  ? cleanCounterCase
                  : cleanBreaks.length > 0
                  ? cleanBreaks[0]
                  : 'No contradiction assessment supplied.'
              } />
              {cleanBreaks.length > 0 && !isDuplicateBreak && (
                <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.05)', paddingTop: 6 }}>
                  {cleanBreaks
                    .map((line, idx) => (
                      <div key={`${idx}:${line}`} style={{ marginBottom: idx < cleanBreaks.length - 1 ? 4 : 0, fontSize: 11.5, color: 'var(--text-t3)' }}>
                        <GlanceRead text={human(line)} />
                      </div>
                    ))}
                </div>
              )}
            </div>

            {!!props.missingConfirmation?.length && <div className={styles.decisionWatchBox}>
              <div className={styles.decisionWatchTitle}>MISSING CONFIRMATION</div>
              <GlanceRead text={sanitizeProseAndExtractEvidence(props.missingConfirmation[0]).cleanText} />
            </div>}
            <div className={styles.decisionWatchBox}>
              <div className={styles.decisionWatchTitle}>
                WHAT TO WATCH NEXT
              </div>
              <div>
                {cleanWatch.length > 0 ? (
                  cleanWatch
                    .slice(0, 2)
                    .map((line, idx) => (
                      <div key={`${idx}:${line}`} style={{ marginBottom: idx < cleanWatch.length - 1 ? 4 : 0, fontSize: 11.5, color: 'var(--text-t2)' }}>
                        <GlanceRead text={human(line)} />
                      </div>
                    ))
                ) : (
                  <div style={{ fontSize: 11.5, color: 'var(--text-t3)' }}>
                    No watch-next condition supplied.
                  </div>
                )}
              </div>
            </div>
          </section>

          {/* Group 2: Cross-Validation & Option Flow */}
          <section
            className={`${styles.metricHeroCard} ${flowAgreement === 'NOT REPORTED' ? styles.metricHeroCardCompact : ''}`}
            data-testid="cognitive-option-buyer"
            data-premium={p.current ? props.premiumConfirmation : undefined}
          >
            <div className={styles.openGroupHeader} style={{ border: 'none', paddingBottom: 0 }}>
              <div className={styles.openGroupTitle}>
                <span className={styles.indicatorBar} style={{ background: 'var(--cyan)' }} />
                02 // OPTION FLOW
              </div>
              <span>CROSS-VALIDATION</span>
            </div>

            <div
              className={`${styles.metricHeroDisplay} ${
                flowAgreement === 'CONFIRMING' || flowAgreement === 'CALL FLOW LEAN'
                  ? styles.metricHeroDisplayGreen
                  : flowAgreement === 'DIVERGING' || flowAgreement === 'PUT FLOW LEAN'
                  ? styles.metricHeroDisplayRed
                  : flowAgreement === 'NOT REPORTED'
                  ? styles.metricHeroDisplayMuted
                  : styles.metricHeroDisplayAmber
              }`}
            >
              {flowAgreement}
            </div>

            {flowAgreement !== 'NOT REPORTED' && (
              <div className={styles.metricBarTrack} data-agreement={flowAgreement}>
                <div
                  className={`${styles.metricBarSegment} ${
                    flowAgreement === 'CONFIRMING' || flowAgreement === 'CALL FLOW LEAN'
                      ? styles.metricBarConfirming
                      : flowAgreement === 'DIVERGING' || flowAgreement === 'PUT FLOW LEAN'
                      ? styles.metricBarDiverging
                      : styles.metricBarUnresolved
                  }`}
                />
              </div>
            )}

            <div className={styles.metricHeroSubtext}>
              <strong data-side={p.current ? props.optionBuyerSide : undefined}>
                {props.optionBuyerSide ? human(props.optionBuyerSide) : 'DIRECTIONAL DELTA NOT REPORTED'}
              </strong>
              {' · '}
              <em data-confirmation={p.current ? props.premiumConfirmation : undefined}>
                {props.premiumConfirmation ? human(props.premiumConfirmation) : 'PREMIUM EXPANSION NOT REPORTED'}
              </em>
            </div>

          </section>

          {/* Group 3: 4-Way Competing Hypotheses */}
          <section className={styles.hypothesesCluster}>
            <div className={styles.openGroupHeader}>
              <div className={styles.openGroupTitle}>
                <span className={styles.indicatorBar} style={{ background: 'var(--violet)' }} />
                03 // COMPETING HYPOTHESES
              </div>
              <span>4-WAY STATUS</span>
            </div>

            <div className={styles.hypothesesGrid}>
              {[
                { id: 'CALL', name: 'CALL CONTINUATION' },
                { id: 'PUT', name: 'PUT EXPANSION' },
                { id: 'NOISE', name: 'CHOP / NOISE' },
                { id: 'REVERSAL', name: 'REVERSAL THESIS' },
              ].map(({ id, name }) => {
                const rawEntry = props.fiveHypotheses?.[id] || (id === 'NOISE' ? props.fiveHypotheses?.['CHOP'] || props.fiveHypotheses?.['NO_TRADE'] : undefined)
                const status = getHypothesisStatus(id)
                const whyText = typeof rawEntry === 'object' ? (rawEntry.why || rawEntry.plausibility) : undefined
                const ordinalMap: Record<string, string> = {
                  SUPPORTED: 'LEADING',
                  PLAUSIBLE: id === 'NOISE' && props.state === 'WAIT' ? 'LEADING' : (id === 'PUT' ? 'ACTIVE' : 'BUILDING'),
                  WEAKENED: 'WEAK',
                  CONTRADICTED: 'INVALIDATED',
                  UNRESOLVED: 'UNRESOLVED',
                }
                const ordinal = ordinalMap[status] || status
                return (
                  <div key={id} className={styles.hypothesisCard}>
                    <div className={styles.hypothesisCardTop}>
                      <span className={styles.hypothesisName}>{name}</span>
                      <span
                        className={`${styles.hypothesisStatusPill} ${
                          status === 'SUPPORTED' || ordinal === 'LEADING'
                            ? styles.pillSupported
                            : status === 'WEAKENED' || ordinal === 'WEAK'
                            ? styles.pillWeakened
                            : status === 'PLAUSIBLE' || ordinal === 'ACTIVE' || ordinal === 'BUILDING'
                            ? styles.pillPlausible
                            : status === 'CONTRADICTED' || ordinal === 'INVALIDATED'
                            ? styles.pillContradicted
                            : styles.pillUnresolved
                        }`}
                      >
                        {status}
                      </span>
                    </div>
                    {whyText && (
                      <p className={styles.hypothesisDiscrimination}>{whyText}</p>
                    )}
                  </div>
                )
              })}
            </div>
          </section>

          {/* Group 4: Horizon Sensor & Reversal Posture */}
          <section
            className={`${styles.metricHeroCard} ${styles.reversalSensoryNode} ${!reversal?.why_not_confirmed ? styles.reversalSensoryNodeCompact : ''}`}
            data-testid="cognitive-reversal"
          >
            <div className={styles.metricHeroLabel}>
              <span>04 // REVERSAL POSTURE</span>
              <span style={{ fontSize: 9, color: 'var(--amber)' }}>HORIZON SENSOR</span>
            </div>

            <div
              className={`${styles.metricHeroDisplay} ${
                reversalPosture.includes('ALERT')
                  ? styles.metricHeroDisplayAmber
                  : styles.metricHeroDisplayCyan
              }`}
            >
              {reversalPosture}
            </div>

            <div className={styles.metricHeroSubtext}>
              {plain(reversal?.first_contradiction, 'No contradiction supplied.')}
            </div>

            {reversal?.why_not_confirmed ? (
              <div className={styles.metricHeroSubtext}>
                {plain(reversal.why_not_confirmed, 'No confirmation assessment supplied.')}
              </div>
            ) : null}

            <div className={styles.pivotRow}>
              <span className={styles.pivotLabel}>
                {reversal?.direction ? reversalLabel : 'INVALIDATION PIVOT'}
              </span>
              <span className={styles.pivotValue}>{reversalPivot}</span>
            </div>
          </section>

          {/* Group 5: Thesis Evolution & Opportunity Maturity */}
          <section className={`${styles.evidenceBlock} ${(!props.thesisEvolution && !props.opportunityMaturity) ? styles.evidenceBlockCompact : ''}`}>
            <div className={styles.evidenceBlockHeader}>
              <span className={styles.evidenceBlockTitle}>
                <span className={styles.categoryDotCyan} />
                05 // EVOLUTION &amp; MATURITY
              </span>
              <span>ACCEPTED INTERPRETATION</span>
            </div>
            <div className={styles.evidenceGrid}>
              <div className={styles.evidenceItem}>
                <span className={styles.evidenceLabel}>THESIS EVOLUTION</span>
                <span className={styles.evidenceValue}>
                  {props.thesisEvolution ? human(props.thesisEvolution) : 'NOT REPORTED'}
                </span>
              </div>
              <div className={styles.evidenceItem}>
                <span className={styles.evidenceLabel}>OPPORTUNITY MATURITY</span>
                <span className={styles.evidenceValue}>
                  {props.opportunityMaturity ? human(props.opportunityMaturity) : 'NOT REPORTED'}
                </span>
              </div>
            </div>
          </section>
        </aside>
      </main>

      {/* 4. Secondary Analytical Strip */}
      <footer className={styles.secondaryAnalyticalStrip}>
        <div className={styles.stripLeftMeta}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)' }} />
          <span style={{ fontWeight: 700, color: '#fff' }}>
            {runtimeModelId === 'gpt-5.6-luna' ? 'LUNA COGNITIVE ENGINE' : 'COGNITIVE ENGINE'}
          </span>
          <span className={`${styles.deskStatusPill} ${lunaStatusClass}`}>
            {statusText}
          </span>
          <span className={styles.secondaryBadge}>SHADOW COGNITION</span>
        </div>

        <div className={styles.stripCenterBadges}>
          <span className={styles.secondaryBadge}>
            EVOLUTION: <strong>{props.thesisEvolution ? human(props.thesisEvolution) : 'NOT REPORTED'}</strong>
          </span>
          <span className={styles.secondaryBadge}>
            MATURITY: <strong>{props.opportunityMaturity ? human(props.opportunityMaturity) : 'NOT REPORTED'}</strong>
          </span>
          <span className={`${styles.secondaryBadge} ${styles.secondaryBadgeAccent}`}>
            {isAnalyzing
              ? 'ANALYZING IN-FLIGHT'
              : isSessionLast
              ? 'SESSION LAST · HISTORICAL AUDIT'
              : props.modelTension
              ? props.modelTension
              : props.agreementStatus && props.agreementStatus !== 'UNAVAILABLE'
              ? human(props.agreementStatus)
              : p.current
              ? 'SOLITARY COGNITIVE AUDIT'
              : 'ANALYSIS UNAVAILABLE'}
          </span>
        </div>

        <div className={styles.stripRightSafety}>
          <span className={styles.secondaryBadge}>
            Read-only interpretation · evidence details below.
          </span>
          <span className={styles.secondaryBadge}>Deterministic privacy sanitization</span>
          <span className={styles.secondaryBadge}>SAFETY: PAPER MODE ONLY</span>
          <span className={styles.secondaryBadge}>EXECUTION INFLUENCE ZERO</span>
        </div>
      </footer>

      {/* 5. Live Auxiliary Rail: Cognitive Timeline & World Context */}
      <section className={styles.liveAuxiliaryRail} aria-label="Auxiliary Market Intelligence">
        <section className={styles.temporalBand} data-scroll-phase="TEMPORAL">
          <div className={styles.timeline} aria-label="Cognitive timeline">
            <span className={styles.timelineTitle}>COGNITIVE TIMELINE</span>
            {timeline.length ? (
              <div className={styles.timelineTrack}>
                {timeline.map((event, index) => (
                  <div key={event.id} className={styles.timelineEvent}>
                    <time>{clockLabel(event.at)}</time>
                    <i />
                    <b>{event.source}</b>
                    <span title={event.label}>{event.label}</span>
                    {index < timeline.length - 1 ? <em aria-hidden="true" /> : null}
                  </div>
                ))}
              </div>
            ) : (
              <p>NO ACCEPTED TIMESTAMPED EVENTS</p>
            )}
          </div>
        </section>

        <div data-scroll-phase="TEMPORAL">
          <ContextStrip world={props.worldContext} />
        </div>
      </section>

      {/* 6. Institutional Detail Deck: Collapsible Deep Diagnostic Drawers */}
      <div className={styles.detailDeck}>
        {input.rejectedHistory ? (
          <CognitiveDrawer title="Rejected legacy analysis" meta="Historical / debug only">
            <p>LEGACY ANALYSIS REJECTED BY CURRENT SEMANTIC FIREWALL. This is not a valid or current view.</p>
            <pre>{JSON.stringify(input.rejectedHistory, null, 2)}</pre>
          </CognitiveDrawer>
        ) : null}

        <CognitiveDrawer
          title="Five hypotheses"
          meta={
            Object.keys(props.fiveHypotheses || {}).length
              ? `${Object.keys(props.fiveHypotheses!).length} recorded`
              : 'Not supplied'
          }
        >
          {Object.keys(props.fiveHypotheses || {}).length ? (
            <div className={styles.hypotheses}>
              {Object.entries(props.fiveHypotheses!).map(([key, hypothesis]) => {
                const status = typeof hypothesis === 'string' ? hypothesis : hypothesis.status
                const why = typeof hypothesis === 'string' ? '' : hypothesis.why
                const premiumConfirmation = typeof hypothesis === 'string' ? undefined : hypothesis.premium_confirmation
                return (
                  <article key={key}>
                    <header>
                      <h4>{human(key)}</h4>
                      <span>{human(status)}</span>
                    </header>
                    <p>{why || 'No explanation supplied.'}</p>
                    <small>{human(premiumConfirmation)}</small>
                  </article>
                )
              })}
            </div>
          ) : (
            <p className={styles.empty}>No hypothesis set supplied for this view.</p>
          )}
        </CognitiveDrawer>

        <CognitiveDrawer
          title="Evidence receipt & audit trail"
          meta={`${uniqueEvidence.length} extracted receipts`}
        >
          {uniqueEvidence.length > 0 ? (
            <table className={styles.evidenceReceiptTable}>
              <thead>
                <tr>
                  <th className={styles.evidenceReceiptTh}>EVENT ID</th>
                  <th className={styles.evidenceReceiptTh}>EVENT TYPE</th>
                  <th className={styles.evidenceReceiptTh}>INSTRUMENT</th>
                  <th className={styles.evidenceReceiptTh}>TIMESTAMP</th>
                </tr>
              </thead>
              <tbody>
                {uniqueEvidence.map((ev) => (
                  <tr key={ev.rawId}>
                    <td className={styles.evidenceReceiptTd}>
                      <code className={styles.evidenceReceiptCode}>{ev.id}</code>
                    </td>
                    <td className={styles.evidenceReceiptTd}>{ev.eventType}</td>
                    <td className={styles.evidenceReceiptTd}>{ev.instrument}</td>
                    <td className={styles.evidenceReceiptTd}>{ev.timestamp || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className={styles.empty}>No discrete raw event IDs extracted from current cognitive cycle.</p>
          )}
        </CognitiveDrawer>

        <CognitiveDrawer
          title="Options & evidence"
          meta={`${props.evidenceReferences?.length || 0} references`}
        >
          <div className={styles.contracts}>
            {([
              ['CALL', receivedContract('ce')],
              ['PUT', receivedContract('pe')],
            ] as const).map(([side, contract]) => (
              <article key={side}>
                <h4>
                  {side} · {contract ? `${contract.strike} / ID ${contract.securityId}` : 'CONTRACT UNAVAILABLE'}
                </h4>
                <dl>
                  <div>
                    <dt>PRICE</dt>
                    <dd>{numeric(contract?.ltp)}</dd>
                  </div>
                  <div>
                    <dt>SAME-CONTRACT CHANGE</dt>
                    <dd>{numeric(contract?.sameContractDelta)}</dd>
                  </div>
                  <div>
                    <dt>SPREAD</dt>
                    <dd>{numeric(contract?.spread)}</dd>
                  </div>
                  <div>
                    <dt>IV</dt>
                    <dd>{numeric(contract?.iv)}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
          <p className={styles.empty}>Contract values are supplied by CITADEL. Missing changes remain unavailable.</p>
          <div className={styles.evidence}>
            {props.evidenceReferences?.length ? (
              props.evidenceReferences.map((id) => <code key={id}>{id}</code>)
            ) : (
              <span>No attached evidence references.</span>
            )}
          </div>
        </CognitiveDrawer>

        <CognitiveDrawer title="Luna production telemetry" meta={runtimeModelId || 'gpt-5.6-luna'}>
          <div className={styles.contracts}>
            {(() => {
              const model = props.gptStatus
              return (
                <article key="LUNA">
                  <h4>{runtimeModelId || 'LUNA COGNITIVE ENGINE'}</h4>
                  <dl>
                    <div>
                      <dt>REPORTED STATUS</dt>
                      <dd>{human(model?.status)}</dd>
                    </div>
                    <div>
                      <dt>ANALYZED REVISION</dt>
                      <dd>{model?.analyzed_revision ?? '—'}</dd>
                    </div>
                    <div>
                      <dt>LATENCY (MS)</dt>
                      <dd>{numeric(model?.latency_ms, 0)}</dd>
                    </div>
                    <div>
                      <dt>TOKENS</dt>
                      <dd>{model?.tokens ?? '—'}</dd>
                    </div>
                  </dl>
                </article>
              )
            })()}
          </div>
        </CognitiveDrawer>
      </div>

      {/* Footer */}
      <footer className={styles.footer}>
        <span>{props.revision != null ? `INPUT r${props.revision}` : 'REVISION UNAVAILABLE'}</span>
        <span>{props.unseenEventsCount != null ? `${props.unseenEventsCount} PENDING EVENTS` : 'EVENT COUNT UNAVAILABLE'}</span>
        <span>VOB INDEPENDENT · EXECUTION INFLUENCE ZERO</span>
      </footer>
    </section>
  )
})
