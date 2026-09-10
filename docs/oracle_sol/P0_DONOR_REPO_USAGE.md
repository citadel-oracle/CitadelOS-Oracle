# CITADEL ORACLE SOL MARKET BRAIN — P0 DONOR REPO USAGE & ACCOUNTABILITY
## COMPREHENSIVE COVERAGE LEDGER OF ALL 8 DONOR REPOSITORIES

> **Coverage Standard**: 100% of Donor Repositories Formally Accounted For.  
> **Date**: August 30, 2026

---

## 1. DONOR REPOSITORY ACCOUNTABILITY TABLE

| # | Donor Repository | Exact Source Concept Audited | Status in P0 | CITADEL Module Using Concept | Forensic Rationale |
| :- | :--- | :--- | :--- | :--- | :--- |
| 1 | **TradingAgents** | Structured Adversarial Debate (Bull vs Bear vs No-Trade) | `ADAPTED (CITADEL-NATIVE)` | `src/oracle_sol/reasoning_protocol.py` | Adapted into a single-model 9-pass reasoning protocol (Passes 3–6) to eliminate multi-agent chat latency while retaining adversarial rigor. |
| 2 | **FinRobot** | Strict Deterministic Compute vs LLM Reasoning Boundary | `ADOPTED DIRECTLY` | `src/oracle_sol/provenance_guard.py` & `contracts.py` | Locked foundational principle: CITADEL calculates all metrics; Sol only interprets. Missing metrics are marked UNAVAILABLE. |
| 3 | **Vibe-Trading** | Shadow Account, Immutable Reasoning Ledger, Run Cards | `ADAPTED (CITADEL-NATIVE)` | `src/oracle_sol/shadow_ledger.py` & `replay.py` | Reimplemented natively in Python & DuckDB to store every reasoning cycle and pre-registered counterfactual expectation. |
| 4 | **Qlib** | Information Coefficient (Rank IC) & Feature Ablation Suite | `DEFERRED TO P1/P2` | `docs/oracle_sol/P0_VALIDATION_REPORT.md` | P0 establishes the clean data schemas and Shadow Ledger. Full statistical Rank IC scoring suite scheduled for P1/P2. |
| 5 | **RD-Agent** | Automated Bounded Research Loop | `DEFERRED (HUMAN-APPROVAL GUARD)` | `docs/oracle_sol/P0_VALIDATION_REPORT.md` | Live rule changes remain strictly human-approved. Shadow Ledger provides the data foundation for future offline experiments. |
| 6 | **QuantDinger** | Long-Running Worker Isolation, Heartbeat, Restart Safety | `ADAPTED (CITADEL-NATIVE)` | `src/oracle_sol/worker.py` | Adapted into `SolMarketBrainWorker` with background thread isolation, queue coalescing, and non-blocking execution. |
| 7 | **AI-Trader** | Champion / Challenger Model Tournament Framework | `ADAPTED (SCHEMA READY)` | `src/oracle_sol/contracts.py` & `shadow_ledger.py` | P0 logs model identifier, prompt version, and schema version to support future champion/challenger comparisons. Social copy-trading rejected. |
| 8 | **ValueCell** | Multi-Provider LLM Fallback Routing & Context Store | `REVIEWED & ACCOUNTED (ZERO PROD CODE IN P0)` | `src/oracle_sol/model_adapter.py` | Reviewed. Existing CITADEL FastAPI and Python abstractions are cleaner. Redundant ValueCell dependencies rejected. |
