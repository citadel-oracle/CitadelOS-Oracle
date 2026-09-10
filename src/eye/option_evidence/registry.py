"""Option Evidence Registry for Eye Engine Phase E4A."""

from typing import Dict, List, Optional
from src.eye.option_evidence.evidence_record import OptionEvidenceRecord


class OptionEvidenceRegistry:
    def __init__(self):
        self._by_evidence_id: Dict[str, OptionEvidenceRecord] = {}
        self._by_setup_key: Dict[str, List[OptionEvidenceRecord]] = {}

    def register(self, record: OptionEvidenceRecord):
        self._by_evidence_id[record.evidence_id] = record
        if record.evidence_link:
            s_key = record.evidence_link.setup_key
            if s_key not in self._by_setup_key:
                self._by_setup_key[s_key] = []
            self._by_setup_key[s_key].append(record)

    def get_by_evidence_id(self, evidence_id: str) -> Optional[OptionEvidenceRecord]:
        return self._by_evidence_id.get(evidence_id)

    def get_by_setup_key(self, setup_key: str) -> List[OptionEvidenceRecord]:
        return self._by_setup_key.get(setup_key, [])
