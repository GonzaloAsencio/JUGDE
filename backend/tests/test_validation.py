"""Unit tests for QueryRequest validation (schemas.py)."""
import pytest
from pydantic import ValidationError

from app.rag.schemas import QueryRequest


def test_question_too_short_returns_422():
    with pytest.raises(ValidationError) as exc_info:
        QueryRequest(question="ab")
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("question",) for e in errors)


def test_question_too_long_returns_422():
    with pytest.raises(ValidationError) as exc_info:
        QueryRequest(question="x" * 501)
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("question",) for e in errors)


def test_xss_script_tag_rejected():
    with pytest.raises(ValidationError):
        QueryRequest(question="<Script>alert(1)</Script>")


def test_xss_javascript_scheme_rejected():
    with pytest.raises(ValidationError):
        QueryRequest(question="javascript:alert(1)")


def test_xss_event_handler_rejected():
    with pytest.raises(ValidationError):
        QueryRequest(question="<img onload=alert(1)>")


def test_valid_question_accepted():
    req = QueryRequest(question="What are Zara's abilities?")
    assert req.question == "What are Zara's abilities?"


def test_too_many_card_mentions_rejected():
    with pytest.raises(ValidationError):
        QueryRequest(question="valid question here", card_mentions=["card"] * 11)


def test_card_mention_too_long_rejected():
    with pytest.raises(ValidationError):
        QueryRequest(question="valid question here", card_mentions=["x" * 101])


def test_invalid_language_rejected():
    with pytest.raises(ValidationError):
        QueryRequest(question="valid question here", language="fr")  # type: ignore[arg-type]


def test_valid_language_en_accepted():
    req = QueryRequest(question="valid question here", language="en")
    assert req.language == "en"


def test_valid_language_es_accepted():
    req = QueryRequest(question="valid question here", language="es")
    assert req.language == "es"


def test_session_id_too_long_rejected():
    with pytest.raises(ValidationError):
        QueryRequest(question="valid question here", session_id="x" * 65)


def test_session_id_within_limit_accepted():
    req = QueryRequest(question="valid question here", session_id="abc123")
    assert req.session_id == "abc123"
