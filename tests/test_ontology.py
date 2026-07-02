"""Direct unit tests for services/ontology.py — extract_alternatives and clean logic."""

from services.ontology import (
    OLD_TO_NEW_CATEGORY_NAMES,
    OLD_TO_NEW_METRIC_NAMES,
    UNIVERSAL_DIMENSIONS,
    UNIVERSAL_METRICS,
    extract_alternatives,
    get_universal_criteria,
)


def test_universal_metrics_have_current_shape():
    metrics = {m["name"]: m for m in UNIVERSAL_METRICS}
    assert metrics["Affordability"]["default_weight"] == 90
    assert metrics["Reliability"]["default_weight"] == 80
    assert metrics["Timeliness"]["default_weight"] == 70
    forbidden = {"direction", "higher_is_better", "lower_is_better", "score_type"}
    assert all(forbidden.isdisjoint(m) for m in UNIVERSAL_METRICS)


def test_exact_fit_ontology_contract():
    expected = [
        (
            "resource_fit",
            "Resource Fit",
            "Is the required burden acceptable and worth it?",
            [
                ("affordability", "Affordability", "How acceptable is the cost, effort, or resource burden?", "Unacceptable burden", "Acceptable but costly", "Excellent resource fit", 90),
                ("value", "Value", "How much benefit is created relative to the burden?", "Poor value", "Fair value", "Excellent value", 75),
            ],
        ),
        (
            "objective_fit",
            "Objective Fit",
            "Does this achieve the purpose of the decision?",
            [
                ("effectiveness", "Effectiveness", "How well does this solve the core problem or achieve the intended goal?", "Does not solve the problem", "Partially solves the problem", "Solves the problem extremely well", 80),
                ("quality", "Quality", "How good, complete, durable, robust, or excellent is the result?", "Low quality", "Acceptable quality", "Excellent quality", 85),
            ],
        ),
        (
            "time_fit",
            "Time Fit",
            "Does the timing work?",
            [
                ("timeliness", "Timeliness", "How well does the speed, delay, schedule, or time requirement fit the decision?", "Poor timing fit", "Acceptable timing", "Excellent timing fit", 70),
                ("efficiency", "Efficiency", "How much useful output is achieved per unit of time, effort, or input?", "Inefficient", "Acceptably efficient", "Highly efficient", 65),
            ],
        ),
        (
            "assurance_fit",
            "Assurance Fit",
            "Can we trust this option to work without unacceptable downside?",
            [
                ("reliability", "Reliability", "How likely is this option to work consistently under uncertainty?", "Unreliable or highly uncertain", "Manageable uncertainty", "Highly reliable and predictable", 80),
                ("protection", "Protection", "How well does this option avoid harm, violations, unacceptable consequences, or irreversible damage?", "Poorly protected", "Acceptably protected", "Very well protected", 75),
            ],
        ),
        (
            "people_fit",
            "People Fit",
            "Does this option fit the people affected?",
            [
                ("desirability", "Desirability", "How attractive, motivating, or personally appealing is this option?", "Undesirable", "Neutral or mixed appeal", "Highly desirable", 85),
                ("acceptance", "Acceptance", "How likely is this option to be accepted, approved, adopted, or tolerated by stakeholders?", "Likely to be rejected", "Mixed or uncertain acceptance", "Likely to be strongly accepted", 80),
            ],
        ),
        (
            "practical_fit",
            "Practical Fit",
            "Can this option realistically be done, used, accessed, operated, and adapted?",
            [
                ("feasibility", "Feasibility", "How realistic is it to obtain, implement, use, maintain, or execute this option?", "Not realistically feasible", "Feasible with effort", "Highly feasible", 70),
                ("flexibility", "Flexibility", "How well can this option adapt, scale, reverse, or remain useful if conditions change?", "Rigid or hard to change", "Somewhat adaptable", "Highly flexible and adaptable", 65),
            ],
        ),
    ]

    assert len(UNIVERSAL_DIMENSIONS) == len(expected)
    for dim, expected_dim in zip(UNIVERSAL_DIMENSIONS, expected):
        stable_id, name, question, expected_metrics = expected_dim
        assert dim["stable_id"] == stable_id
        assert dim["name"] == name
        assert dim["question"] == question
        assert len(dim["metrics"]) == len(expected_metrics)
        for metric, expected_metric in zip(dim["metrics"], expected_metrics):
            (
                metric_id,
                metric_name,
                metric_question,
                low_anchor,
                mid_anchor,
                high_anchor,
                default_weight,
            ) = expected_metric
            assert metric["stable_id"] == metric_id
            assert metric["name"] == metric_name
            assert metric["question"] == metric_question
            assert metric["low_anchor"] == low_anchor
            assert metric["mid_anchor"] == mid_anchor
            assert metric["high_anchor"] == high_anchor
            assert metric["default_weight"] == default_weight


def test_old_to_new_fit_mappings_are_exact():
    assert OLD_TO_NEW_CATEGORY_NAMES == {
        "Financial": {"name": "Resource Fit", "stable_id": "resource_fit"},
        "Quality": {"name": "Objective Fit", "stable_id": "objective_fit"},
        "Time": {"name": "Time Fit", "stable_id": "time_fit"},
        "Risk": {"name": "Assurance Fit", "stable_id": "assurance_fit"},
        "Experience": {"name": "People Fit", "stable_id": "people_fit"},
        "Convenience": {"name": "Practical Fit", "stable_id": "practical_fit"},
    }
    assert OLD_TO_NEW_METRIC_NAMES["Cost"] == {
        "name": "Affordability",
        "stable_id": "affordability",
    }
    assert OLD_TO_NEW_METRIC_NAMES["Accessibility"] == {
        "name": "Flexibility",
        "stable_id": "flexibility",
    }


def test_get_universal_criteria_returns_all_metrics():
    category, metrics = get_universal_criteria()
    assert category == "General"
    assert metrics == UNIVERSAL_METRICS


# ── Ontology invariant tests ──

EXPECTED_CATEGORY_IDS = [
    "resource_fit",
    "objective_fit",
    "time_fit",
    "assurance_fit",
    "people_fit",
    "practical_fit",
]

EXPECTED_METRIC_IDS = [
    "affordability",
    "value",
    "effectiveness",
    "quality",
    "timeliness",
    "efficiency",
    "reliability",
    "protection",
    "desirability",
    "acceptance",
    "feasibility",
    "flexibility",
]

EXPECTED_CATEGORY_NAMES = [
    "Resource Fit",
    "Objective Fit",
    "Time Fit",
    "Assurance Fit",
    "People Fit",
    "Practical Fit",
]

FORBIDDEN_METRIC_FIELDS = {"direction", "higher_is_better", "lower_is_better", "score_type"}


def test_ontology_exactly_six_categories():
    """The ontology must expose exactly these six category stable_ids."""
    assert len(UNIVERSAL_DIMENSIONS) == 6
    category_ids = [dim["stable_id"] for dim in UNIVERSAL_DIMENSIONS]
    assert category_ids == EXPECTED_CATEGORY_IDS


def test_ontology_exactly_twelve_metrics():
    """The ontology must expose exactly these twelve metric stable_ids."""
    assert len(UNIVERSAL_METRICS) == 12
    metric_ids = [m["stable_id"] for m in UNIVERSAL_METRICS]
    assert metric_ids == EXPECTED_METRIC_IDS


def test_ontology_category_names_match():
    """Each category has the expected display name."""
    for dim, expected_name in zip(UNIVERSAL_DIMENSIONS, EXPECTED_CATEGORY_NAMES):
        assert dim["name"] == expected_name, (
            f"Expected category name {expected_name!r}, got {dim['name']!r}"
        )


def test_ontology_metric_names_match():
    """Each metric has the expected display name."""
    expected_names = [
        "Affordability", "Value",
        "Effectiveness", "Quality",
        "Timeliness", "Efficiency",
        "Reliability", "Protection",
        "Desirability", "Acceptance",
        "Feasibility", "Flexibility",
    ]
    for metric, expected_name in zip(UNIVERSAL_METRICS, expected_names):
        assert metric["name"] == expected_name, (
            f"Expected metric name {expected_name!r}, got {metric['name']!r}"
        )


def test_ontology_metrics_have_no_direction_fields():
    """No metric definition contains per-metric direction or score-type fields.

    Higher-is-better is a global invariant of fit scores, not a per-metric property.
    """
    for metric in UNIVERSAL_METRICS:
        metric_keys = set(metric.keys())
        forbidden_found = metric_keys & FORBIDDEN_METRIC_FIELDS
        assert not forbidden_found, (
            f"Metric {metric['name']} contains forbidden field(s): {forbidden_found}"
        )


def test_ontology_every_metric_belongs_to_a_category():
    """Each metric's category_id matches its parent dimension's stable_id."""
    for dim in UNIVERSAL_DIMENSIONS:
        for metric in dim["metrics"]:
            assert metric["category_id"] == dim["stable_id"], (
                f"Metric {metric['name']} has category_id {metric['category_id']!r}, "
                f"expected {dim['stable_id']!r}"
            )


# ── Parser: A/B extraction tests for golden decision case queries ──


def test_extract_doctor_or_stay_home():
    """Should I go to the doctor or stay home? → ['Doctor', 'Stay home']"""
    assert extract_alternatives("Should I go to the doctor or stay home?") == [
        "Doctor",
        "Stay home",
    ]


def test_extract_buy_house_or_rent():
    """Should I buy a house or rent? → ['House', 'Rent']"""
    assert extract_alternatives("Should I buy a house or rent?") == [
        "House",
        "Rent",
    ]


def test_extract_supplier_a_or_b():
    """Should we choose Supplier A or Supplier B? → ['Supplier A', 'Supplier B']"""
    assert extract_alternatives("Should we choose Supplier A or Supplier B?") == [
        "Supplier A",
        "Supplier B",
    ]


def test_extract_build_or_buy_software():
    """Should we build or buy this software? → ['Build this software', 'Buy this software']"""
    assert extract_alternatives("Should we build or buy this software?") == [
        "Build this software",
        "Buy this software",
    ]


def test_extract_switch_jobs_or_stay():
    """Should I switch jobs or stay? → ['Switch jobs', 'Stay']"""
    assert extract_alternatives("Should I switch jobs or stay?") == [
        "Switch jobs",
        "Stay",
    ]


def test_extract_agent_send_email_or_ask():
    """Should an AI agent send this email or ask for approval?
    → ['Send this email', 'Ask for approval']"""
    assert extract_alternatives(
        "Should an AI agent send this email or ask for approval?"
    ) == [
        "Send this email",
        "Ask for approval",
    ]


# ── Basic "or" extraction ──


def test_simple_or():
    """Two items separated by 'or'."""
    assert extract_alternatives("golf or frisbee") == ["Golf", "Frisbee"]


def test_or_with_articles():
    """Articles 'a', 'an', 'the' stripped from alternatives."""
    assert extract_alternatives("a house or an apartment") == ["House", "Apartment"]


def test_or_with_the():
    assert extract_alternatives("the macbook or the thinkpad") == [
        "Macbook",
        "Thinkpad",
    ]


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
    assert extract_alternatives("should I do aikido or football") == [
        "Aikido",
        "Football",
    ]


def test_play_verb():
    """'play' verb stripped from before-part."""
    assert extract_alternatives("should I play golf or frisbee") == ["Golf", "Frisbee"]


def test_buy_verb():
    assert extract_alternatives("buy a house or an apartment") == ["House", "Apartment"]


def test_choose_verb():
    assert extract_alternatives("choose Python or JavaScript") == [
        "Python",
        "JavaScript",
    ]


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
    assert extract_alternatives("I want to learn guitar or piano") == [
        "Guitar",
        "Piano",
    ]


def test_am_i_prefix():
    assert extract_alternatives("am I ready for a dog or a cat") == [
        "Ready for a dog",
        "Cat",
    ]


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
    result = extract_alternatives(
        "should I buy a three-bedroom house or a studio apartment"
    )
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
