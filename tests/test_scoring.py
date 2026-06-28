"""Tests for the scoring algorithm (decision flow)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Decision, Activity, ActivityWeight, Metric, AlternativeScore
from services.scoring import compute_alternative_fit_scores


@pytest.fixture(scope="function")
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
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
    db.add_all([
        ActivityWeight(activity_id=alt1.id, metric_id=m1.id, weight=80),
        ActivityWeight(activity_id=alt1.id, metric_id=m2.id, weight=60),
        ActivityWeight(activity_id=alt2.id, metric_id=m1.id, weight=80),
        ActivityWeight(activity_id=alt2.id, metric_id=m2.id, weight=60),
    ])
    db.flush()

    # Scores: Option A -> Cost=30, Quality=80; Option B -> Cost=70, Quality=40
    db.add_all([
        AlternativeScore(activity_id=alt1.id, metric_id=m1.id, score=30),
        AlternativeScore(activity_id=alt1.id, metric_id=m2.id, score=80),
        AlternativeScore(activity_id=alt2.id, metric_id=m1.id, score=70),
        AlternativeScore(activity_id=alt2.id, metric_id=m2.id, score=40),
    ])
    db.commit()

    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 2
    # Option A: (30*80 + 80*60)/(80+60) = (2400+4800)/140 = 7200/140 = 51.43 → /100 = 0.5143
    # Option B: (70*80 + 40*60)/(80+60) = (5600+2400)/140 = 8000/140 = 57.14 → /100 = 0.5714
    assert results[0]["activity_name"] == "Option B"
    assert results[1]["activity_name"] == "Option A"
    assert round(results[0]["fit_score"], 4) == 0.5714
    assert round(results[1]["fit_score"], 4) == 0.5143


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


def test_paired_t_test_identical():
    """Identical scores → t=0, p=1, not significant."""
    from services.scoring import paired_t_test
    result = paired_t_test([50, 60, 70, 80], [50, 60, 70, 80])
    assert result["t_statistic"] == 0.0
    assert result["p_value"] == 1.0
    assert result["significant"] is False


def test_paired_t_test_significant():
    """Large consistent differences → significant."""
    from services.scoring import paired_t_test
    result = paired_t_test([90, 85, 88, 92], [50, 55, 60, 45])
    assert result["significant"] is True
    assert result["p_value"] < 0.05


def test_paired_t_test_insufficient():
    """Single criterion → error."""
    from services.scoring import paired_t_test
    result = paired_t_test([50], [60])
    assert "error" in result


def test_paired_t_test_mismatched_lengths():
    """Mismatched lengths → error."""
    from services.scoring import paired_t_test
    result = paired_t_test([50, 60], [50])
    assert "error" in result


def test_paired_t_test_no_difference():
    """Scores that average to same → not significant."""
    from services.scoring import paired_t_test
    result = paired_t_test([51, 49], [50, 50])
    assert result["significant"] is False
    assert result["mean_difference"] == 0.0


def test_sorting_order(db):
    decision = make_decision(db)
    m = make_metric(db, "Score")
    alt1 = make_activity(db, "Low", decision.id)
    alt2 = make_activity(db, "High", decision.id)
    db.add_all([
        ActivityWeight(activity_id=alt1.id, metric_id=m.id, weight=100),
        ActivityWeight(activity_id=alt2.id, metric_id=m.id, weight=100),
        AlternativeScore(activity_id=alt1.id, metric_id=m.id, score=30),
        AlternativeScore(activity_id=alt2.id, metric_id=m.id, score=90),
    ])
    db.commit()
    results = compute_alternative_fit_scores(decision.id, db)
    assert len(results) == 2
    assert results[0]["activity_name"] == "High"
    assert results[1]["activity_name"] == "Low"
