"""Tests for provider.py — the thin LLMProvider port and its concrete adapters."""
from unittest.mock import patch

from app.rag.provider import GeminiProvider, OpenAICompatProvider


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


# ---------------------------------------------------------------------------
# LLMProvider.generate(extra_system=...) — multi-card scaffold threading (PR3)
# ---------------------------------------------------------------------------


def test_gemini_provider_generate_default_extra_system_is_empty():
    """Calling generate() without extra_system (existing callers) keeps working."""
    provider = _provider()
    with patch("app.rag.generation.build_prompt", return_value="prompt") as mock_build_prompt:
        with patch("app.rag.generation._call_gemini", return_value="answer"):
            provider.generate("q?", [])

    mock_build_prompt.assert_called_once_with("q?", [], extra_system="")


def test_gemini_provider_generate_forwards_extra_system_to_build_prompt():
    provider = _provider()
    with patch("app.rag.generation.build_prompt", return_value="prompt") as mock_build_prompt:
        with patch("app.rag.generation._call_gemini", return_value="answer"):
            provider.generate("q?", [], extra_system="SCAFFOLD")

    mock_build_prompt.assert_called_once_with("q?", [], extra_system="SCAFFOLD")


def _openai_provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url="http://x", api_key="k", model="m", temperature=0.1, timeout_s=10.0,
    )


def test_openai_compat_provider_generate_default_extra_system_is_empty():
    provider = _openai_provider()
    with patch("app.rag.generation._call_openai_compat_raw", return_value="answer") as mock_call:
        provider.generate("q?", [])

    assert mock_call.call_args.kwargs["extra_system"] == ""


def test_openai_compat_provider_generate_forwards_extra_system():
    provider = _openai_provider()
    with patch("app.rag.generation._call_openai_compat_raw", return_value="answer") as mock_call:
        provider.generate("q?", [], extra_system="SCAFFOLD")

    assert mock_call.call_args.kwargs["extra_system"] == "SCAFFOLD"


# ---------------------------------------------------------------------------
# Output token budget forwarding (improvement plan 1.2)
# ---------------------------------------------------------------------------


def test_gemini_provider_forwards_max_output_tokens():
    provider = GeminiProvider(
        _FakeClient(), "gemini-2.0-flash", temperature=0.1, timeout_s=10.0, max_output_tokens=512,
    )
    with patch("app.rag.generation.build_prompt", return_value="prompt"):
        with patch("app.rag.generation._call_gemini", return_value="answer") as mock_call:
            provider.generate("q?", [])

    assert mock_call.call_args.kwargs["max_output_tokens"] == 512


def test_openai_compat_provider_forwards_max_output_tokens():
    provider = OpenAICompatProvider(
        base_url="http://x", api_key="k", model="m",
        temperature=0.1, timeout_s=10.0, max_output_tokens=512,
    )
    with patch("app.rag.generation._call_openai_compat_raw", return_value="answer") as mock_call:
        provider.generate("q?", [])

    assert mock_call.call_args.kwargs["max_output_tokens"] == 512


def test_create_provider_passes_max_output_tokens_from_settings():
    from unittest.mock import MagicMock
    from app.rag.provider import create_provider

    settings = MagicMock()
    settings.llm_provider = "gemini"
    settings.gemini_model = "gemini-2.0-flash"
    settings.gemini_temperature = 0.1
    settings.gemini_timeout_s = 10.0
    settings.max_output_tokens = 999

    provider = create_provider(settings, llm_client=_FakeClient())
    assert provider._max_output_tokens == 999

    settings.llm_provider = "openai_compat"
    settings.llm_base_url = "http://x"
    settings.llm_api_key = "k"
    settings.llm_model = "m"

    provider = create_provider(settings)
    assert provider._max_output_tokens == 999


def test_fake_llm_provider_accepts_extra_system_kwarg_without_breaking():
    """Fakes in conftest.py must satisfy the extended ABC signature (keyword-only
    extra_system with a default) so the pipeline can always call generate(...,
    extra_system=extra) without breaking test doubles."""
    from tests.conftest import FakeLLMProvider

    provider = FakeLLMProvider()
    assert provider.generate("q?", []) == "Fake answer for testing."
    assert provider.generate("q?", [], extra_system="SCAFFOLD") == "Fake answer for testing."
