import json
from datetime import datetime
from threading import Lock
from time import monotonic
from zoneinfo import ZoneInfo

from src.scanner.market_scanner import MarketScanner
from src.execution.paper_execution import PaperExecution
from src.analytics.report_builder import AnalyticsReportBuilder
from src.optimizer.optimizer_engine import OptimizerEngine
from src.session.session_manager import SessionManager


class DashboardAPI:

    SNAPSHOT_TTL_SECONDS = 2.5

    def __init__(self):
        self.scanner = MarketScanner()
        self.execution = PaperExecution()
        self.analytics = AnalyticsReportBuilder()
        self.optimizer = OptimizerEngine()
        self.session = SessionManager()
        self.settings = self._load_settings()
        self._snapshot_cache = None
        self._snapshot_cached_at = 0.0
        self._snapshot_generated_at = None
        self._snapshot_lock = Lock()

    def snapshot(self):
        now = monotonic()
        if self._snapshot_cache is not None and now - self._snapshot_cached_at < self.SNAPSHOT_TTL_SECONDS:
            return self._snapshot_cache

        with self._snapshot_lock:
            now = monotonic()
            if self._snapshot_cache is not None and now - self._snapshot_cached_at < self.SNAPSHOT_TTL_SECONDS:
                return self._snapshot_cache

            rows = self.scanner.scan()
            strategy_config = self.scanner.strategy_manager.strategy_config()
            active_trade = self.execution.get_active_trade()

            snapshot = {
                "status": {
                    "system": "ONLINE",
                    "phase": "PHASE_4_DASHBOARD_OS",
                    "strategy": self.scanner.strategy_manager.strategy_name(),
                    "mode": self.settings.get("mode"),
                    "broker": self.settings.get("broker"),
                    "live_trading_enabled": self.settings.get("live_trading_enabled"),
                    "session": self.session.status(strategy_config),
                },
                "scanner": rows,
                "active_trade": active_trade,
                "journal_summary": self.execution.journal_summary(),
                "recent_trades": self.execution.recent_trades(10),
                "analytics": self.analytics.build(),
                "optimizer": self.optimizer.suggest(),
            }

            self._snapshot_cache = snapshot
            self._snapshot_cached_at = monotonic()
            self._snapshot_generated_at = datetime.now(
                ZoneInfo("Asia/Kolkata")
            )
            return snapshot

    def latest_snapshot(self):
        """Return the existing cache without triggering a scanner or broker call."""
        if self._snapshot_cache is None or self._snapshot_generated_at is None:
            return None
        return {
            "snapshot": self._snapshot_cache,
            "generated_at": self._snapshot_generated_at,
            "age_seconds": max(0.0, monotonic() - self._snapshot_cached_at),
        }

    @staticmethod
    def _load_settings():
        try:
            with open("config/settings.json", "r") as settings_file:
                return json.load(settings_file)
        except Exception:
            return {}
