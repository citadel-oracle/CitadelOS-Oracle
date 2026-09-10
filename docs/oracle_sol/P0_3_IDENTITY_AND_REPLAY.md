# CITADEL ORACLE SOL MARKET BRAIN — IDENTITY & EXACT REPLAY (P0.3)
## DETERMINISTIC SNAPSHOT IDS, REPLAY-STABLE EVENT IDS & BIT-EXACT INPUT PROOFS

> **Contract Version**: `3.0.0-p0.3`  
> **Module Path**: `src/oracle_sol/replay.py` & `src/oracle_sol/snapshot_extractor.py`

---

## 1. CANONICAL SNAPSHOT & EVENT IDENTITY

1. **Deterministic Snapshot ID**:
   * Derived from deterministic canonical seed:
     `snap_{sha256(session:timestamp:spot:fut:atm:source_hash)[:12]}`
   * Zero UUID, zero wall-clock jitter, zero process state dependency.
2. **Deterministic Event ID**:
   * Derived from stable snapshot seed, event type, instrument, and sequence:
     `evt_{snap_prefix}_{event_type}_{instrument}_{seq:02d}`
   * Identical input frame sequences produce identical event IDs and hashes bit-for-bit.

---

## 2. BIT-EXACT INPUT REPLAY PROOF

* Persists normalized `SolModelRequestEnvelope` containing `cycle_id`, `system_prompt`, `user_payload`, `configured_model`, and `input_hash`.
* Replay engine recomputes SHA-256 hash over normalized request bytes and verifies `original_input_hash == replayed_input_hash`.
