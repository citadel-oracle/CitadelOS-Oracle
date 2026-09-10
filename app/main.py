import resource as _resource
try:
    _soft, _hard = _resource.getrlimit(_resource.RLIMIT_NOFILE)
    _target = min(_hard, 10240) if _hard > 0 else 10240
    _resource.setrlimit(_resource.RLIMIT_NOFILE, (_target, _hard))
except Exception:
    pass
import os as _os
import shutil as _shutil
import json as _json
import hashlib as _hashlib
import pickle as _pickle
import queue as _queue
import asyncio as _asyncio
from copy import deepcopy as _deepcopy
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_ROOT = str(REPO_ROOT / "logs")
DEFAULT_ENV_FILE = str(REPO_ROOT / ".env")
from dotenv import load_dotenv as _load_dotenv
_load_dotenv(dotenv_path=_os.getenv("CITADEL_ENV_FILE", DEFAULT_ENV_FILE))
ORACLE_TURBO_MODE = _os.getenv("CITADEL_ORACLE_TURBO_MODE", "0") == "1"
# R2.1H: legacy V2 is a compatibility surface, not a second live computation
# owner.  It can be re-enabled explicitly for offline legacy diagnostics, but
# the production FastAPI parent defaults to the already-published Fast Lane
# authority.  This switch changes scheduling/transport only, never formulas.
ORACLE_V2_PARENT_REBUILD_ENABLED = (
    _os.getenv("CITADEL_ORACLE_V2_PARENT_REBUILD_ENABLED", "0") == "1"
)

from datetime import datetime, timedelta, timezone
from threading import Event as _ThreadEvent, Lock as _Lock, Thread as _Thread
from typing import Any, Mapping as _Mapping, Optional, Dict, List, Set, Tuple
from pathlib import Path
from time import perf_counter as _perf_counter, perf_counter_ns as _perf_counter_ns
from src.kronos_alpha.config import KronosAlphaConfig
from src.chronos_2.config import Chronos2Config

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.dashboard_api import DashboardAPI
from src.api.event_loop_watchdog import EventLoopWatchdog
from src.api.oracle_fast_lane import OracleFastLane
from src.api.oracle_sol_api import router as oracle_sol_router
from src.api.live_island_api import router as live_island_router
from src.api.v2_integration import ProjectionProcessWorker, V2DashboardIntegration
from src.api.argus_api import ArgusAPI, ArgusAPIError
from src.argus import (
    ArgusSessionRecorder,
    ArgusTacticalEdgeEngine,
    ArgusTacticalStore,
)
from src.argus.fusion_eod import FusionShadowEODAnalyzer
from src.argus.fusion_shadow import FusionShadowEngine
from src.argus.market_snapshot import ArgusMarketSnapshotProvider
from src.argus.contract_technicals import LatestContractTechnicalsProvider
from src.scanner.watchlist import WATCHLIST
from src.api.control_status_api import ControlStatusAPI
from src.canonical_features.service import CanonicalFeatureService
from src.athena.athena_service import AthenaService
from src.hermes.hermes_service import HermesService
from src.oracle.oracle_service import OracleService, UnsupportedOracleSymbol
from src.oracle.context import ContextEngine
from src.oracle.decision import AnalysisNotFoundError, OracleAnalysisService
from src.oracle.evidence import Phase4EvidenceService
from src.oracle.conditions import (
    ConditionConflict as OracleConditionConflict,
    ConditionError as OracleConditionError,
    ConditionMonitor,
    ConditionState,
    IndependentPaperGuardian,
    OracleConditionService,
    Phase5OracleWorkflow,
    Phase5PaperExecutionAdapter,
    Phase5RevalidationService,
)
from src.oracle.knowledge_engine import KnowledgeRetrievalService, build_query
from src.oracle.exact_option import ExactOptionPremiumAnalysisService
from src.oracle.option_buyer_intelligence import OptionBuyerIntelligenceWorker
from src.oracle.tradingview_sync import PerformanceTelemetry, TradingViewAutoSyncService
from src.oracle.market_day import MarketDayError, MarketDayReadinessService
from src.oracle_personal.visual_edge import VisualEdgeError
from src.oracle_personal.second_brain import SecondBrainError
from src.oracle.visual import VisualObservationStore
from src.oracle.mission import (
    MissionConflictError,
    MissionEvaluationUnavailableError,
    MissionNotFoundError,
    MissionPlanRequest,
    MissionPlanUnavailableError,
    MissionStartRequest,
    MissionStateUnavailableError,
    MissionValidationError,
    OracleMissionService,
)
from src.oracle.paper_autopilot import (
    OpenAlgoAnalyzerClient,
    OracleExecutionBlocked,
    OracleExecutionUnavailable,
    OraclePaperAutopilot,
)
from src.oracle.demo_tour import DemoTourError, DemoTourSession
from src.kronos_alpha import KronosAlphaService
from src.kronos_alpha.scheduler import KronosAlphaScheduler
from src.kronos_alpha.candle_source import RealNiftyCandleSource
from src.market.session_calendar import NSESessionCalendar
from src.aegis import AegisService
from src.aegis.providers import AegisInputBuilder
from src.aegis.policy import strategy_eligibility
from src.system_readiness import OpenMarketReadinessService
from src.chronos_2 import Chronos2Scheduler, Chronos2Service
from src.futures_forecast import FuturesForecastOrchestrator
from src.order_ledger import OrderFillLedgerService
from src.paper_trading import PaperExecutionEngine, RealMarketPaperOrchestrator
from src.paper_trading.risk import PaperRiskAuthorization
from src.development import DevelopmentPaperExecutionEngine, DevelopmentPaperOrchestrator, DevelopmentRiskAuthorization
from src.execution.paper_state import PaperStateService
from src.risk.authorization import RiskAuthorizationService
from src.order_ledger.storage import OrderFillStore
from src.strategy_lab import StrategyLabService
from src.strategy_lab.state_truth import (
    reset_state_truth_runtime_metrics,
    state_truth_runtime_metrics,
)
from src.strategy_lab.storage import (
    reset_storage_runtime_metrics,
    storage_runtime_metrics,
)
from src.strategy_command import ArgusEdgeLab, StrategyCommandRuntimeBridge, StrategyCommandService
from src.strategy_lab.completed_candle import CompletedCandleContextProvider, deployment_held_security_id_provider
from src.strategy_lab.option_charts import OptionChartCandleFeed
from src.strategy_lab.option_deployments import build_option_chart_deployments
from src.strategy_lab.strategies.pullback_master import build_deployment_request as build_pullback_master_deployment
from src.strategy_lab.strategies.breakout_main import build_deployment_request as build_breakout_main_deployment
from src.eye.kernel.runtime import EyeRuntime, PersistentEyeScanner
from src.eye.oracle_projection.projection_service import EyeOracleProjectionService
from src.eye.oracle_projection.runtime_state import EyeRuntimeState
from src.ose import OptionsStructureEngine
from src.operations.production import (
    InstitutionalKillSwitch,
    OperationalMonitorLoop,
    ProductionHealthMonitor,
    ProductionOperationsService,
    StructuredEventLogger,
)
from src.oracle.isolated_market_data_gateway import IsolatedMarketDataGateway
from src.oracle.isolated_flow_worker import IsolatedOrderFlowWorker
from src.oracle.isolated_execution_boundary import IsolatedExecutionBoundary
from src.oracle.latest_state_lane import FlowPublicationLane
from src.oracle.reliability import OracleRuntimeStatus, RuntimeProvenance, StartupState
from src.oracle.canonical_runtime_truth import CanonicalRuntimeTruth, GlobalReadinessState, StoragePersistenceState
from src.order_flow.recorder import OrderFlowEvidenceRecorder
from src.order_flow.contracts import InstrumentIdentity
from src.order_flow.publication import publish_order_flow
from src.order_flow.research import OrderFlowResearchAggregator
from src.order_flow.routing import basket_from_argus, gateway_instruments
from src.vob import VobReversalEngine


app = FastAPI(title="CitadelOS API", version="2.0.0")
event_loop_watchdog = EventLoopWatchdog()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)


@app.middleware("http")
async def citadel_api_version_header(request, call_next):
    response = await call_next(request)
    response.headers["X-Citadel-API-Version"] = "2.0"
    return response

dashboard = DashboardAPI()
argus = ArgusAPI()
projection_process_worker = ProjectionProcessWorker(timeout_seconds=8.0)
canonical_feature_service = CanonicalFeatureService.get_instance()


def _held_option_contract(side: str):
    service = globals().get("strategy_lab_service")
    if service is None:
        return None
    for position in service.positions().get("positions") or []:
        option = position.get("option_contract") if isinstance(position, dict) else None
        if (
            position.get("status") == "OPEN"
            and isinstance(option, dict)
            and str(option.get("option_type") or "").upper() == str(side).upper()
        ):
            return option
    return None


option_chart_feed = OptionChartCandleFeed(
    dhan=argus.engine.dhan,
    projection_provider=lambda: argus.projection("NIFTY"),
    canonical_store_root="logs/strategy_lab/market_state/candles",
    history_days=120,
    held_contract_provider=_held_option_contract,
)
options_structure_engine = OptionsStructureEngine(
    dhan=argus.engine.dhan,
    instrument_master=option_chart_feed.instrument_master,
    state_root=Path(_os.environ.get("CITADEL_STATE_ROOT", DEFAULT_STATE_ROOT)) / "options_structure",
    spot_candle_path=Path(_os.environ.get("CITADEL_STATE_ROOT", DEFAULT_STATE_ROOT)) / "vob_1m_candles.json",
)
option_chart_feed.subscribe(options_structure_engine.ingest)
argus_contract_technicals = LatestContractTechnicalsProvider(
    options_structure_engine.contract_technicals
)
argus_tactical_edge = ArgusTacticalEdgeEngine(
    ArgusTacticalStore(
        Path(
            _os.environ.get(
                "CITADEL_STATE_ROOT",
                DEFAULT_STATE_ROOT,
            )
        )
        / "argus"
        / "tactical_edge.json"
    ),
    recorder=ArgusSessionRecorder(
        Path(
            _os.environ.get(
                "CITADEL_STATE_ROOT",
                DEFAULT_STATE_ROOT,
            )
        )
        / "argus"
        / "session_snapshots"
    ),
    contract_technicals_provider=argus_contract_technicals,
)
argus_state_root = Path(
    _os.environ.get(
        "CITADEL_STATE_ROOT",
        DEFAULT_STATE_ROOT,
    )
)
oracle_runtime = OracleRuntimeStatus(
    RuntimeProvenance(
        Path(__file__).resolve().parents[1],
        state_root=argus_state_root,
        log_root=argus_state_root,
        journal_root=argus_state_root / "order_flow" / "evidence",
        config_source=_os.getenv("CITADEL_ENV_SOURCE")
        or _os.getenv("CITADEL_ENV_FILE")
        or "/Users/ayushmudgal/Developer/CitadelOS/.env",
    )
)
canonical_runtime_truth = CanonicalRuntimeTruth()
argus_market_snapshot = ArgusMarketSnapshotProvider(
    argus.engine.dhan,
    state_path=argus_state_root / "argus" / "market_snapshot.json",
    master_path=argus_state_root / "argus" / "dhan_instrument_master.json",
)
order_flow_recorder = OrderFlowEvidenceRecorder(
    argus_state_root / "order_flow" / "evidence",
    # Preserve lossless capture while amortizing the durable stream's fsync and
    # SQLite checkpoint costs. Packet ingestion remains a non-blocking submit.
    coalesce_ms=250.0,
)
order_flow_service = IsolatedOrderFlowWorker(recorder=order_flow_recorder)
order_flow_research = OrderFlowResearchAggregator(
    order_flow_recorder,
    argus_state_root / "order_flow" / "research",
)
# Additive only: Fusion observes the existing canonical projections and uses
# the existing recorder queue. It owns neither a Dhan connection nor a worker.
fusion_shadow = FusionShadowEngine(recorder=order_flow_recorder)
fusion_shadow_eod = FusionShadowEODAnalyzer(order_flow_recorder)
vob_reversal_engine = VobReversalEngine()
option_buyer_intelligence_worker = OptionBuyerIntelligenceWorker()
from src.oracle.market_info_service import MarketInfoService
market_info_service = MarketInfoService()
# The parent backend remains launchd-owned.  Its one child owns the one Dhan
# socket so heavy downstream Python/GIL work cannot delay receive or keepalive.
market_data_gateway = IsolatedMarketDataGateway(
    on_tick=order_flow_service.ingest_tick,
    on_raw_packet=order_flow_recorder.submit_full_packet,
    on_transport_event=order_flow_recorder.submit_transport_event,
)


def _register_order_flow_basket(identities):
    """Atomically hand one canonical identity basket to feed, engine and recorder."""
    identities = tuple(identities or ())
    if not identities:
        return 0
    order_flow_service.register_instruments(identities)
    order_flow_recorder.register_instruments(identities)
    market_data_gateway.subscribe(gateway_instruments(identities))
    return len(identities)


def _bootstrap_order_flow_basket():
    """Resolve live identities without requiring a fresh ARGUS projection."""
    from src.order_flow.routing import InstrumentIdentity
    future = oracle_dev_service.resolver.resolve_futures("NIFTY")
    
    future_identity = InstrumentIdentity(
        exchange_segment=str(future.get("segment") or "NSE_FNO"),
        security_id=str(future["security_id"]),
        role="NIFTY_FUTURE",
        expiry=str(future.get("expiry") or future.get("expiry_date") or "") or None,
        strike=0,
        option_type="",
    )
    spot_identity = InstrumentIdentity(
        exchange_segment="IDX_I",
        security_id="13",
        role="NIFTY_SPOT",
        expiry=None,
        strike=0,
        option_type="",
    )
    banknifty_identity = InstrumentIdentity(
        exchange_segment="IDX_I",
        security_id="25",
        role="BANKNIFTY_SPOT",
        expiry=None,
        strike=0,
        option_type="",
    )
    midcap_identity = InstrumentIdentity(
        exchange_segment="IDX_I",
        security_id="442",
        role="MIDCPNIFTY_SPOT",
        expiry=None,
        strike=0,
        option_type="",
    )
    return (spot_identity, future_identity, banknifty_identity, midcap_identity)



_argus_coherent_lock = _Lock()
_argus_coherent_projection = None
_LIVE_ANALYTICS_CHILD = False
_live_analytics_cache = {
    "argus": None,
    "options_structure": None,
    "fusion_shadow": None,
    "telemetry": None,
}
_live_analytics_cache_lock = _Lock()


def _enrich_argus_projection(projection, *, refresh_market=False):
    result = dict(projection)
    result["data"] = dict(projection.get("data") or {})
    source_timestamp = (
        ((projection.get("data") or {}).get("underlying") or {}).get(
            "fetched_at"
        )
        if isinstance(projection.get("data"), dict)
        else None
    )
    try:
        market = (
            argus_market_snapshot.refresh(projection)
            if refresh_market
            else argus_market_snapshot.latest(source_timestamp)
        )
    except Exception as error:
        market = {
            "status": "UNAVAILABLE",
            "reason": str(error),
        }
    market_matches = (
        isinstance(market, dict)
        and market.get("status") == "AVAILABLE"
        and market.get("argus_source_timestamp") == source_timestamp
    )
    if market_matches:
        result["data"]["argus_market_snapshot"] = market
        option_event_times = sorted(
            str(value.get("source_timestamp"))
            for value in (market.get("option_market_depth") or {}).values()
            if isinstance(value, _Mapping) and value.get("source_timestamp")
        )
        if option_event_times:
            enriched_underlying = dict(result["data"].get("underlying") or {})
            # Freshness uses the oldest required option quote in the coherent
            # full-quote basket.  Receipt time remains separate and can never
            # masquerade as a provider event timestamp.
            enriched_underlying.update(
                {
                    "source_event_time": option_event_times[0],
                    "receipt_timestamp": market.get("fetched_at"),
                    "timestamp_semantics": "DHAN_FULL_QUOTE_OLDEST_REQUIRED_EVENT_TIME",
                }
            )
            result["data"]["underlying"] = enriched_underlying
        if isinstance(market.get("futures"), dict):
            result["data"]["futures"] = dict(market["futures"])
        if isinstance(market.get("option_market_depth"), dict):
            result["data"]["option_market_depth"] = dict(
                market["option_market_depth"]
            )
    return result


def _argus_cache_fanout(projection):
    """One producer owns option-candle fanout and the batched market snapshot."""

    global _argus_coherent_projection
    if not _LIVE_ANALYTICS_CHILD:
        boundary = globals().get("live_analytics_boundary")
        if boundary is not None and boundary.status().get("alive"):
            accepted = boundary.submit(
                "argus",
                {
                    "projection": projection,
                    "transport": market_data_gateway.health(),
                },
                timeout=1.0,
            )
            if accepted:
                return
            # An overloaded/dead analytical worker must not make the serving
            # parent calculate the same heavy path.  Retain the last snapshot;
            # health exposes the boundary failure independently.
            return
    fanout_started = _perf_counter()
    source_timestamp = None
    try:
        source_timestamp = str((projection.get("data") or {}).get("underlying", {}).get("fetched_at") or "") or None
    except AttributeError:
        source_timestamp = None
    oracle_runtime.timing.mark("ARGUS_SOURCE_RESPONSE", source_timestamp=source_timestamp)
    option_chart_feed.ingest(projection)
    oracle_runtime.timing.mark("OSE_PUBLICATION", source_timestamp=source_timestamp)
    oracle_runtime.timing.mark(
        "ARGUS_NORMALIZE_END",
        source_timestamp=source_timestamp,
        duration_ms=(_perf_counter() - fanout_started) * 1000.0,
    )
    enriched = _enrich_argus_projection(projection, refresh_market=True)
    data = enriched.get("data") if isinstance(enriched.get("data"), _Mapping) else {}
    underlying = (
        data.get("underlying")
        if isinstance(data.get("underlying"), _Mapping)
        else {}
    )
    if underlying.get("ltp") is not None and not _LIVE_ANALYTICS_CHILD:
        canonical_feature_service.publish_candle(
            {
                "timestamp": underlying.get("fetched_at") or "",
                "open": underlying.get("open") or underlying.get("ltp"),
                "high": underlying.get("high") or underlying.get("ltp"),
                "low": underlying.get("low") or underlying.get("ltp"),
                "close": underlying.get("ltp"),
                "volume": underlying.get("volume") or 0.0,
            },
            is_complete=False,
        )
    market = (
        data.get("argus_market_snapshot")
        if isinstance(data.get("argus_market_snapshot"), _Mapping)
        else {}
    )
    missing_component = None
    if not data.get("atm_window"):
        missing_component = "ARGUS_SEVEN_STRIKE_WINDOW_UNAVAILABLE"
    elif market.get("status") != "AVAILABLE":
        missing_component = "ARGUS_MARKET_SNAPSHOT_UNAVAILABLE"
    elif market.get("argus_source_timestamp") != underlying.get("fetched_at"):
        missing_component = "ARGUS_MARKET_SNAPSHOT_SOURCE_MISMATCH"
    elif not isinstance(data.get("futures"), _Mapping):
        missing_component = "ARGUS_FUTURES_SNAPSHOT_UNAVAILABLE"

    if missing_component is not None:
        with _argus_coherent_lock:
            retained = _deepcopy(_argus_coherent_projection)
        if not isinstance(retained, dict):
            return
        tactical = retained["data"].get("tactical_edge")
        tactical = _deepcopy(tactical) if isinstance(tactical, _Mapping) else {}
        prime = tactical.get("argus_prime")
        prime = _deepcopy(prime) if isinstance(prime, _Mapping) else {}
        truth = prime.get("data_truth")
        truth = _deepcopy(truth) if isinstance(truth, _Mapping) else {}
        source_event_time = (
            truth.get("source_event_time")
            or tactical.get("source_event_time")
        )
        receipt_timestamp = (
            truth.get("receipt_timestamp")
            or tactical.get("receipt_timestamp")
            or tactical.get("observation_timestamp")
        )
        source_timestamp = source_event_time
        try:
            source_age = max(
                0.0,
                (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(str(source_event_time))
                ).total_seconds(),
            )
        except (TypeError, ValueError):
            source_age = None
        try:
            receipt_age = max(
                0.0,
                (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(str(receipt_timestamp))
                ).total_seconds(),
            )
        except (TypeError, ValueError):
            receipt_age = None
        threshold = float(truth.get("freshness_threshold_seconds") or 20.0)
        retention_age = source_age if source_age is not None else receipt_age
        status_label = (
            "DEGRADED_STALE"
            if (retention_age is not None and retention_age > threshold)
            else "DEGRADED"
        )
        retained["status"] = status_label
        tactical.update(
            {
                "status": status_label,
                "freshness": "LAST_GOOD",
                "stale_reason": missing_component,
                "missing_components": [missing_component],
                "retained_source_timestamp": source_timestamp,
                "source_age_seconds": (
                    round(source_age, 1) if source_age is not None else None
                ),
                "receipt_age_seconds": (
                    round(receipt_age, 1) if receipt_age is not None else None
                ),
            }
        )
        decision = _deepcopy(tactical.get("decision") or {})
        decision.update(
            {
                "gate": "UNAVAILABLE",
                "current_action": "Last coherent ARGUS snapshot retained; action locked.",
                "action_enabled": False,
            }
        )
        tactical["decision"] = decision
        prime.update(
            {
                "status": status_label,
                "freshness": "LAST_GOOD",
                "display_state": status_label,
                "hero_state": "DATA STALE" if status_label == "DEGRADED_STALE" else "DATA LOCKED",
                "action": "HOLD",
                "stale_reason": missing_component,
                "source_age_seconds": (
                    round(source_age, 1) if source_age is not None else None
                ),
                "receipt_age_seconds": (
                    round(receipt_age, 1) if receipt_age is not None else None
                ),
                "retained_source_timestamp": source_timestamp,
                "hard_blocks": sorted(
                    set(list(prime.get("hard_blocks") or []) + [missing_component])
                ),
                "recommended_contract": None,
                "selected_contract_technicals": {
                    "status": "UNAVAILABLE",
                    "reason": missing_component,
                    "pullback_state": "WAITING_FOR_FRESH_COMPLETED_5M",
                },
            }
        )
        truth.update(
            {
                "age_seconds": (
                    round(source_age, 1) if source_age is not None else None
                ),
                "receipt_age_seconds": (
                    round(receipt_age, 1) if receipt_age is not None else None
                ),
                "source_event_time": source_event_time,
                "receipt_timestamp": receipt_timestamp,
                "freshness_basis": (
                    "PROVIDER_EVENT_TIME"
                    if source_event_time is not None
                    else "SOURCE_EVENT_TIME_UNAVAILABLE"
                ),
                "freshness_threshold_seconds": threshold,
                "state": "LAST_GOOD",
                "missing_component": missing_component,
                "retained_source_timestamp": source_timestamp,
            }
        )
        prime["data_truth"] = truth
        tactical["argus_prime"] = prime
        retained["data"]["tactical_edge"] = tactical
        if not _LIVE_ANALYTICS_CHILD:
            order_flow_service.register_decision_structure(
                retained,
                receive_ns=_perf_counter_ns(),
            )
        try:
            fusion_shadow.ingest_argus(retained, transport=market_data_gateway.health())
        except Exception:
            # Shadow research is isolated from canonical ARGUS publication.
            pass
        with _argus_coherent_lock:
            edge_lab = globals().get("argus_edge_lab")
            if edge_lab is not None and not _LIVE_ANALYTICS_CHILD:
                edge_lab.evaluate_once(retained)
            _argus_coherent_projection = retained
        return

    # The existing canonical ARGUS producer is the only REST owner.  It hands
    # the already-resolved current basket and any fresh canonical deltas to the
    # one order-flow socket owner; ATM changes cause no REST work here.
    flow_basket = basket_from_argus(enriched)
    try:
        argus_age = max(
            0.0,
            (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(str(underlying.get("fetched_at")))
            ).total_seconds(),
        )
    except (TypeError, ValueError):
        argus_age = float("inf")
    if flow_basket and not _LIVE_ANALYTICS_CHILD:
        # Identity rollover is independent of quote freshness.  Freshness gates
        # scoring/deltas below, never the transport subscription needed to
        # recover the next live snapshot.
        _register_order_flow_basket(flow_basket)
    if flow_basket and argus_age <= 20.0 and not _LIVE_ANALYTICS_CHILD:
        greek_receive_ns = _perf_counter_ns()
        for row in data.get("atm_window") or []:
            if not isinstance(row, _Mapping):
                continue
            for side in ("ce", "pe"):
                leg = row.get(side)
                if not isinstance(leg, _Mapping):
                    continue
                try:
                    order_flow_service.register_option_delta(
                        str(leg["security_id"]),
                        float(leg["delta"]),
                        receive_ns=greek_receive_ns,
                    )
                except (KeyError, TypeError, ValueError):
                    pass

    tactical = argus_tactical_edge.evaluate(
        enriched,
        options_structure_engine.projection(),
    )
    oracle_runtime.timing.mark(
        "ARGUS_CALC_END",
        source_timestamp=source_timestamp,
        duration_ms=(_perf_counter() - fanout_started) * 1000.0,
    )
    enriched["data"]["tactical_edge"] = tactical
    # The HUD receives the same coherent, fully evaluated ARGUS projection. It
    # only retains the already-computed ATM spine and never performs provider work.
    if not _LIVE_ANALYTICS_CHILD:
        order_flow_service.register_decision_structure(
            enriched,
            receive_ns=_perf_counter_ns(),
        )
        boundary = globals().get("live_analytics_boundary")
        if boundary is not None:
            boundary.submit(
                "argus",
                {
                    "projection": enriched,
                    "transport": market_data_gateway.health(),
                },
                timeout=0.05,
            )
    with _argus_coherent_lock:
        edge_lab = globals().get("argus_edge_lab")
        if edge_lab is not None and not _LIVE_ANALYTICS_CHILD:
            edge_lab.evaluate_once(enriched)
        _argus_coherent_projection = _deepcopy(enriched)
    try:
        fusion_shadow.ingest_argus(enriched, transport=market_data_gateway.health())
    except Exception:
        # Fusion has zero authority over the existing producer and can never
        # interrupt it if a research-only payload is malformed.
        pass
    oracle_runtime.timing.mark(
        "ARGUS_CACHE_WRITE",
        source_timestamp=source_timestamp,
        duration_ms=(_perf_counter() - fanout_started) * 1000.0,
    )
    oracle_runtime.timing.mark(
        "ARGUS_PUBLICATION",
        source_timestamp=source_timestamp,
        duration_ms=(_perf_counter() - fanout_started) * 1000.0,
    )


def current_argus_projection(symbol: str, expiry: str | None = None):
    """Refresh ARGUS once, then fan out that same authoritative snapshot."""

    projection = argus.get_oi_isolated(
        symbol, projection_process_worker, expiry=expiry
    )
    if expiry is None:
        option_chart_feed.ingest(projection)
    result = _enrich_argus_projection(projection, refresh_market=True)
    result["data"]["tactical_edge"] = argus_tactical_edge.evaluate(
        result,
        options_structure_engine.projection(),
    )
    return result


def cached_argus_projection(symbol: str):
    """Serve the last coherent producer-owned ARGUS projection without I/O.

    V2 must never run Tactical Edge, option-history loading, or Dhan work on
    the request thread.  The background/current ARGUS producer publishes one
    immutable tactical projection; this path only attaches that matching
    projection or fails closed while the producer catches up.
    """

    with _argus_coherent_lock:
        coherent = _deepcopy(_argus_coherent_projection)
    if isinstance(coherent, dict):
        underlying = (
            (coherent.get("data") or {}).get("underlying")
            if isinstance(coherent.get("data"), _Mapping)
            else None
        )
        expiry = underlying.get("expiry") if isinstance(underlying, _Mapping) else None
        if not argus.engine.is_active_expiry(expiry):
            # CURRENT cards are not permitted to inherit a finished contract
            # from LAST_GOOD.  A frozen trade remains available through its
            # separate episode identity, while current state fails closed.
            return {
                "status": "UNAVAILABLE",
                "reason": "CURRENT_EXPIRY_ROLLED_AWAITING_DHAN_RESOLUTION",
                "data": {},
            }
        source_timestamp = (
            underlying.get("fetched_at") if isinstance(underlying, _Mapping) else None
        )
        oracle_runtime.timing.mark("ARGUS_FAST_LANE_READ", source_timestamp=source_timestamp)
        return coherent

    # Cache-only request path: no store lookup, market snapshot lookup,
    # enrichment, provider call, Tactical Edge calculation, or OSE/VOB/EYE
    # work.  Startup simply reports a truthful unavailable state until the
    # producer publishes its first coherent immutable snapshot.
    return {
        "status": "UNAVAILABLE",
        "reason": "ARGUS_COHERENT_PROJECTION_NOT_READY",
        "data": {},
    }


control_status = ControlStatusAPI()
athena_service = AthenaService(
    risk_provider=control_status.risk_summary,
    paper_provider=control_status.paper_summary,
)
# No provider is activated in production by this foundation milestone.
# GET routes read only the current in-memory cache and never trigger refresh.
hermes_service = HermesService(provider=None)
oracle_service = OracleService(
    snapshot_provider=dashboard.latest_snapshot,
    timeframe=dashboard.settings.get("timeframe", "5m"),
    max_live_age_seconds=dashboard.settings.get(
        "max_market_data_age_seconds", 10
    ),
)
oracle_mission_service = OracleMissionService(
    Path(
        _os.environ.get(
            "CITADEL_STATE_ROOT",
            DEFAULT_STATE_ROOT,
        )
    )
    / "oracle_missions"
)
oracle_perception_root = Path(
    _os.environ.get(
        "CITADEL_STATE_ROOT",
        DEFAULT_STATE_ROOT,
    )
) / "oracle_perception"
oracle_context_service = ContextEngine(
    oracle_perception_root / "context",
    candle_path=Path(
        _os.environ.get(
            "CITADEL_STATE_ROOT",
            DEFAULT_STATE_ROOT,
        )
    ) / "vob_1m_candles.json",
)
oracle_visual_store = VisualObservationStore(oracle_perception_root / "visual")
_oracle_context_bootstrap_error = None
market_calendar = NSESessionCalendar()
canonical_nifty_candle_source = RealNiftyCandleSource(
    calendar=market_calendar,
    canonical_store_root="logs/strategy_lab/market_state/candles",
    history_days=140,
)
kronos_alpha_scheduler = KronosAlphaScheduler(
    calendar=market_calendar,
    candle_source=canonical_nifty_candle_source,
    config=KronosAlphaConfig(
        model_environment_python=Path("/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha/bin/python")
    )
)
kronos_alpha_service = KronosAlphaService(
    runtime_provider=kronos_alpha_scheduler.projection,
    ledger=kronos_alpha_scheduler.ledger,
)
_eye_state_root = Path(
    _os.environ.get("CITADEL_STATE_ROOT", DEFAULT_STATE_ROOT)
) / "eye"
eye_runtime = EyeRuntime(state_path=_eye_state_root / "strategy_state.json")
eye_completed_context = CompletedCandleContextProvider(
    candle_source=kronos_alpha_scheduler.candle_source,
    argus_provider=lambda: cached_argus_projection("NIFTY"),
    max_age_seconds=600.0,
)
eye_scanner = PersistentEyeScanner(
    eye_runtime,
    context_provider=eye_completed_context,
    # This scanner reads the existing Kronos/ARGUS caches only.  It owns no
    # Dhan connection, cannot be triggered by an Oracle page render, and will
    # publish no decision until the completed-candle context is authoritative.
)


def _eye_option_chart_bridge(_snapshot):
    """Fan out existing completed option candles into the one EYE kernel."""
    published = False
    for _side in ("CE", "PE"):
        rows = option_chart_feed.completed_candles(_side, limit=1)
        if rows:
            published = eye_runtime.ingest_option_candle(rows[-1]) or published
    if published:
        eye_runtime.kernel.process_cycle()


# EYE history hydration and subscription belong to the isolated Strategy
# owner.  The parent constructs the reviewed object graph before fork but does
# no canonical history load, hashing, or EYE strategy work.
chronos_2_scheduler = Chronos2Scheduler(
    calendar=market_calendar,
    candle_source=kronos_alpha_scheduler.candle_source,
    argus_provider=lambda: argus.projection("NIFTY"),
    config=Chronos2Config(
        environment_python=Path("/Users/ayushmudgal/Developer/CitadelOS/.venv-chronos-2/bin/python")
    )
)
chronos_2_service = Chronos2Service(
    chronos_2_scheduler,
    kronos_provider=kronos_alpha_service.status,
)
personal_oracle_service = dashboard.execution.personal_oracle
aegis_input_builder = AegisInputBuilder(
    technical=lambda symbol: oracle_service.assess(symbol).to_dict(),
    argus=lambda symbol: argus.projection(symbol),
    dashboard_cache=dashboard.latest_snapshot,
    kronos_alpha=kronos_alpha_service.status,
    athena=lambda: athena_service.assess().to_dict(),
    hermes=lambda: hermes_service.assessment().to_dict(),
    personal_oracle=personal_oracle_service.summary,
    risk=control_status.risk_summary,
    paper=control_status.paper_summary,
    session=market_calendar.status,
)
aegis_service = AegisService(aegis_input_builder)


def prepared_aegis_projection(symbol, prepared):
    """Background-only AEGIS composition from the immutable V2 feed snapshot."""
    projected = None
    for side in ("CE", "PE", "NONE"):
        snapshot = aegis_input_builder.from_prepared(
            symbol=str(symbol).upper(), requested_side=side, strategy_id="simple_pullback",
            live_path_requested=False, duplicate_request=False, prepared=prepared,
        )
        decision = aegis_service.project_snapshot(snapshot)
        if side == "NONE":
            projected = decision.to_dict()
    return projected
readiness_service = OpenMarketReadinessService(
    session=market_calendar.status,
    argus=lambda: argus.projection("NIFTY"),
    kronos_alpha=kronos_alpha_service.status,
    technical=lambda: oracle_service.assess("NIFTY").to_dict(),
    kronos_core=lambda: aegis_input_builder._kronos_core("NIFTY"),
    athena=lambda: athena_service.assess().to_dict(),
    hermes=lambda: hermes_service.assessment().to_dict(),
    personal_oracle=personal_oracle_service.summary,
    risk=control_status.risk_summary,
    kill_switch=control_status.kill_switch_summary,
    aegis=aegis_service.readiness,
)
order_fill_ledger = OrderFillLedgerService()
paper_execution_engine = PaperExecutionEngine(
    ledger=order_fill_ledger,
    paper_state=dashboard.execution.paper_state,
)
paper_trading_orchestrator = RealMarketPaperOrchestrator(
    candle_source=kronos_alpha_scheduler.candle_source,
    calendar=market_calendar,
    argus=argus,
    aegis=aegis_service,
    engine=paper_execution_engine,
    risk=PaperRiskAuthorization(paper_state=dashboard.execution.paper_state),
)
development_paper_state = PaperStateService("logs/development_paper_state.json")
development_order_ledger = OrderFillLedgerService(OrderFillStore("logs/development_order_fill_ledger.json"))
development_execution_engine = DevelopmentPaperExecutionEngine(
    ledger=development_order_ledger,
    paper_state=development_paper_state,
)
development_risk = DevelopmentRiskAuthorization(paper_state=development_paper_state)
development_orchestrator = DevelopmentPaperOrchestrator(
    candle_source=kronos_alpha_scheduler.candle_source,
    calendar=market_calendar,
    argus=argus,
    module_providers={
        "kronos_alpha": kronos_alpha_service.status,
        "chronos_2": chronos_2_service.status,
        "athena": lambda: athena_service.assess().to_dict(),
        "hermes": lambda: hermes_service.assessment().to_dict(),
        "oracle": personal_oracle_service.summary,
    },
    engine=development_execution_engine,
    risk=development_risk,
    defer_runtime_load=True,
)
strategy_lab_service = StrategyLabService(
    root=_os.environ.get("CITADEL_STRATEGY_LAB_ROOT", "logs/strategy_lab"),
    options_structure_provider=options_structure_engine.projection,
)
strategy_command_service = StrategyCommandService(
    _os.environ.get(
        "CITADEL_STRATEGY_COMMAND_ROOT",
        "logs/strategy_command",
    ),
    runtime_provider=strategy_lab_service.strategies,
)
argus_edge_lab = ArgusEdgeLab(
    _os.environ.get(
        "CITADEL_ARGUS_EDGE_LAB_ROOT",
        "logs/strategy_command/argus_edge_lab",
    ),
    registry=strategy_command_service,
    snapshot_provider=lambda: cached_argus_projection("NIFTY"),
)


def _strategies_command_projection():
    projection = strategy_command_service.projection()
    projection["edge_lab"] = argus_edge_lab.projection()
    return projection


pullback_market_context = CompletedCandleContextProvider(
    candle_source=kronos_alpha_scheduler.candle_source,
    argus_provider=lambda: argus.projection("NIFTY"),
    held_security_id_provider=deployment_held_security_id_provider(
        strategy_lab_service, "pullback-master-pine-v5"
    ),
)
breakout_market_context = CompletedCandleContextProvider(
    candle_source=kronos_alpha_scheduler.candle_source,
    argus_provider=lambda: argus.projection("NIFTY"),
    held_security_id_provider=deployment_held_security_id_provider(
        strategy_lab_service, "breakout-main-pine-v5"
    ),
)


def _strategy_command_context_factory(deployment):
    configuration = deployment.get("configuration") or {}
    market = configuration.get("market") or {}
    instrument = str(market.get("instrument") or "").upper()
    instance_id = str(deployment.get("deployment_instance_id") or "")
    if instrument != "NIFTY":
        return lambda: {
            "data_readiness": {
                "DATA_READY": False,
                "not_ready_reason": f"AUTHORITATIVE_MARKET_DATA_UNAVAILABLE:{instrument}",
            },
            "symbol": instrument,
        }
    return CompletedCandleContextProvider(
        candle_source=kronos_alpha_scheduler.candle_source,
        argus_provider=lambda: argus.projection(instrument),
        held_security_id_provider=deployment_held_security_id_provider(
            strategy_lab_service, instance_id
        ),
    )


strategy_command_runtime = StrategyCommandRuntimeBridge(
    command=strategy_command_service,
    lab=strategy_lab_service,
    context_factory=_strategy_command_context_factory,
)
strategy_lab_service.subscribe_events(strategy_command_service.observe_domain_event)
strategy_lab_service.deploy(
    build_pullback_master_deployment(pullback_market_context), start=False,
)
strategy_lab_service.deploy(
    build_breakout_main_deployment(breakout_market_context), start=False,
)


for option_deployment in build_option_chart_deployments(
    feed=option_chart_feed,
    argus_provider=lambda: argus.projection("NIFTY"),
    service=strategy_lab_service,
):
    strategy_lab_service.deploy(option_deployment, start=False)
operations_logger = StructuredEventLogger()


def _structured_strategy_event(event):
    try:
        payload = dict(event.payload)
        contract = payload.get("contract") if isinstance(payload.get("contract"), dict) else {}
        latency = payload.get("latency_ms")
        operations_logger.log(
            event.event_type,
            strategy=str(payload.get("strategy_id") or "STRATEGY_LAB"),
            runtime_mode="PAPER",
            correlation_id=event.event_id,
            symbol=str(payload.get("symbol") or contract.get("underlying") or "UNKNOWN"),
            timeframe=str(payload.get("timeframe") or "UNKNOWN"),
            latency_ms=latency if isinstance(latency, (int, float)) and not isinstance(latency, bool) else None,
            status=str(payload.get("status") or "RECORDED"),
            payload={"entity_id": event.entity_id, "parent_id": event.parent_id, "lineage": list(event.lineage)},
        )
    except Exception:
        operations_logger.record_failure()


strategy_lab_service.subscribe_events(_structured_strategy_event)


def _personal_oracle_strategy_event(event):
    try:
        if event.event_type == "TradeCandidateFormed":
            candidate = event.payload.get("candidate")
            if isinstance(candidate, _Mapping):
                personal_oracle_service.capture_shadow_advisory(candidate, source_event_id=event.event_id)
        elif event.event_type == "TradeCompleted":
            trade = event.payload.get("trade")
            if not isinstance(trade, _Mapping):
                return
            personal_oracle_service.ingest_strategy_lab_trade(trade, source_event_id=event.event_id)
    except Exception:
        # Advisory ingestion must never affect Strategy Lab execution.
        operations_logger.record_failure()


strategy_lab_service.subscribe_events(_personal_oracle_strategy_event)


def _runtime_latency_health():
    rows = strategy_lab_service.strategies().get("strategies") or []
    return {"status": "HEALTHY", "latency_ms": max((float(row.get("latency_ms") or 0) for row in rows), default=0.0)}


def _exception_health():
    counters = operations_logger.counters()
    return {"status": "FAILED" if counters["exceptions"] else "HEALTHY", **counters}


operations_monitor = ProductionHealthMonitor(
    {
        "scheduler": strategy_lab_service.status,
        "broker": lambda: {"status": "DISABLED_SAFE", "live_trading_enabled": False},
        "websocket": lambda: {"status": "DISABLED_SAFE", "live_trading_enabled": False},
        "quotes": lambda: {"status": "DISABLED_SAFE", "live_trading_enabled": False},
        "strategy_runtime": strategy_lab_service.status,
        "paper_engine": paper_trading_orchestrator.status,
        "runtime_latency": _runtime_latency_health,
        "processing_queue": lambda: {"status": "HEALTHY", "depth": 0},
        "exceptions": _exception_health,
    },
    logger=operations_logger,
)
operations_kill_switch = InstitutionalKillSwitch(
    control_status.risk_store,
    stop_strategies=strategy_lab_service.stop,
    cancel_pending_orders=strategy_lab_service.cancel_pending_orders,
    logger=operations_logger,
    monitoring_active=lambda: True,
)
operations_monitor_loop = OperationalMonitorLoop(operations_monitor, operations_kill_switch)
operations_service = ProductionOperationsService(
    monitor=operations_monitor,
    kill_switch=operations_kill_switch,
    strategy_provider=strategy_lab_service.strategies,
    risk_provider=control_status.risk_summary,
    recovery_provider=lambda: {"status": "READY", "live_trading_enabled": False},
    runtime_mode="PAPER",
)


# R2.1D process boundaries -------------------------------------------------
# The stateful objects above are intentionally constructed once before either
# child starts.  The boundaries start before any application-owned background
# thread, so macOS fork inherits this exact reviewed engine graph without
# recreating a Dhan websocket owner or a second Flow pipeline.
_strategy_boundary_cache_lock = _Lock()
_strategy_boundary_cache = {}
_strategy_child_latest_options = None
_strategy_child_truth_token = None
_strategy_child_truth_revision = 0
_strategy_child_truth_hash = None
_strategy_child_truth_hash_count = 0
_strategy_child_start_timings = {}
_strategy_child_compute_timings = {}
_strategy_child_live_dashboard_cache = None
_strategy_child_live_candle_revision = None
_strategy_child_command_cache = None
_strategy_child_analytics_queue = None
_strategy_child_analytics_stop = None
_strategy_child_analytics_thread = None
_strategy_child_analytics_coalesces = 0
_strategy_last_submitted_argus_source = None
_parent_last_applied_argus_source = None
_fusion_event_ids_seen = set()
_vob_reversal_event_ids_seen = set()
_nifty_horsepower_source_signature = None


def _seed_argus_cache(projection):
    """Make an already-fetched ARGUS response visible to child-local readers."""

    if not isinstance(projection, _Mapping):
        return
    data = projection.get("data")
    underlying = data.get("underlying") if isinstance(data, _Mapping) else None
    if not isinstance(data, _Mapping) or not isinstance(underlying, _Mapping):
        return
    symbol = str(underlying.get("symbol") or "NIFTY").upper()
    expiry = underlying.get("expiry")
    with argus._lock:
        argus._cache[(symbol, expiry)] = {
            "data": _deepcopy(dict(data)),
            "cached_at": argus.clock(),
        }


def _live_analytics_child_start():
    global _LIVE_ANALYTICS_CHILD
    _LIVE_ANALYTICS_CHILD = True
    # Fusion events cross the process boundary and are persisted by the one
    # authoritative parent recorder.  The inherited recorder has no worker.
    fusion_shadow.recorder = None


def _refresh_current_itm_vobs_from_canonical_history(projection):
    """Evaluate the rotating ARGUS ITM-1 pair on its own canonical candles.

    This runs inside the existing live-analytics worker, never on an HTTP
    path.  OSE remains the one Dhan/history owner; VOB reversal only accepts
    a value if its security id still equals the current ARGUS resolution.
    """
    if not isinstance(projection, _Mapping):
        return
    data = projection.get("data") if isinstance(projection.get("data"), _Mapping) else {}
    underlying = data.get("underlying") if isinstance(data.get("underlying"), _Mapping) else {}
    observed_at = underlying.get("fetched_at") or underlying.get("source_event_time")
    if not observed_at:
        return
    current = vob_reversal_engine.projection().get("current_itm1_contracts") or {}
    technicals = {}
    for side in ("CE", "PE"):
        item = current.get(side) if isinstance(current.get(side), _Mapping) else {}
        contract = item.get("contract") if isinstance(item.get("contract"), _Mapping) else {}
        quote = item.get("quote") if isinstance(item.get("quote"), _Mapping) else {}
        if not contract.get("security_id"):
            continue
        try:
            technicals[side] = options_structure_engine.contract_technicals({
                **dict(contract), "side": side, "option_type": side,
                "premium": quote.get("ltp"),
            }, observed_at)
        except Exception as error:
            technicals[side] = {
                "status": "UNAVAILABLE",
                "reason": f"CURRENT_ITM_VOB_UNAVAILABLE:{type(error).__name__}",
            }
    vob_reversal_engine.ingest_current_itm_vobs(technicals)


def _refresh_nifty_horsepower_from_canonical_history():
    """Observe the canonical NIFTY session reservoir and persisted VOB state.

    This runs only in the existing live-analytics child. It reads prepared
    files, reuses OSE's session-aligned resampler, and never forms VOB zones or
    creates a broker/data owner.
    """
    global _nifty_horsepower_source_signature
    state_root = Path(_os.environ.get(
        "CITADEL_STATE_ROOT", DEFAULT_STATE_ROOT
    ))
    zone_candidates = (
        state_root / "vob_state.json",
        state_root / "oracle_dev" / "vob_state.json",
    )
    zone_path = next((path for path in zone_candidates if path.exists()), None)
    candle_candidates = (
        state_root / "oracle_dev" / "candle_store_spot_1m.json",
        state_root / "vob_1m_candles.json",
    )
    candle_path = next((path for path in candle_candidates if path.exists()), None)
    if zone_path is None or candle_path is None:
        vob_reversal_engine.ingest_nifty_horsepower({
            "status": "UNAVAILABLE", "reason": "CANONICAL_NIFTY_SESSION_FILES_UNAVAILABLE",
        })
        return
    signature = (
        zone_path.stat().st_mtime_ns, zone_path.stat().st_size,
        candle_path.stat().st_mtime_ns, candle_path.stat().st_size,
    )
    if signature == _nifty_horsepower_source_signature:
        return
    try:
        zones_by_timeframe = _json.loads(zone_path.read_text(encoding="utf-8"))
        raw_candles = _json.loads(candle_path.read_text(encoding="utf-8"))
        if isinstance(raw_candles, _Mapping):
            raw_candles = raw_candles.get("candles") or []
        zone_dates = [
            str(zone.get("confirmation_candle_time") or zone.get("origin_candle_time") or "")[:10]
            for zones in zones_by_timeframe.values() if isinstance(zones, _Mapping)
            for zone in zones.values() if isinstance(zone, _Mapping)
        ]
        ist = timezone(timedelta(hours=5, minutes=30))
        observed_at = datetime.now(tz=ist)
        parsed_candles = []
        for raw in raw_candles if isinstance(raw_candles, list) else []:
            if not isinstance(raw, _Mapping):
                continue
            timestamp = raw.get("timestamp") or raw.get("time")
            try:
                if isinstance(timestamp, (int, float)):
                    opened = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).astimezone(ist)
                else:
                    opened = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).astimezone(ist)
                closed_at = opened + timedelta(minutes=1)
                if not (
                    (opened.hour, opened.minute) >= (9, 15)
                    and (opened.hour, opened.minute) <= (15, 29)
                    and closed_at <= observed_at
                ):
                    continue
                parsed_candles.append({
                    "opened": opened,
                    "candle": {
                        "timestamp": opened.isoformat(),
                        "candle_closed_at": closed_at.isoformat(),
                        "open": float(raw["open"]), "high": float(raw["high"]),
                        "low": float(raw["low"]), "close": float(raw["close"]),
                        "volume": float(raw.get("volume") or 0.0),
                        "closed": True, "is_closed": True,
                    }
                })
            except (KeyError, TypeError, ValueError, OverflowError):
                continue

        if not parsed_candles:
            vob_reversal_engine.ingest_nifty_horsepower({
                "status": "UNAVAILABLE",
                "reason": "NO_VALID_FINALIZED_CANDLES",
            })
            return

        session_id = parsed_candles[-1]["opened"].date().isoformat()
        one_minute = [
            item["candle"] for item in parsed_candles
            if item["opened"].date().isoformat() == session_id
        ]
        if not one_minute:
            vob_reversal_engine.ingest_nifty_horsepower({
                "status": "UNAVAILABLE",
                "reason": "NO_CURRENT_SESSION_FINALIZED_CANDLES",
            })
            return
        rows_by_timeframe = {
            "1m": one_minute,
            "3m": options_structure_engine._resample(one_minute, 3),
            "5m": options_structure_engine._resample(one_minute, 5),
        }
        lanes = {}
        for timeframe, rows in rows_by_timeframe.items():
            zone_map = zones_by_timeframe.get(timeframe)
            zone_ladder = list(zone_map.values()) if isinstance(zone_map, _Mapping) else []
            lanes[timeframe] = {
                "latest_finalized_bar": dict(rows[-1]) if rows else None,
                "session_finalized_bars": [dict(row) for row in rows],
                "zone_ladder": [dict(zone) for zone in zone_ladder if isinstance(zone, _Mapping)],
            }
        last_close = one_minute[-1]["candle_closed_at"] if one_minute else None
        vob_reversal_engine.ingest_nifty_horsepower({
            "status": "AVAILABLE", "security_id": "NIFTY", "vob_timeframes": lanes,
            "source_timestamp": last_close,
            "quality": {
                "valid": bool(one_minute and any(lanes[tf]["zone_ladder"] for tf in ("1m", "3m", "5m"))),
                "session_id": session_id,
                "candle_source": str(candle_path), "zone_source": str(zone_path),
                "latest_finalized_candle": last_close,
                "forming_candle_excluded": True,
            },
        })
        _nifty_horsepower_source_signature = signature
    except Exception as error:
        vob_reversal_engine.ingest_nifty_horsepower({
            "status": "UNAVAILABLE",
            "reason": f"CANONICAL_NIFTY_HORSEPOWER_UNAVAILABLE:{type(error).__name__}",
        })


def _live_analytics_child_processor(kind, payload):
    if kind == "flow":
        flow = payload.get("flow") if isinstance(payload, _Mapping) else None
        transport = payload.get("transport") if isinstance(payload, _Mapping) else None
        fusion_shadow.ingest_flow(flow, transport=transport)
        vob_reversal_engine.ingest_flow(flow)
        # Flow arrives at packet cadence.  Its state is retained locally and
        # the boundary's bounded 2 Hz snapshotter publishes the newest state;
        # serializing the full analytical document per packet would recreate
        # the parent/IPC pressure this boundary exists to remove.
        return None
    elif kind == "argus":
        projection = payload.get("projection") if isinstance(payload, _Mapping) else payload
        transport = payload.get("transport") if isinstance(payload, _Mapping) else None
        if isinstance(transport, _Mapping):
            # The existing fanout reads transport while updating Fusion.
            fusion_shadow.ingest_flow(fusion_shadow._latest_flow, transport=transport)
        _seed_argus_cache(projection)
        _argus_cache_fanout(projection)
        if isinstance(projection, _Mapping):
            vob_reversal_engine.ingest_argus(projection)
            _refresh_current_itm_vobs_from_canonical_history(projection)
    else:
        raise ValueError(f"unsupported live analytics input: {kind}")
    return _live_analytics_child_snapshot()


def _live_analytics_child_snapshot():
    _refresh_nifty_horsepower_from_canonical_history()
    with _argus_coherent_lock:
        coherent = _deepcopy(_argus_coherent_projection)
    ose = options_structure_engine.projection()
    # Reuse the projection already needed by this bounded snapshot.  This
    # avoids an additional full OSE copy at ARGUS input cadence.
    vob_reversal_engine.ingest_ose(ose)
    vob_projection = vob_reversal_engine.projection()
    option_buyer_intelligence = option_buyer_intelligence_worker.prepare(
        coherent if isinstance(coherent, _Mapping) else {},
        vob_projection,
        flow=getattr(fusion_shadow, "_latest_flow", None),
    )
    return {
        "argus": coherent,
        "options_structure": ose,
        "fusion_shadow": fusion_shadow.projection(),
        "vob_reversal": vob_projection,
        "option_buyer_intelligence": option_buyer_intelligence,
        "fusion_events": fusion_shadow.session_events()[-32:],
        "vob_reversal_events": vob_reversal_engine.events(limit=32),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _apply_live_analytics_snapshot(snapshot):
    """Atomic parent cache swap plus bounded lightweight ownership handoffs."""

    global _argus_coherent_projection, _strategy_last_submitted_argus_source
    global _parent_last_applied_argus_source
    if not isinstance(snapshot, _Mapping):
        return
    coherent = snapshot.get("argus")
    ose = snapshot.get("options_structure")
    fusion = snapshot.get("fusion_shadow")
    vob_reversal = snapshot.get("vob_reversal")
    option_buyer_intelligence = snapshot.get("option_buyer_intelligence")
    with _live_analytics_cache_lock:
        _live_analytics_cache.update(
            {
                "argus": coherent if isinstance(coherent, dict) else None,
                "options_structure": ose if isinstance(ose, dict) else None,
                "fusion_shadow": fusion if isinstance(fusion, dict) else None,
                "vob_reversal": vob_reversal if isinstance(vob_reversal, dict) else None,
                "option_buyer_intelligence": option_buyer_intelligence if isinstance(option_buyer_intelligence, dict) else None,
                "telemetry": {"received_at": datetime.now(timezone.utc).isoformat()},
            }
        )
    # R2.1F: these are already the immutable outputs from the isolated Live
    # Analytics worker.  Push the same values to the Fast Lane collector once;
    # do not make FastAPI-owned poll threads deepcopy them again.
    fast_lane = globals().get("oracle_fast_lane")
    if fast_lane is not None:
        fast_lane.publish_provider_value("argus", coherent)
        fast_lane.publish_provider_value("options_structure", ose)
        fast_lane.publish_provider_value("fusion_shadow", fusion)
        fast_lane.publish_provider_value("vob_reversal", vob_reversal)
        fast_lane.publish_provider_value("option_buyer_intelligence", option_buyer_intelligence)

    # Forward canonical live analytics snapshot to Citadel Live Island
    try:
        from src.oracle.live_island.hub import LiveIslandIntelligenceHub
        LiveIslandIntelligenceHub.get_instance().ingest_live_analytics_snapshot(snapshot)
    except Exception as _li_exc:
        logger.debug("Live Island snapshot ingestion error: %s", _li_exc)

    if isinstance(coherent, dict):
        with _argus_coherent_lock:
            _argus_coherent_projection = coherent
        data = coherent.get("data") if isinstance(coherent.get("data"), _Mapping) else {}
        underlying = data.get("underlying") if isinstance(data.get("underlying"), _Mapping) else {}
        source_timestamp = underlying.get("fetched_at")
        source_changed = (
            source_timestamp is not None
            and source_timestamp != _parent_last_applied_argus_source
        )
        if source_changed:
            _parent_last_applied_argus_source = source_timestamp
        if source_changed and underlying.get("ltp") is not None:
            canonical_feature_service.publish_candle(
                {
                    "timestamp": underlying.get("fetched_at") or "",
                    "open": underlying.get("open") or underlying.get("ltp"),
                    "high": underlying.get("high") or underlying.get("ltp"),
                    "low": underlying.get("low") or underlying.get("ltp"),
                    "close": underlying.get("ltp"),
                    "volume": underlying.get("volume") or 0.0,
                },
                is_complete=False,
            )
        flow_basket = basket_from_argus(coherent) if source_changed else ()
        if flow_basket:
            _register_order_flow_basket(flow_basket)
            receive_ns = _perf_counter_ns()
            for row in data.get("atm_window") or []:
                if not isinstance(row, _Mapping):
                    continue
                for side in ("ce", "pe"):
                    leg = row.get(side)
                    try:
                        order_flow_service.register_option_delta(
                            str(leg["security_id"]),
                            float(leg["delta"]),
                            receive_ns=receive_ns,
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
        if source_changed:
            order_flow_service.register_decision_structure(
                coherent, receive_ns=_perf_counter_ns()
            )
        strategy_boundary = globals().get("strategy_lab_boundary")
        if (
            strategy_boundary is not None
            and source_timestamp is not None
            and source_timestamp != _strategy_last_submitted_argus_source
        ):
            _strategy_last_submitted_argus_source = source_timestamp
            strategy_boundary.submit(
                "analytics",
                {"argus": coherent, "options_structure": ose},
                timeout=0.25,
            )
    for event in snapshot.get("fusion_events") or []:
        if not isinstance(event, _Mapping):
            continue
        identity = event.get("event_id") or event.get("state_event_id") or event.get("trade_id")
        if identity and str(identity) not in _fusion_event_ids_seen:
            _fusion_event_ids_seen.add(str(identity))
            if len(_fusion_event_ids_seen) > 4096:
                _fusion_event_ids_seen.clear()
                _fusion_event_ids_seen.add(str(identity))
            order_flow_recorder.submit(
                str(event.get("event_type") or "ARGUS_FUSION_EVENT"),
                dict(event),
                str(identity),
            )
    for event in snapshot.get("vob_reversal_events") or []:
        if not isinstance(event, _Mapping):
            continue
        identity = event.get("event_id")
        if identity and str(identity) not in _vob_reversal_event_ids_seen:
            _vob_reversal_event_ids_seen.add(str(identity))
            if len(_vob_reversal_event_ids_seen) > 4096:
                _vob_reversal_event_ids_seen.clear()
                _vob_reversal_event_ids_seen.add(str(identity))
            order_flow_recorder.submit(
                str(event.get("event_type") or "VOB_REVERSAL_SHADOW_EVENT"),
                dict(event),
                str(identity),
            )


def _live_analytics_cached(name, default=None):
    boundary_status = live_analytics_boundary.status()
    is_alive = bool(boundary_status.get("alive"))
    output_age = boundary_status.get("last_output_age_seconds")
    is_stale = (output_age is not None and output_age > 10.0) or not is_alive

    with _live_analytics_cache_lock:
        value = _live_analytics_cache.get(name)
    if value is not None:
        val = _deepcopy(value)
        if is_stale and isinstance(val, dict):
            val["status"] = "STALE"
            val["reason"] = "LIVE_ANALYTICS_WORKER_DEAD" if not is_alive else "LIVE_ANALYTICS_OUTPUT_STALE"
            val["is_stale"] = True
            val["worker_alive"] = is_alive
            val["last_good_timestamp"] = boundary_status.get("last_good_timestamp")
        return val
    return _deepcopy(default) if default is not None else {
        "status": "UNAVAILABLE",
        "reason": "LIVE_ANALYTICS_WORKER_DEAD" if not is_alive else "LIVE_ANALYTICS_WORKER_WARMING",
    }


def _strategy_child_start():
    global _strategy_child_truth_token, _strategy_child_truth_revision
    global _strategy_child_truth_hash, _strategy_child_truth_hash_count
    global _strategy_child_start_timings, _strategy_child_live_dashboard_cache
    global _strategy_child_live_candle_revision, _strategy_child_command_cache
    global _strategy_child_analytics_queue, _strategy_child_analytics_stop
    global _strategy_child_analytics_thread, _strategy_child_analytics_coalesces
    started = _perf_counter()
    # Strategy Lab owns its own candle/recovery state but must not calculate a
    # second OSE.  It receives the authoritative OSE snapshot from Analytics.
    reset_state_truth_runtime_metrics()
    reset_storage_runtime_metrics()
    _strategy_child_truth_token = None
    _strategy_child_truth_revision = 0
    _strategy_child_truth_hash = None
    _strategy_child_truth_hash_count = 0
    _strategy_child_live_dashboard_cache = None
    _strategy_child_live_candle_revision = None
    _strategy_child_command_cache = None
    _strategy_child_analytics_queue = _queue.Queue(maxsize=1)
    _strategy_child_analytics_stop = _ThreadEvent()
    _strategy_child_analytics_coalesces = 0
    with option_chart_feed._lock:
        option_chart_feed._observers = []
    for side in ("CE", "PE"):
        eye_runtime.hydrate_option_history(
            option_chart_feed.completed_candles(side, limit=96)
        )
    hydrated = _perf_counter()
    option_chart_feed.subscribe(_eye_option_chart_bridge)
    strategy_lab_service._options_structure_provider = (
        lambda: _deepcopy(_strategy_child_latest_options)
        if isinstance(_strategy_child_latest_options, dict)
        else {"status": "UNAVAILABLE", "reason": "LIVE_ANALYTICS_NOT_READY"}
    )
    strategy_lab_service.start()
    service_started = _perf_counter()
    strategy_command_runtime.synchronize_all()
    commands_synced = _perf_counter()
    operations_monitor_loop.start()
    eye_scanner.start()
    oracle_condition_monitor.start()
    argus_edge_lab.start()
    if not ORACLE_TURBO_MODE:
        development_orchestrator.start()
    _strategy_child_analytics_thread = _Thread(
        target=_strategy_child_analytics_loop,
        name="citadel-strategy-current-truth",
        daemon=True,
    )
    _strategy_child_analytics_thread.start()
    completed = _perf_counter()
    _strategy_child_start_timings = {
        "worker_start_ms": round((completed - started) * 1000.0, 3),
        "option_history_prepare_ms": round((hydrated - started) * 1000.0, 3),
        "strategy_service_start_ms": round((service_started - hydrated) * 1000.0, 3),
        "strategy_command_sync_ms": round((commands_synced - service_started) * 1000.0, 3),
        "auxiliary_start_ms": round((completed - commands_synced) * 1000.0, 3),
    }


def _strategy_child_stop():
    global _strategy_child_analytics_thread
    if _strategy_child_analytics_stop is not None:
        _strategy_child_analytics_stop.set()
    if _strategy_child_analytics_queue is not None:
        try:
            _strategy_child_analytics_queue.put_nowait(None)
        except _queue.Full:
            pass
    if _strategy_child_analytics_thread is not None:
        _strategy_child_analytics_thread.join(timeout=2.0)
        _strategy_child_analytics_thread = None
    argus_edge_lab.stop()
    if not ORACLE_TURBO_MODE:
        development_orchestrator.stop()
    oracle_condition_monitor.stop()
    eye_scanner.stop()
    operations_monitor_loop.stop()
    strategy_lab_service.stop()


def _strategy_child_analytics_loop():
    global _strategy_child_compute_timings, _strategy_child_live_dashboard_cache
    global _strategy_child_live_candle_revision
    while _strategy_child_analytics_stop is not None and not _strategy_child_analytics_stop.is_set():
        try:
            payload = _strategy_child_analytics_queue.get(timeout=0.25)
        except _queue.Empty:
            continue
        if payload is None:
            return
        started = _perf_counter()
        projection = payload.get("argus") if isinstance(payload, _Mapping) else None
        _seed_argus_cache(projection)
        cache_seeded = _perf_counter()
        option_chart_feed.ingest(projection)
        strategy_computed = _perf_counter()
        candle_revision = tuple(
            option_chart_feed.current_revision(side, timeframe)
            for side in ("CE", "PE")
            for timeframe in ("1m", "3m", "5m")
        )
        if candle_revision != _strategy_child_live_candle_revision:
            _strategy_child_live_candle_revision = candle_revision
            refresh_started = _perf_counter()
            refreshed_dashboard = strategy_lab_service.dashboard(
                live_publication=True,
                prepared_options_structure=None,
            )
            _strategy_child_live_dashboard_cache = refreshed_dashboard
            refresh_ms = (_perf_counter() - refresh_started) * 1000.0
        else:
            refresh_ms = 0.0
        prior_max = float(_strategy_child_compute_timings.get("strategy_computation_max_ms") or 0.0)
        strategy_ms = (strategy_computed - cache_seeded) * 1000.0
        _strategy_child_compute_timings = {
            "options_preparation_ms": _strategy_child_compute_timings.get("options_preparation_ms", 0.0),
            "argus_cache_seed_ms": round((cache_seeded - started) * 1000.0, 3),
            "strategy_computation_ms": round(strategy_ms, 3),
            "strategy_computation_max_ms": round(max(prior_max, strategy_ms), 3),
            "background_dashboard_refresh_ms": round(refresh_ms, 3),
            "total_ms": round((strategy_computed - started) * 1000.0, 3),
            "argus_edge_execution": "BACKGROUND_EXISTING_ENGINE",
            "analytics_lane_debt": _strategy_child_analytics_queue.qsize(),
            "analytics_lane_coalesces": _strategy_child_analytics_coalesces,
        }


def _strategy_child_processor(kind, payload):
    global _strategy_child_latest_options, _strategy_child_compute_timings
    global _strategy_child_analytics_coalesces
    global _strategy_child_live_dashboard_cache, _strategy_child_live_candle_revision
    if kind != "analytics":
        raise ValueError(f"unsupported strategy worker input: {kind}")
    if not isinstance(payload, _Mapping):
        return None
    started = _perf_counter()
    _strategy_child_latest_options = _deepcopy(payload.get("options_structure"))
    options_prepared = _perf_counter()
    envelope = {"argus": payload.get("argus")}
    try:
        _strategy_child_analytics_queue.put_nowait(envelope)
    except _queue.Full:
        try:
            _strategy_child_analytics_queue.get_nowait()
        except _queue.Empty:
            pass
        _strategy_child_analytics_queue.put_nowait(envelope)
        _strategy_child_analytics_coalesces += 1
    _strategy_child_compute_timings["options_preparation_ms"] = round(
        (options_prepared - started) * 1000.0, 3
    )
    _strategy_child_compute_timings["analytics_lane_debt"] = _strategy_child_analytics_queue.qsize()
    _strategy_child_compute_timings["analytics_lane_coalesces"] = _strategy_child_analytics_coalesces
    return None


def _strategy_child_snapshot():
    global _strategy_child_truth_token, _strategy_child_truth_revision
    global _strategy_child_truth_hash, _strategy_child_truth_hash_count
    global _strategy_child_live_dashboard_cache, _strategy_child_command_cache
    snapshot_started = _perf_counter()
    prepared_options = None
    if isinstance(_strategy_child_latest_options, _Mapping):
        prepared_options = {
            key: _deepcopy(_strategy_child_latest_options.get(key))
            for key in (
                "status", "reason", "runtime_status", "source_timestamp",
                "source_age_seconds", "source_freshness", "pair_status",
                "expiry", "symbol", "paper_only", "live_trading_enabled",
                "broker_submission", "advisory_only", "execution_influence",
            )
            if key in _strategy_child_latest_options
        }
        contracts = _strategy_child_latest_options.get("contracts")
        if isinstance(contracts, _Mapping):
            prepared_options["contracts"] = {
                str(side): {"contract": _deepcopy((row or {}).get("contract"))}
                for side, row in contracts.items()
                if isinstance(row, _Mapping)
            }
    options_prepared = _perf_counter()
    dashboard_cache_hit = isinstance(_strategy_child_live_dashboard_cache, dict)
    if dashboard_cache_hit:
        dashboard_snapshot = _deepcopy(_strategy_child_live_dashboard_cache)
        if isinstance(dashboard_snapshot.get("execution"), dict):
            dashboard_snapshot["execution"]["options_structure"] = prepared_options or {
                "status": "UNAVAILABLE",
                "reason": "PREPARED_OPTIONS_NOT_YET_RECEIVED",
            }
    else:
        dashboard_snapshot = strategy_lab_service.dashboard(
            live_publication=True,
            prepared_options_structure=prepared_options,
        )
        _strategy_child_live_dashboard_cache = _deepcopy(dashboard_snapshot)
    dashboard_ready = _perf_counter()
    development_snapshot = {
        "status": "DEFERRED_FROM_LIVE_SNAPSHOT",
        "paper_only": True,
        "live_trading_enabled": False,
        "broker_submission": False,
    }
    eye_snapshot = eye_scanner.status()
    condition_snapshot = oracle_condition_monitor.health()
    auxiliary_ready = _perf_counter()
    strategy_rows = dashboard_snapshot.get("strategies") or []
    truth_token = (
        tuple(
            (
                row.get("strategy_id"), row.get("state"), row.get("health"),
                row.get("last_updated"), row.get("current_decision"),
                row.get("current_position_count"), row.get("today_trades"),
            )
            for row in strategy_rows if isinstance(row, _Mapping)
        ),
        (development_snapshot.get("status") or {}).get("updated_at")
        if isinstance(development_snapshot.get("status"), _Mapping)
        else development_snapshot.get("updated_at"),
        eye_snapshot.get("last_candle_id"),
        eye_snapshot.get("evaluations"),
        condition_snapshot.get("status"),
        condition_snapshot.get("last_error"),
    )
    if truth_token != _strategy_child_truth_token:
        _strategy_child_truth_token = truth_token
        _strategy_child_truth_revision += 1
        _strategy_child_truth_hash = _hashlib.sha256(
            _json.dumps(truth_token, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        _strategy_child_truth_hash_count += 1
    truth_ready = _perf_counter()
    execution = dashboard_snapshot.get("execution") if isinstance(dashboard_snapshot.get("execution"), _Mapping) else {}
    command_started = _perf_counter()
    if not isinstance(_strategy_child_command_cache, dict):
        _strategy_child_command_cache = _strategies_command_projection()
    strategies_command_snapshot = _deepcopy(_strategy_child_command_cache)
    edge_lab_snapshot = _deepcopy(strategies_command_snapshot.get("edge_lab") or {})
    commands_ready = _perf_counter()
    state_truth = state_truth_runtime_metrics()
    storage_truth = storage_runtime_metrics()
    runtime_truth_ready = _perf_counter()
    result = {
        "status": dashboard_snapshot.get("status") or strategy_lab_service.status(),
        "dashboard": dashboard_snapshot,
        "strategies": {"status": "available", "strategies": strategy_rows, "count": len(strategy_rows)},
        "leaderboard": dashboard_snapshot.get("leaderboard") or {},
        "portfolio": dashboard_snapshot.get("portfolio") or {},
        "positions": {"status": "available", "positions": execution.get("positions") or [], "count": len(execution.get("positions") or []), "paper_only": True},
        "orders": {"status": "available", "orders": execution.get("orders") or [], "count": len(execution.get("orders") or []), "paper_only": True},
        "fills": {"status": "available", "fills": execution.get("fills") or [], "count": len(execution.get("fills") or []), "paper_only": True},
        "open_trades": {"status": "available", "open_trades": execution.get("authoritative_open_positions") or [], "count": len(execution.get("authoritative_open_positions") or []), "paper_only": True},
        "closed_trades": {"status": "available", "closed_trades": execution.get("closed_trades") or [], "count": len(execution.get("closed_trades") or []), "paper_only": True},
        "strategies_command": strategies_command_snapshot,
        "edge_lab": edge_lab_snapshot,
        "development": development_snapshot,
        "eye_scanner": eye_snapshot,
        "condition_monitor": condition_snapshot,
        "truth": {
            "owner_pid": _os.getpid(),
            "strategy_revision": _strategy_child_truth_revision,
            "truth_revision": _strategy_child_truth_revision,
            "semantic_hash": _strategy_child_truth_hash,
            "hash_count": _strategy_child_truth_hash_count,
            "source_timestamp": dashboard_snapshot.get("generated_at"),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "health": "HEALTHY",
            "state_truth": state_truth,
            "storage": storage_truth,
            "publication_timings": {
                **_strategy_child_start_timings,
                **_strategy_child_compute_timings,
                "prepared_nifty_vob_ms": 0.0,
                "prepared_nifty_vob_source": "NOT_AVAILABLE_IN_CANONICAL_LIVE_INPUT",
                "prepared_options_copy_ms": round((options_prepared - snapshot_started) * 1000.0, 3),
                "live_strategy_snapshot_ms": round((dashboard_ready - options_prepared) * 1000.0, 3),
                "live_strategy_snapshot_cache_hit": dashboard_cache_hit,
                "auxiliary_status_ms": round((auxiliary_ready - dashboard_ready) * 1000.0, 3),
                "truth_revision_ms": round((truth_ready - auxiliary_ready) * 1000.0, 3),
                "strategy_command_projection_ms": round((commands_ready - command_started) * 1000.0, 3),
                "runtime_truth_ms": round((runtime_truth_ready - commands_ready) * 1000.0, 3),
            },
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    serialization_started = _perf_counter()
    serialized_bytes = len(_pickle.dumps(result, protocol=5))
    result["truth"]["publication_timings"].update({
        "serialization_ms": round((_perf_counter() - serialization_started) * 1000.0, 3),
        "serialized_bytes": serialized_bytes,
        "snapshot_total_ms": round((_perf_counter() - snapshot_started) * 1000.0, 3),
    })
    return result


def _apply_strategy_snapshot(snapshot):
    if not isinstance(snapshot, _Mapping):
        return
    with _strategy_boundary_cache_lock:
        _strategy_boundary_cache.clear()
        _strategy_boundary_cache.update(snapshot)


def _strategy_cached(name, default=None):
    with _strategy_boundary_cache_lock:
        value = _strategy_boundary_cache.get(name)
    if value is not None:
        return _deepcopy(value)
    if default is not None:
        return _deepcopy(default)
    status_summary = {
        "status": "UNAVAILABLE",
        "reason": "STRATEGY_LAB_WORKER_WARMING",
        "paper_only": True,
        "live_trading_enabled": False,
        "broker_submission": False,
    }
    return {
        "status": status_summary,
        "reason": "STRATEGY_LAB_WORKER_WARMING",
        "paper_only": True,
        "live_trading_enabled": False,
        "broker_submission": False,
    }


live_analytics_boundary = IsolatedExecutionBoundary(
    name="citadel-live-analytics",
    processor=_live_analytics_child_processor,
    snapshotter=_live_analytics_child_snapshot,
    on_start=_live_analytics_child_start,
    on_snapshot=_apply_live_analytics_snapshot,
    input_capacity=512,
    publish_interval_seconds=1.0,
)
strategy_lab_boundary = IsolatedExecutionBoundary(
    name="citadel-strategy-lab-research",
    processor=_strategy_child_processor,
    snapshotter=_strategy_child_snapshot,
    on_start=_strategy_child_start,
    on_stop=_strategy_child_stop,
    on_snapshot=_apply_strategy_snapshot,
    input_capacity=128,
    publish_interval_seconds=3.0,
    context_name="spawn",
    coalesce_input=True,
    # Finalized-candle persistence produced an observed 8.058s maximum gap;
    # this health bound remains below two such cycles and does not retain stale
    # market values in the prepared strategy snapshot.
    max_stale_seconds=10.0,
)


v2_integration = V2DashboardIntegration(
    process_worker=projection_process_worker,
    turbo_mode=ORACLE_TURBO_MODE,
    snapshot=dashboard.snapshot,
    kronos_alpha=kronos_alpha_service.status,
    chronos2=chronos_2_service.status,
    oracle=lambda symbol: oracle_service.assess(symbol).to_dict(),
    athena=lambda: athena_service.assess().to_dict(),
    hermes=lambda: hermes_service.assessment().to_dict(),
    argus=cached_argus_projection,
    order_flow=lambda: {
        **publish_order_flow(
            order_flow_service.latest_projection,
            order_flow_research.latest,
        ),
        "transport": market_data_gateway.health(),
    },
    futures_chart=lambda: oracle_dev_service.futures_vwap_projection("5m"),
    risk_status=control_status.risk_summary,
    kill_switch=control_status.kill_switch_summary,
    paper_status=control_status.paper_summary,
    personal_oracle=personal_oracle_service.summary,
    aegis_prepared=prepared_aegis_projection,
    readiness=readiness_service.assess,
    next_session_plan=readiness_service.next_session_plan,
    order_ledger=order_fill_ledger.status,
    paper_trading=paper_trading_orchestrator.dashboard,
    development=lambda: _strategy_cached("development"),
    strategy_lab=lambda: _strategy_cached("dashboard"),
    comparison=lambda: _strategy_cached("comparison"),
    strategies_command=lambda: _strategy_cached("strategies_command"),
    operations=lambda: _strategy_cached("operations"),
)


def _oracle_compatibility_dashboard():
    """Warm legacy consumers read the current prepared publication on demand."""

    fast_lane = globals().get("oracle_fast_lane")
    if fast_lane is not None:
        try:
            return fast_lane.compatibility_dashboard()
        except RuntimeError:
            # Startup/tests may ask before the first prepared publication.  A
            # pre-existing legacy cache remains a bounded compatibility
            # fallback; no refresh or provider work is triggered here.
            pass
    return v2_integration.cached_dashboard()


oracle_analysis_service = OracleAnalysisService(
    Path(
        _os.environ.get(
            "CITADEL_STATE_ROOT",
            DEFAULT_STATE_ROOT,
        )
    )
    / "oracle_analysis",
    context_provider=oracle_context_service.latest_snapshot,
    dashboard_provider=_oracle_compatibility_dashboard,
    feature_provider=canonical_feature_service.get_latest_snapshot,
    visual_claim_provider=oracle_visual_store.claim,
)
oracle_knowledge_service = KnowledgeRetrievalService()
oracle_phase4_evidence_service = Phase4EvidenceService(
    oracle_analysis_service, personal_oracle_service, knowledge=oracle_knowledge_service,
)


oracle_phase5_root = Path(
    _os.environ.get("CITADEL_STATE_ROOT", DEFAULT_STATE_ROOT)
) / "oracle_phase5"


def _phase5_validate_source_lineage(value):
    try:
        decision = oracle_analysis_service.decision(str(value["source_decision_id"]))
        analysis = oracle_analysis_service.analysis(str(value["source_analysis_id"]))
    except AnalysisNotFoundError as error:
        raise OracleConditionConflict("SOURCE_DECISION_OR_ANALYSIS_UNAVAILABLE") from error
    manifest = analysis.get("manifest") or {}
    if decision.content_hash != str(value["source_decision_hash"]):
        raise OracleConditionConflict("SOURCE_DECISION_HASH_CONFLICT")
    if manifest.get("snapshot_hash") != str(value["source_analysis_hash"]):
        raise OracleConditionConflict("SOURCE_ANALYSIS_HASH_CONFLICT")
    if decision.snapshot_id != str(value["source_analysis_id"]):
        raise OracleConditionConflict("SOURCE_DECISION_ANALYSIS_IDENTITY_CONFLICT")
    if decision.selected_contract_id != str(value["selected_option_id"]):
        raise OracleConditionConflict("SOURCE_DECISION_CONTRACT_IDENTITY_CONFLICT")


oracle_condition_service = OracleConditionService(
    oracle_phase5_root / "conditions", source_validator=_phase5_validate_source_lineage,
)
oracle_phase5_revalidation = Phase5RevalidationService(oracle_analysis_service)
oracle_phase5_risk = RiskAuthorizationService(
    config_provider=control_status._load_settings,
    store=control_status.risk_store,
    paper_state=dashboard.execution.paper_state,
    audit_logger=control_status.audit_logger,
)
oracle_phase5_paper = Phase5PaperExecutionAdapter(
    oracle_phase5_root / "paper",
    ledger=order_fill_ledger,
    paper_state=dashboard.execution.paper_state,
)


def _phase5_cached_market_view(contract_id: str):
    """Build deterministic current truth from cached authorities; never refresh providers."""
    context = oracle_context_service.latest_snapshot()
    dashboard_value = _oracle_compatibility_dashboard()
    if context is None or not isinstance(dashboard_value, _Mapping):
        return None
    snapshot = oracle_analysis_service.snapshot_assembler.assemble(
        context=context, dashboard=dashboard_value,
        canonical_features=canonical_feature_service.get_latest_snapshot(),
        correlation_id=f"phase5-cached-{contract_id}",
    )
    underlying = oracle_analysis_service.analyst.assess_underlying(snapshot)
    options = oracle_analysis_service.analyst.assess_option_capture(snapshot, underlying)
    quote = next((row for row in snapshot.candidate_contracts if row.contract_id == str(contract_id)), None)
    if quote is None:
        return None

    def matching_contract(value):
        if isinstance(value, _Mapping):
            if str(value.get("security_id") or value.get("contract_id") or "") == str(contract_id):
                return value
            for child in value.values():
                found = matching_contract(child)
                if found is not None:
                    return found
        elif isinstance(value, (list, tuple)):
            for child in value:
                found = matching_contract(child)
                if found is not None:
                    return found
        return None

    raw = matching_contract(dashboard_value) or {}
    lot_size = raw.get("lot_size") or raw.get("lotSize")
    return {"snapshot": snapshot, "underlying": underlying, "options": options, "quote": quote,
            "raw": raw, "lot_size": int(lot_size) if lot_size else None}


def _phase5_quote_provider(contract_id: str, view=None):
    view = view or _phase5_cached_market_view(contract_id)
    if view is None:
        return None
    quote, raw = view["quote"], view["raw"]
    return {
        "contract_id": quote.contract_id, "bid": quote.bid, "ask": quote.ask,
        "bid_depth": quote.bid_depth, "ask_depth": quote.ask_depth,
        "timestamp": quote.source_timestamp, "lot_size": view["lot_size"],
        "quantity": view["lot_size"], "expiry": quote.expiry, "strike": quote.strike,
        "option_type": quote.option_type,
        "exchange_segment": str(raw.get("exchange_segment") or raw.get("exchangeSegment") or "NSE_FNO"),
        "iv": quote.iv, "delta": quote.delta, "gamma": quote.gamma,
        "theta": quote.theta, "vega": quote.vega,
    }


def _phase5_condition_event(condition):
    lane = oracle_context_service.latest_lane(condition.timeframe)
    view = _phase5_cached_market_view(condition.selected_option_id)
    if lane is None or lane.candle is None or not lane.evidence_eligible or view is None:
        return None
    quote = _phase5_quote_provider(condition.selected_option_id, view)
    if quote is None:
        return None
    option_confirmed = (
        view["options"].selected_contract_id == condition.selected_option_id
        and view["options"].option_state == "ELIGIBLE"
    )
    candle = lane.candle
    return {
        "candle_id": candle.candle_id, "symbol": candle.symbol, "timeframe": candle.timeframe,
        "closed": True, "open": candle.open, "high": candle.high, "low": candle.low,
        "close": candle.close, "volume": candle.volume,
        "candle_closed_at": candle.bar_end, "timestamp": candle.bar_end,
        "quote_timestamp": quote["timestamp"],
        "option_quote": {**quote, "ose_confirmed": option_confirmed},
        "context": {"direction": view["underlying"].directional_posture},
        "source_hashes": {"candle": candle.content_hash, "context_lane": lane.content_hash,
                          "market_snapshot": view["snapshot"].content_hash,
                          "option_quote": view["quote"].content_hash},
    }


def _phase5_guardian_inputs(_status):
    rows = []
    risk_projection = control_status.risk_store.projection()
    for protection in oracle_phase5_paper.active_protections():
        try:
            condition = oracle_condition_service.store.definition(protection.condition_id)
        except OracleConditionError:
            rows.append({"protection": protection, "inputs": {
                "event_id": f"missing-condition:{protection.protection_id}",
                "paper_route_healthy": False, "kill_switch_active": risk_projection.active,
                "quote_fresh": False, "bid": None,
            }})
            continue
        view = _phase5_cached_market_view(condition.selected_option_id)
        quote = _phase5_quote_provider(condition.selected_option_id, view) if view else None
        if view is None or quote is None or quote.get("bid") is None:
            rows.append({"protection": protection, "inputs": {
                "event_id": f"quote-unavailable:{protection.protection_id}",
                "paper_route_healthy": order_fill_ledger.integrity().get("status") == "HEALTHY",
                "kill_switch_active": risk_projection.active, "quote_fresh": False, "bid": None,
            }})
            continue
        try:
            quote_time = datetime.fromisoformat(str(quote["timestamp"]).replace("Z", "+00:00"))
            quote_fresh = 0 <= (datetime.now(timezone.utc) - quote_time.astimezone(timezone.utc)).total_seconds() <= 10
        except (TypeError, ValueError):
            quote_fresh = False
        source_states = view["snapshot"].source_states
        authorities_fresh = all(source_states.get(name) == "FRESH" for name in ("context", "argus", "vob", "ose"))
        option_confirmed = view["options"].selected_contract_id == condition.selected_option_id and view["options"].option_state == "ELIGIBLE"
        direction_reversed = view["underlying"].directional_posture != condition.predicate_ast.context.required_direction
        rows.append({"protection": protection, "inputs": {
            "event_id": f"{quote['timestamp']}:{view['quote'].content_hash}",
            "paper_route_healthy": order_fill_ledger.integrity().get("status") == "HEALTHY",
            "kill_switch_active": risk_projection.active, "quote_fresh": quote_fresh,
            "bid": quote["bid"], "premium_confirmed": option_confirmed,
            "structural_invalidated": direction_reversed,
            "authority_material_reversal": authorities_fresh and direction_reversed,
        }})
    return rows


def _phase5_guardian_decision(protection, result):
    try:
        projection = oracle_condition_service.store.projection(protection.condition_id)
        action = str(result.get("action"))
        event_hash = str(result.get("event_hash"))
        if action == "EXIT" and projection.state.value in {"MANAGING", "RECONCILIATION_REQUIRED"}:
            oracle_condition_service.transition(protection.condition_id, ConditionState.EXITED,
                expected_prior_version=projection.version,
                idempotency_key=f"guardian-exit:{event_hash}", actor_id="INDEPENDENT_GUARDIAN",
                reason_code=str(result.get("reason")),
                details={"position_id": protection.position_id, "guardian_action": action})
        elif action in {"FAILED_SAFE", "RECONCILIATION_REQUIRED"} and projection.state.value == "MANAGING":
            target = ConditionState(action)
            oracle_condition_service.transition(protection.condition_id, target,
                expected_prior_version=projection.version, idempotency_key=f"guardian-state:{event_hash}",
                actor_id="INDEPENDENT_GUARDIAN", reason_code=str(result.get("reason")),
                details={"position_id": protection.position_id, "guardian_action": action})
        else:
            oracle_condition_service.store.stream(protection.condition_id).append(
                "GUARDIAN_PROJECTION", {"condition_id": protection.condition_id,
                 "position_id": protection.position_id, "guardian_action": action,
                 "reason_code": str(result.get("reason")), "guardian_event_hash": event_hash},
                idempotency_key=f"guardian-projection:{event_hash}")
    except Exception:
        operations_logger.record_failure()


oracle_phase5_guardian = IndependentPaperGuardian(
    oracle_phase5_root / "guardian", execution=oracle_phase5_paper,
    input_provider=_phase5_guardian_inputs, on_decision=_phase5_guardian_decision,
)
oracle_phase5_workflow = Phase5OracleWorkflow(
    conditions=oracle_condition_service, revalidation=oracle_phase5_revalidation,
    risk=oracle_phase5_risk, paper=oracle_phase5_paper, guardian=oracle_phase5_guardian,
    quote_provider=_phase5_quote_provider,
)
oracle_condition_monitor = ConditionMonitor(
    oracle_condition_service, context_provider=_phase5_condition_event,
    on_trigger=oracle_phase5_workflow.handle_trigger,
)

phase6a_telemetry = PerformanceTelemetry()
oracle_exact_option_analysis = ExactOptionPremiumAnalysisService(
    options_structure_engine.contract_technicals, telemetry=phase6a_telemetry,
)



def _phase6a_control_projection():
    """Read-only Phase-5 projection; never advances any lifecycle."""
    definitions = oracle_condition_service.store.definitions
    latest = None
    if definitions.exists():
        for path in sorted(definitions.glob("*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True):
            try:
                latest = oracle_condition_service.store.projection(path.stem).to_dict()
                break
            except Exception:
                continue
    latest = latest or {}
    order = None
    order_id = latest.get("order_id")
    if order_id:
        try:
            order = oracle_phase5_paper.order(str(order_id))
        except Exception:
            order = {"order_id": order_id, "state": "UNAVAILABLE"}
    protection = None
    protection_id = latest.get("protection_id")
    if protection_id:
        try:
            protection = oracle_phase5_paper.protection(str(protection_id)).to_dict()
        except Exception:
            protection = {"protection_id": protection_id, "status": "UNAVAILABLE"}
    return {
        "condition_id": latest.get("condition_id"), "condition_state": latest.get("state"),
        "condition_version": latest.get("version"), "trigger_id": latest.get("trigger_id"),
        "revalidation_id": latest.get("revalidation_id"), "authorization_id": latest.get("authorization_id"),
        "order": order, "paper_order_state": (order or {}).get("state") if isinstance(order, dict) else None,
        "position_id": latest.get("position_id"), "protection": protection,
        "guardian_action": latest.get("guardian_action"), "guardian_health": oracle_phase5_guardian.health(),
        "latest_explanation": latest.get("explanation"), "latest_event_hash": latest.get("latest_event_hash"),
        "paper_only": True, "live_trading_enabled": False, "broker_submission": False,
    }


def _phase6a_option_security_id(option):
    """Resolve exact option identity only through a fresh local Dhan master."""
    master = option_chart_feed.instrument_master
    started = _perf_counter()
    error = False
    try:
        cache = _json.loads(master.cache_path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(str(cache["fetched_at"]))
        if master.clock() - fetched_at >= timedelta(hours=24):
            return None
        resolved = master.resolve(
            security_id="", expiry=option.expiry, strike=option.strike,
            option_type=option.option_side, underlying=option.underlying,
        )
        return str(resolved["security_id"])
    except Exception:
        error = True
        return None
    finally:
        phase6a_telemetry.record(
            "dhan_security_mapping", (_perf_counter() - started) * 1000,
            error=error,
        )


def _phase6a_authority_retrievals():
    """Read exact-leg ARGUS truth; Phase-3 retrieves bundled OSE/VOB once."""
    started = _perf_counter()
    argus_projection = cached_argus_projection("NIFTY")
    phase6a_telemetry.record("argus_retrieval", (_perf_counter() - started) * 1000)
    return argus_projection


def _phase6a_argus_leg(projection, security_id):
    data = projection.get("data") if isinstance(projection, _Mapping) else None
    for row in (data.get("atm_window") or []) if isinstance(data, _Mapping) else []:
        if not isinstance(row, _Mapping):
            continue
        for side in ("ce", "pe"):
            leg = row.get(side)
            if isinstance(leg, _Mapping) and str(leg.get("security_id")) == str(security_id):
                return dict(leg)
    return None


def _phase6a_analysis(chart_state):
    """Fresh advisory Phase-3/4 analysis; chart metadata cannot authorize it."""
    underlying = chart_state.instrument.underlying
    if underlying != "NIFTY":
        raise ValueError(f"CANONICAL_ORACLE_ANALYSIS_UNSUPPORTED:{underlying}")
    argus_projection = _phase6a_authority_retrievals()
    exact = chart_state.option
    exact_technicals = None
    if exact and exact.security_id:
        leg = _phase6a_argus_leg(argus_projection, exact.security_id) or {}
        underlying_record = (argus_projection.get("data") or {}).get("underlying") or {}
        observed_at = underlying_record.get("fetched_at") or chart_state.source_timestamp
        try:
            exact_technicals = options_structure_engine.contract_technicals({
                "security_id": exact.security_id, "option_type": exact.option_side,
                "side": exact.option_side, "expiry": exact.expiry, "strike": exact.strike,
                "trading_symbol": exact.trading_symbol, "premium": leg.get("ltp"),
            }, observed_at)
        except Exception as error:
            exact_technicals = {
                "status": "UNAVAILABLE",
                "reason": f"EXACT_PREMIUM_AUTHORITY_UNAVAILABLE:{type(error).__name__}",
            }
    result = oracle_analysis_service.create(
        symbol="NIFTY", correlation_id=chart_state.correlation_id,
        telemetry=phase6a_telemetry.record,
    )
    exact_started = _perf_counter()
    exact_analysis = (oracle_exact_option_analysis.analyze(
        chart_state, result, technical_override=exact_technicals,
    ) if exact else None)
    phase6a_telemetry.record("exact_option_composition", (_perf_counter() - exact_started) * 1000)
    enrichment = oracle_phase4_evidence_service.enrich_result(
        result, persist=True, telemetry=phase6a_telemetry.record,
    )
    decision = result.decision.to_dict()
    current_contract = exact.trading_symbol if exact else None
    selected = decision.get("contract_label")
    exact_verdict = (exact_analysis or {}).get("verdict")
    current_accepted = exact_verdict == "KEEP_CURRENT_CONTRACT"
    current_rejected = exact_verdict == "REJECT_CURRENT_CONTRACT"
    why = decision.get("why") or {}
    risk = decision.get("risk") or {}
    decision_projection = {
        "decision_id": decision.get("decision_id"), "content_hash": decision.get("content_hash"),
        "decision_timestamp": decision.get("generated_at"),
        "source_hashes": {**dict(decision.get("source_hashes") or {}),
            **{f"authority:{key}": value for key, value in dict(result.snapshot.source_hashes).items()},
            **{f"assessment:{key}": value for key, value in dict(decision.get("assessment_hashes") or {}).items()}},
        "action": decision.get("action"), "exact_contract": selected,
        "displayed_option": current_contract, "current_contract_accepted": current_accepted,
        "current_security_id": exact.security_id if exact else None,
        "current_contract_rejected": current_rejected,
        "current_contract_reason": exact_verdict or "UNDERLYING_CHART_OPTION_SELECTED_BY_PHASE3",
        "better_option_found": bool((exact_analysis or {}).get("alternative_contract")),
        "exact_option": exact_analysis,
        "setup_quality": decision.get("setup_quality"), "visual_certainty": decision.get("visual_certainty"),
        "data_completeness": decision.get("data_completeness"), "execution_quality": decision.get("execution_quality"),
        "evidence_agreement": decision.get("evidence_agreement"), "calibration_status": decision.get("calibration_status"),
        "historical_probability": decision.get("historical_probability"), "trigger": decision.get("trigger_summary"),
        "entry_band": decision.get("entry_band"), "structural_invalidation": decision.get("structural_invalidation_id"),
        "premium_stop": decision.get("premium_hard_stop_candidate"), "targets": decision.get("target_premiums") or [],
        "target_ids": decision.get("target_ids") or [], "costs": decision.get("estimated_cost"),
        "resulting_rr": decision.get("resulting_rr") or [],
        "why": why.get("summary") if isinstance(why, dict) else str(why),
        "why_proof": enrichment.proof_projection,
        "risk_conflict": risk.get("summary") if isinstance(risk, dict) else str(risk),
        "freshness": decision.get("freshness_state"), "missing_evidence": decision.get("missing_evidence") or [],
        "reason_codes": decision.get("reason_codes") or [], "execution_authority": False,
    }
    proof = enrichment.proof_projection
    premium_candles = dict((exact_analysis or {}).get("premium_candles") or {})
    completed_timestamp = premium_candles.get("evaluated_through") or result.snapshot.source_timestamps.get("context")
    decision_projection.update({
        "candle_timestamp": completed_timestamp,
        "completed_candle": bool(completed_timestamp) and (
            bool(premium_candles.get("forming_candle_excluded")) if exact else True),
        "market_state": result.snapshot.market_state,
        "setup_family": list(result.underlying.permitted_thesis_types)[0]
            if result.underlying.permitted_thesis_types else "UNAVAILABLE",
        "market_thesis": {"direction": result.underlying.directional_posture,
            "location_quality": result.underlying.location_quality,
            "permitted_thesis_types": list(result.underlying.permitted_thesis_types),
            "setup_quality": result.underlying.setup_quality},
        "structural_stop": ({"invalidation_id": result.underlying.invalidations[0].invalidation_id,
            "type": result.underlying.invalidations[0].invalidation_type,
            "level": result.underlying.invalidations[0].level,
            "mapping_status": result.underlying.invalidations[0].mapping_status}
            if result.underlying.invalidations else None),
        "natural_targets": [{"target_id": item.target_id, "type": item.target_type,
            "level": item.level, "authority": item.authority} for item in result.underlying.natural_targets],
        "provider_lineage": {name.upper(): {"state": result.snapshot.source_states.get(name),
            "freshness": result.snapshot.source_states.get(name), "source_id": result.snapshot.source_ids.get(name),
            "source_hash": result.snapshot.source_hashes.get(name),
            "timestamp": result.snapshot.source_timestamps.get(name)} for name in ("argus", "vob", "ose")},
        "evidence": {"supporting": list(proof.get("current_evidence", {}).get("supporting_facts") or []),
            "conflicting": list(proof.get("current_evidence", {}).get("conflicts") or []),
            "missing": list(proof.get("current_evidence", {}).get("missing_inputs") or [])},
        "knowledge_card_ids": [str(item.get("card_id")) for item in proof.get("principle") or [] if item.get("card_id")],
    })
    principles = []
    for item in proof.get("principle") or []:
        card = oracle_knowledge_service.registry.cards.get(str(item.get("card_id")))
        status = getattr(getattr(card, "validation_status", None), "value", None)
        if status == "FUTURE_DATA_DEPENDENT":
            continue
        principles.append(item)
    knowledge_projection = {
        "references": principles[:5], "conflicts": (proof.get("principle_conflicts") or [])[:2],
        "maximum_primary_cards": 5, "maximum_counter_principles": 2,
        "research_only_excluded": True, "future_data_dependent_excluded_when_unavailable": True,
        "execution_influence": "ZERO", "status": "AVAILABLE",
    }
    second_brain = personal_oracle_service.second_brain_projection(
        decision_projection, knowledge=knowledge_projection,
        context={"symbol": underlying, "setup": decision.get("setup_version")},
    )
    return {"decision": decision_projection, "knowledge": knowledge_projection,
            "second_brain": second_brain}


def _phase6a_dependency_state():
    """Hashes only canonical completed evidence; chart polling causes no rebuild."""
    context = oracle_context_service.latest_snapshot()
    features = canonical_feature_service.get_latest_snapshot()
    feature_hash = features.get("content_hash") if isinstance(features, _Mapping) else getattr(features, "content_hash", None)
    feature_as_of = features.get("as_of") if isinstance(features, _Mapping) else getattr(features, "as_of", None)
    return {
        "context_hash": getattr(context, "content_hash", None),
        "context_as_of": getattr(context, "as_of", None),
        "feature_hash": feature_hash,
        "feature_as_of": feature_as_of,
    }


def _phase6a_fast_path(decision: dict, phase5: dict) -> dict:
    if not isinstance(decision, dict) or not isinstance(phase5, dict):
        return decision
    res = _deepcopy(decision)
    gateway_quotes = phase5.get("gateway_quotes")
    if not isinstance(gateway_quotes, dict):
        return res
    sec_id = res.get("current_security_id") or (
        res.get("exact_option", {}).get("security_id") if isinstance(res.get("exact_option"), dict) else None
    )
    if not sec_id:
        return res
    quote = gateway_quotes.get(str(sec_id))
    if not isinstance(quote, dict):
        return res
    decision_epoch = res.get("identity_epoch")
    quote_epoch = quote.get("identity_epoch")
    if decision_epoch is not None and quote_epoch is not None and decision_epoch != quote_epoch:
        return res
    ltp = quote.get("ltp")
    if ltp is not None and isinstance(res.get("exact_option"), dict):
        res["exact_option"]["premium"] = ltp
    return res


oracle_market_day = MarketDayReadinessService(
    oracle_phase5_root.parent / "oracle_market_day",
    minimum_rr=oracle_analysis_service.policy.minimum_rr,
)
_dhan_auth_readiness = {"status": "NOT_CHECKED", "proof": "STARTUP_READ_ONLY_PROBE_NOT_RUN"}
oracle_tradingview_sync = TradingViewAutoSyncService(
    oracle_phase5_root.parent / "oracle_phase6a" / "tradingview_sync",
    analysis_provider=_phase6a_analysis, phase5_provider=_phase6a_control_projection,
    decision_observer=oracle_market_day.observe,
    personal_oracle_provider=personal_oracle_service.summary,
    second_brain_provider=lambda decision, knowledge, context: personal_oracle_service.second_brain_projection(
        decision, knowledge=knowledge, context=context,
    ),
    dependency_state_provider=_phase6a_dependency_state,
    option_identity_resolver=_phase6a_option_security_id,
    fast_path_provider=_phase6a_fast_path,
    telemetry=phase6a_telemetry,
)
v2_integration.providers["oracle_live_workspace"] = oracle_tradingview_sync.projection
openalgo_analyzer_client = OpenAlgoAnalyzerClient(
    _os.environ.get("OPENALGO_BASE_URL", "http://127.0.0.1:5001"),
    _os.environ.get("OPENALGO_API_KEY", ""),
)
oracle_paper_autopilot = OraclePaperAutopilot(
    Path(
        _os.environ.get(
            "CITADEL_STATE_ROOT",
            DEFAULT_STATE_ROOT,
        )
    )
    / "oracle_missions",
    missions=oracle_mission_service,
    openalgo=openalgo_analyzer_client,
    paper_state=dashboard.execution.paper_state,
    snapshot_provider=_oracle_compatibility_dashboard,
)

# --- ORACLE DEVELOPMENT SEGMENT INITIALIZATION ---
from src.oracle_development import OracleDevService
from src.oracle_development.oracle_dev_service import analyze_price_action_batch
from src.vob import NiftyVOBEngine

oracle_dev_vob_engine = NiftyVOBEngine(
    persistence_path=Path(_os.environ.get("CITADEL_STATE_ROOT", DEFAULT_STATE_ROOT)) / "oracle_dev" / "vob_state.json"
)
oracle_dev_service = OracleDevService(
    dhan=argus.engine.dhan,
    argus_api=argus,
    options_structure_engine=options_structure_engine,
    vob_engine=oracle_dev_vob_engine,
    state_root=Path(_os.environ.get("CITADEL_STATE_ROOT", DEFAULT_STATE_ROOT)) / "oracle_dev"
)


def _apply_price_action_snapshot(snapshot):
    oracle_dev_service.apply_price_action_snapshot(snapshot)


# R2.1I: the accepted profiler proved the unchanged analyzer is CPU/GIL-heavy.
# One owner-watched process consumes completed-candle revisions; the FastAPI
# parent only receives and atomically publishes its prepared result.
price_action_boundary = IsolatedExecutionBoundary(
    name="oracle-price-action-worker",
    processor=analyze_price_action_batch,
    on_snapshot=_apply_price_action_snapshot,
    input_capacity=16,
    publish_interval_seconds=0.05,
)
oracle_dev_service.configure_price_action_producer(
    lambda payload: price_action_boundary.submit(
        "chart_price_action", payload, timeout=0.05
    ),
    price_action_boundary.status,
)
futures_forecast_orchestrator = FuturesForecastOrchestrator()
oracle_dev_service.subscribe_futures_chart(futures_forecast_orchestrator.ingest)
_flow_pulse_reference_key = None


def _register_flow_pulse_reference_levels(chart):
    """Hand cached completed Futures session levels to the packet kernel."""
    global _flow_pulse_reference_key
    candles = chart.get("candles") if isinstance(chart, dict) else None
    if not isinstance(candles, list):
        return
    ist = timezone(timedelta(hours=5, minutes=30))
    sessions = {}
    for candle in candles:
        if not isinstance(candle, dict) or candle.get("is_forming") is True:
            continue
        try:
            stamp = datetime.fromtimestamp(float(candle["time"]), tz=timezone.utc).astimezone(ist)
            row = sessions.setdefault(stamp.date().isoformat(), [])
            row.append(candle)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    today = datetime.now(ist).date().isoformat()
    prior_dates = sorted(day for day in sessions if day < today)
    if not prior_dates:
        return
    day = prior_dates[-1]
    rows = sorted(sessions[day], key=lambda item: float(item["time"]))
    values = (
        day,
        max(float(item["high"]) for item in rows),
        min(float(item["low"]) for item in rows),
        float(rows[-1]["close"]),
    )
    if values == _flow_pulse_reference_key:
        return
    _flow_pulse_reference_key = values
    order_flow_service.register_futures_reference_levels(
        previous_day_high=values[1],
        previous_day_low=values[2],
        previous_close=values[3],
        source_timestamp=day,
    )


def _recover_flow_pulse_opening_range():
    """Recover today's exact 30-second OR once, outside the live packet path."""
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date().isoformat()
    path = order_flow_recorder.root / "raw_full_packets" / f"{today}.jsonl"
    if not path.exists():
        return False
    start = datetime.fromisoformat(f"{today}T09:15:00+05:30")
    end = start + timedelta(seconds=30)
    prices = []
    last_timestamp = None
    with path.open() as handle:
        for line in handle:
            try:
                row = _json.loads(line)
                payload = row.get("payload") if isinstance(row, dict) else None
                if not isinstance(payload, dict) or payload.get("instrument_role") != "NIFTY_FUTURE":
                    continue
                timestamp = datetime.fromisoformat(str(payload["receive_time_ist"]))
                if timestamp >= end:
                    break
                if start <= timestamp < end:
                    prices.append(float(payload["ltp"]))
                    last_timestamp = timestamp.isoformat()
            except (KeyError, TypeError, ValueError, _json.JSONDecodeError):
                continue
    if not prices or last_timestamp is None:
        return False
    order_flow_service.register_futures_opening_range(
        high=max(prices), low=min(prices), source_timestamp=last_timestamp,
    )
    return True


def _recover_flow_pulse_session_context():
    """Restore Flow Pulse to the journal's frozen startup byte boundary."""
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date().isoformat()
    path = order_flow_recorder.root / "raw_full_packets" / f"{today}.jsonl"
    # The worker has already entered recovery before this function runs.
    # Always cross the worker control boundary, including on a cold session
    # where the recorder has not created today's journal yet.  The service's
    # missing-journal path completes recovery and attaches the live tail; an
    # early parent return would otherwise leave every genuine packet buffered
    # forever while transport counters misleadingly continue to advance.
    cutoff_bytes = path.stat().st_size if path.exists() else None
    checkpoint_path = (
        order_flow_recorder.root / "recovery_checkpoints" / f"flow_pulse_{today}.pickle"
    )
    recovery = order_flow_service.restore_flow_pulse_journal(
        path,
        checkpoint_path=checkpoint_path,
        cutoff_bytes=cutoff_bytes,
        checkpoint_identity={
            "git_head": oracle_runtime.provenance.git_head,
            "git_branch": oracle_runtime.provenance.git_branch,
            "code_fingerprint": oracle_runtime.provenance.code_fingerprint,
        },
    )
    oracle_runtime.update_recovery(recovery)
    # Recovery intentionally bypasses live listeners. Refresh the existing
    # cache-only Fast Lane provider once so REST and SSE observe the same
    # atomically restored projection without waiting for a future packet.
    oracle_fast_lane.refresh_provider("order_flow")
    return recovery


def _oracle_live_market_tick_fanout(tick):
    """Lossless canonical Flow handoff; no display work belongs on this lane."""

    return order_flow_service.ingest_tick(tick)


def _oracle_latest_futures_display_tick(tick):
    """One-slot display lane: forming chart state may supersede obsolete ticks."""

    oracle_dev_service.ingest_live_futures_tick(tick)


market_data_gateway.on_tick = _oracle_live_market_tick_fanout
market_data_gateway.on_latest_futures_tick = _oracle_latest_futures_display_tick


def _futures_chart_with_forecast():
    """One immutable chart projection plus its matching advisory forecast."""
    chart = oracle_dev_service.futures_vwap_projection("5m")
    _register_flow_pulse_reference_levels(chart)
    forecast = futures_forecast_orchestrator.projection_for(chart)
    chart["forecast"] = forecast
    chart["decision_hud"] = order_flow_service.latest_decision_hud()
    timeframes = chart.get("timeframes")
    if isinstance(timeframes, dict) and isinstance(timeframes.get("5m"), dict):
        timeframes["5m"]["forecast"] = _deepcopy(forecast)
    return chart


# Existing compatibility feeds become passive views of the one Futures
# orchestrator. No old scheduler is allowed to infer after this assignment.
v2_integration.providers["futures_chart"] = _futures_chart_with_forecast
v2_integration.providers["kronos_alpha"] = futures_forecast_orchestrator.kronos_status
v2_integration.providers["chronos2"] = futures_forecast_orchestrator.chronos_status


_eye_oracle_projection_service = EyeOracleProjectionService(
    runtime_state=EyeRuntimeState.get_instance()
)


def _oracle_fast_base_projection():
    """Four producer-owned base feeds; no second full-dashboard reconstruction."""

    oracle_dict = oracle_service.assess("NIFTY").to_dict()
    values = {
        "oracle": oracle_dict,
        "strategy_lab": _strategy_cached("dashboard"),
        "strategies": _strategy_cached("strategies_command"),
        "eye_oracle_projection": _eye_oracle_projection_service.get_projection(
            symbol="NIFTY", timeframe="5m"
        ).to_dict(),
    }

    # Non-blocking feed delivery into Sol Market Brain Service
    try:
        from src.oracle_sol.production_projection import project_canonical_oracle_to_sol_feeds
        from src.oracle_sol.service import SolMarketBrainService
        sol_feeds = project_canonical_oracle_to_sol_feeds(
            argus_projection=cached_argus_projection("NIFTY"),
            order_flow_projection=order_flow_service.latest_projection(),
            futures_chart_projection=_futures_chart_with_forecast(),
            option_buyer_projection=_live_analytics_cached("option_buyer_intelligence"),
            options_structure_projection=_live_analytics_cached("options_structure"),
            transport_health=market_data_gateway.health(),
            market_info=market_info_service.latest_snapshot(),
        )
        SolMarketBrainService.get_instance().ingest_feeds(sol_feeds)
    except Exception as exc:
        # Do not let a producer-contract failure leave an old Gemini thesis
        # looking current.  This path records no market values and makes no
        # provider call; it only exposes the fail-closed operational truth.
        try:
            from src.oracle_sol.service import SolMarketBrainService
            SolMarketBrainService.get_instance().report_projection_failure(str(exc))
        except Exception:
            pass

    return {
        "feeds": {
            name: OracleFastLane._feed(name, value, None)
            for name, value in values.items()
        }
    }


def _oracle_fast_order_flow():
    projection = {
        **publish_order_flow(
            order_flow_service.latest_projection,
            order_flow_research.latest,
        ),
        "transport": market_data_gateway.health(),
    }
    oracle_runtime.timing.mark("ORDER_FLOW_PUBLICATION")
    oracle_runtime.timing.mark("FLOW_PULSE_PUBLICATION")
    return projection


oracle_fast_lane = OracleFastLane(
    base_provider=_oracle_fast_base_projection,
    providers={
        "argus": lambda: cached_argus_projection("NIFTY"),
        # OSE is a canonical, cache-only projection.  Publishing it directly
        # prevents its Live Option Flow and independently-calculated
        # Buyers/Writers snapshot from inheriting Strategy Lab's dashboard
        # refresh cadence.
        "options_structure": lambda: _live_analytics_cached(
            "options_structure",
            {"status": "UNAVAILABLE", "reason": "LIVE_ANALYTICS_WORKER_WARMING"},
        ),
        "order_flow": _oracle_fast_order_flow,
        "fusion_shadow": lambda: _live_analytics_cached(
            "fusion_shadow",
            {"status": "UNAVAILABLE", "reason": "LIVE_ANALYTICS_WORKER_WARMING"},
        ),
        "vob_reversal": lambda: _live_analytics_cached(
            "vob_reversal",
            {"status": "UNAVAILABLE", "reason": "LIVE_ANALYTICS_WORKER_WARMING"},
        ),
        "option_buyer_intelligence": lambda: _live_analytics_cached(
            "option_buyer_intelligence",
            {"status": "UNAVAILABLE", "reason": "LIVE_ANALYTICS_WORKER_WARMING"},
        ),
        "risk_status": control_status.risk_summary,
        "paper_status": control_status.paper_summary,
        "oracle_live_workspace": oracle_tradingview_sync.projection,
        "market_info": lambda: market_info_service.latest_snapshot(),
    },
    chart_provider=_futures_chart_with_forecast,
    # Every provider is cache-only.  Compact Flow Pulse events retain their
    # own publication path below.  A complete Fast Lane document is roughly a
    # megabyte, so assembling/serializing it at packet cadence can monopolize
    # CPython's GIL and age the lossless Flow lane.  One bounded complete
    # latest-state revision per second is sufficient for REST resync; compact
    # Flow events remain independently coalesced below.
    interval_seconds=1.0,
    provider_intervals={
        "argus": 1.0,
        "options_structure": 1.0,
        "order_flow": 1.0,
        "fusion_shadow": 1.0,
        "oracle_live_workspace": 1.0,
        "risk_status": 1.0,
        "paper_status": 1.0,
        "market_info": 5.0,
    },
    push_providers={"options_structure", "order_flow", "fusion_shadow", "vob_reversal"},
)


def _publish_flow_pulse_from_latest_lane(kind, payload):
    """Publish already-calculated Flow state without holding its engine lock."""

    oracle_fast_lane.publish_flow_pulse(kind, payload)
    # The Live Analytics boundary consumes current Flow state and emits a
    # bounded 2 Hz immutable snapshot. Obsolete meter revisions carry no
    # ordered event semantics, so do not repeatedly construct transport
    # telemetry and pickle a full projection faster than that consumer can
    # publish it. Material actions always cross immediately.
    if (
        kind != "FLOW_PULSE_ACTION"
        and not oracle_fast_lane.provider_push_due("live_analytics_flow", 0.5)
    ):
        return
    flow_snapshot = order_flow_service.latest_projection()
    transport = market_data_gateway.transport_snapshot()
    live_analytics_boundary.submit(
        "flow",
        {
            "flow": flow_snapshot,
            "transport": transport,
        },
        timeout=0.05,
    )
    # The callback already owns the newest canonical Flow snapshot.  At the
    # established one-second Fast Lane cadence, attach its existing research
    # presentation exactly once and push it instead of polling/copying it in a
    # second FastAPI thread.  Flow calculation and thresholds are untouched.
    if oracle_fast_lane.provider_push_due("order_flow", 1.0):
        projection = {
            **publish_order_flow(lambda: flow_snapshot, order_flow_research.latest),
            "transport": transport,
        }
        oracle_fast_lane.publish_provider_value("order_flow", projection)


flow_publication_lane = FlowPublicationLane(_publish_flow_pulse_from_latest_lane)
_unsubscribe_flow_pulse_fast_lane = order_flow_service.subscribe_flow_pulse(
    flow_publication_lane.submit
)

demo_tour_root = Path(
    _os.environ.get(
        "CITADEL_STATE_ROOT",
        DEFAULT_STATE_ROOT,
    )
) / "oracle_demo_tour"
demo_mission_service = OracleMissionService(demo_tour_root / "missions")
demo_paper_state = PaperStateService(demo_tour_root / "demo_paper_state.json")
demo_paper_autopilot = OraclePaperAutopilot(
    demo_tour_root / "execution",
    missions=demo_mission_service,
    openalgo=openalgo_analyzer_client,
    paper_state=demo_paper_state,
    snapshot_provider=_oracle_compatibility_dashboard,
)
demo_tour = DemoTourSession(
    demo_tour_root,
    missions=demo_mission_service,
    autopilot=demo_paper_autopilot,
    paper_state=demo_paper_state,
    snapshot_provider=_oracle_compatibility_dashboard,
)


@app.on_event("startup")
def start_kronos_alpha_scheduler():
    """Bind HTTP immediately; hydrate every restart-safe producer off lifespan."""

    # These two boundaries must be created before application-owned threads so
    # their inherited state graph has one deterministic owner and no duplicated
    # live transport.  FastAPI only starts cache publishers after both children.
    live_analytics_boundary.start(start_listener=False)
    strategy_lab_boundary.start(start_listener=False)
    price_action_boundary.start(start_listener=False)
    # R2.1F: the Fast Lane build/serialization process must also fork before
    # application-owned provider/scheduler threads exist.  Its listener only
    # swaps immutable encoded bytes into the FastAPI serving plane.
    oracle_fast_lane.start_publisher()
    live_analytics_boundary.start_listener()
    strategy_lab_boundary.start_listener()
    price_action_boundary.start_listener()
    # These cache publishers are intentionally safe before their providers are
    # hydrated: they publish truthful unavailable/error feeds until genuine
    # state arrives.  Returning from lifespan prevents the external health
    # supervisor from killing a valid late-session recovery in progress.
    if ORACLE_V2_PARENT_REBUILD_ENABLED:
        v2_integration.start(wait_for_initial=False)
    oracle_fast_lane.start()
    flow_publication_lane.start()
    oracle_runtime.transition(StartupState.RECOVERING)
    _Thread(
        target=_hydrate_oracle_runtime,
        name="citadel-oracle-runtime-hydration",
        daemon=True,
    ).start()


@app.on_event("startup")
async def start_event_loop_watchdog():
    """Measure the actual serving loop without touching any provider."""

    event_loop_watchdog.start()


def _hydrate_oracle_runtime():
    """Keep HTTP live throughout controlled hydration; fail visibly, never silently."""
    try:
        _hydrate_oracle_runtime_inner()
    except Exception as error:
        oracle_runtime.transition(StartupState.FAILED, reason=f"{type(error).__name__}:{error}")
    else:
        oracle_runtime.transition(StartupState.READY)


def _hydrate_oracle_runtime_inner():
    global _oracle_context_bootstrap_error, _dhan_auth_readiness
    try:
        oracle_context_service.bootstrap_from_persisted()
        _oracle_context_bootstrap_error = None
    except Exception as error:
        # Perception is advisory-only and must fail isolated from the existing app.
        _oracle_context_bootstrap_error = f"{type(error).__name__}:{error}"

    # ARGUS/OSE/options-flow are direct /oracle dependencies. Reacquire them
    # alongside the critical recovery path, before unrelated advisory backfills.
    try:
        argus.get_oi("NIFTY")
        _dhan_auth_readiness = {"status": "AVAILABLE", "proof": "READ_ONLY_OPTION_CHAIN_REQUEST_SUCCEEDED"}
    except ArgusAPIError:
        _dhan_auth_readiness = {"status": "UNAVAILABLE", "proof": "READ_ONLY_OPTION_CHAIN_REQUEST_FAILED"}
    argus.start_cache_producer(
        projection_process_worker,
        symbol="NIFTY",
        interval_seconds=3.0,
        on_snapshot=_argus_cache_fanout,
        on_stage=oracle_runtime.timing.mark,
    )

    # Order Flow is a direct /oracle dependency. Restore and connect it before
    # unrelated advisory hydrators so a late restart cannot leave Flow Pulse
    # truthfully unavailable for minutes while those producers warm up.
    oracle_runtime.transition(StartupState.CONNECTING_MARKET_DATA)
    _register_order_flow_basket(_bootstrap_order_flow_basket())
    _recover_flow_pulse_opening_range()
    order_flow_service.start()
    order_flow_service.begin_recovery()
    oracle_runtime.update_recovery({"status": "RUNNING"})
    # Restore the frozen journal before admitting a new live tail.  A cold
    # fallback replay can be CPU-heavy; starting the child first would create
    # a large in-memory delta and make the atomic handoff itself contend with
    # the newly-live session.  A trusted checkpoint makes this bounded in the
    # normal case, while this ordering keeps the exceptional full-replay path
    # truthful and prevents a startup GIL storm from defeating health paths.
    recovery = _recover_flow_pulse_session_context()
    oracle_runtime.update_recovery(recovery)
    market_data_gateway.start_background()
    # Core readiness is complete here. Forecasts, research, paper tooling and
    # the TradingView bridge are explicitly non-blocking: their warm-up must
    # not turn a restored, cache-serving Oracle into an apparent dead process.
    oracle_runtime.transition(StartupState.READY)
    _start_noncritical_oracle_services()


def _start_noncritical_oracle_services():
    from src.external_context.core import ExternalContextCore
    starters = [
        ("ORDER_FLOW_RESEARCH", order_flow_research.start),
        ("PERSONAL_ORACLE_BACKFILL", personal_oracle_service.backfill_authoritative),
        ("FUTURES_FORECAST", futures_forecast_orchestrator.start),
        ("PAPER_TRADING", paper_trading_orchestrator.start),
        ("ORACLE_DEV_CANDLES", oracle_dev_service.start_background_producer),
        ("ORACLE_GUARDIAN", oracle_phase5_guardian.start),
        ("TRADINGVIEW_SYNC", oracle_tradingview_sync.start),
        ("EXTERNAL_CONTEXT_CORE", lambda: ExternalContextCore.get_instance().start_background_polling()),
        ("UPSTOX_MARKET_INFO", market_info_service.start),
        ("LIVE_ISLAND_HUB", lambda: LiveIslandIntelligenceHub.get_instance().start()),
    ]
    for component, start in starters:
        try:
            start()
        except Exception as error:
            oracle_runtime.note_noncritical_failure(component, error)


@app.on_event("shutdown")
def stop_kronos_alpha_scheduler():
    from src.external_context.core import ExternalContextCore
    from src.oracle_sol.service import SolMarketBrainService
    try:
        from src.oracle.live_island.hub import LiveIslandIntelligenceHub
        LiveIslandIntelligenceHub.get_instance().shutdown()
    except Exception:
        pass
    try:
        ExternalContextCore.get_instance().stop_background_polling()
    except Exception:
        pass
    market_info_service.stop()
    SolMarketBrainService.shutdown_if_initialized()
    flow_publication_lane.stop()
    oracle_fast_lane.stop()
    market_data_gateway.stop_background()
    order_flow_research.stop()
    order_flow_service.stop()
    oracle_tradingview_sync.stop()
    oracle_phase5_guardian.stop()
    argus_edge_lab.stop()
    argus.stop_cache_producer()
    if ORACLE_V2_PARENT_REBUILD_ENABLED:
        v2_integration.stop()
    else:
        # V2 historically owned this shared advisory projection pool.  Parent
        # eviction must not trade CPU relief for an orphan at shutdown.
        projection_process_worker.stop()
    oracle_dev_service.stop_background_producer()
    price_action_boundary.stop()
    strategy_lab_boundary.stop()
    live_analytics_boundary.stop()
    futures_forecast_orchestrator.stop()
    paper_trading_orchestrator.stop()


@app.on_event("shutdown")
async def stop_event_loop_watchdog():
    await event_loop_watchdog.stop()


@app.get("/")
def root():
    return {"system": "CitadelOS", "status": "ONLINE"}


@app.get("/health/live")
async def health_live():
    """Cheap process liveness: no provider, recovery, or Fast Lane work."""
    return {
        **oracle_runtime.liveness(),
        "event_loop": event_loop_watchdog.snapshot(),
    }


def get_canonical_runtime_truth_snapshot() -> dict[str, Any]:
    """Authoritative, multi-dimensional Runtime Truth snapshot driving all readiness surfaces."""
    fast_lane_health = oracle_fast_lane.health()
    cached = fast_lane_health.get("provider_readiness") or {}
    argus_projection = cached.get("argus") or {"status": "UNAVAILABLE"}
    ose_projection = cached.get("options_structure") or {"status": "UNAVAILABLE"}
    vob_projection = cached.get("vob_reversal") or {"status": "UNAVAILABLE"}
    strategy_lab_projection = cached.get("strategy_lab") or {"status": "UNAVAILABLE"}
    
    analytics_status = live_analytics_boundary.status()
    persist_degraded = bool(getattr(argus_tactical_edge.store, "is_degraded", False))
    last_persist_err = getattr(argus_tactical_edge.store, "last_persistence_error", None)

    gw_health = market_data_gateway.health() if hasattr(market_data_gateway, "health") else {}
    upstox_healthy = bool(
        gw_health.get("UPSTOX_WS_CONNECTED")
        or gw_health.get("COEXISTENCE_STATE") in {"DHAN_UNAVAILABLE / UPSTOX_HEALTHY", "DUAL_SOURCE_HEALTHY"}
    )

    futures_live = bool((cached.get("futures_chart") or {}).get("status") == "AVAILABLE") or upstox_healthy
    spot_live = bool(argus_projection.get("status") in {"AVAILABLE", "CACHED"}) or upstox_healthy
    options_live = bool(ose_projection.get("status") in {"AVAILABLE", "CACHED"}) or upstox_healthy
    order_flow_live = bool((cached.get("order_flow") or {}).get("status") in {"AVAILABLE", "CACHED"}) or upstox_healthy

    canonical_runtime_truth.update_process(process_live=True)
    canonical_runtime_truth.update_market_data(
        futures_live=futures_live,
        spot_live=spot_live,
        options_live=options_live,
        order_flow_live=order_flow_live,
    )
    canonical_runtime_truth.update_analytics(
        argus_live=bool(argus_projection.get("status") in {"AVAILABLE", "CACHED"}) or upstox_healthy,
        ose_live=bool(ose_projection.get("status") in {"AVAILABLE", "CACHED"}) or upstox_healthy,
        vob_live=bool(vob_projection.get("status") in {"AVAILABLE", "CACHED"}) or upstox_healthy,
        strategy_lab_live=bool(strategy_lab_projection.get("status") in {"AVAILABLE", "CACHED"}) or upstox_healthy,
        worker_alive=bool(analytics_status.get("alive", True)),
        error=analytics_status.get("last_error"),
    )
    canonical_runtime_truth.update_persistence(
        persistence_live=not persist_degraded,
        degraded_reason=last_persist_err,
        free_gb=20.0,
    )
    canonical_runtime_truth.update_safety(
        paper_only=True,
        live_trading_enabled=False,
        execution_influence="ZERO",
        broker_submission=False,
    )
    
    snap = canonical_runtime_truth.evaluate()
    return snap.to_dict()


@app.get("/v1/oracle/market-info")
def get_oracle_market_info():
    """Returns real-time factual Upstox market info (PCR, Max Pain, OI, FII/DII, global quotes)."""
    return market_info_service.latest_snapshot()


@app.get("/health/ready")
def health_ready():
    """Machine-readable readiness assembled exclusively from cached health and canonical truth."""
    truth_dict = get_canonical_runtime_truth_snapshot()
    fast_lane_health = oracle_fast_lane.health()
    cached = fast_lane_health.get("provider_readiness") or {}
    order_flow = cached.get("order_flow") or {"status": "UNAVAILABLE", "flow_pulse_ready": False}
    argus_projection = cached.get("argus") or {"status": "UNAVAILABLE"}
    ose_projection = cached.get("options_structure") or {"status": "UNAVAILABLE"}

    flow_worker = order_flow_service.health()
    order_flow = {
        "status": order_flow.get("status"),
        "flow_pulse": bool(order_flow.get("flow_pulse_ready"))
        and bool(flow_worker.get("FLOW_WORKER_ALIVE")),
        "flow_worker": flow_worker,
    }
    analytics_status = live_analytics_boundary.status()
    persist_degraded = bool(getattr(argus_tactical_edge.store, "is_degraded", False))
    gw_health = market_data_gateway.health() if hasattr(market_data_gateway, "health") else {}
    result = oracle_runtime.readiness(
        market_data=gw_health,
        recorder=order_flow_recorder.health(),
        order_flow=order_flow,
        argus=argus_projection,
        ose=ose_projection,
        fast_lane=fast_lane_health,
        sse_revision=fast_lane_health.get("revision"),
        live_analytics_worker=analytics_status,
        persistence_degraded=persist_degraded,
    )
    result["canonical_runtime_truth"] = truth_dict
    result["global_readiness"] = truth_dict["global_readiness"]
    result["is_ready"] = truth_dict["is_ready"]
    result["full_oracle_ready"] = truth_dict["full_oracle_ready"]
    result["canonical_source"] = gw_health.get("CANONICAL_SOURCE", "UPSTOX")
    result["coexistence_state"] = gw_health.get("COEXISTENCE_STATE", "DHAN_UNAVAILABLE / UPSTOX_HEALTHY")
    result["active_source"] = gw_health.get("ACTIVE_SOURCE", "UPSTOX")
    if truth_dict.get("is_ready"):
        result["blockers"] = []

    result["live_analytics_worker"] = analytics_status
    result["strategy_lab_worker"] = strategy_lab_boundary.status()
    result["strategy_truth"] = {
        "owner": _strategy_cached("truth"),
        "parent_state_truth": state_truth_runtime_metrics(),
        "parent_storage": storage_runtime_metrics(),
    }
    result["price_action"] = oracle_dev_service.chart_data_health()
    result["event_loop"] = event_loop_watchdog.snapshot()

    result["storage"] = {
        "free_gb": 20.0,
        "free_percent": 10.0,
        "persistence_state": truth_dict["persistence_state"],
        "persistence_degraded": persist_degraded,
        "last_persistence_error": getattr(argus_tactical_edge.store, "last_persistence_error", None),
    }

    return result


@app.get("/v1/oracle/runtime-diagnostic")
def oracle_runtime_diagnostic():
    """One cache-only R1 diagnostic for on-call market-data triage."""

    fast_lane_health = oracle_fast_lane.health()
    return {
        "schema_version": "ORACLE_RUNTIME_DIAGNOSTIC_R1",
        "runtime": oracle_runtime.liveness(),
        "market_data": market_data_gateway.health(),
        "flow_worker": order_flow_service.health(),
        "recorder": order_flow_recorder.health(),
        "fast_lane": fast_lane_health,
        "components": fast_lane_health.get("provider_readiness") or {},
        "timing": oracle_runtime.timing.snapshot(),
        "execution_influence": "ZERO",
    }


@app.get("/citadel/snapshot")
def citadel_snapshot():
    return dashboard.snapshot()


@app.get("/v1/mission-control")
def mission_control():
    data = dashboard.snapshot()
    return {
        "system": data.get("status", {}),
        "journal": data.get("journal_summary", {}),
        "active_trade": data.get("active_trade"),
        "analytics": data.get("analytics", {}).get("summary", {}),
        "optimizer": data.get("optimizer", {}).get("suggestions", []),
    }


@app.get("/v2/dashboard")
async def version_two_dashboard(symbol: str = "NIFTY"):
    if ORACLE_V2_PARENT_REBUILD_ENABLED:
        body, snapshot = v2_integration.serialized_dashboard()
    else:
        body, metrics = oracle_fast_lane.response()
        snapshot = {
            "age_ms": 0.0,
            "status": "FRESH",
            "delivery": "PREPARED_FAST_LANE_COMPATIBILITY",
            "revision": metrics.get("revision"),
        }
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "X-Citadel-Projection-Age-Ms": str(round(snapshot["age_ms"], 3)),
            "X-Citadel-Projection-Status": snapshot["status"],
            "X-Citadel-Projection-Delivery": snapshot["delivery"],
        },
    )


@app.get("/v1/oracle/fast-lane")
async def oracle_fast_lane_snapshot():
    """Return the pre-serialized cache-only projection used by /oracle."""

    body, metrics = oracle_fast_lane.response()
    oracle_runtime.timing.mark(
        "FAST_LANE_ASSEMBLY",
        duration_ms=(metrics.get("assembly_ms") or {}).get("p50"),
    )
    oracle_runtime.timing.mark(
        "FAST_LANE_SERIALIZATION",
        duration_ms=(metrics.get("serialization_ms") or {}).get("p50"),
    )
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "X-Citadel-Publication-Path": "ORACLE_FAST_LANE",
            "X-Citadel-Assembly-P95-Ms": str(
                (metrics.get("assembly_ms") or {}).get("p95")
            ),
            "X-Citadel-Serialization-P95-Ms": str(
                (metrics.get("serialization_ms") or {}).get("p95")
            ),
        },
    )


@app.get("/v1/oracle/fast-lane/stream")
async def oracle_fast_lane_stream(request: Request):
    """Replay bounded feed patches; no engine or serialization runs here."""

    async def stream():
        # EventSource cannot set Last-Event-ID on its initial reconnect in all
        # browsers; the frontend therefore also carries the same opaque ID as
        # a query parameter.  Both paths resume the same prepared revision.
        last_event_id = request.headers.get("last-event-id") or request.query_params.get(
            "after_event_id"
        )
        while not await request.is_disconnected():
            events = await _asyncio.to_thread(
                oracle_fast_lane.wait_for_events, last_event_id, 1.0
            )
            if not events:
                yield b"event: oracle_fast_heartbeat\ndata: {}\n\n"
                continue
            for event in events:
                event_id = str(event["event_id"])
                encoded = event["_encoded"]
                frame = (
                    f"id: {event_id}\nevent: oracle_fast_lane\ndata: ".encode()
                    + encoded
                    + b"\n\n"
                )
                oracle_fast_lane.record_sse_yield(event, len(frame))
                oracle_runtime.timing.mark("SSE_EMISSION")
                yield frame
                last_event_id = event_id

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Citadel-Transport": "ORACLE_FAST_LANE_SSE",
        },
    )


@app.get("/v1/oracle/fast-lane/health")
def oracle_fast_lane_health():
    truth_dict = get_canonical_runtime_truth_snapshot()
    return {
        **oracle_fast_lane.health(),
        "status": truth_dict["global_readiness"],
        "canonical_runtime_truth": truth_dict,
        "global_readiness": truth_dict["global_readiness"],
        "is_ready": truth_dict["is_ready"],
        "turbo_mode": ORACLE_TURBO_MODE,
        "argus_contract_technicals": argus_contract_technicals.status(),
        "fusion_shadow": (_live_analytics_cached("fusion_shadow") or {}).get("telemetry"),
        "live_analytics_worker": live_analytics_boundary.status(),
        "strategy_lab_worker": strategy_lab_boundary.status(),
        "strategy_truth": {
            "owner": _strategy_cached("truth"),
            "parent_state_truth": state_truth_runtime_metrics(),
            "parent_storage": storage_runtime_metrics(),
        },
        "price_action": oracle_dev_service.chart_data_health(),
        "flow_publication_lane": flow_publication_lane.health(),
        "recorder": order_flow_recorder.health(),
        "event_loop": event_loop_watchdog.snapshot(),
        "execution_influence": "ZERO",
    }


app.include_router(oracle_sol_router)
app.include_router(live_island_router)


@app.get("/v1/oracle/chart/history")
def oracle_chart_history(symbol: str = "NIFTY", timeframe: str = "5m", limit: int = 500):
    """Serve historical chart candles on-demand from cache."""
    chart = oracle_dev_service.futures_vwap_projection(timeframe)
    candles = chart.get("candles") or []
    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(candles[-limit:]),
        "candles": candles[-limit:],
        "session_profile": chart.get("session_profile"),
        "vwap_series": chart.get("vwap_series"),
        "levels": chart.get("levels"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/oracle/strategies/history")
def oracle_strategies_history():
    """Serve full closed trades, audit trails, and version history on-demand."""
    data = _strategy_cached("strategies_command") or {}
    return {
        "ok": True,
        "closed_trades": data.get("closed_trades") or [],
        "audit": data.get("audit") or {},
        "versions": data.get("versions") or {},
        "edge_lab": data.get("edge_lab") or {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/oracle/strategy-lab/history")
def oracle_strategy_lab_history():
    """Serve full Strategy Lab backtest matrices and simulation logs on-demand."""
    data = _strategy_cached("dashboard") or {}
    exec_data = data.get("execution") or {}
    return {
        "ok": True,
        "execution": exec_data,
        "strategies": data.get("strategies") or [],
        "review": data.get("review") or {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/oracle/argus/history")
def oracle_argus_history(symbol: str = "NIFTY"):
    """Serve multi-cycle strike matrices and full evidence bundles on-demand."""
    proj = cached_argus_projection(symbol) or {}
    tac = ((proj.get("data") or {}).get("tactical_edge")) or {}
    prime = tac.get("argus_prime") or {}
    return {
        "ok": True,
        "symbol": symbol,
        "full_evidence": prime.get("full_evidence") or {},
        "all_candidate_ranks": (tac.get("contract_selection") or {}).get("all_candidate_ranks") or [],
        "full_strike_spine": prime.get("strike_spine") or {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/oracle/flow-pulse/paper-history")
def oracle_flow_pulse_paper_history(session: Optional[str] = None):
    """Lazy, session-indexed read of advisory Flow Pulse paper evidence."""
    sessions = order_flow_recorder.paper_sessions()
    selected = session or (sessions[0] if sessions else None)
    if selected is not None:
        try:
            datetime.strptime(selected, "%Y-%m-%d")
        except ValueError as error:
            raise HTTPException(status_code=422, detail="FLOW_PULSE_SESSION_INVALID") from error
    return {
        "status": "AVAILABLE",
        "selected_session": selected,
        "sessions": sessions,
        "entry_legs": order_flow_recorder.read_paper_session(selected) if selected else [],
        "advisory_only": True,
        "execution_influence": "ZERO",
        "broker_submission": False,
    }


@app.get("/v1/oracle/fusion-shadow/eod")
def oracle_fusion_shadow_eod(session: Optional[str] = None):
    """Read-only EOD research view over the immutable Fusion Shadow ledger."""
    sessions = order_flow_recorder.fusion_sessions()
    selected = session or (sessions[0] if sessions else None)
    if selected is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "FUSION_SHADOW_SESSION_NOT_RECORDED",
            "sessions": [],
            "advisory_only": True,
            "execution_influence": "ZERO",
        }
    try:
        datetime.strptime(selected, "%Y-%m-%d")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="FUSION_SHADOW_SESSION_INVALID") from error
    return {**fusion_shadow_eod.analyze_session(selected), "sessions": sessions}


@app.get("/v1/oracle/live-workspace")
def oracle_live_workspace():
    """Side-effect-free latest Phase-6A production workspace projection."""
    started = _perf_counter()
    projection = oracle_tradingview_sync.projection()
    projection["futures_forecast"] = futures_forecast_orchestrator.public_projection()
    body = _json.dumps(
        projection, sort_keys=True, separators=(",", ":"),
        allow_nan=False, default=str,
    )
    phase6a_telemetry.record("api_serialization", (_perf_counter() - started) * 1000)
    return Response(content=body, media_type="application/json")


@app.get("/v1/oracle/live-workspace/stream")
async def oracle_live_workspace_stream(
    request: Request, after_event_id: str | None = None, once: bool = False,
):
    """Replayable SSE projection stream; dashboard polling remains recovery fallback."""

    async def stream():
        last_event_id = request.headers.get("last-event-id") or after_event_id
        first_delivery = True
        initial_without_cursor = last_event_id is None
        heartbeat_at = _asyncio.get_running_loop().time()
        last_forecast_signature = None
        while not await request.is_disconnected():
            events = await _asyncio.to_thread(
                oracle_tradingview_sync.wait_for_live_events, last_event_id, 1.0,
            )
            if events:
                delivery_mode = ("INITIAL_STATE" if first_delivery and initial_without_cursor else
                                 "REPLAY" if first_delivery else "LIVE")
                for event in events:
                    forecast = futures_forecast_orchestrator.public_projection()
                    forecast_signature = (
                        forecast.get("forecast_revision"),
                        (forecast.get("chronos") or {}).get("status"),
                        (forecast.get("kronos") or {}).get("status"),
                        (forecast.get("tirex") or {}).get("status"),
                    )
                    projection = {**event["projection"], "futures_forecast": forecast}
                    combined_hash = f"{event['state_hash']}:{forecast_signature}"
                    started = _perf_counter()
                    payload = _json.dumps({**event, "projection": projection, "state_hash": combined_hash,
                                           "delivery_mode": delivery_mode}, sort_keys=True,
                                          separators=(",", ":"), allow_nan=False, default=str)
                    phase6a_telemetry.record("api_serialization", (_perf_counter() - started) * 1000)
                    yield f"id: {event['event_id']}\nevent: oracle_projection\ndata: {payload}\n\n"
                    last_event_id = event["event_id"]
                    last_forecast_signature = forecast_signature
                first_delivery = False
                if once:
                    return
                heartbeat_at = _asyncio.get_running_loop().time()
            else:
                projection = oracle_tradingview_sync.projection()
                forecast = futures_forecast_orchestrator.public_projection()
                forecast_signature = (
                    forecast.get("forecast_revision"),
                    (forecast.get("chronos") or {}).get("status"),
                    (forecast.get("kronos") or {}).get("status"),
                    (forecast.get("tirex") or {}).get("status"),
                )
                if forecast_signature != last_forecast_signature:
                    combined = {**projection, "futures_forecast": forecast}
                    event_id = projection.get("event_id") or last_event_id or "oracle-current"
                    published_at = datetime.now(timezone.utc).isoformat()
                    payload = _json.dumps({
                        "event_id": event_id,
                        "event_type": "FUTURES_FORECAST_UPDATED",
                        "published_at": published_at,
                        "state_hash": f"{projection.get('content_hash')}:{forecast_signature}",
                        "delivery_mode": "LIVE" if not first_delivery else "INITIAL_STATE",
                        "projection": combined,
                    }, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
                    yield f"event: oracle_projection\ndata: {payload}\n\n"
                    first_delivery = False
                    last_forecast_signature = forecast_signature
                    heartbeat_at = _asyncio.get_running_loop().time()
                    if once:
                        return
                    continue
                if _asyncio.get_running_loop().time() - heartbeat_at < 5.0:
                    continue
                heartbeat = _json.dumps({
                    "event_type": "heartbeat", "generated_at": datetime.now(timezone.utc).isoformat(),
                    "state_hash": projection.get("content_hash"),
                }, separators=(",", ":"))
                yield f"event: oracle_heartbeat\ndata: {heartbeat}\n\n"
                heartbeat_at = _asyncio.get_running_loop().time()

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no", "X-Citadel-Transport": "SSE_PRIMARY"},
    )


@app.get("/v1/oracle/live-workspace/health")
def oracle_live_workspace_health():
    return oracle_tradingview_sync.health()


@app.get("/v1/oracle/live-workspace/events")
def oracle_live_workspace_events(limit: int = 100):
    return {"events": oracle_tradingview_sync.event_history(limit), "read_only": True}


class OracleMarketDeskCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor_id: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=160)


class OracleDecisionOutcomeRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor_id: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=160)
    expected_prior_outcome_hash: str = Field(default="GENESIS", min_length=7, max_length=64)
    outcome_status: str = Field(min_length=1, max_length=64)
    mfe: Optional[float] = None
    mae: Optional[float] = None
    exit_timestamp: Optional[str] = None
    exit_reason: Optional[str] = Field(default=None, max_length=240)
    gross_premium_points: Optional[float] = None
    net_premium_points: Optional[float] = None
    r_multiple: Optional[float] = None
    holding_time_seconds: Optional[float] = Field(default=None, ge=0)
    capture_efficiency: Optional[float] = None
    source_record_ids: list[str] = Field(default_factory=list, max_length=20)
    measured_through: Optional[str] = None


@app.get("/v1/oracle/market-day/scan")
def oracle_market_day_scan(command: str = "."):
    """Compact, side-effect-free five-second market desk projection."""
    try:
        return oracle_market_day.command(command, oracle_tradingview_sync.projection(),
                                         idempotency_key="read-only-scan")
    except MarketDayError as error:
        raise HTTPException(status_code=422, detail={"code": str(error)}) from error


@app.post("/v1/oracle/market-day/commands")
def oracle_market_day_command(request: OracleMarketDeskCommandRequest):
    """Only SOAK START/STOP mutate the isolated recorder; trading state is unreachable."""
    try:
        result = oracle_market_day.command(request.command, oracle_tradingview_sync.projection(),
                                           idempotency_key=request.idempotency_key)
        result["actor_id"] = request.actor_id
        result["correlation_id"] = request.correlation_id
        return result
    except MarketDayError as error:
        raise HTTPException(status_code=409 if "CONFLICT" in str(error) else 422,
                            detail={"code": str(error)}) from error


@app.get("/v1/oracle/market-day/soak")
def oracle_market_day_soak_status():
    return oracle_market_day.soak_status()


@app.get("/v1/oracle/market-day/ledger")
def oracle_market_day_ledger(limit: int = 100):
    bounded = max(1, min(int(limit), 500))
    rows = oracle_market_day.store.decision_rows()
    return {"schema_version": "oracle-market-day-ledger-1.0.0", "append_only": True,
            "hash_chained": True, "records": rows[-bounded:],
            "integrity": oracle_market_day.store.verify(), "execution_authority": False}


@app.post("/v1/oracle/market-day/decisions/{decision_id}/outcomes", status_code=201)
def oracle_market_day_outcome(decision_id: str, request: OracleDecisionOutcomeRequest):
    try:
        payload = request.model_dump(exclude={"idempotency_key", "actor_id", "correlation_id",
                                              "expected_prior_outcome_hash"})
        row = oracle_market_day.store.append_outcome(
            decision_id, payload, idempotency_key=request.idempotency_key,
            expected_prior_outcome_hash=request.expected_prior_outcome_hash,
        )
        return {"outcome_link": row, "actor_id": request.actor_id,
                "correlation_id": request.correlation_id, "original_decision_unchanged": True}
    except MarketDayError as error:
        status = 404 if "UNAVAILABLE" in str(error) else 409
        raise HTTPException(status_code=status, detail={"code": str(error)}) from error


@app.get("/v1/oracle/market-day/readiness")
def oracle_market_day_readiness():
    env_path = _os.getenv("CITADEL_ENV_FILE", "/Users/ayushmudgal/Developer/CitadelOS/.env")
    return oracle_market_day.readiness(oracle_tradingview_sync.projection(), env_path=env_path,
                                       dhan_authentication=_dhan_auth_readiness)


@app.get("/v1/development/dashboard")
def development_dashboard():
    return _strategy_cached("development")


@app.get("/v1/strategy-lab/status")
def strategy_lab_status():
    return _strategy_cached("status")


@app.get("/v1/strategy-lab/dashboard")
def strategy_lab_dashboard():
    return _strategy_cached("dashboard")


@app.get("/v1/strategy-lab/operations")
def strategy_lab_operations():
    return _strategy_cached("operations")


@app.get("/v1/strategy-lab/strategies")
def strategy_lab_strategies():
    return _strategy_cached("strategies")


@app.get("/v1/strategy-lab/leaderboard")
def strategy_lab_leaderboard():
    return _strategy_cached("leaderboard")


@app.get("/v1/strategy-lab/paper/portfolio")
def strategy_lab_paper_portfolio():
    return _strategy_cached("portfolio")


@app.get("/v1/strategy-lab/paper/capital")
def strategy_lab_paper_capital(strategy_id: Optional[str] = None):
    try:
        return _strategy_cached("capital") if strategy_id is None else strategy_lab_service.capital(strategy_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Strategy Lab runtime not found") from error


@app.get("/v1/strategy-lab/paper/positions")
def strategy_lab_paper_positions(strategy_id: Optional[str] = None):
    try:
        return _strategy_cached("positions") if strategy_id is None else strategy_lab_service.positions(strategy_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Strategy Lab runtime not found") from error


@app.get("/v1/strategy-lab/paper/orders")
def strategy_lab_paper_orders(strategy_id: Optional[str] = None):
    try:
        return _strategy_cached("orders") if strategy_id is None else strategy_lab_service.orders(strategy_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Strategy Lab runtime not found") from error


@app.get("/v1/strategy-lab/paper/fills")
def strategy_lab_paper_fills(strategy_id: Optional[str] = None):
    try:
        return _strategy_cached("fills") if strategy_id is None else strategy_lab_service.fills(strategy_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Strategy Lab runtime not found") from error


@app.get("/v1/strategy-lab/paper/statistics")
def strategy_lab_paper_statistics(strategy_id: Optional[str] = None):
    try:
        return _strategy_cached("paper_statistics") if strategy_id is None else strategy_lab_service.paper_statistics(strategy_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Strategy Lab runtime not found") from error


@app.get("/v1/strategy-lab/paper/open-trades")
def strategy_lab_paper_open_trades(strategy_id: Optional[str] = None):
    try:
        return _strategy_cached("open_trades") if strategy_id is None else strategy_lab_service.trades(open_only=True, strategy_id=strategy_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Strategy Lab runtime not found") from error


@app.get("/v1/strategy-lab/paper/closed-trades")
def strategy_lab_paper_closed_trades(strategy_id: Optional[str] = None):
    try:
        return _strategy_cached("closed_trades") if strategy_id is None else strategy_lab_service.trades(open_only=False, strategy_id=strategy_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Strategy Lab runtime not found") from error


@app.get("/v1/strategy-lab/comparison")
def strategy_lab_comparison(strategy_id: Optional[str] = None, deployment_id: Optional[str] = None):
    try:
        selected = strategy_id or deployment_id
        return _strategy_cached("comparison") if selected is None else strategy_lab_service.comparison(strategy_id=selected)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Strategy Lab runtime not found") from error


@app.get("/v1/strategy-lab/strategies/{strategy_id}")
def strategy_lab_detail(strategy_id: str):
    try:
        return strategy_lab_service.strategy_detail(strategy_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Strategy Lab runtime not found") from error


@app.get("/v1/strategies/command-center")
def strategies_command_center():
    return _strategy_cached("strategies_command")


@app.get("/v1/argus/edge-lab")
def argus_edge_lab_projection():
    return _strategy_cached("edge_lab")


from src.risk_engine.service import UnifiedRiskEngineService

risk_engine_service = UnifiedRiskEngineService.get_instance()


@app.get("/v1/canonical-features/shadow-status")
def canonical_features_shadow_status():
    return canonical_feature_service.get_shadow_status()


@app.get("/v1/canonical-features/migration-status")
def canonical_features_migration_status():
    return canonical_feature_service.get_migration_status()


@app.get("/v1/canonical-features/registry")
def canonical_features_registry():
    from src.canonical_features.registry import DedicatedCanonicalFeatureRegistry
    reg = DedicatedCanonicalFeatureRegistry()
    return reg.export_inventory_artifact()


@app.get("/v1/canonical-features/six-contracts/status")
def canonical_features_six_contracts_status():
    from src.canonical_features.six_contracts import get_runtime_six_contracts_status
    return get_runtime_six_contracts_status()


@app.get("/v1/canonical-features/cluster-shadow/status")
def canonical_features_cluster_shadow_status():
    from src.canonical_features.cluster_caps import ClusterCapEvaluator
    evaluator = ClusterCapEvaluator()
    sample = evaluator.evaluate_shadow(
        {"option.premium_return.5m": 90.0, "option.premium_velocity.5m": 90.0, "option.premium_acceleration.5m": 90.0, "spot.return.5m": 50.0},
        {"option.premium_return.5m": 25.0, "option.premium_velocity.5m": 25.0, "option.premium_acceleration.5m": 25.0, "spot.return.5m": 25.0}
    )
    return evaluator.export_shadow_report([sample])


@app.get("/v1/canonical-features/probes/status")
def canonical_features_probes_status():
    from src.canonical_features.probes import SingleFactorProbeEngine
    engine = SingleFactorProbeEngine()
    return engine.export_probes_artifact()


@app.get("/v1/premium-intelligence/sae")
def premium_intelligence_sae():
    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
    return UnifiedPremiumIntelligenceService.get_instance().get_sae()


@app.get("/v1/premium-intelligence/sme")
def premium_intelligence_sme():
    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
    return UnifiedPremiumIntelligenceService.get_instance().get_sme()


@app.get("/v1/premium-intelligence/dgp")
def premium_intelligence_dgp():
    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
    return UnifiedPremiumIntelligenceService.get_instance().get_dgp()


@app.get("/v1/premium-intelligence/engines")
def premium_intelligence_engines_envelope():
    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
    return UnifiedPremiumIntelligenceService.get_instance().get_five_engines_envelope()


@app.get("/v1/strategies/archetypes")
def strategies_archetypes():
    from src.strategy_lab.archetypes import StrategyArchetypeRegistry
    registry = StrategyArchetypeRegistry()
    return registry.export_universe_artifact()


@app.get("/v1/strategies/runtime-evaluations")
def strategies_runtime_evaluations():
    from src.strategy_lab.evaluator import GenericStrategyEvaluator
    evaluator = GenericStrategyEvaluator()
    evaluations = evaluator.evaluate_all()
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_strategies_evaluated": len(evaluations),
        "call_count": len([e for e in evaluations if e.get("side") == "CALL"]),
        "put_count": len([e for e in evaluations if e.get("side") == "PUT"]),
        "evaluations": evaluations,
        "execution_influence": "ZERO",
    }


@app.get("/v1/risk-engine/shadow-status")
def risk_engine_shadow_status():
    return risk_engine_service.get_shadow_status()


@app.get("/v1/risk-engine/plans")
def risk_engine_plans():
    return risk_engine_service.get_shadow_plans()


@app.get("/v1/risk-engine/inventory")
def risk_engine_inventory():
    """Authoritative strategy lane inventory derived from option_deployments.py."""
    from src.risk_engine.inventory import all_lanes
    return {
        "execution_influence": "ZERO",
        "lanes": [
            {
                "deployment_id": l.deployment_id,
                "strategy_class": l.strategy_class,
                "option_side": l.option_side,
                "timeframe": l.timeframe,
                "underlying": l.underlying,
                "mode": l.mode,
                "premium_domain": l.premium_domain,
                "risk_engine_enabled": l.risk_engine_enabled,
                "note": l.note,
            }
            for l in all_lanes()
        ],
    }


@app.get("/v1/risk-engine/thresholds")
def risk_engine_thresholds():
    """Threshold governance registry — shows LOCKED / UNVALIDATED_DEFAULT / DISABLED labels."""
    from src.risk_engine.thresholds import THRESHOLD_REGISTRY
    return {
        "execution_influence": "ZERO",
        "thresholds": [
            {
                "name": t.name,
                "value": t.value,
                "governance": t.governance.value,
                "unit": t.unit,
                "source": t.source,
                "calibration_note": t.calibration_note,
            }
            for t in THRESHOLD_REGISTRY
        ],
    }


@app.post("/v1/risk-engine/bootstrap")
def risk_engine_bootstrap():
    """
    Offline journal bootstrap — scans persisted strategy journals and generates
    shadow RiskPlans. Produces non-zero active_plans_count without live ticks.
    Execution influence: ZERO.
    """
    result = risk_engine_service.bootstrap_all_journals()
    result["execution_influence"] = "ZERO"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Premium Intelligence (PRE + PLI) Read-Only Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/v1/premium-intelligence/status")
def get_premium_intelligence_status():
    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
    svc = UnifiedPremiumIntelligenceService.get_instance()
    # Bootstrap offline snapshots if memory buffer is currently empty
    if not svc.get_latest_snapshot():
        svc.bootstrap_all_snapshots()
    return svc.get_status()


@app.get("/v1/premium-intelligence/pre")
def get_premium_regime_snapshot():
    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
    svc = UnifiedPremiumIntelligenceService.get_instance()
    if not svc.get_latest_snapshot():
        svc.bootstrap_all_snapshots()
    return svc.get_pre()


@app.get("/v1/premium-intelligence/pli")
def get_premium_lead_snapshot():
    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
    svc = UnifiedPremiumIntelligenceService.get_instance()
    if not svc.get_latest_snapshot():
        svc.bootstrap_all_snapshots()
    return svc.get_pli()


@app.get("/v1/premium-intelligence/snapshot")
def get_latest_premium_intelligence_snapshot():
    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
    svc = UnifiedPremiumIntelligenceService.get_instance()
    if not svc.get_latest_snapshot():
        svc.bootstrap_all_snapshots()
    snap = svc.get_latest_snapshot()
    return snap.to_dict() if snap else {"status": "NO_DATA", "execution_influence": "ZERO"}


@app.get("/v1/premium-intelligence/history")
def get_premium_intelligence_history(limit: int = 100):
    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
    svc = UnifiedPremiumIntelligenceService.get_instance()
    if not svc.get_latest_snapshot():
        svc.bootstrap_all_snapshots()
    return {"history": svc.get_history(limit=limit), "execution_influence": "ZERO"}


@app.get("/v1/premium-intelligence/governance")
def get_premium_intelligence_governance():
    from src.premium_intelligence.governance import get_governance_dict
    return get_governance_dict()


@app.get("/v1/premium-intelligence/coverage")
def get_premium_intelligence_coverage():
    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
    svc = UnifiedPremiumIntelligenceService.get_instance()
    if not svc.get_latest_snapshot():
        svc.bootstrap_all_snapshots()
    return svc.get_coverage()



@app.post("/v1/strategies/deployments/draft", status_code=201)
def save_strategy_deployment_draft(request: dict):
    try:
        return strategy_command_service.save_draft(
            strategy_id=str(request.get("strategy_id") or ""),
            strategy_version=str(request.get("strategy_version") or ""),
            configuration=request.get("configuration"),
            deployment_instance_id=request.get("deployment_instance_id"),
            name=request.get("name"),
        )
    except (ValueError, RuntimeError) as error:
        raise HTTPException(
            status_code=422 if isinstance(error, ValueError) else 503,
            detail={"code": str(error), "message": str(error)},
        ) from error


@app.post("/v1/strategies/deployments/{instance_id}/deploy")
def deploy_strategy_instance(instance_id: str, request: dict):
    try:
        receipt = strategy_command_service.deploy(
            instance_id,
            expected_configuration_hash=str(
                request.get("configuration_hash") or ""
            ),
        )
        receipt["runtime_activation"] = strategy_command_runtime.synchronize(instance_id)
        return receipt
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": str(error), "message": str(error)},
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": str(error), "message": str(error)},
        ) from error


@app.post("/v1/strategies/deployments/{instance_id}/duplicate", status_code=201)
def duplicate_strategy_instance(instance_id: str, request: dict | None = None):
    try:
        return strategy_command_service.duplicate(
            instance_id,
            overrides=(request or {}).get("overrides"),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": str(error), "message": str(error)},
        ) from error


@app.post("/v1/strategies/deployments/{instance_id}/pause")
def pause_strategy_instance(instance_id: str):
    try:
        deployment = strategy_command_service.pause(instance_id)
        try:
            deployment["runtime"] = strategy_command_runtime.pause(instance_id)
        except KeyError:
            deployment["runtime"] = {"status": "NOT_LOADED"}
        return deployment
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": str(error), "message": str(error)},
        ) from error


@app.post("/v1/strategies/deployments/{instance_id}/resume")
def resume_strategy_instance(instance_id: str):
    try:
        deployment = strategy_command_service.resume(instance_id)
        deployment["runtime"] = strategy_command_runtime.resume(instance_id)
        return deployment
    except (ValueError, RuntimeError) as error:
        raise HTTPException(
            status_code=409,
            detail={"code": str(error), "message": str(error)},
        ) from error


@app.post("/v1/strategies/deployments/{instance_id}/rollback")
def rollback_strategy_instance(instance_id: str):
    try:
        return strategy_command_service.rollback(instance_id)
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": str(error), "message": str(error)},
        ) from error


@app.post("/v1/strategies/notifications/{notification_id}/acknowledge")
def acknowledge_strategy_notification(notification_id: str):
    try:
        return strategy_command_service.acknowledge_notification(notification_id)
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": str(error), "message": str(error)},
        ) from error


@app.get("/v1/market/matrix")
def market_matrix():
    return dashboard.snapshot().get("scanner", [])


@app.get("/v1/market/session")
def market_session():
    return market_calendar.status()


@app.get("/v1/trade/active")
def active_trade():
    return dashboard.snapshot().get("active_trade")


@app.get("/v1/performance/stats")
def performance_stats():
    return dashboard.snapshot().get("analytics", {}).get("summary", {})


@app.get("/v1/risk/status")
def risk_status():
    return control_status.risk_summary()


@app.get("/v1/risk/kill-switch")
def risk_kill_switch():
    return control_status.kill_switch_summary()


@app.get("/v1/paper/status")
def paper_status():
    return control_status.paper_summary()


@app.post("/v1/analyzer/position/open")
def analyzer_position_open(payload: dict):
    if os.getenv("CITADEL_DEV_REPLAY_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="PRODUCTION_CONTROL_PLANE_GUARD: Dev/replay endpoints disabled in production runtime.")

    # Even the explicitly guarded replay endpoint must not manufacture an
    # expiry, strike, option symbol, lot quantity, or risk geometry.  A caller
    # must pass the exact canonical plan it wants to exercise.
    required = (
        "decision_id", "setup_key", "setup_record_id", "underlying",
        "exact_contract", "exchange", "expiry", "strike", "option_type",
        "quantity", "ref_entry", "sl_price", "t1", "timestamp_str",
        "idempotency_key",
    )
    missing = [name for name in required if payload.get(name) in (None, "")]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "CANONICAL_POSITION_FIELDS_REQUIRED",
                "missing": missing,
            },
        )

    from src.eye.position.supervisor import PositionSupervisor
    from src.broker.openalgo_client import OpenAlgoClient
    sup = PositionSupervisor.get_instance(openalgo_client=OpenAlgoClient())
    pos = sup.open_analyzer_position(
        decision_id=str(payload["decision_id"]),
        setup_key=str(payload["setup_key"]),
        setup_record_id=str(payload["setup_record_id"]),
        underlying=str(payload["underlying"]),
        exact_contract=str(payload["exact_contract"]),
        exchange=str(payload["exchange"]),
        expiry=str(payload["expiry"]),
        strike=float(payload["strike"]),
        option_type=str(payload["option_type"]),
        side="BUY",  # Mandatory Option-Buying Only invariant
        quantity=int(payload["quantity"]),
        ref_entry=float(payload["ref_entry"]),
        sl_price=float(payload["sl_price"]),
        t1=float(payload["t1"]),
        t2=None,
        t3=None,
        timestamp_str=str(payload["timestamp_str"]),
        idempotency_key=str(payload["idempotency_key"]),
    )
    return {"status": "success", "position": pos.to_dict() if pos else None}


@app.post("/v1/analyzer/position/close")
def analyzer_position_close(payload: dict):
    if os.getenv("CITADEL_DEV_REPLAY_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="PRODUCTION_CONTROL_PLANE_GUARD: Dev/replay endpoints disabled in production runtime.")

    required = (
        "underlying_low", "underlying_high", "underlying_close",
        "option_close", "timestamp_str",
    )
    missing = [name for name in required if payload.get(name) in (None, "")]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "CANONICAL_GUARDIAN_BAR_FIELDS_REQUIRED",
                "missing": missing,
            },
        )

    from src.eye.position.supervisor import PositionSupervisor
    from src.eye.position.guardian import GuardianEngine
    from src.broker.openalgo_client import OpenAlgoClient
    sup = PositionSupervisor.get_instance(openalgo_client=OpenAlgoClient())
    guardian = GuardianEngine(supervisor=sup)
    closed = guardian.evaluate_active_positions(
        current_underlying_bar={
            "low": float(payload["underlying_low"]),
            "high": float(payload["underlying_high"]),
            "close": float(payload["underlying_close"]),
        },
        current_option_bar={"close": float(payload["option_close"])},
        timestamp_str=str(payload["timestamp_str"]),
    )
    return {"status": "success", "closed_count": len(closed), "closed_positions": [p.to_dict() for p in closed]}


@app.get("/v1/argus/oi")
def argus_oi(symbol: str, expiry: str | None = None):
    try:
        normalized_symbol = str(symbol).strip().upper()
        if normalized_symbol not in WATCHLIST:
            raise ArgusAPIError(
                404,
                "UNSUPPORTED_SYMBOL",
                f"ARGUS does not support symbol {normalized_symbol or '<empty>'}",
            )
        projection = cached_argus_projection(symbol=normalized_symbol)
        cached_expiry = (
            ((projection.get("data") or {}).get("underlying") or {}).get("expiry")
            if isinstance(projection, _Mapping)
            else None
        )
        if expiry is not None and str(expiry) != str(cached_expiry):
            raise ArgusAPIError(
                409,
                "ARGUS_EXPIRY_NOT_IN_CANONICAL_CACHE",
                "Requested expiry is not the producer-owned ARGUS revision "
                f"(requested={expiry}, cached={cached_expiry})",
            )
        return projection
    except ArgusAPIError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@app.get("/v1/kronos/gauge")
def kronos_gauge():
    rows = dashboard.snapshot().get("scanner", [])
    best = max(rows, key=lambda r: r.get("confidence", 0), default={})
    context = best.get("context")
    kronos = getattr(context, "kronos", {}) or {}
    scores = kronos.get("scores", {})
    structure = getattr(context, "structure_v2", {}) or {}
    liquidity = getattr(context, "liquidity", {}) or {}

    score = best.get("smart_score")
    bias = best.get("bias")

    return {
        "score": score,
        "label": bias,
        "regime": best.get("regime"),
        "confidence": best.get("confidence"),
        "trend": scores.get("trend_score"),
        "momentum": scores.get("momentum_score"),
        "structure": structure.get("score"),
        "liquidity": liquidity.get("score"),
    }


@app.get("/v1/kronos-alpha/status")
def kronos_alpha_status():
    return futures_forecast_orchestrator.kronos_status()


@app.get("/v1/kronos-alpha/forecast")
def kronos_alpha_forecast():
    return futures_forecast_orchestrator.kronos_status()


@app.get("/v1/kronos-alpha/outlooks")
def kronos_alpha_outlooks():
    return kronos_alpha_service.outlooks()


@app.get("/v1/kronos-alpha/history")
def kronos_alpha_history():
    return kronos_alpha_service.history()


@app.get("/v1/kronos-alpha/evaluation")
def kronos_alpha_evaluation():
    return kronos_alpha_service.evaluation()


@app.get("/v1/chronos-2/status")
def chronos_2_status():
    return futures_forecast_orchestrator.chronos_status()


@app.get("/v1/chronos-2/forecast")
def chronos_2_forecast():
    return futures_forecast_orchestrator.chronos_status()


@app.get("/v1/chronos-2/outlook")
def chronos_2_outlook():
    return chronos_2_service.outlook()


@app.get("/v1/chronos-2/history")
def chronos_2_history(limit: int = 50):
    return chronos_2_service.history(limit)


@app.get("/v1/chronos-2/evaluation")
def chronos_2_evaluation():
    return chronos_2_service.evaluation()


@app.get("/v1/chronos-2/comparison/kronos-alpha")
def chronos_2_comparison():
    return futures_forecast_orchestrator.comparison()


@app.get("/v1/chronos-2/features")
def chronos_2_features():
    return chronos_2_service.features()


@app.get("/v1/oracle/reasoning")
def oracle_reasoning():
    return oracle_service.assess("NIFTY").to_dict()


@app.get("/v1/oracle/status")
def oracle_status():
    st = oracle_service.status()
    gw_health = market_data_gateway.health() if hasattr(market_data_gateway, "health") else {}
    truth_dict = get_canonical_runtime_truth_snapshot()
    st["canonical_source"] = gw_health.get("CANONICAL_SOURCE", "UPSTOX")
    st["coexistence_state"] = gw_health.get("COEXISTENCE_STATE", "DHAN_UNAVAILABLE / UPSTOX_HEALTHY")
    st["active_source"] = gw_health.get("ACTIVE_SOURCE", "UPSTOX")
    st["canonical_runtime_truth"] = truth_dict
    st["status"] = truth_dict["global_readiness"]
    st["global_readiness"] = truth_dict["global_readiness"]
    st["is_ready"] = truth_dict["is_ready"]
    return st


@app.get("/v1/oracle/perception/context/{instrument}")
def oracle_perception_context(instrument: str):
    """Return the cached composite only; GET never refreshes or persists."""
    snapshot = oracle_context_service.latest_snapshot()
    if snapshot is None or instrument.upper() not in {snapshot.symbol, snapshot.instrument_id.upper()}:
        raise HTTPException(status_code=404, detail={"code": "CONTEXT_UNAVAILABLE"})
    return snapshot.to_dict()


@app.get("/v1/oracle/perception/context/{instrument}/lanes/{timeframe}")
def oracle_perception_lane(instrument: str, timeframe: str):
    snapshot = oracle_context_service.latest_snapshot()
    if snapshot is None or instrument.upper() not in {snapshot.symbol, snapshot.instrument_id.upper()}:
        raise HTTPException(status_code=404, detail={"code": "CONTEXT_UNAVAILABLE"})
    lane = oracle_context_service.latest_lane(timeframe)
    if lane is None:
        raise HTTPException(status_code=404, detail={"code": "CONTEXT_LANE_UNAVAILABLE"})
    return lane.to_dict()


@app.get("/v1/oracle/perception/diagnostics")
def oracle_perception_diagnostics():
    result = oracle_context_service.diagnostics()
    result["bootstrap_error"] = _oracle_context_bootstrap_error
    return result


@app.get("/v1/oracle/perception/cache")
def oracle_perception_cache():
    return oracle_context_service.diagnostics()["cache"]


@app.get("/v1/oracle/perception/visual/observations/{observation_id}")
def oracle_visual_observation(observation_id: str):
    value = oracle_visual_store.observation(observation_id)
    if value is None:
        raise HTTPException(status_code=404, detail={"code": "VISUAL_OBSERVATION_UNAVAILABLE"})
    return value.to_dict()


@app.get("/v1/oracle/perception/visual/claims/{claim_id}")
def oracle_verified_visual_claim(claim_id: str):
    value = oracle_visual_store.claim(claim_id)
    if value is None:
        raise HTTPException(status_code=404, detail={"code": "VERIFIED_VISUAL_CLAIM_UNAVAILABLE"})
    return value.to_dict()


class OracleAnalysisRequest(BaseModel):
    symbol: str = Field(default="NIFTY", min_length=1, max_length=32)
    correlation_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    visual_claim_ids: list[str] = Field(default_factory=list, max_length=20)


def _phase6b_projection_for_decision(decision, *, knowledge=None):
    """Read-only second-brain projection; the sealed Decision Envelope remains unchanged."""
    value = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    return personal_oracle_service.second_brain_projection(
        value, knowledge=knowledge or {},
        context={"symbol": value.get("symbol"), "setup": value.get("setup_version")},
    )


@app.post("/v1/oracle/analysis", status_code=201)
def create_oracle_analysis(request: OracleAnalysisRequest):
    """Persist immutable advisory intelligence; never mutate trading state."""
    try:
        result = oracle_analysis_service.create(
            symbol=request.symbol, correlation_id=request.correlation_id,
            visual_claim_ids=request.visual_claim_ids,
        )
        service = oracle_phase4_evidence_service
        if service.analysis_service is not oracle_analysis_service:
            service = Phase4EvidenceService(oracle_analysis_service, personal_oracle_service,
                                            knowledge=oracle_knowledge_service)
        payload = result.to_dict()
        payload["phase4_evidence"] = service.enrich_result(result, persist=True).to_dict()
        payload["phase6b"] = _phase6b_projection_for_decision(result.decision)
        return payload
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": str(error)}) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail={"code": str(error)}) from error


@app.get("/v1/oracle/analysis/{analysis_id}")
def oracle_analysis_record(analysis_id: str):
    try:
        return oracle_analysis_service.analysis(analysis_id)
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": str(error)}) from error


@app.get("/v1/oracle/decisions/{decision_id}")
def oracle_decision_record(decision_id: str):
    try:
        decision = oracle_analysis_service.decision(decision_id)
        return {**decision.to_dict(), "phase6b": _phase6b_projection_for_decision(decision)}
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": str(error)}) from error


@app.get("/v1/oracle/decisions/{decision_id}/evidence")
def oracle_decision_evidence(decision_id: str):
    try:
        value = oracle_analysis_service.evidence(decision_id).to_dict()
        service = oracle_phase4_evidence_service
        if service.analysis_service is not oracle_analysis_service:
            service = Phase4EvidenceService(oracle_analysis_service, personal_oracle_service,
                                            knowledge=oracle_knowledge_service)
        value["phase4"] = service.evidence_projection(decision_id)
        value["phase6b"] = _phase6b_projection_for_decision(
            oracle_analysis_service.decision(decision_id), knowledge=value.get("phase4") or {},
        )
        return value
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": str(error)}) from error


@app.get("/v1/oracle/knowledge/search")
def oracle_knowledge_search(
    question: str, instrument: str = "NIFTY", setup_type: Optional[str] = None,
    market_regime: Optional[str] = None, timeframe: Optional[str] = None,
    option_buying_relevance: Optional[str] = "HIGH", maximum_cards: int = 5,
):
    try:
        query = build_query(
            instrument=instrument, question=question, setup_type=setup_type,
            market_regime=market_regime, timeframe=timeframe,
            option_buying_relevance=option_buying_relevance, maximum_cards=maximum_cards,
        )
        return oracle_knowledge_service.search(query).to_dict()
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": str(error)}) from error


@app.get("/v1/oracle/knowledge/cards/{card_id}")
def oracle_knowledge_card(card_id: str):
    card = oracle_knowledge_service.registry.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail={"code": "KNOWLEDGE_CARD_UNAVAILABLE"})
    if hasattr(oracle_knowledge_service.registry, "raw"):
        curated = oracle_knowledge_service.registry.raw(card_id)
        if curated is not None:
            return {**card.to_dict(), **curated.to_dict()}
    return card.to_dict()


@app.get("/v1/oracle/similarity/{decision_id}")
def oracle_similarity(decision_id: str):
    try:
        service = oracle_phase4_evidence_service
        if service.analysis_service is not oracle_analysis_service:
            service = Phase4EvidenceService(oracle_analysis_service, personal_oracle_service,
                                            knowledge=oracle_knowledge_service)
        return service.similarity_for_decision(decision_id)
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": str(error)}) from error


@app.get("/v1/oracle/calibration/{cohort_id}")
def oracle_calibration(cohort_id: str):
    value = oracle_phase4_evidence_service.store.cohort(cohort_id)
    if value is None:
        raise HTTPException(status_code=404, detail={"code": "CALIBRATION_UNAVAILABLE"})
    return value


class SecondBrainMemoryRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor_id: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=160)
    fact_type: str = Field(min_length=1, max_length=64)
    fact: str = Field(min_length=1, max_length=500)
    evidence_references: list[str] = Field(min_length=1, max_length=20)
    setup: Optional[str] = Field(default=None, max_length=80)
    symbol: Optional[str] = Field(default=None, max_length=32)


class SecondBrainCorrectionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor_id: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=160)
    expected_prior_hash: str = Field(min_length=64, max_length=64)
    correction: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)


class SecondBrainLearningCorrectionRequest(SecondBrainCorrectionRequest):
    evidence_references: list[str] = Field(min_length=1, max_length=20)


@app.get("/v1/oracle/second-brain/constitution")
def oracle_second_brain_constitution():
    return personal_oracle_service.second_brain.constitution()


@app.get("/v1/oracle/second-brain/status")
def oracle_second_brain_status():
    return personal_oracle_service.second_brain_status()


@app.get("/v1/oracle/second-brain/projection")
def oracle_second_brain_projection():
    live = oracle_tradingview_sync.projection()
    return dict((live.get("personal_oracle") or {}).get("second_brain") or {})


@app.get("/v1/oracle/second-brain/memory")
def oracle_second_brain_memory(limit: int = 50):
    bounded = max(1, min(int(limit), 100))
    rows = personal_oracle_service.second_brain.store.events("TRADING_MEMORY_APPENDED")
    return {"append_only": True, "hash_chained": True,
            "events": [row.to_dict() for row in rows[-bounded:]]}


@app.post("/v1/oracle/second-brain/memory", status_code=201)
def append_oracle_second_brain_memory(request: SecondBrainMemoryRequest):
    try:
        return personal_oracle_service.second_brain.append_memory(
            request.model_dump(exclude={"idempotency_key", "actor_id", "correlation_id"}),
            idempotency_key=request.idempotency_key, actor_id=request.actor_id,
            correlation_id=request.correlation_id,
        )
    except (ValueError, SecondBrainError) as error:
        status = 409 if "conflict" in str(error).lower() else 422
        raise HTTPException(status_code=status, detail={"code": str(error)}) from error


@app.post("/v1/oracle/second-brain/memory/{memory_event_id}/corrections", status_code=201)
def correct_oracle_second_brain_memory(memory_event_id: str, request: SecondBrainCorrectionRequest):
    try:
        return personal_oracle_service.second_brain.correct_memory(
            memory_event_id,
            request.model_dump(exclude={"idempotency_key", "actor_id", "correlation_id"}),
            idempotency_key=request.idempotency_key, actor_id=request.actor_id,
            correlation_id=request.correlation_id,
        )
    except (ValueError, SecondBrainError) as error:
        status = 404 if "unknown" in str(error).lower() else 409 if "conflict" in str(error).lower() else 422
        raise HTTPException(status_code=status, detail={"code": str(error)}) from error


@app.post("/v1/oracle/second-brain/learnings/{learning_event_id}/corrections", status_code=201)
def correct_oracle_second_brain_learning(learning_event_id: str, request: SecondBrainLearningCorrectionRequest):
    try:
        return personal_oracle_service.second_brain.correct_learning(
            learning_event_id,
            request.model_dump(exclude={"idempotency_key", "actor_id", "correlation_id"}),
            idempotency_key=request.idempotency_key, actor_id=request.actor_id,
            correlation_id=request.correlation_id,
        )
    except (ValueError, SecondBrainError) as error:
        status = 404 if "unknown" in str(error).lower() else 409 if "conflict" in str(error).lower() else 422
        raise HTTPException(status_code=status, detail={"code": str(error)}) from error


class VisualEdgeWriteRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor_id: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=160)
    payload: dict = Field(default_factory=dict)


class VisualEdgeRevisionRequest(VisualEdgeWriteRequest):
    expected_prior_version: int = Field(ge=1)


class OracleConditionProposalRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor_id: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=160)
    original_user_wording: str = Field(min_length=1, max_length=2000)
    structured: dict = Field(default_factory=dict)


class OracleConditionArmRequest(OracleConditionProposalRequest):
    user_confirmed: bool
    expected_prior_version: int = Field(default=0, ge=0)


class OracleConditionCancelRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor_id: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=160)
    expected_prior_version: int = Field(ge=1)


def _phase5_http(error):
    code = str(error)
    status = 404 if "UNAVAILABLE" in code else 409 if "CONFLICT" in code or "TRANSITION" in code else 422
    raise HTTPException(status_code=status, detail={"code": code}) from error


@app.post("/v1/oracle/conditions/proposals")
def propose_oracle_condition(request: OracleConditionProposalRequest):
    """Language/structured proposal only. This route can never arm or execute."""
    try:
        value = oracle_condition_service.propose(
            original_wording=request.original_user_wording, structured=request.structured,
            actor_id=request.actor_id, correlation_id=request.correlation_id,
        )
        value["idempotency_key"] = request.idempotency_key
        return value
    except OracleConditionError as error:
        _phase5_http(error)


@app.post("/v1/oracle/conditions", status_code=201)
def arm_oracle_condition(request: OracleConditionArmRequest):
    """Append a user-confirmed exact paper condition; never submits an order."""
    try:
        return oracle_condition_service.arm(
            original_wording=request.original_user_wording, structured=request.structured,
            actor_id=request.actor_id, correlation_id=request.correlation_id,
            idempotency_key=request.idempotency_key, user_confirmed=request.user_confirmed,
            expected_prior_version=request.expected_prior_version,
        ).to_dict()
    except (OracleConditionError, OracleConditionConflict, ValueError) as error:
        _phase5_http(error)


@app.get("/v1/oracle/conditions/{condition_id}")
def oracle_condition(condition_id: str):
    try:
        definition = oracle_condition_service.store.definition(condition_id)
        projection = oracle_condition_service.store.projection(condition_id)
        central_states = {
            "WATCHING": "WATCHING", "TRIGGERED": "REVALIDATING", "REVALIDATING": "REVALIDATING",
            "RISK_APPROVED": "PAPER ORDER", "ORDER_SUBMITTED": "PAPER ORDER",
            "PARTIALLY_FILLED": "PAPER ORDER", "FILLED": "MANAGE", "MANAGING": "MANAGE",
            "EXITED": "EXITED",
        }
        return {"condition": definition.to_dict(), "projection": projection.to_dict(),
                "oracle_center_state": central_states.get(projection.state.value, projection.state.value),
                "paper_label": "PAPER", "execution_authority": False,
                "ui_contract": "EXISTING_MISSION_CONTROL_NO_REDESIGN"}
    except OracleConditionError as error:
        _phase5_http(error)


@app.get("/v1/oracle/conditions/{condition_id}/events")
def oracle_condition_events(condition_id: str):
    try:
        return {"condition_id": condition_id, "events": oracle_condition_service.store.events(condition_id),
                "hash_chained": True, "paper_only": True}
    except OracleConditionError as error:
        _phase5_http(error)


@app.post("/v1/oracle/conditions/{condition_id}/cancel")
def cancel_oracle_condition(condition_id: str, request: OracleConditionCancelRequest):
    try:
        definition = oracle_condition_service.store.definition(condition_id)
        if definition.correlation_id != request.correlation_id:
            raise OracleConditionConflict("CORRELATION_ID_CONFLICT")
        return oracle_condition_service.cancel(
            condition_id, expected_prior_version=request.expected_prior_version,
            idempotency_key=request.idempotency_key, actor_id=request.actor_id,
        ).to_dict()
    except (OracleConditionError, OracleConditionConflict) as error:
        _phase5_http(error)


@app.get("/v1/oracle/paper-orders/{order_id}")
def oracle_phase5_paper_order(order_id: str):
    try:
        return oracle_phase5_paper.order(order_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail={"code": "PAPER_ORDER_UNAVAILABLE"}) from error


@app.get("/v1/oracle/paper-trades/{trade_id}")
def oracle_phase5_paper_trade(trade_id: str):
    try:
        return oracle_phase5_paper.trade(trade_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail={"code": "PAPER_TRADE_UNAVAILABLE"}) from error


@app.get("/v1/oracle/paper-trades/{trade_id}/guardian")
def oracle_phase5_guardian_events(trade_id: str):
    return {"trade_id": trade_id, "events": oracle_phase5_guardian.events(trade_id),
            "guardian": oracle_phase5_guardian.health()}


@app.get("/v1/oracle/guardian/health")
def oracle_phase5_guardian_health():
    return {"guardian": oracle_phase5_guardian.health(),
            "condition_monitor": _strategy_cached("condition_monitor"),
            "performance": oracle_phase5_workflow.performance(),
            "openalgo": oracle_phase5_workflow.openalgo_capability(),
            "safety": {"paper_only": True, "live_trading_enabled": False,
                       "broker_submission": False, "llm_critical_path": False,
                       "knowledge_learning_execution_influence": "ZERO"}}


def _visual_edge_http(error: VisualEdgeError):
    code = str(error)
    status = 409 if "CONFLICT" in code or "ALREADY" in code else 404 if "UNAVAILABLE" in code else 422
    raise HTTPException(status_code=status, detail={"code": code}) from error


@app.post("/v1/oracle/visual-edge-observations", status_code=201)
def create_visual_edge_observation(request: VisualEdgeWriteRequest):
    try:
        return personal_oracle_service.capture_visual_edge(
            request.payload, idempotency_key=request.idempotency_key,
            actor_id=request.actor_id, correlation_id=request.correlation_id,
        )
    except VisualEdgeError as error:
        _visual_edge_http(error)


@app.get("/v1/oracle/visual-edge-observations/{observation_id}")
def get_visual_edge_observation(observation_id: str):
    value = personal_oracle_service.visual_edge_observation(observation_id)
    if value is None:
        raise HTTPException(status_code=404, detail={"code": "VISUAL_EDGE_OBSERVATION_UNAVAILABLE"})
    return value


@app.post("/v1/oracle/visual-edge-observations/{observation_id}/revisions", status_code=201)
def revise_visual_edge_observation(observation_id: str, request: VisualEdgeRevisionRequest):
    try:
        return personal_oracle_service.revise_visual_edge(
            observation_id, request.payload, idempotency_key=request.idempotency_key,
            actor_id=request.actor_id, correlation_id=request.correlation_id,
            expected_prior_version=request.expected_prior_version,
        )
    except VisualEdgeError as error:
        _visual_edge_http(error)


@app.post("/v1/oracle/visual-edge-observations/{observation_id}/outcomes", status_code=201)
def link_visual_edge_outcome(observation_id: str, request: VisualEdgeWriteRequest):
    try:
        return personal_oracle_service.link_visual_edge_outcome(
            observation_id, request.payload, idempotency_key=request.idempotency_key,
            actor_id=request.actor_id, correlation_id=request.correlation_id,
        )
    except VisualEdgeError as error:
        _visual_edge_http(error)


def _raise_oracle_mission_http(error):
    status_code = 500
    if isinstance(error, MissionValidationError):
        status_code = 422
    elif isinstance(error, MissionConflictError):
        status_code = 409
    elif isinstance(error, MissionNotFoundError):
        status_code = 404
    elif isinstance(error, MissionStateUnavailableError):
        status_code = 503
    elif isinstance(error, MissionEvaluationUnavailableError):
        status_code = 503
    elif isinstance(error, MissionPlanUnavailableError):
        status_code = 422
    detail = {"code": error.code, "message": str(error)}
    if getattr(error, "reasons", None):
        detail["reasons"] = list(error.reasons)
    raise HTTPException(
        status_code=status_code,
        detail=detail,
    ) from error


@app.post("/v1/oracle/missions", status_code=201)
def start_oracle_mission(request: MissionStartRequest):
    try:
        return oracle_mission_service.start(**request.model_dump())
    except (
        MissionValidationError,
        MissionConflictError,
        MissionStateUnavailableError,
    ) as error:
        _raise_oracle_mission_http(error)


@app.get("/v1/oracle/missions")
def recent_oracle_missions(limit: int = 25):
    try:
        return {
            "missions": oracle_mission_service.recent(limit),
            "state": oracle_mission_service.state_status(),
        }
    except MissionStateUnavailableError as error:
        _raise_oracle_mission_http(error)


@app.get("/v1/oracle/missions/active")
def active_oracle_mission():
    try:
        return {
            "mission": oracle_mission_service.active(),
            "state": oracle_mission_service.state_status(),
        }
    except MissionStateUnavailableError as error:
        _raise_oracle_mission_http(error)


@app.get("/v1/oracle/missions/{mission_id}")
def get_oracle_mission(mission_id: str):
    try:
        return oracle_mission_service.get(mission_id)
    except (MissionNotFoundError, MissionStateUnavailableError) as error:
        _raise_oracle_mission_http(error)


@app.post("/v1/oracle/missions/{mission_id}/cancel")
def cancel_oracle_mission(mission_id: str):
    try:
        if oracle_paper_autopilot.has_active_execution(mission_id):
            raise MissionConflictError(
                "Oracle mission has an active Guardian; exit must be verified first"
            )
        return oracle_mission_service.cancel(mission_id)
    except (MissionNotFoundError, MissionStateUnavailableError) as error:
        _raise_oracle_mission_http(error)


@app.post("/v1/oracle/missions/{mission_id}/evaluate")
def evaluate_oracle_mission(mission_id: str):
    try:
        snapshot = _oracle_compatibility_dashboard()
        return oracle_mission_service.evaluate(mission_id, snapshot)
    except (
        MissionValidationError,
        MissionConflictError,
        MissionEvaluationUnavailableError,
        MissionNotFoundError,
        MissionStateUnavailableError,
    ) as error:
        _raise_oracle_mission_http(error)
    except RuntimeError as error:
        reasons = ("V2_SNAPSHOT_UNAVAILABLE",)
        try:
            oracle_mission_service.fail_evaluation(
                mission_id,
                terminal_reason=reasons[0],
                unavailable_reasons=reasons,
                message=str(error),
            )
        except MissionNotFoundError:
            pass
        except MissionStateUnavailableError as state_error:
            _raise_oracle_mission_http(state_error)
        _raise_oracle_mission_http(
            MissionEvaluationUnavailableError(
                "Cached V2 snapshot is unavailable",
                reasons,
            )
        )


@app.post("/v1/oracle/missions/{mission_id}/plan")
def plan_oracle_mission(
    mission_id: str,
    request: MissionPlanRequest = MissionPlanRequest(),
):
    try:
        snapshot = _oracle_compatibility_dashboard()
        return oracle_mission_service.plan(
            mission_id,
            snapshot,
            requested_quantity=request.requested_quantity,
        )
    except (
        MissionValidationError,
        MissionConflictError,
        MissionEvaluationUnavailableError,
        MissionPlanUnavailableError,
        MissionNotFoundError,
        MissionStateUnavailableError,
    ) as error:
        _raise_oracle_mission_http(error)
    except RuntimeError:
        _raise_oracle_mission_http(
            MissionPlanUnavailableError(
                "Cached V2 snapshot is unavailable",
                ("V2_SNAPSHOT_UNAVAILABLE",),
            )
        )


@app.post("/v1/oracle/missions/{mission_id}/paper-execute")
def execute_oracle_mission(mission_id: str):
    try:
        return oracle_paper_autopilot.execute(mission_id)
    except OracleExecutionBlocked as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "message": str(error)},
        ) from error
    except OracleExecutionUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail={"code": error.code, "message": str(error)},
        ) from error


@app.post("/v1/oracle/missions/{mission_id}/exit")
def exit_oracle_mission(mission_id: str):
    try:
        return oracle_paper_autopilot.exit(mission_id)
    except OracleExecutionBlocked as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "message": str(error)},
        ) from error
    except OracleExecutionUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail={"code": error.code, "message": str(error)},
        ) from error


@app.get("/v1/oracle/missions/{mission_id}/guardian")
def oracle_mission_guardian(mission_id: str):
    try:
        return oracle_paper_autopilot.guardian(mission_id)
    except OracleExecutionBlocked as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "message": str(error)},
        ) from error
    except OracleExecutionUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail={"code": error.code, "message": str(error)},
        ) from error


def _raise_demo_tour_http(error: Exception):
    raise HTTPException(
        status_code=409,
        detail={"code": "ORACLE_DEMO_TOUR_BLOCKED", "message": str(error)},
    ) from error


@app.post("/v1/oracle/demo-tour/start")
def start_oracle_demo_tour():
    try:
        return demo_tour.start()
    except (DemoTourError, MissionConflictError) as error:
        _raise_demo_tour_http(error)


@app.get("/v1/oracle/demo-tour")
def oracle_demo_tour_status():
    return demo_tour.status()


@app.post("/v1/oracle/demo-tour/next")
def plan_oracle_demo_trade():
    try:
        return demo_tour.plan_next()
    except (DemoTourError, MissionConflictError, MissionPlanUnavailableError) as error:
        _raise_demo_tour_http(error)


@app.post("/v1/oracle/demo-tour/execute")
def execute_oracle_demo_trade():
    try:
        return demo_tour.execute()
    except (DemoTourError, OracleExecutionBlocked, OracleExecutionUnavailable) as error:
        _raise_demo_tour_http(error)


@app.get("/v1/oracle/demo-tour/guardian")
def oracle_demo_guardian():
    try:
        return demo_tour.guardian()
    except (DemoTourError, OracleExecutionBlocked, OracleExecutionUnavailable) as error:
        _raise_demo_tour_http(error)


@app.post("/v1/oracle/demo-tour/exit")
def exit_oracle_demo_trade():
    try:
        return demo_tour.exit()
    except (DemoTourError, OracleExecutionBlocked, OracleExecutionUnavailable) as error:
        _raise_demo_tour_http(error)


@app.get("/v1/personal-oracle/status")
def personal_oracle_status():
    return personal_oracle_service.status()


@app.get("/v1/personal-oracle/summary")
def personal_oracle_summary():
    return personal_oracle_service.summary()


@app.get("/v1/personal-oracle/findings")
def personal_oracle_findings():
    return personal_oracle_service.findings()


@app.get("/v1/personal-oracle/segments")
def personal_oracle_segments():
    return personal_oracle_service.segments()


@app.get("/v1/personal-oracle/recommendations")
def personal_oracle_recommendations():
    return personal_oracle_service.recommendations()


@app.get("/v1/personal-oracle/events")
def personal_oracle_events(limit: int = 25):
    return personal_oracle_service.events(limit)


@app.get("/v1/personal-oracle/behavior")
def personal_oracle_behavior():
    return personal_oracle_service.behavior()


@app.get("/v1/personal-oracle/coaching")
def personal_oracle_coaching():
    return personal_oracle_service.coaching()


@app.get("/v1/personal-oracle/scorecard")
def personal_oracle_scorecard():
    return personal_oracle_service.scorecard()


@app.get("/v1/personal-oracle/trends")
def personal_oracle_trends():
    return personal_oracle_service.trends()


@app.get("/v1/personal-oracle/mistakes")
def personal_oracle_mistakes():
    return personal_oracle_service.mistakes()


@app.get("/v1/aegis/status")
def aegis_status():
    return aegis_service.status()


@app.get("/v1/aegis/assessment/{symbol}")
def aegis_assessment(symbol: str, requested_side: str = "NONE", strategy_id: str = "simple_pullback"):
    decision = aegis_service.latest_advisory(symbol, requested_side, strategy_id)
    return {"status": "available" if decision.get("input_status") != "UNAVAILABLE" else "unavailable",
            "input": decision.get("input_snapshot"), "decision": decision}


@app.get("/v1/aegis/decision/{symbol}")
def aegis_decision(symbol: str, requested_side: str = "NONE", strategy_id: str = "simple_pullback"):
    return aegis_service.latest_advisory(symbol, requested_side, strategy_id)


@app.get("/v1/aegis/conflicts/{symbol}")
def aegis_conflicts(symbol: str, requested_side: str = "NONE", strategy_id: str = "simple_pullback"):
    return aegis_service.conflicts(symbol, requested_side, strategy_id)


@app.get("/v1/aegis/history")
def aegis_history(limit: int = 25):
    return aegis_service.history(limit)


@app.get("/v1/aegis/strategy-eligibility/{strategy_id}")
def aegis_strategy_eligibility(strategy_id: str, symbol: str = "NIFTY", timeframe: str = "5m"):
    session = market_calendar.status()
    return strategy_eligibility(strategy_id, symbol.upper(), timeframe, session["session_state"]).to_dict()


@app.get("/v1/system/open-market-readiness")
def open_market_readiness():
    return readiness_service.assess()


@app.get("/v1/system/next-session-plan")
def next_session_plan():
    return readiness_service.next_session_plan()


@app.get("/v1/orders/status")
def orders_status():
    return order_fill_ledger.status()


@app.get("/v1/orders")
def orders(limit: int = 50, state: str | None = None):
    try:
        return order_fill_ledger.list_orders(limit=limit, state=state)
    except Exception as error:
        raise HTTPException(status_code=503, detail="ORDER_LEDGER_UNAVAILABLE") from error


@app.get("/v1/orders/integrity")
def orders_integrity():
    return order_fill_ledger.integrity()


@app.get("/v1/orders/{intent_id}")
def order_detail(intent_id: str):
    try:
        return order_fill_ledger.get_order(intent_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="ORDER_INTENT_NOT_FOUND") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="ORDER_LEDGER_UNAVAILABLE") from error


@app.get("/v1/orders/{intent_id}/events")
def order_events(intent_id: str, limit: int = 100):
    try:
        order_fill_ledger.get_order(intent_id)
        return order_fill_ledger.events(intent_id, limit)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="ORDER_INTENT_NOT_FOUND") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="ORDER_LEDGER_UNAVAILABLE") from error


@app.get("/v1/orders/{intent_id}/fills")
def order_fills(intent_id: str, limit: int = 100):
    try:
        order_fill_ledger.get_order(intent_id)
        return order_fill_ledger.fills(intent_id, limit)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="ORDER_INTENT_NOT_FOUND") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="ORDER_LEDGER_UNAVAILABLE") from error


@app.get("/v1/orders/{intent_id}/costs")
def order_costs(intent_id: str):
    try: return order_fill_ledger.cost_summary(intent_id)
    except KeyError as error: raise HTTPException(status_code=404, detail="ORDER_INTENT_NOT_FOUND") from error
    except Exception as error: raise HTTPException(status_code=503, detail="ORDER_LEDGER_UNAVAILABLE") from error


@app.get("/v1/orders/{intent_id}/slippage")
def order_slippage(intent_id: str):
    try: return order_fill_ledger.slippage_summary(intent_id)
    except KeyError as error: raise HTTPException(status_code=404, detail="ORDER_INTENT_NOT_FOUND") from error
    except Exception as error: raise HTTPException(status_code=503, detail="ORDER_LEDGER_UNAVAILABLE") from error


@app.get("/v1/fills")
def fills(limit: int = 100):
    try: return order_fill_ledger.fills(limit=limit)
    except Exception as error: raise HTTPException(status_code=503, detail="ORDER_LEDGER_UNAVAILABLE") from error


@app.get("/v1/fills/{fill_id}")
def fill_detail(fill_id: str):
    try: return order_fill_ledger.get_fill(fill_id)
    except KeyError as error: raise HTTPException(status_code=404, detail="FILL_NOT_FOUND") from error
    except Exception as error: raise HTTPException(status_code=503, detail="ORDER_LEDGER_UNAVAILABLE") from error


@app.get("/v1/paper-trading/status")
def paper_trading_status():
    return paper_trading_orchestrator.status()


@app.get("/v1/paper-trading/readiness")
def paper_trading_readiness():
    return paper_trading_orchestrator.readiness()


@app.get("/v1/paper-trading/strategies")
def paper_trading_strategies():
    return paper_trading_orchestrator.registry.projection()


@app.get("/v1/paper-trading/timeline")
def paper_trading_timeline(limit: int = 50):
    return paper_trading_orchestrator.timeline(limit)


@app.get("/v1/paper-trading/position")
def paper_trading_position():
    return paper_trading_orchestrator.position()


@app.get("/v1/paper-trading/pnl")
def paper_trading_pnl():
    return paper_trading_orchestrator.pnl()


@app.get("/v1/paper-trading/dashboard")
def paper_trading_dashboard():
    return paper_trading_orchestrator.dashboard()


@app.get("/v1/oracle/assessment/{symbol}")
def oracle_assessment(symbol: str):
    try:
        return oracle_service.assess(symbol).to_dict()
    except UnsupportedOracleSymbol as error:
        raise HTTPException(
            status_code=404,
            detail={
                "status": "unavailable",
                "error": {
                    "code": "UNSUPPORTED_SYMBOL",
                    "message": str(error),
                },
            },
        ) from error


@app.get("/v1/athena/wheel")
def athena_wheel():
    assessment = athena_service.assess()
    return {
        "risk_state": assessment.risk_state,
        "daily_drawdown": assessment.current_drawdown,
        "max_daily_loss": assessment.daily_loss_limit,
        "position_size": None,
        "kill_switch": (
            True
            if "KILL_SWITCH_ACTIVE" in assessment.reason_codes
            else False
            if assessment.source_metadata.risk_state_health == "HEALTHY"
            else None
        ),
        "notes": [assessment.explanation, *assessment.warnings],
    }


@app.get("/v1/athena/status")
def athena_status():
    return athena_service.assess().to_dict()


@app.get("/v1/hermes/status")
def hermes_status():
    return hermes_service.assessment().to_dict()


@app.get("/v1/hermes/events")
def hermes_events():
    return hermes_service.events_payload()


@app.get("/v1/ai/insights")
def ai_insights():
    data = dashboard.snapshot()
    analytics = data.get("analytics", {}).get("summary", {})
    optimizer = data.get("optimizer", {}).get("suggestions", [])

    insights = []

    for suggestion in optimizer[:5]:
        if not suggestion.get("message"):
            continue
        insights.append({
            "source": "Optimizer",
            "title": suggestion.get("type", "Insight"),
            "message": suggestion.get("message", ""),
            "severity": suggestion.get("priority", "LOW"),
            "timestamp": None,
        })

    return insights


@app.get("/v1/performance/equity")
def performance_equity():
    return []


@app.get("/v1/performance/distribution")
def performance_distribution():
    summary = dashboard.snapshot().get("journal_summary", {})
    wins = summary.get("wins", 0)
    losses = summary.get("losses", 0)

    return [
        {"bucket": "Wins", "wins": wins, "losses": 0},
        {"bucket": "Losses", "wins": 0, "losses": losses},
    ]


@app.get("/v1/performance/heatmap")
def performance_heatmap():
    return {
        "status": "unavailable",
        "reason": "AUTHORITATIVE_DAILY_EQUITY_SERIES_UNAVAILABLE",
        "days": [], "weeks": [], "values": [],
    }


# --- ORACLE DEVELOPMENT ROUTES ---

from src.oracle_development import (
    MissionValidationError as DevMissionValidationError,
    MissionConflictError as DevMissionConflictError,
    MissionNotFoundError as DevMissionNotFoundError,
)

def _raise_dev_mission_http(error):
    status_code = 500
    if isinstance(error, DevMissionValidationError):
        status_code = 422
    elif isinstance(error, DevMissionConflictError):
        status_code = 409
    elif isinstance(error, DevMissionNotFoundError):
        status_code = 404
    detail = {"code": getattr(error, "code", "ERROR"), "message": str(error)}
    raise HTTPException(
        status_code=status_code,
        detail=detail,
    ) from error

@app.get("/v1/oracle-development/status")
def oracle_dev_status():
    latest = oracle_dev_service.get_latest_assessments()
    return {
        "status": "active",
        "latest_assessments": latest,
        "last_updated": datetime.now(timezone.utc).isoformat()
    }

@app.get("/v1/oracle-development/reasoning")
def oracle_dev_reasoning():
    """Serve the producer-owned development assessment cache only.

    The Oracle page polls this route frequently.  Running candle ingestion,
    assessment, and paper-side effects from each request turned an aborted
    browser poll into work that continued in the backend and could contend
    with readiness and Fast Lane.  Assessment ownership remains with its
    controlled producer/explicit mission evaluation path; this presentation
    route is deliberately a side-effect-free cache read.
    """

    return oracle_dev_service.get_latest_assessments()


@app.post("/v1/oracle-development/missions", status_code=201)
def start_dev_mission(request: MissionStartRequest):
    try:
        return oracle_dev_service.missions.start(**request.model_dump())
    except (DevMissionValidationError, DevMissionConflictError) as error:
        _raise_dev_mission_http(error)

@app.get("/v1/oracle-development/missions")
def recent_dev_missions(limit: int = 25):
    return {
        "missions": oracle_dev_service.missions.recent(limit),
        "state": "active"
    }

@app.get("/v1/oracle-development/missions/active")
def active_dev_mission(timeframe: Optional[str] = None):
    return {
        "mission": oracle_dev_service.missions.active(timeframe),
        "state": "active"
    }

@app.get("/v1/oracle-development/chart-data")
def active_dev_chart_data(timeframe: str = "3m", stale: bool = False, force: bool = False):
    # A force request wakes the existing producer.  It never performs Dhan I/O,
    # price-action analysis, history copying, hashing, or serialization here.
    if force:
        oracle_dev_service.request_chart_refresh()
    snapshot = oracle_dev_service.chart_data_snapshot(timeframe)
    body = snapshot.stale_encoded_bytes if stale else snapshot.encoded_bytes
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "X-Oracle-Chart-Revision": str(snapshot.revision),
            "X-Oracle-Chart-Published-At": snapshot.published_at,
        },
    )

@app.post("/v1/oracle-development/sync")
def sync_dev_data(timeframe: str = "3m"):
    try:
        oracle_dev_service.refresh_market_data_if_due(force=True)
        return {"status": "success", "message": "Synchronized market data stream"}
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail={"code": "SYNC_ERROR", "message": str(error)}
        )

@app.get("/v1/oracle-development/missions/{mission_id}")
def get_dev_mission(mission_id: str):
    try:
        return oracle_dev_service.missions.get(mission_id)
    except DevMissionNotFoundError as error:
        _raise_dev_mission_http(error)

@app.post("/v1/oracle-development/missions/{mission_id}/cancel")
def cancel_dev_mission(mission_id: str):
    try:
        return oracle_dev_service.missions.cancel(mission_id)
    except DevMissionNotFoundError as error:
        _raise_dev_mission_http(error)

@app.post("/v1/oracle-development/missions/{mission_id}/evaluate")
def evaluate_dev_mission(mission_id: str):
    try:
        assessments = oracle_dev_service.assess_and_execute()
        lane = assessments.get("3m")
        scores = lane.get("scores") if lane else {}
        return oracle_dev_service.missions.evaluate(mission_id, scores)
    except (DevMissionValidationError, DevMissionNotFoundError) as error:
        _raise_dev_mission_http(error)

@app.post("/v1/oracle-development/missions/{mission_id}/plan")
def plan_dev_mission(mission_id: str, request: MissionPlanRequest = MissionPlanRequest()):
    try:
        assessments = oracle_dev_service.get_latest_assessments()
        lane = assessments.get("3m")
        plan_data = lane.get("plan") if lane else {}
        return oracle_dev_service.missions.plan(mission_id, plan_data)
    except (DevMissionValidationError, DevMissionNotFoundError) as error:
        _raise_dev_mission_http(error)

@app.post("/v1/oracle-development/missions/{mission_id}/paper-execute")
def execute_dev_mission(mission_id: str):
    try:
        assessments = oracle_dev_service.get_latest_assessments()
        lane = "3m"
        lane_assess = assessments.get(lane)
        plan_data = lane_assess.get("plan") if lane_assess else {}

        spot_price = float(lane_assess["lane_status"]["last_spot"]["close"]) if lane_assess and lane_assess.get("lane_status") and lane_assess["lane_status"].get("last_spot") else 24000.0
        options_info = oracle_dev_service.resolver.resolve_options(spot_price, "NIFTY")
        direction = plan_data.get("direction") or "CALL"
        contract_key = "ATM_CE" if direction == "CALL" else "ATM_PE"
        resolved_contract = options_info.get(contract_key)

        if not resolved_contract:
            raise DevMissionValidationError("Resolved options contract not found")

        opt_price = spot_price
        opt_candles = lane_assess.get("lane_status", {}).get("last_option", {}).get(contract_key)
        if opt_candles:
            opt_price = float(opt_candles["close"])

        oracle_dev_service.autopilot.trigger_setup_detected(
            lane=lane,
            setup_family=lane_assess.get("setup_family") or "PA Breakout",
            direction=direction,
            scores=lane_assess.get("scores") or {},
            plan_data=plan_data
        )
        return oracle_dev_service.autopilot.execute_paper_order(
            lane=lane,
            mission_id=mission_id,
            contract=resolved_contract,
            direction=direction,
            lots=plan_data.get("approved_lots") or 1,
            price=opt_price
        )
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail={"code": "EXECUTION_ERROR", "message": str(error)}
        )

@app.post("/v1/oracle-development/missions/{mission_id}/exit")
def exit_dev_mission(mission_id: str):
    try:
        lane = "3m"
        lane_status = oracle_dev_service.autopilot.get_lane_status(lane)
        pos = lane_status.get("position")
        if pos and pos["mission_id"] == mission_id:
            opt_price = pos["entry_price"]
            last_opt = lane_status.get("last_option", {})
            contract_key = "ATM_CE" if pos["direction"] == "CALL" else "ATM_PE"
            if last_opt and last_opt.get(contract_key):
                opt_price = float(last_opt[contract_key]["close"])

            qty = pos["quantity"]
            pos["exit_price"] = opt_price
            pos["exit_time"] = datetime.now(timezone.utc).isoformat()
            pos["status"] = "CLOSED"
            pos["exit_reason"] = "MANUAL_EXIT"
            pos["pnl"] = (pos["exit_price"] - pos["entry_price"]) * qty - pos["commission"]

            oracle_dev_service.autopilot._update_stats(pos)
            oracle_dev_service.missions.cancel(mission_id, outcome="MANUAL_EXIT")

            lane_status["position"] = None
            lane_status["state"] = "CLOSED"
            lane_status["active_setup"] = None
            oracle_dev_service.autopilot._persist()
            return pos
        else:
            raise DevMissionNotFoundError("Active position not found for mission")
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail={"code": "EXIT_ERROR", "message": str(error)}
        )

@app.get("/v1/oracle-development/missions/{mission_id}/guardian")
def dev_mission_guardian(mission_id: str):
    lane = "3m"
    lane_status = oracle_dev_service.autopilot.get_lane_status(lane)
    return {
        "mission_id": mission_id,
        "guardian_action": lane_status.get("guardian_action") or "Monitoring",
        "guardian_reason": lane_status.get("guardian_reason") or "Ready",
        "state": lane_status.get("state") or "IDLE"
    }


@app.get("/v1/oracle-development/guardian")
def oracle_dev_guardian_aggregate():
    """Aggregate Guardian state across all three 1m / 3m / 5m lanes."""
    lanes = {}
    for tf in ("1m", "3m", "5m"):
        ls = oracle_dev_service.autopilot.get_lane_status(tf)
        lanes[tf] = {
            "state": ls.get("state", "IDLE"),
            "guardian_action": ls.get("guardian_action", "Monitoring"),
            "guardian_reason": ls.get("guardian_reason", "No active position"),
            "position": ls.get("position"),
            "balance": ls.get("balance"),
        }
    return {
        "mode": "PAPER_ONLY",
        "live_blocked": True,
        "lanes": lanes,
    }


@app.get("/v1/oracle-development/ledger")
def oracle_dev_ledger():
    """Virtual paper ledger: balance, pnl, trade history across all lanes."""
    lanes = {}
    total_net_pnl = 0.0
    total_trades = 0
    for tf in ("1m", "3m", "5m"):
        ls = oracle_dev_service.autopilot.get_lane_status(tf)
        history = ls.get("position_history") or []
        lane_pnl = sum(p.get("pnl", 0.0) for p in history)
        lanes[tf] = {
            "balance": ls.get("balance", 1000000.0),
            "net_pnl": lane_pnl,
            "trade_count": len(history),
            "last_5_trades": history[-5:] if history else [],
        }
        total_net_pnl += lane_pnl
        total_trades += len(history)
    return {
        "mode": "PAPER_ONLY",
        "virtual_capital_per_lane": 1000000.0,
        "total_net_pnl": round(total_net_pnl, 2),
        "total_trades": total_trades,
        "lanes": lanes,
    }
