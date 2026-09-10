import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "citadel-dashboard/src/components/institutional/OracleWorkspacePanel.tsx"
ARGUS_PROJECTION = ROOT / "citadel-dashboard/src/components/institutional/oracleArgusProjection.ts"


def panel_source() -> str:
    return PANEL.read_text(encoding="utf-8")


def argus_surface() -> str:
    panel = panel_source()
    return panel[panel.index("id: 'argus'"):panel.index("id: 'vob'")]


def run_projection(overrides: str = "") -> dict:
    module_uri = ARGUS_PROJECTION.as_uri()
    script = f"""
      const {{ buildArgusProviderProjection }} = await import({json.dumps(module_uri)});
      const rows = [24200, 24250, 24300, 24350, 24400, 24450, 24500].map((strike, index) => ({{
        strike,
        CE: {{ security_id: 100 + index * 2, load_intensity: 30 + index, probable_flow: 'CALL_WRITING' }},
        PE: {{ security_id: 101 + index * 2, load_intensity: 40 + index, probable_flow: 'PUT_WRITING' }},
      }}));
      const spine = rows.map((row, index) => ({{
        strike: row.strike,
        CE: {{ load_intensity: index === 2 ? 91 : 30 + index }},
        PE: {{ load_intensity: index === 4 ? 92 : 40 + index }},
        is_atm: index === 3,
        is_probable_magnet: index === 4,
        is_strongest_pressure: index === 4,
        is_strongest_gamma: false,
        wall_types: [],
        breadth: index < 4 ? 'PUT' : 'CALL',
      }}));
      const input = {{
        envelope: {{ status: 'LIVE' }},
        tactical: {{
          status: 'LIVE', schema_version: 'argus-tactical-edge-3.0.0', symbol: 'NIFTY', expiry: '2026-08-04',
          source_event_time: null, receipt_timestamp: '2026-08-01T09:30:00+05:30',
          timestamp_semantics: 'RECEIPT_TIME_NO_PROVIDER_EVENT_TIME',
          source_timestamp: '2026-08-01T09:30:00+05:30', computed_snapshot_id: 'snapshot-1',
          pressure: {{ call_score: 44, put_score: 56, direction: 'PUT', strikes: rows }},
          breadth: {{ call_confirming_strikes: 2, put_confirming_strikes: 5 }},
          persistence: {{ direction: 'PUT', consecutive_confirmations: 2, required_count: 3 }},
          argus_prime: {{
            display_state: 'LIVE', direction: 'PUT', source_timestamp: '2026-08-01T09:30:00+05:30', snapshot_id: 'snapshot-1',
            strike_spine: spine, trigger: 'WAIT FOR RETEST', invalidation_text: 'LOSE 24350',
            recommended_contract: {{ trading_symbol: 'NIFTY260804P24400' }},
            tactical_summary: {{ title: 'BEARISH', state: 'PRESSURE PERSISTING' }},
            why: ['PUT pressure breadth and persistence agree.'],
            expiry_gamma_blast: {{ state: 'READY', chase_risk: 'LOW', wall: 24400, gamma_proxy: true }},
            best_strike_stack: {{ strike: 24400, wall: {{ magnet: true }} }},
            canonical_presentation: {{
              state: 'LIVE', verdict: 'PUT', producer_revision: 'ARGUS_PRIME_V3_AUDITABLE',
              snapshot_id: 'snapshot-1', source_event_time: null,
              observation_timestamp: '2026-08-01T09:30:00+05:30',
              compact_spine: [
                {{ label: 'ATM', strike: 24350, ce_load: 33, pe_load: 43, flow_state: 'PUT', structural_role: 'CURRENT ATM', ce_acceleration: null, pe_acceleration: null, ce_flow: null, pe_flow: null }},
                {{ label: 'LOWER', strike: 24300, ce_load: 91, pe_load: 42, flow_state: 'PUT', structural_role: 'STRONGEST LOWER', ce_acceleration: null, pe_acceleration: null, ce_flow: null, pe_flow: null }},
                {{ label: 'UPPER', strike: 24400, ce_load: 34, pe_load: 92, flow_state: 'CALL', structural_role: 'MAGNET + STRONGEST PRESSURE', ce_acceleration: null, pe_acceleration: null, ce_flow: null, pe_flow: null }},
              ],
              full_spine: spine.map((row, index) => ({{
                label: `STRIKE ${{row.strike}}`, strike: row.strike,
                ce_load: row.CE.load_intensity, pe_load: row.PE.load_intensity,
                flow_state: index < 4 ? 'PUT' : 'CALL', structural_role: index === 3 ? 'CURRENT ATM' : 'CHAIN STRIKE',
                ce_acceleration: null, pe_acceleration: null, ce_flow: null, pe_flow: null,
              }})),
              highest_load: {{ label: 'HIGHEST LOAD', strike: 24400, ce_load: 34, pe_load: 92, flow_state: 'CALL', structural_role: 'MAGNET + STRONGEST PRESSURE', ce_acceleration: null, pe_acceleration: null, ce_flow: null, pe_flow: null }},
              fastest_acceleration: {{ label: 'FASTEST ACCELERATION', strike: 24350, ce_load: 33, pe_load: 43, flow_state: 'PUT', structural_role: 'CURRENT ATM', ce_acceleration: null, pe_acceleration: null, ce_flow: null, pe_flow: null }},
              best_stack_strike: 24400, support_strike: null, resistance_strike: null,
              flow_type: 'BEARISH', gamma_strike: 24400, wall_magnet: {{ wall: 24400, magnet: 24400 }},
              gamma_blast: 'READY', proposed_contract: 'NIFTY260804P24400',
              canonical_read: 'BEARISH · PRESSURE PERSISTING', canonical_why: 'PUT pressure breadth and persistence agree.',
            }},
          }},
        }},
        exactContract: {{ security_id: '110', strike: 24450, option_side: 'CE', expiry: '2026-08-04' }},
        chartOption: {{ security_id: '110', expiry: '2026-08-04' }},
        currentUnderlying: 'NIFTY',
      }};
      {overrides}
      process.stdout.write(JSON.stringify(buildArgusProviderProjection(input)));
    """
    completed = subprocess.run(
        ["node", "--no-warnings", "--experimental-strip-types", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_argus_status_comes_from_argus_snapshot_not_exact_quote():
    panel = panel_source()
    assert "argusProvider.providerLineageAvailable" in panel
    assert "? argusProvider.state" in panel
    assert "const argusState = display(exactQuote.freshness_state" not in panel

    stale = run_projection("input.tactical.argus_prime.canonical_presentation.state = 'DEGRADED_STALE'; input.tactical.argus_prime.canonical_presentation.proposed_contract = null;")
    assert stale["state"] == "DEGRADED_STALE"
    assert stale["verdict"] == "PUT"
    assert stale["proposedContract"] == "NOT REPORTED"


def test_oracle_never_defaults_missing_vob_freshness_to_fresh():
    panel = panel_source()
    assert "vob.market_input_state : 'UNAVAILABLE'" in panel
    assert "vob.market_input_state : 'FRESH'" not in panel


def test_argus_exact_identity_is_verified_against_chain_leg_and_chart():
    matched = run_projection()
    assert matched["providerLineageAvailable"] is True
    assert matched["exactContractLineageAvailable"] is True
    assert matched["securityId"] == "110"
    assert matched["verdict"] == "PUT"

    mismatched = run_projection("input.chartOption.security_id = '999';")
    assert mismatched["providerLineageAvailable"] is True
    assert mismatched["exactContractLineageAvailable"] is False
    assert mismatched["securityId"] == "NOT REPORTED"

    inherited = run_projection("input.currentUnderlying = 'BANKNIFTY';")
    assert inherited["providerLineageAvailable"] is False
    assert inherited["callPressure"] is None
    assert inherited["putPressure"] is None
    assert inherited["fullSpine"] == []

    rolled = run_projection("input.chartOption.expiry = '2026-08-11';")
    assert rolled["providerLineageAvailable"] is False
    assert rolled["exactContractLineageAvailable"] is False
    assert rolled["verdict"] == "NOT REPORTED"
    assert rolled["callPressure"] is None


def test_argus_three_row_spine_is_deterministic_and_full_spine_stays_in_drawer():
    projection = run_projection()
    assert len(projection["compactSpine"]) == 3
    assert [row["label"] for row in projection["compactSpine"]] == ["ATM", "LOWER", "UPPER"]
    assert [row["strike"] for row in projection["compactSpine"]] == [24350, 24300, 24400]
    assert len(projection["fullSpine"]) == 7

    surface = argus_surface()
    for label in (
        "Three-strike decision spine",
        "Seven-strike quantitative spine",
    ):
        assert label in surface


def test_argus_card_exposes_provider_truth_without_becoming_decision_authority():
    surface = argus_surface()
    for label in (
        "Directional verdict",
        "Chain CE / PE pressure",
        "Breadth",
        "Persistence",
        "Wall / magnet",
        "Gamma / blast readiness",
        "Proposed best contract",
        "Chase risk",
        "CANONICAL READ",
        "WHY",
        "Instrument / security ID",
        "Expiry / timeframe",
        "Snapshot ID / producer revision",
        "Exact-contract lineage",
    ):
        assert label in surface

    for forbidden in ("Probability", "VIX", "Risk Control", "VOB", "OSE", "Strategy"):
        assert forbidden not in surface
    assert "BUY / WAIT / NO_TRADE" not in surface
    assert "liveDecision?.action" not in surface


def test_argus_refinement_preserves_six_card_geometry_and_existing_drawer():
    panel = panel_source()
    assert "type NodeId = 'thesis' | 'argus' | 'vob' | 'ose' | 'risk' | 'guardian'" in panel
    assert "function InspectionDrawer" in panel
    assert panel.count("title: 'Truth lineage'") == 6
    assert "ARGUS existing rank + canonical Dhan quote · tactical edge + canonical Dhan chain" in panel


def test_argus_frontend_is_presentation_only_and_uses_canonical_freshness():
    projection = ARGUS_PROJECTION.read_text(encoding="utf-8")
    panel = panel_source()

    for forbidden in ("directionalVerdict", "rowStrength", "const structuralRole ="):
        assert forbidden not in projection
    assert "prime.canonical_presentation" in projection
    assert "canonicalOracleFreshness" in panel
    assert "`${liveChart.freshness}" not in panel

    ose = (ROOT / "citadel-dashboard/src/components/institutional/OseFlagshipComponents.tsx").read_text(encoding="utf-8")
    options = (ROOT / "citadel-dashboard/src/components/institutional/OptionsStructurePanel.tsx").read_text(encoding="utf-8")
    assert "fallbackEdge" not in ose
    assert "compatibilitySsi" not in options
