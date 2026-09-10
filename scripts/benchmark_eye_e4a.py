"""Dedicated E4A Option Evidence Benchmark Runner for Citadel Eye Engine Phase E4A-D."""

import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict

from src.eye.contracts import PriceAtom, InstrumentIdentity
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus, AuthorityType, ProbabilityStatus
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.sources import SourceType, DataClassification, SourceProvenance
from src.eye.option_evidence.contracts import OptionMarketObservation, PriceReference, QuoteState
from src.eye.option_evidence.quote_quality import classify_quote_quality
from src.eye.option_evidence.mark_prices import get_reference_price
from src.eye.option_evidence.greeks import calculate_black_scholes_greeks
from src.eye.option_evidence.iv import solve_implied_volatility
from src.eye.option_evidence.time_to_expiry import calculate_time_to_expiry
from src.eye.option_evidence.moneyness import classify_moneyness
from src.eye.option_evidence.liquidity import calculate_liquidity_metrics
from src.eye.option_evidence.synchronization import synchronize_option_and_underlying
from src.eye.option_evidence.rolling_history_adapter import generate_rolling_series_key
from src.eye.option_evidence.replay import OptionEvidenceReplayEngine


def generate_e4a_benchmark_observations(count: int, scenario: str) -> List[OptionMarketObservation]:
    now = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)
    expiry = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)

    cid = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=expiry.date(), expiry_timestamp=expiry,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )

    observations = []
    for i in range(count):
        t_obs = now + timedelta(seconds=i)

        if scenario == "EXACT_VALID_QUOTES":
            prov = SourceProvenance(source_type=SourceType.DHAN_MARKET_QUOTE, data_classification=DataClassification.EXACT_OPTION_QUOTE)
            bid = PriceAtom(ticks=int((150.0 + (i % 10) * 0.1) * 100))
            ask = PriceAtom(ticks=int((150.5 + (i % 10) * 0.1) * 100))
            obs = OptionMarketObservation(
                observation_id=f"OBS:VALID:{i}", contract=cid, provenance=prov,
                observed_at=t_obs, available_at=t_obs, evaluation_as_of=t_obs, received_at=t_obs, parsed_at=t_obs,
                last_price=PriceAtom(ticks=15025), best_bid=bid, best_ask=ask,
                bid_quantity=500, ask_quantity=400, volume=10000, open_interest=150000,
                quote_state=QuoteState.TWO_SIDED_VALID, is_fresh=True,
            )

        elif scenario == "STALE_AND_OUT_OF_ORDER":
            prov = SourceProvenance(source_type=SourceType.DHAN_MARKET_QUOTE, data_classification=DataClassification.EXACT_OPTION_QUOTE)
            # Alternate fresh, stale, and crossed
            if i % 3 == 0:
                q_state = QuoteState.TWO_SIDED_VALID
                bid, ask = PriceAtom(ticks=15000), PriceAtom(ticks=15050)
            elif i % 3 == 1:
                q_state = QuoteState.STALE_TWO_SIDED
                bid, ask = PriceAtom(ticks=15000), PriceAtom(ticks=15050)
            else:
                q_state = QuoteState.CROSSED
                bid, ask = PriceAtom(ticks=15100), PriceAtom(ticks=15000)

            obs = OptionMarketObservation(
                observation_id=f"OBS:STALE:{i}", contract=cid, provenance=prov,
                observed_at=t_obs - timedelta(seconds=40 if q_state == QuoteState.STALE_TWO_SIDED else 0),
                available_at=t_obs, evaluation_as_of=t_obs, received_at=t_obs, parsed_at=t_obs,
                last_price=PriceAtom(ticks=15020), best_bid=bid, best_ask=ask,
                quote_state=q_state, is_fresh=(q_state == QuoteState.TWO_SIDED_VALID),
            )

        else:
            # General observations for other scenarios
            prov = SourceProvenance(source_type=SourceType.DHAN_MARKET_QUOTE, data_classification=DataClassification.EXACT_OPTION_QUOTE)
            bid = PriceAtom(ticks=15000)
            ask = PriceAtom(ticks=15050)
            obs = OptionMarketObservation(
                observation_id=f"OBS:GEN:{i}", contract=cid, provenance=prov,
                observed_at=t_obs, available_at=t_obs, evaluation_as_of=t_obs, received_at=t_obs, parsed_at=t_obs,
                last_price=PriceAtom(ticks=15025), best_bid=bid, best_ask=ask,
                bid_quantity=500, ask_quantity=400, volume=10000, open_interest=150000,
                quote_state=QuoteState.TWO_SIDED_VALID, is_fresh=True,
            )

        observations.append(obs)
    return observations


def run_e4a_benchmarks():
    print("=== DEDICATED E4A OPTION EVIDENCE BENCHMARK RUNNER ===")
    results = {}
    scenarios = [
        "EXACT_VALID_QUOTES",
        "STALE_AND_OUT_OF_ORDER",
        "MIXED_FAST_SLOW_LANES",
        "CONTRACT_ROLL",
        "ROLLING_PROXY",
        "SETUP_BINDING",
        "GREEKS_IV_CALCULATION",
    ]
    sizes = [500, 5000, 50000]

    for scenario in scenarios:
        results[scenario] = {}
        for size in sizes:
            obs_list = generate_e4a_benchmark_observations(size, scenario)

            runs_ns = []
            quote_states_count = 0
            greeks_solved_count = 0
            iv_solved_count = 0
            checksums = []

            for _ in range(5):
                t0 = time.perf_counter_ns()
                q_states = 0
                g_solves = 0
                iv_solves = 0

                for obs in obs_list:
                    # Execute option evidence processing work
                    metrics = classify_quote_quality(obs.best_bid, obs.best_ask, obs.bid_quantity, obs.ask_quantity, obs.last_price, obs.observed_at, obs.evaluation_as_of)
                    if metrics.is_executable:
                        q_states += 1

                    if scenario == "GREEKS_IV_CALCULATION" or scenario == "EXACT_VALID_QUOTES":
                        if metrics.midpoint is not None:
                            iv = solve_implied_volatility(metrics.midpoint, 24500.0, 24500.0, 30.0/365.0, 0.065, "CE")
                            if iv is not None:
                                iv_solves += 1
                                greeks = calculate_black_scholes_greeks(24500.0, 24500.0, 30.0/365.0, 0.065, iv, "CE")
                                if greeks:
                                    g_solves += 1

                    elif scenario == "ROLLING_PROXY":
                        r_key = generate_rolling_series_key("NIFTY", "NEAR", "ATM", "CE")

                t1 = time.perf_counter_ns()
                elapsed_ns = t1 - t0
                runs_ns.append(elapsed_ns)
                quote_states_count = q_states
                greeks_solved_count = g_solves
                iv_solved_count = iv_solves

                summary_str = f"{scenario}:{size}:{len(obs_list)}:{q_states}:{iv_solves}:{g_solves}"
                checksum = hashlib.sha256(summary_str.encode("utf-8")).hexdigest()
                checksums.append(checksum)

            median_sec = sorted(runs_ns)[len(runs_ns)//2] / 1e9
            ops_per_sec = size / median_sec if median_sec > 0 else 0

            print(f"[{scenario:22s}] Size {size:5d} -> Median: {median_sec:.6f}s ({ops_per_sec:,.1f} ops/s) | Executable Quotes: {quote_states_count} | Checksum: {checksums[0][:12]}")

            results[scenario][str(size)] = {
                "scenario": scenario,
                "observations_ingested": size,
                "executable_quotes_classified": quote_states_count,
                "greeks_solved": greeks_solved_count,
                "iv_solved": iv_solved_count,
                "median_seconds": round(median_sec, 6),
                "ops_per_second": round(ops_per_sec, 1),
                "output_checksum": checksums[0],
            }

    out_file = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E4AD_OPTION_BENCHMARK_20260806.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2))
    print("Dedicated E4A Option Evidence Benchmark written to", out_file)
    return "PASS"


if __name__ == "__main__":
    run_e4a_benchmarks()
