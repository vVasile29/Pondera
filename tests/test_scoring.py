"""Tests for the scoring algorithm (decision flow)."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Decision, Activity, DecisionWeight, Metric, AlternativeScore
from services.scoring import (
    compute_alternative_fit_scores,
    evaluate_ko_criteria,
    filter_by_thresholds,
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


def make_metric(db, name, category="Resource Fit"):
    m = Metric(name=name, category=category)
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
    m1 = make_metric(db, "Affordability")
    m2 = make_metric(db, "Quality")
    alt1 = make_activity(db, "Option A", decision.id)
    alt2 = make_activity(db, "Option B", decision.id)

    # Weights: Affordability=80, Quality=60 (decision-level, shared across all activities)
    db.add_all(
        [
            DecisionWeight(decision_id=decision.id, metric_id=m1.id, weight=80),
            DecisionWeight(decision_id=decision.id, metric_id=m2.id, weight=60),
        ]
    )
    db.flush()

    # Scores: Option A -> Affordability=30, Quality=80; Option B -> Affordability=70, Quality=40
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
    assert results[0]["activity_name"] == "Option B"
    assert results[1]["activity_name"] == "Option A"
    assert round(results[0]["fit_score"], 4) == 0.5714
    assert round(results[1]["fit_score"], 4) == 0.5143


def test_scores_are_direct_fit_values(db):
    """Scores are treated as direct fit values."""
    decision = make_decision(db)
    m = make_metric(db, "Affordability")
    alt = make_activity(db, "Cheap", decision.id)
    db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100))
    db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=30))
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 1
    assert round(results[0]["fit_score"], 4) == 0.3000


def test_mixed_metric_scoring_uses_direct_benefit_values(db):
    """Multiple metrics use direct fit scores."""
    decision = make_decision(db)
    m1 = make_metric(db, "Affordability", category="Resource Fit")
    m2 = make_metric(db, "Quality", category="Objective Fit")
    m3 = make_metric(db, "Reliability", category="Assurance Fit")
    alt1 = make_activity(db, "Option A", decision.id)
    alt2 = make_activity(db, "Option B", decision.id)

    db.add_all(
        [
            DecisionWeight(decision_id=decision.id, metric_id=m1.id, weight=80),
            DecisionWeight(decision_id=decision.id, metric_id=m2.id, weight=60),
            DecisionWeight(decision_id=decision.id, metric_id=m3.id, weight=50),
        ]
    )
    db.flush()

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
    assert results[0]["activity_name"] == "Option B"
    assert round(results[0]["fit_score"], 4) == 0.6158
    assert round(results[1]["fit_score"], 4) == 0.4737


def test_all_fit_scores_are_direct_values(db):
    """All scores are treated as fit scores."""
    decision = make_decision(db)
    m1 = make_metric(db, "Affordability")
    m2 = make_metric(db, "Reliability")
    alt1 = make_activity(db, "Good", decision.id)
    alt2 = make_activity(db, "Bad", decision.id)
    db.add_all(
        [
            DecisionWeight(decision_id=decision.id, metric_id=m1.id, weight=100),
            DecisionWeight(decision_id=decision.id, metric_id=m2.id, weight=100),
            AlternativeScore(activity_id=alt1.id, metric_id=m1.id, score=20),
            AlternativeScore(activity_id=alt1.id, metric_id=m2.id, score=30),
            AlternativeScore(activity_id=alt2.id, metric_id=m1.id, score=80),
            AlternativeScore(activity_id=alt2.id, metric_id=m2.id, score=90),
        ]
    )
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 2
    assert results[0]["activity_name"] == "Bad"
    assert round(results[0]["fit_score"], 4) == 0.8500
    assert round(results[1]["fit_score"], 4) == 0.2500


def test_boundary_scores(db):
    """Scores at 0 and 100 boundaries."""
    decision = make_decision(db)
    m1 = make_metric(db, "Affordability")
    m2 = make_metric(db, "Quality")
    alt1 = make_activity(db, "Best", decision.id)
    alt2 = make_activity(db, "Worst", decision.id)
    db.add_all(
        [
            DecisionWeight(decision_id=decision.id, metric_id=m1.id, weight=100),
            DecisionWeight(decision_id=decision.id, metric_id=m2.id, weight=100),
            AlternativeScore(activity_id=alt1.id, metric_id=m1.id, score=0),
            AlternativeScore(activity_id=alt1.id, metric_id=m2.id, score=100),
            AlternativeScore(activity_id=alt2.id, metric_id=m1.id, score=100),
            AlternativeScore(activity_id=alt2.id, metric_id=m2.id, score=0),
        ]
    )
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 2
    assert round(results[0]["fit_score"], 4) == 0.5
    assert round(results[1]["fit_score"], 4) == 0.5


def test_dimension_scores_use_direct_fit_scores(db):
    """Dimension scores should use direct fit scores."""
    from services.scoring import compute_dimension_scores

    decision = make_decision(db)
    m1 = make_metric(db, "Affordability", category="Resource Fit")
    m2 = make_metric(db, "Value", category="Resource Fit")
    alt = make_activity(db, "Option", decision.id)
    db.add_all(
        [
            DecisionWeight(decision_id=decision.id, metric_id=m1.id, weight=80),
            DecisionWeight(decision_id=decision.id, metric_id=m2.id, weight=60),
            AlternativeScore(activity_id=alt.id, metric_id=m1.id, score=30),
            AlternativeScore(activity_id=alt.id, metric_id=m2.id, score=80),
        ]
    )
    db.commit()

    dim_scores = compute_dimension_scores(decision.id, db)
    assert len(dim_scores) == 1
    fin = dim_scores[0]
    assert fin["dimension"] == "Resource Fit"
    assert fin["score"] == 51.4


def test_missing_metric_row_still_scores_directly(db):
    """Missing metric metadata does not affect direct benefit scoring."""
    decision = make_decision(db)
    m = make_metric(db, "Affordability")
    alt = make_activity(db, "Test", decision.id)
    fake_metric_id = 99999  # Does not exist in Metric table
    db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=80))
    db.add(DecisionWeight(decision_id=decision.id, metric_id=fake_metric_id, weight=60))
    db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=30))
    db.add(AlternativeScore(activity_id=alt.id, metric_id=fake_metric_id, score=80))
    db.commit()

    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 1
    assert round(results[0]["fit_score"], 4) == 0.5143


def test_perfect_score(db):
    decision = make_decision(db)
    m = make_metric(db, "Quality")
    alt = make_activity(db, "Perfect", decision.id)
    db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100))
    db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=100))
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 1
    assert results[0]["fit_score"] == 1.0


def test_zero_scores(db):
    decision = make_decision(db)
    m = make_metric(db, "Quality")
    alt = make_activity(db, "Zero", decision.id)
    db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100))
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
    # No DecisionWeight
    db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=80))
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 0  # skipped because no weights


def test_sorting_order(db):
    decision = make_decision(db)
    m = make_metric(db, "Score")
    alt1 = make_activity(db, "Low", decision.id)
    alt2 = make_activity(db, "High", decision.id)
    db.add_all(
        [
            DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100),
            AlternativeScore(activity_id=alt1.id, metric_id=m.id, score=30),
            AlternativeScore(activity_id=alt2.id, metric_id=m.id, score=90),
        ]
    )
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 2
    assert results[0]["activity_name"] == "High"
    assert results[1]["activity_name"] == "Low"


def test_increasing_any_metric_score_cannot_reduce_fit_score(db):
    decision = make_decision(db)
    m1 = make_metric(db, "Affordability")
    m2 = make_metric(db, "Protection", category="Assurance Fit")
    alt = make_activity(db, "Option", decision.id)
    db.add_all(
        [
            DecisionWeight(decision_id=decision.id, metric_id=m1.id, weight=60),
            DecisionWeight(decision_id=decision.id, metric_id=m2.id, weight=40),
            AlternativeScore(activity_id=alt.id, metric_id=m1.id, score=30),
            AlternativeScore(activity_id=alt.id, metric_id=m2.id, score=40),
        ]
    )
    db.commit()
    before = compute_alternative_fit_scores(decision.id, db)[0]["fit_score"]

    score = db.query(AlternativeScore).filter_by(activity_id=alt.id, metric_id=m1.id).one()
    score.score = 80
    db.commit()
    after = compute_alternative_fit_scores(decision.id, db)[0]["fit_score"]

    assert after >= before


# ── Threshold filtering tests ──


class TestFilterByThresholds:
    def test_all_pass(self, db):
        decision = make_decision(db)
        m = make_metric(db, "Affordability")
        alt = make_activity(db, "Good Fit", decision.id)
        db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100))
        db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=80))
        decision.thresholds = json.dumps(
            [{"metric_id": m.id, "operator": ">=", "value": 60}]
        )
        db.commit()

        result = filter_by_thresholds(decision.id, db)
        assert result["all_passed"] is True
        assert len(result["passed"]) == 1
        assert len(result["failed"]) == 0

    def test_one_fails_one_passes(self, db):
        decision = make_decision(db)
        m = make_metric(db, "Affordability")
        alt1 = make_activity(db, "Affordable", decision.id)
        alt2 = make_activity(db, "Poor Fit", decision.id)
        db.add_all(
            [
                DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100),
                AlternativeScore(activity_id=alt1.id, metric_id=m.id, score=80),
                AlternativeScore(activity_id=alt2.id, metric_id=m.id, score=30),
            ]
        )
        decision.thresholds = json.dumps(
            [{"metric_id": m.id, "operator": ">=", "value": 60}]
        )
        db.commit()

        result = filter_by_thresholds(decision.id, db)
        assert result["all_passed"] is False
        assert len(result["passed"]) == 1
        assert len(result["failed"]) == 1
        assert result["passed"][0]["activity_name"] == "Affordable"
        assert result["failed"][0]["activity_name"] == "Poor Fit"

    def test_all_fail(self, db):
        decision = make_decision(db)
        m = make_metric(db, "Affordability")
        alt = make_activity(db, "Poor Fit", decision.id)
        db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100))
        db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=30))
        decision.thresholds = json.dumps(
            [{"metric_id": m.id, "operator": ">=", "value": 60}]
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
        db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100))
        db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=85))
        db.commit()

        result = filter_by_thresholds(decision.id, db)
        assert result["all_passed"] is True
        assert len(result["passed"]) == 1
        assert len(result["failed"]) == 0
        assert len(result["survivor_results"]) == 1

    def test_fit_score_minimum_threshold(self, db):
        """Affordability >= 30 with score 50 should pass; score 20 should fail."""
        decision = make_decision(db)
        m = make_metric(db, "Affordability")
        alt_good = make_activity(db, "LowCost", decision.id)
        alt_bad = make_activity(db, "HighCost", decision.id)
        db.add_all(
            [
                DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100),
                AlternativeScore(activity_id=alt_good.id, metric_id=m.id, score=50),
                AlternativeScore(activity_id=alt_bad.id, metric_id=m.id, score=20),
            ]
        )
        decision.thresholds = json.dumps(
            [{"metric_id": m.id, "operator": ">=", "value": 30}]
        )
        db.commit()

        result = filter_by_thresholds(decision.id, db)
        assert result["all_passed"] is False
        assert len(result["passed"]) == 1
        assert result["passed"][0]["activity_name"] == "LowCost"
        assert len(result["failed"]) == 1
        assert result["failed"][0]["activity_name"] == "HighCost"


# ── KO (Knock-Out) criteria tests ──


class TestEvaluateKoCriteria:
    def test_no_ko_returns_none(self, db):
        """No KO criteria -> None."""
        decision = make_decision(db)
        m = make_metric(db, "Affordability")
        alt = make_activity(db, "Option", decision.id)
        db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100))
        db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=80))
        db.commit()

        result = evaluate_ko_criteria(decision.id, db)
        assert result is None

    def test_ko_all_pass(self, db):
        """All metrics scored meets thresholds."""
        decision = make_decision(db)
        m = make_metric(db, "Affordability")
        alt = make_activity(db, "Good", decision.id)
        db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100))
        db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=80))
        decision.ko_criteria = json.dumps(
            [{"metric_id": m.id, "ko_operator": ">=", "ko_value": 60}]
        )
        db.commit()

        result = evaluate_ko_criteria(decision.id, db)
        assert result is not None
        assert result["all_passed"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["status"] == "passed"
        assert result["eligible_activity_ids"] == [alt.id]

    def test_ko_one_fails(self, db):
        """One alternative fails, one passes."""
        decision = make_decision(db)
        m = make_metric(db, "Affordability")
        alt1 = make_activity(db, "Pass", decision.id)
        alt2 = make_activity(db, "Fail", decision.id)
        db.add_all(
            [
                DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100),
                AlternativeScore(activity_id=alt1.id, metric_id=m.id, score=80),
                AlternativeScore(activity_id=alt2.id, metric_id=m.id, score=30),
            ]
        )
        decision.ko_criteria = json.dumps(
            [{"metric_id": m.id, "ko_operator": ">=", "ko_value": 60}]
        )
        db.commit()

        result = evaluate_ko_criteria(decision.id, db)
        assert result is not None
        assert result["all_passed"] is False
        assert len(result["results"]) == 2
        passed = [r for r in result["results"] if r["status"] == "passed"]
        knocked = [r for r in result["results"] if r["status"] == "knocked_out"]
        assert len(passed) == 1
        assert passed[0]["activity_name"] == "Pass"
        assert len(knocked) == 1
        assert knocked[0]["activity_name"] == "Fail"
        assert len(knocked[0]["reasons"]) > 0
        assert result["eligible_activity_ids"] == [alt1.id]

    def test_ko_all_fail(self, db):
        """All fail KO."""
        decision = make_decision(db)
        m = make_metric(db, "Affordability")
        alt1 = make_activity(db, "Low", decision.id)
        alt2 = make_activity(db, "Lower", decision.id)
        db.add_all(
            [
                DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100),
                AlternativeScore(activity_id=alt1.id, metric_id=m.id, score=30),
                AlternativeScore(activity_id=alt2.id, metric_id=m.id, score=20),
            ]
        )
        decision.ko_criteria = json.dumps(
            [{"metric_id": m.id, "ko_operator": ">=", "ko_value": 60}]
        )
        db.commit()

        result = evaluate_ko_criteria(decision.id, db)
        assert result is not None
        assert result["all_passed"] is False
        assert all(r["status"] == "knocked_out" for r in result["results"])
        assert result["eligible_activity_ids"] == []

    def test_ko_missing_score(self, db):
        """Missing score -> knocked_out."""
        decision = make_decision(db)
        m = make_metric(db, "Affordability")
        make_activity(db, "NoScore", decision.id)
        db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100))
        # No AlternativeScore added
        decision.ko_criteria = json.dumps(
            [{"metric_id": m.id, "ko_operator": ">=", "ko_value": 60}]
        )
        db.commit()

        result = evaluate_ko_criteria(decision.id, db)
        assert result is not None
        assert result["all_passed"] is False
        assert result["results"][0]["status"] == "knocked_out"
        assert any("No score available" in r for r in result["results"][0]["reasons"])
        assert result["eligible_activity_ids"] == []

    def test_ko_boundary_score(self, db):
        """Score == threshold -> pass."""
        decision = make_decision(db)
        m = make_metric(db, "Affordability")
        alt = make_activity(db, "Boundary", decision.id)
        db.add(DecisionWeight(decision_id=decision.id, metric_id=m.id, weight=100))
        db.add(AlternativeScore(activity_id=alt.id, metric_id=m.id, score=60))
        decision.ko_criteria = json.dumps(
            [{"metric_id": m.id, "ko_operator": ">=", "ko_value": 60}]
        )
        db.commit()

        result = evaluate_ko_criteria(decision.id, db)
        assert result is not None
        assert result["all_passed"] is True
        assert result["results"][0]["status"] == "passed"
        assert result["eligible_activity_ids"] == [alt.id]
