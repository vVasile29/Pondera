"""Tests for Monte Carlo simulation."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Activity, ActivityWeight, Metric
from services.monte_carlo import run_monte_carlo


@pytest.fixture(scope="function")
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    yield session
    session.close()


def test_monte_carlo_basic(db):
    """Test that Monte Carlo returns expected structure for valid activity."""
    m1 = Metric(name="Speed", category="Physical")
    m2 = Metric(name="Strength", category="Physical")
    db.add_all([m1, m2])
    db.flush()

    activity = Activity(name="Test Activity", category="Sport")
    db.add(activity)
    db.flush()

    db.add_all([
        ActivityWeight(activity_id=activity.id, metric_id=m1.id, weight=80),
        ActivityWeight(activity_id=activity.id, metric_id=m2.id, weight=60),
    ])
    db.commit()

    results = run_monte_carlo(activity.id, db, n=50)

    assert len(results) == 2

    for r in results:
        assert "metric_id" in r
        assert "metric_name" in r
        assert "avg" in r
        assert "min" in r
        assert "max" in r
        assert "stddev" in r
        assert "importance" in r
        assert 0 <= r["importance"] <= 100
        assert r["min"] <= r["avg"] <= r["max"]


def test_monte_carlo_invalid_activity(db):
    """Test that invalid activity returns empty list."""
    results = run_monte_carlo(999, db)
    assert results == []


def test_monte_carlo_no_weights(db):
    """Test activity with no weights returns empty list."""
    activity = Activity(name="Empty", category="Sport")
    db.add(activity)
    db.commit()

    results = run_monte_carlo(activity.id, db)
    assert results == []


def test_monte_carlo_importance_ordering(db):
    """Test that results are ordered by importance descending."""
    m1 = Metric(name="Speed", category="Physical")
    m2 = Metric(name="Endurance", category="Physical")
    m3 = Metric(name="Flexibility", category="Physical")
    db.add_all([m1, m2, m3])
    db.flush()

    activity = Activity(name="Three Metric", category="Sport")
    db.add(activity)
    db.flush()

    db.add_all([
        ActivityWeight(activity_id=activity.id, metric_id=m1.id, weight=50),
        ActivityWeight(activity_id=activity.id, metric_id=m2.id, weight=50),
        ActivityWeight(activity_id=activity.id, metric_id=m3.id, weight=50),
    ])
    db.commit()

    results = run_monte_carlo(activity.id, db, n=50)

    assert len(results) == 3

    # Check that importance is descending
    for i in range(len(results) - 1):
        assert results[i]["importance"] >= results[i + 1]["importance"]
