"""Token usage capture (Fase 5, PR1a) — providers report what they spent.

Contract under test:
- ``Usage`` is additive metadata: real counts from the provider APIs when
  available (``response.usage`` / ``usage_metadata``), a chars/4 estimate
  marked ``estimated=True`` otherwise. Estimation can degrade accuracy but
  must NEVER break or block a query.
- ``LLMProvider.generate_metered`` returns ``(answer, Usage | None)``; the
  default falls back to ``generate()`` with no usage so existing doubles work.
- The streamers call ``on_usage`` at most once, with real counts, only when
  the API attached them to the stream — never blocking delivery otherwise.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.rag.generation import estimate_usage
from app.rag.schemas import Usage
from tests.conftest import FakeLLMProvider


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
