"""Pure-logic tests for the keyword-eviction probe (no DB, no network)."""
import json

from app.rag.retrieval import Chunk
from scripts.keyword_eviction_probe import (
    card_eviction,
    count_card_chunks,
    load_rulings,
)


def _chunk(cid: str, source_type: str, sim: float = 0.5) -> Chunk:
    return Chunk(cid, f"content-{cid}", f"sec-{cid}", None, source_type, sim)


def test_count_card_chunks_counts_only_cards():
    chunks = [_chunk("a", "card"), _chunk("b", "rulebook"), _chunk("c", "card")]
    assert count_card_chunks(chunks) == 2


def test_count_card_chunks_empty():
    assert count_card_chunks([]) == 0


def test_card_eviction_positive_when_card_dropped():
    baseline = [_chunk("card1", "card"), _chunk("card2", "card")]
    assembled = [_chunk("card1", "card")]  # card2 evicted
    assert card_eviction(baseline, assembled) == 1


def test_card_eviction_zero_when_cards_survive():
    baseline = [_chunk("card1", "card"), _chunk("rule1", "rulebook")]
    assembled = [_chunk("card1", "card"), _chunk("rule1", "rulebook")]
    assert card_eviction(baseline, assembled) == 0


def test_card_eviction_negative_when_tagging_adds_cards():
    baseline = [_chunk("card1", "card")]
    assembled = [_chunk("tagcard", "card"), _chunk("card1", "card")]
    assert card_eviction(baseline, assembled) == -1


def test_load_rulings_filters_specific_card(tmp_path):
    eval_set = tmp_path / "eval_set.json"
    eval_set.write_text(json.dumps([
        {"id": "eval-001", "question": "q1", "tags": ["deck-construction"]},
        {"id": "eval-021", "question": "q2", "tags": ["brambleback", "specific-card"]},
        {"id": "eval-040", "question": "q3", "tags": ["kaisa", "specific-card"]},
    ]), encoding="utf-8")
    rulings = load_rulings(eval_set)
    assert [r["id"] for r in rulings] == ["eval-021", "eval-040"]
