"""Unit tests for the scoring algorithm."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Activity, ActivityWeight, Candidate, CandidateScore, Metric
from services.scoring import compute_fit_score, resolve_submetrics


@pytest.fixture(scope="function")
def db():
    """Create a fresh in-memory database for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    yield session
    session.close()


def test_basic_fit_score(db):
    """Test a simple fit score computation."""
    # Create metrics
    m1 = Metric(name="Speed", category="Physical", unit="m/s")
    m2 = Metric(name="Strength", category="Physical")
    db.add_all([m1, m2])
    db.flush()

    # Create activity
    activity = Activity(name="Sprinter", category="Sport")
    db.add(activity)
    db.flush()

    # Add weights (Speed: 80, Strength: 40)
    db.add_all([
        ActivityWeight(activity_id=activity.id, metric_id=m1.id, weight=80),
        ActivityWeight(activity_id=activity.id, metric_id=m2.id, weight=40),
    ])
    db.flush()

    # Create candidate with scores
    candidate = Candidate(name="Test")
    db.add(candidate)
    db.flush()
    db.add_all([
        CandidateScore(candidate_id=candidate.id, metric_id=m1.id, score=80),
        CandidateScore(candidate_id=candidate.id, metric_id=m2.id, score=60),
    ])
    db.commit()

    # Expected:
    # numerator = 80*80 + 60*40 = 6400 + 2400 = 8800
    # denominator = 80 + 40 = 120
    # fit = 8800 / 120 / 100 = 0.7333...
    fit = compute_fit_score(candidate.id, activity.id, db)
    assert round(fit, 4) == 0.7333


def test_perfect_fit(db):
    """Test perfect score (100 on all metrics)."""
    m1 = Metric(name="Speed", category="Physical")
    m2 = Metric(name="Strength", category="Physical")
    db.add_all([m1, m2])
    db.flush()

    activity = Activity(name="Perfect Match", category="Sport")
    db.add(activity)
    db.flush()

    db.add_all([
        ActivityWeight(activity_id=activity.id, metric_id=m1.id, weight=50),
        ActivityWeight(activity_id=activity.id, metric_id=m2.id, weight=50),
    ])
    db.flush()

    candidate = Candidate(name="Perfect")
    db.add(candidate)
    db.flush()
    db.add_all([
        CandidateScore(candidate_id=candidate.id, metric_id=m1.id, score=100),
        CandidateScore(candidate_id=candidate.id, metric_id=m2.id, score=100),
    ])
    db.commit()

    fit = compute_fit_score(candidate.id, activity.id, db)
    assert fit == 1.0


def test_zero_fit(db):
    """Test fit score when candidate has no scores for the activity's metrics."""
    m1 = Metric(name="Speed", category="Physical")
    db.add(m1)
    db.flush()

    activity = Activity(name="Empty", category="Sport")
    db.add(activity)
    db.flush()

    db.add(ActivityWeight(activity_id=activity.id, metric_id=m1.id, weight=50))
    db.flush()

    candidate = Candidate(name="No Scores")
    db.add(candidate)
    db.commit()

    fit = compute_fit_score(candidate.id, activity.id, db)
    assert fit == 0.0


def test_sub_metric_resolution(db):
    """Test that sub-metrics are properly resolved."""
    # Parent metric
    parent = Metric(name="Fitness", category="Physical")
    db.add(parent)
    db.flush()

    # Child metrics
    child1 = Metric(name="Speed", category="Physical", parent_id=parent.id)
    child2 = Metric(name="Endurance", category="Physical", parent_id=parent.id)
    db.add_all([child1, child2])
    db.flush()

    activity = Activity(name="Athlete", category="Sport")
    db.add(activity)
    db.flush()

    # Parent metric weight used at activity level
    db.add(ActivityWeight(activity_id=activity.id, metric_id=parent.id, weight=100))
    db.flush()

    candidate = Candidate(name="Test")
    db.add(candidate)
    db.flush()

    # Only child scores exist (no direct parent score)
    db.add_all([
        CandidateScore(candidate_id=candidate.id, metric_id=child1.id, score=80),
        CandidateScore(candidate_id=candidate.id, metric_id=child2.id, score=60),
    ])
    db.commit()

    # Parent score should be average of children: (80 + 60) / 2 = 70
    parent_score = resolve_submetrics(candidate.id, parent.id, db)
    assert parent_score == 70.0

    # Fit = 70 * 100 / 100 / 100 = 0.7
    fit = compute_fit_score(candidate.id, activity.id, db)
    assert fit == 0.7


def test_weighted_average_sub_metrics(db):
    """Test that sub-metrics are equally weighted even with different child scores."""
    parent = Metric(name="Combat", category="Physical")
    db.add(parent)
    db.flush()

    child1 = Metric(name="Strength", category="Physical", parent_id=parent.id)
    child2 = Metric(name="Agility", category="Physical", parent_id=parent.id)
    db.add_all([child1, child2])
    db.flush()

    candidate = Candidate(name="Fighter")
    db.add(candidate)
    db.flush()

    db.add_all([
        CandidateScore(candidate_id=candidate.id, metric_id=child1.id, score=40),
        CandidateScore(candidate_id=candidate.id, metric_id=child2.id, score=100),
    ])
    db.commit()

    score = resolve_submetrics(candidate.id, parent.id, db)
    assert score == 70.0  # (40 + 100) / 2


def test_no_weights_returns_zero(db):
    """Test that an activity with no weights returns 0 fit."""
    candidate = Candidate(name="Lonely")
    db.add(candidate)
    db.commit()
    fit = compute_fit_score(candidate.id, 999, db)
    assert fit == 0.0


def test_missing_metric_score_returns_zero(db):
    """Test that a metric with no candidate score returns 0."""
    m1 = Metric(name="Speed", category="Physical")
    db.add(m1)
    db.flush()

    activity = Activity(name="Test", category="Sport")
    db.add(activity)
    db.flush()

    db.add(ActivityWeight(activity_id=activity.id, metric_id=m1.id, weight=50))
    db.flush()

    candidate = Candidate(name="Missing Score")
    db.add(candidate)
    db.commit()

    fit = compute_fit_score(candidate.id, activity.id, db)
    assert fit == 0.0
