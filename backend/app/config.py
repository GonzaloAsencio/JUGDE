from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    gemini_api_key: str | None = None
    top_k: int = 5
    model_name: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    corpus_version: str | None = None
    # -latest alias on purpose: Google retired the gemini-2.0-flash free tier
    # (limit: 0) and closed gemini-2.5-* to new users; a pinned retired model
    # here means every request 429s until someone notices.
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_temperature: float = 0.1
    gemini_timeout_s: float = 30.0
    # Ceiling for the answer-generation call, the only LLM call that had no
    # output cap (HyDE: 160, rewrite: 120). Output tokens are the expensive
    # side. If answers start truncating, the existing gemini.max_tokens warning
    # fires — raise this instead of removing it. Applies to both providers.
    max_output_tokens: int = 1024
    top_k_fetch: int = 15
    rrf_k: int = 60
    # Flipped to True after the 2026-07-10 eval gate: deterministic recall
    # 9/15 -> 12/15 (60% -> 80%) with zero losses, at zero LLM tokens (local
    # CPU cross-encoder, ~80MB RAM). Opt out per-deploy via ENABLE_RERANKER.
    enable_reranker: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_pool_size: int = 15
    # 3.5 keyword family completion: max sibling chunks of a detected keyword's
    # rule family appended BEYOND top_k (families are 2-9 chunks, ~200-950
    # tokens). Flipped to 8 after prod validation 2026-07-13 (eval-030: 8
    # citations, LLM reasons over 809.1.c/d). 0 = off, byte-identical assembly.
    keyword_family_extra: int = 8

    # 4.2+4.3 hard-query routing: deterministic classifier (>=2 cards or >=2
    # keywords) sends hard queries to a thinking model with the FULL rulebook
    # stuffed into the context. Flipped to True after prod validation
    # 2026-07-13 (eval-014 cites 383.3.d.1, 23.6s, zero Gemini 429s in soak).
    # Gemini-only: requires llm_provider=gemini.
    hard_query_routing: bool = True
    # 3.11.1a: opens the (1 card, 1 keyword) cell of is_hard_query. Probed
    # 3W/0L with zero product code (scripts/routing_threshold_probe.py):
    # brings eval-020/030/037's missing gold rules into the context, costs no
    # gold ref anywhere, coverage 22/26 -> 25/26. OFF until a real eval proves
    # the extra context yields better ANSWERS — the probe measures presence,
    # not correctness. Flipping it moves routing 21/40 -> 27/40 on the eval
    # set against a ~20 req/day free tier, and the eval set is enriched with
    # hard questions so that ratio does NOT predict production traffic.
    hard_routing_relaxed: bool = False
    hard_gemini_model: str = "gemini-3.5-flash"
    # Routed calls carry ~80K prompt tokens and think before answering: the
    # 2026-07-13 probe measured 18-32s on a small sample, but the 2026-07-14
    # eval showed real-world latency spreading up to 58s with 6/21 hard
    # queries breaching the old 60s cutoff by only a few seconds — the probe
    # undersampled Gemini's variance, not a context-size regression (rulebook.md
    # unchanged since #58). Raised to give headroom above observed p99.
    hard_timeout_s: float = 90.0
    # Thinking models spend the output budget on thoughts; 1024 strangles them.
    hard_max_output_tokens: int = 8192

    # 2.2 HyDE model: the HyDE passage is 2-3 throwaway sentences used only to
    # embed a second retrieval arm — it does not need the answer model. None =
    # use the main model (byte-identical to pre-2.2 behaviour).
    hyde_model: str | None = None

    # 2.1 skip HyDE on routed queries. A routed (hard) query REPLACES its
    # retrieved context with the stuffed rulebook (see pipeline.answer_question:
    # `chunks = stuffed`), so the HyDE arm it just paid an LLM call to build is
    # thrown away. Skipping it saves one LLM call per hard query for free.
    #
    # This replaces the plan's original 2.1 ("skip HyDE when the raw cosine is
    # already high"), which was KILLED BY MEASUREMENT: on the eval set the raw
    # best cosine does not separate "gold retrieved" from "gold missed" at all
    # (eval-037 scores 0.7007 — 2nd highest — with its gold absent from the
    # top-15; eval-010 scores the LOWEST at 0.5277 with its gold at rank 1).
    # Any threshold high enough to be safe (>=0.75) skips HyDE on 0/40
    # questions; any threshold low enough to save calls strips HyDE from
    # exactly the hard questions that need it most.
    #
    # Trade-off this DOES have: semantic_confidence for a routed query is then
    # computed from the raw arm alone. That number is already of dubious meaning
    # for routed queries (their context isn't what retrieval returned), but it
    # does move — hence the flag, and the eval gate.
    skip_hyde_when_routed: bool = False

    # LLM provider: "gemini" (default) | "openai_compat" (Groq, LM Studio, Ollama, etc.)
    llm_provider: str = "gemini"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    @field_validator("corpus_version", mode="after")
    @classmethod
    def _strip_corpus_version(cls, v: str | None) -> str | None:
        # Espacios accidentales en la env var rompen el match exacto
        # WHERE corpus_version = %s contra la DB. Normalizamos siempre.
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _check_provider_fields(self):
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("gemini_api_key is required when llm_provider=gemini")
        # Fail-closed, like proxy_shared_secret: the hard provider is
        # Gemini-only regardless of the MAIN provider (prod runs Groq/
        # openai_compat as main). An operator flipping the flag without the
        # key must get a loud startup error — the pipeline's never-raise
        # fallbacks would otherwise hide a routing path that never routes.
        if self.hard_query_routing and not self.gemini_api_key:
            raise ValueError(
                "hard_query_routing requires gemini_api_key (the hard provider is Gemini-only)"
            )
        if self.llm_provider == "openai_compat":
            missing = [name for name, val in [
                ("llm_base_url", self.llm_base_url),
                ("llm_api_key", self.llm_api_key),
                ("llm_model", self.llm_model),
            ] if not val]
            if missing:
                raise ValueError(f"openai_compat requires: {missing}")
        return self

    @model_validator(mode="after")
    def _require_secret_in_prod(self):
        # Fail-closed: the auth middleware disables itself when
        # proxy_shared_secret is None. In production that would silently expose
        # the whole backend (and burn the LLM quota) on a misconfigured deploy.
        # Refuse to start instead of booting "healthy" but wide open.
        if self.app_env == "production" and not self.proxy_shared_secret:
            raise ValueError(
                "proxy_shared_secret is required when app_env=production (fail-closed auth)"
            )
        return self

    # Runtime environment
    app_env: str = "development"

    # Shared secret between the Next.js proxy and this backend.
    # When set, every endpoint except shallow /health requires the
    # X-Proxy-Secret header. When None, auth is disabled (local dev).
    proxy_shared_secret: str | None = None

    # Upstash Redis (optional — cache disabled if not set)
    upstash_redis_url: str | None = None
    upstash_redis_token: str | None = None

    # Langfuse (optional — tracing disabled if not set)
    langfuse_secret_key: str | None = None
    langfuse_public_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Sentry (optional — error reporting disabled if not set)
    sentry_dsn: str | None = None
    sentry_sample_rate: float = 0.1

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_per_min: int = 10
    rate_limit_per_day: int = 100

    # Cache
    cache_ttl_s: int = 86400

    # 2.3 semantic cache: on an exact-key miss, reuse the answer of the nearest
    # already-answered question (pgvector ANN over cached_questions, migration
    # 007). The exact key is a SHA-256, so today every paraphrase pays a full
    # LLM call — that is what exhausts the free tier.
    #
    # Default OFF: a false positive here serves the answer to a DIFFERENT
    # question, so it ships dark and flips only after an eval gate, the same
    # two-step used by the reranker (#42 -> #46) and hard routing (#58 -> #63).
    #
    # HARD queries are never eligible — not out of caution, but because
    # scripts/semantic_cache_probe.py proved no safe threshold exists for them
    # (eval-013 vs eval-014: cosine 0.982, OPPOSITE rulings). See
    # pipeline._semantic_cache_is_safe.
    semantic_cache_enabled: bool = False
    # Cosine floor for a match, measured — not guessed — by
    # scripts/semantic_cache_probe.py on the non-hard subset of the eval set:
    #   ceiling (most similar DIFFERENT questions) = 0.7633
    #   floor   (least similar SELF-paraphrase)    = 0.8739
    # 0.85 sits inside that band: it rejects every different-question pair on the
    # eval set while still catching the rewordings the cache exists to catch.
    semantic_cache_threshold: float = 0.85
    # v7: added a third few-shot example teaching chain placement-order vs
    # LIFO resolution-order (383.3.d.1) — the model was inverting these.
    # Bumping invalidates the response cache — the version is part of the key.
    prompt_version: str = "v7"

    # 2.6 concise reasoning: rule 7 makes a Reasoning section mandatory, which is
    # what lifts the hard bucket — but on a direct one-rule lookup it just pays
    # output tokens (the expensive side) to restate the obvious. When on, simple
    # queries (not routed, no multi-card scaffold) get a 3-bullet cap. The
    # section is CAPPED, never removed: dropping it would undo the v6/v7
    # chaining gains and break the Reasoning:/Answer: parsing.
    #
    # Default OFF, and this is the riskiest flag in Phase 2 — it is the only one
    # that changes what the model is ASKED, so it can only be judged by the eval
    # (output tokens down AND the hard bucket unmoved). It carries its own cache
    # namespace (see pipeline.answer_question) so flipping it never serves
    # verbose answers as concise ones or vice versa.
    concise_reasoning: bool = False

    # DB connection pool sizing. maxconn must not exceed the database's
    # max_connections; a worker that finds the pool exhausted gets a fast 503
    # (see the query handler) instead of blocking.
    db_pool_min: int = 1
    db_pool_max: int = 10

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
