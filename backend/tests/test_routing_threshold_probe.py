"""Unit tests for the relaxed routing classifier that gates 3.11.1 lever (a).

The DB-driven run_probe/main are exercised manually. What matters here is that
the TREATMENT predicate differs from production in EXACTLY one way — the
card+keyword branch needs one keyword instead of two — and in no other.
"""
from app.rag.routing import is_hard_query
from scripts.routing_threshold_probe import is_hard_query_relaxed


def test_relaxed_routes_one_card_one_keyword():
    # eval-020's exact shape, and the whole point of the treatment.
    assert is_hard_query_relaxed(card_count=1, keyword_count=1) is True
    assert is_hard_query(card_count=1, keyword_count=1) is False


def test_relaxed_still_requires_a_card():
    # routing.py is explicit: the keyword vocabulary holds everyday words
    # (draw, discard, token, combat), so a card-less relaxation would route
    # "when do I draw?" to the 60s thinking model. The card stays mandatory.
    assert is_hard_query_relaxed(card_count=0, keyword_count=5) is False
    assert is_hard_query_relaxed(card_count=0, keyword_count=1) is False


def test_relaxed_keeps_the_two_card_branch():
    assert is_hard_query_relaxed(card_count=2, keyword_count=0) is True


def test_relaxed_does_not_route_a_card_with_no_keywords():
    # One card alone is not a multi-entity interaction question.
    assert is_hard_query_relaxed(card_count=1, keyword_count=0) is False


def test_relaxed_is_a_superset_of_production():
    # The treatment may only ADD routing, never remove it — otherwise a
    # question could lose the stuffed context and the gate's "lost refs" would
    # be measuring two changes at once.
    for cards in range(4):
        for keywords in range(4):
            if is_hard_query(card_count=cards, keyword_count=keywords):
                assert is_hard_query_relaxed(card_count=cards, keyword_count=keywords), (
                    f"production routes ({cards} cards, {keywords} kw) but relaxed does not"
                )


def test_relaxed_differs_only_on_the_one_card_one_keyword_cell():
    # Pin the exact delta: anything else changing means the treatment is
    # measuring more than it claims.
    diffs = [
        (c, k)
        for c in range(5) for k in range(5)
        if is_hard_query(card_count=c, keyword_count=k)
        != is_hard_query_relaxed(card_count=c, keyword_count=k)
    ]
    assert diffs == [(1, 1)]


def test_treatment_is_productions_relaxed_branch():
    """The probe must measure the predicate production actually ships.

    is_hard_query_relaxed was hand-written when this probe was the gate that
    justified the parameter — routing.py had no relaxed branch yet. The grid
    test above compares the probe against production's DEFAULT, which cannot
    catch a retune of the relaxed branch: routing.py and the probe would
    diverge silently and the next run would report a 3W/0L belonging to a
    predicate production no longer uses. This is what pins them.
    """
    from app.rag.routing import is_hard_query

    for c in range(5):
        for k in range(5):
            assert is_hard_query_relaxed(card_count=c, keyword_count=k) == is_hard_query(
                card_count=c, keyword_count=k, relaxed=True
            ), f"probe treatment diverged from production at ({c} cards, {k} keywords)"
