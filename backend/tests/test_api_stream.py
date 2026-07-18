"""POST /api/v1/query/stream (2.5 SSE) — the streaming endpoint.

SSE framing: ``event: <type>\\ndata: <json>\\n\\n``. Mid-stream failures cannot
change the HTTP status (200 is already on the wire), so the /query error
mapping is delivered as a terminal ``error`` event instead.
"""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.rag.retrieval import Chunk


def _make_chunk() -> Chunk:
    return Chunk(
        id="chunk-1",
        content="Content about the rules of the game.",
        section="Game Rules",
        parent_section=None,
        source_type="rulebook",
        similarity=0.92,
    )


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        name, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((name, data))
    return events


def test_stream_happy_path_tokens_then_final(client: TestClient):
    # get_cached pinned to a miss: the in-process cache fallback survives across
    # tests, and test_api.py caches this very question earlier in the run.
    with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            resp = client.post(
                "/api/v1/query/stream", json={"question": "How does double-tap work?"}
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert names[-1] == "final"
    assert "token" in names
    # The default (non-streaming) provider yields its whole answer as one token.
    token_text = "".join(d["text"] for n, d in events if n == "token")
    assert token_text == "Fake answer for testing."


def test_stream_final_event_is_a_query_response(client: TestClient):
    with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            resp = client.post(
                "/api/v1/query/stream", json={"question": "How does double-tap work?"}
            )

    final = _parse_sse(resp.text)[-1][1]
    assert final["answer"] == "Fake answer for testing."
    assert isinstance(final["citations"], list) and final["citations"]
    assert final["cache_hit"] is False
    assert "latency_ms" in final and "confidence" in final


def test_stream_empty_question_returns_422(client: TestClient):
    resp = client.post("/api/v1/query/stream", json={"question": ""})
    assert resp.status_code == 422


def test_stream_timeout_becomes_terminal_error_event(timeout_client: TestClient):
    """GenerationTimeout mid-stream: HTTP 200 already sent, so the /query 504
    mapping arrives as an ``error`` event with the same detail."""
    with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
        resp = timeout_client.post(
            "/api/v1/query/stream", json={"question": "What happens on timeout?"}
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1] == ("error", {"detail": "Generation timeout"})


def test_stream_unexpected_error_becomes_generic_error_event(client: TestClient):
    with patch(
        "app.api.v1.query.answer_question_stream",
        side_effect=RuntimeError("boom"),
    ):
        resp = client.post(
            "/api/v1/query/stream", json={"question": "Any question here?"}
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1] == ("error", {"detail": "Internal server error"})
