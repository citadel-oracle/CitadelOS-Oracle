from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "citadel-dashboard" / "src"
PAGE = FRONTEND / "app" / "page.tsx"
PROVIDER = FRONTEND / "dashboard" / "providers" / "RestDashboardProvider.ts"
CONTEXT = FRONTEND / "dashboard" / "contexts" / "DashboardContext.tsx"
SELECTORS = FRONTEND / "dashboard" / "selectors" / "index.ts"


def assert_centralized_feed(selector: str, backend_key: str) -> None:
    page = PAGE.read_text(encoding="utf-8")
    provider = PROVIDER.read_text(encoding="utf-8")
    selectors = SELECTORS.read_text(encoding="utf-8")
    assert f"useDashboardSelector(feedSelectors.{selector})" in page
    assert f"'{backend_key}'" in selectors
    assert "/v2/dashboard?symbol=${encodeURIComponent(this.symbol)}" in provider
    assert "fetch(" not in page


def assert_single_centralized_polling_loop() -> None:
    provider = PROVIDER.read_text(encoding="utf-8")
    context = CONTEXT.read_text(encoding="utf-8")
    assert provider.count("fetch(") == 1
    assert "if (this.running) return" in provider
    assert "if (this.inFlight)" in provider
    assert "setTimeout(() => void this.load()" in provider
    assert "clearTimeout(this.timer)" in provider
    assert "this.controller?.abort()" in provider
    assert "useEffect(() => { store.start(); return () => store.stop() }" in context


def assert_last_good_stale_recovery() -> None:
    provider = PROVIDER.read_text(encoding="utf-8")
    assert "private lastSnapshot" in provider
    assert "this.lastSnapshot =" in provider
    assert "health: 'STALE'" in provider
    assert "readiness: 'DEGRADED'" in provider
    assert "cachedProjectionStale" in provider
    assert "this.publish(stale)" in provider
