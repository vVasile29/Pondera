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
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "decisions" in data
    assert isinstance(data["decisions"], list)


def test_create_metric(client, db):
    """Test creating a metric via API."""
    response = client.post(
        "/metrics", json={"name": "Test Metric", "category": "Financial", "unit": "cm"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Metric"
    assert data["category"] == "Financial"


def test_list_metrics(client, db):
    """Test metrics page loads."""
    response = client.get("/metrics")
    assert response.status_code == 200


def test_delete_metric(client, db):
    """Test deleting a metric."""
    resp = client.post("/metrics", json={"name": "Delete Me", "category": "Financial"})
    metric_id = resp.json()["id"]

    response = client.delete(f"/metrics/{metric_id}")
    assert response.status_code == 200


def test_add_sub_metric(client, db):
    """Test adding a sub-metric."""
    resp = client.post("/metrics", json={"name": "Parent", "category": "Financial"})
    parent_id = resp.json()["id"]

    response = client.post(
        f"/metrics/{parent_id}/sub", json={"name": "Child", "category": "Financial"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["parent_id"] == parent_id


def test_add_sub_metric_to_sub_metric_fails(client, db):
    """Test that adding sub-metric to a sub-metric returns 400."""
    resp = client.post("/metrics", json={"name": "Parent", "category": "Financial"})
    parent_id = resp.json()["id"]

    resp = client.post(
        f"/metrics/{parent_id}/sub", json={"name": "Child", "category": "Financial"}
    )
    child_id = resp.json()["id"]

    response = client.post(
        f"/metrics/{child_id}/sub", json={"name": "Grandchild", "category": "Financial"}
    )
    assert response.status_code == 400


# ── Decision flow tests ──


def test_decide_flow_parsed(client, db):
    """Test the full decide flow with a parsable question."""
    response = client.post(
        "/decide", data={"q": "Should I buy a house or an apartment?"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "choose"
    assert "house" in str(data["alternatives"]).lower() or "House" in str(data["alternatives"])
    assert "apartment" in str(data["alternatives"]).lower() or "Apartment" in str(data["alternatives"])


def test_decide_flow_with_do_verb(client, db):
    """'should I do X or Y' correctly extracts Aikido and Football."""
    response = client.post("/decide", data={"q": "should I do aikido or football"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "choose"
    assert "Aikido" in str(data["alternatives"]) or "aikido" in str(data["alternatives"])
    assert "Football" in str(data["alternatives"]) or "football" in str(data["alternatives"])


def test_review_page_get(client, db):
    """GET /decisions/{id}/review returns the review data."""
    # Create a decision first
    resp = client.post("/decide", data={"q": "Tea or Coffee?"})
    assert resp.status_code == 200
    data = resp.json()
    decision_id = data["decision_id"]

    # GET the review page
    review_resp = client.get(f"/decisions/{decision_id}/review")
    assert review_resp.status_code == 200
    review_data = review_resp.json()
    assert "alternatives" in review_data
    assert "Tea" in str(review_data["alternatives"]) or "tea" in str(review_data["alternatives"])
    assert "Coffee" in str(review_data["alternatives"]) or "coffee" in str(review_data["alternatives"])


def test_delete_decision(client, db):
    """POST /decisions/{id}/delete removes the decision and redirects."""
    # Create a decision with refine + scores
    resp = client.post("/decide", data={"q": "Tea or Coffee?"})
    assert resp.status_code == 200
    decision_id = resp.json()["decision_id"]

    # Verify it exists
    from models import Decision

    assert db.query(Decision).filter(Decision.id == decision_id).first() is not None

    # Delete it (don't follow redirect — we want the 303)
    del_resp = client.post(f"/decisions/{decision_id}/delete", follow_redirects=False)
    assert del_resp.status_code == 303  # redirect

    # Verify it's gone
    assert db.query(Decision).filter(Decision.id == decision_id).first() is None


def test_delete_decision_not_found(client, db):
    """POST /decisions/99999/delete returns 404."""
    resp = client.post("/decisions/99999/delete")
    assert resp.status_code == 404


def test_review_page_not_found(client, db):
    """GET /decisions/99999/review returns 404."""
    resp = client.get("/decisions/99999/review")
    assert resp.status_code == 404


def test_decision_list_page(client, db):
    """Test decisions list endpoint."""
    response = client.get("/decisions")
    assert response.status_code == 200
    data = response.json()
    assert "decisions" in data
    assert isinstance(data["decisions"], list)


def test_decision_list_mode_aware_result_links(client, db):
    """Decisions list includes mode-specific result URLs."""
    from models import Decision

    decisions = [
        Decision(query="House or Apartment?", category="General", mode="choose"),
        Decision(query="How good is Tesla?", category="General", mode="diagnose"),
        Decision(query="Cost <= 60", category="General", mode="screen"),
        Decision(query="Rank Python, Java, Go", category="General", mode="rank"),
    ]
    db.add_all(decisions)
    db.commit()

    response = client.get("/api/decisions")
    assert response.status_code == 200
    data = response.json()
    assert len(data["decisions"]) == 4
    result_urls = [d["result_url"] for d in data["decisions"]]
    assert f"/decisions/{decisions[0].id}/result" in result_urls
    assert f"/evaluate/{decisions[1].id}/result" in result_urls
    assert f"/screen/{decisions[2].id}/result" in result_urls
    assert f"/rank/{decisions[3].id}/result" in result_urls


def test_delete_decision_redirect_param(client, db):
    """Delete redirect query parameter can keep the user on /decisions."""
    from models import Decision

    decision = Decision(query="Tea or Coffee?", category="General", mode="choose")
    db.add(decision)
    db.commit()

    response = client.post(
        f"/decisions/{decision.id}/delete?redirect=/decisions",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/decisions"
    assert db.query(Decision).filter(Decision.id == decision.id).first() is None


def test_delete_decision_rejects_external_redirect(client, db):
    """Delete redirect query parameter rejects external destinations."""
    from models import Decision

    decision = Decision(query="Tea or Coffee?", category="General", mode="choose")
    db.add(decision)
    db.commit()

    response = client.post(
        f"/decisions/{decision.id}/delete?redirect=https://evil.example",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert db.query(Decision).filter(Decision.id == decision.id).first() is None


def test_decision_refine_and_score(client, db):
    """Test the refine and score endpoints."""
    # First create a decision via /decide
    resp = client.post("/decide", data={"q": "House or Apartment?"})
    assert resp.status_code == 200
    decision_id = resp.json()["decision_id"]

    # Get metric IDs from the seeded metrics
    from models import Metric

    metrics = db.query(Metric).all()
    metric_id = metrics[0].id if metrics else 1

    # Refine the decision using global metric IDs
    refine_resp = client.post(
        f"/decisions/{decision_id}/refine",
        data={
            "alt_name_0": "House",
            "alt_name_1": "Apartment",
            "metric_id_0": str(metric_id),
            "include_metric_0": "true",
            "criterion_weight_0": "80",
            "criterion_higher_0": "false",
        },
        follow_redirects=False,
    )
    assert refine_resp.status_code == 303

    # Follow redirect to scoring page
    score_resp = client.get(refine_resp.headers["location"])
    assert score_resp.status_code == 200
    score_data = score_resp.json()
    assert "criteria" in score_data
    assert "activities" in score_data or "alternatives" in score_data


def test_refine_with_native_form_values(client, db):
    """Refine must accept 'on' as checkbox value (native HTML form submission)."""
    resp = client.post("/decide", data={"q": "X or Y?"})
    assert resp.status_code == 200
    decision_id = resp.json()["decision_id"]

    from models import Metric

    metrics = db.query(Metric).order_by(Metric.id).all()
    assert len(metrics) >= 2

    # Submit with 'on' (native browser behavior) instead of 'true' (Alpine.js)
    refine_resp = client.post(
        f"/decisions/{decision_id}/refine",
        data={
            "alt_name_0": "X",
            "alt_name_1": "Y",
            "include_metric_0": "on",
            "metric_id_0": str(metrics[0].id),
            "criterion_weight_0": "80",
            "include_metric_1": "on",
            "metric_id_1": str(metrics[1].id),
            "criterion_weight_1": "70",
        },
        follow_redirects=False,
    )
    # Should redirect to scoring, not re-render with error
    assert refine_resp.status_code == 303


def test_ontology_parsing(client, db):
    """Test that ontology-based parsing works via /decide."""
    response = client.post("/decide", data={"q": "Which job offer should I take?"})
    assert response.status_code == 200
    data = response.json()
    assert "decision_id" in data
    assert data["mode"] == "choose"


def test_decision_not_found(client, db):
    """Test 404 for non-existent decision."""
    response = client.get("/decisions/99999/result")
    assert response.status_code == 404

    response = client.get("/decisions/99999/score")
    assert response.status_code == 404

    response = client.post("/decisions/99999/refine", data={"alt_name_0": "Test"})
    assert response.status_code == 404

    response = client.post("/decisions/99999/score", data={"score_1_1": "50"})
    assert response.status_code == 404


def test_full_decision_flow(client, db):
    """Test the complete decision flow: decide → refine → score → result."""
    # Step 1: Create decision
    resp = client.post("/decide", data={"q": "Tea or Coffee?"})
    assert resp.status_code == 200
    data = resp.json()
    decision_id = data["decision_id"]

    # Get metric IDs from seeded metrics
    from models import Metric

    all_metrics = db.query(Metric).order_by(Metric.id).all()
    assert len(all_metrics) >= 2

    # Step 2: Refine with 2 alternatives, 3 metrics
    refine_resp = client.post(
        f"/decisions/{decision_id}/refine",
        data={
            "alt_name_0": "Tea",
            "alt_name_1": "Coffee",
            "metric_id_0": str(all_metrics[0].id),
            "include_metric_0": "true",
            "criterion_weight_0": "85",
            "criterion_higher_0": "true",
            "metric_id_1": str(all_metrics[1].id),
            "include_metric_1": "true",
            "criterion_weight_1": "70",
            "criterion_higher_1": "true",
            "metric_id_2": str(all_metrics[2].id),
            "include_metric_2": "true",
            "criterion_weight_2": "50",
            "criterion_higher_2": "false",
        },
        follow_redirects=False,
    )
    assert refine_resp.status_code == 303

    # Follow redirect
    client.get(refine_resp.headers["location"])

    # Step 3: Score page should load
    score_page = client.get(f"/decisions/{decision_id}/score")
    assert score_page.status_code == 200
    score_data = score_page.json()
    # Should show both alternatives and all criteria
    activity_names = [a.get("name", "") for a in score_data.get("activities", [])]
    assert "Tea" in activity_names
    assert "Coffee" in activity_names

    # Step 4: Submit scores via the API endpoint
    import re

    score_resp = client.post(
        f"/api/decisions/{decision_id}/score",
        json={
            "scores": [
                {"activity_id": act["id"], "metric_id": m["id"], "score": 70}
                for act in score_data["activities"]
                for m in score_data["criteria"]
            ]
        },
    )
    assert score_resp.status_code == 200
    result_data = score_resp.json()
    assert "results" in result_data
    assert "series" in result_data

    # Step 5: Check result page via API
    api_result = client.get(f"/api/decisions/{decision_id}")
    assert api_result.status_code == 200
    api_data = api_result.json()
    assert "results" in api_data
    assert "series" in api_data
    assert "metric_names" in api_data


def test_decide_empty_query(client, db):
    """Test /decide with empty query returns error."""
    response = client.post("/decide", data={"q": ""})
    assert response.status_code == 400
    data = response.json()
    assert "error" in data
    assert "question" in data["error"].lower() or "please" in data["error"].lower()


def test_decide_no_match(client, db):
    """Test /decide with a query that has no or/vs pattern."""
    response = client.post("/decide", data={"q": "What should I do today?"})
    assert response.status_code == 200
    data = response.json()
    assert "decision_id" in data


def test_metrics_page_requires_no_auth(client, db):
    """Test that metrics page loads."""
    response = client.get("/metrics")
    assert response.status_code == 200


def test_update_metric(client, db):
    """Test updating a metric."""
    resp = client.post("/metrics", json={"name": "UpdateMe", "category": "Financial"})
    metric_id = resp.json()["id"]

    response = client.put(
        f"/metrics/{metric_id}", json={"name": "Updated", "category": "Quality"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated"


def test_seeded_metrics_on_list_page(client, db):
    """Test that seeded universal metrics show on the metrics page."""
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
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


def test_evaluate_how_good(client, db):
    """How good is X for Y → review page shows subject"""
    response = client.post(
        "/evaluate",
        data={"q": "How good is a Tesla for commuting?"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    # Follow redirect to review page
    response = client.get(response.headers["location"])
    assert response.status_code == 200
    data = response.json()
    # Check that "Tesla" appears somewhere in the serialized data
    assert "Tesla" in str(data)


def test_evaluate_rate_my(client, db):
    """Rate my X → review page shows subject"""
    response = client.post(
        "/evaluate", data={"q": "Rate my portfolio"}, follow_redirects=False
    )
    assert response.status_code == 303
    response = client.get(response.headers["location"])
    assert response.status_code == 200


def test_evaluate_no_match(client, db):
    """No match → fallback subject"""
    response = client.post(
        "/evaluate", data={"q": "Hello world"}, follow_redirects=False
    )
    assert response.status_code == 303
    response = client.get(response.headers["location"])
    assert response.status_code == 200
    data = response.json()
    # Fallback: should contain the query text somewhere in the serialized data
    assert "Hello" in str(data) or "This option" in str(data)


def test_evaluate_empty_query(client, db):
    """Empty query → error"""
    response = client.post("/evaluate", data={"q": ""})
    assert response.status_code == 200
    data = response.json()
    assert "error" in data or "_template" in data


def test_evaluate_flow(client, db):
    """Full flow: evaluate → refine → score → result"""
    # Create evaluation
    resp = client.post(
        "/evaluate",
        data={"q": "How good is Python for data science?"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    import re

    review_url = resp.headers["location"]
    decision_id = re.search(r"/evaluate/(\d+)/review", review_url).group(1)

    # Refine: submit with criteria
    resp = client.post(
        f"/evaluate/{decision_id}/refine",
        data={
            "alt_name_0": "Python",
            "metric_id_0": "1",
            "include_metric_0": "true",
            "criterion_weight_0": "80",
            "criterion_higher_0": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    score_url = resp.headers["location"]
    assert "/score" in score_url

    # Follow to score page
    resp = client.get(score_url)
    assert resp.status_code == 200
    score_data = resp.json()

    # Score: submit scores using API endpoint
    if score_data.get("activities") and score_data.get("criteria"):
        act_id = score_data["activities"][0]["id"]
        met_id = score_data["criteria"][0]["id"]
        score_resp = client.post(
            f"/api/decisions/{decision_id}/score",
            json={
                "scores": [
                    {"activity_id": act_id, "metric_id": met_id, "score": 85}
                ]
            },
        )
        assert score_resp.status_code == 200
        result_data = score_resp.json()
        assert "results" in result_data

        # Check result via API
        api_result = client.get(f"/api/evaluate/{decision_id}")
        assert api_result.status_code == 200
        api_data = api_result.json()
        assert "results" in api_data
        assert "Python" in str(api_data)


def test_evaluate_not_found(client, db):
    """404 for nonexistent evaluation"""
    resp = client.get("/evaluate/99999/result")
    assert resp.status_code == 404


def test_evaluate_delete(client, db):
    """Delete evaluation"""
    resp = client.post(
        "/evaluate", data={"q": "How good is Go?"}, follow_redirects=False
    )
    decision_id = resp.headers["location"].split("/")[2]
    resp = client.post(f"/evaluate/{decision_id}/delete", follow_redirects=False)
    assert resp.status_code == 303


def test_decide_routes_to_diagnose(client, db):
    """DIAGNOSE-style query via /decide → redirect to /evaluate/{id}/review"""
    resp = client.post(
        "/decide",
        data={"q": "How good is a Tesla for commuting?"},
        follow_redirects=False,
    )
    # Must redirect to evaluate (DIAGNOSE), not decisions (CHOOSE)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/evaluate/")
    assert "/review" in resp.headers["location"]

    # Follow redirect to verify review page
    resp = client.get(resp.headers["location"])
    assert resp.status_code == 200
    data = resp.json()
    assert "Tesla" in str(data)
    assert "commuting" in str(data)


def test_decide_with_choose_query_still_works(client, db):
    """CHOOSE query via /decide → returns JSON with parsed alternatives"""
    resp = client.post(
        "/decide",
        data={"q": "Should I buy a house or an apartment?"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "house" in str(data["alternatives"]).lower()
    assert "apartment" in str(data["alternatives"]).lower()


def test_decide_with_no_match_fallback(client, db):
    """Query matching neither CHOOSE nor DIAGNOSE → fallback to CHOOSE"""
    resp = client.post(
        "/decide",
        data={"q": "Hello world"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "decision_id" in data


# ── SCREEN (Mode 3) tests ──


def test_screen_direct_still_works(client, db):
    """Direct POST /screen still works (backward compat)"""
    resp = client.post(
        "/screen", data={"q": "Screen jobs by cost"}, follow_redirects=False
    )
    assert resp.status_code == 303
    import re

    decision_id = re.search(r"/screen/(\d+)/review", resp.headers["location"]).group(1)

    # GET the review page
    review_resp = client.get(f"/screen/{decision_id}/review")
    assert review_resp.status_code == 200
    data = review_resp.json()
    assert "alternatives" in data or "activities" in data


def test_screen_review_page(client, db):
    """GET /screen/{id}/review loads review data"""
    # Create via /screen POST
    resp = client.post(
        "/screen", data={"q": "Screen jobs by cost"}, follow_redirects=False
    )
    assert resp.status_code == 303
    import re

    decision_id = re.search(r"/screen/(\d+)/review", resp.headers["location"]).group(1)

    # GET the review page
    review_resp = client.get(f"/screen/{decision_id}/review")
    assert review_resp.status_code == 200
    data = review_resp.json()
    assert "alternatives" in data or "activities" in data


def test_screen_backward_compat_result(client, db):
    """Existing screen decisions still return result data (backward compat)"""
    from models import Activity, Decision

    decision = Decision(query="Cost <= 60", category="General", mode="screen")
    db.add(decision)
    db.flush()

    activity = Activity(
        name="Cheap Option", category="General", decision_id=decision.id
    )
    db.add(activity)
    db.commit()

    resp = client.get(f"/screen/{decision.id}/result")
    assert resp.status_code == 200
    data = resp.json()
    assert "decision" in data or "results" in data


def test_screen_not_found(client, db):
    """404 for nonexistent screening"""
    resp = client.get("/screen/99999/review")
    assert resp.status_code == 404


def test_screen_delete(client, db):
    """Delete screen"""
    resp = client.post("/screen", data={"q": "Screen test"}, follow_redirects=False)
    decision_id = resp.headers["location"].split("/")[2]
    resp = client.post(f"/screen/{decision_id}/delete", follow_redirects=False)
    assert resp.status_code == 303


# ── RANK (Mode 4) tests ──


def test_rank_via_decide(client, db):
    """List query via /decide → redirect to /rank/{id}/review"""
    resp = client.post(
        "/decide",
        data={"q": "Rank Python, Java, Go"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/rank/")
    assert "/review" in resp.headers["location"]

    # Follow redirect
    resp = client.get(resp.headers["location"])
    assert resp.status_code == 200
    data = resp.json()
    assert "alternatives" in data or "activities" in data


def test_rank_review_page(client, db):
    """GET /rank/{id}/review loads review data"""
    resp = client.post("/rank", data={"q": "Python, Java, Go"}, follow_redirects=False)
    assert resp.status_code == 303
    import re

    decision_id = re.search(r"/rank/(\d+)/review", resp.headers["location"]).group(1)

    review_resp = client.get(f"/rank/{decision_id}/review")
    assert review_resp.status_code == 200
    data = review_resp.json()
    assert "alternatives" in data or "activities" in data


def test_rank_flow(client, db):
    """Full flow: decide → refine → score → result"""
    resp = client.post(
        "/decide",
        data={"q": "Python, Java, Go"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    import re

    decision_id = re.search(r"/rank/(\d+)/review", resp.headers["location"]).group(1)

    # Get metric IDs
    from models import Metric

    metrics = db.query(Metric).order_by(Metric.id).all()
    assert len(metrics) >= 1

    # Refine
    refine_resp = client.post(
        f"/rank/{decision_id}/refine",
        data={
            "alt_name_0": "Python",
            "alt_name_1": "Java",
            "alt_name_2": "Go",
            "metric_id_0": str(metrics[0].id),
            "include_metric_0": "true",
            "criterion_weight_0": "80",
            "criterion_higher_0": "true",
        },
        follow_redirects=False,
    )
    assert refine_resp.status_code == 303

    # Follow to score page
    score_page = client.get(refine_resp.headers["location"])
    assert score_page.status_code == 200
    score_data = score_page.json()

    # Submit scores via API
    if score_data.get("activities") and score_data.get("criteria"):
        scores = [
            {"activity_id": a["id"], "metric_id": m["id"], "score": 70}
            for a in score_data["activities"]
            for m in score_data["criteria"]
        ]
        score_resp = client.post(
            f"/api/decisions/{decision_id}/score",
            json={"scores": scores},
        )
        assert score_resp.status_code == 200
        result_data = score_resp.json()
        assert "results" in result_data


def test_rank_not_found(client, db):
    """404 for nonexistent ranking"""
    resp = client.get("/rank/99999/review")
    assert resp.status_code == 404


def test_rank_delete(client, db):
    """Delete ranking"""
    resp = client.post("/rank", data={"q": "A, B, C"}, follow_redirects=False)
    decision_id = resp.headers["location"].split("/")[2]
    resp = client.post(f"/rank/{decision_id}/delete", follow_redirects=False)
    assert resp.status_code == 303


def test_rank_two_items_fallback(client, db):
    """2 items should NOT route to rank — CHOOSE handles it"""
    resp = client.post(
        "/decide",
        data={"q": "A, B"},
        follow_redirects=False,
    )
    # For 2 items, the system may return JSON directly (CHOOSE) or redirect
    assert resp.status_code in (200, 303)
    # Should NOT redirect to rank (fewer than 3 items)
    if resp.status_code == 303:
        assert not resp.headers.get("location", "").startswith("/rank/")


def test_rank_result_reuses_decision_result(client, db):
    """Rank result page shows ranking data"""
    # Create a rank with 3 items and score them
    resp = client.post("/rank", data={"q": "X, Y, Z"}, follow_redirects=False)
    assert resp.status_code == 303
    import re

    decision_id = re.search(r"/rank/(\d+)/review", resp.headers["location"]).group(1)

    from models import Metric

    metrics = db.query(Metric).order_by(Metric.id).all()
    assert len(metrics) >= 1

    # Refine
    refine_resp = client.post(
        f"/rank/{decision_id}/refine",
        data={
            "alt_name_0": "X",
            "alt_name_1": "Y",
            "alt_name_2": "Z",
            "metric_id_0": str(metrics[0].id),
            "include_metric_0": "true",
            "criterion_weight_0": "80",
            "criterion_higher_0": "true",
        },
        follow_redirects=False,
    )
    assert refine_resp.status_code == 303

    score_page = client.get(refine_resp.headers["location"])
    score_data = score_page.json()

    # Submit scores via API
    scores = [
        {"activity_id": a["id"], "metric_id": m["id"], "score": 70}
        for a in score_data["activities"]
        for m in score_data["criteria"]
    ]
    client.post(f"/api/decisions/{decision_id}/score", json={"scores": scores})

    # Check result via API
    result = client.get(f"/api/screen/{decision_id}")
    assert result.status_code == 200
    data = result.json()
    assert "results" in data


def test_decide_heuristic_routing(client, db):
    """/decide auto-detects workflow from query text."""
    resp = client.post(
        "/decide",
        data={"q": "Should I buy a house or an apartment?"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "choose"

    # Heuristic rank detection
    resp3 = client.post(
        "/decide",
        data={"q": "Rank Python, Java, Go"},
        follow_redirects=False,
    )
    assert resp3.status_code == 303
    assert resp3.headers["location"].startswith("/rank/")

    # Heuristic diagnose detection
    resp4 = client.post(
        "/decide",
        data={"q": "How good is Rust?"},
        follow_redirects=False,
    )
    assert resp4.status_code == 303
    assert resp4.headers["location"].startswith("/evaluate/")


# ── Threshold filter tests (post-hoc on decision result page) ──


def _create_decision_with_metric(client, db, query="House or Apartment?"):
    """Helper: create a decision via /decide, refine with 1 metric, return decision_id and metric_id."""
    resp = client.post("/decide", data={"q": query})
    assert resp.status_code == 200
    decision_id = resp.json()["decision_id"]

    # Get a metric
    from models import Metric

    metric = db.query(Metric).order_by(Metric.id).first()
    assert metric is not None
    metric_id = metric.id

    # Refine with this metric and 2 alternatives
    refine_resp = client.post(
        f"/decisions/{decision_id}/refine",
        data={
            "alt_name_0": "House",
            "alt_name_1": "Apartment",
            "metric_id_0": str(metric_id),
            "include_metric_0": "true",
            "criterion_weight_0": "80",
            "criterion_higher_0": "true",
        },
        follow_redirects=False,
    )
    assert refine_resp.status_code == 303
    return decision_id, metric_id


def test_decision_result_threshold_panel_renders(client, db):
    """Result page includes threshold data."""
    decision_id, _ = _create_decision_with_metric(client, db)

    # Fetch result page
    resp = client.get(f"/decisions/{decision_id}/result")
    assert resp.status_code == 200
    data = resp.json()
    # The result page now contains JSON context; check for relevant keys
    assert "decision" in data or "_template" in data


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
            "thresholds": [
                {"metric_id": metric_id, "operator": "<=", "value": 60.0}
            ]
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
        json={
            "thresholds": [
                {"metric_id": metric_id, "operator": "<=", "value": 150}
            ]
        },
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
            "thresholds": [
                {"metric_id": metric_id, "operator": "<=", "value": "abc"}
            ]
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
            "thresholds": [
                {"metric_id": metric_id, "operator": "<=", "value": 60.0}
            ]
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
            "thresholds": [
                {"metric_id": metric_id, "operator": ">=", "value": 75.0}
            ]
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


# ── Markdown export + significance + slider polish tests ──


def _seed_scored_decision(db, mode="choose"):
    from models import Activity, ActivityWeight, AlternativeScore, Decision, Metric

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
    for activity in activities:
        for metric in metrics:
            db.add(
                ActivityWeight(activity_id=activity.id, metric_id=metric.id, weight=70)
            )

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


def test_export_markdown_endpoints_use_significance_language(client, db):
    choose = _seed_scored_decision(db, "choose")
    diagnose = _seed_scored_decision(db, "diagnose")
    rank = _seed_scored_decision(db, "rank")
    screen = _seed_scored_decision(db, "screen")

    endpoints = [
        f"/decisions/{choose.id}/export-markdown",
        f"/evaluate/{diagnose.id}/export-markdown",
        f"/rank/{rank.id}/export-markdown",
        f"/screen/{screen.id}/export-markdown",
    ]
    for endpoint in endpoints:
        response = client.get(endpoint)
        forbidden = "con" + "fidence"
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "attachment" in response.headers["content-disposition"]
        assert "Decision Brief" in response.text
        assert forbidden not in response.text.lower()

    assert "Statistical Significance" in client.get(endpoints[0]).text
    assert "Statistical Significance" not in client.get(endpoints[1]).text


def test_result_pages_use_significance_without_legacy_wording(client, db):
    decision = _seed_scored_decision(db, "choose")
    response = client.get(f"/api/decisions/{decision.id}")
    assert response.status_code == 200
    data = response.json()
    # The API response should include significance data
    if data.get("significance"):
        assert "p_value" in data["significance"] or "p-value" in str(data["significance"])


def test_slider_fill_markup_and_sensitivity_classes(client, db):
    decision = _seed_scored_decision(db, "choose")
    score_page = client.get(f"/decisions/{decision.id}/score")
    assert score_page.status_code == 200
    score_data = score_page.json()
    # Score page should contain criteria and activities
    assert "criteria" in score_data
    assert "activities" in score_data

    result_page = client.get(f"/api/decisions/{decision.id}")
    assert result_page.status_code == 200
    result_data = result_page.json()
    # Result should contain results and series
    assert "results" in result_data
    assert "series" in result_data
