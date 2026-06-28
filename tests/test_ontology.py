"""Direct unit tests for services/ontology.py — extract_alternatives and clean logic."""

import pytest
from services.ontology import extract_alternatives


# ── Basic "or" extraction ──

def test_simple_or():
    """Two items separated by 'or'."""
    assert extract_alternatives("golf or frisbee") == ["Golf", "Frisbee"]


def test_or_with_articles():
    """Articles 'a', 'an', 'the' stripped from alternatives."""
    assert extract_alternatives("a house or an apartment") == ["House", "Apartment"]


def test_or_with_the():
    assert extract_alternatives("the macbook or the thinkpad") == ["Macbook", "Thinkpad"]


# ── "vs" variants ──

def test_vs():
    assert extract_alternatives("Python vs JavaScript") == ["Python", "JavaScript"]


def test_vs_dot():
    assert extract_alternatives("Team A vs. Team B") == ["Team A", "Team B"]


def test_versus():
    assert extract_alternatives("option 1 versus option 2") == ["Option 1", "Option 2"]


# ── Verb stripping (the "do" / "play" / "should I" bugs) ──

def test_do_verb():
    """'should I do X or Y' → ['X', 'Y']."""
    assert extract_alternatives("should I do aikido or football") == ["Aikido", "Football"]


def test_play_verb():
    """'play' verb stripped from before-part."""
    assert extract_alternatives("should I play golf or frisbee") == ["Golf", "Frisbee"]


def test_buy_verb():
    assert extract_alternatives("buy a house or an apartment") == ["House", "Apartment"]


def test_choose_verb():
    assert extract_alternatives("choose Python or JavaScript") == ["Python", "JavaScript"]


def test_pick_verb():
    assert extract_alternatives("pick the red or the blue") == ["Red", "Blue"]


def test_go_for_verb():
    assert extract_alternatives("go for coffee or tea") == ["Coffee", "Tea"]


def test_decide_between_verb():
    assert extract_alternatives("decide between Spain or France") == ["Spain", "France"]


def test_compare_verb():
    assert extract_alternatives("compare iPhone or Samsung") == ["IPhone", "Samsung"]


def test_have_verb():
    assert extract_alternatives("should I have sushi or pizza") == ["Sushi", "Pizza"]


# ── Prefix stripping ──

def test_should_i_prefix():
    assert extract_alternatives("should I buy a car or a bike") == ["Car", "Bike"]


def test_i_want_to_prefix():
    assert extract_alternatives("I want to learn guitar or piano") == ["Guitar", "Piano"]


def test_am_i_prefix():
    assert extract_alternatives("am I ready for a dog or a cat") == ["Ready for a dog", "Cat"]


# ── No-match cases ──

def test_no_match_single_item():
    assert extract_alternatives("What should I do today?") == []


def test_no_match_no_conjunction():
    assert extract_alternatives("hello world") == []


def test_empty_string():
    assert extract_alternatives("") == []


def test_no_match_numbers():
    assert extract_alternatives("42") == []


# ── Edge cases ──

def test_trailing_punctuation():
    """Trailing ? and . are stripped."""
    result = extract_alternatives("Should I buy a car or a bike?")
    assert result == ["Car", "Bike"]


def test_mixed_case():
    """All-uppercase input keeps uppercase (clean() only lower→upper first letter)."""
    result = extract_alternatives("SHOULD I DO YOGA OR PILATES")
    assert result == ["YOGA", "PILATES"]


def test_multiple_words_in_alternative():
    """Only first letter is capitalized; remaining words preserve case."""
    result = extract_alternatives("should I buy a three-bedroom house or a studio apartment")
    assert result == ["Three-bedroom house", "Studio apartment"]


def test_or_at_start_returns_empty():
    """Query starting with 'or' has no viable before-part → no match."""
    assert extract_alternatives("or something") == []


def test_do_verb_with_plurals():
    assert extract_alternatives("do pull ups or push ups") == ["Pull ups", "Push ups"]


def test_case_and_article_combined():
    """Combined article stripping and capitalization."""
    result = extract_alternatives("Should I Buy a Tesla or a Ford")
    assert result == ["Tesla", "Ford"]
