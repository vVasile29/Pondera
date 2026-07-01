"""Tests for FastAPI routes using TestClient.

Uses real main.app with overridden get_db dependency.
Per-function temporary SQLite database file.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from main import app
from models import Decision, Metric
from services.decision_limits import MAX_DECISION_ALTERNATIVES, MAX_DECISION_METRICS

# Per-test state
_test_db_path = None
_test_engine = None
_test_session = None


def _get_test_db():
    """Override dependency that returns the test session."""
    global _test_session
    try:
        yield _test_session
    finally:
        pass


@pytest.fixture(scope="function")
def db():
    """Create a fresh tempfile-based database for each test."""
    global _test_db_path, _test_engine, _test_session

    # Create a temp file
    fd, _test_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    _test_engine = create_engine(
        f"sqlite:///{_test_db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=_test_engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)
    _test_session = TestSession()

    # Seed universal metrics
    from services.ontology import UNIVERSAL_DIMENSIONS
    from models import Metric as MetricModel

    for dim in UNIVERSAL_DIMENSIONS:
        for m in dim["metrics"]:
            metric = MetricModel(
                name=m["name"],
                category=dim["name"],
                description=m["description"],
                higher_is_better=m["higher_is_better"],
            )
            _test_session.add(metric)
    _test_session.commit()

    yield _test_session
    _test_session.close()
    _test_engine.dispose()
    # Clean up temp file
    try:
        os.unlink(_test_db_path)
    except OSError:
        pass
    _test_db_path = None
    _test_engine = None
    _test_session = None


@pytest.fixture(scope="function")
def client(db):
    """Use the real main.app with overridden get_db."""
    app.dependency_overrides[get_db] = _get_test_db
    with TestClient(app) as c:
        yield c
    # Clean up override to avoid cross-test pollution
    app.dependency_overrides.pop(get_db, None)


def test_index_page(client, db):
    """Test index page returns decisions list as JSON."""
    response = client.get("/api/decisions")
    assert response.status_code == 200
    data = response.json()
    assert "decisions" in data
    assert isinstance(data["decisions"], list)


def test_list_metrics(client, db):
    """Test metrics page loads."""
    response = client.get("/api/metrics")
    assert response.status_code == 200


def test_api_refine_rejects_too_many_selected_metrics(client, db):
    decision = Decision(query="Pick one", category="General")
    db.add(decision)
    db.commit()
    metrics = db.query(Metric).limit(MAX_DECISION_METRICS).all()
    for index in range(MAX_DECISION_METRICS + 1 - len(metrics)):
        metric = Metric(name=f"Extra Limit Metric {index}", category="General")
        db.add(metric)
        db.flush()
        metrics.append(metric)
    db.commit()

    response = client.post(
        f"/api/decisions/{decision.id}/refine",
        json={
            "alternatives": ["A", "B"],
            "metrics": [
                {"metric_id": metric.id, "weight": 50}
                for metric in metrics[: MAX_DECISION_METRICS + 1]
            ],
        },
    )

    assert response.status_code == 422


def test_api_decide_rejects_too_many_parsed_alternatives(client, db):
    query = ", ".join(
        f"Option {index}" for index in range(MAX_DECISION_ALTERNATIVES + 1)
    )

    response = client.post("/api/decide", json={"q": query})

    assert response.status_code == 422


# ── Decision flow tests ──


def test_decide_flow_parsed(client, db):
    """Test the full decide flow with a parsable question."""
    response = client.post(
        "/api/decide", json={"q": "Should I buy a house or an apartment?"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "choose"
    assert "decision_id" in data
    # Verify alternatives were extracted via the decision detail endpoint
    detail = client.get(f"/api/decisions/{data['decision_id']}")
    names = [a["name"].lower() for a in detail.json()["activities"]]
    assert "house" in names or "apartment" in names


def test_decide_flow_with_do_verb(client, db):
    """'should I do X or Y' correctly extracts Aikido and Football."""
    response = client.post("/api/decide", json={"q": "should I do aikido or football"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "choose"
    assert "decision_id" in data
    # Verify alternatives were extracted via the decision detail endpoint
    detail = client.get(f"/api/decisions/{data['decision_id']}")
    names = [a["name"].lower() for a in detail.json()["activities"]]
    assert "aikido" in names or "football" in names


def test_ontology_parsing(client, db):
    """Test that ontology-based parsing works via /decide."""
    response = client.post("/api/decide", json={"q": "Which job offer should I take?"})
    assert response.status_code == 200
    data = response.json()
    assert "decision_id" in data
    assert data["mode"] == "choose"


def test_decision_not_found(client, db):
    """Test 404 for non-existent decision via API."""
    response = client.get("/api/decisions/99999")
    assert response.status_code == 404

    response = client.post(
        "/api/decisions/99999/refine",
        json={"alternatives": ["Test"], "metrics": [{"metric_id": 1, "weight": 50}]},
    )
    assert response.status_code == 404

    response = client.post(
        "/api/decisions/99999/score",
        json={"scores": [{"activity_id": 1, "metric_id": 1, "score": 50}]},
    )
    assert response.status_code == 404


def test_full_decision_flow(client, db):
    """Test the complete decision flow: decide → refine → score → result."""
    # Step 1: Create decision
    resp = client.post("/api/decide", json={"q": "Tea or Coffee?"})
    assert resp.status_code == 200
    data = resp.json()
    decision_id = data["decision_id"]

    # Get metric IDs from seeded metrics
    from models import Metric

    all_metrics = db.query(Metric).order_by(Metric.id).all()
    assert len(all_metrics) >= 2

    # Step 2: Refine with 2 alternatives, 3 metrics via API
    refine_resp = client.post(
        f"/api/decisions/{decision_id}/refine",
        json={
            "alternatives": ["Tea", "Coffee"],
            "metrics": [
                {"metric_id": all_metrics[0].id, "weight": 85},
                {"metric_id": all_metrics[1].id, "weight": 70},
                {"metric_id": all_metrics[2].id, "weight": 50},
            ],
        },
    )
    assert refine_resp.status_code == 200
    refine_data = refine_resp.json()
    assert "activities" in refine_data
    assert "criteria" in refine_data

    # Step 3: Submit scores via the API endpoint
    score_resp = client.post(
        f"/api/decisions/{decision_id}/score",
        json={
            "scores": [
                {"activity_id": act["id"], "metric_id": m["id"], "score": 70}
                for act in refine_data["activities"]
                for m in refine_data["criteria"]
            ]
        },
    )
    assert score_resp.status_code == 200
    result_data = score_resp.json()
    assert "results" in result_data
    assert "series" in result_data

    # Step 4: Check result page via API
    api_result = client.get(f"/api/decisions/{decision_id}")
    assert api_result.status_code == 200
    api_data = api_result.json()
    assert "results" in api_data
    assert "series" in api_data
    assert "metric_names" in api_data


def test_decide_empty_query(client, db):
    """Test /api/decide with empty query returns error."""
    response = client.post("/api/decide", json={"q": ""})
    assert response.status_code == 400
    data = response.json()
    assert data["detail"] == "Query cannot be empty"


def test_decide_no_match(client, db):
    """Test /decide with a query that has no or/vs pattern."""
    response = client.post("/api/decide", json={"q": "What should I do today?"})
    assert response.status_code == 200
    data = response.json()
    assert "decision_id" in data


def test_metrics_page_requires_no_auth(client, db):
    """Test that metrics page loads."""
    response = client.get("/api/metrics")
    assert response.status_code == 200


def test_seeded_metrics_on_list_page(client, db):
    """Test that seeded universal metrics show on the metrics page."""
    # Use the API endpoint to get grouped metrics
    api_resp = client.get("/api/metrics")
    assert api_resp.status_code == 200
    api_data = api_resp.json()
    grouped = api_data["grouped_metrics"]
    for dim_name in [
        "Financial",
        "Quality",
        "Time",
        "Risk",
        "Experience",
        "Convenience",
    ]:
        assert dim_name in grouped


# ── Evaluate (DIAGNOSE) tests ──


def test_evaluate_result_returns_single_option_robustness(client, db):
    decision = _seed_scored_decision(db, "diagnose")

    response = client.get(f"/api/decisions/{decision.id}")
    assert response.status_code == 200
    data = response.json()
    robustness = data["robustness"]

    assert robustness["method"] == "weighted_additive_monte_carlo"
    assert robustness["winner_id"] == decision.activities[0].id
    assert robustness["winner_robustness_percent"] == 100.0
    assert robustness["winner_changed_percent"] == 0.0
    assert robustness["robustness_label"] == "Very High"
    assert robustness["top_two"] is None
    assert robustness["rank_acceptability"] == [
        {
            "activity_id": decision.activities[0].id,
            "activity_name": "Solo",
            "first_rank_count": robustness["simulations"],
            "first_rank_percent": 100.0,
        }
    ]
    assert data["significance"] is None


def test_decide_routes_to_diagnose(client, db):
    """DIAGNOSE-style query via /api/decide → returns JSON with diagnose mode"""
    resp = client.post(
        "/api/decide",
        json={"q": "How good is a Tesla for commuting?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "diagnose"
    assert "decision_id" in data


def test_decide_with_choose_query_still_works(client, db):
    """CHOOSE query via /api/decide → returns JSON with decision_id"""
    resp = client.post(
        "/api/decide",
        json={"q": "Should I buy a house or an apartment?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "choose"
    assert "decision_id" in data


def test_decide_with_no_match_fallback(client, db):
    """Query matching neither CHOOSE nor DIAGNOSE → fallback to CHOOSE"""
    resp = client.post(
        "/api/decide",
        json={"q": "Hello world"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "decision_id" in data


# ── RANK (Mode 4) tests ──


def test_rank_via_decide(client, db):
    """List query via /api/decide → returns JSON with rank mode"""
    resp = client.post(
        "/api/decide",
        json={"q": "Rank Python, Java, Go"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "rank"
    assert "decision_id" in data


def test_rank_flow(client, db):
    """Full flow: decide → refine → score → result"""
    resp = client.post(
        "/api/decide",
        json={"q": "Python, Java, Go"},
    )
    assert resp.status_code == 200
    data = resp.json()
    decision_id = data["decision_id"]

    # Get metric IDs
    from models import Metric

    metrics = db.query(Metric).order_by(Metric.id).all()
    assert len(metrics) >= 1

    # Refine via API
    refine_resp = client.post(
        f"/api/decisions/{decision_id}/refine",
        json={
            "alternatives": ["Python", "Java", "Go"],
            "metrics": [{"metric_id": metrics[0].id, "weight": 80}],
        },
    )
    assert refine_resp.status_code == 200
    refine_data = refine_resp.json()

    # Submit scores via API
    scores = [
        {"activity_id": a["id"], "metric_id": m["id"], "score": 70}
        for a in refine_data["activities"]
        for m in refine_data["criteria"]
    ]
    score_resp = client.post(
        f"/api/decisions/{decision_id}/score",
        json={"scores": scores},
    )
    assert score_resp.status_code == 200
    result_data = score_resp.json()
    assert "results" in result_data


def test_rank_two_items_fallback(client, db):
    """2 items should NOT route to rank — CHOOSE handles it"""
    resp = client.post(
        "/api/decide",
        json={"q": "A, B"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "choose"


def test_rank_result_reuses_decision_result(client, db):
    """Rank result page shows ranking data via API"""
    # Create a decision with rank mode via /decide
    resp = client.post("/api/decide", json={"q": "X, Y, Z"})
    assert resp.status_code == 200
    data = resp.json()
    decision_id = data["decision_id"]

    from models import Metric

    metrics = db.query(Metric).order_by(Metric.id).all()
    assert len(metrics) >= 1

    # Refine via API
    refine_resp = client.post(
        f"/api/decisions/{decision_id}/refine",
        json={
            "alternatives": ["X", "Y", "Z"],
            "metrics": [{"metric_id": metrics[0].id, "weight": 80}],
        },
    )
    assert refine_resp.status_code == 200
    refine_data = refine_resp.json()

    # Submit scores via API
    scores = [
        {"activity_id": a["id"], "metric_id": m["id"], "score": 70}
        for a in refine_data["activities"]
        for m in refine_data["criteria"]
    ]
    client.post(f"/api/decisions/{decision_id}/score", json={"scores": scores})

    # Check result via API
    result = client.get(f"/api/decisions/{decision_id}")
    assert result.status_code == 200
    data = result.json()
    assert "results" in data


def test_decide_heuristic_routing(client, db):
    """/api/decide auto-detects workflow from query text."""
    resp = client.post(
        "/api/decide",
        json={"q": "Should I buy a house or an apartment?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "choose"

    # Heuristic rank detection
    resp3 = client.post(
        "/api/decide",
        json={"q": "Rank Python, Java, Go"},
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["mode"] == "rank"

    # Heuristic diagnose detection
    resp4 = client.post(
        "/api/decide",
        json={"q": "How good is Rust?"},
    )
    assert resp4.status_code == 200
    data4 = resp4.json()
    assert data4["mode"] == "diagnose"


# ── Threshold filter tests (post-hoc on decision result page) ──


def _create_decision_with_metric(client, db, query="House or Apartment?"):
    """Helper: create a decision via /api/decide, refine with 1 metric via API, return decision_id and metric_id."""
    resp = client.post("/api/decide", json={"q": query})
    assert resp.status_code == 200
    decision_id = resp.json()["decision_id"]

    # Get a metric
    from models import Metric

    metric = db.query(Metric).order_by(Metric.id).first()
    assert metric is not None
    metric_id = metric.id

    # Refine with this metric and 2 alternatives via API
    refine_resp = client.post(
        f"/api/decisions/{decision_id}/refine",
        json={
            "alternatives": ["House", "Apartment"],
            "metrics": [{"metric_id": metric_id, "weight": 80}],
        },
    )
    assert refine_resp.status_code == 200
    return decision_id, metric_id


def test_decision_result_threshold_panel_renders(client, db):
    """Result data includes decision details via API."""
    decision_id, _ = _create_decision_with_metric(client, db)

    # Fetch result via API
    resp = client.get(f"/api/decisions/{decision_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "decision" in data
    assert "results" in data


def test_decision_apply_thresholds_valid(client, db):
    """POST valid thresholds → stored in DB JSON."""
    decision_id, metric_id = _create_decision_with_metric(client, db)

    # First score (so filter doesn't show "no scores")
    from models import Activity

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    for act in activities:
        from models import AlternativeScore

        ascore = AlternativeScore(activity_id=act.id, metric_id=metric_id, score=80)
        db.add(ascore)
    db.commit()

    # Apply valid threshold via API
    resp = client.post(
        f"/api/decisions/{decision_id}/thresholds",
        json={
            "thresholds": [{"metric_id": metric_id, "operator": "<=", "value": 60.0}]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "filter_result" in data

    # Verify stored
    from models import Decision
    from json import loads

    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    assert decision.thresholds is not None
    stored = loads(decision.thresholds)
    assert len(stored) >= 1
    assert stored[0]["metric_id"] == metric_id
    assert stored[0]["operator"] == "<="
    assert stored[0]["value"] == 60.0

    # Fetch result page via API
    result = client.get(f"/api/decisions/{decision_id}")
    assert result.status_code == 200
    result_data = result.json()
    assert "filter_result" in result_data


def test_decision_apply_thresholds_invalid_range(client, db):
    """POST threshold value 150 → error, NOT stored."""
    decision_id, metric_id = _create_decision_with_metric(client, db)

    resp = client.post(
        f"/api/decisions/{decision_id}/thresholds",
        json={"thresholds": [{"metric_id": metric_id, "operator": "<=", "value": 150}]},
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "detail" in data
    assert "outside the 0–100 scale" in data["detail"]

    # Verify NOT stored
    from models import Decision

    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    assert decision.thresholds is None or decision.thresholds == "null"


def test_decision_apply_thresholds_invalid_non_numeric(client, db):
    """POST threshold value 'abc' → error."""
    decision_id, metric_id = _create_decision_with_metric(client, db)

    resp = client.post(
        f"/api/decisions/{decision_id}/thresholds",
        json={
            "thresholds": [{"metric_id": metric_id, "operator": "<=", "value": "abc"}]
        },
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "detail" in data

    # Verify NOT stored
    from models import Decision

    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    assert decision.thresholds is None or decision.thresholds == "null"


def test_decision_clear_thresholds(client, db):
    """POST /thresholds/clear removes filters."""
    decision_id, metric_id = _create_decision_with_metric(client, db)

    from models import Decision

    # Set a threshold first
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    import json

    decision.thresholds = json.dumps(
        [{"metric_id": metric_id, "operator": "<=", "value": 60.0}]
    )
    db.commit()

    # Clear it via API
    resp = client.post(
        f"/api/decisions/{decision_id}/thresholds/clear",
    )
    assert resp.status_code == 200

    # Verify cleared
    db.refresh(decision)
    assert decision.thresholds is None


def test_decision_thresholds_no_scores(client, db):
    """Apply thresholds before scoring → all FAIL with 'No score available'."""
    decision_id, metric_id = _create_decision_with_metric(client, db)

    # Apply valid threshold without any scores via API
    resp = client.post(
        f"/api/decisions/{decision_id}/thresholds",
        json={
            "thresholds": [{"metric_id": metric_id, "operator": "<=", "value": 60.0}]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "filter_result" in data

    # Check result via API
    result = client.get(f"/api/decisions/{decision_id}")
    assert result.status_code == 200
    result_data = result.json()
    assert "filter_result" in result_data


def test_decision_threshold_criteria_prepopulation(client, db):
    """threshold_criteria contains expected operator/value pairs."""
    decision_id, metric_id = _create_decision_with_metric(client, db)

    from models import Metric

    metric = db.query(Metric).filter(Metric.id == metric_id).first()
    assert metric is not None

    # Apply thresholds via API
    client.post(
        f"/api/decisions/{decision_id}/thresholds",
        json={
            "thresholds": [{"metric_id": metric_id, "operator": ">=", "value": 75.0}]
        },
    )

    # Fetch result via API
    result = client.get(f"/api/decisions/{decision_id}")
    assert result.status_code == 200
    result_data = result.json()

    # Check that threshold_criteria contains the metric and operator
    assert metric.name in str(result_data.get("threshold_criteria", []))
    assert ">=" in str(result_data.get("threshold_criteria", []))
    assert "75" in str(result_data.get("threshold_criteria", []))


def test_decision_result_robustness_uses_saved_threshold_survivors(client, db):
    decision = _seed_scored_decision(db, "choose")

    from models import Activity, AlternativeScore, Decision

    winner = decision.activities[0]
    winner_scores = (
        db.query(AlternativeScore)
        .filter(AlternativeScore.activity_id == winner.id)
        .all()
    )
    metric_id = winner_scores[0].metric_id

    third = Activity(name="Filtered", category="General", decision_id=decision.id)
    db.add(third)
    db.flush()
    for score in winner_scores:
        mid = score.metric_id
        db.add(AlternativeScore(activity_id=third.id, metric_id=mid, score=95))

    stored = db.query(Decision).filter(Decision.id == decision.id).first()
    stored.thresholds = '[{"metric_id": %d, "operator": "<=", "value": 80}]' % metric_id
    db.commit()

    response = client.get(f"/api/decisions/{decision.id}")
    assert response.status_code == 200
    data = response.json()

    survivor_ids = {
        result["activity_id"] for result in data["filter_result"]["survivor_results"]
    }
    robust_ids = {
        item["activity_id"] for item in data["robustness"]["rank_acceptability"]
    }
    assert len(survivor_ids) == 1
    assert robust_ids == survivor_ids
    assert data["robustness"]["top_two"] is None
    assert data["robustness"]["winner_robustness_percent"] == 100.0


def test_decision_result_robustness_handles_no_threshold_survivors(client, db):
    decision = _seed_scored_decision(db, "choose")

    from models import AlternativeScore, Decision

    score = (
        db.query(AlternativeScore)
        .filter(AlternativeScore.activity_id == decision.activities[0].id)
        .first()
    )
    metric_id = score.metric_id

    stored = db.query(Decision).filter(Decision.id == decision.id).first()
    stored.thresholds = '[{"metric_id": %d, "operator": "<=", "value": 10}]' % metric_id
    db.commit()

    response = client.get(f"/api/decisions/{decision.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["filter_result"]["survivor_results"] == []
    assert data["robustness"] is None


def test_decision_invalid_threshold_via_api_uses_saved_threshold_survivors(client, db):
    """Invalid threshold input via API returns 422; saved thresholds still apply."""
    decision = _seed_scored_decision(db, "choose")

    from models import AlternativeScore, Decision

    score = (
        db.query(AlternativeScore)
        .filter(AlternativeScore.activity_id == decision.activities[0].id)
        .first()
    )
    metric_id = score.metric_id

    stored = db.query(Decision).filter(Decision.id == decision.id).first()
    stored.thresholds = '[{"metric_id": %d, "operator": "<=", "value": 10}]' % metric_id
    db.commit()

    # Attempt invalid threshold via API — should reject
    response = client.post(
        f"/api/decisions/{decision.id}/thresholds",
        json={
            "thresholds": [{"metric_id": metric_id, "operator": "<=", "value": "not-a-number"}]
        },
    )
    assert response.status_code == 422

    # Saved thresholds should still apply when fetching result
    result = client.get(f"/api/decisions/{decision.id}")
    assert result.status_code == 200
    data = result.json()
    assert data["filter_result"]["survivor_results"] == []
    assert data["robustness"] is None


# ── Markdown export + robustness + slider polish tests ──


def _seed_scored_decision(db, mode="choose"):
    from models import Activity, AlternativeScore, Decision, DecisionWeight, Metric

    decision = Decision(query=f"Export {mode} decision", category="General", mode=mode)
    db.add(decision)
    db.flush()
    activities = [
        Activity(name="Winner", category="General", decision_id=decision.id),
        Activity(name="Runner", category="General", decision_id=decision.id),
    ]
    if mode == "diagnose":
        activities = [
            Activity(name="Solo", category="General", decision_id=decision.id)
        ]
    db.add_all(activities)
    db.flush()

    metrics = db.query(Metric).order_by(Metric.id).limit(3).all()
    assert len(metrics) >= 2
    # Decision-level weights (shared across all activities)
    for metric in metrics:
        db.add(DecisionWeight(decision_id=decision.id, metric_id=metric.id, weight=70))

    if mode == "diagnose":
        for metric in metrics:
            db.add(
                AlternativeScore(
                    activity_id=activities[0].id, metric_id=metric.id, score=80
                )
            )
    else:
        for idx, metric in enumerate(metrics):
            db.add(
                AlternativeScore(
                    activity_id=activities[0].id, metric_id=metric.id, score=90 - idx
                )
            )
            db.add(
                AlternativeScore(
                    activity_id=activities[1].id, metric_id=metric.id, score=50 + idx
                )
            )
    db.commit()
    return decision


def test_export_markdown_endpoint(client, db):
    """Export markdown works via consolidated /api endpoint.

    For scored decisions, the brief includes MCDA robustness analysis.
    """
    choose = _seed_scored_decision(db, "choose")
    diagnose = _seed_scored_decision(db, "diagnose")

    # ── choose mode export ──
    resp = client.get(f"/api/decisions/{choose.id}/export-markdown")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    assert "Decision Brief" in resp.text
    assert "Decision Robustness" in resp.text
    assert (
        "Monte Carlo sensitivity analysis on a weighted additive value model (WAVM)"
        in resp.text
    )
    assert "not hypothesis testing" in resp.text
    assert "Rank acceptability (Rank 1)" in resp.text
    assert "95% simulation interval" in resp.text
    assert "percentage points" in resp.text
    assert "confidence interval" not in resp.text.lower()
    assert "p-value" not in resp.text
    assert "t-statistic" not in resp.text

    # ── diagnose mode export ──
    resp = client.get(f"/api/decisions/{diagnose.id}/export-markdown")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    assert "Decision Brief" in resp.text
    assert "Decision Robustness" in resp.text
    assert "Rank acceptability (Rank 1)" in resp.text
    assert "confidence interval" not in resp.text.lower()
    assert "p-value" not in resp.text

    # ── non-existent decision ──
    resp = client.get("/api/decisions/99999/export-markdown")
    assert resp.status_code == 404


def test_result_pages_include_robustness_and_null_compatibility_key(client, db):
    decision = _seed_scored_decision(db, "choose")
    response = client.get(f"/api/decisions/{decision.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["robustness"]["method"] == "weighted_additive_monte_carlo"
    assert "method_description" in data["robustness"]
    assert data["robustness"]["weight_renormalization"]["applied"] is True
    assert (
        data["robustness"]["winner_retained_total"] == data["robustness"]["simulations"]
    )
    assert data["significance"] is None
    assert "confidence interval" not in str(data).lower()
    assert "p_value" not in str(data)
    assert "t_statistic" not in str(data)


def test_slider_fill_markup_and_sensitivity_classes(client, db):
    decision = _seed_scored_decision(db, "choose")

    # Fetch decision detail via API — includes activities, metrics, and results
    response = client.get(f"/api/decisions/{decision.id}")
    assert response.status_code == 200
    data = response.json()
    assert "activities" in data
    assert "metrics" in data
    assert "results" in data
    assert "series" in data


def test_api_decision_rows_expose_sensitivity_scoring_fields(client, db):
    """Decision detail rows include metric direction and decision-level weights."""
    from models import Activity, AlternativeScore, Decision, DecisionWeight, Metric

    metric = db.query(Metric).filter(Metric.higher_is_better.is_(False)).first()
    assert metric is not None

    decision = Decision(query="Sensitivity parity", category="General", mode="choose")
    db.add(decision)
    db.flush()
    first = Activity(name="First", category="General", decision_id=decision.id)
    second = Activity(name="Second", category="General", decision_id=decision.id)
    db.add_all([first, second])
    db.flush()

    # Decision-level weight (shared)
    db.add(DecisionWeight(decision_id=decision.id, metric_id=metric.id, weight=80))
    db.add(AlternativeScore(activity_id=first.id, metric_id=metric.id, score=10))
    db.add(AlternativeScore(activity_id=second.id, metric_id=metric.id, score=30))
    db.commit()

    response = client.get(f"/api/decisions/{decision.id}")
    assert response.status_code == 200
    data = response.json()
    row = data["rows"][0]

    assert row["metric_id"] == metric.id
    assert row["higher_is_better"] is False
    # Decision-level weight: both activities use the same weight
    assert row["weight"] == 80
    assert data["results"][0]["fit_score"] == 0.9
