"""Genera líneas de contexto por chunk rulebook (contextual retrieval, plan 3.8).

Uso:
  python -m scripts.contextualize --dry-run       # cuenta pendientes, muestra prompts
  python -m scripts.contextualize --limit 50      # batch corto (smoke / cuota justa)
  python -m scripts.contextualize                 # todo lo pendiente

Batch one-time: una llamada LLM por chunk rulebook. Checkpoint en
data/context_lines.json keyed por content_key (estable entre versiones de
corpus), así que re-ejecutar retoma donde quedó — pensado para repartir la
cuota free-tier entre días. Un 429 guarda el checkpoint y sale limpio.

La línea resultante se prependea al chunk en el ingest (--context-file) ANTES
de embeber: el probe 2026-07-11 mostró que una línea con forma de pregunta
cruza el floor de similitud que el chunk pelado no cruza (0.52 vs floor 0.49
para el gold de eval-014), y viaja también a FTS y reranker.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.rag.rules import _RULE_CODE  # noqa: E402
from scripts.ingest import SOURCES, build_chunks  # noqa: E402

CHECKPOINT_PATH = Path(__file__).resolve().parent.parent / "data" / "context_lines.json"
_PREFIX = "Context: "
_MAX_LEN = 300
_MIN_BODY = 10
_SAVE_EVERY = 20

# Señales de cuota agotada (google.genai levanta ClientError con el status).
_QUOTA_MARKERS = ("429", "RESOURCE_EXHAUSTED", "quota")


# ---------------------------------------------------------------------------
# Lógica pura (testeada en tests/test_contextualize.py)
# ---------------------------------------------------------------------------

def build_prompt(section: str, content: str) -> str:
    """Prompt para UNA línea de contexto con forma de pregunta.

    El probe mostró que la variante ganadora describe el ESCENARIO del jugador
    ("my opponent has an ability that triggers when I play a unit...") — no un
    resumen abstracto, que diluye (gold+padre: 0.46 < gold pelado: 0.49).
    """
    return f"""You are indexing a trading-card-game rulebook for search. Given one rule chunk, write ONE line describing the concrete player situation this rule answers, phrased with the everyday words a player would use when asking about it.

Guidelines:
- Single line, at most 40 words.
- Describe the in-game situation ("my opponent...", "I play...", "both abilities trigger..."), not an abstract summary.
- Use everyday player vocabulary; you may name game concepts, but NEVER cite rule numbers.
- Output ONLY the line, no quotes, no markdown.

Section: {section}

Rule chunk:
{content}"""


def sanitize_line(raw: str | None) -> str | None:
    """Colapsa a una sola línea 'Context: ...' segura, o None si no sirve.

    Los códigos de regla se eliminan SIEMPRE: una línea con '383.3.d.1' se
    metería en rule_codes en query-time y reintroduciría hits de papel.
    """
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"```[a-z]*", "", text)
    text = text.strip().strip('"').strip("'")
    text = _RULE_CODE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if text.startswith(_PREFIX.strip()):
        text = text[len(_PREFIX.strip()):].strip(" :")
    if len(text) < _MIN_BODY:
        return None
    line = _PREFIX + text
    if not line.endswith((".", "?", "!")) and len(line) < _MAX_LEN:
        line += "."
    return line[:_MAX_LEN]


def load_checkpoint(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_checkpoint(path: Path, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )


def _is_quota_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(marker.lower() in text.lower() for marker in _QUOTA_MARKERS)


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------

def _rulebook_chunks() -> list[dict]:
    chunks: list[dict] = []
    for source_path, source_type in SOURCES:
        if source_type == "rulebook":
            chunks.extend(build_chunks(source_path, source_type))
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera context lines por chunk rulebook (plan 3.8)")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de llamadas LLM en esta corrida")
    parser.add_argument("--dry-run", action="store_true", help="No llama al LLM; cuenta pendientes y muestra 3 prompts")
    parser.add_argument("--sleep", type=float, default=2.5, help="Segundos entre llamadas (default 2.5 ≈ 24 rpm)")
    args = parser.parse_args()

    chunks = _rulebook_chunks()
    checkpoint = load_checkpoint(CHECKPOINT_PATH)
    pending = [c for c in chunks if c["content_key"] not in checkpoint]
    print(f"Chunks rulebook: {len(chunks)} | con línea: {len(chunks) - len(pending)} | pendientes: {len(pending)}")

    if args.dry_run:
        for c in pending[:3]:
            print("\n----- PROMPT -----")
            print(build_prompt(c["section"], c["content"]))
        return

    if not pending:
        print("Nada pendiente. Checkpoint completo.")
        return

    from app.config import Settings
    from app.rag.generation import _call_gemini

    settings = Settings()
    if settings.llm_provider != "gemini":
        print(f"ERROR: solo gemini está soportado para el batch (llm_provider={settings.llm_provider})")
        sys.exit(1)
    from google import genai
    client = genai.Client(api_key=settings.gemini_api_key)

    if args.limit:
        pending = pending[: args.limit]

    done = skipped = 0
    try:
        for i, chunk in enumerate(pending, 1):
            try:
                raw = _call_gemini(
                    client, settings.gemini_model, build_prompt(chunk["section"], chunk["content"]),
                    temperature=0.2, timeout_s=20.0, max_output_tokens=80,
                )
            except Exception as exc:  # noqa: BLE001 — cuota o red: cortar y guardar
                if _is_quota_error(exc):
                    print(f"\nCuota agotada tras {done} líneas ({exc}). Checkpoint guardado; re-ejecutar mañana retoma.")
                    break
                raise
            line = sanitize_line(raw)
            if line is None:
                skipped += 1  # sin checkpoint: reintenta en la próxima corrida
            else:
                checkpoint[chunk["content_key"]] = {"line": line, "section": chunk["section"]}
                done += 1
            if done and done % _SAVE_EVERY == 0:
                save_checkpoint(CHECKPOINT_PATH, checkpoint)
            print(f"[{i}/{len(pending)}] {chunk['section'][:40]:40} {'OK' if line else 'SKIP'}")
            time.sleep(args.sleep)
    finally:
        save_checkpoint(CHECKPOINT_PATH, checkpoint)

    total = len(chunks)
    print(f"\nGeneradas: {done} | salteadas (respuesta inservible): {skipped}")
    print(f"Checkpoint: {len(checkpoint)}/{total} chunks con línea → {CHECKPOINT_PATH}")
    if len(checkpoint) == total:
        print("COMPLETO. Siguiente paso: CORPUS_VERSION=v2.3.0 python -m scripts.ingest --context-file data/context_lines.json")


if __name__ == "__main__":
    main()
