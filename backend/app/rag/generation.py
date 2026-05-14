import google.api_core.exceptions as _gapi_exc
import google.generativeai as genai

from app.rag.retrieval import Chunk


class GenerationTimeout(Exception):
    """Raised when the Gemini API call exceeds the configured timeout."""


class GenerationError(Exception):
    """Raised when the Gemini API returns an error."""


_SYSTEM_INSTRUCTION = """\
Sos un juez asistente experto en las reglas del juego de cartas Riftbound.
Respondés preguntas sobre reglas usando EXCLUSIVAMENTE el contexto provisto abajo.

Reglas estrictas:
1. Si la respuesta no está en el contexto, decí literalmente: "No tengo información suficiente para responder esa pregunta con las reglas disponibles."
2. NO inventes reglas, números, ni nombres de cartas que no aparezcan en el contexto.
3. Cuando una regla provenga de la errata, mencionálo explícitamente ("según la errata...").
4. Citá las secciones relevantes al final con el formato [#N] donde N es el número del chunk.
5. Respondé en el mismo idioma de la pregunta.
"""


def build_prompt(question: str, chunks: list[Chunk]) -> str:
    """Pure function: build the full prompt string for Gemini."""
    lines = [_SYSTEM_INSTRUCTION, "=== CONTEXTO ==="]

    for i, chunk in enumerate(chunks, 1):
        lines.append(
            f'[#{i}] section: "{chunk.section}" (source: {chunk.source_type})\n{chunk.content}'
        )

    lines.append("")
    lines.append("=== PREGUNTA ===")
    lines.append(question)
    lines.append("")
    lines.append("=== RESPUESTA ===")

    return "\n".join(lines)


def call_gemini(
    client: genai.GenerativeModel,
    prompt: str,
    *,
    temperature: float = 0.1,
    timeout_s: float = 10.0,
) -> str:
    """Call Gemini and return the answer text.

    Raises:
        GenerationTimeout: if the API call exceeds timeout_s.
        GenerationError: if the API returns an error.
    """
    generation_config = genai.types.GenerationConfig(temperature=temperature)
    request_options = {"timeout": timeout_s}

    try:
        response = client.generate_content(
            prompt,
            generation_config=generation_config,
            request_options=request_options,
        )
        return response.text
    except (_gapi_exc.DeadlineExceeded, _gapi_exc.GatewayTimeout) as e:
        raise GenerationTimeout("Gemini API call timed out") from e
    except Exception as e:
        error_str = str(e).lower()
        if "timeout" in error_str or "deadline" in error_str or "timed out" in error_str:
            raise GenerationTimeout("Gemini API call timed out") from e
        raise GenerationError(f"Gemini API error: {e}") from e
