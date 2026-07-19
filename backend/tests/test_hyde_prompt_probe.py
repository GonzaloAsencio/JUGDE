"""Pure-logic tests for the 3.14 gate rule in scripts/hyde_prompt_probe.py."""
from scripts.hyde_prompt_probe import variant_lives


def test_lives_with_confirmed_win_and_no_regressions():
    assert variant_lives(frozenset({"425"}), persistent_regressions=False) is True


def test_dies_without_any_confirmed_target_win():
    assert variant_lives(frozenset(), persistent_regressions=False) is False


def test_dies_when_a_persistent_regression_exists_even_with_wins():
    """The lever-(d) shape: a headline win never buys a regression."""
    assert variant_lives(frozenset({"131.4", "425"}), persistent_regressions=True) is False


def test_dies_with_neither():
    assert variant_lives(frozenset(), persistent_regressions=True) is False
