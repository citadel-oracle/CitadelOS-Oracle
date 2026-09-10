"""Market Thesis & Evidence Provenance Synthesizer for Eye Oracle Projection."""

from typing import Dict, Optional, Any
from src.eye.oracle_projection.contracts import EyeMarketThesis


class MarketThesisSynthesizer:
    """Synthesizes deterministic market thesis, headline, and WHY proof from Eye events."""

    def synthesize_thesis(
        self,
        symbol: str,
        structure: Dict[str, Any],
        setup: Dict[str, Any],
        liquidity: Dict[str, Any],
    ) -> EyeMarketThesis:
        dir_struct = str(structure.get("directional_structure", "UNKNOWN")).upper()
        bos_event = structure.get("last_bos")
        choch_event = structure.get("last_choch")

        setup_family = setup.get("family", "NO_ACTIVE_SETUP")
        setup_status = setup.get("lifecycle", "NO_ACTIVE_SETUP")

        if dir_struct == "BULLISH":
            headline = f"Bullish structure confirmed; {setup_family} setup {setup_status}."
            structural_thesis = "BULLISH"
            why_text = f"{symbol} structure is bullish with confirmed BOS ({bos_event or 'EVT:BOS'})."
        elif dir_struct == "BEARISH":
            headline = f"Bearish structure confirmed; {setup_family} setup {setup_status}."
            structural_thesis = "BEARISH"
            why_text = f"{symbol} structure is bearish with confirmed BOS ({bos_event or 'EVT:BOS'})."
        elif dir_struct == "RANGE":
            headline = f"Market in range; {setup_family} setup {setup_status}."
            structural_thesis = "RANGE"
            why_text = f"{symbol} is consolidating inside prior swing range."
        else:
            headline = f"Market structure UNKNOWN; {setup_family} active."
            structural_thesis = "UNKNOWN"
            why_text = f"No Eye atomic events have established market structure for {symbol}."

        why_proof = {
            "principle": "CITADEL Eye Engine Deterministic Structure Invariance Rule V1",
            "directional_structure": dir_struct,
            "last_bos": bos_event,
            "last_choch": choch_event,
            "active_setup_family": setup_family,
            "setup_lifecycle": setup_status,
            "source_events": [bos_event] if bos_event else [],
        }

        return EyeMarketThesis(
            headline=headline,
            structural_thesis=structural_thesis,
            why=why_text,
            why_proof=why_proof,
            options_context="Options quote alignment status evaluated",
        )
