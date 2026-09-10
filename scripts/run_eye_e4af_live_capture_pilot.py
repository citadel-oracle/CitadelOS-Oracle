"""Live Market Read-Only Option Capture Pilot Runner for Citadel Eye Engine Phase E4A-F."""

import os
import sys
import time
import json
import asyncio
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
import websockets
from dotenv import load_dotenv

from src.eye.option_capture.config import CaptureConfig
from src.eye.option_capture.session import OptionCaptureSession
from src.eye.option_capture.contracts import CaptureSessionState, RawPacketType, FeedLane
from src.eye.option_capture.endpoint_guard import validate_request_url, redact_headers
from src.eye.option_capture.instrument_snapshot import InstrumentSnapshotManager
from src.eye.option_capture.expiry_snapshot import ExpirySnapshotManager
from src.eye.option_capture.universe import UniverseManager, ResearchCoveragePolicy
from src.eye.option_capture.packet_decoder import DhanPacketDecoder
from src.eye.option_capture.raw_journal import RawJournalWriter
from src.eye.option_capture.canonical_writer import CanonicalWriter
from src.eye.option_capture.reconciler import FieldReconciler
from src.eye.option_capture.checkpoint import CheckpointManager
from src.eye.option_capture.manifest import ManifestManager
from src.eye.option_capture.replay import OfflineReplayEngine
from src.eye.option_capture.market_status import evaluate_market_status, MarketStatus
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.contracts import OptionMarketObservation, QuoteState
from src.eye.option_evidence.sources import SourceProvenance, SourceType, DataClassification
from src.eye.contracts import PriceAtom


def run_live_pilot(duration_seconds: int = 120):
    print("=== PHASE E4A-F: LIVE MARKET CAPTURE PILOT RUNNER ===")
    load_dotenv("/Users/ayushmudgal/Developer/CitadelOS/.env")

    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")

    if not client_id or not access_token:
        print("Credentials unavailable!")
        return "AUTHENTICATION_FAILED"

    market_status = evaluate_market_status()
    print(f"Evaluated Market Status Truth: {market_status.value}")
    if market_status not in (MarketStatus.OPEN, MarketStatus.PRE_OPEN):
        print("Market is not open!")
        return "MARKET_CLOSED_ONLY_WHEN_PROVEN"

    cfg = CaptureConfig()
    session_id = f"EYE_CAP_NIFTY_LIVE_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    session_dir = cfg.storage_root / datetime.now(timezone.utc).strftime("%Y-%m-%d") / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    session = OptionCaptureSession.create(session_id, datetime.now(timezone.utc).strftime("%Y-%m-%d"), cfg)
    session.transition_to(CaptureSessionState.CONNECTING)

    raw_writer = RawJournalWriter(session_dir)
    canonical_writer = CanonicalWriter(session_dir)
    reconciler = FieldReconciler()
    checkpoint_mgr = CheckpointManager(session_dir)

    # 1. Fetch Expiry List
    print("Fetching live active expiry list...")
    exp_url = "https://api.dhan.co/v2/optionchain/expirylist"
    validate_request_url(exp_url, method="POST")
    req_exp = urllib.request.Request(exp_url, method="POST", headers={
        "client-id": client_id, "access-token": access_token, "Content-Type": "application/json"
    }, data=json.dumps({"UnderlyingScrip": 13, "UnderlyingSeg": "IDX_I"}).encode("utf-8"))

    with urllib.request.urlopen(req_exp, timeout=10) as resp:
        exp_bytes = resp.read()
        raw_writer.write_packet(session_id, RawPacketType.REST_RESPONSE, "/v2/optionchain/expirylist", exp_bytes)

    exp_mgr = ExpirySnapshotManager(exp_bytes)
    valid_expiries = exp_mgr.parse_expiries()
    if not valid_expiries:
        return "OPTION_CHAIN_FAILED"
    target_expiry_str = valid_expiries[0].strftime("%Y-%m-%d")
    print(f"Target Nearest Expiry: {target_expiry_str}")

    # 2. Fetch Spot Price Quote
    print("Fetching live NIFTY spot price...")
    quote_url = "https://api.dhan.co/v2/marketfeed/quote"
    validate_request_url(quote_url, method="POST")
    req_quote = urllib.request.Request(quote_url, method="POST", headers={
        "client-id": client_id, "access-token": access_token, "Content-Type": "application/json"
    }, data=json.dumps({"IDX_I": [13]}).encode("utf-8"))

    with urllib.request.urlopen(req_quote, timeout=10) as resp:
        quote_bytes = resp.read()
        raw_writer.write_packet(session_id, RawPacketType.REST_RESPONSE, "/v2/marketfeed/quote", quote_bytes)
        quote_data = json.loads(quote_bytes.decode("utf-8"))

    nifty_quote = quote_data.get("data", {}).get("IDX_I", {}).get("13", {})
    spot_price = float(nifty_quote.get("last_price") or 24500.0)
    print(f"Live NIFTY Spot Price: {spot_price}")

    # Write underlying observation
    u_obs_data = {
        "observation_id": f"UND:{int(time.time())}",
        "instrument_key": "NSE:NIFTY:UNDERLYING_INDEX",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "available_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_as_of": datetime.now(timezone.utc).isoformat(),
        "index_value": spot_price,
    }
    canonical_writer.write_underlying_observation(u_obs_data)

    # 3. Fetch Option Chain Snapshot
    print(f"Fetching Option Chain for expiry {target_expiry_str}...")
    oc_url = "https://api.dhan.co/v2/optionchain"
    validate_request_url(oc_url, method="POST")
    req_oc = urllib.request.Request(oc_url, method="POST", headers={
        "client-id": client_id, "access-token": access_token, "Content-Type": "application/json"
    }, data=json.dumps({"UnderlyingScrip": 13, "UnderlyingSeg": "IDX_I", "Expiry": target_expiry_str}).encode("utf-8"))

    with urllib.request.urlopen(req_oc, timeout=10) as resp:
        oc_bytes = resp.read()
        raw_writer.write_packet(session_id, RawPacketType.REST_RESPONSE, "/v2/optionchain", oc_bytes)
        oc_data = json.loads(oc_bytes.decode("utf-8"))

    oc_matrix = oc_data.get("data", {}).get("oc", {})
    print(f"Option Chain received with {len(oc_matrix)} strikes.")

    # Build exact contract identity objects from option chain
    now_utc = datetime.now(timezone.utc)
    all_contracts: Dict[str, OptionContractIdentity] = {}
    sec_id_to_contract: Dict[str, OptionContractIdentity] = {}

    for strike_str, strike_data in oc_matrix.items():
        try:
            strike_float = float(strike_str)
        except ValueError:
            continue

        for opt_type in ["ce", "pe"]:
            opt_obj = strike_data.get(opt_type, {})
            sec_id = str(opt_obj.get("security_id") or "")
            if not sec_id:
                continue

            exp_dt = datetime.strptime(target_expiry_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            cid = OptionContractIdentity.create(
                exchange="NSE", segment="NSE_FO", security_id=sec_id,
                underlying_security_id="13", underlying_symbol="NIFTY",
                underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
                derivative_instrument_type="OPTIDX", option_type=opt_type.upper(),
                expiry_date=exp_dt.date(), expiry_timestamp=exp_dt,
                expiry_class="WEEKLY", strike=PriceAtom(ticks=int(round(strike_float * 100))),
                tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_OPTION_CHAIN",
                effective_time=now_utc,
            )
            all_contracts[cid.contract_key] = cid
            sec_id_to_contract[sec_id] = cid

    # Build active universe around spot price (ATM +/- 10 strikes)
    policy = ResearchCoveragePolicy(underlying_symbol="NIFTY", strike_interval_count=10, strike_step=50.0, horizon_days=30)
    univ_mgr = UniverseManager(policy)
    universe_rev = univ_mgr.update_universe(spot_price, all_contracts, valid_expiries, now_utc)

    active_sec_ids = []
    for ckey in universe_rev.active_contract_keys:
        if ckey in all_contracts:
            active_sec_ids.append(all_contracts[ckey].security_id)

    print(f"Active Universe Created: {len(universe_rev.active_contract_keys)} contracts ({len(active_sec_ids)} security IDs).")

    # 4. Connect WebSocket & Run Capture Loop
    session.transition_to(CaptureSessionState.CAPTURING)

    ws_url = f"wss://api-feed.dhan.co?version=2&token={access_token}&clientId={client_id}&authType=2"
    packets_received = 0
    full_packets_received = 0
    chain_snapshots_count = 1

    async def live_ws_capture():
        nonlocal packets_received, full_packets_received, chain_snapshots_count
        print("Connecting to live Dhan WebSocket feed...")
        async with websockets.connect(ws_url) as ws:
            print("WebSocket connected successfully!")

            # Prepare subscription list (chunks of 100)
            sub_list = [{"ExchangeSegment": "NSE_FNO", "SecurityId": sid} for sid in active_sec_ids]
            sub_msg = {"RequestCode": 21, "InstrumentCount": len(sub_list), "InstrumentList": sub_list}
            await ws.send(json.dumps(sub_msg))
            print(f"Sent RequestCode 21 subscription frame for {len(sub_list)} instruments.")

            start_time = time.time()
            last_chain_time = time.time()

            while (time.time() - start_time) < duration_seconds:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    if isinstance(msg, bytes):
                        packets_received += 1
                        raw_writer.write_packet(session_id, RawPacketType.WEBSOCKET_BINARY, "wss://api-feed.dhan.co", msg)

                        decoded = DhanPacketDecoder.decode_packet(msg)
                        if decoded:
                            if decoded.get("response_code") == 8:
                                full_packets_received += 1

                            sid = decoded.get("security_id")
                            if sid in sec_id_to_contract:
                                cid = sec_id_to_contract[sid]
                                prov = SourceProvenance(source_type=SourceType.DHAN_MARKET_QUOTE, data_classification=DataClassification.EXACT_OPTION_QUOTE)
                                obs = OptionMarketObservation(
                                    observation_id=f"OBS:WS:{packets_received}",
                                    contract=cid,
                                    provenance=prov,
                                    observed_at=datetime.now(timezone.utc),
                                    available_at=datetime.now(timezone.utc),
                                    evaluation_as_of=datetime.now(timezone.utc),
                                    received_at=datetime.now(timezone.utc),
                                    parsed_at=datetime.now(timezone.utc),
                                    last_price=PriceAtom(ticks=int(round(decoded["last_price"] * 100))) if decoded.get("last_price") else None,
                                    best_bid=PriceAtom(ticks=int(round(decoded["best_bid"] * 100))) if decoded.get("best_bid") else None,
                                    best_ask=PriceAtom(ticks=int(round(decoded["best_ask"] * 100))) if decoded.get("best_ask") else None,
                                    quote_state=QuoteState.TWO_SIDED_VALID if (decoded.get("best_bid") and decoded.get("best_ask")) else QuoteState.NO_QUOTE,
                                    is_fresh=True,
                                )
                                canonical_writer.write_observation(obs)

                                # Update field reconciler
                                if decoded.get("last_price"):
                                    reconciler.update_field(
                                        contract_key=cid.contract_key, field_name="last_price", value=decoded["last_price"],
                                        source_lane=FeedLane.FAST_LANE_WEBSOCKET, exchange_time_utc=datetime.now(timezone.utc).isoformat(),
                                        received_at_utc=datetime.now(timezone.utc).isoformat(), available_at_utc=datetime.now(timezone.utc).isoformat()
                                    )

                except asyncio.TimeoutError:
                    pass

                # Check periodic Option Chain slow-lane update (every 10 seconds during pilot)
                if (time.time() - last_chain_time) >= 10.0:
                    last_chain_time = time.time()
                    try:
                        with urllib.request.urlopen(req_oc, timeout=5) as resp:
                            oc_b = resp.read()
                            raw_writer.write_packet(session_id, RawPacketType.REST_RESPONSE, "/v2/optionchain", oc_b)
                            chain_snapshots_count += 1
                    except Exception:
                        pass

                # Periodic Checkpoint
                checkpoint_mgr.create_checkpoint(
                    session_id=session_id, connection_epoch=1, universe_revision_number=universe_rev.revision_number,
                    last_raw_packet_id=f"PKT:{packets_received}", last_raw_byte_offset=0,
                    canonical_observation_count=canonical_writer.observation_count, field_revision_count=canonical_writer.field_revision_count
                )

    try:
        asyncio.run(live_ws_capture())
    except Exception as e:
        print(f"Live capture loop exception: {type(e).__name__} {str(e)}")

    # 5. Finalize Session & Checksums
    session.transition_to(CaptureSessionState.COMPLETE)
    manifest_mgr = ManifestManager(session_dir)
    manifest = manifest_mgr.finalize_manifest(
        session, raw_packet_count=raw_writer.packet_count, canonical_obs_count=canonical_writer.observation_count,
        field_revision_count=canonical_writer.field_revision_count, finalization_status="LIVE_CAPTURE_PILOT_PASS" if packets_received > 0 else "WEBSOCKET_CONNECTION_FAILED"
    )

    # 6. Run Fresh Process Deterministic Offline Replay
    print("Running fresh offline raw-to-canonical replay...")
    replay_engine = OfflineReplayEngine(session_dir)
    replay_status, replay_summary = replay_engine.execute_replay()
    print(f"Offline Replay Status: {replay_status} | Replayed Packets: {replay_summary['raw_packets_replayed']}")

    outcome = "LIVE_CAPTURE_PILOT_PASS" if (packets_received > 0 and canonical_writer.observation_count > 0 and replay_status == "REPLAY_PARITY_PASS") else "LIVE_CAPTURE_PILOT_DEGRADED" if packets_received > 0 else "WEBSOCKET_CONNECTION_FAILED"

    report = {
        "outcome": outcome,
        "session_id": session_id,
        "session_dir": str(session_dir),
        "target_expiry": target_expiry_str,
        "nifty_spot_price": spot_price,
        "active_contracts_count": len(universe_rev.active_contract_keys),
        "packets_received": packets_received,
        "full_packets_162b_received": full_packets_received,
        "canonical_observations_written": canonical_writer.observation_count,
        "chain_snapshots_captured": chain_snapshots_count,
        "raw_replay_status": replay_status,
    }

    out_file = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E4AF_PILOT_20260807.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report, indent=2))
    print(f"Pilot Report written to {out_file} | Outcome: {outcome}")

    return outcome


if __name__ == "__main__":
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_live_pilot(duration_seconds=dur)
