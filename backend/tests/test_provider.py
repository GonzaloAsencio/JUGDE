"""Tests for provider.py — the thin LLMProvider port and its concrete adapters."""
from unittest.mock import patch

from app.rag.provider import GeminiProvider


class _FakeClient:
    """Stand-in genai client — hyde() must not construct a new client."""


def _provider() -> GeminiProvider:
    return GeminiProvider(_FakeClient(), "gemini-2.0-flash", temperature=0.1, timeout_s=10.0)


# ---------------------------------------------------------------------------
# GeminiProvider.hyde — PR1 (hard-bucket-v2)
# ---------------------------------------------------------------------------


def test_gemini_provider_hyde_success_reuses_hyde_gemini():
    """On success, hyde() returns the text and reuses _hyde_gemini (lazy import)
    with the provider's own client — no new client construction."""
    provider = _provider()
    with patch(
        "app.rag.generation._hyde_gemini", return_value="A hypothetical answer."
    ) as mock_hyde_gemini:
        result = provider.hyde("How does Accelerate work?")

    assert result == "A hypothetical answer."
    mock_hyde_gemini.assert_called_once()
    called_client = mock_hyde_gemini.call_args.args[0]
    assert called_client is provider._client, "must reuse the provider's existing client"


def test_gemini_provider_hyde_exception_degrades_to_empty():
    """If _hyde_gemini raises for any reason, hyde() must not propagate — the
    pipeline's degrade-to-raw-only contract requires '' on any failure."""
    provider = _provider()
    with patch("app.rag.generation._hyde_gemini", side_effect=RuntimeError("boom")):
        result = provider.hyde("q?")

    assert result == ""
