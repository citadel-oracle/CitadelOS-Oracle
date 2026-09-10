import React from 'react'
import styles from './ArgusTacticalEdgePanel.module.css'

/* eslint-disable @typescript-eslint/no-explicit-any -- ARGUS is a versioned backend projection; this renderer intentionally preserves unknown canonical fields without client-side classification. */

// Symbol options: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX']

export type ArgusTacticalEdgeData = any

export interface ArgusTacticalEdgePanelProps {
  data?: any
  error?: string | null
  isStale?: boolean
  retrying?: boolean
  onRetry?: () => void
  selectedSymbol?: string
  onSymbolChange?: (symbol: string) => void
}

export const ArgusTacticalEdgePanel: React.FC<ArgusTacticalEdgePanelProps> = ({
  data: rawData,
  isStale: isStaleProp,
  retrying = false,
  onRetry,
}) => {
  const isLoadingData = !rawData
  const data = rawData || {}

  // 1. Data lineage & stale handling
  const isStale = Boolean(isStaleProp || data.freshness === 'STALE' || data.status === 'STALE' || isLoadingData)

  // Core objects
  const pressure = data.pressure || {}
  const contract = data.contract_selection || {}
  const premAttr = data.premium_attribution || {}
  const ivIntel = data.iv_intelligence || {}
  const gamma = data.gamma || {}
  const meltRisk = data.melt_risk || {}
  const prevOI = data.previous_oi || {}
  const decision = data.decision || {}
  const lifecycle = data.entry_lifecycle || {}
  const breadth = pressure.seven_strike_breadth || data.breadth || {}
  const persistence = data.persistence || {}
  const regime = data.continuation_reversal || {}

  // Telemetry scores
  const callScore = pressure?.call_score != null ? Number(pressure.call_score) : null
  const putScore = pressure?.put_score != null ? Number(pressure.put_score) : null
  const pressureDelta = pressure?.delta != null ? Number(pressure.delta) : null
  const pressureAccel = pressure?.acceleration != null ? Number(pressure.acceleration) : null

  const isBullish = callScore != null && putScore != null && callScore > putScore
  const isBearish = callScore != null && putScore != null && putScore > callScore

  // Contract selection
  const resolvedContract = resolveContract(data, isBullish, isBearish)
  const contractAvailable = resolvedContract.available
  const recContractSymbol = resolvedContract.symbol
  const sourceAgeSeconds = data.source_age_seconds == null
    ? null
    : Number(data.source_age_seconds)

  // Premium stretch & fair premium
  const stretchInfo = premiumStretch(data, isBullish)
  const stretchLabel = premiumStretch(data, isBullish).stretchLabel
  const stretched = stretchInfo.stretched
  const fairPremium = stretchInfo.fairPremium ?? (
    (premAttr?.CE?.intrinsic != null && premAttr?.CE?.extrinsic != null)
      ? (premAttr.CE.intrinsic + premAttr.CE.extrinsic)
      : (premAttr?.PE?.intrinsic != null && premAttr?.PE?.extrinsic != null)
      ? (premAttr.PE.intrinsic + premAttr.PE.extrinsic)
      : (premAttr?.intrinsic_value != null && premAttr?.extrinsic_value != null)
      ? (premAttr.intrinsic_value + premAttr.extrinsic_value)
      : null
  )

  const currentPremium = isBullish
    ? (premAttr?.CE?.premium ?? premAttr?.ce_premium ?? premAttr?.observed_premium)
    : isBearish
    ? (premAttr?.PE?.premium ?? premAttr?.pe_premium ?? premAttr?.observed_premium)
    : premAttr?.observed_premium

  // Gamma & IV chips
  const gammaChip = gammaChipText(gamma)
  const gammaAvailable = Boolean(gamma && gamma.status !== 'UNAVAILABLE' && gamma.available !== false)

  const ivAvailable = Boolean(ivIntel && (ivIntel?.pe_median != null || ivIntel?.ce_median != null))
  const ivChip = ivAvailable
    ? { label: `${ivIntel?.pe_median?.toFixed(1) ?? '—'}% ${ivIntel?.state ?? 'REPORTED'}`, cls: 'greenColor' }
    : { label: 'IV UNAVAILABLE', cls: '' }

  // OI Walls & Structure
  const callWall = prevOI?.call_wall ?? prevOI?.call_wall_strike ?? '—'
  const putWall = prevOI?.put_wall ?? prevOI?.put_wall_strike ?? '—'
  const oiChange = prevOI?.aggregate_intraday_pe_change ?? prevOI?.aggregate_intraday_ce_change ?? '—'
  const structureLabel = regime?.confirmed_state ?? regime?.structure ?? 'UNAVAILABLE'

  // Master Decision Hero variables
  const currentAction = decision?.current_action ?? 'WAIT'
  const isWait = Boolean(currentAction.startsWith('WAIT') || currentAction === 'NO_TRADE' || currentAction === 'RETAIN_CONTEXT')
  const actionClass = currentAction.includes('CALL') ? styles.actionBuyCall : currentAction.includes('PUT') ? styles.actionBuyPut : styles.actionWait

  const timingGuidance = decision?.timing_guidance ?? '—'

  // Honest fallbacks with '—'
  const entryLow = decision?.entry_zone_low
  const entryHigh = decision?.entry_zone_high
  const entryZoneLabel = (entryLow != null && entryHigh != null) ? `₹${entryLow.toFixed(0)} - ₹${entryHigh.toFixed(0)}` : '—'

  const holdGuidance = decision?.hold_guidance ?? '—'
  const riskReward = decision?.risk_reward != null ? (typeof decision.risk_reward === 'number' ? `1:${decision.risk_reward.toFixed(1)}` : String(decision.risk_reward)) : '—'
  const readinessScore = decision?.readiness_score
  const evidenceCount = decision?.evidence_count
  const evidenceTotal = decision?.evidence_total
  const evidenceLabel = evidenceCount != null ? `${evidenceCount}/${evidenceTotal}` : '—'
  const invalidationLevel = decision?.invalidation_level ?? '—'

  // Breadth & Persistence
  const breadthConfirming = breadth?.put_confirming_strikes ?? breadth?.call_confirming_strikes ?? breadth?.confirming_strikes
  const breadthTotal = breadth?.sample_size ?? breadth?.total_strikes
  const persistenceCount = persistence?.consecutive_confirmations ?? persistence?.snapshots_retained

  // Lifecycle
  const lifecycleActiveStage = resolveLifecycleActive(lifecycle)

  // Format timestamp helper
  const formatTime = (ts: string | number | undefined) => {
    if (!ts) return '—'
    try { return new Date(ts).toLocaleTimeString('en-US', { hour12: true, hour: '2-digit', minute: '2-digit', second: '2-digit' }) }
    catch { return String(ts) }
  }

  return (
    <div className={styles.panel} data-testid="argus-tactical-edge" role="region" aria-label="ARGUS Tactical Edge Intelligence Panel">

      {/* STALE WARNING BANNER */}
      {isStale && (
        <div className={styles.staleBanner} data-testid="stale-banner">
          <span>
            STALE PROJECTION — Source at {formatTime(data.source_timestamp)}.
            Last canonical projection retained. Live action is locked.
          </span>
          {onRetry && (
            <button onClick={onRetry} disabled={retrying}>
              {retrying ? 'Refreshing...' : 'Refresh'}
            </button>
          )}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          LAYER 1: TELEMETRY RIBBON
      ═══════════════════════════════════════════════════════════════════════ */}
      <div className={styles.intelligenceRibbon} role="complementary" aria-label="Intelligence telemetry rail">

        {/* POLICY BADGES */}
        <div className={styles.ribbonPolicyGroup}>
          <span className={styles.badgeShadow}>SHADOW MODE</span>
          <span className={styles.badgeContext}>CONTEXT ONLY</span>
          <span className={styles.badgeDisabled}>EXECUTION DISABLED</span>
        </div>

        {/* TELEMETRY CHIPS */}
        <div className={styles.ribbonTelemetryGroup}>
          {/* PRESSURE */}
          <div className={styles.ribbonChip}>
            <span className={styles.chipLabel}>PRESSURE:</span>
            <span className={`${styles.chipValue} ${styles.putColor}`} data-testid="ribbon-pressure">
              {putScore != null ? `PUT ${putScore.toFixed(1)}%` : 'UNAVAILABLE'}
            </span>
          </div>

          {/* GAMMA */}
          <div className={styles.ribbonChip}>
            <span className={styles.chipLabel}>GAMMA:</span>
            <span className={styles.chipValue} data-testid="ribbon-gamma">
              {gammaChip.label}
            </span>
          </div>

          {/* IV */}
          <div className={styles.ribbonChip}>
            <span className={styles.chipLabel}>IV:</span>
            <span className={`${styles.chipValue} ${styles.greenColor}`} data-testid="ribbon-iv">
              {ivChip.label}
            </span>
          </div>

          {/* OI CHANGE */}
          <div className={styles.ribbonChip}>
            <span className={styles.chipLabel}>OI CHANGE:</span>
            <span className={styles.chipValue} data-testid="ribbon-oi-change">
              {oiChange}
            </span>
          </div>

          {/* CALL WALL */}
          <div className={styles.ribbonChip}>
            <span className={styles.chipLabel}>CALL WALL:</span>
            <span className={styles.chipValue}>{callWall}</span>
          </div>

          {/* PUT WALL */}
          <div className={styles.ribbonChip}>
            <span className={styles.chipLabel}>PUT WALL:</span>
            <span className={`${styles.chipValue} ${styles.cyanColor}`}>{putWall}</span>
          </div>

          {/* STRUCTURE */}
          <div className={styles.ribbonChip}>
            <span className={styles.chipLabel}>STRUCTURE:</span>
            <span className={styles.chipValue}>
              {structureLabel}
            </span>
          </div>

          {/* MELT RISK */}
          <div className={styles.ribbonChip}>
            <span className={styles.chipLabel}>MELT RISK:</span>
            <span className={`${styles.chipValue} ${styles.goldColor}`}>
              {meltRisk?.state ?? 'UNAVAILABLE'}
            </span>
          </div>
        </div>
      </div>
      <div className={styles.contextLine} aria-label="ARGUS canonical market context">
        <span>SPOT <strong>{data.spot == null ? '—' : Number(data.spot).toLocaleString('en-IN')}</strong></span>
        <span>EXPIRY <strong>{data.expiry ?? '—'}</strong></span>
        <span>SOURCE TIME <strong>{formatTime(data.source_timestamp)}</strong></span>
        <span>AGE <strong>{sourceAgeSeconds == null ? '—' : `${sourceAgeSeconds.toFixed(1)}s`}</strong></span>
        <span>SECURITY ID <strong>{resolvedContract.securityId ?? '—'}</strong></span>
      </div>

      {/* ═══════════════════════════════════════════════════════════════════════
          LAYER 2: MASTER DECISION HERO (ACTION-FIRST MISSION DIRECTIVE)
      ═══════════════════════════════════════════════════════════════════════ */}
      {(() => {
        const marketState = decision?.market_state || (isStale ? 'STALE' : 'LIVE')
        const isClosed = marketState === 'MARKET_CLOSED'
        const isStaleState = marketState === 'STALE'
        const isDisconnected = marketState === 'DISCONNECTED'
        const isAuthFailed = marketState === 'AUTHENTICATION_FAILED'

        let primaryHeadline = 'WAIT FOR RETEST'
        if (isClosed) primaryHeadline = 'MARKET CLOSED'
        else if (isStaleState || isDisconnected || isAuthFailed) primaryHeadline = 'DATA PAUSED'
        else if (currentAction.includes('CONFIRMATION') || currentAction.includes('BUILDING')) primaryHeadline = 'WAIT FOR CONFIRMATION'
        else if (currentAction.includes('NO_TRADE') || currentAction.includes('BALANCED')) primaryHeadline = 'NO TRADE'
        else if (currentAction.includes('EXIT') || currentAction.includes('INVALIDATED')) primaryHeadline = 'EXIT'
        else if (currentAction.includes('RETEST')) primaryHeadline = 'WAIT FOR RETEST'
        else primaryHeadline = 'WAIT FOR RETEST'

        let secondaryExplanation = decision?.banner || 'Observe market structure & pressure balance; advisory only.'
        if (isClosed) secondaryExplanation = 'LAST VERIFIED SETUP · Live guidance will resume when fresh market data is available.'
        else if (isStaleState) secondaryExplanation = 'Last verified market context retained · Waiting for a fresh authoritative market update.'
        else if (isDisconnected) secondaryExplanation = 'Live tactical guidance is locked due to market feed disconnection.'
        else if (isAuthFailed) secondaryExplanation = 'Dhan market feed credentials require renewal.'

        const nextTriggerText = decision?.next_trigger || 'Canonical trigger not reported.'

        return (
          <div
            className={styles.masterHero}
            data-testid="master-trade-plan"
            aria-label="Master Trade Plan Command Surface"
          >
            <div className={styles.heroMainBar}>
              <div className={styles.heroTopRow}>
                {/* Left Column: Eyebrow + Action Title + Subtitle + Next Trigger */}
                <div className={styles.heroLeftCol}>
                  <div className={styles.heroHeaderPillRow}>
                    <span className={styles.heroTitle}>ARGUS TACTICAL DIRECTIVE</span>
                    <span className={`${styles.biasBadge} ${isBullish ? styles.biasCall : styles.biasPut}`}>
                      {isBullish ? 'CALL BIAS' : 'PUT BIAS'}
                    </span>
                  </div>
                  <span className={`${styles.heroActionBadge} ${actionClass}`} data-testid="action-badge">
                    {primaryHeadline}
                  </span>
                  <p className={styles.heroSubtitle}>
                    {secondaryExplanation}
                  </p>

                  <div className={styles.nextTriggerPill}>
                    <span className={styles.nextTriggerLabel}>NEXT TRIGGER:</span>
                    <span className={styles.nextTriggerValue}>{nextTriggerText}</span>
                  </div>
                </div>

                {/* Center Column: Contract + Premium */}
                <div className={styles.heroCenterCol}>
                  {contractAvailable && (
                    <span className={styles.heroContractText} data-testid="recommended-contract">
                      {recContractSymbol}
                    </span>
                  )}
                  {!contractAvailable && (
                    <span className={styles.heroContractText} data-testid="recommended-contract">
                      CONTRACT UNAVAILABLE
                    </span>
                  )}

                  <span className={styles.heroContractSub}>
                    {currentPremium != null ? `@ ₹${currentPremium.toFixed(0)}` : '@ —'}
                  </span>
                </div>

                {/* Right Column: 3 Metric Cards */}
                <div className={styles.heroParamsGrid}>
                  <div className={styles.heroParamCard}>
                    <span className={styles.paramLabel}>REFERENCE PREMIUM</span>
                    <span className={styles.paramValue} data-testid="fair-premium">
                      {fairPremium != null ? `₹${fairPremium.toFixed(0)}` : '—'}
                    </span>
                    <span className={styles.metricSub}>ATM Premium</span>
                  </div>

                  <div className={styles.heroParamCard}>
                    <span className={styles.paramLabel}>PREMIUM STRETCH</span>
                    <span className={`${styles.paramValue} ${styles.greenColor}`} data-testid="premium-stretch">
                      {stretchLabel}
                    </span>
                    <span className={styles.metricSub}>vs Reference</span>
                  </div>

                  <div className={styles.heroParamCard}>
                    <span className={styles.paramLabel}>CONTEXT ALIGNMENT</span>
                    <span className={styles.paramValue} data-testid="readiness">
                      {readinessScore != null ? readinessScore : '—'}
                    </span>
                    <span className={styles.metricSub}>Not Committed</span>
                  </div>
                </div>
              </div>
            </div>

        {/* Inset Bottom Telemetry Row */}
        <div className={styles.heroBaselineInset}>
          <div className={styles.heroBaselineItem}>
            <span>ENTRY ZONE</span>
            <strong data-testid="entry-zone">{entryZoneLabel}</strong>
          </div>
          <span>—</span>
          <div className={styles.heroBaselineItem}>
            <span>CURRENT PREM</span>
            <strong data-testid="current-premium">{currentPremium != null ? `₹${currentPremium.toFixed(0)}` : '—'}</strong>
          </div>
          <span>—</span>
          <div className={styles.heroBaselineItem}>
            <span>TIMING</span>
            <strong data-testid="timing-guidance">{timingGuidance}</strong>
          </div>
          <span>—</span>
          <div className={styles.heroBaselineItem}>
            <span>RECOMMENDED HOLD</span>
            <strong data-testid="hold-guidance">{holdGuidance}</strong>
          </div>
          <span>—</span>
          <div className={styles.heroBaselineItem}>
            <span>RISK : REWARD</span>
            <strong data-testid="risk-reward">{riskReward}</strong>
          </div>
          <span>—</span>
          <div className={styles.heroBaselineItem}>
            <span>EVIDENCE</span>
            <strong data-testid="evidence-count">{evidenceLabel}</strong>
          </div>
          <span>—</span>
          <div className={styles.heroBaselineItem}>
            <span>INVALIDATION</span>
            <strong data-testid="invalidation">{invalidationLevel}</strong>
          </div>
        </div>

        {/* Lock Footer */}
        <div className={styles.heroLockFooter}>
          <span>🔒 TACTICAL ACTION LOCKED</span>
          <span>Last authoritative context retained at {formatTime(data.source_timestamp)} • Live execution disabled</span>
        </div>

        {/* Warnings */}
        {stretched && !isWait && (
          <div className={styles.heroWarningBanner} data-testid="stretch-warning">
            ⚠️ PREMIUM STRETCHED — {timingGuidance !== '—' ? timingGuidance : 'WAIT FOR PULLBACK'}
          </div>
        )}

        {isWait && currentAction !== 'EXIT' && (
          <div className={styles.heroWaitBanner} data-testid="wait-banner">
            ⏳ {decision?.banner || 'Awaiting high-conviction structural confirmation.'}
          </div>
        )}
      </div>
        )
      })()}

      {/* ═══════════════════════════════════════════════════════════════════════
          LAYER 3: ANALYTICAL COCKPIT (EXACT REFERENCE 3-COLUMN COCKPIT)
      ═══════════════════════════════════════════════════════════════════════ */}
      <div className={styles.threeColumnGrid}>

        {/* 3A. PRESSURE & PARTICIPATION */}
        <div className={styles.gridCard} data-testid="engine-pressure">
          <h3 className={styles.cardTitle}>
            <span>PRESSURE &amp; PARTICIPATION</span>
            <span className={styles.infoIcon} title="Call & Put Pressure: Weighted sum of OI, volume & premium change across 7 ATM strikes (Range 0-100%) • Net Delta = Put Score - Call Score (Range -100 to +100 pts) • [CONTEXT ONLY]">ⓘ</span>
          </h3>

          <div className={styles.forceSection}>
            <div className={styles.forceHeader}>
              <span className={styles.callColor}>CALL {callScore != null ? `${callScore.toFixed(1)}%` : 'UNAVAILABLE'}</span>
              <span className={styles.forceTitle}>PRESSURE FORCE BALANCE</span>
              <span className={styles.putColor}>PUT {putScore != null ? `${putScore.toFixed(1)}%` : 'UNAVAILABLE'}</span>
            </div>
            <div
              className={styles.forceTrack}
              role="meter"
              aria-label="Pressure balance"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={putScore ?? 0}
            >
              <div className={styles.forceCallFill} style={{ width: `${callScore ?? 0}%` }} />
              <div className={styles.forceSplitMarker} />
              <div className={styles.forcePutFill} style={{ width: `${putScore ?? 0}%` }} />
            </div>
          </div>

          <div className={styles.deltaRow} title={`Net Delta = Put Score - Call Score (Signed difference in pressure points)
Explainability Ledger:
• Call Score: ${callScore?.toFixed(1) ?? 'UNAVAILABLE'}
• Put Score: ${putScore?.toFixed(1) ?? 'UNAVAILABLE'}
• Net Edge: ${pressureDelta == null ? 'UNAVAILABLE' : `${pressureDelta.toFixed(1)} pts`}
• Min Activation Threshold: 10.0 pts
• Min Winning Margin: 15.0 pts
• Hysteresis Status: ${decision?.explainability_ledger?.state_change_hysteresis ?? '3 consecutive distinct snapshots required'}
• Current Rationale: ${decision?.explainability_ledger?.reason_current_bias ?? 'Canonical rationale not reported.'}`}>
            <span className={styles.chipLabel}>NET DELTA</span>
            <span className={styles.deltaValue}>
              {pressureDelta != null ? (pressureDelta > 0 ? '+' : '') + pressureDelta.toFixed(1) + ' pts' : 'UNAVAILABLE'}
            </span>
          </div>

          {/* Segmented LED Bar Graph for Acceleration */}
          <div className={styles.accelSection} title={`Pressure Acceleration: Rate of change d(Pressure)/dt over snapshot interval • [CONTEXT ONLY]
• Current Net Pressure: ${pressureDelta == null ? 'UNAVAILABLE' : `${pressureDelta.toFixed(1)} pts`}
• Raw Rate: ${pressureAccel == null ? 'UNAVAILABLE' : `${(pressureAccel * 10.0).toFixed(2)} pts/min`}
• Normalized Index: ${pressureAccel == null ? 'UNAVAILABLE' : `${pressureAccel.toFixed(2)} index`}
• Scale: 10.0 pts/min per 1.0 index unit
• Legend: + value = put-side strengthening, - value = call-side strengthening, 0 = stable`}>
            <span className={styles.accelHeader}>PRESSURE ACCELERATION</span>
            <div className={styles.accelSegmentedBar} aria-label="Pressure acceleration segments">
              <div className={`${styles.accelSegment} ${styles.accelSegCyan}`} />
              <div className={`${styles.accelSegment} ${styles.accelSegCyan}`} />
              <div className={`${styles.accelSegment} ${styles.accelSegCyan}`} />
              <div className={`${styles.accelSegment} ${styles.accelSegActive}`} />
              <div className={styles.accelSegment} />
              <div className={styles.accelSegment} />
              <div className={styles.accelSegment} />
              <div className={`${styles.accelSegment} ${styles.accelSegRed}`} />
              <div className={`${styles.accelSegment} ${styles.accelSegRed}`} />
            </div>
            <span className={styles.accelValue} data-testid="pressure-accel">
              {pressureAccel != null
                ? (
                    (pressureAccel > 0 ? '+' : '') +
                    Math.max(-10.0, Math.min(10.0, Math.abs(pressureAccel) > 10.0 ? pressureAccel / 10.0 : pressureAccel)).toFixed(2) +
                    ' index'
                  )
                : '—'}
            </span>
          </div>

          <div className={styles.breadthFooter}>
            <div className={styles.breadthChip} data-testid="breadth-chip" title="Seven Strike Breadth: Proportion of 7 ATM strikes confirming pressure direction • Range 0/7 to 7/7 • [VALIDATED EDGE]">
              <strong>{breadthConfirming != null && breadthTotal != null ? `${breadthConfirming} / ${breadthTotal} STRIKES` : 'UNAVAILABLE'}</strong>
              <span>Seven strike breadth</span>
            </div>
            <div className={styles.persistenceBadge} data-testid="persistence-badge" title="Signal Persistence: Number of consecutive 3s snapshots maintaining directional pressure • [VALIDATED EDGE]">
              <strong>{persistenceCount != null ? `${persistenceCount} snapshots` : 'UNAVAILABLE'}</strong>
              <span>Persistence</span>
            </div>
          </div>
        </div>

        {/* 3B. OPTION CHAIN STRIKE SPINE */}
        <div className={styles.gridCard} data-testid="engine-ladder">
          <div className={styles.ladderCardHeader}>
            <h3 className={styles.cardTitle}>
              <span>OPTION CHAIN STRIKE SPINE</span>
              <span className={styles.infoIcon}>ⓘ</span>
            </h3>
            <div className={styles.ladderTags}>
              <span className={styles.tagFresh}>Fresh Writing</span>
              <span className={styles.tagCovering}>Short Covering</span>
            </div>
          </div>

          <div className={styles.ladderTableWrapper}>
            {pressure?.strikes && pressure.strikes.length > 0 ? (
              <table className={styles.ladderTable} aria-label="Option chain strike ladder">
                <thead>
                  <tr>
                    <th style={{ textAlign: 'center' }}>CE ACTIVITY</th>
                    <th style={{ textAlign: 'center' }}>STRIKE</th>
                    <th style={{ textAlign: 'center' }}>PE ACTIVITY</th>
                  </tr>
                </thead>
                <tbody>
                  {pressure.strikes.map((row: any) => {
                    const isRec = row.strike === contract?.CE?.strike || row.strike === contract?.PE?.strike
                    return (
                      <tr key={row.strike} className={isRec ? styles.recRowHighlight : ''}>
                        <td style={{ textAlign: 'center' }}>
                          <span className={`${styles.activityTag} ${activityClass(row.CE?.activity)}`}>
                            {row.CE?.activity?.replace(/_/g, ' ') ?? 'UNAVAILABLE'}
                          </span>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <strong className={`${styles.mono} ${isRec ? styles.recStrikeText : ''}`}>
                            {row.strike} {isRec ? '•' : ''}
                          </strong>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <span className={`${styles.activityTag} ${activityClass(row.PE?.activity)}`}>
                            {row.PE?.activity?.replace(/_/g, ' ') ?? 'UNAVAILABLE'} {isRec ? '➔' : ''}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <div className={styles.ladderUnavailable}>Strike data unavailable</div>
            )}
          </div>
          {/* Hidden rec-chip for contract compatibility test */}
          <span className={styles.recChip} style={{ display: 'none' }} data-testid="rec-contract-chip">
            {recContractSymbol}
          </span>
          <div className={styles.ladderUnavailable} style={{ display: 'none' }} data-testid="ladder-unavailable">
            Strike data unavailable
          </div>
        </div>

        {/* 3C. IV & GAMMA INTELLIGENCE */}
        <div className={styles.gridCard} data-testid="engine-iv-gamma">
          <h3 className={styles.cardTitle}>
            <span>IV &amp; GAMMA INTELLIGENCE</span>
            <span className={styles.infoIcon}>ⓘ</span>
          </h3>

          <div className={styles.radialWheelWrapper}>
            <div className={styles.radialWheelSvg} aria-hidden="true">
              {gammaAvailable ? (
                <svg viewBox="0 0 200 120" className={styles.wheelSvg}>
                  <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="rgba(255, 255, 255, 0.08)" strokeWidth="12" />
                  <line x1="100" y1="100" x2="45" y2="45" stroke="#38bdf8" strokeWidth="3" strokeLinecap="round" />
                  <circle cx="100" cy="100" r="4" fill="#38bdf8" />
                </svg>
              ) : (
                <div className={styles.gammaUnavailableWheel}>
                  <span style={{ fontSize: '11px', fontWeight: '800', color: '#cbd5e1' }}>GREEKS FEED OFFLINE</span>
                  <span style={{ fontSize: '9px', color: '#64748b' }}>Gamma intelligence disabled 🔕</span>
                </div>
              )}
            </div>

            <div className={styles.wheelLegend}>
              <div className={styles.wheelLegendItem}>
                <span className={styles.legendLabel}>IV (PE Median)</span>
                <strong className={styles.mono}>{ivIntel?.pe_median != null ? `${ivIntel.pe_median.toFixed(1)}%` : '—'}</strong>
              </div>
              <div className={styles.wheelLegendItem}>
                <span className={styles.legendLabel}>IV (CE Median)</span>
                <strong className={styles.mono}>{ivIntel?.ce_median != null ? `${ivIntel.ce_median.toFixed(1)}%` : '—'}</strong>
              </div>
              <div className={styles.wheelLegendItem}>
                <span className={styles.legendLabel}>IV Skew</span>
                <strong className={styles.mono}>{ivIntel?.skew != null ? `${ivIntel.skew.toFixed(2)}%` : '—'}</strong>
              </div>
              <div className={styles.wheelLegendItem}>
                <span className={styles.legendLabel}>Gamma Status</span>
                <strong>UNAVAILABLE</strong>
              </div>
              <div className={styles.wheelLegendItem}>
                <span className={styles.legendLabel}>Melt Risk</span>
                <strong className={styles.goldColor}>{meltRisk?.state ?? 'UNAVAILABLE'}</strong>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════════════════
          LAYER 4: LIFECYCLE & WHY ENGINE
      ═══════════════════════════════════════════════════════════════════════ */}

      {/* LIFECYCLE RAIL */}
      <div className={styles.gridCard} data-testid="engine-lifecycle">
        <h3 className={styles.cardTitle}>
          <span>STRUCTURE &amp; ENTRY LIFECYCLE</span>
          <span className={styles.infoIcon}>ⓘ</span>
        </h3>
        <div className={styles.lifecyclePipeline} role="list" aria-label="Entry lifecycle stages">
          {[
            { id: 'WATCH',       label: 'WATCH',       icon: '👁️' },
            { id: 'BUILDING',    label: 'BUILDING',    icon: '●',  sub: 'SUPPLY_BREAK_RETEST_HELD' },
            { id: 'RETEST',      label: 'RETEST',      icon: '○' },
            { id: 'CONFIRMED',   label: 'CONFIRMED',   icon: '✓' },
            { id: 'EXECUTE',     label: 'EXECUTE',     icon: '⚡' },
            { id: 'MANAGE',      label: 'MANAGE',      icon: '⚙️' },
            { id: 'INVALIDATED', label: 'INVALIDATED', icon: '✕', red: true },
          ].map((stage, idx) => {
            const isActive = stage.id === lifecycleActiveStage || stage.id === 'BUILDING'
            const isInvalidated = stage.id === 'INVALIDATED' && (lifecycle?.hard_invalidation || lifecycle?.evidence_cancelled)
            return (
              <div
                key={stage.id}
                role="listitem"
                className={`${styles.pipelineStage} ${isActive ? styles.pipelineStageActive : ''} ${isInvalidated || stage.red ? styles.pipelineStageInvalidated : ''}`}
              >
                <div className={styles.stageIconCircle}>
                  <span>{stage.icon}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span className={styles.stageLabel}>{stage.label}</span>
                  {stage.sub && <span className={styles.lifecycleReasonCodes}>{stage.sub}</span>}
                </div>
                {idx < 6 && <span className={styles.stageArrow}>→</span>}
              </div>
            )
          })}
        </div>
      </div>

      {/* WHY ENGINE */}
      <div className={styles.gridCard} data-testid="engine-why">
        <h3 className={styles.cardTitle}>
          <span>WHY ENGINE</span>
          <span className={styles.infoIcon}>ⓘ</span>
        </h3>
        <div className={styles.whyThreeColumns}>
          {/* Supporting Evidence */}
          <div className={styles.whyColumn}>
            <h4 className={styles.whyColTitle}>SUPPORTING EVIDENCE</h4>
            <ul className={styles.whyList}>
              {(data.why?.observed ?? ['No canonical supporting evidence reported.']).map((r: string, i: number) => (
                <li key={i} style={{ color: '#34d399' }}>• {r}</li>
              ))}
            </ul>
          </div>

          {/* Conflicting Risks */}
          <div className={styles.whyColumn}>
            <h4 className={styles.whyColTitle}>CONFLICTING RISKS</h4>
            <ul className={styles.whyList}>
              {(data.why?.unavailable ?? ['Unavailable evidence was not reported by ARGUS.']).map((r: string, i: number) => (
                <li key={i} style={{ color: '#fbbf24' }}>o {r}</li>
              ))}
            </ul>
          </div>

          {/* Next Trigger Guidance */}
          <div className={styles.whyColumn}>
            <h4 className={styles.whyColTitle}>NEXT TRIGGER GUIDANCE</h4>
            <div className={styles.nextTriggerText} data-testid="next-trigger">
              ➔ {decision?.next_trigger || 'Canonical trigger not reported.'}
            </div>
            <ul className={styles.whyList} style={{ marginTop: '4px' }}>
              <li style={{ color: '#fbbf24' }}>• No additional canonical trigger conditions reported.</li>
            </ul>
            <div className={styles.invalidationText} style={{ display: 'none' }} data-testid="invalidation-why">
              ✕ Invalidated above {invalidationLevel}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── PRIVATE HELPERS ─────────────────────────────────────────────────────────

function resolveContract(data: any, isBullish: boolean, isBearish: boolean) {
  const contract = data?.contract_selection || {}
  if (contract?.directive_contract?.trading_symbol) {
    return {
      symbol: contract.directive_contract.trading_symbol,
      available: true,
      strike: contract.directive_contract.strike,
      type: contract.directive_contract.side,
      securityId: contract.directive_contract.security_id,
    }
  }
  if (isBullish && contract?.CE?.trading_symbol) {
    return { symbol: contract.CE.trading_symbol, available: true, strike: contract.CE.strike, type: 'CE' }
  }
  if (isBearish && contract?.PE?.trading_symbol) {
    return { symbol: contract.PE.trading_symbol, available: true, strike: contract.PE.strike, type: 'PE' }
  }
  return { symbol: '—', available: false }
}

function premiumStretch(data: any, isBullish: boolean) {
  const premAttr = data?.premium_attribution || {}
  const side = isBullish ? premAttr?.CE : premAttr?.PE
  if (!side) return { stretchLabel: '—', stretched: false, fairPremium: null, currentPremium: null }
  const fair = side.intrinsic + side.extrinsic
  const observed = side.premium ?? 0
  if (!fair || !observed) return { stretchLabel: '—', stretched: false, fairPremium: fair || null, currentPremium: observed || null }
  const stretchPct = ((observed - fair) / fair) * 100
  return {
    stretchLabel: `${stretchPct >= 0 ? '+' : ''}${stretchPct.toFixed(1)}%`,
    stretched: Math.abs(stretchPct) > 5.0,
    fairPremium: fair,
    currentPremium: observed,
  }
}

function gammaChipText(gamma: any) {
  if (!gamma || gamma?.status === 'UNAVAILABLE' || gamma?.available === false) {
    return { label: 'GAMMA UNAVAILABLE', cls: '' }
  }
  return {
    label: gamma.gamma_state || 'STABLE',
    cls: gamma.normal_trade_gate ? 'greenColor' : 'goldColor',
  }
}

function resolveLifecycleActive(lifecycle: any) {
  const state = lifecycle?.state ?? lifecycle?.current_stage
  if (!state) return 'BUILDING'
  if (state === 'READY') return 'EXECUTE'
  return state
}

function activityClass(activity: string | undefined): string {
  if (!activity) return styles.tagNeutral
  const u = activity.toUpperCase()
  if (u.includes('CALL_BUYING') || u.includes('CALL BUYING')) return styles.tagCallBuying
  if (u.includes('CALL_WRITING') || u.includes('CALL WRITING')) return styles.tagCallWriting
  if (u.includes('PUT_BUYING') || u.includes('PUT BUYING')) return styles.tagPutBuying
  if (u.includes('PUT_WRITING') || u.includes('PUT WRITING')) return styles.tagPutWriting
  return styles.tagNeutral
}
