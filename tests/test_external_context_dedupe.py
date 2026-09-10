import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.external_context.core import ExternalContextCore
from src.external_context.contracts import ExternalEvent, VerificationTier


class TestExternalContextDedupe(unittest.TestCase):
    def test_twenty_repeated_headlines_deduplicated_to_one(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            core = ExternalContextCore(ledger_dir=Path(tmp_dir))
            core.clear()

        # 20 repeated identical headlines across different polling ticks
        raw_headline = "RBI announces overnight VRRR auction under LAF window"
        registered_count = 0
        for i in range(20):
            evt = ExternalEvent.create(
                provider="rbi",
                source_name="Reserve Bank of India",
                source_url=f"https://rbi.org.in/pr_{i}.html",
                published_at=datetime.now(timezone.utc).isoformat(),
                event_type="REGULATORY_CIRCULAR",
                headline=raw_headline,
                summary=f"Variable rate reverse repo auction details tick {i}.",
                entities=["RBI", "VRRR"],
                country="IN",
                market_tags=["RBI", "MONETARY_POLICY"],
                verification_tier=VerificationTier.TIER_A_OFFICIAL.value,
            )
            if core._register_event(evt):
                registered_count += 1

        events = core.get_latest_events()
        self.assertEqual(registered_count, 1)
        self.assertEqual(len(events), 1)
        self.assertIn("VRRR", events[0].headline)


if __name__ == "__main__":
    unittest.main()
