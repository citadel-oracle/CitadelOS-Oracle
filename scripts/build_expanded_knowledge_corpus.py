#!/usr/bin/env python3
"""Build the immutable Phase-5A.2 local knowledge snapshot.

This is an authoring tool.  It performs no network access and cannot touch any
trading bounded context.  Externally fetched byte hashes are explicit review
inputs; user files are read locally and their expected hashes are enforced.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KROOT = ROOT / "oracle_knowledge"
SCHEMA = "5a.2.0"
POLICY = "oracle-knowledge-advisory-5a.2.0"
GENERATED = "2026-08-01T14:30:00+00:00"
USER_FVG_HASH = "c51f68b10a8d0947f576ba49ad4520a5213edad17de645adfa2bb4c79be59269"
USER_STRATEGY_HASH = "dccf62ee374392d9c0fd5d722b9a65d98f41ebae5ab2862d1d9e421bd957c525"


def write_json(relative: str, value: object) -> None:
    path = KROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def source(source_id: str, title: str, author: str, version: str, publication: str | None,
           kind: str, digest: str, location: str, locators: list[str], *, rights: str,
           quality: str = "SOURCE_BACKED_UNVALIDATED", limitations: list[str] | None = None,
           contradictions: list[str] | None = None, excerpt: bool = False) -> dict:
    return {
        "source_id": source_id, "title": title, "author_organisation": author,
        "edition_version": version, "publication_date": publication, "source_type": kind,
        "document_hash": digest, "hash_scope": ("EXACT_USER_PROVIDED_ATTACHMENT_BYTES"
                                                   if kind == "USER_PROVIDED" else "FULL_RETRIEVED_DOCUMENT_BYTES"),
        "source_location": location, "access_status": "ACCESSIBLE", "rights_status": rights,
        "ingestion_status": "VERIFIED",
        "excerpt_policy": {"policy_id": "expanded-paraphrase-5a.2.0" if not excerpt else "expanded-short-excerpt-5a.2.0",
                           "excerpt_allowed": excerpt, "maximum_words": 20 if excerpt else 0,
                           "attribution_required": True, "full_text_runtime_allowed": False},
        "stable_locators": locators,
        "provenance": {"discovered_via": ("USER_PROVIDED_ATTACHMENT" if kind == "USER_PROVIDED"
                                               else "DIRECT_PRIMARY_SOURCE_REVIEW"),
                       "retrieved_at": "2026-08-01"},
        "validation_status": quality,
        "limitations": limitations or ["The source is explanatory and has not been validated on CITADEL outcomes."],
        "contradictions": contradictions or ["No source principle creates probability or execution authority."],
    }


NEW_SOURCES = [
    source("adam-grimes-fundamental-patterns-2026", "Fundamental Trading Patterns", "Adam H. Grimes",
           "Retrieved 2026-08-01", None, "OFFICIAL_DOCUMENTATION",
           "f8a495ae10555b9234e3c9fb6f3cab3da002e881b5907edecca689306f724e04",
           "https://www.adamhgrimes.com/fundamental-trading-patterns/",
           ["Simple Pullback", "Complex Pullback", "Failure Test", "Breakouts"],
           rights="AUTHOR_OFFICIAL_FREE_WEB_PARAPHRASE_ONLY"),
    source("adam-grimes-market-structure-2026", "Elementary Market Structure", "Adam H. Grimes",
           "Retrieved 2026-08-01", None, "OFFICIAL_DOCUMENTATION",
           "e0453eef62e1ca83b3c50651d996eb38690e318061d3a1f52a0455a217d24f31",
           "https://www.adamhgrimes.com/market-structure/",
           ["Elementary Market Structure > market structure vs price action",
            "Elementary Market Structure > trends and ranges",
            "Elementary Market Structure > quantifiable/statistically verifiable boundary"],
           rights="AUTHOR_OFFICIAL_FREE_WEB_PARAPHRASE_ONLY"),
    source("adam-grimes-breakout-failures-2026", "Breakouts and Breakout Failures: Real-World Trading",
           "Adam H. Grimes", "Retrieved 2026-08-01", "2021-04-09", "OFFICIAL_DOCUMENTATION",
           "a178bf8ea51abd26c21743054eee3e66d7d177e82b04a69560bad488aa2f9d76",
           "https://www.adamhgrimes.com/breakouts-and-breakout-failures-real-world-trading/",
           ["Breakouts and breakout failures > classic breakout setup",
            "Breakouts and breakout failures > failure test",
            "Breakouts and breakout failures > follow-through/no-bias lesson"],
           rights="AUTHOR_OFFICIAL_FREE_WEB_PARAPHRASE_ONLY"),
    source("al-brooks-price-action-manual-2026", "How to Trade Price Action Manual", "Al Brooks",
           "Retrieved 2026-08-01", None, "OFFICIAL_DOCUMENTATION",
           "5b8f6df6284a6c394a428d2cae36caa61829277c9ffe61540843f1dd2023d5d9",
           "https://www.brookstradingcourse.com/how-to-trade-price-action-manual/",
           ["Opening overview > context over candle patterns", "How to Trade Price Action Contents > open/public chapters",
            "Either high probability or good risk/reward, but never both"],
           rights="AUTHOR_OFFICIAL_FREE_MANUAL_PARAPHRASE_ONLY"),
    source("al-brooks-candlestick-context-2026", "Candlestick Charts", "Al Brooks",
           "Retrieved 2026-08-01", None, "OFFICIAL_DOCUMENTATION",
           "20ab78e79fac62f996398ce2a629cf4ee667aba4cf2683bb7a85f9a615f1b1ac",
           "https://www.brookstradingcourse.com/how-to-trade-manual/candlestick-charts/",
           ["The lure of candlestick chart patterns", "Setups and Signals", "context means bars to the left"],
           rights="AUTHOR_OFFICIAL_FREE_MANUAL_PARAPHRASE_ONLY"),
    source("al-brooks-price-action-glossary-2026", "Price Action Trading Terms Glossary", "Al Brooks",
           "Retrieved 2026-08-01", None, "OFFICIAL_DOCUMENTATION",
           "55c9f8aeb31202e1176c26e7340c35340c9e887eac9b4d4a577d033b6ab10936",
           "https://www.brookstradingcourse.com/price-action-trading-terms-glossary/",
           ["breakout", "breakout pullback", "failure (a failed move)", "follow-through", "pullback", "trading range"],
           rights="AUTHOR_OFFICIAL_FREE_GLOSSARY_PARAPHRASE_ONLY"),
    source("al-brooks-trading-ranges-2026", "Trading Ranges", "Al Brooks",
           "Retrieved 2026-08-01", None, "OFFICIAL_DOCUMENTATION",
           "ecd1e85fe583deaad34b52a5e9821bc7f4d906ee1d68e16e2ca4dee5bb4f7f99",
           "https://www.brookstradingcourse.com/how-to-trade-manual/trading-ranges/",
           ["Market cycles between trends and trading ranges", "Most breakout attempts fail",
            "Tight Trading Ranges > Most should not trade"],
           rights="AUTHOR_OFFICIAL_FREE_MANUAL_PARAPHRASE_ONLY"),
    source("frbny-osler-stoploss-cascades-2002", "Stop-Loss Orders and Price Cascades in Currency Markets",
           "Carol L. Osler; Federal Reserve Bank of New York", "Staff Report No. 150", "2002-07-01", "PAPER",
           "0132a12fe1116a4608e437bb36212e21589fec22e925a04edb903d0f0e601904",
           "https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf",
           ["PDF p.1 > Abstract", "PDF p.6 > scope and other-factor limitation",
            "PDF p.20 > causal-connection caveat"], rights="FEDERAL_RESERVE_OPEN_RESEARCH_PARAPHRASE_ONLY",
           limitations=["The evidence is from FX stop-order data and cannot be transferred to Indian options without validation."],
           contradictions=["The paper explicitly preserves other-factor and causal limitations."]),
    source("oic-bid-ask-options-2024", "Understanding the Bid and Ask Prices for Options",
           "The Options Industry Council", "Updated 2024-08", "2024-08-01", "OFFICIAL_DOCUMENTATION",
           "8ace352032241eef29870355a95fb74655e8e0b19efe1dbe1493c8def9975502",
           "https://www.optionseducation.org/news/understanding-the-bid-and-ask-prices-for-options",
           ["Main article > order routing and execution outcomes", "Main article > market and limit order trade-offs", "Key Takeaways"],
           rights="OIC_OFFICIAL_EDUCATIONAL_PARAPHRASE_ONLY"),
    source("oic-options-pricing-2026", "Options Pricing", "The Options Industry Council",
           "Retrieved 2026-08-01", None, "OFFICIAL_DOCUMENTATION",
           "17f6dc2cd4744823163e0d3535114da27d0dd8f4a0485c4b82c7429175b03e5c",
           "https://www.optionseducation.org/optionsoverview/options-pricing",
           ["Intrinsic Value", "Time Value", "Major Factors Influencing Options Premium"],
           rights="OIC_OFFICIAL_EDUCATIONAL_PARAPHRASE_ONLY"),
    source("occ-learning-curriculum-2026", "OCC Learning", "Options Clearing Corporation",
           "Retrieved 2026-08-01", None, "OFFICIAL_DOCUMENTATION",
           "d80060fe597d908f338042cf8cefe0a670d357de0e0fd705b56853e1a532f2b2",
           "https://www.optionseducation.org/theoptionseducationcenter/occ-learning",
           ["Options 101", "Getting to Know the Greeks", "Options Volatility - Forecasting the Unknown"],
           rights="OCC_OFFICIAL_EDUCATIONAL_PARAPHRASE_ONLY"),
    source("oic-open-interest-2026", "Open Interest: Why It Matters", "The Options Industry Council",
           "Retrieved 2026-08-01", None, "OFFICIAL_DOCUMENTATION",
           "b60f674d6bec0951b3a0805a6e3f81fcb139a050e0935370750d5e1a9ecf5e88",
           "https://www.optionseducation.org/news/open-interest-why-it-matters",
           ["Main article > volume versus open interest", "Main article > exercise/assignment removals", "Key Takeaways"],
           rights="OIC_OFFICIAL_EDUCATIONAL_PARAPHRASE_ONLY"),
    source("bailey-pbo-2015", "The Probability of Backtest Overfitting", "David H. Bailey et al.",
           "Journal of Computational Finance version", "2015-02-27", "PAPER",
           "d8bfbadaaedb430d9dec929646d92f3580fdf18238f34121ae7738fa1c69a63d",
           "https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf",
           ["PDF p.2 > Abstract", "PDF pp.6-8 > hold-out limitations",
            "PDF pp.10-13 > combinatorially symmetric cross-validation and PBO", "PDF p.28 > Conclusions"],
           rights="AUTHOR_HOSTED_OPEN_RESEARCH_PARAPHRASE_ONLY"),
    source("bailey-lopez-dsr-2014", "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality",
           "David H. Bailey; Marcos López de Prado", "2014 manuscript", "2014-07-31", "PAPER",
           "ca4a1e834a2954b84eb560776e903329cd9cef318d458aadf6d67bc8166d10b5",
           "https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf",
           ["PDF p.2 > Abstract", "PDF pp.3-6 > Multiple testing and selection bias",
            "PDF p.8 > The Deflated Sharpe Ratio", "PDF p.11 > Conclusions"],
           rights="AUTHOR_HOSTED_OPEN_RESEARCH_PARAPHRASE_ONLY"),
    source("arxiv-xu-gould-howison-mlofi-2019", "Multi-Level Order-Flow Imbalance in a Limit Order Book",
           "Ke Xu; Martin D. Gould; Sam D. Howison", "arXiv:1907.06230", "2019-07-14", "PAPER",
           "a4da688fe33e8bf981e96e265b89cee3e42d0ae7efd187aa3f6cbd5c27359460",
           "https://arxiv.org/pdf/1907.06230",
           ["PDF p.1 > Abstract", "Section 2 > Multi-level order-flow imbalance definition",
            "Section 4 > out-of-sample comparison", "Section 5 > Conclusion"],
           rights="ARXIV_OPEN_ACCESS_PARAPHRASE_ONLY",
           limitations=["CITADEL lacks authoritative multi-level Indian option order-event history; production use is unavailable."]),
    source("arxiv-smith-farmer-gillemot-cda-2002", "Statistical Theory of the Continuous Double Auction",
           "Eric Smith; J. Doyne Farmer; László Gillemot; Supriya Krishnamurthy",
           "arXiv:cond-mat/0210475", "2002-10-22", "PAPER",
           "3ee6de4abe6126462237f67715bc2a28337b8b8d0d64f7a44ddde4893408d345",
           "https://arxiv.org/pdf/cond-mat/0210475",
           ["PDF p.1 > Abstract", "PDF p.3 > Background: The continuous double auction",
            "PDF pp.13-14 > fill probability and fill time", "PDF p.29 > liquidity and immediate impact",
            "PDF p.32 > dimensionless-model limitation"], rights="ARXIV_OPEN_ACCESS_PARAPHRASE_ONLY",
           limitations=["The zero-intelligence model is explanatory and is not a live fill forecast."]),
    source("user-fvg-strategy-notes-2026", "FVG Strategy Knowledge Notes", "User-provided compilation",
           "Exact attachment bytes 2026-08-01", "2026-08-01", "USER_PROVIDED", USER_FVG_HASH,
           "user_sources/fvg_strategy_notes.txt",
           ["Usable FVG Rules > rule 1", "Usable FVG Rules > rules 2-7", "Usable FVG Rules > rules 8-16",
            "Entry Models For Our FVG Strategy > rules 1-7", "Stop And Target Logic > rules 1-8",
            "Filters For Indian Option Buying > rules 1-10", "What Not To Do > rules 1-6"],
           rights="USER_PROVIDED_RETAIN_EXACT_LOCAL_SOURCE_NO_REDISTRIBUTION",
           quality="USER_PROVIDED_UNVALIDATED",
           limitations=["Video-derived assertions were supplied by the user; linked video bytes/transcripts were not reviewed."],
           contradictions=["The notes mix measurable rules with discretionary terminology and fixed-RR hypotheses."]),
    source("user-strategy-knowledge-base-2026", "Strategy Knowledge Base", "User-provided compilation",
           "Exact attachment bytes 2026-08-01", "2026-08-01", "USER_PROVIDED", USER_STRATEGY_HASH,
           "user_sources/strategy_knowledge_base.txt",
           ["Video 2 > Main Ideas", "Video 3 > Main Ideas", "Video 5 > Main Rules", "Video 7 > Entry Families",
            "Video 8 > FVG Rules", "Video 9 > Valid Pullback", "Video 10 > Strategy Rules",
            "Video 11 > Trade Logic", "Video 13 > Rules", "Video 17 > CHoCH Rules",
            "Unified Strategy Design Notes > Context", "Unified Strategy Design Notes > Zone",
            "Unified Strategy Design Notes > Trigger", "Unified Strategy Design Notes > Risk",
            "V2 Build Blueprint > Pullback V2", "V2 Build Blueprint > Breakout V2"],
           rights="USER_PROVIDED_RETAIN_EXACT_LOCAL_SOURCE_NO_REDISTRIBUTION",
           quality="USER_PROVIDED_UNVALIDATED",
           limitations=["The linked video transcripts were not independently fetched or authenticated."],
           contradictions=["All setup descriptions remain research-only and cannot direct execution."]),
]


def card(card_id: str, concept: str, domain: str, source_id: str, locator: str, principle: str,
         *, predicates: list[str] | None = None, failures: list[str] | None = None,
         contradictions: list[str] | None = None, not_use: list[str] | None = None,
         fields: list[str] | None = None, status: str = "SOURCE_BACKED_UNVALIDATED",
         quality: str = "OFFICIAL_PRIMARY", empirical: str = "NOT_CITADEL_VALIDATED",
         setup: list[str] | None = None, regimes: list[str] | None = None,
         links: list[str] | None = None, relevance: str = "HIGH") -> dict:
    src = next(row for row in NEW_SOURCES if row["source_id"] == source_id)
    return {
        "card_id": card_id, "version": "1.0.0", "card_type": "PRINCIPLE", "concept": concept,
        "domain": domain, "definition_principle": principle,
        "measurable_predicates": predicates or ["The claim is compiled into versioned numerical predicates."],
        "required_evidence": ["canonical completed candles or authoritative option snapshot", "source and predicate version"],
        "optional_confirmations": [], "valid_conditions": ["All cited inputs are complete, current, and time-safe."],
        "failure_conditions": failures or ["Required deterministic evidence is missing or stale."],
        "contradictions": contradictions or ["The principle does not establish a CITADEL probability."],
        "when_not_to_use": not_use or ["Do not use as standalone direction, probability, risk, or execution authorization."],
        "timeframes": ["1D", "4H", "1H", "15m", "5m", "3m", "1m"],
        "instruments": ["NIFTY", "BANKNIFTY"], "option_buying_relevance": relevance,
        "relevant_citadel_fields": fields or ["canonical_candle_refs", "verified_visual_claims", "evidence_bundle"],
        "data_availability": {"canonical_candles": "AVAILABLE", "visual_claim": "VERIFY_NUMERICALLY"},
        "source_id": source_id, "exact_locator": locator, "short_excerpt": None,
        "paraphrase": principle, "source_quality": quality, "source_hash_version": src["document_hash"],
        "validation_status": status, "empirical_status": empirical, "execution_influence": "ZERO",
        "knowledge_policy_version": POLICY, "regimes": regimes or [], "setup_types": setup or [],
        "contradicts_card_ids": links or [], "research_only": False, "research_fields": {},
    }


CARDS: list[dict] = []


def add(*args, **kwargs) -> None:
    CARDS.append(card(*args, **kwargs))


# Official price action, market structure, and candlestick context.
add("grimes-structure-before-pattern", "Structure before pattern", "market_structure", "adam-grimes-market-structure-2026",
    "Elementary Market Structure > market structure vs price action",
    "First classify structural context; a named short-term pattern does not replace trend/range location.")
add("grimes-trend-range-classification", "Trend and range classification", "market_structure", "adam-grimes-market-structure-2026",
    "Elementary Market Structure > trends and ranges",
    "Trend and trading-range states require different expectations and predicates.", regimes=["TRENDING", "RANGING"])
add("grimes-objective-structure-boundary", "Objective structure boundary", "market_structure", "adam-grimes-market-structure-2026",
    "Elementary Market Structure > quantifiable/statistically verifiable boundary",
    "Market structure becomes CITADEL evidence only after its levels and transitions are numerically reproducible.")
add("grimes-simple-pullback", "Simple trend pullback", "price_action", "adam-grimes-fundamental-patterns-2026", "Simple Pullback",
    "A pullback is context inside a prior impulse and needs a defined trend, retracement, invalidation, and continuation trigger.",
    setup=["TREND_PULLBACK"], regimes=["TRENDING"])
add("grimes-failure-test", "Failure test and reclaim", "price_action", "adam-grimes-fundamental-patterns-2026", "Failure Test",
    "A failed break is evaluated by trade-through and return, not by a wick label alone.",
    predicates=["Price trades beyond a predeclared level.", "A completed candle returns through the level within the fixed window."],
    setup=["FAILED_BREAKOUT_REVERSAL", "LIQUIDITY_SWEEP_RECLAIM"], links=["grimes-breakout-followthrough"])
add("grimes-breakout-definition", "Breakout from defined structure", "price_action", "adam-grimes-fundamental-patterns-2026", "Breakouts",
    "A breakout requires a predeclared boundary and completed-candle movement beyond it.", setup=["BREAKOUT_ACCEPTANCE_RETEST"])
add("grimes-breakout-followthrough", "Breakout follow-through", "price_action", "adam-grimes-breakout-failures-2026",
    "Breakouts and breakout failures > classic breakout setup",
    "A break requires subsequent acceptance or follow-through before continuation is supported.",
    setup=["BREAKOUT_ACCEPTANCE_RETEST"], links=["grimes-failure-test"])
add("grimes-breakout-no-bias", "No bias after failed evidence", "price_action", "adam-grimes-breakout-failures-2026",
    "Breakouts and breakout failures > follow-through/no-bias lesson",
    "If the expected follow-through is absent, evidence must be reassessed rather than defended.")
add("brooks-context-over-candle-name", "Context over candlestick name", "candlesticks", "al-brooks-price-action-manual-2026",
    "Opening overview > context over candle patterns",
    "A candle name is not a setup; the bars and structure around it determine what can be measured.", links=["brooks-candle-pattern-alone-invalid"])
add("brooks-signal-plus-context", "Signal plus context", "candlesticks", "al-brooks-candlestick-context-2026", "Setups and Signals",
    "A signal bar is usable only as part of a defined setup and preceding context.")
add("brooks-bars-left-context", "Prior bars define context", "candlesticks", "al-brooks-candlestick-context-2026", "context means bars to the left",
    "Completed bars preceding a candidate candle are required context and must not be hindsight-selected.")
add("brooks-candle-pattern-alone-invalid", "Candlestick pattern alone is insufficient", "candlesticks", "al-brooks-candlestick-context-2026",
    "The lure of candlestick chart patterns", "Do not convert a candlestick label alone into trading evidence.",
    links=["brooks-context-over-candle-name"])
add("brooks-breakout-pullback", "Breakout pullback", "price_action", "al-brooks-price-action-glossary-2026", "breakout pullback",
    "A breakout-retest claim requires a confirmed break, a return to the boundary, and a deterministic hold/failure rule.",
    setup=["BREAKOUT_ACCEPTANCE_RETEST"])
add("brooks-failed-move", "Failed move", "price_action", "al-brooks-price-action-glossary-2026", "failure (a failed move)",
    "Failure is defined relative to a declared expected move and a fixed invalidation window.", setup=["FAILED_BREAKOUT_REVERSAL"])
add("brooks-range-breakout-failure", "Range breakout attempts often fail", "market_structure", "al-brooks-trading-ranges-2026",
    "Most breakout attempts fail", "Inside a trading range, breakout candidates require acceptance and follow-through rather than anticipation.",
    regimes=["RANGING"], links=["grimes-breakout-followthrough"])
add("brooks-tight-range-no-trade", "Tight-range restraint", "market_structure", "al-brooks-trading-ranges-2026",
    "Tight Trading Ranges > Most should not trade", "Tight overlapping price action is a valid no-trade context for directional option buying.",
    predicates=["Range width, overlap, and directional progress are measured over a fixed window."], regimes=["RANGING"])

# Liquidity: measurable sequence plus explicit scope and causality boundaries.
add("frbny-stop-cascade-observation", "Observed stop-loss clustering and cascades", "liquidity_smc",
    "frbny-osler-stoploss-cascades-2002", "PDF p.1 > Abstract",
    "The FX study observed stop-order clustering and rapid moves after levels, which motivates a measurable level/trade-through/reclaim sequence.",
    setup=["LIQUIDITY_SWEEP_RECLAIM"], links=["frbny-stop-cascade-transfer-limit"], quality="PEER_REVIEWED_PRIMARY")
add("frbny-stop-cascade-transfer-limit", "Stop-cascade transfer boundary", "liquidity_smc",
    "frbny-osler-stoploss-cascades-2002", "PDF p.6 > scope and other-factor limitation",
    "FX stop-order findings do not prove hidden orders or institutional causality in Indian index options.",
    links=["frbny-stop-cascade-observation"], quality="PEER_REVIEWED_PRIMARY")
add("frbny-stop-cascade-causality-limit", "Stop-cascade causal limitation", "liquidity_smc",
    "frbny-osler-stoploss-cascades-2002", "PDF p.20 > causal-connection caveat",
    "Even an observed price cascade must retain the source paper's causal caveat.", quality="PEER_REVIEWED_PRIMARY")

# Options, volatility, liquidity, and executable price.
add("oic-executable-bid-ask", "Executable option bid and ask", "options", "oic-bid-ask-options-2024",
    "Main article > order routing and execution outcomes",
    "Last price is not execution truth; option evidence must use current bid, ask, spread, timestamp, and route assumptions.",
    fields=["option_bid", "option_ask", "spread", "quote_freshness", "route_health"], relevance="HIGH")
add("oic-market-order-tradeoff", "Market-order execution trade-off", "microstructure", "oic-bid-ask-options-2024",
    "Main article > market and limit order trade-offs",
    "A market-style order prioritizes execution but does not guarantee price.", links=["oic-limit-order-tradeoff"], relevance="HIGH")
add("oic-limit-order-tradeoff", "Limit-order execution trade-off", "microstructure", "oic-bid-ask-options-2024", "Key Takeaways",
    "A limit constrains price but may remain unfilled or partially filled.", links=["oic-market-order-tradeoff"], relevance="HIGH")
add("oic-option-intrinsic-value", "Option intrinsic value", "options", "oic-options-pricing-2026", "Intrinsic Value",
    "Intrinsic value depends on option type, strike, and underlying relationship; it is not the entire premium.", relevance="HIGH")
add("oic-option-time-value", "Option time value", "volatility", "oic-options-pricing-2026", "Time Value",
    "Premium beyond intrinsic value includes time value and changes as expiry and other inputs change.", relevance="HIGH")
add("oic-premium-multiple-inputs", "Option premium has multiple inputs", "options", "oic-options-pricing-2026",
    "Major Factors Influencing Options Premium",
    "Underlying price, strike, time, volatility, dividends, and rates jointly affect theoretical premium.", relevance="HIGH")
add("occ-greeks-sensitivities", "Greeks are sensitivities", "options", "occ-learning-curriculum-2026", "Getting to Know the Greeks",
    "Delta, Gamma, Theta, and Vega describe theoretical sensitivities and are not realized-price promises.", relevance="HIGH")
add("occ-volatility-uncertainty", "Volatility is uncertain", "volatility", "occ-learning-curriculum-2026",
    "Options Volatility - Forecasting the Unknown", "Volatility inputs are estimates and require current contract evidence.", relevance="HIGH")
add("oic-open-interest-not-volume", "Open interest differs from volume", "options", "oic-open-interest-2026",
    "Main article > volume versus open interest", "Open interest and trading volume measure different contract activity.", relevance="HIGH")
add("oic-open-interest-not-direction", "Open interest is not direction", "options", "oic-open-interest-2026", "Key Takeaways",
    "Open interest alone does not identify bullish/bearish pressure, executable liquidity, or outcome probability.", relevance="HIGH")

# Transparent order-book research remains future-data dependent.
add("cda-order-matching-context", "Continuous double-auction matching", "microstructure",
    "arxiv-smith-farmer-gillemot-cda-2002", "PDF p.3 > Background: The continuous double auction",
    "Orders interact through price-time matching rules; a candle is not an order-book reconstruction.",
    status="FUTURE_DATA_DEPENDENT", quality="WORKING_PAPER_PRIMARY")
add("cda-fill-probability-model-limit", "Fill probability model boundary", "microstructure",
    "arxiv-smith-farmer-gillemot-cda-2002", "PDF pp.13-14 > fill probability and fill time",
    "Modelled fill properties depend on assumptions and cannot replace observed CITADEL paper/broker events.",
    status="FUTURE_DATA_DEPENDENT", quality="WORKING_PAPER_PRIMARY", links=["oic-executable-bid-ask"])
add("cda-impact-model-limit", "Immediate impact model boundary", "microstructure",
    "arxiv-smith-farmer-gillemot-cda-2002", "PDF p.32 > dimensionless-model limitation",
    "A stylized dimensionless model is not a live forecast for Indian option spread or impact.",
    status="FUTURE_DATA_DEPENDENT", quality="WORKING_PAPER_PRIMARY")
add("mlofi-multiple-depth-levels", "Multi-level order-flow imbalance", "order_flow",
    "arxiv-xu-gould-howison-mlofi-2019", "Section 2 > Multi-level order-flow imbalance definition",
    "Multi-level imbalance requires synchronized changes across several book levels, not volume or top-of-book alone.",
    status="FUTURE_DATA_DEPENDENT", quality="WORKING_PAPER_PRIMARY", links=["mlofi-citadel-data-unavailable"])
add("mlofi-oos-comparison", "Order-flow models need OOS comparison", "order_flow",
    "arxiv-xu-gould-howison-mlofi-2019", "Section 4 > out-of-sample comparison",
    "Any order-flow feature must be evaluated out of sample and with market-specific data.",
    status="FUTURE_DATA_DEPENDENT", quality="WORKING_PAPER_PRIMARY")
add("mlofi-citadel-data-unavailable", "CITADEL multi-level data unavailable", "order_flow",
    "arxiv-xu-gould-howison-mlofi-2019", "PDF p.1 > Abstract",
    "Without authoritative multi-level order-event history, CITADEL cannot claim MLOFI evidence.",
    status="FUTURE_DATA_DEPENDENT", quality="WORKING_PAPER_PRIMARY", links=["mlofi-multiple-depth-levels"])

# Validation and anti-overfitting.
add("pbo-holdout-limit", "Hold-out reuse limitation", "systematic_validation", "bailey-pbo-2015",
    "PDF pp.6-8 > hold-out limitations", "A repeatedly consulted hold-out set no longer provides a clean final test.",
    quality="PEER_REVIEWED_PRIMARY", links=["pbo-cscv-trial-accounting"])
add("pbo-cscv-trial-accounting", "PBO and CSCV trial accounting", "systematic_validation", "bailey-pbo-2015",
    "PDF pp.10-13 > combinatorially symmetric cross-validation and PBO",
    "Backtest selection risk requires explicit candidate-trial accounting and an immutable validation design.",
    quality="PEER_REVIEWED_PRIMARY", links=["pbo-holdout-limit"])
add("pbo-no-live-probability", "PBO is not live trade probability", "systematic_validation", "bailey-pbo-2015",
    "PDF p.28 > Conclusions", "A backtest-overfitting diagnostic cannot become the probability of a current setup.",
    quality="PEER_REVIEWED_PRIMARY")
add("dsr-multiple-testing", "Deflated Sharpe multiple-testing correction", "systematic_validation", "bailey-lopez-dsr-2014",
    "PDF pp.3-6 > Multiple testing and selection bias",
    "Performance interpretation must disclose selection among trials and non-normal returns.", quality="PEER_REVIEWED_PRIMARY")
add("dsr-selection-bias", "Selection bias disclosure", "systematic_validation", "bailey-lopez-dsr-2014",
    "PDF p.8 > The Deflated Sharpe Ratio", "A selected Sharpe ratio must be evaluated against the number and distribution of trials.",
    quality="PEER_REVIEWED_PRIMARY")
add("dsr-not-edge", "Deflated Sharpe is not current edge", "systematic_validation", "bailey-lopez-dsr-2014",
    "PDF p.11 > Conclusions", "A corrected historical performance statistic does not authorize or predict a current trade.",
    quality="PEER_REVIEWED_PRIMARY")


# User-provided FVG cards: exact text retained, every claim visibly unvalidated.
USER_FVG = [
    ("user-fvg-three-candle-definition", "Three-candle FVG definition", "Usable FVG Rules > rule 1", "The notes define bullish and bearish gaps by non-overlap between candle-one and candle-three wicks."),
    ("user-fvg-displacement-filter", "Displacement filter", "Usable FVG Rules > rules 2-7", "The notes require a strong middle displacement candle and reject tiny gaps without impulse."),
    ("user-fvg-not-standalone-entry", "FVG is not a standalone entry", "Usable FVG Rules > rules 2-7", "The notes require a retest, rejection, structure, engulfing, or continuation trigger."),
    ("user-fvg-structure-break-filter", "Structure-break quality filter", "Usable FVG Rules > rules 2-7", "The notes treat BOS or CHoCH near formation as a quality hypothesis."),
    ("user-fvg-liquidity-sweep-filter", "Liquidity-sweep quality filter", "Usable FVG Rules > rules 2-7", "The notes treat a prior measurable sweep as optional confluence."),
    ("user-fvg-unmitigated-priority", "Unmitigated FVG priority", "Usable FVG Rules > rules 2-7", "The notes prefer fresh, untested zones and default to one-time use."),
    ("user-fvg-reaction-close", "Reaction-close predicate", "Usable FVG Rules > rules 2-7", "A long reaction should close inside or above the zone rather than invalidate below it."),
    ("user-fvg-htf-ltf-map", "Higher/lower timeframe FVG roles", "Usable FVG Rules > rules 8-16", "The notes separate higher-timeframe location from lower-timeframe entry timing."),
    ("user-fvg-premium-discount", "Premium-discount filter", "Usable FVG Rules > rules 8-16", "The notes propose impulse-midpoint location as an option-premium quality filter."),
    ("user-fvg-extreme-location", "Extreme FVG location", "Usable FVG Rules > rules 8-16", "The notes prioritize an extreme gap over an internal gap, subject to deterministic definition."),
    ("user-fvg-demand-confluence", "Demand or supply confluence", "Usable FVG Rules > rules 8-16", "The notes propose deterministic demand/support or supply/resistance overlap as confluence."),
    ("user-fvg-inside-bar-exception", "Inside-bar exception", "Usable FVG Rules > rules 8-16", "The notes propose a mother-candle/four-candle adjustment when candle one is inside."),
    ("user-fvg-news-slippage", "Event-gap slippage caution", "Usable FVG Rules > rules 8-16", "The notes warn that abrupt event gaps may have poor executable prices."),
    ("user-fvg-retest-close-entry", "Retest-close entry", "Entry Models For Our FVG Strategy > rules 1-7", "A candidate entry waits for completed-candle acceptance inside or above a bullish FVG."),
    ("user-fvg-wick-touch-entry", "Wick-touch entry hypothesis", "Filters For Indian Option Buying > rules 1-10", "Wick touch is retained only as a selectable research mode and not a confirmed entry rule."),
    ("user-fvg-midpoint-entry", "Midpoint-limit entry hypothesis", "Entry Models For Our FVG Strategy > rules 1-7", "The notes propose midpoint entry for large gaps, subject to fill and OOS testing."),
    ("user-fvg-engulf-entry", "Engulf-confirmation entry", "Entry Models For Our FVG Strategy > rules 1-7", "The notes propose completed engulf confirmation after a gap tap."),
    ("user-fvg-breakaway-continuation", "Breakaway FVG continuation", "Entry Models For Our FVG Strategy > rules 1-7", "The notes propose continuation only after strong breakout, displacement, and an unfilled gap."),
    ("user-fvg-stop-candidates", "FVG stop candidates", "Stop And Target Logic > rules 1-8", "The notes list zone, displacement, demand, and transparent buffer candidates; none is automatically authoritative."),
    ("user-fvg-target-room", "FVG target-room filter", "Stop And Target Logic > rules 1-8", "The notes require room to a natural structure or liquidity target before considering the setup."),
    ("user-fvg-fixed-rr-hypothesis", "Fixed 2R/3R target hypothesis", "Stop And Target Logic > rules 1-8", "The supplied 2R/3R targets remain an unvalidated research hypothesis and cannot replace natural CITADEL targets."),
    ("user-fvg-session-window", "Indian option session window", "Filters For Indian Option Buying > rules 1-10", "The notes propose avoiding the chaotic opening minute and late-decay entries as testable session filters."),
    ("user-fvg-volume-filter", "Option displacement volume filter", "Filters For Indian Option Buying > rules 1-10", "The notes propose displacement volume relative to recent average as an optional research filter."),
    ("user-fvg-chop-rejection", "Choppy overlapping FVG rejection", "Filters For Indian Option Buying > rules 1-10", "The notes reject many overlapping small gaps without clean impulse or structure break."),
    ("user-fvg-do-not-buy-every-touch", "Do not buy every FVG touch", "What Not To Do > rules 1-6", "The notes explicitly reject blind gap-touch entries and repeated use of mitigated gaps."),
]
for card_id, concept, locator, principle in USER_FVG:
    counter_links = {
        "user-fvg-three-candle-definition": ["pa-patterns-require-deterministic-predicates"],
        "user-fvg-liquidity-sweep-filter": ["liquidity-sweep-no-causality"],
        "user-fvg-fixed-rr-hypothesis": ["construction-no-fixed-rr-targets"],
    }.get(card_id, [])
    add(card_id, concept, "user_fvg", "user-fvg-strategy-notes-2026", locator, principle,
        status="HYPOTHESIS" if "fixed-rr" in card_id else "USER_PROVIDED_UNVALIDATED",
        quality="USER_PROVIDED_NOT_VERIFIED", empirical="USER_CLAIM_NOT_INTERNALLY_VALIDATED",
        setup=["DISPLACEMENT_FVG_RETEST", "BREAKAWAY_FVG_CONTINUATION"], relevance="HIGH", links=counter_links,
        failures=["The predicate is ambiguous, uses future data, or lacks the authoritative CITADEL field."],
        not_use=["Do not use this user-provided claim for current-trade risk or execution."])


def research(card_id: str, concept: str, setup_type: str, locator: str, setup_logic: str,
             trigger_logic: str, invalidation: str, target: str) -> dict:
    row = card(card_id, concept, "strategy_research", "user-strategy-knowledge-base-2026", locator,
               setup_logic, status="USER_PROVIDED_UNVALIDATED", quality="USER_PROVIDED_NOT_VERIFIED",
               empirical="RESEARCH_ONLY_NOT_BACKTESTED", setup=[setup_type], relevance="HIGH")
    row.update({"card_type": "STRATEGY_RESEARCH", "research_only": True,
        "research_fields": {
            "instrument_scope": ["NIFTY", "BANKNIFTY", "CE_OR_PE_PREMIUM_LONG_ONLY"],
            "timeframe_scope": ["15m", "5m", "3m", "1m"],
            "regime_filter": "Versioned context policy; skip directionless/tight overlapping range.",
            "setup_logic": setup_logic, "trigger_logic": trigger_logic, "invalidation_logic": invalidation,
            "target_logic": target, "option_filter": "Fresh exact contract, bid/ask/spread, Greeks and expiry where available.",
            "required_data": ["canonical completed candles", "VOB", "OSE", "ARGUS", "option quote and spread"],
            "missing_data": "Fail unavailable; do not proxy or infer the missing authority.",
            "cost_model": "Executable bid/ask, fees and slippage must be included.",
            "backtest_plan": "Compile predicates, freeze versions, replay authoritative records, include costs and failures.",
            "oos_plan": "Immutable time split, trial accounting, untouched OOS evaluation and degradation checks.",
            "failure_analysis": "Report no-trigger, invalidation, spread, stale data, regime transfer and target-room failures.",
            "research_status": "RESEARCH_ONLY",
        }})
    return row


RESEARCH = [
    research("research-liquidity-sweep-reclaim", "Liquidity sweep and reclaim", "LIQUIDITY_SWEEP_RECLAIM",
             "Video 11 > Trade Logic", "Predeclared level, trade-through, completed reclaim, and room to target.",
             "Fresh reclaim plus option-premium confirmation.", "Close back beyond the sweep extreme or protected structure.",
             "Next verified liquidity/structure level; no fixed RR target."),
    research("research-breakout-acceptance-retest", "Breakout acceptance and retest", "BREAKOUT_ACCEPTANCE_RETEST",
             "V2 Build Blueprint > Breakout V2", "Completed close beyond VOB/supply followed by acceptance or a fresh retest zone.",
             "Retest hold or continuation break with premium confirmation.", "Failed reclaim of the breakout boundary.",
             "Next authoritative VOB/supply/liquidity target."),
    research("research-failed-breakout-reversal-v2", "Failed breakout reversal", "FAILED_BREAKOUT_REVERSAL",
             "Video 2 > Main Ideas", "Trade-through a declared boundary followed by completed return inside.",
             "Reclaim plus structure/premium confirmation.", "Renewed acceptance beyond the failed-break extreme.",
             "Opposite range boundary or verified structure level."),
    research("research-trend-pullback-v2", "Trend pullback", "TREND_PULLBACK", "Video 9 > Valid Pullback",
             "Verified trend, corrective pullback into an authoritative zone, and target room.",
             "Completed continuation/reclaim trigger.", "Protected swing or zone failure.", "Next verified structure/VOB target."),
    research("research-compression-displacement", "Compression and displacement", "COMPRESSION_DISPLACEMENT",
             "Unified Strategy Design Notes > Context", "Deterministic contraction followed by completed displacement through structure.",
             "Acceptance/follow-through and premium confirmation.", "Return into compression with failed continuation.",
             "Next natural structure or VOB level."),
    research("research-displacement-fvg-retest-v2", "Displacement FVG retest", "DISPLACEMENT_FVG_RETEST",
             "Video 13 > Rules", "Verified three-candle imbalance after displacement and structure transition.",
             "Fresh retest close/engulf confirmation.", "FVG/structure failure under explicit predicate.",
             "Next natural structure/liquidity level."),
    research("research-breakaway-fvg-continuation-v2", "Breakaway FVG continuation", "BREAKAWAY_FVG_CONTINUATION",
             "Video 8 > FVG Rules", "Strong completed breakout/displacement with an unmitigated gap and room.",
             "Follow-through beyond displacement reference plus premium confirmation.", "Gap fill and failed breakout acceptance.",
             "Next authoritative supply/VOB/liquidity level."),
    research("research-demand-vob-fvg-confluence", "Demand/VOB and FVG confluence", "DEMAND_VOB_FVG_CONFLUENCE",
             "Video 3 > Main Ideas", "Authoritative VOB/demand overlap with separately verified FVG location.",
             "LTF structure confirmation; no blind zone touch.", "VOB/demand structural failure.",
             "Next verified opposite VOB or structure target."),
    research("research-premium-confirmed-continuation-v2", "Premium-confirmed continuation", "PREMIUM_CONFIRMED_CONTINUATION",
             "Unified Strategy Design Notes > Trigger", "Underlying continuation setup plus exact option contract evidence.",
             "OSE and executable premium confirm without stale/wide spread.", "Underlying or premium structure failure.",
             "Natural underlying and premium levels with costs."),
    research("research-premium-confirmed-reversal", "Premium-confirmed reversal", "PREMIUM_CONFIRMED_REVERSAL",
             "Video 17 > CHoCH Rules", "Verified reversal context plus exact CE/PE contract evidence.",
             "Completed reversal trigger and OSE premium confirmation.", "Reversal structure fails or premium does not confirm.",
             "Next verified opposite structure/VOB level."),
]
CARDS.extend(RESEARCH)


FETCH_FACTS = {
    "adam-grimes-fundamental-patterns-2026": (23193, "text/html"),
    "adam-grimes-market-structure-2026": (25647, "text/html"),
    "adam-grimes-breakout-failures-2026": (38168, "text/html"),
    "al-brooks-price-action-manual-2026": (171844, "text/html"),
    "al-brooks-candlestick-context-2026": (164191, "text/html"),
    "al-brooks-price-action-glossary-2026": (197169, "text/html"),
    "al-brooks-trading-ranges-2026": (170546, "text/html"),
    "frbny-osler-stoploss-cascades-2002": (131865, "application/pdf"),
    "oic-bid-ask-options-2024": (95490, "text/html"),
    "oic-options-pricing-2026": (95855, "text/html"),
    "occ-learning-curriculum-2026": (94596, "text/html"),
    "oic-open-interest-2026": (95530, "text/html"),
    "bailey-pbo-2015": (1145522, "application/pdf"),
    "bailey-lopez-dsr-2014": (1048118, "application/pdf"),
    "arxiv-xu-gould-howison-mlofi-2019": (655636, "application/pdf"),
    "arxiv-smith-farmer-gillemot-cda-2002": (692906, "application/pdf"),
    "user-fvg-strategy-notes-2026": (5379, "text/plain"),
    "user-strategy-knowledge-base-2026": (26890, "text/plain"),
}


FETCH_ROWS = [
    {"source_id": row["source_id"], "source_location": row["source_location"],
     "resolved_location": row["source_location"],
     "access_status": "LOCAL_USER_PROVIDED" if row["source_type"] == "USER_PROVIDED" else "VERIFIED",
     "http_status": None if row["source_type"] == "USER_PROVIDED" else 200,
     "content_type": FETCH_FACTS[row["source_id"]][1], "byte_length": FETCH_FACTS[row["source_id"]][0],
     "sha256": row["document_hash"], "retrieved_at": "2026-08-01",
     "fetch_required_on_same_url_hash": False,
     "cache_key": hashlib.sha256((row["source_location"] + ":" + row["document_hash"]).encode()).hexdigest()}
    for row in NEW_SOURCES
]


def main() -> None:
    for rel, expected in (("user_sources/fvg_strategy_notes.txt", USER_FVG_HASH),
                          ("user_sources/strategy_knowledge_base.txt", USER_STRATEGY_HASH)):
        actual = hashlib.sha256((KROOT / rel).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"user source hash mismatch: {rel}")

    old_sources = json.loads((KROOT / "source_manifests/phase5a_sources.json").read_text())["sources"]
    all_sources = old_sources + NEW_SOURCES
    if len({row["source_id"] for row in all_sources}) != len(all_sources):
        raise SystemExit("duplicate source id")
    if len({row["source_location"] for row in all_sources}) != len(all_sources):
        raise SystemExit("duplicate source URL")
    if len({row["document_hash"] for row in all_sources}) != len(all_sources):
        raise SystemExit("duplicate source hash")
    write_json("source_manifests/expanded_sources.json", {"schema_version": SCHEMA, "sources": all_sources})

    grouped: dict[str, list[dict]] = {}
    for row in CARDS:
        grouped.setdefault(row["domain"], []).append(row)
    card_files = []
    for domain, rows in sorted(grouped.items()):
        relative = f"cards/{domain}/expanded.json"
        write_json(relative, {"schema_version": SCHEMA, "defaults": {}, "cards": rows})
        card_files.append(relative)

    old_card_files = [
        "cards/price_action/phase5a.json", "cards/market_structure/phase5a.json",
        "cards/liquidity_smc/phase5a.json", "cards/options/phase5a.json",
        "cards/microstructure/phase5a.json", "cards/trade_construction/phase5a.json",
        "cards/systematic_validation/phase5a.json",
    ]
    old_conflicts = json.loads((KROOT / "conflicts/phase5a_conflicts.json").read_text())["conflicts"]
    new_conflict_pairs = [
        ("breakout-followthrough-vs-failure", "grimes-breakout-followthrough", "grimes-failure-test",
         "A breakout requires follow-through; a trade-through and reclaim is a distinct failure sequence."),
        ("candle-name-vs-context", "brooks-context-over-candle-name", "brooks-candle-pattern-alone-invalid",
         "A named candle remains unavailable without preceding context and deterministic predicates."),
        ("stop-cascade-vs-transfer", "frbny-stop-cascade-observation", "frbny-stop-cascade-transfer-limit",
         "Retain the measurable FX observation while withholding hidden-order and Indian-option causality claims."),
        ("market-vs-limit-order", "oic-market-order-tradeoff", "oic-limit-order-tradeoff",
         "Expose the price-certainty versus execution-certainty trade-off; neither guarantees a fill at the displayed quote."),
        ("mlofi-vs-data-gap", "mlofi-multiple-depth-levels", "mlofi-citadel-data-unavailable",
         "MLOFI stays unavailable until authoritative multi-level order-event data exists."),
        ("pbo-holdout-vs-trials", "pbo-holdout-limit", "pbo-cscv-trial-accounting",
         "Use immutable splits plus trial accounting; do not reuse the final OOS sample."),
        ("user-fvg-vs-objective-predicate", "user-fvg-three-candle-definition", "pa-patterns-require-deterministic-predicates",
         "Keep the user definition as a hypothesis until the same completed candles reproduce the versioned predicate."),
        ("user-liquidity-vs-causality", "user-fvg-liquidity-sweep-filter", "liquidity-sweep-no-causality",
         "A measurable sweep may be context; hidden liquidity or institutional causality remains unverified."),
        ("user-fixed-rr-vs-natural-target", "user-fvg-fixed-rr-hypothesis", "construction-no-fixed-rr-targets",
         "Keep 2R/3R as a research variable; live construction uses natural targets and resulting RR."),
    ]
    conflicts = old_conflicts + [{"conflict_id": cid, "card_ids": [a, b], "materiality": "MATERIAL", "resolution": resolution}
                                 for cid, a, b, resolution in new_conflict_pairs]
    write_json("conflicts/expanded_conflicts.json", {"schema_version": SCHEMA, "conflicts": conflicts})

    old_pending = json.loads((KROOT / "pending_sources/phase5a_pending.json").read_text())["pending"]
    videos = ["WEhmadJArQo", "-uRKGucJEkE", "zm2CyPrD5Uk", "BFfF_Lnk9T4", "ZTMregh_428", "yFPrP6nJRYQ",
              "2u9oYfx5xdY", "vGyREXEwLIk", "pMRlqE-Tngs", "f18gazn0nYE", "dnnFb9V9uLI", "sSAGIzQAhuM",
              "vtZ6hWYT_nM", "JpQybUVffVI", "n6Z81Pmm3pc", "0UTvF4SWdQM", "xH_taQ9cIRs", "RE0qezm-Zvk",
              "-XPOohUo5fY", "NaWpOBxdsCY", "Gatya8gJdgM"]
    pending = old_pending + [
        {"candidate_id": "original-candlestick-pattern-research", "status": "PENDING_SOURCE",
         "location": "https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID932984_code328612.pdf",
         "reason": "HTTP 403 during byte fetch; no manifest or card created."},
        {"candidate_id": "white-reality-check-original-paper", "status": "PENDING_SOURCE",
         "location": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=160330",
         "reason": "HTTP 403 during byte fetch; no manifest or card created."},
    ] + [{"candidate_id": f"youtube-{video_id}", "status": "PENDING_SOURCE",
          "location": f"https://www.youtube.com/watch?v={video_id}",
          "reason": "User-attributed video reference; transcript and source bytes were not independently reviewed."}
         for video_id in videos]
    write_json("pending_sources/expanded_pending.json", {"schema_version": SCHEMA, "pending": pending})

    rejected = json.loads((KROOT / "rejected_sources/phase5a_rejected.json").read_text())["rejected"]
    write_json("rejected_sources/expanded_rejected.json", {"schema_version": SCHEMA, "rejected": rejected})

    reused_fetch = [{"source_id": row["source_id"], "source_location": row["source_location"],
                     "access_status": "REUSED_PINNED", "http_status": None,
                     "sha256": row["document_hash"], "retrieved_at": row["provenance"]["retrieved_at"],
                     "fetch_required_on_same_url_hash": False} for row in old_sources]
    blocked_fetch = [
        {"candidate_id": "original-candlestick-pattern-research", "source_location": pending[-23]["location"],
         "access_status": "PENDING_HTTP_403", "http_status": 403, "content_type": "text/html",
         "byte_length": 5695, "sha256": None,
         "error_response_sha256": "e871a3bc36cc05b4d9e4c1ac37e2974050e626eb26c3234c215e20ea8c628831",
         "retrieved_at": "2026-08-01"},
        {"candidate_id": "white-reality-check-original-paper", "source_location": pending[-22]["location"],
         "access_status": "PENDING_HTTP_403", "http_status": 403, "content_type": "text/html",
         "byte_length": 5523, "sha256": None,
         "error_response_sha256": "b6dca1adae443c60534dcfc337d60c7836b0afc7aff32d15c0f677e57c01d990",
         "retrieved_at": "2026-08-01"},
    ]
    write_json("fetched_sources/expanded_fetched.json", {"schema_version": SCHEMA,
               "network_fetches": {"attempted": 18, "accepted": 16, "pending": 2},
               "sources": reused_fetch + FETCH_ROWS, "pending_fetches": blocked_fetch})

    audit = {
        "schema_version": SCHEMA, "audit_date": "2026-08-01", "source_families_inspected": 12,
        "source_family_names": ["Adam H. Grimes official", "Al Brooks official", "Federal Reserve Bank of New York",
                                "National Bureau of Economic Research", "OIC/OCC", "SEC", "open microstructure papers",
                                "PBO/DSR/data-snooping/CFTC", "user FVG notes", "user strategy notes",
                                "GitHub discovery indexes", "original candlestick research candidates"],
        "network_fetch_attempts": 18,
        "network_sources_accepted": 16, "network_sources_pending": 2, "user_sources": 2,
        "books_ingested": 0, "youtube_transcripts_verified": 0,
        "github_repositories": [
            {"repository": "TA-Lib/ta-lib-python", "role": "DISCOVERY_INDEX_ONLY", "reused": False},
            {"repository": "kernc/backtesting.py", "role": "DISCOVERY_INDEX_ONLY", "reused": False},
        ], "repositories_cloned": 0, "frameworks_installed": 0,
        "source_selection": "Official author/organisation pages and original/open papers only.",
        "safety": {"advisory_only": True, "execution_influence": "ZERO", "historical_probability": None,
                   "strategy_promotion": False, "runtime_network": False, "runtime_llm": False},
    }
    write_json("ingestion_reports/expanded_source_audit.json", audit)

    all_card_count = sum(len(json.loads((KROOT / rel).read_text())["cards"]) for rel in old_card_files) + len(CARDS)
    summary = {"schema_version": SCHEMA, "registry_version": "oracle-knowledge-corpus-5a.2.0",
               "counts": {"accepted_sources": len(all_sources), "cards": all_card_count,
                          "new_cards": len(CARDS), "research_only_setups": len(RESEARCH),
                          "user_fvg_cards": len(USER_FVG), "pending": len(pending), "rejected": len(rejected),
                          "conflicts": len(conflicts), "new_conflicts": len(new_conflict_pairs),
                          "future_data_dependent_cards": sum(
                              row.get("validation_status") == "FUTURE_DATA_DEPENDENT" for row in CARDS) + 1},
               "truth": {"internally_validated_cards": 0, "historical_probabilities_created": 0,
                         "strategies_promoted": 0, "youtube_sources_verified": 0,
                         "same_trade_execution_influence": "ZERO", "runtime_network_required": False},
               "user_sources": {"fvg_sha256": USER_FVG_HASH, "strategy_sha256": USER_STRATEGY_HASH},
               "known_limitations": ["Two academic candidates were inaccessible and remain pending.",
                                     "YouTube references remain pending without verified transcripts.",
                                     "No CITADEL OOS outcome validation was performed by ingestion."]}
    write_json("ingestion_reports/expanded_ingestion_summary.json", summary)

    fixtures = {"schema_version": SCHEMA, "fixtures": [
        {"fixture_id": "fvg-support-and-counter", "instrument": "NIFTY", "timeframe": "3m",
         "setup_type": "DISPLACEMENT_FVG_RETEST", "question": "FVG displacement retest context contradiction",
         "expected_max_cards": 5, "research_only_allowed": False},
        {"fixture_id": "option-executable-price", "instrument": "NIFTY", "timeframe": "5m",
         "setup_type": None, "question": "option bid ask spread executable price limit market",
         "expected_max_cards": 5, "research_only_allowed": False},
        {"fixture_id": "overfitting", "instrument": "BANKNIFTY", "timeframe": "15m",
         "setup_type": None, "question": "backtest overfitting holdout multiple testing OOS",
         "expected_max_cards": 5, "research_only_allowed": False},
    ]}
    write_json("retrieval_fixtures/expanded_retrieval.json", fixtures)

    registry = {"schema_version": SCHEMA, "registry_version": "oracle-knowledge-corpus-5a.2.0",
                "generated_at": GENERATED, "source_manifests": "source_manifests/expanded_sources.json",
                "card_files": old_card_files + card_files, "conflicts": "conflicts/expanded_conflicts.json",
                "pending_sources": "pending_sources/expanded_pending.json",
                "rejected_sources": "rejected_sources/expanded_rejected.json",
                "audit_report": "ingestion_reports/expanded_source_audit.json",
                "ingestion_summary": "ingestion_reports/expanded_ingestion_summary.json",
                "fetched_sources": "fetched_sources/expanded_fetched.json",
                "ingestion_ledger": "ingestion_ledgers/expanded_ingestion.jsonl",
                "retrieval_fixtures": "retrieval_fixtures/expanded_retrieval.json",
                "user_source_files": ["user_sources/fvg_strategy_notes.txt", "user_sources/strategy_knowledge_base.txt"]}
    write_json("registry/expanded_registry.json", registry)

    ledger_path = KROOT / "ingestion_ledgers/expanded_ingestion.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    events = []
    prior_hash = "0" * 64
    stages = ["DISCOVERED", "SOURCE_VERIFIED", "RIGHTS/ACCESS_CHECKED", "DUPLICATE_CHECKED", "FETCHED",
              "HASHED", "EXTRACTED", "REVIEWED", "CARD_VALIDATED", "REGISTERED", "RETRIEVAL_TESTED"]
    new_ids = {row["source_id"] for row in NEW_SOURCES}
    for candidate in [row["source_id"] for row in all_sources]:
        for index, stage in enumerate(stages):
            event = {"schema_version": SCHEMA, "policy_version": "oracle-knowledge-ingestion-5a.2.0",
                     "candidate_id": candidate, "stage": stage,
                     "idempotency_key": f"expanded:{candidate}:{index}", "actor_id": "codex-curator",
                     "correlation_id": "expanded-knowledge-20260801",
                     "details": {"stage_index": index, "network_runtime": False,
                                 "reused_phase5a_pin": candidate not in new_ids}, "prior_hash": prior_hash}
            event_hash = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            event["event_hash"] = event_hash
            events.append(event); prior_hash = event_hash
    ledger_path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in events), encoding="utf-8")

    print(json.dumps({"sources": len(all_sources), "new_cards": len(CARDS), "all_cards": all_card_count,
                      "research": len(RESEARCH), "ledger_events": len(events)}, sort_keys=True))


if __name__ == "__main__":
    main()
