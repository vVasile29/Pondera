"""Tests for the scoring algorithm (decision flow)."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Decision, Activity, ActivityWeight, Metric, AlternativeScore
from services.scoring import (
    compute_alternative_fit_scores,
    filter_by_thresholds,
    paired_t_test,
)


@pytest.fixture(scope="function")
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    yield session
    session.close()


def make_decision(db, query="Test decision?"):
    d = Decision(query=query, category="General")
    db.add(d)
    db.flush()
    return d


def make_metric(db, name, category="Financial", higher_is_better=True):
    m = Metric(name=name, category=category, higher_is_better=higher_is_better)
    db.add(m)
    db.flush()
    return m


def make_activity(db, name, decision_id):
    a = Activity(name=name, category="General", decision_id=decision_id)
    db.add(a)
    db.flush()
    return a


def test_basic_scoring(db):
    decision = make_decision(db)
    m1 = make_metric(db, "Cost", higher_is_better=False)
    m2 = make_metric(db, "Quality")
    alt1 = make_activity(db, "Option A", decision.id)
    alt2 = make_activity(db, "Option B", decision.id)

    # Weights: Cost=80, Quality=60
    db.add_all(
        [
            ActivityWeight(activity_id=alt1.id, metric_id=m1.id, weight=80),
            ActivityWeight(activity_id=alt1.id, metric_id=m2.id, weight=60),
            ActivityWeight(activity_id=alt2.id, metric_id=m1.id, weight=80),
            ActivityWeight(activity_id=alt2.id, metric_id=m2.id, weight=60),
        ]
    )
    db.flush()

    # Scores: Option A -> Cost=30, Quality=80; Option B -> Cost=70, Quality=40
    db.add_all(
        [
            AlternativeScore(activity_id=alt1.id, metric_id=m1.id, score=30),
            AlternativeScore(activity_id=alt1.id, metric_id=m2.id, score=80),
            AlternativeScore(activity_id=alt2.id, metric_id=m1.id, score=70),
            AlternativeScore(activity_id=alt2.id, metric_id=m2.id, score=40),
        ]
    )
    db.commit()

    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 2
    # Cost is lower-is-better (inverted):
    #   Option A: effective Cost = 100-30 = 70, numerator = 70*80 + 80*60 = 10400
    #             fit = 10400/140/100 = 74.2857/100 = 0.7429
    #   Option B: effective Cost = 100-70 = 30, numerator = 30*80 + 40*60 = 4800
    #             fit = 4800/140/100 = 34.2857/100 = 0.3429
    assert results[0]["activity_name"] == "Option A"
    assert results[1]["activity_name"] == "Option B"
    assert round(results[0]["fit_score"], 4) == 0.7429
    assert round(results[1]["fit_score"], 4) == 0.3429


def test_lower_is_better_scoring(db):
    """Single metric that is lower-is-better should be inverted."""
    decision = make_decision(db)
    m = make_metric(db, "Cost", higher_is_better=False)
    alt = make_activity(db, "Cheap", decision.id)
    db.add(ActivityWeight(activity_id=alt.id, metric_id=m.id, weight=100))
    db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=30))
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 1
    # effective_score = 100 - 30 = 70
    # fit = 70*100/100/100 = 0.7000
    assert round(results[0]["fit_score"], 4) == 0.7000


def test_mixed_direction_scoring(db):
    """Multiple metrics with mixed lower/higher-is-better directions."""
    decision = make_decision(db)
    m1 = make_metric(db, "Cost", category="Financial", higher_is_better=False)
    m2 = make_metric(db, "Quality", category="Quality", higher_is_better=True)
    m3 = make_metric(db, "Risk", category="Risk", higher_is_better=False)
    alt1 = make_activity(db, "Option A", decision.id)
    alt2 = make_activity(db, "Option B", decision.id)

    db.add_all(
        [
            ActivityWeight(activity_id=alt1.id, metric_id=m1.id, weight=80),
            ActivityWeight(activity_id=alt1.id, metric_id=m2.id, weight=60),
            ActivityWeight(activity_id=alt1.id, metric_id=m3.id, weight=50),
            ActivityWeight(activity_id=alt2.id, metric_id=m1.id, weight=80),
            ActivityWeight(activity_id=alt2.id, metric_id=m2.id, weight=60),
            ActivityWeight(activity_id=alt2.id, metric_id=m3.id, weight=50),
        ]
    )
    db.flush()

    # Option A: Cost=40, Quality=80, Risk=20
    #   effective: Cost=60, Quality=80, Risk=80
    #   numerator = 60*80 + 80*60 + 80*50 = 13600
    #   denominator = 190, fit = 13600/190/100 = 0.7158
    # Option B: Cost=80, Quality=30, Risk=70
    #   effective: Cost=20, Quality=30, Risk=30
    #   numerator = 20*80 + 30*60 + 30*50 = 4900
    #   denominator = 190, fit = 4900/190/100 = 0.2579
    db.add_all(
        [
            AlternativeScore(activity_id=alt1.id, metric_id=m1.id, score=40),
            AlternativeScore(activity_id=alt1.id, metric_id=m2.id, score=80),
            AlternativeScore(activity_id=alt1.id, metric_id=m3.id, score=20),
            AlternativeScore(activity_id=alt2.id, metric_id=m1.id, score=80),
            AlternativeScore(activity_id=alt2.id, metric_id=m2.id, score=30),
            AlternativeScore(activity_id=alt2.id, metric_id=m3.id, score=70),
        ]
    )
    db.commit()

    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 2
    assert results[0]["activity_name"] == "Option A"
    assert round(results[0]["fit_score"], 4) == 0.7158
    assert round(results[1]["fit_score"], 4) == 0.2579


def test_all_lower_is_better_scoring(db):
    """All metrics are lower-is-better — higher raw scores should rank lower."""
    decision = make_decision(db)
    m1 = make_metric(db, "Cost", higher_is_better=False)
    m2 = make_metric(db, "Risk", higher_is_better=False)
    alt1 = make_activity(db, "Good", decision.id)
    alt2 = make_activity(db, "Bad", decision.id)
    db.add_all(
        [
            ActivityWeight(activity_id=alt1.id, metric_id=m1.id, weight=100),
            ActivityWeight(activity_id=alt1.id, metric_id=m2.id, weight=100),
            ActivityWeight(activity_id=alt2.id, metric_id=m1.id, weight=100),
            ActivityWeight(activity_id=alt2.id, metric_id=m2.id, weight=100),
            AlternativeScore(activity_id=alt1.id, metric_id=m1.id, score=20),
            AlternativeScore(activity_id=alt1.id, metric_id=m2.id, score=30),
            AlternativeScore(activity_id=alt2.id, metric_id=m1.id, score=80),
            AlternativeScore(activity_id=alt2.id, metric_id=m2.id, score=90),
        ]
    )
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 2
    # Good: effective Cost=80, Risk=70 → numerator = 15000, denom=200, fit=0.7500
    # Bad: effective Cost=20, Risk=10 → numerator = 3000, denom=200, fit=0.1500
    assert results[0]["activity_name"] == "Good"
    assert round(results[0]["fit_score"], 4) == 0.7500
    assert round(results[1]["fit_score"], 4) == 0.1500


def test_boundary_scores(db):
    """Scores at 0 and 100 boundaries with mixed direction."""
    decision = make_decision(db)
    m1 = make_metric(db, "Cost", higher_is_better=False)
    m2 = make_metric(db, "Quality", higher_is_better=True)
    alt1 = make_activity(db, "Best", decision.id)
    alt2 = make_activity(db, "Worst", decision.id)
    db.add_all(
        [
            ActivityWeight(activity_id=alt1.id, metric_id=m1.id, weight=100),
            ActivityWeight(activity_id=alt1.id, metric_id=m2.id, weight=100),
            ActivityWeight(activity_id=alt2.id, metric_id=m1.id, weight=100),
            ActivityWeight(activity_id=alt2.id, metric_id=m2.id, weight=100),
            # Best: Cost=0 (inverted to 100), Quality=100 → 20000/200/100 = 1.0
            AlternativeScore(activity_id=alt1.id, metric_id=m1.id, score=0),
            AlternativeScore(activity_id=alt1.id, metric_id=m2.id, score=100),
            # Worst: Cost=100 (inverted to 0), Quality=0 → 0/200/100 = 0.0
            AlternativeScore(activity_id=alt2.id, metric_id=m1.id, score=100),
            AlternativeScore(activity_id=alt2.id, metric_id=m2.id, score=0),
        ]
    )
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 2
    assert round(results[0]["fit_score"], 4) == 1.0
    assert round(results[1]["fit_score"], 4) == 0.0


def test_dimension_scores_inversion(db):
    """Dimension scores should use effective (inverted) scores for lower-is-better metrics."""
    from services.scoring import compute_dimension_scores

    decision = make_decision(db)
    m1 = make_metric(db, "Cost", category="Financial", higher_is_better=False)
    m2 = make_metric(db, "Value", category="Financial", higher_is_better=True)
    alt = make_activity(db, "Option", decision.id)
    db.add_all(
        [
            ActivityWeight(activity_id=alt.id, metric_id=m1.id, weight=80),
            ActivityWeight(activity_id=alt.id, metric_id=m2.id, weight=60),
            AlternativeScore(activity_id=alt.id, metric_id=m1.id, score=30),
            AlternativeScore(activity_id=alt.id, metric_id=m2.id, score=80),
        ]
    )
    db.commit()

    dim_scores = compute_dimension_scores(decision.id, db)
    assert len(dim_scores) == 1
    fin = dim_scores[0]
    assert fin["dimension"] == "Financial"
    # With inversion: Cost effective=70, Value effective=80
    #   weighted avg = (70*80 + 80*60) / (80+60) = 10400/140 = 74.2857 → 74.3
    # Without inversion: (30*80 + 80*60) / 140 = 7200/140 = 51.4
    assert fin["score"] == 74.3
    assert fin["score"] != 51.4  # would be without inversion


def test_higher_is_better_map_missing_metric(db):
    """Missing metric in higher_is_better_map defaults to True (higher-is-better)."""
    decision = make_decision(db)
    m = make_metric(db, "Cost", higher_is_better=False)
    alt = make_activity(db, "Test", decision.id)
    fake_metric_id = 99999  # Does not exist in Metric table
    db.add(ActivityWeight(activity_id=alt.id, metric_id=m.id, weight=80))
    db.add(ActivityWeight(activity_id=alt.id, metric_id=fake_metric_id, weight=60))
    db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=30))
    db.add(AlternativeScore(activity_id=alt.id, metric_id=fake_metric_id, score=80))
    db.commit()

    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 1
    # Cost (known, lower_is_better=False): effective = 100-30 = 70
    # fake_metric_id (no Metric row): defaults to higher_is_better=True, effective = 80
    # numerator = 70*80 + 80*60 = 10400, denom = 140, fit = 10400/140/100 = 0.7429
    assert round(results[0]["fit_score"], 4) == 0.7429


def test_perfect_score(db):
    decision = make_decision(db)
    m = make_metric(db, "Quality")
    alt = make_activity(db, "Perfect", decision.id)
    db.add(ActivityWeight(activity_id=alt.id, metric_id=m.id, weight=100))
    db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=100))
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 1
    assert results[0]["fit_score"] == 1.0


def test_zero_scores(db):
    decision = make_decision(db)
    m = make_metric(db, "Quality")
    alt = make_activity(db, "Zero", decision.id)
    db.add(ActivityWeight(activity_id=alt.id, metric_id=m.id, weight=100))
    db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=0))
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 1
    assert results[0]["fit_score"] == 0.0


def test_no_activities(db):
    decision = make_decision(db)
    results = compute_alternative_fit_scores(decision.id, db)
    assert results == []


def test_no_weights_skipped(db):
    decision = make_decision(db)
    m = make_metric(db, "Quality")
    alt = make_activity(db, "No Weights", decision.id)
    # No ActivityWeight
    db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=80))
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 0  # skipped because no weights


# ── Paired t-test tests ──


def test_paired_t_test_highly_significant():
    result = paired_t_test([98, 96, 97, 95, 99], [40, 42, 41, 43, 39])
    assert result["significant"] is True
    assert result["p_value"] < 0.01


def test_paired_t_test_single_alternative_no_significance():
    result = paired_t_test([85], [70])
    assert "error" in result
    assert "Need at least 2" in result["error"]


def test_paired_t_test_equal_scores():
    result = paired_t_test([50, 60, 70, 80], [50, 60, 70, 80])
    assert result["t_statistic"] == 0.0
    assert result["p_value"] == 1.0
    assert result["significant"] is False


def test_paired_t_test_marginally_significant():
    result = paired_t_test([53, 53, 53, 53, 62], [50, 50, 50, 50, 50])
    assert 0.05 <= result["p_value"] < 0.10
    assert result["significant"] is False


def test_paired_t_test_not_significant():
    result = paired_t_test([62, 55, 70, 61], [60, 58, 68, 63])
    assert result["p_value"] >= 0.10
    assert result["significant"] is False


def test_paired_t_test_equal_scores_p_value_not_zero_regression():
    result = paired_t_test([51, 49, 70, 70], [51, 49, 70, 70])
    assert result["p_value"] != 0.0
    assert result["significant"] is False


def test_sorting_order(db):
    decision = make_decision(db)
    m = make_metric(db, "Score")
    alt1 = make_activity(db, "Low", decision.id)
    alt2 = make_activity(db, "High", decision.id)
    db.add_all(
        [
            ActivityWeight(activity_id=alt1.id, metric_id=m.id, weight=100),
            ActivityWeight(activity_id=alt2.id, metric_id=m.id, weight=100),
            AlternativeScore(activity_id=alt1.id, metric_id=m.id, score=30),
            AlternativeScore(activity_id=alt2.id, metric_id=m.id, score=90),
        ]
    )
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 2
    assert results[0]["activity_name"] == "High"
    assert results[1]["activity_name"] == "Low"


# ── Threshold filtering tests ──


class TestFilterByThresholds:
    def test_all_pass(self, db):
        decision = make_decision(db)
        m = make_metric(db, "Cost")
        alt = make_activity(db, "Cheap", decision.id)
        db.add(ActivityWeight(activity_id=alt.id, metric_id=m.id, weight=100))
        db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=30))
        decision.thresholds = json.dumps(
            [{"metric_id": m.id, "operator": "<=", "value": 60}]
        )
        db.commit()

        result = filter_by_thresholds(decision.id, db)
        assert result["all_passed"] is True
        assert len(result["passed"]) == 1
        assert len(result["failed"]) == 0

    def test_one_fails_one_passes(self, db):
        decision = make_decision(db)
        m = make_metric(db, "Cost")
        alt1 = make_activity(db, "Cheap", decision.id)
        alt2 = make_activity(db, "Expensive", decision.id)
        db.add_all(
            [
                ActivityWeight(activity_id=alt1.id, metric_id=m.id, weight=100),
                ActivityWeight(activity_id=alt2.id, metric_id=m.id, weight=100),
                AlternativeScore(activity_id=alt1.id, metric_id=m.id, score=30),
                AlternativeScore(activity_id=alt2.id, metric_id=m.id, score=80),
            ]
        )
        decision.thresholds = json.dumps(
            [{"metric_id": m.id, "operator": "<=", "value": 60}]
        )
        db.commit()

        result = filter_by_thresholds(decision.id, db)
        assert result["all_passed"] is False
        assert len(result["passed"]) == 1
        assert len(result["failed"]) == 1
        assert result["passed"][0]["activity_name"] == "Cheap"
        assert result["failed"][0]["activity_name"] == "Expensive"

    def test_all_fail(self, db):
        decision = make_decision(db)
        m = make_metric(db, "Cost")
        alt = make_activity(db, "Expensive", decision.id)
        db.add(ActivityWeight(activity_id=alt.id, metric_id=m.id, weight=100))
        db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=80))
        decision.thresholds = json.dumps(
            [{"metric_id": m.id, "operator": "<=", "value": 60}]
        )
        db.commit()

        result = filter_by_thresholds(decision.id, db)
        assert result["all_passed"] is False
        assert len(result["passed"]) == 0
        assert len(result["failed"]) == 1
        assert result["survivor_results"] == []

    def test_no_thresholds_all_pass(self, db):
        decision = make_decision(db)
        m = make_metric(db, "Quality")
        alt = make_activity(db, "Good", decision.id)
        db.add(ActivityWeight(activity_id=alt.id, metric_id=m.id, weight=100))
        db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=85))
        db.commit()

        result = filter_by_thresholds(decision.id, db)
        assert result["all_passed"] is True
        assert len(result["passed"]) == 1
        assert len(result["failed"]) == 0
        assert len(result["survivor_results"]) == 1

    def test_lower_is_better_direction(self, db):
        """Cost <= 30 with score 20 should pass; score 50 should fail."""
        decision = make_decision(db)
        m = make_metric(db, "Cost")
        alt_good = make_activity(db, "LowCost", decision.id)
        alt_bad = make_activity(db, "HighCost", decision.id)
        db.add_all(
            [
                ActivityWeight(activity_id=alt_good.id, metric_id=m.id, weight=100),
                ActivityWeight(activity_id=alt_bad.id, metric_id=m.id, weight=100),
                AlternativeScore(activity_id=alt_good.id, metric_id=m.id, score=20),
                AlternativeScore(activity_id=alt_bad.id, metric_id=m.id, score=50),
            ]
        )
        decision.thresholds = json.dumps(
            [{"metric_id": m.id, "operator": "<=", "value": 30}]
        )
        db.commit()

        result = filter_by_thresholds(decision.id, db)
        assert result["all_passed"] is False
        assert len(result["passed"]) == 1
        assert result["passed"][0]["activity_name"] == "LowCost"
        assert len(result["failed"]) == 1
        assert result["failed"][0]["activity_name"] == "HighCost"
