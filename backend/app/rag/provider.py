from abc import ABC, abstractmethod

from app.rag.retrieval import Chunk


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, question: str, chunks: list[Chunk]) -> str: ...

    def rewrite_query(self, question: str) -> str:
        return question

    def hyde(self, question: str) -> str:
        """Hypothetical answer for the HyDE retrieval arm. Default: none, so the
        pipeline degrades to raw-only retrieval. Providers override to enable it."""
        return ""

    def health_check(self) -> str | None:
        return None


class GeminiProvider(LLMProvider):
    def __init__(self, client, model: str, temperature: float, timeout_s: float) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._timeout_s = timeout_s

    def generate(self, question: str, chunks: list[Chunk]) -> str:
        from app.rag.generation import _call_gemini, build_prompt
        return _call_gemini(
            self._client,
            self._model,
            build_prompt(question, chunks),
            temperature=self._temperature,
            timeout_s=self._timeout_s,
        )

    def health_check(self) -> str | None:
        from google.genai import types
        try:
            self._client.models.generate_content(
                model=self._model,
                contents="ping",
                http_options={"timeout": 5},
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
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._timeout_s = timeout_s

    def generate(self, question: str, chunks: list[Chunk]) -> str:
        from app.rag.generation import _call_openai_compat_raw
        return _call_openai_compat_raw(
            question, chunks,
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            temperature=self._temperature,
            timeout_s=self._timeout_s,
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
            model=self._model,
        )


def create_provider(settings, llm_client=None) -> LLMProvider:
    if settings.llm_provider == "openai_compat":
        return OpenAICompatProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            temperature=settings.gemini_temperature,
            timeout_s=settings.gemini_timeout_s,
        )
    return GeminiProvider(
        client=llm_client,
        model=settings.gemini_model,
        temperature=settings.gemini_temperature,
        timeout_s=settings.gemini_timeout_s,
    )
