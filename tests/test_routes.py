"""Tests for FastAPI routes using TestClient.

Uses real main.app with overridden get_db dependency.
Per-function temporary SQLite database file.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from main import app
from models import AlternativeScore, Decision, Metric
from services.decision_limits import MAX_DECISION_ALTERNATIVES, MAX_DECISION_METRICS
from services.ontology import (
    FIT_SCORE_EXPORT_EXPLANATION,
    RESERVED_LEGACY_METRIC_NAMES,
    UNIVERSAL_METRICS,
)

# Per-test state
_test_db_path = None
_test_engine = None
_test_session = None

FORBIDDEN_DIRECTION_FIELDS = {
    "direction",
    "higher_is_better",
    "lower_is_better",
    "score_type",
}


def _assert_no_forbidden_direction_fields(value):
    if isinstance(value, dict):
        assert FORBIDDEN_DIRECTION_FIELDS.isdisjoint(value)
        for child in value.values():
            _assert_no_forbidden_direction_fields(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_forbidden_direction_fields(child)


def _expected_metric_metadata(name: str) -> dict:
    metric = next(m for m in UNIVERSAL_METRICS if m["name"] == name)
    return {
        "stable_id": metric["stable_id"],
        "name": metric["name"],
        "category": metric["category"],
        "category_id": metric["category_id"],
        "description": metric["description"],
        "question": metric["question"],
        "anchors": {
            "low": metric["low_anchor"],
            "mid": metric["mid_anchor"],
            "high": metric["high_anchor"],
        },
    }


def _assert_exact_metric_metadata(payload: dict, name: str) -> None:
    expected = _expected_metric_metadata(name)
    for key, expected_value in expected.items():
        assert payload[key] == expected_value


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

    @event.listens_for(_test_engine, "connect")
    def _set_sqlite_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=_test_engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)
    _test_session = TestSession()

    from main import reconcile_seed_metrics

    reconcile_seed_metrics(_test_session)

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
    assert "decision_id" in data
    assert "mode" not in data
    assert "category" not in data
    # Verify alternatives were extracted via the decision detail endpoint
    detail = client.get(f"/api/decisions/{data['decision_id']}")
    names = [a["name"].lower() for a in detail.json()["activities"]]
    assert "house" in names or "apartment" in names


def test_decide_flow_with_do_verb(client, db):
    """'should I do X or Y' correctly extracts Aikido and Football."""
    response = client.post("/api/decide", json={"q": "should I do aikido or football"})
    assert response.status_code == 200
    data = response.json()
    assert "decision_id" in data
    assert "mode" not in data
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
    assert "mode" not in data


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
    assert "mode" not in api_data["decision"]
    assert "category" not in api_data["decision"]
    assert "results" in api_data
    assert "series" in api_data
    assert "metric_names" in api_data


def test_api_score_rejects_foreign_activity_before_deleting_existing_scores(client, db):
    from models import AlternativeScore

    decision_id, metric_id = _create_decision_with_metric(client, db)
    other_decision_id, _ = _create_decision_with_metric(client, db, query="Train or Bus?")

    activity_id = client.get(f"/api/decisions/{decision_id}").json()["activities"][0]["id"]
    other_activity_id = client.get(f"/api/decisions/{other_decision_id}").json()[
        "activities"
    ][0]["id"]

    valid = client.post(
        f"/api/decisions/{decision_id}/score",
        json={"scores": [{"activity_id": activity_id, "metric_id": metric_id, "score": 70}]},
    )
    assert valid.status_code == 200
    assert db.query(AlternativeScore).count() == 1

    invalid = client.post(
        f"/api/decisions/{decision_id}/score",
        json={
            "scores": [
                {"activity_id": other_activity_id, "metric_id": metric_id, "score": 80}
            ]
        },
    )
    assert invalid.status_code == 422
    assert db.query(AlternativeScore).count() == 1


def test_api_score_rejects_unselected_metric(client, db):
    decision_id, metric_id = _create_decision_with_metric(client, db)
    activity_id = client.get(f"/api/decisions/{decision_id}").json()["activities"][0]["id"]
    unselected_metric = db.query(Metric).filter(Metric.id != metric_id).first()
    assert unselected_metric is not None

    response = client.post(
        f"/api/decisions/{decision_id}/score",
        json={
            "scores": [
                {
                    "activity_id": activity_id,
                    "metric_id": unselected_metric.id,
                    "score": 70,
                }
            ]
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "score_payload",
    [
        {},
        {"score": "70"},
        {"score": -1},
        {"score": 101},
    ],
)
def test_api_score_rejects_malformed_score_values(client, db, score_payload):
    decision_id, metric_id = _create_decision_with_metric(client, db)
    activity_id = client.get(f"/api/decisions/{decision_id}").json()["activities"][0]["id"]
    payload = {"activity_id": activity_id, "metric_id": metric_id, **score_payload}

    response = client.post(
        f"/api/decisions/{decision_id}/score",
        json={"scores": [payload]},
    )

    assert response.status_code == 422


def test_api_score_rejects_non_finite_score(client, db):
    decision_id, metric_id = _create_decision_with_metric(client, db)
    activity_id = client.get(f"/api/decisions/{decision_id}").json()["activities"][0]["id"]

    response = client.post(
        f"/api/decisions/{decision_id}/score",
        content=(
            '{"scores":[{"activity_id":%d,"metric_id":%d,"score":NaN}]}'
            % (activity_id, metric_id)
        ),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422


def test_api_score_rejects_duplicate_score_entries_before_deleting_existing_scores(
    client, db
):
    from models import AlternativeScore

    decision_id, metric_id = _create_decision_with_metric(client, db)
    activity_id = client.get(f"/api/decisions/{decision_id}").json()["activities"][0]["id"]

    valid = client.post(
        f"/api/decisions/{decision_id}/score",
        json={"scores": [{"activity_id": activity_id, "metric_id": metric_id, "score": 70}]},
    )
    assert valid.status_code == 200
    assert db.query(AlternativeScore).count() == 1

    duplicate = client.post(
        f"/api/decisions/{decision_id}/score",
        json={
            "scores": [
                {"activity_id": activity_id, "metric_id": metric_id, "score": 80},
                {"activity_id": activity_id, "metric_id": metric_id, "score": 90},
            ]
        },
    )

    assert duplicate.status_code == 422
    assert db.query(AlternativeScore).count() == 1


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
        "Resource Fit",
        "Objective Fit",
        "Time Fit",
        "Assurance Fit",
        "People Fit",
        "Practical Fit",
    ]:
        assert dim_name in grouped
    forbidden = {"direction", "higher_is_better", "lower_is_better", "score_type"}
    all_metrics = [metric for metrics in grouped.values() for metric in metrics]
    assert all(forbidden.isdisjoint(metric) for metric in all_metrics)
    assert all(metric["anchors"] for metric in all_metrics)
    assert {metric["name"] for metric in all_metrics}.isdisjoint(
        {"Cost", "Performance", "Time Required", "Risk", "Safety", "Enjoyment", "Satisfaction", "Convenience", "Accessibility"}
    )
    # No stale duplicate names in clean startup
    assert not any("(custom)" in m["name"] for m in all_metrics)


def test_metrics_api_exposes_exact_fit_metadata_without_direction_fields(client, db):
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    _assert_no_forbidden_direction_fields(data)

    all_metrics = [
        metric
        for metrics in data["grouped_metrics"].values()
        for metric in metrics
    ]
    by_name = {metric["name"]: metric for metric in all_metrics}
    _assert_exact_metric_metadata(by_name["Affordability"], "Affordability")
    _assert_exact_metric_metadata(by_name["Reliability"], "Reliability")


def test_list_metrics_filters_stale_custom_duplicates(client, db):
    """After a Cost + pre-existing Affordability conflict, only one
    'Affordability' appears — the (custom) duplicate is filtered out."""
    from main import reconcile_seed_metrics

    # Simulate the conflict scenario
    db.query(Metric).delete()
    db.commit()
    old_cost = Metric(name="Cost", category="Financial", description="old cost")
    conflict = Metric(name="Affordability", category="Custom", description="user-made")
    db.add_all([old_cost, conflict])
    db.commit()

    reconcile_seed_metrics(db)

    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    all_metrics = data["grouped_metrics"]
    names = [m["name"] for group in all_metrics.values() for m in group]

    # Canonical Affordability appears exactly once
    assert names.count("Affordability") == 1
    # The stale duplicate is suppressed
    assert "Affordability (custom)" not in names
    # All 12 built-in names appear exactly once each
    from services.ontology import UNIVERSAL_METRICS
    builtin_names = {m["name"] for m in UNIVERSAL_METRICS}
    for bname in builtin_names:
        assert names.count(bname) == 1, f"{bname} count is {names.count(bname)}"


def test_list_metrics_shows_genuine_custom_metrics(client, db):
    """A genuinely custom metric (no name conflict with built-ins)
    still appears in the listing."""
    resp = client.post("/api/metrics", json={
        "name": "My Custom Metric",
        "category": "General",
        "description": "A user-created metric",
    })
    assert resp.status_code == 201

    resp2 = client.get("/api/metrics")
    data = resp2.json()
    names = [m["name"] for group in data["grouped_metrics"].values() for m in group]
    assert "My Custom Metric" in names
    assert names.count("My Custom Metric") == 1


def test_list_metrics_shows_custom_with_suffix_not_matching_builtin(client, db):
    """A metric named e.g. 'Special (custom)' whose base 'Special' is
    not a built-in metric is still shown (not a stale duplicate)."""
    resp = client.post("/api/metrics", json={
        "name": "Special (custom)",
        "category": "General",
        "description": "Custom metric with (custom) in name",
    })
    assert resp.status_code == 201

    resp2 = client.get("/api/metrics")
    data = resp2.json()
    names = [m["name"] for group in data["grouped_metrics"].values() for m in group]
    assert "Special (custom)" in names


def test_decision_detail_and_refine_expose_exact_fit_contract(client, db):
    metric = db.query(Metric).filter(Metric.name == "Affordability").one()
    response = client.post("/api/decide", json={"q": "Tea or Coffee?"})
    assert response.status_code == 200
    decision_id = response.json()["decision_id"]

    refine_response = client.post(
        f"/api/decisions/{decision_id}/refine",
        json={
            "alternatives": ["Tea", "Coffee"],
            "metrics": [{"metric_id": metric.id, "weight": 90}],
        },
    )
    assert refine_response.status_code == 200
    refine_data = refine_response.json()
    _assert_no_forbidden_direction_fields(refine_data)
    _assert_exact_metric_metadata(refine_data["criteria"][0], "Affordability")

    detail_response = client.get(f"/api/decisions/{decision_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    _assert_no_forbidden_direction_fields(detail)
    _assert_exact_metric_metadata(detail["metrics"][0], "Affordability")
    assert detail["rows"][0]["metric_question"] == _expected_metric_metadata(
        "Affordability"
    )["question"]
    assert detail["rows"][0]["metric_anchors"] == _expected_metric_metadata(
        "Affordability"
    )["anchors"]


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



def test_decide_routes_to_diagnose(client, db):
    """Diagnose-style query via /api/decide creates a decision."""
    resp = client.post(
        "/api/decide",
        json={"q": "How good is a Tesla for commuting?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "decision_id" in data
    assert "mode" not in data


def test_decide_with_choose_query_still_works(client, db):
    """CHOOSE query via /api/decide → returns JSON with decision_id"""
    resp = client.post(
        "/api/decide",
        json={"q": "Should I buy a house or an apartment?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "decision_id" in data
    assert "mode" not in data


def test_decide_with_no_match_fallback(client, db):
    """Query matching neither CHOOSE nor DIAGNOSE → fallback to CHOOSE"""
    resp = client.post(
        "/api/decide",
        json={"q": "Hello world"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "decision_id" in data


# ── Ranking flow tests ──


def test_rank_via_decide(client, db):
    """List query via /api/decide creates a decision."""
    resp = client.post(
        "/api/decide",
        json={"q": "Rank Python, Java, Go"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "decision_id" in data
    assert "mode" not in data


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
    """2 items create a comparison decision."""
    resp = client.post(
        "/api/decide",
        json={"q": "A, B"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "decision_id" in data
    assert "mode" not in data


def test_rank_result_reuses_decision_result(client, db):
    """Rank result page shows ranking data via API"""
    # Create a ranking decision via /decide
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
    assert "mode" not in data

    # Heuristic rank detection
    resp3 = client.post(
        "/api/decide",
        json={"q": "Rank Python, Java, Go"},
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert "mode" not in data3

    # Heuristic diagnose detection
    resp4 = client.post(
        "/api/decide",
        json={"q": "How good is Rust?"},
    )
    assert resp4.status_code == 200
    data4 = resp4.json()
    assert "mode" not in data4


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
    assert data["threshold_criteria"]
    assert all(tc["operator"] == ">=" for tc in data["threshold_criteria"])


def test_seeded_fit_metrics_have_current_shape(db):
    metrics = {
        m.name: m
        for m in db.query(Metric)
        .filter(Metric.name.in_(["Affordability", "Reliability", "Timeliness"]))
        .all()
    }
    assert metrics["Affordability"].description == "How acceptable is the cost, effort, or resource burden?"
    assert metrics["Reliability"].description == "How likely is this option to work consistently under uncertainty?"
    assert metrics["Timeliness"].description == "How well does the speed, delay, schedule, or time requirement fit the decision?"


def test_seed_reconciliation_preserves_old_metric_ids_and_scores(db):
    from main import reconcile_seed_metrics
    from models import Activity, AlternativeScore, Decision, DecisionWeight

    db.query(Metric).delete()
    db.commit()
    old_cost = Metric(name="Cost", category="Financial", description="old")
    db.add(old_cost)
    db.flush()
    decision = Decision(query="Legacy", category="General")
    db.add(decision)
    db.flush()
    activity = Activity(name="Option", category="General", decision_id=decision.id)
    db.add(activity)
    db.flush()
    db.add(DecisionWeight(decision_id=decision.id, metric_id=old_cost.id, weight=90))
    db.add(AlternativeScore(activity_id=activity.id, metric_id=old_cost.id, score=25))
    old_id = old_cost.id
    db.commit()

    reconcile_seed_metrics(db)

    renamed = db.query(Metric).filter(Metric.id == old_id).one()
    assert renamed.name == "Affordability"
    assert renamed.category == "Resource Fit"
    assert db.query(AlternativeScore).filter_by(metric_id=old_id).one().score == 25


def test_seed_reconciliation_renames_new_name_conflict_deterministically(db):
    from main import reconcile_seed_metrics

    db.query(Metric).delete()
    db.commit()
    old_cost = Metric(name="Cost", category="Financial", description="old")
    conflict = Metric(name="Affordability", category="Custom", description="custom")
    db.add_all([old_cost, conflict])
    db.flush()
    old_id = old_cost.id
    conflict_id = conflict.id
    db.commit()

    reconcile_seed_metrics(db)

    assert db.query(Metric).filter(Metric.id == old_id).one().name == "Affordability"
    assert db.query(Metric).filter(Metric.id == conflict_id).one().name == "Affordability (custom)"


def test_seed_reconciliation_fresh_insert_creates_exact_fit_metadata(db):
    from main import reconcile_seed_metrics

    db.query(Metric).delete()
    db.commit()

    reconcile_seed_metrics(db)

    inserted = db.query(Metric).filter(Metric.name == "Affordability").one()
    assert inserted.category == "Resource Fit"
    assert inserted.description == _expected_metric_metadata("Affordability")["description"]
    assert db.query(Metric).filter(Metric.name.in_(
        [metric["name"] for metric in UNIVERSAL_METRICS]
    )).count() == len(UNIVERSAL_METRICS)


def test_seed_reconciliation_existing_new_name_upserts_exact_metadata(db):
    from main import reconcile_seed_metrics

    db.query(Metric).delete()
    db.commit()
    metric = Metric(
        name="Affordability",
        category="Custom Category",
        description="Custom description",
    )
    db.add(metric)
    db.flush()
    metric_id = metric.id
    db.commit()

    reconcile_seed_metrics(db)

    upserted = db.query(Metric).filter(Metric.id == metric_id).one()
    assert upserted.name == "Affordability"
    assert upserted.category == "Resource Fit"
    assert upserted.description == _expected_metric_metadata("Affordability")["description"]


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
            "thresholds": [{"metric_id": metric_id, "operator": ">=", "value": 60.0}]
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
    assert stored[0]["operator"] == ">="
    assert stored[0]["value"] == 60.0

    # Fetch result page via API
    result = client.get(f"/api/decisions/{decision_id}")
    assert result.status_code == 200
    result_data = result.json()
    assert "filter_result" in result_data


def test_decision_apply_thresholds_defaults_to_minimum_operator(client, db):
    decision_id, metric_id = _create_decision_with_metric(client, db)

    resp = client.post(
        f"/api/decisions/{decision_id}/thresholds",
        json={"thresholds": [{"metric_id": metric_id, "value": 60.0}]},
    )
    assert resp.status_code == 200

    from json import loads
    from models import Decision

    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    stored = loads(decision.thresholds)
    assert stored[0]["operator"] == ">="


def test_decision_apply_thresholds_invalid_range(client, db):
    """POST threshold value 150 → error, NOT stored."""
    decision_id, metric_id = _create_decision_with_metric(client, db)

    resp = client.post(
        f"/api/decisions/{decision_id}/thresholds",
        json={"thresholds": [{"metric_id": metric_id, "operator": ">=", "value": 150}]},
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
            "thresholds": [{"metric_id": metric_id, "operator": ">=", "value": "abc"}]
        },
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "detail" in data

    # Verify NOT stored
    from models import Decision

    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    assert decision.thresholds is None or decision.thresholds == "null"


@pytest.mark.parametrize(
    "threshold",
    [
        {"operator": ">=", "value": 60},
        {"metric_id": "1", "operator": ">=", "value": 60},
        {"metric_id": 1, "operator": "=", "value": 60},
        {"metric_id": 1, "operator": [], "value": 60},
        {"metric_id": 1, "operator": {}, "value": 60},
        {"metric_id": 1, "operator": ">=", "value": "nan"},
        {"metric_id": 1, "operator": ">=", "value": "inf"},
    ],
)
def test_decision_apply_thresholds_rejects_malformed_thresholds(
    client, db, threshold
):
    decision_id, metric_id = _create_decision_with_metric(client, db)
    threshold = dict(threshold)
    if threshold.get("metric_id") == 1:
        threshold["metric_id"] = metric_id

    resp = client.post(
        f"/api/decisions/{decision_id}/thresholds",
        json={"thresholds": [threshold]},
    )

    assert resp.status_code == 422


def test_decision_apply_thresholds_rejects_unselected_metric(client, db):
    decision_id, metric_id = _create_decision_with_metric(client, db)
    unselected_metric = db.query(Metric).filter(Metric.id != metric_id).first()
    assert unselected_metric is not None

    resp = client.post(
        f"/api/decisions/{decision_id}/thresholds",
        json={
            "thresholds": [
                {"metric_id": unselected_metric.id, "operator": ">=", "value": 60}
            ]
        },
    )

    assert resp.status_code == 422


def test_decision_clear_thresholds(client, db):
    """POST /thresholds/clear removes filters."""
    decision_id, metric_id = _create_decision_with_metric(client, db)

    from models import Decision

    # Set a threshold first
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    import json

    decision.thresholds = json.dumps(
        [{"metric_id": metric_id, "operator": ">=", "value": 60.0}]
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
            "thresholds": [{"metric_id": metric_id, "operator": ">=", "value": 60.0}]
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
        db.add(AlternativeScore(activity_id=third.id, metric_id=mid, score=10))

    stored = db.query(Decision).filter(Decision.id == decision.id).first()
    stored.thresholds = '[{"metric_id": %d, "operator": ">=", "value": 80}]' % metric_id
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
    stored.thresholds = '[{"metric_id": %d, "operator": ">=", "value": 95}]' % metric_id
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
    stored.thresholds = '[{"metric_id": %d, "operator": ">=", "value": 95}]' % metric_id
    db.commit()

    # Attempt invalid threshold via API — should reject
    response = client.post(
        f"/api/decisions/{decision.id}/thresholds",
        json={
            "thresholds": [{"metric_id": metric_id, "operator": ">=", "value": "not-a-number"}]
        },
    )
    assert response.status_code == 422

    # Saved thresholds should still apply when fetching result
    result = client.get(f"/api/decisions/{decision.id}")
    assert result.status_code == 200
    data = result.json()
    assert data["filter_result"]["survivor_results"] == []
    assert data["robustness"] is None


@pytest.mark.parametrize(
    "saved_thresholds",
    [
        '["bad"]',
        "[{}]",
        '[{"metric_id": SELECTED_METRIC, "operator": ">=", "value": "abc"}]',
        '[{"metric_id": SELECTED_METRIC, "operator": "=", "value": 60}]',
        '[{"metric_id": SELECTED_METRIC, "operator": [], "value": 60}]',
        '[{"metric_id": SELECTED_METRIC, "operator": {}, "value": 60}]',
        '[{"metric_id": UNSELECTED_METRIC, "operator": ">=", "value": 60}]',
        '[{"metric_id": SELECTED_METRIC, "operator": ">=", "value": NaN}]',
        '[{"metric_id": SELECTED_METRIC, "operator": ">=", "value": Infinity}]',
    ],
)
def test_decision_result_skips_malformed_persisted_thresholds(
    client, db, saved_thresholds
):
    decision = _seed_scored_decision(db, "choose")

    from models import AlternativeScore, Decision, DecisionWeight, Metric

    selected_metric_id = (
        db.query(AlternativeScore)
        .filter(AlternativeScore.activity_id == decision.activities[0].id)
        .first()
        .metric_id
    )
    selected_metric_ids = {
        weight.metric_id
        for weight in db.query(DecisionWeight)
        .filter(DecisionWeight.decision_id == decision.id)
        .all()
    }
    unselected_metric = db.query(Metric).filter(~Metric.id.in_(selected_metric_ids)).first()
    assert unselected_metric is not None

    saved_thresholds = saved_thresholds.replace(
        "UNSELECTED_METRIC", str(unselected_metric.id)
    )
    saved_thresholds = saved_thresholds.replace(
        "SELECTED_METRIC", str(selected_metric_id)
    )

    stored = db.query(Decision).filter(Decision.id == decision.id).first()
    stored.thresholds = saved_thresholds
    db.commit()

    response = client.get(f"/api/decisions/{decision.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["filter_result"] is None
    assert data["thresholds"] == []


@pytest.mark.parametrize(
    "saved_thresholds",
    [
        '["bad"]',
        "[{}]",
        '[{"metric_id": SELECTED_METRIC, "operator": ">=", "value": "abc"}]',
        '[{"metric_id": SELECTED_METRIC, "operator": "=", "value": 60}]',
        '[{"metric_id": SELECTED_METRIC, "operator": [], "value": 60}]',
        '[{"metric_id": SELECTED_METRIC, "operator": {}, "value": 60}]',
        '[{"metric_id": SELECTED_METRIC, "operator": ">=", "value": 101}]',
        '[{"operator": ">=", "value": 60}]',
        '[{"metric_id": SELECTED_METRIC, "operator": ">=", "value": NaN}]',
        '[{"metric_id": SELECTED_METRIC, "operator": ">=", "value": Infinity}]',
    ],
)
def test_export_markdown_skips_malformed_persisted_thresholds(
    client, db, saved_thresholds
):
    decision = _seed_scored_decision(db, "choose")

    from models import AlternativeScore, Decision

    selected_metric_id = (
        db.query(AlternativeScore)
        .filter(AlternativeScore.activity_id == decision.activities[0].id)
        .first()
        .metric_id
    )
    saved_thresholds = saved_thresholds.replace(
        "SELECTED_METRIC", str(selected_metric_id)
    )

    stored = db.query(Decision).filter(Decision.id == decision.id).first()
    stored.thresholds = saved_thresholds
    db.commit()

    response = client.get(f"/api/decisions/{decision.id}/export-markdown")

    assert response.status_code == 200
    assert "Decision Brief" in response.text
    assert "Threshold Filters" not in response.text


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


def test_delete_decision_removes_owned_rows(client, db):
    from models import Activity, AlternativeScore, DecisionWeight

    decision = _seed_scored_decision(db, "choose")
    decision_id = decision.id
    activity_ids = [activity.id for activity in decision.activities]

    assert db.query(Decision).filter(Decision.id == decision_id).first() is not None
    assert db.query(Activity).filter(Activity.decision_id == decision_id).count() == 2
    assert (
        db.query(DecisionWeight)
        .filter(DecisionWeight.decision_id == decision_id)
        .count()
        == 3
    )
    assert (
        db.query(AlternativeScore)
        .filter(AlternativeScore.activity_id.in_(activity_ids))
        .count()
        == 6
    )

    response = client.post(f"/api/decisions/{decision_id}/delete")

    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}
    assert db.query(Decision).filter(Decision.id == decision_id).first() is None
    assert db.query(Activity).filter(Activity.decision_id == decision_id).count() == 0
    assert (
        db.query(DecisionWeight)
        .filter(DecisionWeight.decision_id == decision_id)
        .count()
        == 0
    )
    assert (
        db.query(AlternativeScore)
        .filter(AlternativeScore.activity_id.in_(activity_ids))
        .count()
        == 0
    )


def test_export_markdown_endpoint(client, db):
    """Export markdown works via consolidated /api endpoint.

    For scored decisions, the brief includes MCDA robustness analysis.
    """
    choose = _seed_scored_decision(db, "choose")
    diagnose = _seed_scored_decision(db, "diagnose")

    # ── comparison export ──
    resp = client.get(f"/api/decisions/{choose.id}/export-markdown")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    assert "Decision Brief" in resp.text
    assert FIT_SCORE_EXPORT_EXPLANATION in resp.text
    assert "- Mode:" not in resp.text
    assert "- Category:" not in resp.text
    for forbidden in FORBIDDEN_DIRECTION_FIELDS:
        assert forbidden not in resp.text
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

    # ── diagnosis export ──
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


def test_result_pages_include_robustness(client, db):
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


# ── KO (Knock-Out) criteria API tests ──


class TestKoApi:
    """Integration tests for KO criteria via the API."""

    def test_refine_with_ko(self, client, db):
        """Valid KO stored via refine, GET includes ko_criteria and ko_result."""
        # Create decision
        resp = client.post("/api/decide", json={"q": "A or B?"})
        assert resp.status_code == 200
        decision_id = resp.json()["decision_id"]

        from models import Metric
        metric = db.query(Metric).order_by(Metric.id).first()
        assert metric is not None

        # Refine with KO criteria
        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["A", "B"],
                "metrics": [{"metric_id": metric.id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": metric.id, "ko_operator": ">=", "ko_value": 50}
                ],
            },
        )
        assert refine_resp.status_code == 200
        refine_data = refine_resp.json()
        assert "ko_criteria" in refine_data
        assert len(refine_data["ko_criteria"]) == 1
        assert refine_data["ko_criteria"][0]["metric_id"] == metric.id
        assert refine_data["ko_criteria"][0]["ko_operator"] == ">="
        assert refine_data["ko_criteria"][0]["ko_value"] == 50

        # GET includes ko_criteria and ko_result
        detail_resp = client.get(f"/api/decisions/{decision_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert "ko_criteria" in detail
        assert len(detail["ko_criteria"]) == 1
        assert "ko_result" in detail

    def test_refine_ko_rejects_partial(self, client, db):
        """operator without value -> 422."""
        resp = client.post("/api/decide", json={"q": "X or Y?"})
        decision_id = resp.json()["decision_id"]
        from models import Metric
        metric = db.query(Metric).order_by(Metric.id).first()

        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["X", "Y"],
                "metrics": [{"metric_id": metric.id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": metric.id, "ko_operator": ">="}
                ],
            },
        )
        assert refine_resp.status_code == 422

    def test_refine_ko_rejects_bad_operator(self, client, db):
        """Invalid operator -> 422."""
        resp = client.post("/api/decide", json={"q": "X or Y?"})
        decision_id = resp.json()["decision_id"]
        from models import Metric
        metric = db.query(Metric).order_by(Metric.id).first()

        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["X", "Y"],
                "metrics": [{"metric_id": metric.id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": metric.id, "ko_operator": "==", "ko_value": 50}
                ],
            },
        )
        assert refine_resp.status_code == 422

    @pytest.mark.parametrize("bad_op", [[], {}])
    def test_refine_ko_rejects_non_string_operator(self, client, db, bad_op):
        """List/dict operator -> 422 (security)."""
        resp = client.post("/api/decide", json={"q": "X or Y?"})
        decision_id = resp.json()["decision_id"]
        from models import Metric
        metric = db.query(Metric).order_by(Metric.id).first()

        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["X", "Y"],
                "metrics": [{"metric_id": metric.id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": metric.id, "ko_operator": bad_op, "ko_value": 50}
                ],
            },
        )
        assert refine_resp.status_code == 422

    def test_refine_ko_rejects_bad_value(self, client, db):
        """Out-of-range value -> 422."""
        resp = client.post("/api/decide", json={"q": "X or Y?"})
        decision_id = resp.json()["decision_id"]
        from models import Metric
        metric = db.query(Metric).order_by(Metric.id).first()

        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["X", "Y"],
                "metrics": [{"metric_id": metric.id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": metric.id, "ko_operator": ">=", "ko_value": 150}
                ],
            },
        )
        assert refine_resp.status_code == 422

    def test_refine_ko_rejects_unselected_metric(self, client, db):
        """Metric not in decision -> 422."""
        resp = client.post("/api/decide", json={"q": "X or Y?"})
        decision_id = resp.json()["decision_id"]
        from models import Metric
        # Get a metric that won't be in the refine
        metrics = db.query(Metric).order_by(Metric.id).all()
        assert len(metrics) >= 2

        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["X", "Y"],
                "metrics": [{"metric_id": metrics[0].id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": metrics[1].id, "ko_operator": ">=", "ko_value": 50}
                ],
            },
        )
        assert refine_resp.status_code == 422

    def test_ko_blocks_in_results(self, client, db):
        """KO'd alt excluded from results/series/robustness."""
        from models import Metric
        metrics = db.query(Metric).order_by(Metric.id).all()
        assert len(metrics) >= 1
        m = metrics[0]

        # Create decision via /decide
        resp = client.post("/api/decide", json={"q": "Test decision"})
        decision_id = resp.json()["decision_id"]

        # Refine with 2 alternatives and KO criterion
        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["Good", "Bad"],
                "metrics": [{"metric_id": m.id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": m.id, "ko_operator": ">=", "ko_value": 60}
                ],
            },
        )
        assert refine_resp.status_code == 200
        acts = refine_resp.json()["activities"]
        good_id = next(a["id"] for a in acts if a["name"] == "Good")
        bad_id = next(a["id"] for a in acts if a["name"] == "Bad")

        # Score: Good passes (80), Bad fails (30)
        score_resp = client.post(
            f"/api/decisions/{decision_id}/score",
            json={
                "scores": [
                    {"activity_id": good_id, "metric_id": m.id, "score": 80},
                    {"activity_id": bad_id, "metric_id": m.id, "score": 30},
                ]
            },
        )
        assert score_resp.status_code == 200

        # GET detail — KO'd alt should be excluded from results
        detail = client.get(f"/api/decisions/{decision_id}").json()
        assert len(detail["results"]) == 1
        assert detail["results"][0]["activity_name"] == "Good"
        assert len(detail["series"]) == 1
        assert detail["series"][0]["name"] == "Good"
        assert detail["ko_result"] is not None
        assert detail["ko_result"]["all_passed"] is False
        knocked = [r for r in detail["ko_result"]["results"] if r["status"] == "knocked_out"]
        assert len(knocked) == 1
        assert knocked[0]["activity_name"] == "Bad"

    def test_ko_all_knocked_out_empty_results(self, client, db):
        """All KO'd -> results=[], robustness=None."""
        from models import Metric
        m = db.query(Metric).order_by(Metric.id).first()

        resp = client.post("/api/decide", json={"q": "Test"})
        decision_id = resp.json()["decision_id"]

        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["Fail1", "Fail2"],
                "metrics": [{"metric_id": m.id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": m.id, "ko_operator": ">=", "ko_value": 60}
                ],
            },
        )
        assert refine_resp.status_code == 200
        acts = refine_resp.json()["activities"]
        fail1_id = acts[0]["id"]
        fail2_id = acts[1]["id"]

        score_resp = client.post(
            f"/api/decisions/{decision_id}/score",
            json={
                "scores": [
                    {"activity_id": fail1_id, "metric_id": m.id, "score": 30},
                    {"activity_id": fail2_id, "metric_id": m.id, "score": 20},
                ]
            },
        )
        assert score_resp.status_code == 200

        detail = client.get(f"/api/decisions/{decision_id}").json()
        assert detail["results"] == []
        assert detail["series"] == []
        assert detail["robustness"] is None

    def test_ko_with_scores(self, client, db):
        """Scored alternatives evaluated correctly."""
        from models import Metric
        metrics = db.query(Metric).order_by(Metric.id).limit(2).all()
        assert len(metrics) >= 2
        m1, m2 = metrics[0], metrics[1]

        resp = client.post("/api/decide", json={"q": "Test"})
        decision_id = resp.json()["decision_id"]

        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["High", "Low"],
                "metrics": [
                    {"metric_id": m1.id, "weight": 50},
                    {"metric_id": m2.id, "weight": 50},
                ],
                "ko_criteria": [
                    {"metric_id": m1.id, "ko_operator": ">=", "ko_value": 70},
                ],
            },
        )
        assert refine_resp.status_code == 200
        acts = refine_resp.json()["activities"]
        high_id = next(a["id"] for a in acts if a["name"] == "High")
        low_id = next(a["id"] for a in acts if a["name"] == "Low")

        score_resp = client.post(
            f"/api/decisions/{decision_id}/score",
            json={
                "scores": [
                    {"activity_id": high_id, "metric_id": m1.id, "score": 90},
                    {"activity_id": high_id, "metric_id": m2.id, "score": 50},
                    {"activity_id": low_id, "metric_id": m1.id, "score": 30},
                    {"activity_id": low_id, "metric_id": m2.id, "score": 80},
                ]
            },
        )
        assert score_resp.status_code == 200

        detail = client.get(f"/api/decisions/{decision_id}").json()
        assert len(detail["results"]) == 1
        assert detail["results"][0]["activity_name"] == "High"

    def test_ko_missing_score(self, client, db):
        """No score for KO metric -> knocked_out."""
        from models import Metric
        m = db.query(Metric).order_by(Metric.id).first()

        resp = client.post("/api/decide", json={"q": "Test"})
        decision_id = resp.json()["decision_id"]

        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["NoScore"],
                "metrics": [{"metric_id": m.id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": m.id, "ko_operator": ">=", "ko_value": 50}
                ],
            },
        )
        assert refine_resp.status_code == 200

        # Don't submit any scores
        detail = client.get(f"/api/decisions/{decision_id}").json()
        assert detail["ko_result"] is not None
        assert detail["ko_result"]["results"][0]["status"] == "knocked_out"
        assert any("No score available" in r for r in detail["ko_result"]["results"][0]["reasons"])

    def test_export_includes_ko(self, client, db):
        """Markdown export includes KO section."""
        from models import Metric
        m = db.query(Metric).order_by(Metric.id).first()

        resp = client.post("/api/decide", json={"q": "Test KO export"})
        decision_id = resp.json()["decision_id"]

        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["Pass", "Fail"],
                "metrics": [{"metric_id": m.id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": m.id, "ko_operator": ">=", "ko_value": 60}
                ],
            },
        )
        assert refine_resp.status_code == 200
        acts = refine_resp.json()["activities"]
        pass_id = next(a["id"] for a in acts if a["name"] == "Pass")
        fail_id = next(a["id"] for a in acts if a["name"] == "Fail")

        client.post(
            f"/api/decisions/{decision_id}/score",
            json={
                "scores": [
                    {"activity_id": pass_id, "metric_id": m.id, "score": 80},
                    {"activity_id": fail_id, "metric_id": m.id, "score": 30},
                ]
            },
        )

        export_resp = client.get(f"/api/decisions/{decision_id}/export-markdown")
        assert export_resp.status_code == 200
        text = export_resp.text
        assert "## Knock-Out Criteria" in text
        assert "## Knock-Out Results" in text
        assert "PASSED" in text
        assert "KNOCKED OUT" in text

    def test_ko_robustness_only_eligible(self, client, db):
        """Robustness only on passed alts."""
        from models import Metric
        m = db.query(Metric).order_by(Metric.id).first()

        resp = client.post("/api/decide", json={"q": "Test"})
        decision_id = resp.json()["decision_id"]

        refine_resp = client.post(
            f"/api/decisions/{decision_id}/refine",
            json={
                "alternatives": ["Pass", "Fail"],
                "metrics": [{"metric_id": m.id, "weight": 80}],
                "ko_criteria": [
                    {"metric_id": m.id, "ko_operator": ">=", "ko_value": 60}
                ],
            },
        )
        assert refine_resp.status_code == 200
        acts = refine_resp.json()["activities"]
        pass_id = next(a["id"] for a in acts if a["name"] == "Pass")
        fail_id = next(a["id"] for a in acts if a["name"] == "Fail")

        client.post(
            f"/api/decisions/{decision_id}/score",
            json={
                "scores": [
                    {"activity_id": pass_id, "metric_id": m.id, "score": 80},
                    {"activity_id": fail_id, "metric_id": m.id, "score": 30},
                ]
            },
        )

        detail = client.get(f"/api/decisions/{decision_id}").json()
        assert detail["robustness"] is not None
        assert detail["robustness"]["winner_id"] == pass_id
        assert len(detail["robustness"]["rank_acceptability"]) == 1
        assert detail["robustness"]["rank_acceptability"][0]["activity_name"] == "Pass"
        # Only one passed alt -> top_two should be None
        assert detail["robustness"]["top_two"] is None


def test_api_decision_rows_expose_sensitivity_scoring_fields(client, db):
    """Decision detail rows include metric ids and decision-level weights."""
    from models import Activity, AlternativeScore, Decision, DecisionWeight, Metric

    metric = Metric(name="Sensitivity", category="General")
    db.add(metric)
    db.flush()

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
    assert "higher_is_better" not in row
    # Decision-level weight: both activities use the same weight
    assert row["weight"] == 80
    assert data["results"][0]["activity_name"] == "Second"
    assert data["results"][0]["fit_score"] == 0.3


class TestMetricsCrud:
    """CRUD coverage for POST /api/metrics, PUT /api/metrics/{id}, DELETE /api/metrics/{id}."""

    def test_create_metric_success(self, client, db):
        resp = client.post("/api/metrics", json={
            "name": "Test Metric",
            "category": "Resource Fit",
            "description": "A test metric",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Metric"
        assert data["category"] == "Resource Fit"
        assert data["description"] == "A test metric"
        assert isinstance(data["id"], int)

    def test_create_metric_duplicate_name(self, client, db):
        client.post("/api/metrics", json={"name": "Dup", "category": "Objective Fit", "description": ""})
        resp = client.post("/api/metrics", json={"name": "Dup", "category": "Assurance Fit", "description": ""})
        assert resp.status_code == 422
        assert "already exists" in resp.json()["detail"]

    def test_create_metric_missing_name(self, client, db):
        resp = client.post("/api/metrics", json={"category": "General", "description": ""})
        assert resp.status_code == 422
        assert "name is required" in resp.json()["detail"].lower()

    def test_create_metric_missing_category(self, client, db):
        resp = client.post("/api/metrics", json={"name": "NoCat", "description": ""})
        assert resp.status_code == 422
        assert "category is required" in resp.json()["detail"].lower()

    def test_create_metric_empty_name(self, client, db):
        resp = client.post("/api/metrics", json={"name": "  ", "category": "General"})
        assert resp.status_code == 422
        assert "name is required" in resp.json()["detail"].lower()

    def test_create_metric_rejects_reserved_legacy_seed_name(self, client, db):
        assert "Cost" in RESERVED_LEGACY_METRIC_NAMES

        resp = client.post(
            "/api/metrics",
            json={
                "name": "Cost",
                "category": "Resource Fit",
                "description": "Custom cost metric",
            },
        )

        assert resp.status_code == 422
        assert "reserved" in resp.json()["detail"].lower()
        assert db.query(Metric).filter(Metric.name == "Cost").count() == 0
        assert db.query(Metric).filter(Metric.name == "Affordability").count() == 1

    def test_update_metric_rejects_reserved_legacy_seed_name(self, client, db):
        create = client.post(
            "/api/metrics",
            json={
                "name": "Custom Risk View",
                "category": "Assurance Fit",
                "description": "Custom metric",
            },
        )
        metric_id = create.json()["id"]

        resp = client.put(
            f"/api/metrics/{metric_id}",
            json={
                "name": "Risk",
                "category": "Assurance Fit",
                "description": "Custom metric",
            },
        )

        assert resp.status_code == 422
        assert "reserved" in resp.json()["detail"].lower()
        metric = db.query(Metric).filter(Metric.id == metric_id).one()
        assert metric.name == "Custom Risk View"
        assert db.query(Metric).filter(Metric.name == "Risk").count() == 0

    def test_update_metric_success(self, client, db):
        create = client.post("/api/metrics", json={"name": "Old", "category": "Resource Fit", "description": "Old desc"})
        mid = create.json()["id"]
        resp = client.put(f"/api/metrics/{mid}", json={"name": "New Name", "category": "Objective Fit", "description": "New desc"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "New Name"
        assert data["category"] == "Objective Fit"
        assert data["description"] == "New desc"

    def test_update_metric_not_found(self, client, db):
        resp = client.put("/api/metrics/99999", json={"name": "Nope", "category": "General", "description": ""})
        assert resp.status_code == 404

    def test_update_metric_duplicate_name(self, client, db):
        client.post("/api/metrics", json={"name": "Existing", "category": "Resource Fit", "description": ""})
        create2 = client.post("/api/metrics", json={"name": "Target", "category": "Objective Fit", "description": ""})
        mid2 = create2.json()["id"]
        resp = client.put(f"/api/metrics/{mid2}", json={"name": "Existing", "category": "Assurance Fit", "description": ""})
        assert resp.status_code == 422
        assert "already exists" in resp.json()["detail"]

    def test_delete_metric_success(self, client, db):
        create = client.post("/api/metrics", json={"name": "Delete Me", "category": "Time Fit", "description": ""})
        mid = create.json()["id"]
        resp = client.delete(f"/api/metrics/{mid}")
        assert resp.status_code == 200
        assert resp.json() == {"status": "deleted"}
        # Verify gone
        get_resp = client.get("/api/metrics")
        all_ids = [m["id"] for group in get_resp.json()["grouped_metrics"].values() for m in group]
        assert mid not in all_ids

    def test_delete_metric_not_found(self, client, db):
        resp = client.delete("/api/metrics/99999")
        assert resp.status_code == 404

    def test_delete_metric_cascades_to_scores_and_weights(self, client, db):
        from models import DecisionWeight, AlternativeScore, Metric as MetricModel
        
        # Create a metric
        create = client.post("/api/metrics", json={"name": "Cascade Metric", "category": "Resource Fit", "description": ""})
        metric_id = create.json()["id"]

        # Create a decision with this metric
        decide = client.post("/api/decide", json={"q": "Test cascade"})
        dec_id = decide.json()["decision_id"]

        # Refine to add the metric
        client.post(f"/api/decisions/{dec_id}/refine", json={
            "alternatives": ["A", "B"],
            "metrics": [{"metric_id": metric_id, "weight": 80}],
        })

        # Score
        detail = client.get(f"/api/decisions/{dec_id}").json()
        act_ids = [a["id"] for a in detail["activities"]]
        client.post(f"/api/decisions/{dec_id}/score", json={
            "scores": [
                {"activity_id": act_ids[0], "metric_id": metric_id, "score": 50},
                {"activity_id": act_ids[1], "metric_id": metric_id, "score": 70},
            ],
        })

        # Verify weights and scores exist
        assert db.query(DecisionWeight).filter(DecisionWeight.metric_id == metric_id).count() > 0
        assert db.query(AlternativeScore).filter(AlternativeScore.metric_id == metric_id).count() > 0

        # Delete the metric
        resp = client.delete(f"/api/metrics/{metric_id}")
        assert resp.status_code == 200

        # Verify cascade
        assert db.query(DecisionWeight).filter(DecisionWeight.metric_id == metric_id).count() == 0
        assert db.query(AlternativeScore).filter(AlternativeScore.metric_id == metric_id).count() == 0
        assert db.query(MetricModel).filter(MetricModel.id == metric_id).count() == 0


class TestCustomMetrics:
    """Coverage for decision-scoped custom metrics CRUD, refine, scoring, and export."""

    def test_create_custom_metric_success(self, client, db):
        """POST /api/decisions/{id}/custom-metrics → scope=decision, source=user, auto-weight=50."""
        from models import DecisionWeight

        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        resp = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "My Metric", "category": "Resource Fit", "description": "Custom desc"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["scope"] == "decision"
        assert data["source"] == "user"
        assert data["decision_id"] == dec_id
        assert data["stable_id"] is None
        assert data["anchors"] is None
        assert data["name"] == "My Metric"
        assert data["category"] == "Resource Fit"
        assert data["description"] == "Custom desc"
        assert isinstance(data["id"], int)

        # Auto-weight should be 50
        dw = db.query(DecisionWeight).filter(
            DecisionWeight.decision_id == dec_id,
            DecisionWeight.metric_id == data["id"],
        ).first()
        assert dw is not None
        assert dw.weight == 50

    def test_create_custom_metric_persists_requested_weight(self, client, db):
        """AI-selected custom metrics can persist recommended weights immediately."""
        from models import DecisionWeight

        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]
        resp = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "AI Fit", "category": "Practical Fit", "weight": 73},
        )
        assert resp.status_code == 201
        metric_id = resp.json()["id"]
        dw = db.query(DecisionWeight).filter(
            DecisionWeight.decision_id == dec_id,
            DecisionWeight.metric_id == metric_id,
        ).one()
        assert dw.weight == 73

    def test_create_custom_metric_duplicate_name_same_decision(self, client, db):
        """Same name within same decision → 422."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Dup", "category": "Resource Fit"},
        )
        resp = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Dup", "category": "Objective Fit"},
        )
        assert resp.status_code == 422
        assert "already exists" in resp.json()["detail"]

    def test_create_custom_metric_same_name_different_decision(self, client, db):
        """Same name in different decisions → both 201."""
        d1 = client.post("/api/decide", json={"q": "First"})
        d2 = client.post("/api/decide", json={"q": "Second"})
        id1 = d1.json()["decision_id"]
        id2 = d2.json()["decision_id"]

        r1 = client.post(
            f"/api/decisions/{id1}/custom-metrics",
            json={"name": "Shared", "category": "Resource Fit"},
        )
        r2 = client.post(
            f"/api/decisions/{id2}/custom-metrics",
            json={"name": "Shared", "category": "Objective Fit"},
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["name"] == "Shared"
        assert r2.json()["name"] == "Shared"

    def test_create_custom_metric_same_name_as_global(self, client, db):
        """Same name as a global ontology metric → 201 (allowed)."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        # "Affordability" is a global ontology metric
        resp = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Affordability", "category": "Resource Fit", "description": "Custom Affordability"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Affordability"
        assert data["scope"] == "decision"
        assert data["stable_id"] is None  # scope-aware: no ontology metadata

    def test_create_custom_metric_missing_name(self, client, db):
        """Missing name → 422."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        resp = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"category": "Resource Fit"},
        )
        assert resp.status_code == 422
        assert "name is required" in resp.json()["detail"].lower()

    def test_create_custom_metric_reserved_legacy_name(self, client, db):
        """Reserved legacy name 'Cost' → 422."""
        assert "Cost" in RESERVED_LEGACY_METRIC_NAMES
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        resp = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Cost", "category": "Resource Fit"},
        )
        assert resp.status_code == 422
        assert "reserved" in resp.json()["detail"].lower()

    def test_create_custom_metric_unknown_decision(self, client, db):
        """Non-existent decision → 404."""
        resp = client.post(
            "/api/decisions/99999/custom-metrics",
            json={"name": "Test", "category": "Resource Fit"},
        )
        assert resp.status_code == 404

    def test_update_custom_metric_success(self, client, db):
        """PUT /api/decisions/{id}/custom-metrics/{mid} → 200."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        create = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Original", "category": "Resource Fit", "description": "Original desc"},
        )
        metric_id = create.json()["id"]

        update = client.put(
            f"/api/decisions/{dec_id}/custom-metrics/{metric_id}",
            json={"name": "Updated", "category": "Objective Fit", "description": "Updated desc"},
        )
        assert update.status_code == 200
        data = update.json()
        assert data["name"] == "Updated"
        assert data["category"] == "Objective Fit"
        assert data["description"] == "Updated desc"
        assert data["scope"] == "decision"
        assert data["stable_id"] is None

    def test_update_custom_metric_not_found(self, client, db):
        """Update non-existent metric → 404."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        resp = client.put(
            f"/api/decisions/{dec_id}/custom-metrics/99999",
            json={"name": "Nope", "category": "Resource Fit"},
        )
        assert resp.status_code == 404

    def test_delete_custom_metric_success(self, client, db):
        """DELETE custom metric → 200, verify DecisionWeight cascade."""
        from models import DecisionWeight

        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        create = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Delete Me", "category": "Resource Fit"},
        )
        metric_id = create.json()["id"]

        # Verify weight exists
        assert db.query(DecisionWeight).filter(
            DecisionWeight.metric_id == metric_id,
            DecisionWeight.decision_id == dec_id,
        ).count() == 1

        resp = client.delete(f"/api/decisions/{dec_id}/custom-metrics/{metric_id}")
        assert resp.status_code == 200
        assert resp.json() == {"status": "deleted"}

        # Verify Metric row deleted
        assert db.query(Metric).filter(Metric.id == metric_id).count() == 0
        # Verify DecisionWeight cascade deleted
        assert db.query(DecisionWeight).filter(
            DecisionWeight.metric_id == metric_id,
        ).count() == 0

    def test_delete_decision_removes_custom_metrics(self, client, db):
        """Deleting a decision cascades to its custom Metric rows."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        create = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Custom Metric", "category": "Resource Fit"},
        )
        metric_id = create.json()["id"]

        # Delete the decision
        resp = client.post(f"/api/decisions/{dec_id}/delete")
        assert resp.status_code == 200

        # Custom Metric should be gone
        assert db.query(Metric).filter(Metric.id == metric_id).count() == 0

    def test_refine_with_custom_metric_weight(self, client, db):
        """Refine with custom metric weight preserves DecisionWeight."""
        from models import DecisionWeight

        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        create = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Custom", "category": "Resource Fit"},
        )
        metric_id = create.json()["id"]

        # Refine with custom metric weight
        resp = client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": ["A", "B"],
                "metrics": [
                    {"metric_id": metric_id, "weight": 75},
                ],
            },
        )
        assert resp.status_code == 200

        # Verify weight preserved
        dw = db.query(DecisionWeight).filter(
            DecisionWeight.decision_id == dec_id,
            DecisionWeight.metric_id == metric_id,
        ).first()
        assert dw is not None
        assert dw.weight == 75

    def test_refine_omits_custom_metric_weight(self, client, db):
        """Refine without custom metric weight → DecisionWeight deleted."""
        from models import DecisionWeight

        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        create = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Custom", "category": "Resource Fit"},
        )
        metric_id = create.json()["id"]

        # First refine with it
        client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": ["A", "B"],
                "metrics": [{"metric_id": metric_id, "weight": 50}],
            },
        )

        # Second refine without it
        # Get a global metric to include instead
        global_metric = db.query(Metric).filter(Metric.decision_id.is_(None)).first()
        resp = client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": ["A", "B"],
                "metrics": [{"metric_id": global_metric.id, "weight": 80}],
            },
        )
        assert resp.status_code == 200

        # Custom metric DecisionWeight should be gone
        assert db.query(DecisionWeight).filter(
            DecisionWeight.decision_id == dec_id,
            DecisionWeight.metric_id == metric_id,
        ).count() == 0

    def test_custom_metric_named_like_builtin_returns_none_ontology(self, client, db):
        """Custom metric named 'Affordability' → stable_id=None, anchors=None in detail."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        create = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Affordability", "category": "Resource Fit"},
        )
        metric_id = create.json()["id"]

        # Refine to add it
        client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": ["A", "B"],
                "metrics": [{"metric_id": metric_id, "weight": 50}],
            },
        )

        # Get decision detail
        detail = client.get(f"/api/decisions/{dec_id}").json()
        custom_metrics = [m for m in detail["metrics"] if m["id"] == metric_id]
        assert len(custom_metrics) == 1
        cm = custom_metrics[0]
        assert cm["stable_id"] is None
        assert cm["anchors"] is None
        assert cm["category_id"] is None
        assert cm["name"] == "Affordability"
        assert cm["scope"] == "decision"

    def test_list_metrics_global_only(self, client, db):
        """GET /api/metrics excludes decision-scoped custom metrics."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Secret Custom", "category": "Resource Fit"},
        )

        # Global list should not include it
        resp = client.get("/api/metrics")
        data = resp.json()
        all_names = [
            m["name"] for group in data["grouped_metrics"].values() for m in group
        ]
        assert "Secret Custom" not in all_names

    def test_decision_detail_includes_custom_metrics(self, client, db):
        """Decision detail includes custom metrics in the metrics array."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        create = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Custom Detail", "category": "Resource Fit"},
        )
        metric_id = create.json()["id"]

        # Refine to add it
        client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": ["A", "B"],
                "metrics": [{"metric_id": metric_id, "weight": 60}],
            },
        )

        detail = client.get(f"/api/decisions/{dec_id}").json()
        metric_ids = [m["id"] for m in detail["metrics"]]
        assert metric_id in metric_ids

        cm = next(m for m in detail["metrics"] if m["id"] == metric_id)
        assert cm["scope"] == "decision"
        assert cm["source"] == "user"
        assert cm["decision_id"] == dec_id

    def test_scoring_with_custom_metric(self, client, db):
        """Score a custom metric and verify correct fit score."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        create = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Custom Score", "category": "Resource Fit"},
        )
        metric_id = create.json()["id"]

        # Refine with it
        client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": ["Option A", "Option B"],
                "metrics": [{"metric_id": metric_id, "weight": 100}],
            },
        )

        # Score
        detail = client.get(f"/api/decisions/{dec_id}").json()
        act_ids = [a["id"] for a in detail["activities"]]
        score_resp = client.post(
            f"/api/decisions/{dec_id}/score",
            json={
                "scores": [
                    {"activity_id": act_ids[0], "metric_id": metric_id, "score": 80},
                    {"activity_id": act_ids[1], "metric_id": metric_id, "score": 40},
                ],
            },
        )
        assert score_resp.status_code == 200
        score_data = score_resp.json()

        # With only one metric at weight 100, fit_score = score / 100
        results = score_data["results"]
        assert len(results) == 2
        for r in results:
            if r["activity_id"] == act_ids[0]:
                assert r["fit_score"] == 0.8  # 80 / 100
            else:
                assert r["fit_score"] == 0.4  # 40 / 100

    def test_export_with_custom_metrics(self, client, db):
        """Markdown export includes custom metric rows."""
        decide = client.post("/api/decide", json={"q": "Pick one"})
        dec_id = decide.json()["decision_id"]

        create = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Custom Export", "category": "Resource Fit"},
        )
        metric_id = create.json()["id"]

        # Refine with it
        client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": ["A", "B"],
                "metrics": [{"metric_id": metric_id, "weight": 50}],
            },
        )

        # Score
        detail = client.get(f"/api/decisions/{dec_id}").json()
        act_ids = [a["id"] for a in detail["activities"]]
        client.post(
            f"/api/decisions/{dec_id}/score",
            json={
                "scores": [
                    {"activity_id": act_ids[0], "metric_id": metric_id, "score": 90},
                    {"activity_id": act_ids[1], "metric_id": metric_id, "score": 60},
                ],
            },
        )

        # Export
        export = client.get(f"/api/decisions/{dec_id}/export-markdown")
        assert export.status_code == 200
        content = export.text
        assert "Custom Export" in content
        assert "50.0" in content  # weight value
        assert "90.0" in content  # score for A
        assert "60.0" in content  # score for B


class TestUserCreatedGlobalMetrics:
    """User-created global metrics (from MetricsManager) should appear in new decisions."""

    def test_user_created_global_metric_appears_in_new_decision(self, client, db):
        """Create a global metric, then create a decision — metric should be seeded."""
        # Create a global metric via MetricsManager
        create = client.post(
            "/api/metrics",
            json={"name": "My Custom Global", "category": "Resource Fit", "description": "User-made"},
        )
        assert create.status_code == 201
        metric_id = create.json()["id"]

        # Create a new decision
        decide = client.post("/api/decide", json={"q": "Should I do X or Y?"})
        assert decide.status_code == 200
        dec_id = decide.json()["decision_id"]

        # Decision detail should include the user-created global metric
        detail = client.get(f"/api/decisions/{dec_id}").json()
        metric_ids = [m["id"] for m in detail["metrics"]]
        assert metric_id in metric_ids, f"User-created global metric {metric_id} not found in decision {dec_id} metrics: {metric_ids}"

        # It should also have a DecisionWeight
        from models import DecisionWeight
        dw = db.query(DecisionWeight).filter(
            DecisionWeight.decision_id == dec_id,
            DecisionWeight.metric_id == metric_id,
        ).first()
        assert dw is not None, "User-created global metric should have a DecisionWeight"
        assert dw.weight == 50, "User-created global metric should default to weight 50"

    def test_multiple_user_created_global_metrics_all_seeded(self, client, db):
        """Multiple user-created global metrics all appear in new decisions."""
        ids = []
        for name in ["Alpha Metric", "Beta Metric", "Gamma Metric"]:
            r = client.post("/api/metrics", json={"name": name, "category": "Objective Fit"})
            assert r.status_code == 201
            ids.append(r.json()["id"])

        decide = client.post("/api/decide", json={"q": "Pick A, B, or C"})
        dec_id = decide.json()["decision_id"]

        detail = client.get(f"/api/decisions/{dec_id}").json()
        detail_metric_ids = {m["id"] for m in detail["metrics"]}
        for mid in ids:
            assert mid in detail_metric_ids, f"Metric {mid} missing from decision metrics"

    def test_user_created_global_metric_does_not_break_builtin_metrics(self, client, db):
        """Built-in metrics still get seeded alongside user-created ones."""
        from services.ontology import UNIVERSAL_METRICS

        client.post("/api/metrics", json={"name": "Side Metric", "category": "People Fit"})

        decide = client.post("/api/decide", json={"q": "House vs Apartment"})
        dec_id = decide.json()["decision_id"]

        detail = client.get(f"/api/decisions/{dec_id}").json()
        metric_names = {m["name"] for m in detail["metrics"]}

        # All built-in metrics should still be present
        for builtin in UNIVERSAL_METRICS:
            assert builtin["name"] in metric_names, f"Built-in metric '{builtin['name']}' missing"

        # Plus the user-created one
        assert "Side Metric" in metric_names


class TestKOCriteriaOnCustomMetrics:
    """KO criteria should work on custom metrics just like global metrics."""

    def test_set_ko_on_custom_metric_via_refine(self, client, db):
        """KO criteria can be set on a custom metric through the refine endpoint."""
        decide = client.post("/api/decide", json={"q": "Option A vs Option B"})
        dec_id = decide.json()["decision_id"]

        # Create a custom metric
        cm = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "My Custom", "category": "Resource Fit"},
        ).json()
        cm_id = cm["id"]

        # Refine with custom metric + KO criteria
        detail = client.get(f"/api/decisions/{dec_id}").json()
        act_names = [a["name"] for a in detail["activities"]]
        global_metric_id = detail["metrics"][0]["id"]

        refine = client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": act_names,
                "metrics": [
                    {"metric_id": global_metric_id, "weight": 80},
                    {"metric_id": cm_id, "weight": 60},
                ],
                "ko_criteria": [
                    {"metric_id": cm_id, "ko_operator": ">=", "ko_value": 50},
                ],
            },
        )
        assert refine.status_code == 200

        # Verify KO criteria stored on decision
        import json
        from models import Decision
        decision = db.query(Decision).filter(Decision.id == dec_id).first()
        assert decision.ko_criteria is not None
        stored_ko = json.loads(decision.ko_criteria)
        assert any(kc["metric_id"] == cm_id for kc in stored_ko)

    def test_ko_thresholds_on_custom_metric_survive_score_and_results(self, client, db):
        """KO criteria on custom metrics are evaluated during scoring."""
        decide = client.post("/api/decide", json={"q": "X vs Y"})
        dec_id = decide.json()["decision_id"]

        # Create custom metric
        cm = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Knockout Metric", "category": "Assurance Fit"},
        ).json()
        cm_id = cm["id"]

        # Refine with custom metric + KO
        detail = client.get(f"/api/decisions/{dec_id}").json()
        act_names = [a["name"] for a in detail["activities"]]
        global_mid = detail["metrics"][0]["id"]

        refine = client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": act_names,
                "metrics": [
                    {"metric_id": global_mid, "weight": 50},
                    {"metric_id": cm_id, "weight": 50},
                ],
                "ko_criteria": [
                    {"metric_id": cm_id, "ko_operator": ">=", "ko_value": 70},
                ],
            },
        )
        assert refine.status_code == 200

        # Get activity IDs
        detail2 = client.get(f"/api/decisions/{dec_id}").json()
        act_ids = [a["id"] for a in detail2["activities"]]

        # Score — first activity scores high on custom (passes KO), second scores low (fails KO)
        score_resp = client.post(
            f"/api/decisions/{dec_id}/score",
            json={
                "scores": [
                    {"activity_id": act_ids[0], "metric_id": global_mid, "score": 50},
                    {"activity_id": act_ids[0], "metric_id": cm_id, "score": 90},
                    {"activity_id": act_ids[1], "metric_id": global_mid, "score": 50},
                    {"activity_id": act_ids[1], "metric_id": cm_id, "score": 30},
                ],
            },
        )
        assert score_resp.status_code == 200

        # Results should include KO result
        result = client.get(f"/api/decisions/{dec_id}").json()
        assert result.get("ko_result") is not None
        # Activity with score 30 on a >=70 KO should be knocked_out
        ko_result = result["ko_result"]
        if isinstance(ko_result, str):
            import json
            ko_result = json.loads(ko_result)
        ko_results_list = ko_result.get("results", []) if isinstance(ko_result, dict) else ko_result
        knocked_out = [r for r in ko_results_list if isinstance(r, dict) and r.get("status") == "knocked_out"]
        assert len(knocked_out) >= 1, f"Expected at least 1 knocked_out activity, got: {ko_result}"

    def test_ko_on_custom_metric_removed_when_metric_excluded_via_refine(self, client, db):
        """KO criteria for a custom metric are cleaned up when the metric is omitted from refine."""
        decide = client.post("/api/decide", json={"q": "Red vs Blue"})
        dec_id = decide.json()["decision_id"]

        cm = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Temporary", "category": "Time Fit"},
        ).json()
        cm_id = cm["id"]

        # First refine with the custom metric and KO
        detail = client.get(f"/api/decisions/{dec_id}").json()
        global_mid = detail["metrics"][0]["id"]

        client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": ["Red", "Blue"],
                "metrics": [
                    {"metric_id": global_mid, "weight": 50},
                    {"metric_id": cm_id, "weight": 50},
                ],
                "ko_criteria": [
                    {"metric_id": cm_id, "ko_operator": ">=", "ko_value": 50},
                ],
            },
        )

        # Second refine WITHOUT the custom metric — KO should be gone
        refine2 = client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": ["Red", "Blue"],
                "metrics": [
                    {"metric_id": global_mid, "weight": 80},
                ],
                "ko_criteria": [],  # explicitly clear KO criteria
            },
        )
        assert refine2.status_code == 200

        import json
        from models import Decision
        decision = db.query(Decision).filter(Decision.id == dec_id).first()
        if decision.ko_criteria:
            stored_ko = json.loads(decision.ko_criteria)
            assert all(kc["metric_id"] != cm_id for kc in stored_ko), \
                "KO criteria for omitted custom metric should not persist"


class TestMetricLimitWithCustomMetrics:
    """MAX_DECISION_METRICS should accommodate both global and custom metrics."""

    def test_decision_with_global_and_custom_metrics_under_limit(self, client, db):
        """Refine with 12 global + custom metrics should pass the 20 metric limit."""
        decide = client.post("/api/decide", json={"q": "Option A vs Option B"})
        dec_id = decide.json()["decision_id"]

        # Get the auto-seeded global metrics
        detail = client.get(f"/api/decisions/{dec_id}").json()
        global_metrics = detail["metrics"]

        # Add a custom metric
        cm = client.post(
            f"/api/decisions/{dec_id}/custom-metrics",
            json={"name": "Extra Metric", "category": "Resource Fit"},
        ).json()

        # Refine with all global metrics + the custom metric (13 total, under limit of 20)
        metrics_payload = [{"metric_id": m["id"], "weight": 50} for m in global_metrics]
        metrics_payload.append({"metric_id": cm["id"], "weight": 50})

        refine = client.post(
            f"/api/decisions/{dec_id}/refine",
            json={
                "alternatives": ["Option A", "Option B"],
                "metrics": metrics_payload,
            },
        )
        assert refine.status_code == 200, f"Expected 200, got {refine.status_code}: {refine.text}"


class TestEvidenceAndScoreDrafts:
    def _decision_cell(self, client):
        resp = client.post("/api/decide", json={"q": "Option A vs Option B"})
        assert resp.status_code == 200
        decision_id = resp.json()["decision_id"]
        detail = client.get(f"/api/decisions/{decision_id}").json()
        return decision_id, detail["activities"][0]["id"], detail["metrics"][0]["id"]

    def test_ai_status_disabled_does_not_expose_key(self, client, monkeypatch):
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
        resp = client.get("/api/ai/status")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["enabled"] is True
        assert payload["provider"] == "openai"
        assert "secret-value" not in str(payload)
        assert "OPENAI_API_KEY" not in str(payload)

    def test_evidence_crud_and_review(self, client):
        decision_id, activity_id, metric_id = self._decision_cell(client)
        created = client.post(
            f"/api/decisions/{decision_id}/evidence",
            json={
                "claim": "Option A has strong fit evidence",
                "activity_id": activity_id,
                "metric_id": metric_id,
                "confidence": 0.7,
                "polarity": "positive",
            },
        )
        assert created.status_code == 201
        evidence = created.json()
        assert evidence["review_status"] == "pending"
        approved = client.post(f"/api/decisions/{decision_id}/evidence/{evidence['id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["review_status"] == "approved"
        listed = client.get(f"/api/decisions/{decision_id}/evidence", params={"review_status": "approved"})
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["evidence"]] == [evidence["id"]]
        deleted = client.delete(f"/api/decisions/{decision_id}/evidence/{evidence['id']}")
        assert deleted.status_code == 200
        assert deleted.json() == {"status": "deleted"}

    def test_drafts_apply_is_only_path_to_final_score(self, client, db):
        decision_id, activity_id, metric_id = self._decision_cell(client)
        draft_resp = client.post(
            f"/api/decisions/{decision_id}/score-drafts",
            json={"activity_id": activity_id, "metric_id": metric_id, "suggested_score": 88},
        )
        assert draft_resp.status_code == 201
        draft = draft_resp.json()
        assert db.query(AlternativeScore).count() == 0
        patch_resp = client.patch(
            f"/api/decisions/{decision_id}/score-drafts/{draft['id']}",
            json={"human_adjusted_score": 90},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "edited"
        assert db.query(AlternativeScore).count() == 0
        approve_patch = client.patch(
            f"/api/decisions/{decision_id}/score-drafts/{draft['id']}",
            json={"status": "approved"},
        )
        assert approve_patch.status_code == 422
        approve_resp = client.post(f"/api/decisions/{decision_id}/score-drafts/{draft['id']}/approve")
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"
        assert db.query(AlternativeScore).count() == 0
        apply_resp = client.post(f"/api/decisions/{decision_id}/score-drafts/{draft['id']}/apply")
        assert apply_resp.status_code == 200
        assert apply_resp.json()["score"]["score"] == 90
        assert db.query(AlternativeScore).filter_by(activity_id=activity_id, metric_id=metric_id).one().score == 90
        second_apply = client.post(f"/api/decisions/{decision_id}/score-drafts/{draft['id']}/apply")
        assert second_apply.status_code == 409

    def test_manual_score_draft_rejects_llm_source(self, client):
        decision_id, activity_id, metric_id = self._decision_cell(client)
        resp = client.post(
            f"/api/decisions/{decision_id}/score-drafts",
            json={"activity_id": activity_id, "metric_id": metric_id, "suggested_score": 50, "source_type": "llm"},
        )
        assert resp.status_code == 422

    def test_mocked_ai_inserts_pending_only_then_bulk_apply(self, client, db, monkeypatch):
        decision_id, activity_id, metric_id = self._decision_cell(client)
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        def fake_ai(_prompt):
            return {
                "evidence_items": [
                    {"activity_id": activity_id, "metric_id": metric_id, "claim": "Strong evidence", "confidence": 0.8, "polarity": "positive"}
                ],
                "score_drafts": [
                    {"activity_id": activity_id, "metric_id": metric_id, "suggested_score": 77, "evidence_ids": []}
                ],
                "metric_suggestions": [
                    {"name": "Fit detail", "category": "Practical Fit", "description": "Extra local fit", "recommended_weight": 55}
                ],
            }

        monkeypatch.setattr("routers.api.OpenAIDecisionClient.structured_json", lambda self, prompt: fake_ai(prompt))
        ev_resp = client.post(f"/api/decisions/{decision_id}/ai/draft-evidence", json={})
        assert ev_resp.status_code == 201
        evidence = ev_resp.json()["evidence_items"][0]
        assert evidence["source_type"] == "llm"
        assert evidence["review_status"] == "pending"
        draft_resp = client.post(f"/api/decisions/{decision_id}/ai/suggest-scores", json={})
        assert draft_resp.status_code == 201
        draft = draft_resp.json()["score_drafts"][0]
        assert draft["source_type"] == "llm"
        assert draft["status"] == "pending"
        assert db.query(AlternativeScore).count() == 0
        bulk = client.post(f"/api/decisions/{decision_id}/score-drafts/apply", json={"draft_ids": [draft["id"]]})
        assert bulk.status_code == 200
        assert bulk.json()["status"] == "applied"
        assert db.query(AlternativeScore).count() == 1
        suggestions = client.post(f"/api/decisions/{decision_id}/ai/suggest-metrics", json={})
        assert suggestions.status_code == 200
        assert suggestions.json()["metric_suggestions"][0]["name"] == "Fit detail"

    def test_malformed_ai_output_is_safe(self, client, monkeypatch):
        decision_id, _, _ = self._decision_cell(client)
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setattr("routers.api.OpenAIDecisionClient.structured_json", lambda self, prompt: {"score_drafts": "bad"})
        resp = client.post(f"/api/decisions/{decision_id}/ai/suggest-scores", json={})
        assert resp.status_code == 502

    def test_ai_max_request_fields_validate_strictly(self, client, monkeypatch):
        decision_id, _, _ = self._decision_cell(client)
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setattr("routers.api.OpenAIDecisionClient.structured_json", lambda self, prompt: {})

        assert client.post(f"/api/decisions/{decision_id}/ai/suggest-metrics", json={"max_suggestions": "2"}).status_code == 422
        assert client.post(f"/api/decisions/{decision_id}/ai/draft-evidence", json={"max_items": 0}).status_code == 422
        assert client.post(f"/api/decisions/{decision_id}/ai/suggest-scores", json={"max_drafts": 101}).status_code == 422

    def test_ai_provider_invalid_numeric_items_are_skipped(self, client, monkeypatch):
        decision_id, activity_id, metric_id = self._decision_cell(client)
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        def fake_ai(_prompt):
            return {
                "metric_suggestions": [
                    {"name": "Bad", "category": "Resource Fit", "recommended_weight": "heavy"},
                    {"name": "Good", "category": "Resource Fit", "recommended_weight": 65},
                ],
                "evidence_items": [
                    {"activity_id": activity_id, "metric_id": metric_id, "claim": "Bad confidence", "confidence": "high"},
                    {"activity_id": activity_id, "metric_id": metric_id, "claim": "Good evidence", "confidence": 0.6},
                ],
                "score_drafts": [
                    {"activity_id": activity_id, "metric_id": metric_id, "suggested_score": "high"},
                    {"activity_id": activity_id, "metric_id": metric_id, "suggested_score": 72},
                ],
            }

        monkeypatch.setattr("routers.api.OpenAIDecisionClient.structured_json", lambda self, prompt: fake_ai(prompt))
        suggestions = client.post(f"/api/decisions/{decision_id}/ai/suggest-metrics", json={})
        assert suggestions.status_code == 200
        assert [item["name"] for item in suggestions.json()["metric_suggestions"]] == ["Good"]
        evidence = client.post(f"/api/decisions/{decision_id}/ai/draft-evidence", json={})
        assert evidence.status_code == 201
        assert [item["claim"] for item in evidence.json()["evidence_items"]] == ["Good evidence"]
        assert len(evidence.json()["skipped"]) == 1
        drafts = client.post(f"/api/decisions/{decision_id}/ai/suggest-scores", json={})
        assert drafts.status_code == 201
        assert [item["suggested_score"] for item in drafts.json()["score_drafts"]] == [72]
        assert len(drafts.json()["skipped"]) == 1

    def test_ai_filters_and_evidence_review_policy_are_enforced(self, client, monkeypatch):
        resp = client.post("/api/decide", json={"q": "Option A vs Option B"})
        decision_id = resp.json()["decision_id"]
        detail = client.get(f"/api/decisions/{decision_id}").json()
        activity_id = detail["activities"][0]["id"]
        other_activity_id = detail["activities"][1]["id"]
        metric_id = detail["metrics"][0]["id"]
        other_metric_id = detail["metrics"][1]["id"]
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        def fake_evidence(_prompt):
            return {
                "evidence_items": [
                    {"claim": "general"},
                    {"activity_id": other_activity_id, "metric_id": metric_id, "claim": "wrong activity"},
                    {"activity_id": activity_id, "metric_id": other_metric_id, "claim": "wrong metric"},
                    {"activity_id": activity_id, "metric_id": metric_id, "claim": "allowed"},
                ]
            }

        monkeypatch.setattr("routers.api.OpenAIDecisionClient.structured_json", lambda self, prompt: fake_evidence(prompt))
        evidence_resp = client.post(
            f"/api/decisions/{decision_id}/ai/draft-evidence",
            json={"activity_ids": [activity_id], "metric_ids": [metric_id], "include_general_evidence": False},
        )
        assert evidence_resp.status_code == 201
        evidence_payload = evidence_resp.json()
        assert [item["claim"] for item in evidence_payload["evidence_items"]] == ["allowed"]
        assert len(evidence_payload["skipped"]) == 3
        evidence_id = evidence_payload["evidence_items"][0]["id"]
        approved = client.post(f"/api/decisions/{decision_id}/evidence/{evidence_id}/approve").json()

        pending_evidence = client.post(
            f"/api/decisions/{decision_id}/evidence",
            json={"activity_id": activity_id, "metric_id": metric_id, "claim": "pending link"},
        ).json()

        def fake_scores(_prompt):
            return {
                "score_drafts": [
                    {"activity_id": other_activity_id, "metric_id": metric_id, "suggested_score": 80},
                    {"activity_id": activity_id, "metric_id": other_metric_id, "suggested_score": 80},
                    {"activity_id": activity_id, "metric_id": metric_id, "suggested_score": 80, "evidence_ids": [pending_evidence["id"]]},
                    {"activity_id": activity_id, "metric_id": metric_id, "suggested_score": 81, "evidence_ids": [approved["id"]]},
                ]
            }

        monkeypatch.setattr("routers.api.OpenAIDecisionClient.structured_json", lambda self, prompt: fake_scores(prompt))
        draft_resp = client.post(
            f"/api/decisions/{decision_id}/ai/suggest-scores",
            json={"activity_ids": [activity_id], "metric_ids": [metric_id], "evidence_review_policy": "approved_only"},
        )
        assert draft_resp.status_code == 201
        draft_payload = draft_resp.json()
        assert [item["suggested_score"] for item in draft_payload["score_drafts"]] == [81]
        assert len(draft_payload["skipped"]) == 3

    def test_patch_any_pending_or_approved_draft_edit_marks_edited(self, client):
        decision_id, activity_id, metric_id = self._decision_cell(client)
        draft = client.post(
            f"/api/decisions/{decision_id}/score-drafts",
            json={"activity_id": activity_id, "metric_id": metric_id, "suggested_score": 50},
        ).json()
        approved = client.post(f"/api/decisions/{decision_id}/score-drafts/{draft['id']}/approve")
        assert approved.status_code == 200
        edited = client.patch(
            f"/api/decisions/{decision_id}/score-drafts/{draft['id']}",
            json={"rationale": "Human edited rationale"},
        )
        assert edited.status_code == 200
        assert edited.json()["status"] == "edited"
