"""Tests for FastAPI routes using TestClient.

Uses a per-function temporary SQLite database file to avoid issues
with in-memory databases having separate connection pools.
"""

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from database import Base, get_db
from routers import metrics
from routers.decisions import router as decisions_router

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
    """Create a TestClient with all routes but no lifespan."""
    test_app = FastAPI(title="MetricMatch Test")

    test_app.include_router(metrics.router)
    test_app.include_router(decisions_router)

    # Add the main app routes (index + decide)
    from fastapi.responses import HTMLResponse
    from fastapi.templating import Jinja2Templates
    from fastapi import Request, Depends
    templates = Jinja2Templates(directory="templates")

    @test_app.get("/", response_class=HTMLResponse)
    def test_index(request: Request, db: Session = Depends(get_db)):
        from models import Decision
        decisions = db.query(Decision).order_by(Decision.created_at.desc()).all()
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "decisions": decisions, "active_page": "home"},
        )

    @test_app.post("/decide")
    async def test_decide(request: Request, db: Session = Depends(get_db)):
        from models import Activity, ActivityWeight, Decision, Metric
        from services.parser import parse_question

        form = await request.form()
        query = form.get("q", "").strip()

        if not query:
            decisions = db.query(Decision).order_by(Decision.created_at.desc()).all()
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "request": request,
                    "decisions": decisions,
                    "query": query,
                    "error": "Please enter a question.",
                    "active_page": "home",
                },
            )

        parsed = parse_question(query)
        alternatives = parsed["alternatives"]
        criteria_list = parsed["criteria"]
        category = parsed["category"]
        is_parsed = parsed["parsed"]

        # Get all global metrics
        all_metrics = db.query(Metric).all()
        metric_map = {m.name: m for m in all_metrics}

        # Create the Decision record
        decision = Decision(query=query, category=category)
        db.add(decision)
        db.flush()

        # Create Activity records for each alternative
        for alt_name in alternatives:
            activity = Activity(
                name=alt_name,
                category=category,
                decision_id=decision.id,
            )
            db.add(activity)
            db.flush()

            # Create ActivityWeight records
            for crit in criteria_list:
                metric = metric_map.get(crit["name"])
                if metric:
                    aw = ActivityWeight(
                        activity_id=activity.id,
                        metric_id=metric.id,
                        weight=crit["default_weight"],
                    )
                    db.add(aw)

        db.commit()

        # Re-fetch all metrics for the template
        all_metrics = db.query(Metric).order_by(Metric.category, Metric.name).all()

        return templates.TemplateResponse(
            request,
            "decision_review.html",
            {
                "request": request,
                "decision": decision,
                "alternatives": alternatives,
                "criteria": criteria_list,
                "all_metrics": all_metrics,
                "category": category,
                "parsed": is_parsed,
                "active_page": "decisions",
            },
        )

    # Override the get_db dependency in all routers
    test_app.dependency_overrides[get_db] = _get_test_db

    with TestClient(test_app) as c:
        yield c


def test_index_page(client, db):
    """Test index page loads."""
    response = client.get("/")
    assert response.status_code == 200
    assert "What's your decision today?" in response.text


def test_create_metric(client, db):
    """Test creating a metric via API."""
    response = client.post("/metrics", json={
        "name": "Test Metric",
        "category": "Financial",
        "unit": "cm"
    })
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

    response = client.post(f"/metrics/{parent_id}/sub", json={
        "name": "Child",
        "category": "Financial"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["parent_id"] == parent_id


def test_add_sub_metric_to_sub_metric_fails(client, db):
    """Test that adding sub-metric to a sub-metric returns 400."""
    resp = client.post("/metrics", json={"name": "Parent", "category": "Financial"})
    parent_id = resp.json()["id"]

    resp = client.post(f"/metrics/{parent_id}/sub", json={"name": "Child", "category": "Financial"})
    child_id = resp.json()["id"]

    response = client.post(f"/metrics/{child_id}/sub", json={"name": "Grandchild", "category": "Financial"})
    assert response.status_code == 400


# ── Decision flow tests ──

def test_decide_flow_parsed(client, db):
    """Test the full decide flow with a parsable question."""
    response = client.post("/decide", data={"q": "Should I buy a house or an apartment?"})
    assert response.status_code == 200
    # Should show the review page
    assert "Decision Review" in response.text
    assert "house" in response.text.lower() or "House" in response.text
    assert "apartment" in response.text.lower() or "Apartment" in response.text


def test_decide_flow_with_do_verb(client, db):
    """'should I do X or Y' correctly extracts Aikido and Football."""
    response = client.post("/decide", data={"q": "should I do aikido or football"})
    assert response.status_code == 200
    assert "Decision Review" in response.text
    assert "Aikido" in response.text or "aikido" in response.text
    assert "Football" in response.text or "football" in response.text


def test_review_page_get(client, db):
    """GET /decisions/{id}/review returns the review page."""
    # Create a decision first
    resp = client.post("/decide", data={"q": "Tea or Coffee?"})
    assert resp.status_code == 200
    import re
    match = re.search(r'/decisions/(\d+)/refine', resp.text)
    assert match
    decision_id = int(match.group(1))

    # GET the review page
    review_resp = client.get(f"/decisions/{decision_id}/review")
    assert review_resp.status_code == 200
    assert "Decision Review" in review_resp.text
    assert "Tea" in review_resp.text or "tea" in review_resp.text
    assert "Coffee" in review_resp.text or "coffee" in review_resp.text


def test_delete_decision(client, db):
    """POST /decisions/{id}/delete removes the decision and redirects."""
    # Create a decision with refine + scores
    resp = client.post("/decide", data={"q": "Tea or Coffee?"})
    assert resp.status_code == 200
    import re
    match = re.search(r'/decisions/(\d+)/refine', resp.text)
    assert match
    decision_id = int(match.group(1))

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
    """Test decisions list page."""
    response = client.get("/decisions")
    assert response.status_code == 200


def test_decision_refine_and_score(client, db):
    """Test the refine and score endpoints."""
    # First create a decision via /decide
    resp = client.post("/decide", data={"q": "House or Apartment?"})
    assert resp.status_code == 200

    # Extract decision ID from the response
    import re
    match = re.search(r'/decisions/(\d+)/refine', resp.text)
    assert match, "Could not find decision ID in response"
    decision_id = int(match.group(1))

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
    assert refine_resp.status_code in (200, 303)

    # Follow redirect if needed
    if refine_resp.status_code == 303:
        score_resp = client.get(refine_resp.headers["location"])
    else:
        score_resp = refine_resp
    assert score_resp.status_code == 200
    assert "Score Your Alternatives" in score_resp.text or "Rate each alternative" in score_resp.text


def test_refine_with_native_form_values(client, db):
    """Refine must accept 'on' as checkbox value (native HTML form submission)."""
    resp = client.post("/decide", data={"q": "X or Y?"})
    assert resp.status_code == 200
    import re
    match = re.search(r'/decisions/(\d+)/refine', resp.text)
    assert match
    decision_id = int(match.group(1))

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
    assert refine_resp.status_code in (200, 303), f"Expected redirect, got {refine_resp.status_code}"


def test_ontology_parsing(client, db):
    """Test that ontology-based parsing works via /decide."""
    response = client.post("/decide", data={"q": "Which job offer should I take?"})
    assert response.status_code == 200
    assert "Decision Review" in response.text


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
    assert "Decision Review" in resp.text

    import re
    match = re.search(r'/decisions/(\d+)/refine', resp.text)
    assert match, "No decision ID in /decide response"
    decision_id = int(match.group(1))

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
    )
    assert refine_resp.status_code in (200, 303)

    # Follow redirect
    if refine_resp.status_code == 303:
        client.get(refine_resp.headers["location"])

    # Step 3: Score page should load
    score_page = client.get(f"/decisions/{decision_id}/score")
    assert score_page.status_code == 200
    assert "Score Your Alternatives" in score_page.text
    # Should show both alternatives and all criteria
    for s in ["Tea", "Coffee"]:
        assert s in score_page.text
    for m in all_metrics[:3]:
        assert m.name in score_page.text

    # Step 4: Submit scores
    score_fields = re.findall(r'name="(score_\d+_\d+)"', score_page.text)
    assert len(score_fields) == 6, f"Expected 6 score fields, got {len(score_fields)}"

    score_data = {}
    for field in score_fields:
        score_data[field] = "70"

    score_resp = client.post(
        f"/decisions/{decision_id}/score",
        data=score_data,
    )
    assert score_resp.status_code == 200
    assert "Results" in score_resp.text

    # Step 5: Check result page directly
    result_page = client.get(f"/decisions/{decision_id}/result")
    assert result_page.status_code == 200
    assert "Results" in result_page.text
    assert "Ranking" in result_page.text
    assert "Detailed Scores" in result_page.text
    assert "%" in result_page.text


def test_decide_empty_query(client, db):
    """Test /decide with empty query returns error message."""
    response = client.post("/decide", data={"q": ""})
    assert response.status_code == 200
    assert "question" in response.text.lower() or "please" in response.text.lower()


def test_decide_no_match(client, db):
    """Test /decide with a query that has no or/vs pattern."""
    response = client.post("/decide", data={"q": "What should I do today?"})
    assert response.status_code == 200
    assert "Decision Review" in response.text or "decision" in response.text.lower()


def test_metrics_page_requires_no_auth(client, db):
    """Test that metrics page loads."""
    response = client.get("/metrics")
    assert response.status_code == 200


def test_update_metric(client, db):
    """Test updating a metric."""
    resp = client.post("/metrics", json={"name": "UpdateMe", "category": "Financial"})
    metric_id = resp.json()["id"]

    response = client.put(f"/metrics/{metric_id}", json={
        "name": "Updated",
        "category": "Quality"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated"


def test_seeded_metrics_on_list_page(client, db):
    """Test that seeded universal metrics show on the metrics page."""
    response = client.get("/metrics")
    assert response.status_code == 200
    # Should show dimension names
    for dim_name in ["Financial", "Quality", "Time", "Risk", "Experience", "Convenience"]:
        assert dim_name in response.text
