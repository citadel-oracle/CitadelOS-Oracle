'use client'

import {
  Activity, Bell, Boxes, Check, ChevronRight, Copy, FileClock, GitBranch,
  Pause, RotateCcw, Settings2, ShieldCheck, Sparkles, X, Zap,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { feedSelectors, useDashboardSelector } from '@/dashboard'
import type { DashboardFeedState } from '@/dashboard/types'
import { CitadelPrimaryNavigation } from '@/components/institutional'
import styles from './strategies.module.css'
import editorStyles from './editor.module.css'
import { useStrategyCommandActions } from './useStrategyCommandActions'

type UnknownMap = Record<string, unknown>

type StrategyDefinition = {
  strategy_id: string
  name: string
  family: string
  latest_version: string
  versions: string[]
  registration_state: string
  enabled: boolean
}

type StrategyVersion = {
  strategy_id: string
  name: string
  version: string
  family: string
  description: string
  supported_instruments: string[]
  supported_timeframes: string[]
  required_inputs: string[]
  optional_inputs: string[]
  signal_logic: string
  source_module: string
  guardian_compatibility: boolean
}

type Deployment = {
  deployment_instance_id: string
  name: string
  strategy_id: string
  strategy_version: string
  configuration_hash: string
  runtime_configuration_hash: string | null
  state: string
  reason: string
  enabled: boolean
  updated_at: string
  material_changes: string[]
  configuration: {
    market: UnknownMap
    timeframes: { roles: Record<string, string[]>; aggregation: string; stale_data_threshold_seconds: number }
    position: UnknownMap
    session: UnknownMap
    entry: UnknownMap
    exit: UnknownMap
    guardian: UnknownMap
    decision: { weights: Record<string, number>; intelligence: Record<string, string> }
    conflict: UnknownMap
    execution: { path: string; enabled: boolean; paper_only: true; live_trading_enabled: false; broker_submission: false; advisory_only: boolean }
  }
  runtime: UnknownMap
  decision: UnknownMap
  analytics: UnknownMap
  deployment_history: UnknownMap[]
  deployment_receipts?: UnknownMap[]
}

type Notification = {
  notification_id: string
  severity: string
  timestamp: string
  strategy_id: string | null
  strategy_version: string | null
  deployment_instance_id: string | null
  destination: string | null
  message: string
  evidence_link: string
  acknowledged: boolean
}

type StrategyCommandData = {
  status: string
  health: string
  readiness: string
  generated_at: string
  definitions: StrategyDefinition[]
  versions: StrategyVersion[]
  deployments: Deployment[]
  active_deployments: Deployment[]
  registration_errors: Array<{ module: string; reason: string }>
  notifications: Notification[]
  execution_paths: string[]
  aggregation_modes: string[]
  configuration_schema: { modes: string[]; sections: Record<string, string[]> }
  decision_policy: UnknownMap
  price_action_reuse: UnknownMap
  safety: { paper_only: true; live_trading_enabled: false; broker_submission: false; new_strategies_auto_deployed: false; oracle_development_mutated: false }
}

const text = (value: unknown, fallback = 'NOT REPORTED') => typeof value === 'string' && value ? value : fallback
const number = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : null
const shortHash = (value: string | null) => value ? `${value.slice(0, 8)}…${value.slice(-6)}` : 'NOT LOADED'
const label = (value: string) => value.replaceAll('_', ' ')
const time = (value: string | null | undefined) => value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }) : 'NOT REPORTED'
const record = (value: unknown): UnknownMap => value && typeof value === 'object' && !Array.isArray(value) ? value as UnknownMap : {}
const lifecycleViews = [
  { label: 'VIEW MISSION', view: 'mission' },
  { label: 'VIEW ORDER', view: 'order' },
  { label: 'VIEW POSITION', view: 'position' },
  { label: 'VIEW GUARDIAN', view: 'guardian' },
  { label: 'VIEW LEDGER', view: 'ledger' },
  { label: 'VIEW EVIDENCE', view: 'evidence' },
] as const

export default function StrategiesCommandCenter() {
  const feed = useDashboardSelector(feedSelectors.strategies) as DashboardFeedState<StrategyCommandData>
  const actions = useStrategyCommandActions()
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null)
  const [mode, setMode] = useState<'SIMPLE' | 'ADVANCED'>('SIMPLE')
  const [review, setReview] = useState<Deployment | null>(null)
  const [editing, setEditing] = useState<Deployment | null>(null)
  const [notificationsOpen, setNotificationsOpen] = useState(false)

  const data = feed.data
  const selectedDefinition = useMemo(() => {
    const id = selectedStrategy ?? data?.definitions[0]?.strategy_id
    return data?.definitions.find((item) => item.strategy_id === id) ?? null
  }, [data, selectedStrategy])
  const selectedVersion = data?.versions.find((item) => item.strategy_id === selectedDefinition?.strategy_id && item.version === selectedDefinition.latest_version) ?? null
  const selectedDeployments = data?.deployments.filter((item) => item.strategy_id === selectedDefinition?.strategy_id) ?? []

  const createDraft = async () => {
    if (!selectedDefinition) return
    await actions.saveDraft({
      strategy_id: selectedDefinition.strategy_id,
      strategy_version: selectedDefinition.latest_version,
      name: `${selectedDefinition.name} · COMMAND INSTANCE`,
    })
  }

  return (
    <main className={styles.command} aria-label="CITADEL Strategies Command Center">
      <CitadelPrimaryNavigation
        active="strategies"
        title="CITADEL OS"
        instrument="STRATEGIES COMMAND CENTER"
        marketStatus="PAPER ONLY"
      />
      <header className={styles.topbar}>
        <div className={styles.brand}><Boxes size={16} /><span>STRATEGIES COMMAND CENTER</span><small>Configuration &amp; deployment authority</small></div>
        <div className={styles.safety}>PAPER ONLY · LIVE DISABLED · BROKER SUBMISSION OFF</div>
        <button type="button" className={styles.notificationButton} onClick={() => setNotificationsOpen((value) => !value)} aria-label="Notification centre">
          <Bell size={15} /><span>{data?.notifications.length ?? 0}</span>
        </button>
      </header>

      {notificationsOpen && (
        <aside className={styles.notificationCenter} aria-label="Persistent notification centre">
          <header><span>NOTIFICATION CENTRE</span><button type="button" onClick={() => setNotificationsOpen(false)}><X size={14} /></button></header>
          {(data?.notifications ?? []).slice().reverse().map((item, index) => (
            <article key={`${item.timestamp}-${index}`} data-severity={item.severity} data-acknowledged={item.acknowledged}>
              <i /><div><strong>{item.message}</strong><small>{label(item.severity)} · {time(item.timestamp)}</small></div>
              <button type="button" onClick={() => location.assign(item.evidence_link)}>EVIDENCE</button>
              {!item.acknowledged && <button type="button" onClick={() => void actions.acknowledge(item.notification_id)}>ACK</button>}
            </article>
          ))}
          {!data?.notifications.length && <p>No persisted strategy events.</p>}
        </aside>
      )}

      <section className={styles.hero}>
        <div><span>REGISTRY</span><strong>{data?.definitions.length ?? '—'}</strong><small>Canonical definitions</small></div>
        <div><span>VERSIONS</span><strong>{data?.versions.length ?? '—'}</strong><small>Immutable strategy versions</small></div>
        <div><span>INSTANCES</span><strong>{data?.deployments.length ?? '—'}</strong><small>Independent configurations</small></div>
        <div><span>ACTIVE</span><strong>{data?.active_deployments.length ?? '—'}</strong><small>Runtime hash verified</small></div>
        <div><span>REGISTRY HEALTH</span><strong className={data?.health === 'HEALTHY' ? styles.good : styles.warn}>{data?.health ?? 'CONNECTING'}</strong><small>{data?.registration_errors.length ?? 0} registration errors</small></div>
      </section>

      {actions.error && <div className={styles.errorBanner}><span>{actions.error}</span><button type="button" onClick={() => location.reload()}>REFRESH STATE</button></div>}
      {!data && <div className={styles.loading}>CONNECTING TO STRATEGY AUTHORITY · {feed.error ?? 'WAITING FOR CANONICAL V2 FEED'}</div>}

      {data && (
        <>
          <section className={styles.registryShell}>
            <header className={styles.sectionHeader}>
              <div><span>01 / CANONICAL REGISTRY</span><h1>Strategy Registry</h1><p>Discovered from valid deployment contracts. New definitions remain disabled drafts.</p></div>
              <button type="button" className={styles.primary} onClick={() => void createDraft()} disabled={!selectedDefinition || actions.busyAction !== null}><Zap size={13} /> CREATE INSTANCE</button>
            </header>
            <div className={styles.registryGrid}>
              <div className={styles.strategyList}>
                {data.definitions.map((item) => (
                  <button key={item.strategy_id} type="button" onClick={() => setSelectedStrategy(item.strategy_id)} className={selectedDefinition?.strategy_id === item.strategy_id ? styles.selected : ''}>
                    <i /><div><strong>{item.name}</strong><small>{item.family} · {item.latest_version}</small></div><span>{item.registration_state}</span><ChevronRight size={13} />
                  </button>
                ))}
              </div>
              <article className={styles.definitionDetail}>
                {selectedVersion ? (
                  <>
                    <header><div><span>{selectedVersion.family}</span><h2>{selectedVersion.name}</h2><p>{selectedVersion.description}</p></div><em>DRAFT · DISABLED</em></header>
                    <div className={styles.definitionMatrix}>
                      <Metric label="Strategy ID" value={selectedVersion.strategy_id} />
                      <Metric label="Version" value={selectedVersion.version} />
                      <Metric label="Instruments" value={selectedVersion.supported_instruments.join(' · ')} />
                      <Metric label="Timeframes" value={selectedVersion.supported_timeframes.join(' · ')} />
                      <Metric label="Required inputs" value={selectedVersion.required_inputs.join(' · ')} />
                      <Metric label="Optional inputs" value={selectedVersion.optional_inputs.join(' · ') || 'NONE'} />
                    </div>
                    <div className={styles.logicStrip}><span>SIGNAL LOGIC</span><code>{selectedVersion.signal_logic}</code><small>Guardian {selectedVersion.guardian_compatibility ? 'COMPATIBLE' : 'NOT DECLARED'}</small></div>
                  </>
                ) : <p>No version selected.</p>}
              </article>
            </div>
          </section>

          <section className={styles.instanceShell}>
            <header className={styles.sectionHeader}>
              <div><span>02 / DEPLOYMENT INSTANCES</span><h2>Independent Runtime Instances</h2><p>Each instance owns its configuration, hash, runtime state, audit lineage and analytics attribution.</p></div>
              <div className={styles.modeToggle}><button type="button" className={mode === 'SIMPLE' ? styles.active : ''} onClick={() => setMode('SIMPLE')}>SIMPLE</button><button type="button" className={mode === 'ADVANCED' ? styles.active : ''} onClick={() => setMode('ADVANCED')}>ADVANCED</button></div>
            </header>

            {!selectedDeployments.length && <div className={styles.empty}>No instance exists for this strategy. Create one to begin configuration; nothing will deploy automatically.</div>}
            <div className={styles.instanceGrid}>
              {selectedDeployments.map((instance) => (
                <article key={instance.deployment_instance_id} className={styles.instanceCard} data-state={instance.state}>
                  <header>
                    <div><span>{instance.configuration.execution.path}</span><h3>{instance.name}</h3><small>{instance.deployment_instance_id}</small></div>
                    <StateBadge state={instance.state} />
                  </header>
                  <div className={styles.runtimeReason}><Activity size={12} /><span>{label(instance.reason)}</span></div>
                  {mode === 'SIMPLE' ? <SimpleConfiguration instance={instance} /> : <AdvancedConfiguration instance={instance} schema={data.configuration_schema.sections} />}
                  <DecisionEvidence instance={instance} />
                  <RuntimeLifecycle instance={instance} />
                  <div className={styles.hashStrip}>
                    <span>CONFIGURATION HASH</span><code>{shortHash(instance.configuration_hash)}</code>
                    <i className={instance.runtime_configuration_hash === instance.configuration_hash ? styles.hashGood : styles.hashPending}>{instance.runtime_configuration_hash === instance.configuration_hash ? 'VERIFIED' : 'PENDING'}</i>
                  </div>
                  <footer>
                    <button type="button" onClick={() => setEditing(instance)} disabled={actions.busyAction !== null}><Settings2 size={12} /> EDIT CONFIG</button>
                    <button type="button" onClick={() => setReview(instance)} disabled={actions.busyAction !== null}><ShieldCheck size={12} /> REVIEW &amp; DEPLOY</button>
                    <button type="button" onClick={() => void actions.duplicate(instance.deployment_instance_id)} disabled={actions.busyAction !== null}><Copy size={12} /> DUPLICATE</button>
                    <button type="button" onClick={() => void actions.pause(instance.deployment_instance_id)} disabled={actions.busyAction !== null || instance.state === 'PAUSED'}><Pause size={12} /> PAUSE</button>
                    <button type="button" onClick={() => void actions.resume(instance.deployment_instance_id)} disabled={actions.busyAction !== null || instance.state !== 'PAUSED' || instance.configuration.execution.enabled !== true}><Activity size={12} /> RESUME</button>
                    <button type="button" onClick={() => void actions.rollback(instance.deployment_instance_id)} disabled={actions.busyAction !== null || instance.deployment_history.length < 2}><RotateCcw size={12} /> ROLLBACK</button>
                    <button type="button" onClick={() => actions.showReceipt((instance.deployment_receipts ?? []).at(-1) ?? {})} disabled={actions.busyAction !== null || !(instance.deployment_receipts ?? []).length}><FileClock size={12} /> OPEN RECEIPT</button>
                    <button type="button" onClick={() => location.assign(`/oracle?instance=${encodeURIComponent(instance.deployment_instance_id)}`)}><Sparkles size={12} /> VIEW IN ORACLE</button>
                    {lifecycleViews.map((item) => (
                      <button
                        key={item.view}
                        type="button"
                        onClick={() => location.assign(`/oracle?instance=${encodeURIComponent(instance.deployment_instance_id)}&view=${item.view}`)}
                      >
                        {item.label}
                      </button>
                    ))}
                  </footer>
                </article>
              ))}
            </div>
          </section>

          <section className={styles.controlGrid}>
            <article><header><GitBranch size={14} /><span>MULTI-TIMEFRAME CONSENSUS</span></header><strong>{selectedDeployments[0]?.configuration.timeframes.aggregation ?? 'NOT CONFIGURED'}</strong><p>{selectedDeployments[0] ? Object.entries(selectedDeployments[0].configuration.timeframes.roles).map(([role, frames]) => `${label(role)}: ${frames.join('+')}`).join(' · ') : 'Create an instance to expose deterministic role mapping.'}</p></article>
            <article><header><ShieldCheck size={14} /><span>DECISION AUTHORITY</span></header><strong>50 / 25 / 25</strong><p>Price Action / VOB / selected strategy trigger. Intelligence layers default to display only.</p></article>
            <article><header><FileClock size={14} /><span>PRICE ACTION PARITY</span></header><strong>{text(data.price_action_reuse.status)}</strong><p>{text(data.price_action_reuse.original_source)} · no mutable Oracle Development dependency.</p></article>
            <article><header><Settings2 size={14} /><span>SAFETY BOUNDARY</span></header><strong className={styles.good}>PROTECTED</strong><p>Paper only · live disabled · broker submission off · newly discovered strategies never auto-deploy.</p></article>
          </section>
        </>
      )}

      {review && (
        <DeploymentReview
          instance={review}
          busy={actions.busyAction}
          onClose={() => setReview(null)}
          onSaveDraft={async () => {
            const result = await actions.saveDraft({
              strategy_id: review.strategy_id,
              strategy_version: review.strategy_version,
              deployment_instance_id: review.deployment_instance_id,
              name: review.name,
              configuration: review.configuration,
            })
            if (result) setReview(null)
          }}
          onDeploy={async () => {
            const result = await actions.deploy(review.deployment_instance_id, review.configuration_hash)
            if (result) setReview(null)
          }}
        />
      )}
      {editing && (
        <ConfigurationEditor
          key={`${editing.deployment_instance_id}:${editing.configuration_hash}:${mode}`}
          instance={editing}
          mode={mode}
          executionPaths={data?.execution_paths ?? []}
          onClose={() => setEditing(null)}
          onSave={async (configuration) => {
            const result = await actions.saveDraft({
              strategy_id: editing.strategy_id,
              strategy_version: editing.strategy_version,
              deployment_instance_id: editing.deployment_instance_id,
              name: editing.name,
              configuration,
            })
            if (result) setEditing(null)
          }}
        />
      )}
      {actions.busyAction === 'DEPLOY' && <DeploymentProgress />}
      {actions.receipt && <ReceiptDrawer receipt={actions.receipt} onClose={actions.dismissReceipt} />}
    </main>
  )
}

function Metric({ label: metricLabel, value }: { label: string; value: string }) {
  return <div><span>{metricLabel}</span><strong>{value}</strong></div>
}

function StateBadge({ state }: { state: string }) {
  const icon = state === 'ERROR' || state === 'BLOCKED' ? <X size={10} /> : state === 'ACTIVE' || state === 'OBSERVING' ? <Check size={10} /> : <Activity size={10} />
  return <em className={styles.stateBadge} data-state={state}>{icon}{label(state)}</em>
}

function SimpleConfiguration({ instance }: { instance: Deployment }) {
  const config = instance.configuration
  return (
    <div className={styles.simpleGrid}>
      <Metric label="Instrument" value={text(config.market.instrument)} />
      <Metric label="Entry timeframe" value={config.timeframes.roles.entry.join(' + ')} />
      <Metric label="Option policy" value={Array.isArray(config.market.option_sides) ? config.market.option_sides.join(' / ') : 'NOT REPORTED'} />
      <Metric label="Lots" value={String(config.position.fixed_lots)} />
      <Metric label="Execution path" value={config.execution.path} />
      <Metric label="Session" value={`${text(config.session.first_entry_time)} → ${text(config.session.square_off_time)}`} />
      <Metric label="Stop / target" value={`${config.exit.structural_invalidation ? 'STRUCTURAL' : text(config.exit.premium_stop_loss)} / ${text(config.exit.target, 'STRATEGY')}`} />
      <Metric label="Enabled" value={config.execution.enabled ? 'ENABLED' : 'PAUSED'} />
    </div>
  )
}

function AdvancedConfiguration({ instance, schema }: { instance: Deployment; schema: Record<string, string[]> }) {
  return (
    <div className={styles.advancedGrid}>
      {Object.entries(schema).map(([section, fields]) => (
        <details key={section}>
          <summary><span>{label(section)}</span><small>{fields.length} controls</small></summary>
          <div>{fields.map((field) => <span key={field}><i>{label(field)}</i><code>{formatConfigValue((instance.configuration as unknown as Record<string, UnknownMap>)[section]?.[field])}</code></span>)}</div>
        </details>
      ))}
    </div>
  )
}

function formatConfigValue(value: unknown) {
  if (value == null) return 'NOT REPORTED'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function DecisionEvidence({ instance }: { instance: Deployment }) {
  const decision = instance.decision
  return (
    <div className={styles.decisionGrid}>
      <Metric label="Price Action" value={number(decision.price_action_score)?.toFixed(0) ?? '—'} />
      <Metric label="VOB" value={number(decision.vob_score)?.toFixed(0) ?? '—'} />
      <Metric label="Strategy" value={number(decision.strategy_trigger_score)?.toFixed(0) ?? '—'} />
      <Metric label="Total" value={number(decision.total_score)?.toFixed(0) ?? '—'} />
      <div className={styles.nextCondition}><span>NEXT REQUIRED CONDITION</span><strong>{text(decision.next_required_condition, 'AWAITING COMPLETED CANDLE')}</strong></div>
    </div>
  )
}

function RuntimeLifecycle({ instance }: { instance: Deployment }) {
  const runtime = record(instance.runtime)
  const lifecycle = record(runtime.lifecycle)
  const mission = record(lifecycle.mission)
  const order = record(lifecycle.order)
  const fill = record(lifecycle.fill)
  const position = record(lifecycle.position)
  const guardian = record(lifecycle.guardian)
  const latestTrade = record(lifecycle.latest_trade)
  const analytics = record(lifecycle.analytics)
  const runtimeState = text(lifecycle.runtime_state, text(runtime.state, instance.state))
  const runtimeReason = text(lifecycle.runtime_reason, text(runtime.reason, instance.reason))
  return (
    <section aria-label={`Paper lifecycle for ${instance.name}`}>
      <div className={styles.hashStrip}>
        <span>REAL PAPER LIFECYCLE</span>
        <StateBadge state={runtimeState} />
        <code>{label(runtimeReason)}</code>
      </div>
      <div className={styles.decisionGrid}>
        <Metric label="Mission" value={text(mission.mission_id)} />
        <Metric label="Selected contract" value={text(position.contract, text(mission.contract))} />
        <Metric label="Order / fill" value={`${text(order.status)} / ${text(fill.status)}`} />
        <Metric label="Position" value={text(position.status, latestTrade.status ? 'CLOSED' : 'NONE')} />
        <Metric label="Guardian" value={text(guardian.state, text(latestTrade.guardian_contribution))} />
        <Metric label="PnL" value={number(position.pnl)?.toFixed(2) ?? number(latestTrade.net_pnl)?.toFixed(2) ?? 'NOT AVAILABLE'} />
        <Metric label="Latest timestamp" value={time(text(lifecycle.latest_authoritative_timestamp, ''))} />
        <Metric label="Lifecycle totals" value={`${formatConfigValue(analytics.missions)}M · ${formatConfigValue(analytics.orders)}O · ${formatConfigValue(analytics.fills)}F · ${formatConfigValue(analytics.trades)}T`} />
      </div>
    </section>
  )
}

function DeploymentReview({ instance, busy, onClose, onSaveDraft, onDeploy }: { instance: Deployment; busy: string | null; onClose: () => void; onSaveDraft: () => Promise<void>; onDeploy: () => Promise<void> }) {
  const config = instance.configuration
  return (
    <div className={styles.modalBackdrop} role="presentation">
      <section className={styles.reviewModal} role="dialog" aria-modal="true" aria-label="Final deployment review">
        <header><div><span>FINAL DEPLOYMENT REVIEW</span><h2>{instance.name}</h2><p>Material configuration will be persisted before runtime activation.</p></div><button type="button" onClick={onClose}><X size={16} /></button></header>
        <div className={styles.reviewGrid}>
          <Metric label="Strategy / version" value={`${instance.strategy_id} · ${instance.strategy_version}`} />
          <Metric label="Instance ID" value={instance.deployment_instance_id} />
          <Metric label="Instrument" value={text(config.market.instrument)} />
          <Metric label="All timeframes" value={Object.entries(config.timeframes.roles).map(([role, frames]) => `${label(role)} ${frames.join('+')}`).join(' · ')} />
          <Metric label="Execution path" value={config.execution.path} />
          <Metric label="CALL / PUT policy" value={Array.isArray(config.market.option_sides) ? config.market.option_sides.join(' / ') : 'NOT REPORTED'} />
          <Metric label="Contract selection" value={`${text(config.market.moneyness)} · offset ${formatConfigValue(config.market.strike_offset)}`} />
          <Metric label="Lots / capital" value={`${formatConfigValue(config.position.fixed_lots)} / ₹${formatConfigValue(config.position.capital)}`} />
          <Metric label="Maximum monetary risk" value={`₹${formatConfigValue(config.position.fixed_rupee_risk)}`} />
          <Metric label="Daily loss / max trades" value={`₹${formatConfigValue(config.session.daily_loss_limit)} / ${formatConfigValue(config.session.maximum_trades_per_day)}`} />
          <Metric label="Entry / exit" value={`${text(config.entry.conflict_behaviour)} / ${config.exit.structural_invalidation ? 'STRUCTURAL INVALIDATION' : 'NOT REPORTED'}`} />
          <Metric label="Guardian" value={`${config.guardian.enabled ? 'ENABLED' : 'DISABLED'} · ${text(config.guardian.execution_mode)}`} />
          <Metric label="Intelligence modes" value={Object.entries(config.decision.intelligence).map(([name, value]) => `${label(name)} ${label(value)}`).join(' · ')} />
          <Metric label="Conflict policy" value={text(config.conflict.policy)} />
          <Metric label="Configuration hash" value={instance.configuration_hash} />
        </div>
        <div className={styles.warningStrip}><ShieldCheck size={13} /><span>LIVE remains disabled. Broker submission remains false. Runtime activation requires exact hash parity.</span></div>
        <div className={styles.changeList}><span>CHANGES VERSUS PREVIOUS DEPLOYMENT</span><strong>{instance.material_changes.map(label).join(' · ') || 'NO MATERIAL CHANGE'}</strong></div>
        <footer><button type="button" onClick={onClose}>CANCEL</button><button type="button" onClick={() => void onSaveDraft()} disabled={busy !== null}>SAVE AS DRAFT</button><button type="button" className={styles.primary} onClick={() => void onDeploy()} disabled={busy !== null}><Zap size={13} /> DEPLOY</button></footer>
      </section>
    </div>
  )
}

function ConfigurationEditor({ instance, mode, executionPaths, onClose, onSave }: {
  instance: Deployment
  mode: 'SIMPLE' | 'ADVANCED'
  executionPaths: string[]
  onClose: () => void
  onSave: (configuration: Deployment['configuration']) => Promise<void>
}) {
  const [configuration, setConfiguration] = useState(instance.configuration)
  const [sections, setSections] = useState<Record<string, string>>(
    () => Object.fromEntries(
      Object.entries(instance.configuration).map(([key, value]) => [
        key,
        JSON.stringify(value, null, 2),
      ]),
    ),
  )
  const [parseError, setParseError] = useState<string | null>(null)

  const patch = (section: keyof Deployment['configuration'], key: string, value: unknown) => {
    setConfiguration((current) => ({
      ...current,
      [section]: { ...current[section], [key]: value },
    }))
  }

  const save = async () => {
    if (mode === 'SIMPLE') {
      await onSave(configuration)
      return
    }
    try {
      const parsed = Object.fromEntries(Object.entries(sections).map(([key, value]) => [key, JSON.parse(value)])) as Deployment['configuration']
      setParseError(null)
      await onSave(parsed)
    } catch {
      setParseError('Advanced configuration contains invalid JSON.')
    }
  }

  return (
    <div className={styles.modalBackdrop} role="presentation">
      <section className={editorStyles.editorModal} role="dialog" aria-modal="true" aria-label={`${mode} configuration editor`}>
        <header><div><span>{mode} CONFIGURATION</span><h2>{instance.name}</h2><p>Both modes write the same canonical typed configuration and hash.</p></div><button type="button" onClick={onClose}><X size={16} /></button></header>
        {mode === 'SIMPLE' ? (
          <div className={editorStyles.editorGrid}>
            <Field label="Instrument"><input value={text(configuration.market.instrument, '')} onChange={(event) => patch('market', 'instrument', event.target.value)} /></Field>
            <Field label="Entry timeframe"><input value={configuration.timeframes.roles.entry.join(',')} onChange={(event) => patch('timeframes', 'roles', { ...configuration.timeframes.roles, entry: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} /></Field>
            <Field label="CALL / PUT"><select value={Array.isArray(configuration.market.option_sides) && configuration.market.option_sides.length === 1 ? String(configuration.market.option_sides[0]) : 'BOTH'} onChange={(event) => patch('market', 'option_sides', event.target.value === 'BOTH' ? ['CALL', 'PUT'] : [event.target.value])}><option>BOTH</option><option>CALL</option><option>PUT</option></select></Field>
            <Field label="Fixed lots"><input type="number" min="1" value={String(configuration.position.fixed_lots)} onChange={(event) => patch('position', 'fixed_lots', Number(event.target.value))} /></Field>
            <Field label="Maximum lots"><input type="number" min="1" value={String(configuration.position.maximum_lots)} onChange={(event) => patch('position', 'maximum_lots', Number(event.target.value))} /></Field>
            <Field label="Execution path"><select value={configuration.execution.path} onChange={(event) => patch('execution', 'path', event.target.value)}>{executionPaths.map((path) => <option key={path}>{path}</option>)}</select></Field>
            <Field label="First entry"><input type="time" value={text(configuration.session.first_entry_time, '')} onChange={(event) => patch('session', 'first_entry_time', event.target.value)} /></Field>
            <Field label="Last entry"><input type="time" value={text(configuration.session.last_entry_time, '')} onChange={(event) => patch('session', 'last_entry_time', event.target.value)} /></Field>
            <Field label="Square off"><input type="time" value={text(configuration.session.square_off_time, '')} onChange={(event) => patch('session', 'square_off_time', event.target.value)} /></Field>
            <Field label="Rupee risk"><input type="number" min="0" value={String(configuration.position.fixed_rupee_risk ?? '')} onChange={(event) => patch('position', 'fixed_rupee_risk', Number(event.target.value))} /></Field>
            <Field label="Minimum RR"><input type="number" min="0" step=".1" value={String(configuration.entry.minimum_rr ?? '')} onChange={(event) => patch('entry', 'minimum_rr', Number(event.target.value))} /></Field>
            <Field label="Enabled"><select value={configuration.execution.enabled ? 'ENABLED' : 'PAUSED'} onChange={(event) => patch('execution', 'enabled', event.target.value === 'ENABLED')}><option>PAUSED</option><option>ENABLED</option></select></Field>
          </div>
        ) : (
          <div className={editorStyles.jsonEditorGrid}>
            {Object.entries(sections).map(([section, value]) => (
              <label key={section}><span>{label(section)}</span><textarea spellCheck={false} value={value} onChange={(event) => setSections((current) => ({ ...current, [section]: event.target.value }))} /></label>
            ))}
          </div>
        )}
        {parseError && <div className={styles.errorBanner}>{parseError}</div>}
        <footer><button type="button" onClick={onClose}>CANCEL</button><button type="button" className={styles.primary} onClick={() => void save()}>SAVE AS DRAFT</button></footer>
      </section>
    </div>
  )
}

function Field({ label: fieldLabel, children }: { label: string; children: ReactNode }) {
  return <label className={editorStyles.editorField}><span>{fieldLabel}</span>{children}</label>
}

function DeploymentProgress() {
  return (
    <div className={styles.progressToast} role="status">
      <Sparkles size={15} /><div><strong>DEPLOYMENT SEQUENCE ACTIVE</strong><span>VALIDATING · SAVING CONFIGURATION · SYNCHRONIZING RUNTIME · ACTIVATING</span></div>
    </div>
  )
}

function ReceiptDrawer({ receipt, onClose }: { receipt: UnknownMap; onClose: () => void }) {
  return (
    <aside className={styles.receiptDrawer} aria-label="Deployment receipt">
      <header><div><Check size={16} /><span>STRATEGY DEPLOYED SUCCESSFULLY</span></div><button type="button" onClick={onClose}><X size={14} /></button></header>
      <dl>{Object.entries(receipt).filter(([key]) => !['timeframes'].includes(key)).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{formatConfigValue(value)}</dd></div>)}</dl>
      <footer><button type="button" onClick={() => location.assign('/oracle')}>VIEW IN ORACLE</button><button type="button" onClick={onClose}>VIEW RUNTIME</button></footer>
    </aside>
  )
}
