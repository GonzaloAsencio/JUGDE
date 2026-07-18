"""Streaming generation (2.5 SSE) — the provider port and its adapters.

Contract under test:
- ``LLMProvider.generate_stream`` yields text deltas; the DEFAULT implementation
  falls back to ``generate()`` as a single chunk, so providers (and test
  doubles) that don't implement streaming keep working with identical output.
- Adapters delegate to their streaming call in generation.py with the same
  knobs as generate() (model, extra_system, max_output_tokens, timeout).
- 429 retry wraps only the stream CREATION, never the iteration: a token
  already yielded cannot be retracted, so once the stream starts an error
  propagates instead of retrying.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.rag.generation import GenerationError, GenerationTimeout
from app.rag.provider import GeminiProvider, OpenAICompatProvider
from tests.conftest import FakeLLMProvider


# ---------------------------------------------------------------------------
# LLMProvider.generate_stream — default fallback
# ---------------------------------------------------------------------------


def test_generate_stream_default_yields_generate_output_as_single_chunk():
    provider = FakeLLMProvider()
    assert list(provider.generate_stream("q?", [])) == ["Fake answer for testing."]


def test_generate_stream_default_forwards_extra_system():
    class _Recording(FakeLLMProvider):
        def generate(self, question, chunks, *, extra_system=""):
            self.seen_extra = extra_system
            return "ans"

    provider = _Recording()
    assert list(provider.generate_stream("q?", [], extra_system="SCAFFOLD")) == ["ans"]
    assert provider.seen_extra == "SCAFFOLD"


# ---------------------------------------------------------------------------
# OpenAICompatProvider.generate_stream — delegation
# ---------------------------------------------------------------------------


def _openai_provider(**kwargs) -> OpenAICompatProvider:
    defaults = dict(
        base_url="http://x", api_key="k", model="m",
        temperature=0.1, timeout_s=10.0, max_output_tokens=512,
    )
    defaults.update(kwargs)
    return OpenAICompatProvider(**defaults)


def test_openai_compat_generate_stream_delegates_with_kwargs():
    provider = _openai_provider()
    with patch(
        "app.rag.generation._stream_openai_compat_raw", return_value=iter(["a", "b"])
    ) as mock_stream:
        out = list(provider.generate_stream("q?", [], extra_system="S"))

    assert out == ["a", "b"]
    kwargs = mock_stream.call_args.kwargs
    assert kwargs["model"] == "m"
    assert kwargs["extra_system"] == "S"
    assert kwargs["max_output_tokens"] == 512
    assert kwargs["timeout_s"] == 10.0


# ---------------------------------------------------------------------------
# GeminiProvider.generate_stream — delegation
# ---------------------------------------------------------------------------


class _FakeClient:
    """Stand-in genai client — generate_stream must reuse it, never build one."""


def test_gemini_generate_stream_delegates_and_reuses_client():
    client = _FakeClient()
    provider = GeminiProvider(
        client, "gemini-x", temperature=0.1, timeout_s=10.0, max_output_tokens=256,
    )
    with patch(
        "app.rag.generation._stream_gemini", return_value=iter(["x"])
    ) as mock_stream:
        out = list(provider.generate_stream("q?", []))

    assert out == ["x"]
    assert mock_stream.call_args.args[0] is client, "must reuse the provider's client"
    assert mock_stream.call_args.kwargs["max_output_tokens"] == 256


# ---------------------------------------------------------------------------
# _stream_openai_compat_raw — behaviour against a fake openai client
# ---------------------------------------------------------------------------


def _delta_chunk(content):
    chunk = MagicMock()
    chunk.choices = [MagicMock(delta=MagicMock(content=content))]
    return chunk


def _no_choices_chunk():
    chunk = MagicMock()
    chunk.choices = []  # e.g. a trailing usage-only chunk
    return chunk


def _stream_raw(fake_client, **kwargs):
    from app.rag.generation import _stream_openai_compat_raw

    defaults = dict(
        base_url="http://x", api_key="k", model="m",
        temperature=0.1, timeout_s=10.0,
    )
    defaults.update(kwargs)
    with patch("openai.OpenAI", return_value=fake_client):
        return list(_stream_openai_compat_raw("q?", [], **defaults))


def test_stream_openai_compat_yields_deltas_skipping_empty_and_no_choices():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = iter([
        _delta_chunk(None),  # role-only first chunk
        _delta_chunk("Hel"),
        _delta_chunk("lo"),
        _no_choices_chunk(),
    ])

    assert _stream_raw(fake_client) == ["Hel", "lo"]
    assert fake_client.chat.completions.create.call_args.kwargs["stream"] is True


def test_stream_openai_compat_passes_max_tokens():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = iter([_delta_chunk("a")])

    _stream_raw(fake_client, max_output_tokens=777)

    assert fake_client.chat.completions.create.call_args.kwargs["max_tokens"] == 777


def test_stream_openai_compat_timeout_maps_to_generation_timeout():
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = Exception("Request timed out")

    with pytest.raises(GenerationTimeout):
        _stream_raw(fake_client)


def test_stream_openai_compat_error_maps_to_generation_error():
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = Exception("boom")

    with pytest.raises(GenerationError):
        _stream_raw(fake_client)


def test_stream_openai_compat_midstream_error_maps_to_generation_error():
    def _exploding():
        yield _delta_chunk("partial")
        raise Exception("connection reset")

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _exploding()

    from app.rag.generation import _stream_openai_compat_raw

    collected = []
    with patch("openai.OpenAI", return_value=fake_client):
        gen = _stream_openai_compat_raw(
            "q?", [], base_url="http://x", api_key="k", model="m",
            temperature=0.1, timeout_s=10.0,
        )
        with pytest.raises(GenerationError):
            for piece in gen:
                collected.append(piece)

    assert collected == ["partial"], "deltas before the failure are still delivered"


def test_stream_openai_compat_retries_429_before_first_token():
    """A 429 at stream CREATION is retried (same schedule as generate); the
    stream then proceeds normally."""
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = [
        Exception("429 too many requests"),
        iter([_delta_chunk("ok")]),
    ]

    assert _stream_raw(fake_client) == ["ok"]
    assert fake_client.chat.completions.create.call_count == 2


# ---------------------------------------------------------------------------
# _stream_gemini — behaviour against a recording client
# ---------------------------------------------------------------------------


class _TextChunk:
    def __init__(self, text):
        self._text = text

    @property
    def text(self):
        return self._text


class _RaisingTextChunk:
    @property
    def text(self):
        raise ValueError("no content")  # safety block shape in google-genai


class _Models:
    def __init__(self, outer):
        self._outer = outer

    def generate_content_stream(self, *, model, contents, config):
        self._outer.calls.append({"model": model, "contents": contents, "config": config})
        if self._outer.error is not None:
            raise self._outer.error
        return iter(self._outer.chunks)


class _RecordingStreamClient:
    def __init__(self, chunks=(), error=None):
        self.calls = []
        self.chunks = list(chunks)
        self.error = error
        self.models = _Models(self)


def _stream_gemini_list(client, **kwargs):
    from app.rag.generation import _stream_gemini

    defaults = dict(temperature=0.1, timeout_s=10.0, max_output_tokens=256)
    defaults.update(kwargs)
    return list(_stream_gemini(client, "gemini-x", "prompt", **defaults))


def test_stream_gemini_yields_text_skipping_empty_and_raising_chunks():
    client = _RecordingStreamClient(chunks=[
        _TextChunk("Hel"), _TextChunk(None), _RaisingTextChunk(), _TextChunk("lo"),
    ])

    assert _stream_gemini_list(client) == ["Hel", "lo"]


def test_stream_gemini_forwards_config_knobs():
    client = _RecordingStreamClient(chunks=[_TextChunk("a")])

    _stream_gemini_list(client, temperature=0.3, timeout_s=45.0, max_output_tokens=777)

    config = client.calls[0]["config"]
    assert config.max_output_tokens == 777
    assert config.temperature == 0.3
    assert config.http_options.timeout == 45_000


def test_stream_gemini_timeout_maps_to_generation_timeout():
    client = _RecordingStreamClient(error=Exception("deadline exceeded"))

    with pytest.raises(GenerationTimeout):
        _stream_gemini_list(client)


def test_stream_gemini_error_maps_to_generation_error():
    client = _RecordingStreamClient(error=Exception("boom"))

    with pytest.raises(GenerationError):
        _stream_gemini_list(client)
