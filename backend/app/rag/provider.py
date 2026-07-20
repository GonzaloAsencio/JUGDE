from abc import ABC, abstractmethod
from typing import Callable, Iterator, Optional

from app.rag.retrieval import Chunk
from app.rag.schemas import Usage


class LLMProvider(ABC):
    @property
    @abstractmethod
    def model(self) -> str:
        """The model this provider actually calls.

        Abstract on purpose. Callers that need to REPORT the model must ask the
        object that generates, never re-derive it from Settings: with
        llm_provider='gemini' and the openai_compat knobs left set,
        create_provider builds GeminiProvider(gemini_model) while
        `llm_model or gemini_model` names gpt-oss-120b — a model that provider
        never touches. That mismatch shipped in fc8e3ee (2026-07-02) and made
        every non-routed query log the wrong model until 2026-07-17, when it
        produced a wrong reading of a gate. One authority, no second copy.

        Test doubles must declare it too (`model = "fake"` satisfies this):
        a stub that cannot say what it impersonates is how the pipeline learns
        to trust a name nobody set.
        """

    @property
    def hyde_model(self) -> str:
        """The model hyde() actually calls. Defaults to the answer model.

        Same authority rule as `model`: /health reports THIS, never
        settings.hyde_model — a typo'd HYDE_MODEL env var fails at the first
        hyde() call and silently degrades to raw-only retrieval, so the only
        honest report is what the provider object was actually built with.
        Non-abstract on purpose: providers without a separate writer (and test
        doubles) answer with their answer model, which is the truth.
        """
        return self.model

    @abstractmethod
    def generate(self, question: str, chunks: list[Chunk], *, extra_system: str = "") -> str: ...

    def generate_metered(
        self, question: str, chunks: list[Chunk], *, extra_system: str = ""
    ) -> tuple[str, Optional[Usage]]:
        """generate() plus the real token Usage when the API reports it.

        Default: ``(generate(...), None)`` so providers (and test doubles) that
        don't meter keep working — a None usage tells the pipeline to estimate.
        """
        return self.generate(question, chunks, extra_system=extra_system), None

    def generate_stream(
        self,
        question: str,
        chunks: list[Chunk],
        *,
        extra_system: str = "",
        on_usage: Optional[Callable[[Usage], None]] = None,
    ) -> Iterator[str]:
        """Yield answer text deltas as they arrive (2.5 SSE).

        Default: the full generate_metered() output as a single chunk, so
        providers (and test doubles) that don't implement streaming degrade to
        the exact same answer — just without progressive delivery. *on_usage*
        receives the real Usage when the provider has one; never required.
        """
        answer, usage = self.generate_metered(question, chunks, extra_system=extra_system)
        if on_usage is not None and usage is not None:
            on_usage(usage)
        yield answer

    def rewrite_query(self, question: str) -> str:
        return question

    def hyde(self, question: str) -> str:
        """Hypothetical answer for the HyDE retrieval arm. Default: none, so the
        pipeline degrades to raw-only retrieval. Providers override to enable it."""
        return ""

    def health_check(self) -> str | None:
        return None


class GeminiProvider(LLMProvider):
    def __init__(
        self, client, model: str, temperature: float, timeout_s: float,
        max_output_tokens: int = 1024,
        hyde_model: str | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._timeout_s = timeout_s
        self._max_output_tokens = max_output_tokens
        # 2.2: HyDE writes 2-3 throwaway sentences that are only ever embedded,
        # never shown. It does not need the answer model. Defaults to it so an
        # unset hyde_model is byte-identical to the pre-2.2 behaviour.
        self._hyde_model = hyde_model or model

    @property
    def model(self) -> str:
        return self._model

    @property
    def hyde_model(self) -> str:
        return self._hyde_model

    def generate(self, question: str, chunks: list[Chunk], *, extra_system: str = "") -> str:
        from app.rag.generation import _call_gemini, build_prompt
        return _call_gemini(
            self._client,
            self._model,
            build_prompt(question, chunks, extra_system=extra_system),
            temperature=self._temperature,
            timeout_s=self._timeout_s,
            max_output_tokens=self._max_output_tokens,
        )

    def generate_metered(
        self, question: str, chunks: list[Chunk], *, extra_system: str = ""
    ) -> tuple[str, Optional[Usage]]:
        from app.rag.generation import _call_gemini_metered, build_prompt
        return _call_gemini_metered(
            self._client,
            self._model,
            build_prompt(question, chunks, extra_system=extra_system),
            temperature=self._temperature,
            timeout_s=self._timeout_s,
            max_output_tokens=self._max_output_tokens,
        )

    def generate_stream(
        self,
        question: str,
        chunks: list[Chunk],
        *,
        extra_system: str = "",
        on_usage: Optional[Callable[[Usage], None]] = None,
    ) -> Iterator[str]:
        from app.rag.generation import _stream_gemini, build_prompt
        yield from _stream_gemini(
            self._client,
            self._model,
            build_prompt(question, chunks, extra_system=extra_system),
            temperature=self._temperature,
            timeout_s=self._timeout_s,
            max_output_tokens=self._max_output_tokens,
            on_usage=on_usage,
        )

    def hyde(self, question: str) -> str:
        from app.rag.generation import _hyde_gemini
        try:
            return _hyde_gemini(self._client, self._hyde_model, question)
        except Exception:
            return ""

    def health_check(self) -> str | None:
        from google.genai import types
        try:
            self._client.models.generate_content(
                model=self._model,
                contents="ping",
                config=types.GenerateContentConfig(
                    http_options=types.HttpOptions(timeout=5000),
                ),
            )
            return None
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                return None
            return err


class OpenAICompatProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float,
        timeout_s: float,
        max_output_tokens: int = 1024,
        hyde_model: str | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._timeout_s = timeout_s
        self._max_output_tokens = max_output_tokens
        # See GeminiProvider: HyDE output is embedded, never shown.
        self._hyde_model = hyde_model or model

    @property
    def model(self) -> str:
        return self._model

    @property
    def hyde_model(self) -> str:
        return self._hyde_model

    def generate(self, question: str, chunks: list[Chunk], *, extra_system: str = "") -> str:
        from app.rag.generation import _call_openai_compat_raw
        return _call_openai_compat_raw(
            question, chunks,
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            temperature=self._temperature,
            timeout_s=self._timeout_s,
            extra_system=extra_system,
            max_output_tokens=self._max_output_tokens,
        )

    def generate_metered(
        self, question: str, chunks: list[Chunk], *, extra_system: str = ""
    ) -> tuple[str, Optional[Usage]]:
        from app.rag.generation import _call_openai_compat_raw_metered
        return _call_openai_compat_raw_metered(
            question, chunks,
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            temperature=self._temperature,
            timeout_s=self._timeout_s,
            extra_system=extra_system,
            max_output_tokens=self._max_output_tokens,
        )

    def generate_stream(
        self,
        question: str,
        chunks: list[Chunk],
        *,
        extra_system: str = "",
        on_usage: Optional[Callable[[Usage], None]] = None,
    ) -> Iterator[str]:
        from app.rag.generation import _stream_openai_compat_raw
        yield from _stream_openai_compat_raw(
            question, chunks,
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            temperature=self._temperature,
            timeout_s=self._timeout_s,
            extra_system=extra_system,
            max_output_tokens=self._max_output_tokens,
            on_usage=on_usage,
        )

    def rewrite_query(self, question: str) -> str:
        from app.rag.generation import _rewrite_openai_compat
        return _rewrite_openai_compat(
            question,
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
        )

    def hyde(self, question: str) -> str:
        from app.rag.generation import _hyde_openai_compat
        return _hyde_openai_compat(
            question,
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._hyde_model,
        )


def create_hard_provider(settings, llm_client=None) -> LLMProvider | None:
    """Provider for routed hard queries (thinking model + routed-sized
    timeout/output budget), or None when the flag is off.

    Independent of the MAIN provider on purpose: prod runs openai_compat
    (Groq) as main, so the hard path builds its own Gemini client from
    gemini_api_key when the main one isn't Gemini. Settings validation
    guarantees the key exists whenever the flag is on (fail-closed).
    """
    if not settings.hard_query_routing:
        return None
    if llm_client is None:
        from google import genai
        llm_client = genai.Client(api_key=settings.gemini_api_key)
    return GeminiProvider(
        client=llm_client,
        model=settings.hard_gemini_model,
        temperature=settings.gemini_temperature,
        timeout_s=settings.hard_timeout_s,
        max_output_tokens=settings.hard_max_output_tokens,
    )


def create_provider(settings, llm_client=None) -> LLMProvider:
    if settings.llm_provider == "openai_compat":
        return OpenAICompatProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            temperature=settings.gemini_temperature,
            timeout_s=settings.gemini_timeout_s,
            max_output_tokens=settings.max_output_tokens,
            hyde_model=settings.hyde_model,
        )
    return GeminiProvider(
        client=llm_client,
        model=settings.gemini_model,
        temperature=settings.gemini_temperature,
        timeout_s=settings.gemini_timeout_s,
        max_output_tokens=settings.max_output_tokens,
        hyde_model=settings.hyde_model,
    )
