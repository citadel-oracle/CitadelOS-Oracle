import React from 'react'
import styles from './ArgusPrimePanel.module.css'

/* eslint-disable @typescript-eslint/no-explicit-any -- backend-owned versioned ARGUS PRIME contract */

export interface ArgusPrimePanelProps {
  data?: any
  isStale?: boolean
  retrying?: boolean
  onRetry?: () => void
}

const show = (value: unknown, fallback = 'UNAVAILABLE') =>
  value === null || value === undefined || value === '' ? fallback : String(value)

const number = (value: unknown, digits = 0) => {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '—'
}

const price = (value: unknown) => {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed)
    ? `₹${parsed.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : 'UNAVAILABLE'
}

const compact = (value: unknown) => {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return '—'
  return Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 }).format(parsed)
}

const human = (value: unknown) => show(value).replaceAll('_', ' ')

const istTime = (value: unknown) => {
  if (!value) return 'UNAVAILABLE'
  const parsed = new Date(String(value))
  return Number.isNaN(parsed.getTime())
    ? 'UNAVAILABLE'
    : new Intl.DateTimeFormat('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
      }).format(parsed)
}

const flowTone = (value: unknown) => {
  const label = show(value, '').toUpperCase()
  if (
    label === 'BULLISH'
    || label.includes('CALL_BUYING')
    || label.includes('PUT_WRITING')
    || label.includes('CALL_SHORT_COVERING')
    || label.includes('PUT_LONG_UNWINDING')
  ) return styles.flowBull
  if (
    label === 'BEARISH'
    || label.includes('CALL_WRITING')
    || label.includes('PUT_BUYING')
    || label.includes('PUT_SHORT_COVERING')
    || label.includes('CALL_LONG_UNWINDING')
  ) return styles.flowBear
  return styles.flowNeutral
}

const arrow = (value: unknown) =>
  value === 'UP' ? '↑' : value === 'DOWN' ? '↓' : '→'

const contractName = (contract: any) => {
  if (!contract) return 'NO CONTRACT'
  return contract.trading_symbol
    ?? `${number(contract.strike)} ${show(contract.side)}`
}

const zone = (value: any) => (
  value?.low != null && value?.high != null
    ? `${price(value.low)}–${price(value.high).replace('₹', '')}`
    : 'UNAVAILABLE'
)

export const ArgusPrimePanel: React.FC<ArgusPrimePanelProps> = ({
  data,
  isStale = false,
  retrying = false,
  onRetry,
}) => {
  const prime = data?.argus_prime
  const direction = show(prime?.direction, 'HOLD')
  const theme = direction === 'CALL' ? styles.call : direction === 'PUT' ? styles.put : styles.hold
  const stale = isStale || !prime || prime?.display_state !== 'LIVE'
  const flow = prime?.smart_money_flow ?? {}
  const wall = prime?.wall_outcome ?? {}
  const gamma = prime?.gamma_regime ?? {}
  const futures = prime?.futures_confirmation ?? {}
  const blast = prime?.expiry_gamma_blast ?? {}
  const contract = prime?.recommended_contract
  const why = Array.isArray(prime?.why) ? prime.why.slice(0, 3) : []
  const spine = Array.isArray(prime?.strike_spine) ? prime.strike_spine : []
  const outcomes = prime?.outcome_engines ?? {}
  const score = number(prime?.argus_prime_score)
  const stability = prime?.stability ?? {}
  const retestStatus = show(prime?.retest_status, 'NOT_ACTIVE')
  const actionCard = prime?.action_card ?? {}
  const summary = prime?.tactical_summary ?? {}
  const technicals = prime?.selected_contract_technicals ?? {}
  const trend = technicals?.trend ?? {}
  const vob = technicals?.vob_3m ?? {}
  const stack = prime?.best_strike_stack ?? {}
  const pcr = prime?.live_pcr ?? {}
  const chainSummary = Array.isArray(prime?.chain_summary) ? prime.chain_summary : []
  const truth = prime?.data_truth ?? {}
  const reversal = prime?.reversal_semantics ?? {}
  const quantEvidence = {
    ...(prime?.full_evidence ?? { unavailable: ['ARGUS_PRIME_UNAVAILABLE'] }),
    metadata: {
      snapshot_id: prime?.snapshot_id ?? null,
      source_event_time: truth.source_event_time ?? null,
      receipt_timestamp: truth.receipt_timestamp ?? null,
      timestamp_semantics: truth.timestamp_semantics ?? null,
      reversal_score: prime?.reversal_score ?? null,
      formula_version: truth.formula_version ?? null,
      security_id: truth.security_id ?? null,
    },
  }
  const focusStrike = stack?.strike ?? data?.spot
  const strikeRole = contract ? 'AUTHORIZED BEST CONTRACT' : 'STRONGEST STRUCTURAL STRIKE'
  const primaryWheels = [
    ['call_edge', 'CALL'],
    ['put_edge', 'PUT'],
    ['hold_edge', 'HOLD'],
  ] as const
  const tacticalMeters = [
    ['decay_risk', 'DECAY'],
    ['big_move', 'BIG MOVE'],
    ['gamma_blast', 'GAMMA BLAST'],
    ['reversal', 'REVERSAL'],
  ] as const

  return (
    <section
      className={`${styles.panel} ${theme} ${stale ? styles.stale : ''}`}
      data-testid="argus-prime"
      data-direction={direction}
      aria-label="ARGUS PRIME advisory intelligence"
    >
      <div className={styles.edgeLight} aria-hidden="true"><i /><b /></div>
      <header className={styles.topline}>
        <div>
          <span className={styles.eyebrow}>ARGUS PRIME / PROBABLE FLOW</span>
          <strong>Institutional Options Command Surface</strong>
        </div>
        <div className={styles.policy}>
            <span>{stale ? human(prime?.hero_state ?? 'DATA LOCKED') : 'LIVE SNAPSHOT'}</span>
          <span>ADVISORY ONLY</span>
          <span>EXECUTION INFLUENCE ZERO</span>
          {onRetry && stale ? (
            <button type="button" disabled={retrying} onClick={onRetry}>
              {retrying ? 'REFRESHING' : 'REFRESH'}
            </button>
          ) : null}
        </div>
      </header>

      <div className={styles.hero}>
        <div className={styles.heroCopy}>
          <span className={styles.heroLabel}>CONFIRMED COMMAND STATE</span>
          <h2>{show(prime?.hero_state, 'HOLD — DATA UNAVAILABLE')}</h2>
          <div className={styles.heroContract}>
            <span>{strikeRole}</span>
            <strong>{contract ? `${number(contract.strike)} ${show(contract.side)}` : focusStrike == null ? 'NO CLEAN OBSERVATION' : `${number(focusStrike)} · ${human(stack?.state)}`}</strong>
            <small>{contract ? contractName(contract) : `ATM OBSERVATION ${number(stack?.atm_observation)} · AUTHORIZED CONTRACT NONE — ${human(stack?.authorization_reason)}`}</small>
          </div>
          <div className={styles.stateRail}>
            <span className={retestStatus === 'RETEST_CONFIRMED' ? styles.retestConfirmed : retestStatus === 'RETEST_ACTIVE' ? styles.retestActive : styles.retestWait}>
              {human(technicals?.pullback_state ?? retestStatus)}
            </span>
            <span className={styles.stabilityChip}>
              {stability.transition === 'SOFT_CHANGE_PENDING'
                ? `STABLE ${direction} · RAW ${show(prime?.raw_direction)} PENDING ${show(stability.pending_count, '0')}/3`
                : `STABLE ${direction}`}
            </span>
            <span className={styles.moveChip}>BIG MOVE {human(prime?.move_state)}</span>
            <span className={styles.gammaChip}>GAMMA {human(blast?.state)}</span>
          </div>
          <div className={styles.snapshot}>
            <span>SPOT <b>{data?.spot == null ? '—' : Number(data.spot).toLocaleString('en-IN')}</b></span>
            <span>EXPIRY <b>{show(data?.expiry)}</b></span>
            <span>PROVIDER EVENT TIME <b>{istTime(truth.source_event_time)} IST</b></span>
            <span>CHAIN OBSERVED <b>{istTime(truth.receipt_timestamp)} IST</b></span>
            <span>AGE <b>{truth.age_seconds == null ? '—' : `${number(truth.age_seconds, 1)}s`}</b></span>
            <span>SOURCE <b>Upstox Option Chain + NIFTY Futures</b></span>
          </div>
        </div>

        <BuyLevels technicals={technicals} trend={trend} vob={vob} contract={contract} />

        <div className={styles.scoreInstrument} aria-label={`ARGUS PRIME score ${score} out of 100`}>
          <svg viewBox="0 0 220 220" role="img">
            <circle className={styles.scoreHalo} cx="110" cy="110" r="96" />
            <circle className={styles.scoreTrack} cx="110" cy="110" r="86" pathLength="100" />
            <circle className={styles.scoreGlow} cx="110" cy="110" r="86" pathLength="100" strokeDasharray={`${number(prime?.display_score, 1)} 100`} />
            <circle className={styles.scoreMiddle} cx="110" cy="110" r="71" pathLength="100" />
            <circle className={styles.scoreInner} cx="110" cy="110" r="56" pathLength="100" />
            <circle className={styles.scoreOrbit} cx="110" cy="110" r="45" pathLength="100" />
            <circle className={styles.scoreHub} cx="110" cy="110" r="6" />
          </svg>
          <div><strong>{score}</strong><span>/ 100</span><small>ARGUS PRIME SCORE · NOT PROBABILITY</small></div>
        </div>
      </div>

      <div className={styles.intelligenceRail}>
        <article className={styles.tacticalSummary}>
          <span className={styles.eyebrow}>TACTICAL SUMMARY</span>
          <strong>{show(summary.title, 'NO CLEAN SIDE')}</strong>
          <small>WHY</small>
          <ul>
            {(Array.isArray(summary.reasons) ? summary.reasons : ['Canonical interpretation unavailable.']).map((reason: string) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
          <div className={styles.summaryMissing}>
            <small>WHAT IS MISSING</small>
            <b>{show(actionCard.reason, prime?.trigger ?? 'Canonical trigger unavailable')}</b>
          </div>
          <footer><span>STATE</span><b>{show(summary.state, 'Unavailable')}</b></footer>
        </article>

        <div className={styles.engineGrid}>
          <EngineCard title="Money Flow" value={flow.label} score={flow.score} detail={flow.state} tone={flowTone(`${flow.direction}_${flow.label}`)} />
          <EngineCard title="Wall Outcome" value={human(wall.outcome)} score={wall.score} detail={wall.wall ? `${number(wall.wall)} WALL` : 'LEVEL UNAVAILABLE'} />
          <EngineCard title="Gamma Proxy" value={human(gamma.state)} score={gamma.score} detail={gamma.status === 'AVAILABLE' ? show(gamma.trader_explanation, `${number(gamma.concentration_percentage, 1)}% CONCENTRATION`) : show(gamma.reason)} />
          <EngineCard title="Futures Confirmation" value={futures.status === 'LAST_GOOD' ? `LAST GOOD · ${human(futures.state)}` : human(futures.state)} score={futures.score} detail={`${show(futures.reason, 'CANONICAL CONFIRMATION')} · ${istTime(futures.as_of ?? futures.source_timestamp)} IST`} unavailable={futures.status === 'UNAVAILABLE'} />
        </div>

        <article className={`${styles.pcrCard} ${pcr.trend === 'RISING' ? styles.pcrRising : pcr.trend === 'FALLING' ? styles.pcrFalling : styles.pcrStable}`}>
          <div><span>LIVE OI PCR</span><b>{human(pcr.trend)}</b></div>
          <strong>{number(pcr.oi_pcr, 2)}</strong>
          <p>
            <span>1M {pcr.change_1m == null ? human(pcr.change_1m_state) : `${Number(pcr.change_1m) >= 0 ? '↑' : '↓'} ${Number(pcr.change_1m).toFixed(2)}`}</span>
            <span>5M {pcr.change_5m == null ? human(pcr.change_5m_state) : `${Number(pcr.change_5m) >= 0 ? '↑' : '↓'} ${Number(pcr.change_5m).toFixed(2)}`}</span>
          </p>
          <small>PUT OI {compact(pcr.total_put_oi)} / CALL OI {compact(pcr.total_call_oi)} · AGE {pcr.source_age_seconds == null ? '—' : `${number(pcr.source_age_seconds, 1)}s`}</small>
          {pcr.warning ? <em>{human(pcr.warning)}</em> : null}
        </article>

        <article className={styles.chainCard}>
          <span className={styles.eyebrow}>UPSTOX OPTION CHAIN</span>
          <strong>{chainSummary[0] ?? 'No clean chain edge'}</strong>
          <ul>{chainSummary.slice(1).map((item: string) => <li key={item}>{item}</li>)}</ul>
        </article>
      </div>

      <section className={styles.wheelDeck} aria-label="ARGUS PRIME outcome engines">
        <div className={styles.wheelHeader}>
          <div>
            <span>OUTCOME ENGINES</span>
            <strong>RAW {number(prime?.raw_score, 1)} <i>→</i> SMOOTHED {number(prime?.smoothed_score, 1)} <i>→</i> DISPLAY {number(prime?.display_score, 1)}</strong>
          </div>
          <small>{human(prime?.score_update)} · {human(stability.transition)}</small>
        </div>
        <div className={styles.instrumentGrid}>
          <div className={styles.primaryWheels}>
            {primaryWheels.map(([key, label]) => <TacticalHalo key={key} label={label} data={outcomes[key]} stale={stale} />)}
          </div>
          <div className={styles.tacticalMeters}>
            {tacticalMeters.map(([key, label]) => <TacticalHalo key={key} label={label} data={outcomes[key]} stale={stale} compact />)}
          </div>
        </div>
      </section>

      <BestStrikeStack stack={stack} />
      <GammaBlast blast={blast} contract={contract} trigger={prime?.trigger} invalidation={prime?.invalidation_text} />

      <article className={styles.spineCard}>
        <div className={styles.cardHeading}>
          <span>ENHANCED STRIKE SPINE</span>
          <b>{spine.length ? `${spine.length} AUTHORITATIVE STRIKES` : 'UNAVAILABLE'}</b>
        </div>
        <div className={styles.spineLegend}>
          <span>↑ ADDING</span><span>↓ UNWINDING</span><span>↑↑ ACCELERATING</span><span>→ STABLE</span>
        </div>
        <div className={styles.spineScroll}>
          <table aria-label="ARGUS PRIME strike spine">
            <thead>
              <tr>
                <th>CE probable flow</th>
                <th>CE OI velocity</th>
                <th>CE load</th>
                <th>Move / strike</th>
                <th>Wall / blast</th>
                <th>PE load</th>
                <th>PE OI velocity</th>
                <th>PE probable flow</th>
              </tr>
            </thead>
            <tbody>
              {spine.map((row: any) => (
                <tr
                  key={row.strike}
                  className={[
                    row.blast_relevance !== 'LOW' ? styles.blastRow : '',
                    row.is_strongest_pressure ? styles.strongestRow : '',
                    row.wall_strength !== 'NONE' ? styles.wallRow : '',
                    Number(row.strike) === Number(stack?.strike) ? styles.selectedRow : '',
                  ].filter(Boolean).join(' ')}
                >
                  <td><span className={`${styles.flowPill} ${flowTone(row.CE?.probable_flow)}`}>{human(row.CE?.probable_flow)}</span></td>
                  <td><b className={styles.velocity}>{show(row.CE?.velocity_arrow, '→')} {compact(row.CE?.oi_velocity)}</b><small>{row.CE?.oi_acceleration == null ? 'BASELINE BUILDING' : `${compact(row.CE?.oi_acceleration)} accel`}</small></td>
                  <td><span className={styles.loadRail}><i style={{ width: `${Math.max(0, Math.min(100, Number(row.CE?.load_intensity) || 0))}%` }} /></span><small>{number(row.CE?.load_intensity)} LOAD</small></td>
                  <td><strong className={styles.strikeValue}><i>{arrow(row.directional_arrow)}</i>{number(row.strike)}</strong><small>{row.is_atm ? 'ATM · ' : ''}{Number(row.strike) === Number(stack?.strike) ? 'BEST STACK · ' : ''}{row.is_strongest_pressure ? 'STRONGEST PRESSURE' : human(row.move_hint)}</small></td>
                  <td><span>{row.wall_strength !== 'NONE' ? `◆ ${human(row.wall_strength)}` : '—'}</span><small>{human(row.wall_condition)} · {row.is_probable_magnet ? 'MAGNET' : row.is_strongest_gamma ? `Γ ${human(row.blast_relevance)}` : human(row.blast_relevance)}</small></td>
                  <td><span className={styles.loadRail}><i style={{ width: `${Math.max(0, Math.min(100, Number(row.PE?.load_intensity) || 0))}%` }} /></span><small>{number(row.PE?.load_intensity)} LOAD</small></td>
                  <td><b className={styles.velocity}>{show(row.PE?.velocity_arrow, '→')} {compact(row.PE?.oi_velocity)}</b><small>{row.PE?.oi_acceleration == null ? 'BASELINE BUILDING' : `${compact(row.PE?.oi_acceleration)} accel`}</small></td>
                  <td><span className={`${styles.flowPill} ${flowTone(row.PE?.probable_flow)}`}>{human(row.PE?.probable_flow)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!spine.length ? <div className={styles.unavailable}>Strike spine unavailable from the canonical snapshot.</div> : null}
        </div>
      </article>

      <div className={styles.whyGrid}>
        <article>
          <div className={styles.cardHeading}><span>WHY</span><b>CANONICAL READ</b></div>
          <ol>{(why.length ? why : ['No canonical reasons reported.']).map((reason: string) => <li key={reason}>{reason}</li>)}</ol>
        </article>
        <article>
          <div className={styles.cardHeading}><span>RISK SHAPE</span><b>{human(prime?.pressure_price_state)}</b></div>
          <div className={styles.microMetrics}>
            <span>Smart Flow <b>{number(prime?.smart_flow_score)}</b></span>
            <span>Wall <b>{number(prime?.wall_outcome_score)}</b></span>
            <span>Reversal <b>{human(reversal.label ?? 'REVERSAL NOT SCORED')}</b></span>
            <span>Decay <b>{number(outcomes?.decay_risk?.display_score)}</b></span>
            <span>Gamma <b>{number(prime?.gamma_regime_score)}</b></span>
            <span>Blast <b>{number(prime?.gamma_blast_score)}</b></span>
          </div>
        </article>
        <details>
          <summary>FULL QUANT EVIDENCE</summary>
          <pre>{JSON.stringify(quantEvidence, null, 2)}</pre>
        </details>
      </div>
    </section>
  )
}

const BuyLevels: React.FC<{ technicals: any; trend: any; vob: any; contract: any }> = ({ technicals, trend, vob, contract }) => (
  <article className={styles.buyLevels}>
    <div><span>BUY LEVELS</span><b>{contract ? `${number(contract.strike)} ${show(contract.side)}` : 'LOCKED'}</b></div>
    {technicals?.status === 'AVAILABLE' ? (
      <dl>
        <div><dt>Current premium</dt><dd>{price(technicals.current_premium)}</dd></div>
        <div><dt>EMA21 pullback</dt><dd>{zone(trend.ema_21_zone)}</dd></div>
        <div><dt>EMA50 deep pullback</dt><dd>{zone(trend.ema_50_zone)}</dd></div>
        <div><dt>Supertrend pullback</dt><dd>{zone(trend.supertrend_zone)}</dd></div>
        <div><dt>3M VOB support</dt><dd>{zone(vob.support_buy_zone)}</dd></div>
        <div><dt>3M VOB breakout</dt><dd>{vob.breakout_trigger == null ? 'UNAVAILABLE' : `ABOVE ${price(vob.breakout_trigger)}`}</dd></div>
        <div className={styles.invalidLevel}><dt>Invalid</dt><dd>{technicals.invalidation_premium == null ? 'UNAVAILABLE' : `5M CLOSE BELOW ${price(technicals.invalidation_premium)}`}</dd></div>
        <div className={styles.strengthLevel}><dt>Next strength</dt><dd>{technicals.next_strength_premium == null ? 'UNAVAILABLE' : `ABOVE ${price(technicals.next_strength_premium)}${technicals.underlying_strength_level == null ? '' : ` / NIFTY ABOVE ${number(technicals.underlying_strength_level)}`}`}</dd></div>
      </dl>
    ) : (
      <p>{human(technicals?.reason ?? 'SELECTED CONTRACT TECHNICALS UNAVAILABLE')}</p>
    )}
    <small>{technicals?.completed_5m_timestamp ? `COMPLETED 5M · ${technicals.completed_5m_timestamp}` : 'COMPLETED-CANDLE LEVELS PENDING'}</small>
  </article>
)

const EngineCard: React.FC<{ title: string; value: unknown; score: unknown; detail: unknown; tone?: string; unavailable?: boolean }> = ({
  title,
  value,
  score,
  detail,
  tone,
  unavailable = false,
}) => (
  <article className={`${styles.engineCard} ${tone ?? ''} ${unavailable ? styles.engineUnavailable : ''}`}>
    <span>{title}</span><strong>{human(value)}</strong>
    <div><i style={{ width: `${unavailable ? 0 : Math.max(0, Math.min(100, Number(score) || 0))}%` }} /></div>
    <small>{unavailable ? 'NOT SCORED' : `${number(score)} / 100`} · {human(detail)}</small>
  </article>
)

const TacticalHalo: React.FC<{ label: string; data: any; stale: boolean; compact?: boolean }> = ({
  label,
  data,
  stale,
  compact = false,
}) => {
  const score = Math.max(0, Math.min(100, Number(data?.display_score ?? data?.score) || 0))
  const persistence = Math.max(0, Math.min(100, Number(data?.persistence) || 0))
  const trend = show(data?.trend, 'STABLE')
  const activeArc = score * 0.833
  const cometOffset = 100 - activeArc
  return (
    <article
      className={`${styles.tacticalHalo} ${compact ? styles.compactHalo : styles.primaryHalo} ${stale ? styles.wheelStale : ''}`}
      data-kind={data?.kind ?? label}
      aria-label={`${label} edge score ${score.toFixed(0)}; ${human(data?.state)}; ${stale ? 'last good snapshot' : human(trend)}`}
    >
      <svg viewBox="0 0 150 150" role="img">
        <circle className={styles.haloOuter} cx="75" cy="75" r="62" />
        <circle className={styles.haloTrack} cx="75" cy="75" r="55" pathLength="100" strokeDasharray="83.3 16.7" />
        <circle className={styles.haloArc} cx="75" cy="75" r="55" pathLength="100" strokeDasharray={`${activeArc} ${100 - activeArc}`} />
        <circle className={styles.haloPersistence} cx="75" cy="75" r="45" pathLength="100" strokeDasharray={`${persistence * 0.833} ${100 - persistence * 0.833}`} />
        <circle className={styles.haloOrbit} cx="75" cy="75" r="34" pathLength="100" />
        <circle className={styles.haloComet} cx="75" cy="75" r="55" pathLength="100" strokeDasharray=".8 99.2" strokeDashoffset={cometOffset} />
      </svg>
      <header><span>{label}</span><b>{trend === 'RISING' ? '↗' : trend === 'FALLING' ? '↘' : '→'}</b></header>
      <div><strong>{score.toFixed(0)}</strong><small>{human(data?.state)}</small></div>
      <footer><i style={{ width: stale ? '18%' : `${Math.max(12, score)}%` }} /><span>{stale ? 'LAST GOOD' : human(trend)}</span></footer>
    </article>
  )
}

const GammaBlast: React.FC<{
  blast: any
  contract: any
  trigger: unknown
  invalidation: unknown
}> = ({ blast, contract, trigger, invalidation }) => (
  <article className={styles.gammaBlast}>
    <div className={styles.cardHeading}>
      <span>EXPIRY GAMMA BLAST</span>
      <b>{human(blast?.state ?? 'NO_BLAST')}</b>
    </div>
    <div className={styles.gammaGrid}>
      <span>Score <b>{number(blast?.score)} / 100</b></span>
      <span>Likely direction <b>{human(blast?.direction ?? 'HOLD')}</b></span>
      <span>Wall <b>{blast?.wall == null ? 'UNAVAILABLE' : number(blast.wall)}</b></span>
      <span>Best contract <b>{contractName(contract)}</b></span>
      <span>Trigger <b>{show(trigger, 'UNAVAILABLE')}</b></span>
      <span>Invalidation <b>{show(invalidation, 'UNAVAILABLE')}</b></span>
      <span>Chase risk <b>{human(blast?.chase_risk)}</b></span>
      <span>Coverage <b>{blast?.components ? `${Object.keys(blast.components).length} COMPONENTS` : 'UNAVAILABLE'}</b></span>
    </div>
  </article>
)

const BestStrikeStack: React.FC<{ stack: any }> = ({ stack }) => {
  const primary = stack?.primary_flow ?? {}
  const defence = stack?.defence_flow ?? {}
  const path = Array.isArray(stack?.migration?.path) ? stack.migration.path : []
  const direction = show(stack?.direction, 'HOLD')
  const readiness = stack?.trade_readiness ?? {}
  return (
    <article className={styles.stackCard}>
      <div className={styles.stackHeading}>
        <div><span>STRONGEST STRUCTURAL STRIKE</span><strong>{stack?.strike == null ? 'NO CLEAN STRIKE' : number(stack.strike)} · {human(stack?.state)}</strong></div>
        <b>STRUCTURE {number(stack?.structural_strength?.score ?? stack?.score)} / 100</b>
      </div>
      <div className={styles.stackMetrics}>
        <div><span>{direction === 'PUT' ? 'PE BUYING' : 'CE BUYING'}</span><b>{show(primary.arrow, '→')} {compact(primary.acceleration)} ACCEL · {number(primary.load)} LOAD</b><small>{human(primary.label)}</small></div>
        <div><span>{direction === 'PUT' ? 'CE WRITING' : 'PE WRITING'}</span><b>{show(defence.arrow, '→')} {compact(defence.acceleration)} ACCEL · {number(defence.load)} LOAD</b><small>{human(defence.label)}</small></div>
        <div><span>OI MIGRATION</span><b>{path.length > 1 ? path.map((item: number) => number(item)).join(' → ') : 'NO CLEAN MIGRATION'}</b><small>{human(stack?.migration?.state)}</small></div>
      </div>
      <footer>
        <div><span>TRADE READINESS</span><b>{number(readiness.score)} / 100 · {(Array.isArray(readiness.reasons) ? readiness.reasons : []).map(human).join(' · ') || 'READY'}</b></div>
        <div><span>ATM / AUTHORIZATION</span><b>ATM {number(stack?.atm_observation)} · {stack?.authorized_contract ? 'CONTRACT AUTHORIZED' : human(stack?.authorization_reason)}</b></div>
      </footer>
      {stack?.score_contributions ? (
        <details className={styles.stackEvidence}>
          <summary>Stack score lineage</summary>
          <div>{Object.entries(stack.score_contributions).map(([key, item]: [string, any]) => (
            <span key={key}>{human(key)} <b>{number(item.score)} × {number(item.weight, 2)} = {number(item.contribution, 2)}</b></span>
          ))}</div>
        </details>
      ) : null}
    </article>
  )
}
