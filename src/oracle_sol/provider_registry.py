"""CITADEL Multi-Provider Model Capability Inventory & Registry.

Machine-readable catalog of verified zero-cost model providers and model identities.
Zero trading roles encoded (no CALL/PUT/CHIEF assignments today).

Explicit Multi-State Verification:
- CATALOG_VISIBLE: Listed in provider documentation or API catalog.
- ZERO_COST_CATALOG_VERIFIED: Confirmed free/zero-cost in vendor pricing/terms, awaiting live test.
- LIVE_ZERO_COST_VERIFIED: Successfully executed live test with 200 OK and $0 / zero-neuron cost.
- VERIFICATION_FAILED: Explicitly rejected by provider or failed live test.

Commercial Status Classification:
- ZERO_COST_RECURRING: Daily/monthly recurring zero-cost quota (e.g. Cloudflare 10k daily Neurons).
- FREE_TIER: Permanent/ongoing free developer tier (e.g. Groq free tier, OpenRouter :free models).
- TRIAL_CREDIT: Finite promotional/developer credits (e.g. NVIDIA NIM 1,000 trial credits).
- PAID: Pay-per-token commercial billing (blocked for zero-cost routing).
- UNKNOWN: Unverified commercial status.

Quota Truth Hierarchy:
LIVE_PROVIDER_HEADERS > ACCOUNT_TELEMETRY > DOCUMENTATION > UNKNOWN
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Verification States
CATALOG_VISIBLE = "CATALOG_VISIBLE"
ZERO_COST_CATALOG_VERIFIED = "ZERO_COST_CATALOG_VERIFIED"
LIVE_ZERO_COST_VERIFIED = "LIVE_ZERO_COST_VERIFIED"
LIVE_ZERO_COST_PENDING = "LIVE_ZERO_COST_PENDING"
VERIFICATION_FAILED = "VERIFICATION_FAILED"

# Commercial Statuses
ZERO_COST_RECURRING = "ZERO_COST_RECURRING"
FREE_TIER = "FREE_TIER"
TRIAL_CREDIT = "TRIAL_CREDIT"
PROMOTIONAL_ZERO_COST = "PROMOTIONAL_ZERO_COST"
CATALOG_PROMOTIONAL_FREE = "CATALOG_PROMOTIONAL_FREE"
PROMOTION_EXPIRED = "PROMOTION_EXPIRED"
PAID = "PAID"
UNKNOWN = "UNKNOWN"

# Quota Sources
QUOTA_SOURCE_LIVE_HEADERS = "LIVE_PROVIDER_HEADERS"
QUOTA_SOURCE_ACCOUNT_TELEMETRY = "ACCOUNT_TELEMETRY"
QUOTA_SOURCE_DOCUMENTATION = "DOCUMENTATION"
QUOTA_SOURCE_UNKNOWN = "UNKNOWN"


@dataclass
class ModelCapability:
    """Detailed specifications and operational constraints for a model endpoint."""
    provider: str
    model_id: str
    display_name: str
    enabled: bool = True
    endpoint: str = ""
    # Explicit Multi-State Verification
    verification_state: str = CATALOG_VISIBLE
    free_verified: bool = False
    free_verified_at: Optional[str] = None
    # Commercial Tier Classification
    commercial_status: str = UNKNOWN
    plan_name: str = ""
    # Quota Truth Hierarchy Tracking
    quota_source: str = QUOTA_SOURCE_UNKNOWN
    documented_limits: Dict[str, Any] = field(default_factory=dict)
    observed_limits: Dict[str, Any] = field(default_factory=dict)
    context_window: int = 128000
    max_output_tokens: Optional[int] = 4096
    reasoning_support: bool = False
    structured_output_support: str = "JSON_OBJECT"  # NATIVE_JSON_SCHEMA, JSON_OBJECT, LOCAL_POST_VALIDATION
    native_json_schema_support: bool = False
    streaming_support: bool = True
    multimodal_support: bool = False
    tool_support: bool = False
    privacy_notes: str = ""
    rate_limit_source: str = ""
    finance_relevance: str = "GENERAL"
    last_health_status: str = "UNTESTED"  # HEALTHY, DEGRADED, UNAVAILABLE, GENERATION_DENIED, AWAITING_CREDENTIALS, UNTESTED
    last_health_timestamp: Optional[str] = None
    known_limitations: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.verification_state == LIVE_ZERO_COST_VERIFIED:
            self.free_verified = True
        elif self.verification_state in (CATALOG_VISIBLE, VERIFICATION_FAILED):
            self.free_verified = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ProviderRegistry:
    """Registry maintaining current zero-cost provider endpoints and model capabilities."""

    def __init__(self) -> None:
        self._models: Dict[str, ModelCapability] = {}
        self._register_default_catalog()

    def _make_key(self, provider: str, model_id: str) -> str:
        return f"{provider.lower()}::{model_id}"

    def register(self, capability: ModelCapability) -> None:
        key = self._make_key(capability.provider, capability.model_id)
        self._models[key] = capability

    def get(self, provider: str, model_id: str) -> Optional[ModelCapability]:
        return self._models.get(self._make_key(provider, model_id))

    def list_models(
        self,
        provider: Optional[str] = None,
        free_only: bool = True,
        min_verification_state: Optional[str] = None,
    ) -> List[ModelCapability]:
        res = []
        for cap in self._models.values():
            if free_only and cap.commercial_status not in (FREE_TIER, ZERO_COST_RECURRING, PROMOTIONAL_ZERO_COST, CATALOG_PROMOTIONAL_FREE):
                continue
            if provider and cap.provider.lower() != provider.lower():
                continue
            if min_verification_state == LIVE_ZERO_COST_VERIFIED:
                if cap.verification_state != LIVE_ZERO_COST_VERIFIED:
                    continue
            elif min_verification_state == ZERO_COST_CATALOG_VERIFIED:
                if cap.verification_state not in (ZERO_COST_CATALOG_VERIFIED, LIVE_ZERO_COST_VERIFIED):
                    continue
            elif free_only and not cap.free_verified and cap.verification_state not in (ZERO_COST_CATALOG_VERIFIED, LIVE_ZERO_COST_VERIFIED):
                continue
            res.append(cap)
        return res

    def update_health(self, provider: str, model_id: str, status: str) -> None:
        cap = self.get(provider, model_id)
        if cap:
            cap.last_health_status = status
            cap.last_health_timestamp = datetime.now(timezone.utc).isoformat()

    def _register_default_catalog(self) -> None:
        now_str = "2026-09-05T18:45:00Z"

        # --- GROQ ---
        self.register(ModelCapability(
            provider="groq",
            model_id="openai/gpt-oss-120b",
            display_name="GPT-OSS 120B (Groq Production)",
            endpoint="https://api.groq.com/openai/v1/chat/completions",
            verification_state=LIVE_ZERO_COST_VERIFIED,
            free_verified=True,
            free_verified_at=now_str,
            commercial_status=FREE_TIER,
            plan_name="Groq Cloud Developer Free Tier",
            quota_source=QUOTA_SOURCE_LIVE_HEADERS,
            documented_limits={"requests_per_minute": 30, "tokens_per_minute": 8000, "requests_per_day": 14400},
            observed_limits={"limit_requests": 1000, "limit_tokens": 8000},
            context_window=131072,
            max_output_tokens=4096,
            reasoning_support=True,
            structured_output_support="NATIVE_JSON_SCHEMA",
            native_json_schema_support=True,
            privacy_notes="Groq Cloud standard developer terms. Not Zero Data Retention (ZDR_MANUAL_VERIFICATION_REQUIRED).",
            rate_limit_source="x-ratelimit-* headers (RPD/daily requests info, 8000 TPM)",
            finance_relevance="Strong instruction-following and zero-shot reasoning",
            last_health_status="HEALTHY",
            last_health_timestamp=now_str,
            known_limitations=["Emits 60-110 reasoning tokens; max_output_tokens must be >= 1024 to prevent json_validate_failed truncation", "Occasional 429 during peak US market hours"],
        ))
        self.register(ModelCapability(
            provider="groq",
            model_id="qwen/qwen3.8-27b",
            display_name="Qwen 3.8 27B (Groq Preview)",
            endpoint="https://api.groq.com/openai/v1/chat/completions",
            verification_state=LIVE_ZERO_COST_VERIFIED,
            free_verified=True,
            free_verified_at=now_str,
            commercial_status=FREE_TIER,
            plan_name="Groq Cloud Developer Free Tier",
            quota_source=QUOTA_SOURCE_LIVE_HEADERS,
            documented_limits={"requests_per_minute": 30, "tokens_per_minute": 8000, "requests_per_day": 14400},
            observed_limits={"limit_requests": 1000, "limit_tokens": 8000},
            context_window=131072,
            max_output_tokens=4096,
            reasoning_support=True,
            structured_output_support="JSON_OBJECT",
            native_json_schema_support=False,
            privacy_notes="Groq Cloud preview terms.",
            rate_limit_source="x-ratelimit-* headers (1000 RPD/window info, 8000 TPM)",
            finance_relevance="Exceptional low latency market observation and fast pattern detection",
            last_health_status="HEALTHY",
            last_health_timestamp=now_str,
            known_limitations=["Preview status; potential schema hallucinations on deep nesting"],
        ))
        self.register(ModelCapability(
            provider="groq",
            model_id="openai/gpt-oss-20b",
            display_name="GPT-OSS 20B (Groq Production)",
            endpoint="https://api.groq.com/openai/v1/chat/completions",
            verification_state=LIVE_ZERO_COST_VERIFIED,
            free_verified=True,
            free_verified_at=now_str,
            commercial_status=FREE_TIER,
            plan_name="Groq Cloud Developer Free Tier",
            quota_source=QUOTA_SOURCE_LIVE_HEADERS,
            documented_limits={"requests_per_minute": 30, "tokens_per_minute": 8000, "requests_per_day": 14400},
            observed_limits={"limit_requests": 1000, "limit_tokens": 8000},
            context_window=131072,
            max_output_tokens=4096,
            reasoning_support=True,
            structured_output_support="NATIVE_JSON_SCHEMA",
            native_json_schema_support=True,
            privacy_notes="Groq Cloud standard developer terms.",
            rate_limit_source="x-ratelimit-* headers (RPD/daily requests info, 8000 TPM)",
            finance_relevance="Ultra-low latency fallback synthesizer",
            last_health_status="HEALTHY",
            last_health_timestamp=now_str,
            known_limitations=["Emits internal reasoning tokens; max_output_tokens must be >= 1024", "Lower reasoning depth than 120B"],
        ))

        # --- GOOGLE GEMINI (PRIMARY PROFILE) ---
        self.register(ModelCapability(
            provider="gemini_primary",
            enabled=False,
            model_id="gemini-3.8-flash",
            display_name="Google Gemini 3.8 Flash (Primary Profile)",
            endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
            verification_state=CATALOG_VISIBLE,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=FREE_TIER,
            plan_name="Google AI Studio Free Tier",
            quota_source=QUOTA_SOURCE_LIVE_HEADERS,
            documented_limits={"requests_per_minute": 5, "tokens_per_minute": 1000000, "requests_per_day": 20},
            observed_limits={"requests_per_minute": 5, "requests_per_day": 20, "tokens_per_minute": 1000000},
            context_window=1048576,
            max_output_tokens=65536,
            reasoning_support=True,
            structured_output_support="NATIVE_JSON_SCHEMA",
            native_json_schema_support=True,
            privacy_notes="Google AI Studio terms. Free tier logs prompt/completion for training (POLICY_BLOCKED for proprietary market data).",
            rate_limit_source="20 RPD (GenerateRequestsPerDayPerProjectPerModel-FreeTier), 5 RPM, 1,000,000 TPM",
            finance_relevance="1M context window accommodates full market days, deep multi-horizon reasoning (Project gen-lang-client-0105277208)",
            last_health_status="HEALTHY",
            last_health_timestamp=now_str,
            known_limitations=["20 RPD free tier ceiling per project; intermittent upstream 503 capacity spikes handled via client exponential backoff and multi-profile failover; modern thinkingLevel (LOW, MEDIUM, HIGH) supported. Awaiting Astra cognitive activation."],
        ))

        # --- GOOGLE GEMINI (SECONDARY PROFILE - INDEPENDENT PROJECT) ---
        self.register(ModelCapability(
            provider="gemini_secondary",
            enabled=False,
            model_id="gemini-3.8-flash",
            display_name="Google Gemini 3.8 Flash (Secondary Profile)",
            endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
            verification_state=CATALOG_VISIBLE,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=FREE_TIER,
            plan_name="Google AI Studio Free Tier",
            quota_source=QUOTA_SOURCE_LIVE_HEADERS,
            documented_limits={"requests_per_minute": 5, "tokens_per_minute": 1000000, "requests_per_day": 20},
            observed_limits={"requests_per_minute": 5, "requests_per_day": 20, "tokens_per_minute": 1000000},
            context_window=1048576,
            max_output_tokens=65536,
            reasoning_support=True,
            structured_output_support="NATIVE_JSON_SCHEMA",
            native_json_schema_support=True,
            privacy_notes="Google AI Studio Free Tier terms.",
            rate_limit_source="20 RPD (GenerateRequestsPerDayPerProjectPerModel-FreeTier), 5 RPM, 1,000,000 TPM",
            finance_relevance="Secondary independent zero-cost profile (Project 514112777776)",
            last_health_status="HEALTHY",
            last_health_timestamp=now_str,
            known_limitations=["20 RPD free tier ceiling per project; upstream 503 capacity spikes handled via client exponential backoff and multi-profile failover. Awaiting Astra cognitive activation."],
        ))

        # --- GOOGLE GEMINI (TERTIARY PROFILE - INDEPENDENT RESERVE) ---
        self.register(ModelCapability(
            provider="gemini_tertiary",
            enabled=False,
            model_id="gemini-3.8-flash",
            display_name="Google Gemini 3.8 Flash (Tertiary Profile)",
            endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
            verification_state=CATALOG_VISIBLE,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=FREE_TIER,
            plan_name="Google AI Studio Free Tier",
            quota_source=QUOTA_SOURCE_LIVE_HEADERS,
            documented_limits={"requests_per_minute": 5, "tokens_per_minute": 1000000, "requests_per_day": 20},
            observed_limits={"requests_per_minute": 5, "requests_per_day": 20, "tokens_per_minute": 1000000},
            context_window=1048576,
            max_output_tokens=65536,
            reasoning_support=True,
            structured_output_support="NATIVE_JSON_SCHEMA",
            native_json_schema_support=True,
            privacy_notes="Google AI Studio Free Tier terms.",
            rate_limit_source="20 RPD (GenerateRequestsPerDayPerProjectPerModel-FreeTier), 5 RPM, 1,000,000 TPM",
            finance_relevance="Tertiary independent zero-cost profile (Project 137181438165)",
            last_health_status="HEALTHY",
            last_health_timestamp=now_str,
            known_limitations=["20 RPD free tier ceiling per project; upstream 503 capacity spikes handled via client exponential backoff and multi-profile failover. Awaiting Astra cognitive activation."],
        ))

        # --- NVIDIA NIM ---
        self.register(ModelCapability(
            provider="nvidia",
            enabled=False,
            model_id="openai/gpt-oss-20b",
            display_name="GPT-OSS 20B (NVIDIA NIM)",
            endpoint="https://integrate.api.nvidia.com/v1/chat/completions",
            verification_state=CATALOG_VISIBLE,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=TRIAL_CREDIT,
            plan_name="NVIDIA NIM Developer Trial (1,000 Credits)",
            quota_source=QUOTA_SOURCE_DOCUMENTATION,
            documented_limits={"requests_per_minute": 40, "trial_credits": 1000},
            observed_limits={},
            context_window=131072,
            max_output_tokens=4096,
            reasoning_support=True,
            structured_output_support="JSON_OBJECT",
            native_json_schema_support=False,
            privacy_notes="NVIDIA NIM hosted developer trial terms.",
            rate_limit_source="40 RPM developer tier",
            finance_relevance="Fast synthesis fallback with sub-second latency",
            last_health_status="TRIAL_CREDIT",
            last_health_timestamp=now_str,
            known_limitations=["Trial credits pool (1,000 developer credits); not recurring free quota. Disabled for zero-cost production routing to protect $0 spend."],
        ))
        self.register(ModelCapability(
            provider="nvidia",
            enabled=False,
            model_id="meta/llama-3.2-11b-vision-instruct",
            display_name="Llama 3.2 11B Vision (NVIDIA NIM)",
            endpoint="https://integrate.api.nvidia.com/v1/chat/completions",
            verification_state=CATALOG_VISIBLE,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=TRIAL_CREDIT,
            plan_name="NVIDIA NIM Developer Trial (1,000 Credits)",
            quota_source=QUOTA_SOURCE_DOCUMENTATION,
            documented_limits={"requests_per_minute": 40, "trial_credits": 1000},
            observed_limits={},
            context_window=131072,
            max_output_tokens=4096,
            reasoning_support=False,
            structured_output_support="JSON_OBJECT",
            native_json_schema_support=False,
            privacy_notes="NVIDIA NIM hosted developer trial terms.",
            rate_limit_source="40 RPM developer tier",
            finance_relevance="High speed reasoning (<600ms latency)",
            last_health_status="TRIAL_CREDIT",
            last_health_timestamp=now_str,
            known_limitations=["Trial credits pool (1,000 developer credits); not recurring free quota. Disabled for zero-cost production routing to protect $0 spend."],
        ))
        self.register(ModelCapability(
            provider="nvidia",
            enabled=False,
            model_id="writer/palmyra-fin-70b-32k",
            display_name="Palmyra Financial 70B (Writer / NVIDIA NIM)",
            endpoint="https://integrate.api.nvidia.com/v1/chat/completions",
            verification_state=CATALOG_VISIBLE,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=TRIAL_CREDIT,
            plan_name="NVIDIA NIM Developer Trial (1,000 Credits)",
            quota_source=QUOTA_SOURCE_DOCUMENTATION,
            documented_limits={"requests_per_minute": 40, "trial_credits": 1000},
            observed_limits={},
            context_window=32768,
            max_output_tokens=4096,
            reasoning_support=True,
            structured_output_support="JSON_OBJECT",
            native_json_schema_support=False,
            privacy_notes="NVIDIA NIM hosted terms; 1,000 free trial developer credits.",
            rate_limit_source="NVIDIA developer tier: 40 RPM",
            finance_relevance="Pre-trained and fine-tuned on financial market reasoning, SEC filings, and macro contracts",
            last_health_status="TRIAL_CREDIT",
            last_health_timestamp=now_str,
            known_limitations=["32K context window; trial credits pool (1,000 developer credits); not recurring free quota. Disabled for zero-cost production routing to protect $0 spend."],
        ))

        # --- OPENROUTER ---
        self.register(ModelCapability(
            provider="openrouter",
            model_id="inclusionai/ling-3.0-flash-fin:free",
            display_name="InclusionAI Ling 3.0 Flash Financial (:free)",
            endpoint="https://openrouter.ai/api/v1/chat/completions",
            verification_state=LIVE_ZERO_COST_VERIFIED,
            free_verified=True,
            free_verified_at=now_str,
            commercial_status=FREE_TIER,
            plan_name="OpenRouter Free Models Tier ($0 Model Routing)",
            quota_source=QUOTA_SOURCE_LIVE_HEADERS,
            documented_limits={"cost_per_token": 0.0, "data_collection": "deny"},
            observed_limits={"cost": 0.0},
            context_window=262144,
            max_output_tokens=8192,
            reasoning_support=True,
            structured_output_support="LOCAL_POST_VALIDATION",
            native_json_schema_support=False,
            privacy_notes="Enforces provider.data_collection='deny' and provider.allow_fallbacks=False to prevent upstream provider data collection or paid routing.",
            rate_limit_source="OpenRouter free rate limits & x-ratelimit-* headers",
            finance_relevance="Finance-specialized foundation model tailored for financial entity recognition, order flow balance, and ratio analysis",
            last_health_status="HEALTHY",
            last_health_timestamp=now_str,
            known_limitations=["Novita backend upstream rejects API-level response_format; must use LOCAL_POST_VALIDATION with prompt-level schema", "Free tier upstream queue delays during peak traffic"],
        ))
        self.register(ModelCapability(
            provider="openrouter",
            enabled=False,
            model_id="z-ai/glm-5.2:free",
            display_name="GLM 5.2 (:free)",
            endpoint="https://openrouter.ai/api/v1/chat/completions",
            verification_state=VERIFICATION_FAILED,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=FREE_TIER,
            plan_name="OpenRouter Free Models Tier ($0 Model Routing)",
            quota_source=QUOTA_SOURCE_DOCUMENTATION,
            documented_limits={"cost_per_token": 0.0, "data_collection": "deny"},
            observed_limits={},
            context_window=256000,
            max_output_tokens=8192,
            reasoning_support=True,
            structured_output_support="JSON_OBJECT",
            native_json_schema_support=False,
            privacy_notes="Enforces provider.data_collection='deny'.",
            rate_limit_source="OpenRouter free rate limits",
            finance_relevance="High reasoning capacity, strong logical deduction across multi-condition inputs",
            last_health_status="FREE_ROUTE_RETIRED",
            last_health_timestamp=now_str,
            known_limitations=["Free route retired upstream on OpenRouter; only paid variants exist. Disabled for zero-cost routing."],
        ))

        # --- CLOUDFLARE WORKERS AI (ACTIVE SCOPED TOKEN) ---
        self.register(ModelCapability(
            provider="cloudflare",
            model_id="@cf/meta/llama-3.1-8b-instruct-fp8",
            display_name="Cloudflare Workers AI Llama 3.1 8B Instruct FP8",
            endpoint="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions",
            verification_state=LIVE_ZERO_COST_VERIFIED,
            free_verified=True,
            free_verified_at=now_str,
            commercial_status=ZERO_COST_RECURRING,
            plan_name="Cloudflare Workers AI Free Tier (10k Daily Neurons)",
            quota_source=QUOTA_SOURCE_ACCOUNT_TELEMETRY,
            documented_limits={"daily_neuron_allowance": 10000},
            observed_limits={"sample_neurons_consumed": 1.00},
            context_window=131072,
            max_output_tokens=4096,
            reasoning_support=False,
            structured_output_support="JSON_OBJECT",
            native_json_schema_support=False,
            privacy_notes="Cloudflare Workers AI edge transient inference. Scoped API token active.",
            rate_limit_source="Daily free allowance: 10,000 Neurons/day",
            finance_relevance="Edge inference with sub-second execution overhead",
            last_health_status="HEALTHY",
            last_health_timestamp=now_str,
            known_limitations=["10k Neurons/day free floor (~1.00 neuron per test call); requires standard User-Agent header to avoid Cloudflare WAF block 1010"],
        ))
        self.register(ModelCapability(
            provider="cloudflare",
            enabled=False,
            model_id="@cf/zai-org/glm-5.3-flash",
            display_name="Cloudflare Workers AI GLM 5.3 Flash",
            endpoint="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions",
            verification_state=VERIFICATION_FAILED,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=ZERO_COST_RECURRING,
            plan_name="Cloudflare Workers AI Free Tier (10k Daily Neurons)",
            quota_source=QUOTA_SOURCE_DOCUMENTATION,
            documented_limits={"daily_neuron_allowance": 10000},
            observed_limits={},
            context_window=131072,
            max_output_tokens=4096,
            reasoning_support=True,
            structured_output_support="JSON_OBJECT",
            native_json_schema_support=False,
            privacy_notes="Cloudflare Workers AI edge transient inference.",
            rate_limit_source="Daily free allowance: 10,000 Neurons/day",
            finance_relevance="High efficiency reasoning on Cloudflare edge network",
            last_health_status="PLAN_GATED",
            last_health_timestamp=now_str,
            known_limitations=["Model is not available on Workers Free plan (HTTP 403 AiError 5035: Upgrade to access). Disabled."],
        ))

        # --- EXPERIENTIAL LABS (PROMOTIONAL FREE TIER - COGNITIVELY UNASSIGNED FOR ASTRA) ---
        self.register(ModelCapability(
            provider="experiential",
            enabled=False,
            model_id="gpt-6-astra",
            display_name="GPT-6 Astra (Experiential Labs Promotional)",
            endpoint="https://api.experientiallabs.ai/v1/chat/completions",
            verification_state=LIVE_ZERO_COST_PENDING,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=CATALOG_PROMOTIONAL_FREE,
            plan_name="Experiential Labs Promotional Free Tier (375k In / 75k Out Daily)",
            quota_source=QUOTA_SOURCE_ACCOUNT_TELEMETRY,
            documented_limits={"free_input_tokens_per_day": 375000, "free_output_tokens_per_day": 75000, "free_input_tokens_per_hour": 150000, "free_output_tokens_per_hour": 30000},
            observed_limits={},
            context_window=1050000,
            max_output_tokens=128000,
            reasoning_support=True,
            structured_output_support="NATIVE_JSON_SCHEMA",
            native_json_schema_support=True,
            privacy_notes="OpenAI upstream default retention. Not Zero Data Retention (PRIVACY_RESTRICTED_FOR_PRODUCTION). Blocked from receiving proprietary CITADEL order flow.",
            rate_limit_source="Experiential Labs Promotional Quota (375k in / 75k out daily)",
            finance_relevance="1.05M context frontier reasoning model",
            last_health_status="ORG_REVIEW_BLOCKED",
            last_health_timestamp=now_str,
            known_limitations=["Promotional daily allowance (375k in/75k out); not permanent free infrastructure; org review currently blocks inference (HTTP 429 org_under_review); not ZDR; unassigned for Astra."],
        ))
        self.register(ModelCapability(
            provider="experiential",
            enabled=False,
            model_id="gpt-5.6-luna",
            display_name="GPT-5.6 Luna (Experiential Labs Promotional)",
            endpoint="https://api.experientiallabs.ai/v1/chat/completions",
            verification_state=LIVE_ZERO_COST_PENDING,
            free_verified=False,
            free_verified_at=None,
            commercial_status=CATALOG_PROMOTIONAL_FREE,
            plan_name="Experiential Labs Promotional Free Tier ($5.00/day)",
            quota_source=QUOTA_SOURCE_ACCOUNT_TELEMETRY,
            documented_limits={"per_org_cap_micro_usd": 5000000},
            observed_limits={},
            context_window=1050000,
            max_output_tokens=128000,
            reasoning_support=True,
            structured_output_support="NATIVE_JSON_SCHEMA",
            native_json_schema_support=True,
            privacy_notes="OpenAI/OpenRouter upstream. Not Zero Data Retention (PRIVACY_RESTRICTED_FOR_PRODUCTION). Sanitized observable packet enforced.",
            rate_limit_source="Experiential Labs Promotional Quota ($5.00/day allowance)",
            finance_relevance="1.05M context frontier reasoning model",
            last_health_status="ORG_REVIEW_BLOCKED",
            last_health_timestamp=now_str,
            known_limitations=["Single production cognitive analyst qualified via prospective live shadow (4/4 passed). Zero cash cost verified ($0.000000). Privacy sanitizer strictly enforced."],
        ))
        self.register(ModelCapability(
            provider="experiential",
            enabled=False,
            model_id="deepseek-v4-flash",
            display_name="DeepSeek V4 Flash (Experiential Labs Promotional)",
            endpoint="https://api.experientiallabs.ai/v1/chat/completions",
            verification_state=LIVE_ZERO_COST_PENDING,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=CATALOG_PROMOTIONAL_FREE,
            plan_name="Experiential Labs Promotional Free Tier ($5.00/day)",
            quota_source=QUOTA_SOURCE_ACCOUNT_TELEMETRY,
            documented_limits={"per_org_cap_micro_usd": 5000000},
            observed_limits={},
            context_window=1048576,
            max_output_tokens=384000,
            reasoning_support=True,
            structured_output_support="JSON_OBJECT",
            native_json_schema_support=False,
            privacy_notes="Experiential Cloud and Fireworks rungs support Zero Data Retention (ZDR_ELIGIBLE). OpenRouter rung is not ZDR.",
            rate_limit_source="Experiential Labs Promotional Quota ($5.00/day allowance)",
            finance_relevance="High-speed 1M context reasoning engine with ultra-low latency",
            last_health_status="ORG_REVIEW_BLOCKED",
            last_health_timestamp=now_str,
            known_limitations=["Promotional $5.00/day cap; org review currently blocks inference (HTTP 429 org_under_review); waterfall has mixed ZDR rungs; unassigned for Astra."],
        ))
        self.register(ModelCapability(
            provider="experiential",
            enabled=False,
            model_id="qwen3.8-27b",
            display_name="Qwen 3.8 27B (Experiential Labs Promotional)",
            endpoint="https://api.experientiallabs.ai/v1/chat/completions",
            verification_state=LIVE_ZERO_COST_PENDING,
            free_verified=False,
            free_verified_at=now_str,
            commercial_status=CATALOG_PROMOTIONAL_FREE,
            plan_name="Experiential Labs Promotional Free Tier ($5.00/day)",
            quota_source=QUOTA_SOURCE_ACCOUNT_TELEMETRY,
            documented_limits={"per_org_cap_micro_usd": 5000000},
            observed_limits={},
            context_window=1000000,
            max_output_tokens=131072,
            reasoning_support=True,
            structured_output_support="JSON_OBJECT",
            native_json_schema_support=False,
            privacy_notes="Experiential Cloud and Fireworks rungs support Zero Data Retention (ZDR_ELIGIBLE). Cerebras fallback is not ZDR.",
            rate_limit_source="Experiential Labs Promotional Quota ($5.00/day allowance)",
            finance_relevance="1M context mathematical and financial reasoning foundation model",
            last_health_status="ORG_REVIEW_BLOCKED",
            last_health_timestamp=now_str,
            known_limitations=["Promotional $5.00/day cap; org review currently blocks inference (HTTP 429 org_under_review); Cerebras fallback is not ZDR; unassigned for Astra."],
        ))


GLOBAL_PROVIDER_REGISTRY = ProviderRegistry()
