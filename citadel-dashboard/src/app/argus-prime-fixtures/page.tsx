import { ArgusPrimePanel } from '@/components/institutional'
import styles from './page.module.css'

type FixtureState =
  | 'call'
  | 'put'
  | 'hold'
  | 'retest-active'
  | 'retest-confirmed'
  | 'gamma-armed'

const STATES: FixtureState[] = [
  'call',
  'put',
  'hold',
  'retest-active',
  'retest-confirmed',
  'gamma-armed',
]

const wheel = (kind: string, score: number, state: string) => ({
  kind,
  score,
  raw_score: score,
  smoothed_score: score,
  display_score: score,
  state,
  persistence: 82,
  trend: score > 55 ? 'RISING' : score < 40 ? 'FALLING' : 'STABLE',
})

const makeFixture = (state: FixtureState) => {
  const isPut = state === 'put'
  const isHold = state === 'hold'
  const direction = isHold ? 'HOLD' : isPut ? 'PUT' : 'CALL'
  const score = isHold ? 43 : isPut ? 76 : 82
  const retestStatus =
    state === 'retest-active'
      ? 'RETEST_ACTIVE'
      : state === 'retest-confirmed'
        ? 'RETEST_CONFIRMED'
        : 'WAIT_RETEST'
  const blastArmed = state === 'gamma-armed'
  const side = direction === 'PUT' ? 'PE' : 'CE'
  const strikes = [24100, 24150, 24200, 24250, 24300, 24350, 24400]

  return {
    status: 'LIVE',
    freshness: 'FRESH',
    spot: 24252.35,
    expiry: '2026-08-04',
    argus_prime: {
      status: 'LIVE',
      freshness: 'FRESH',
      display_state: 'LIVE',
      market_state: 'OPEN',
      snapshot_id: `TEST-${state.toUpperCase()}`,
      source_timestamp: '2026-07-29T14:25:00+05:30',
      direction,
      raw_direction: direction,
      hero_state: isHold
        ? 'HOLD — BIG MOVE QUIET'
        : state === 'gamma-armed'
          ? 'BIG MOVE ARMED'
          : `BUY ${direction}`,
      action: isHold ? 'HOLD' : `PREPARE ${side}`,
      data_truth: {
        source: 'TEST_FIXTURE_ONLY',
        age_seconds: 0.8,
        freshness_threshold_seconds: 20,
        state: 'LIVE',
      },
      move_state: isHold ? 'BALANCED' : 'DIRECTIONAL',
      argus_prime_score: score,
      raw_score: score + 2,
      smoothed_score: score + 1,
      display_score: score,
      score_update: 'MATERIAL',
      retest_status: retestStatus,
      entry_style:
        retestStatus === 'RETEST_CONFIRMED'
          ? 'RETEST CONFIRMED'
          : retestStatus === 'RETEST_ACTIVE'
            ? 'RETEST ACTIVE'
            : 'WAIT FOR RETEST',
      trigger: isHold
        ? 'WAIT — DIRECTIONAL EVIDENCE NOT ALIGNED'
        : `BUY ${side} ONLY AFTER TEST FIXTURE RETEST CONFIRMATION`,
      invalidation_text: isHold
        ? 'INVALIDATION NOT ACTIVE'
        : `INVALID ${direction} BELOW TEST STRUCTURE`,
      why: [
        'TEST fixture · deterministic canonical presentation contract.',
        isHold
          ? 'Flow and structure are balanced.'
          : `${direction} flow, wall and futures evidence are aligned.`,
        `Retest state: ${retestStatus}.`,
      ],
      stability: {
        confirmed_direction: direction,
        transition: 'HARD_PERSISTENCE_CONFIRMED',
        pending_count: 0,
      },
      smart_money_flow: {
        label: isHold ? 'BALANCED' : isPut ? 'BEARISH' : 'BULLISH',
        state: isHold ? 'TWO_SIDED' : 'DIRECTIONAL',
        direction,
        score: isHold ? 50 : 78,
      },
      wall_outcome: {
        outcome: isHold ? 'CONTESTED' : 'BROKEN',
        score: isHold ? 48 : 74,
        wall: isPut ? 24200 : 24300,
      },
      gamma_regime: {
        status: 'AVAILABLE',
        state: blastArmed ? 'EXPANSION_READY' : 'CONTROLLED',
        score: blastArmed ? 88 : 62,
        concentration_percentage: blastArmed ? 71 : 44,
      },
      futures_confirmation: {
        status: 'AVAILABLE',
        state: isHold ? 'MIXED' : 'CONFIRMED',
        score: isHold ? 50 : 76,
        reason: 'TEST COMPLETED FUTURES SNAPSHOT',
      },
      expiry_gamma_blast: {
        state: blastArmed ? 'ARMED' : 'MONITORING',
        score: blastArmed ? 86 : 44,
        direction,
        wall: 24300,
        chase_risk: blastArmed ? 'ELEVATED' : 'CONTROLLED',
        dte: 6,
      },
      recommended_contract: isHold
        ? null
        : {
            side,
            option_type: side,
            security_id: isPut ? 'TEST-PE' : 'TEST-CE',
            trading_symbol: `NIFTY 04 AUG 24200 ${side}`,
            strike: 24200,
            expiry: '2026-08-04',
            spread_pct: 0.34,
            volume: 1850000,
            oi: 4210000,
          },
      action_card: {
        status: isHold ? 'NO CLEAN EDGE' : retestStatus === 'RETEST_CONFIRMED' ? 'READY' : 'WAIT',
        reason: isHold ? 'Directional evidence is balanced.' : 'Waiting for the canonical completed-candle trigger.',
        entry_style:
          retestStatus === 'RETEST_CONFIRMED'
            ? 'RETEST CONFIRMED'
            : retestStatus === 'RETEST_ACTIVE'
              ? 'RETEST ACTIVE'
              : 'WAIT FOR RETEST',
        trigger: isHold
          ? 'WAIT — TEST EVIDENCE BALANCED'
          : `TEST ${direction} TRIGGER AFTER RETEST`,
        invalidation: isHold ? 'NOT ACTIVE' : `TEST ${direction} STRUCTURE`,
      },
      tactical_summary: {
        title: isHold ? 'NO CLEAN SIDE' : `${direction} SIDE BUILDING`,
        reasons: isHold
          ? ['Call and Put evidence are balanced.', 'No clean strike dominance.']
          : [
              `${direction} edge is stronger than the opposite side.`,
              'Reversal risk is controlled.',
              'Big-move evidence is loading.',
            ],
        state: isHold ? 'Balanced Bias' : 'Stable Bias',
      },
      live_pcr: {
        status: 'AVAILABLE',
        freshness: 'FRESH',
        oi_pcr: isPut ? 1.31 : isHold ? 1.02 : 1.18,
        volume_pcr: isPut ? 1.26 : isHold ? 1.01 : 1.13,
        change_1m: isPut ? 0.03 : isHold ? 0.0 : 0.02,
        change_5m: isPut ? 0.08 : isHold ? 0.01 : 0.06,
        change_1m_state: 'AVAILABLE',
        change_5m_state: 'AVAILABLE',
        volume_state: 'AVAILABLE',
        source_age_seconds: 0.8,
        trend: isHold ? 'STABLE' : 'RISING',
        source_timestamp: '2026-07-29T14:25:00+05:30',
        warning: null,
      },
      chain_summary: isHold
        ? ['No clean chain edge', 'Participation remains two-sided']
        : [
            `${direction === 'CALL' ? 'Bullish' : 'Bearish'} chain posture`,
            `Support concentrated at 24,200`,
            `${direction === 'CALL' ? 'Upward' : 'Downward'} migration visible`,
          ],
      selected_contract_technicals: isHold
        ? { status: 'UNAVAILABLE', reason: 'NO_CLEAN_CONTRACT' }
        : {
            status: 'AVAILABLE',
            security_id: isPut ? 'TEST-PE' : 'TEST-CE',
            side,
            current_premium: isPut ? 167.2 : 151.8,
            completed_5m_timestamp: '2026-07-29T14:20:00+05:30',
            completed_3m_timestamp: '2026-07-29T14:21:00+05:30',
            pullback_state:
              retestStatus === 'RETEST_CONFIRMED'
                ? 'PULLBACK_CONFIRMED'
                : retestStatus === 'RETEST_ACTIVE'
                  ? 'PULLBACK_ACTIVE'
                  : 'WAITING_FOR_5M_PULLBACK',
            invalidation_premium: isPut ? 158.4 : 143.6,
            next_strength_premium: isPut ? 173.5 : 154.0,
            trend: {
              ema_21: isPut ? 164.8 : 149.45,
              ema_50: isPut ? 159.6 : 140.55,
              supertrend_value: isPut ? 158.4 : 143.6,
              supertrend_direction: 'POSITIVE',
              atr: 8.25,
              ema_21_zone: { low: isPut ? 164.1 : 148.75, high: isPut ? 165.5 : 150.15 },
              ema_50_zone: { low: isPut ? 158.9 : 139.85, high: isPut ? 160.3 : 141.25 },
              supertrend_zone: { low: isPut ? 157.7 : 142.9, high: isPut ? 159.1 : 144.3 },
            },
            vob_3m: {
              support_buy_zone: { low: isPut ? 162.8 : 146.0, high: isPut ? 165.1 : 149.0 },
              breakout_trigger: isPut ? 173.5 : 154.0,
            },
          },
      best_strike_stack: {
        status: isHold ? 'MIXED' : 'AVAILABLE',
        authorized_contract: !isHold,
        strike_role: isHold ? 'FOCUS_STRIKE' : 'BEST_STRIKE',
        strike: isHold ? 24250 : 24200,
        state: isHold ? 'MIXED STACK' : `${direction === 'CALL' ? 'BULLISH' : 'BEARISH'} STACK`,
        score: isHold ? 51 : 86,
        primary_flow: {
          arrow: '↑↑',
          acceleration: isHold ? 1200 : 78600,
          load: isHold ? 52 : 100,
          label: isHold ? 'BALANCED' : direction === 'CALL' ? 'CALL BUYING' : 'PUT BUYING',
        },
        defence_flow: {
          arrow: '↑',
          acceleration: isHold ? 900 : 62000,
          load: isHold ? 49 : 84,
          label: isHold ? 'BALANCED' : direction === 'CALL' ? 'PUT WRITING' : 'CALL WRITING',
        },
        migration: {
          state: isHold ? 'SCATTERED' : direction === 'CALL' ? 'UPWARD' : 'DOWNWARD',
          path: isHold ? [] : direction === 'CALL' ? [24150, 24200, 24250] : [24300, 24250, 24200],
        },
        interpretation: isHold ? 'NO CLEAN STRIKE DOMINANCE' : `STRONG ${direction} POSITIONING`,
        next_strength: direction === 'CALL' ? 24250 : direction === 'PUT' ? 24150 : null,
      },
      outcome_engines: {
        call_edge: wheel('CALL', isPut ? 18 : isHold ? 45 : 84, 'CALL EDGE'),
        put_edge: wheel('PUT', isPut ? 84 : isHold ? 46 : 18, 'PUT EDGE'),
        hold_edge: wheel('HOLD', isHold ? 82 : 24, isHold ? 'DOMINANT' : 'LOW'),
        decay_risk: wheel('DECAY', 34, 'CONTROLLED'),
        big_move: wheel(direction, isHold ? 38 : 79, isHold ? 'MIXED' : 'READY'),
        gamma_blast: wheel(
          'GAMMA',
          blastArmed ? 86 : 44,
          blastArmed ? 'ARMED' : 'MONITORING',
        ),
        reversal: wheel('REVERSAL', isHold ? 50 : 28, 'LOW'),
      },
      strike_spine: strikes.map((strike, index) => ({
        strike,
        is_atm: strike === 24250,
        is_selected_contract: !isHold && strike === 24200,
        is_strongest_pressure: index === (isPut ? 2 : 4),
        is_strongest_gamma: blastArmed && index === 4,
        directional_arrow: isPut ? 'DOWN' : isHold ? 'FLAT' : 'UP',
        move_hint: isHold ? 'BALANCED' : `${direction} PRESSURE`,
        wall_strength: index === 4 ? 'STRONG' : 'NONE',
        wall_condition: index === 4 ? 'TEST WALL' : 'CLEAR',
        blast_relevance: blastArmed && index === 4 ? 'HIGH' : 'LOW',
        is_probable_magnet: index === 3,
        CE: {
          probable_flow: isPut ? 'CALL_WRITING' : isHold ? 'BALANCED' : 'CALL_BUYING',
          velocity_arrow: isPut ? '↓' : '↑',
          oi_velocity: 125000 + index * 9000,
          oi_acceleration: 8000,
          load_intensity: 35 + index * 5,
        },
        PE: {
          probable_flow: isPut ? 'PUT_BUYING' : isHold ? 'BALANCED' : 'PUT_WRITING',
          velocity_arrow: isPut ? '↑' : '↓',
          oi_velocity: 118000 + index * 7000,
          oi_acceleration: 6500,
          load_intensity: 68 - index * 4,
        },
      })),
      pressure_price_state: isHold ? 'BALANCED' : 'CONFIRMED',
      smart_flow_score: isHold ? 50 : 78,
      wall_outcome_score: isHold ? 48 : 74,
      reversal_score: isHold ? 50 : 28,
      gamma_regime_score: blastArmed ? 88 : 62,
      gamma_blast_score: blastArmed ? 86 : 44,
      futures_confirmation_score: isHold ? 50 : 76,
      full_evidence: {
        fixture: true,
        label: 'TEST ONLY',
        score_is_probability: false,
        execution_influence: 'ZERO',
      },
    },
  }
}

export default async function ArgusPrimeFixtures({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>
}) {
  const query = await searchParams
  const state = STATES.includes(query.state as FixtureState)
    ? (query.state as FixtureState)
    : 'call'
  return (
    <main className={styles.page}>
      <header className={styles.fixtureHeader}>
        <strong>TEST FIXTURE · ARGUS PRIME</strong>
        <span>{state.replaceAll('-', ' ').toUpperCase()}</span>
        <small>DETERMINISTIC UI CONTRACT · NO PRODUCTION DATA · EXECUTION INFLUENCE ZERO</small>
      </header>
      <ArgusPrimePanel data={makeFixture(state)} />
    </main>
  )
}
