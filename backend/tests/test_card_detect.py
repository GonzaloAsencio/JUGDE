"""Unit tests for card-mention auto-detection (pure logic — no DB, no network).

detect_card_mentions scans a free-text question for card names drawn from the
corpus vocabulary and returns the ones to look up. The risk surface is FALSE
POSITIVES: many single-word card names ("Charm", "Block", "Eclipse") are also
ordinary English. These tests pin the rules that keep those from firing while
still catching the real multi-card interaction queries the hard bucket needs.
"""
from app.rag.card_detect import detect_card_mentions

KW = frozenset({"counter", "chain", "stun"})


# ---------------------------------------------------------------------------
# Multi-word names — the unambiguous, always-accepted case
# ---------------------------------------------------------------------------

def test_multiword_name_detected():
    out = detect_card_mentions("My opponent controls Vex Apathetic.", {"Vex Apathetic"})
    assert out == ["Vex Apathetic"]


def test_multiword_name_case_insensitive():
    # Multi-word phrases are distinctive enough to match regardless of casing.
    out = detect_card_mentions("marching orders with repeat", {"Marching Orders"})
    assert out == ["Marching Orders"]


def test_longest_match_wins():
    # "Jhin Virtuoso" present -> do NOT also report the shorter "Jhin".
    out = detect_card_mentions("Jhin Virtuoso attacks", {"Jhin", "Jhin Virtuoso"})
    assert out == ["Jhin Virtuoso"]


def test_multiple_cards_deduped_in_order():
    q = "I play Tideturner, opponent has Vex Apathetic, then another Tideturner"
    out = detect_card_mentions(q, {"Tideturner", "Vex Apathetic"})
    assert out == ["Tideturner", "Vex Apathetic"]


# ---------------------------------------------------------------------------
# Single-word names — the false-positive guard
# ---------------------------------------------------------------------------

def test_single_word_lowercase_not_matched():
    # "charm" as an ordinary verb (lowercase) must NOT pull the card "Charm".
    out = detect_card_mentions("can i charm a unit here", {"Charm"})
    assert out == []


def test_single_word_capitalized_proper_noun_matched():
    out = detect_card_mentions("I use Eclipse to give -4 might", {"Eclipse"})
    assert out == ["Eclipse"]


def test_single_word_shorter_than_five_chars_excluded():
    out = detect_card_mentions("cast Gust now", {"Gust"})
    assert out == []


def test_single_word_colliding_with_keyword_excluded():
    out = detect_card_mentions("play Counter now", {"Counter"}, known_keywords=KW)
    assert out == []


def test_substring_of_word_not_matched():
    # whole-word only: "Charm" must not fire inside "Charming"
    out = detect_card_mentions("a Charming Smile", {"Charm"})
    assert out == []


def test_single_word_name_with_trailing_punctuation():
    # eval-030: "Guards!" in prose -> card "Guards"
    out = detect_card_mentions("he plays Guards! and a soldier", {"Guards"})
    assert out == ["Guards"]


# ---------------------------------------------------------------------------
# Bounds and degenerate inputs
# ---------------------------------------------------------------------------

def test_cap_limits_returned_mentions():
    vocab = {"Marching Orders", "Vex Apathetic", "Hidden Blade", "Tideturner"}
    q = "Marching Orders Vex Apathetic Hidden Blade Tideturner"
    out = detect_card_mentions(q, vocab, max_mentions=2)
    assert len(out) == 2


def test_empty_vocab_returns_empty():
    assert detect_card_mentions("Vex Apathetic", set()) == []


def test_empty_question_returns_empty():
    assert detect_card_mentions("", {"Vex Apathetic"}) == []


# ---------------------------------------------------------------------------
# v2: window-bounded token-subset matching (recovers reversed / split names)
#
# The exact-phrase pass misses cards whose tokens appear out of order
# ("Angel Guardian" -> "Guardian Angel") or split by filler words
# ("Irelia Legend's Blade Dancer" -> "Irelia Blade Dancer"). A SECONDARY pass
# matches a card when ALL its tokens occur in the question, capitalized, within
# a short window. The capitalization + window guards keep incidental token
# co-occurrence in long prose from false-firing.
# ---------------------------------------------------------------------------

def test_v2_reversed_token_order_matched():
    out = detect_card_mentions("the Angel Guardian and its unit", {"Guardian Angel"})
    assert out == ["Guardian Angel"]


def test_v2_tokens_split_by_filler_matched():
    out = detect_card_mentions(
        "activate Irelia Legend's Blade Dancer ability", {"Irelia Blade Dancer"}
    )
    assert out == ["Irelia Blade Dancer"]


def test_v2_scatter_beyond_window_not_matched():
    # tokens present but far apart -> incidental co-occurrence, must NOT fire
    q = "the Angel flew over the castle while a lone Guardian watched the distant gate"
    assert detect_card_mentions(q, {"Guardian Angel"}) == []


def test_v2_lowercase_tokens_not_matched():
    # subset match still demands the proper-noun (capitalized) signal
    assert detect_card_mentions("the angel guardian thing", {"Guardian Angel"}) == []


def test_v2_partial_token_subset_not_matched():
    # only one of the card's tokens present -> not the card
    assert detect_card_mentions("a lone Guardian stands", {"Guardian Angel"}) == []


def test_v2_does_not_double_count_with_exact_match():
    # exact contiguous match must not also be re-added by the secondary pass
    out = detect_card_mentions("play Marching Orders now", {"Marching Orders"})
    assert out == ["Marching Orders"]
