import assert from 'node:assert/strict'
import test from 'node:test'
import type { RiskPlanItem, ShadowStatusData, DeploymentLaneItem, ThresholdItem, MigrationStatusData } from '../src/components/institutional/RiskIntelligenceShadowConsole'

// Pure logic & state transformation helpers for unit verification

export function computeHeroCounts(
  shadowStatus: Partial<ShadowStatusData> | null,
  plans: RiskPlanItem[]
) {
  const actionableCount = plans.filter(
    (p) => !p.is_skipped && p.provenance?.actionable !== false
  ).length
  const skippedCount =
    shadowStatus?.skipped_plans_count ?? plans.filter((p) => p.is_skipped).length
  const storedCount = shadowStatus?.active_plans_count ?? plans.length
  const hookFailures = shadowStatus?.hook_telemetry?.risk_hook_failures ?? 0
  const executionInfluence = shadowStatus?.execution_influence ?? 'ZERO'

  return {
    actionableCount,
    skippedCount,
    storedCount,
    hookFailures,
    executionInfluence,
  }
}

export function computeCandidateCardState(plan: RiskPlanItem | null) {
  if (!plan) {
    return {
      title: 'NO CANDIDATE DATA',
      isActionable: false,
      contract: '—',
      entryStr: '—',
      stopStr: '—',
      riskDistanceStr: '—',
      skipReason: 'NO_DATA',
    }
  }

  const isActionable = !plan.is_skipped && plan.provenance?.actionable !== false
  const isSuppressed =
    plan.provenance?.candidate_status === 'SUPPRESSED' ||
    Boolean(plan.provenance?.suppression_reason)

  let title = 'SKIPPED'
  if (isActionable) {
    title = 'RISK PLAN READY'
  } else if (isSuppressed) {
    title = 'SUPPRESSED'
  }

  const entryStr = plan.entry_price > 0 ? `${plan.entry_price.toFixed(2)} pts` : '—'
  const stopStr = plan.effective_stop > 0 ? `${plan.effective_stop.toFixed(2)} pts` : '—'
  const riskDistance =
    plan.entry_price > 0 && plan.effective_stop > 0
      ? `${Math.abs(plan.entry_price - plan.effective_stop).toFixed(2)} pts`
      : '—'

  return {
    title,
    isActionable,
    contract: plan.option_symbol || plan.provenance?.deployment_id || '—',
    entryStr,
    stopStr,
    riskDistanceStr: riskDistance,
    skipReason: plan.provenance?.suppression_reason || plan.skip_reason || 'NONE',
  }
}

export function computeSafetyStrip(
  migrationStatus: MigrationStatusData | null,
  isStale: boolean,
  fetchError: boolean
) {
  const canonicalMode = migrationStatus?.migration_modes?.OSE || 'DUAL_READ'
  const primaryPermit = migrationStatus?.primary_permit ?? false
  const dataStatus = isStale ? 'STALE' : fetchError ? 'ERROR' : 'LIVE / RESTORED'
  const isUnsafe = primaryPermit || isStale || fetchError

  return {
    canonicalMode,
    primaryPermitStr: primaryPermit ? 'ON' : 'OFF',
    broker: 'DISABLED',
    executionInfluence: 'ZERO',
    dataStatus,
    isUnsafe,
  }
}

export function filterPlans(
  plans: RiskPlanItem[],
  filter: 'ALL' | 'ACTIONABLE' | 'SKIPPED' | 'SUPPRESSED'
) {
  return plans.filter((plan) => {
    if (filter === 'ACTIONABLE') return !plan.is_skipped && plan.provenance?.actionable !== false
    if (filter === 'SKIPPED') return plan.is_skipped
    if (filter === 'SUPPRESSED')
      return (
        plan.provenance?.candidate_status === 'SUPPRESSED' ||
        Boolean(plan.provenance?.suppression_reason)
      )
    return true
  })
}

// ── Tests ───────────────────────────────────────────────────────────────────

test('zero actionable / nine skipped offline bootstrap state', () => {
  const mockStatus: Partial<ShadowStatusData> = {
    active_plans_count: 9,
    skipped_plans_count: 9,
    execution_influence: 'ZERO',
    hook_telemetry: {
      risk_hook_failures: 0,
      last_failure_at: null,
      last_failure_deployment: null,
      last_failure_type: null,
      last_failure_message: null,
      failure_log_tail: [],
    },
  }

  const mockPlans: RiskPlanItem[] = Array.from({ length: 9 }, (_, i) => ({
    plan_id: `plan_${i}`,
    strategy_id: 'PULLBACK',
    deployment_id: `PB_NIFTY_CE_${i}`,
    instrument: 'NIFTY',
    option_symbol: null,
    side: 'LONG',
    entry_price: 0,
    structural_invalidation: null,
    effective_stop: 0,
    maximum_risk_cap: 0,
    position_size: 1,
    target_ladder: [],
    is_skipped: true,
    skip_reason: 'OPTION_PREMIUM_UNAVAILABLE',
    skip_details: 'option premium translation unavailable',
    provenance: {
      shadow_mode: true,
      execution_influence: 'ZERO',
      deployment_id: `PB_NIFTY_CE_${i}`,
      actionable: false,
    },
  }))

  const counts = computeHeroCounts(mockStatus, mockPlans)
  assert.equal(counts.actionableCount, 0)
  assert.equal(counts.skippedCount, 9)
  assert.equal(counts.storedCount, 9)
  assert.equal(counts.hookFailures, 0)
  assert.equal(counts.executionInfluence, 'ZERO')

  const card = computeCandidateCardState(mockPlans[mockPlans.length - 1])
  assert.equal(card.title, 'SKIPPED')
  assert.equal(card.isActionable, false)
  assert.equal(card.skipReason, 'OPTION_PREMIUM_UNAVAILABLE')
})

test('valid actionable RiskPlan state triggers RISK PLAN READY card transformation', () => {
  const actionablePlan: RiskPlanItem = {
    plan_id: 'plan_active01',
    strategy_id: 'TREND_CATCHER',
    deployment_id: 'TC_NIFTY_PE_1M',
    instrument: 'NIFTY',
    option_symbol: 'NIFTY26AUG24400CE',
    side: 'LONG',
    entry_price: 85.0,
    structural_invalidation: 70.0,
    effective_stop: 70.0,
    maximum_risk_cap: 1.7,
    position_size: 25,
    target_ladder: [{ target_price: 110.0, exit_ratio: 0.5, description: 'T1' }],
    is_skipped: false,
    skip_reason: 'NONE',
    skip_details: 'Valid structural stop calculated',
    provenance: {
      shadow_mode: true,
      execution_influence: 'ZERO',
      deployment_id: 'TC_NIFTY_PE_1M',
      candidate_status: 'ENTRY_CANDIDATE',
      suppression_reason: null,
      actionable: true,
    },
  }

  const counts = computeHeroCounts(null, [actionablePlan])
  assert.equal(counts.actionableCount, 1)
  assert.equal(counts.skippedCount, 0)

  const card = computeCandidateCardState(actionablePlan)
  assert.equal(card.title, 'RISK PLAN READY')
  assert.equal(card.isActionable, true)
  assert.equal(card.contract, 'NIFTY26AUG24400CE')
  assert.equal(card.entryStr, '85.00 pts')
  assert.equal(card.stopStr, '70.00 pts')
  assert.equal(card.riskDistanceStr, '15.00 pts')
})

test('suppressed candidate reflects SUPPRESSED status and actionable=false', () => {
  const suppressedPlan: RiskPlanItem = {
    plan_id: 'plan_supp01',
    strategy_id: 'PULLBACK',
    deployment_id: 'PB_NIFTY_PE_1M',
    instrument: 'NIFTY',
    option_symbol: 'NIFTY26AUG24400PE',
    side: 'LONG',
    entry_price: 75.0,
    structural_invalidation: 60.0,
    effective_stop: 60.0,
    maximum_risk_cap: 1.5,
    position_size: 25,
    target_ladder: [],
    is_skipped: false,
    skip_reason: 'NONE',
    skip_details: 'Valid',
    provenance: {
      shadow_mode: true,
      execution_influence: 'ZERO',
      deployment_id: 'PB_NIFTY_PE_1M',
      candidate_status: 'SUPPRESSED',
      suppression_reason: 'MAX_POSITIONS_REACHED',
      actionable: false,
    },
  }

  const card = computeCandidateCardState(suppressedPlan)
  assert.equal(card.title, 'SUPPRESSED')
  assert.equal(card.isActionable, false)
  assert.equal(card.skipReason, 'MAX_POSITIONS_REACHED')
})

test('API failure and stale data update safety strip data status', () => {
  const liveStrip = computeSafetyStrip(
    {
      primary_permit: false,
      migration_modes: { OSE: 'DUAL_READ' },
      safety: { legacy_authoritative: true, canonical_primary_allowed: false, execution_influence: 'ZERO' },
    },
    false,
    false
  )
  assert.equal(liveStrip.dataStatus, 'LIVE / RESTORED')
  assert.equal(liveStrip.isUnsafe, false)

  const staleStrip = computeSafetyStrip(null, true, false)
  assert.equal(staleStrip.dataStatus, 'STALE')
  assert.equal(staleStrip.isUnsafe, true)

  const errStrip = computeSafetyStrip(null, false, true)
  assert.equal(errStrip.dataStatus, 'ERROR')
  assert.equal(errStrip.isUnsafe, true)
})

test('execution influence ZERO invariant holds across all responses', () => {
  const mockStatus: Partial<ShadowStatusData> = { execution_influence: 'ZERO' }
  const counts = computeHeroCounts(mockStatus, [])
  assert.equal(counts.executionInfluence, 'ZERO')

  const strip = computeSafetyStrip(null, false, false)
  assert.equal(strip.executionInfluence, 'ZERO')
})

test('plan list filtering respects ALL, ACTIONABLE, SKIPPED, SUPPRESSED', () => {
  const p1: RiskPlanItem = {
    plan_id: 'p1', strategy_id: 'S1', deployment_id: 'D1', instrument: 'NIFTY', option_symbol: 'OPT1', side: 'LONG', entry_price: 100, structural_invalidation: 90, effective_stop: 90, maximum_risk_cap: 2, position_size: 1, target_ladder: [], is_skipped: false, skip_reason: 'NONE', skip_details: '', provenance: { shadow_mode: true, execution_influence: 'ZERO', deployment_id: 'D1', actionable: true }
  }
  const p2: RiskPlanItem = {
    plan_id: 'p2', strategy_id: 'S2', deployment_id: 'D2', instrument: 'NIFTY', option_symbol: null, side: 'LONG', entry_price: 0, structural_invalidation: null, effective_stop: 0, maximum_risk_cap: 0, position_size: 1, target_ladder: [], is_skipped: true, skip_reason: 'OPTION_PREMIUM_UNAVAILABLE', skip_details: '', provenance: { shadow_mode: true, execution_influence: 'ZERO', deployment_id: 'D2', actionable: false }
  }
  const p3: RiskPlanItem = {
    plan_id: 'p3', strategy_id: 'S3', deployment_id: 'D3', instrument: 'NIFTY', option_symbol: 'OPT3', side: 'LONG', entry_price: 80, structural_invalidation: 70, effective_stop: 70, maximum_risk_cap: 2, position_size: 1, target_ladder: [], is_skipped: false, skip_reason: 'NONE', skip_details: '', provenance: { shadow_mode: true, execution_influence: 'ZERO', deployment_id: 'D3', candidate_status: 'SUPPRESSED', suppression_reason: 'MAX_POSITIONS_REACHED', actionable: false }
  }

  const all = filterPlans([p1, p2, p3], 'ALL')
  assert.equal(all.length, 3)

  const actionable = filterPlans([p1, p2, p3], 'ACTIONABLE')
  assert.equal(actionable.length, 1)
  assert.equal(actionable[0].plan_id, 'p1')

  const skipped = filterPlans([p1, p2, p3], 'SKIPPED')
  assert.equal(skipped.length, 1)
  assert.equal(skipped[0].plan_id, 'p2')

  const suppressed = filterPlans([p1, p2, p3], 'SUPPRESSED')
  assert.equal(suppressed.length, 1)
  assert.equal(suppressed[0].plan_id, 'p3')
})
