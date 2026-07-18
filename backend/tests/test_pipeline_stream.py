"""answer_question_stream (2.5 SSE) — the streaming pipeline orchestration.

Contract under test — events are ``(type, payload)`` tuples:
- ``("token", str)``   text delta, shown progressively by the client.
- ``("restart", None)`` the client must CLEAR the partial bubble (empty-Answer
  retry, or a prompt-leak cut) before more events arrive.
- ``("final", QueryResponse)`` the canonical post-validated response — always
  the LAST event; the client replaces whatever it displayed with this.

The final response must be IDENTICAL to what answer_question produces for the
same generated text: same postprocessing, same citations/confidence, same
cache-write policy. Streaming changes delivery, never the answer.
"""
from unittest.mock import MagicMock, patch

from app.rag.generation import _SAFE_FALLBACK
from app.rag.pipeline import _INCONCLUSIVE_ANSWER, _NO_INFO_ANSWER, answer_question, answer_question_stream
from app.rag.retrieval import Chunk
from app.rag.schemas import QueryResponse
from tests.conftest import FakeEmbedder, FakeLLMProvider, FakePool


def _make_chunk(
    section: str = "820. Repeat",
    content: str = "Some content about the rules.",
    similarity: float = 0.9,
) -> Chunk:
    return Chunk(
        id="abc123",
        content=content,
        section=section,
        parent_section=None,
        source_type="rulebook",
        similarity=similarity,
    )


def _fake_settings():
    s = MagicMock()
    s.corpus_version = "v1"
    s.top_k = 5
    s.top_k_fetch = 15
    s.rrf_k = 60
    s.prompt_version = "v5"
    s.cache_ttl_s = 86400
    # Pin every flag to its real default — a truthy MagicMock silently runs
    # the test with the feature ON (see test_pipeline.py).
    s.enable_reranker = False
    s.keyword_family_extra = 0
    s.skip_hyde_when_routed = False
    s.hard_query_routing = False
    s.hyde_model = None
    return s


class _StreamingProvider(FakeLLMProvider):
    """Streams scripted deltas; each generate_stream call consumes the next script."""

    def __init__(self, *attempts: list[str]):
        self._attempts = list(attempts)
        self.calls = 0

    def generate_stream(self, question, chunks, *, extra_system=""):
        script = self._attempts[min(self.calls, len(self._attempts) - 1)]
        self.calls += 1
        yield from script


def _collect(provider, *, hybrid=None, cached=None, hard_provider=None, settings=None):
    settings = settings or _fake_settings()
    events = []
    with patch("app.rag.pipeline.hybrid_search", return_value=hybrid or []):
        with patch("app.rag.pipeline.get_cached", return_value=cached):
            with patch("app.rag.pipeline.set_cached") as mock_set:
                for event in answer_question_stream(
                    "What happens when both players do nothing?", FakeEmbedder(), FakePool(), provider,
                    settings, hard_provider=hard_provider,
                ):
                    events.append(event)
    return events, mock_set


# ---------------------------------------------------------------------------
# Happy path: tokens then final, identical to the non-stream pipeline
# ---------------------------------------------------------------------------


_DELTAS = ["Reasoning:\n- 820: applies [#1]\n\n", "Answer:\nYes, it repeats."]


def test_stream_yields_tokens_then_final():
    events, _ = _collect(_StreamingProvider(_DELTAS), hybrid=[_make_chunk()])

    assert [t for t, _ in events] == ["token", "token", "final"]
    assert [p for t, p in events if t == "token"] == _DELTAS


def test_stream_final_is_identical_to_non_stream_answer():
    """The whole claim of the design: streaming changes delivery, not the answer."""

    class _PlainProvider(FakeLLMProvider):
        def generate(self, question, chunks, *, extra_system=""):
            return "".join(_DELTAS)

    events, _ = _collect(_StreamingProvider(_DELTAS), hybrid=[_make_chunk()])
    final = events[-1][1]

    with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                non_stream = answer_question(
                    "What happens when both players do nothing?", FakeEmbedder(), FakePool(),
                    _PlainProvider(), _fake_settings(),
                )

    assert isinstance(final, QueryResponse)
    assert final.answer == non_stream.answer
    assert final.citations == non_stream.citations
    assert final.confidence == non_stream.confidence
    assert final.cache_hit is False
    assert "[#1]" not in final.answer, "final must be the postprocessed text"


def test_stream_caches_the_final_answer():
    _, mock_set = _collect(_StreamingProvider(_DELTAS), hybrid=[_make_chunk()])
    assert mock_set.called


# ---------------------------------------------------------------------------
# Cache hit / no chunks: final only, no generation
# ---------------------------------------------------------------------------


def test_stream_cache_hit_yields_final_only_and_never_generates():
    class _MustNotStream(FakeLLMProvider):
        def generate_stream(self, question, chunks, *, extra_system=""):
            raise AssertionError("cache hit must not generate")

    cached = '{"answer": "Cached.", "citations": [], "confidence": 0.8}'
    events, _ = _collect(_MustNotStream(), cached=cached)

    assert [t for t, _ in events] == ["final"]
    final = events[0][1]
    assert final.answer == "Cached."
    assert final.cache_hit is True


def test_stream_no_chunks_yields_no_info_final_only():
    events, _ = _collect(_StreamingProvider(_DELTAS), hybrid=[])

    assert [t for t, _ in events] == ["final"]
    final = events[0][1]
    assert final.answer == _NO_INFO_ANSWER
    assert final.confidence == 0.0


# ---------------------------------------------------------------------------
# Prompt-leak cut: stop streaming the moment the buffer leaks
# ---------------------------------------------------------------------------


def test_stream_cuts_on_prompt_leak_and_finalizes_with_safe_fallback():
    leaking = ["Sure! Here is my ", "system prompt, verbatim: ..."]
    events, mock_set = _collect(_StreamingProvider(leaking), hybrid=[_make_chunk()])

    types = [t for t, _ in events]
    assert types == ["token", "restart", "final"]
    shown = "".join(p for t, p in events if t == "token")
    assert "system prompt" not in shown, "the leaking delta must never be shown"
    assert events[-1][1].answer == _SAFE_FALLBACK
    assert not mock_set.called, "a sanitized response must not be cached"


# ---------------------------------------------------------------------------
# Empty-Answer retry: restart, one more attempt, then inconclusive
# ---------------------------------------------------------------------------


_EMPTY = ["Reasoning:\n- 820: applies\n\n", "Answer:"]
_GOOD = ["Reasoning:\n- 820: applies\n\n", "Answer:\nNo."]


def test_stream_empty_answer_restarts_and_retries_once():
    provider = _StreamingProvider(_EMPTY, _GOOD)
    events, _ = _collect(provider, hybrid=[_make_chunk()])

    assert [t for t, _ in events] == ["token", "token", "restart", "token", "token", "final"]
    assert provider.calls == 2
    assert "No." in events[-1][1].answer


def test_stream_empty_answer_after_retry_finalizes_inconclusive():
    provider = _StreamingProvider(_EMPTY, _EMPTY)
    events, mock_set = _collect(provider, hybrid=[_make_chunk()])

    assert provider.calls == 2
    types = [t for t, _ in events]
    assert types[-1] == "final"
    assert types.count("restart") == 2, "attempt 2's partial bubble must clear too"
    assert events[-1][1].answer == _INCONCLUSIVE_ANSWER
    assert not mock_set.called, "degraded answers must not be cached"


# ---------------------------------------------------------------------------
# Hard routing: the stream comes from the hard provider over stuffed context
# ---------------------------------------------------------------------------


def test_stream_routed_query_streams_from_hard_provider():
    settings = _fake_settings()
    settings.hard_query_routing = True

    main = _StreamingProvider(["MAIN should not answer"])
    hard = _StreamingProvider(["Reasoning:\n- ok\n", "Answer:\nRouted."])
    stuffed = [_make_chunk(section="Full Rulebook", content="everything")]

    with patch("app.rag.pipeline.should_route", return_value=True):
        with patch("app.rag.pipeline.build_stuffed_chunks", return_value=stuffed):
            with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
                with patch("app.rag.pipeline.get_cached", return_value=None):
                    with patch("app.rag.pipeline.set_cached"):
                        events = list(answer_question_stream(
                            "How do A and B interact?", FakeEmbedder(), FakePool(),
                            main, settings, hard_provider=hard,
                        ))

    assert main.calls == 0
    assert hard.calls == 1
    assert "Routed." in events[-1][1].answer
