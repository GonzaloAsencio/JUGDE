"""Token usage capture (Fase 5, PR1) — providers report what they spent.

Contract under test:
- ``Usage`` is additive metadata: real counts from the provider APIs when
  available (``response.usage`` / ``usage_metadata``), a chars/4 estimate
  marked ``estimated=True`` otherwise. Estimation can degrade accuracy but
  must NEVER break or block a query.
- ``LLMProvider.generate_metered`` returns ``(answer, Usage | None)``; the
  default falls back to ``generate()`` with no usage so existing doubles work.
- ``QueryResponse.usage`` is additive and optional: cache hits carry None,
  fresh generations carry HyDE (estimated) + generation (real or estimated),
  the empty-Answer retry sums BOTH attempts.
- The cache payload gains ``total_tokens`` (additive; old entries without it
  still load).
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.rag.generation import estimate_usage
from app.rag.pipeline import answer_question, answer_question_stream
from app.rag.retrieval import Chunk
from app.rag.schemas import QueryResponse, Usage
from tests.conftest import FakeEmbedder, FakeLLMProvider, FakePool


def _make_chunk(similarity: float = 0.9) -> Chunk:
    return Chunk(
        id="abc123", content="Some content about the rules.", section="820. Repeat",
        parent_section=None, source_type="rulebook", similarity=similarity,
    )


def _fake_settings():
    s = MagicMock()
    s.corpus_version = "v1"
    s.top_k = 5
    s.top_k_fetch = 15
    s.rrf_k = 60
    s.prompt_version = "v7"
    s.cache_ttl_s = 86400
    # Pin every flag to its real default — a truthy MagicMock silently runs
    # the test with the feature ON (see test_pipeline.py).
    s.enable_reranker = False
    s.keyword_family_extra = 0
    s.skip_hyde_when_routed = False
    s.hard_query_routing = False
    s.hyde_model = None
    return s


_ANSWER = "Reasoning:\n- 820 applies.\n\nAnswer:\nYes, it repeats."
_EMPTY_ANSWER = "Reasoning:\n- 820 applies.\n\nAnswer:"
_REAL_USAGE = Usage(prompt_tokens=100, output_tokens=20, total_tokens=120)


class _MeteredProvider(FakeLLMProvider):
    """Returns scripted answers WITH real usage, one per generate_metered call."""

    def __init__(self, answers=None, usage=_REAL_USAGE):
        self._answers = answers or [_ANSWER]
        self._usage = usage
        self.calls = 0

    def generate_metered(self, question, chunks, *, extra_system=""):
        answer = self._answers[min(self.calls, len(self._answers) - 1)]
        self.calls += 1
        return answer, self._usage


def _ask(provider, *, cached=None, settings=None):
    settings = settings or _fake_settings()
    with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
        with patch("app.rag.pipeline.get_cached", return_value=cached):
            with patch("app.rag.pipeline.set_cached") as mock_set:
                response = answer_question(
                    "What happens when both players do nothing?", FakeEmbedder(), FakePool(), provider, settings,
                )
    return response, mock_set


# ---------------------------------------------------------------------------
# Usage model + estimation
# ---------------------------------------------------------------------------


def test_usage_addition_sums_counts_and_ors_estimated():
    real = Usage(prompt_tokens=10, output_tokens=5, total_tokens=15)
    est = Usage(prompt_tokens=2, output_tokens=1, total_tokens=3, estimated=True)

    combined = real + est

    assert combined == Usage(prompt_tokens=12, output_tokens=6, total_tokens=18, estimated=True)


def test_estimate_usage_uses_chars_over_four_and_marks_estimated():
    usage = estimate_usage("x" * 40, "y" * 8)

    assert usage == Usage(prompt_tokens=10, output_tokens=2, total_tokens=12, estimated=True)


# ---------------------------------------------------------------------------
# Real capture from the provider APIs
# ---------------------------------------------------------------------------


def test_openai_compat_metered_captures_response_usage():
    from app.rag.generation import _call_openai_compat_raw_metered

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ans"))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=4, total_tokens=15),
    )
    with patch("openai.OpenAI", return_value=fake_client):
        answer, usage = _call_openai_compat_raw_metered(
            "q?", [], base_url="http://x", api_key="k", model="m",
            temperature=0.1, timeout_s=10.0,
        )

    assert answer == "ans"
    assert usage == Usage(prompt_tokens=11, output_tokens=4, total_tokens=15)


def test_gemini_metered_captures_usage_metadata():
    from app.rag.generation import _call_gemini_metered

    response = SimpleNamespace(
        text="ans",
        candidates=[],
        usage_metadata=SimpleNamespace(
            prompt_token_count=7, candidates_token_count=2, total_token_count=9,
        ),
    )
    client = MagicMock()
    client.models.generate_content.return_value = response

    answer, usage = _call_gemini_metered(client, "gemini-x", "prompt")

    assert answer == "ans"
    assert usage == Usage(prompt_tokens=7, output_tokens=2, total_tokens=9)


def test_generate_metered_default_returns_answer_without_usage():
    assert FakeLLMProvider().generate_metered("q?", []) == ("Fake answer for testing.", None)


# ---------------------------------------------------------------------------
# Blocking pipeline: QueryResponse.usage
# ---------------------------------------------------------------------------


def test_answer_question_reports_real_usage_when_provider_meters():
    response, _ = _ask(_MeteredProvider())

    assert response.usage == _REAL_USAGE.model_copy(update={"llm_model": "fake-model"})


def test_answer_question_estimates_usage_when_provider_does_not_meter():
    response, _ = _ask(FakeLLMProvider())

    assert response.usage is not None
    assert response.usage.estimated is True
    assert response.usage.total_tokens > 0


def test_empty_answer_retry_sums_both_attempts():
    provider = _MeteredProvider(answers=[_EMPTY_ANSWER, _ANSWER])

    response, _ = _ask(provider)

    assert provider.calls == 2
    assert response.usage == (_REAL_USAGE + _REAL_USAGE).model_copy(update={"llm_model": "fake-model"})


def test_hyde_usage_is_estimated_and_added_to_real_generation_usage():
    class _HydeMetered(_MeteredProvider):
        def hyde(self, question):
            return "A hypothetical answer about repeating."

    response, _ = _ask(_HydeMetered())

    assert response.usage.estimated is True, "any estimated component marks the sum"
    assert response.usage.total_tokens > _REAL_USAGE.total_tokens


def test_cache_hit_carries_no_usage():
    cached = json.dumps({"answer": "Cached.", "citations": [], "confidence": 0.8, "total_tokens": 99})

    response, _ = _ask(_MeteredProvider(), cached=cached)

    assert response.cache_hit is True
    assert response.answer == "Cached."  # additive payload field must not break old/new entries
    assert response.usage is None


def test_cache_payload_includes_total_tokens():
    _, mock_set = _ask(_MeteredProvider())

    payload = json.loads(mock_set.call_args.args[1])
    assert payload["total_tokens"] == _REAL_USAGE.total_tokens


# ---------------------------------------------------------------------------
# Streaming pipeline: usage on the final event
# ---------------------------------------------------------------------------


def _collect_stream(provider):
    events = []
    with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                for event in answer_question_stream(
                    "What happens when both players do nothing?", FakeEmbedder(), FakePool(), provider, _fake_settings(),
                ):
                    events.append(event)
    return events


def test_stream_final_reports_real_usage_when_provider_delivers_it():
    class _UsageStreaming(FakeLLMProvider):
        def generate_stream(self, question, chunks, *, extra_system="", on_usage=None):
            yield _ANSWER
            if on_usage is not None:
                on_usage(Usage(prompt_tokens=50, output_tokens=5, total_tokens=55))

    events = _collect_stream(_UsageStreaming())
    final = events[-1][1]

    assert isinstance(final, QueryResponse)
    assert final.usage == Usage(prompt_tokens=50, output_tokens=5, total_tokens=55, llm_model="fake-model")


def test_stream_final_estimates_usage_for_legacy_providers_without_on_usage():
    class _LegacyStreaming(FakeLLMProvider):
        def generate_stream(self, question, chunks, *, extra_system=""):
            yield _ANSWER

    events = _collect_stream(_LegacyStreaming())
    final = events[-1][1]

    assert final.usage is not None
    assert final.usage.estimated is True


# ---------------------------------------------------------------------------
# Streamers: on_usage fires when the API attaches usage to the stream
# ---------------------------------------------------------------------------


def test_stream_openai_compat_reports_usage_from_trailing_chunk():
    from app.rag.generation import _stream_openai_compat_raw

    delta = MagicMock()
    delta.choices = [MagicMock(delta=MagicMock(content="Hi"))]
    trailing = SimpleNamespace(
        choices=[], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3, total_tokens=13),
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = iter([delta, trailing])

    captured = []
    with patch("openai.OpenAI", return_value=fake_client):
        out = list(_stream_openai_compat_raw(
            "q?", [], base_url="http://x", api_key="k", model="m",
            temperature=0.1, timeout_s=10.0, on_usage=captured.append,
        ))

    assert out == ["Hi"]
    assert captured == [Usage(prompt_tokens=10, output_tokens=3, total_tokens=13)]


def test_stream_gemini_reports_usage_from_last_chunk_metadata():
    from app.rag.generation import _stream_gemini

    chunk = SimpleNamespace(
        text="Hi",
        usage_metadata=SimpleNamespace(
            prompt_token_count=7, candidates_token_count=2, total_token_count=9,
        ),
    )
    client = MagicMock()
    client.models.generate_content_stream.return_value = iter([chunk])

    captured = []
    out = list(_stream_gemini(
        client, "gemini-x", "prompt",
        temperature=0.1, timeout_s=10.0, max_output_tokens=256, on_usage=captured.append,
    ))

    assert out == ["Hi"]
    assert captured == [Usage(prompt_tokens=7, output_tokens=2, total_tokens=9)]
