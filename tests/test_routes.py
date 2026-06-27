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
from routers import activities, metrics, candidates, analysis
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

    test_app.include_router(activities.router)
    test_app.include_router(metrics.router)
    test_app.include_router(candidates.router)
    test_app.include_router(analysis.router)
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

        # Create the Decision record
        decision = Decision(query=query, category=category)
        db.add(decision)
        db.flush()

        # Create Metric records for each criterion
        metric_objects = {}
        for crit in criteria_list:
            metric = Metric(
                name=crit["name"],
                category=category,
                description=crit["description"],
                higher_is_better=crit["higher_is_better"],
                decision_id=decision.id,
            )
            db.add(metric)
            db.flush()
            metric_objects[crit["name"]] = metric

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
                metric = metric_objects[crit["name"]]
                aw = ActivityWeight(
                    activity_id=activity.id,
                    metric_id=metric.id,
                    weight=crit["default_weight"],
                )
                db.add(aw)

        db.commit()

        return templates.TemplateResponse(
            request,
            "decision_review.html",
            {
                "request": request,
                "decision": decision,
                "alternatives": alternatives,
                "criteria": criteria_list,
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


def test_activities_page(client, db):
    """Test activities page redirects to dashboard."""
    response = client.get("/activities", follow_redirects=False)
    assert response.status_code == 302


def test_create_activity(client, db):
    """Test creating an activity via API."""
    response = client.post("/activities", json={
        "name": "Test Sport",
        "category": "Sport",
        "description": "A test activity"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Sport"
    assert "id" in data


def test_create_duplicate_activity(client, db):
    """Test that duplicate activity name returns 400."""
    client.post("/activities", json={"name": "Unique", "category": "Sport"})
    response = client.post("/activities", json={"name": "Unique", "category": "Sport"})
    assert response.status_code == 400


def test_get_activity_detail(client, db):
    """Test activity detail page loads."""
    resp = client.post("/activities", json={"name": "Detail Test", "category": "Strategy"})
    activity_id = resp.json()["id"]

    response = client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert "Detail Test" in response.text


def test_get_missing_activity(client, db):
    """Test that missing activity returns 404."""
    response = client.get("/activities/999")
    assert response.status_code == 404


def test_update_activity(client, db):
    """Test updating an activity."""
    resp = client.post("/activities", json={"name": "Old Name", "category": "Fitness"})
    activity_id = resp.json()["id"]

    response = client.put(f"/activities/{activity_id}", json={"name": "New Name"})
    assert response.status_code == 200

    # Verify via detail page
    response = client.get(f"/activities/{activity_id}")
    assert "New Name" in response.text


def test_create_metric(client, db):
    """Test creating a metric via API."""
    response = client.post("/metrics", json={
        "name": "Test Metric",
        "category": "Physical",
        "unit": "cm"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Metric"
    assert data["category"] == "Physical"


def test_list_metrics(client, db):
    """Test metrics page loads."""
    response = client.get("/metrics")
    assert response.status_code == 200


def test_delete_metric(client, db):
    """Test deleting a metric."""
    resp = client.post("/metrics", json={"name": "Delete Me", "category": "Physical"})
    metric_id = resp.json()["id"]

    response = client.delete(f"/metrics/{metric_id}")
    assert response.status_code == 200


def test_add_sub_metric(client, db):
    """Test adding a sub-metric."""
    resp = client.post("/metrics", json={"name": "Parent", "category": "Physical"})
    parent_id = resp.json()["id"]

    response = client.post(f"/metrics/{parent_id}/sub", json={
        "name": "Child",
        "category": "Physical"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["parent_id"] == parent_id


def test_add_sub_metric_to_sub_metric_fails(client, db):
    """Test that adding sub-metric to a sub-metric returns 400."""
    resp = client.post("/metrics", json={"name": "Parent", "category": "Physical"})
    parent_id = resp.json()["id"]

    resp = client.post(f"/metrics/{parent_id}/sub", json={"name": "Child", "category": "Physical"})
    child_id = resp.json()["id"]

    response = client.post(f"/metrics/{child_id}/sub", json={"name": "Grandchild", "category": "Physical"})
    assert response.status_code == 400


def test_create_candidate(client, db):
    """Test creating a candidate with scores."""
    resp = client.post("/metrics", json={"name": "Height", "category": "Physical"})
    metric_id = resp.json()["id"]

    response = client.post("/candidates", json={
        "name": "Test Candidate",
        "scores": {str(metric_id): 85.0}
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Candidate"


def test_new_candidate_form(client, db):
    """Test candidate form page loads."""
    response = client.get("/candidates/new")
    assert response.status_code == 200


def test_random_candidate(client, db):
    """Test random candidate generation."""
    client.post("/metrics", json={"name": "Speed", "category": "Physical"})

    response = client.get("/candidates/random", follow_redirects=False)
    assert response.status_code == 303


def test_upsert_weights(client, db):
    """Test upserting weights for an activity."""
    resp = client.post("/metrics", json={"name": "Weight Metric", "category": "Physical"})
    metric_id = resp.json()["id"]

    resp = client.post("/activities", json={"name": "Weight Activity", "category": "Sport"})
    activity_id = resp.json()["id"]

    response = client.post(f"/activities/{activity_id}/weights", json={
        "weights": [{"metric_id": metric_id, "weight": 75.0}]
    })
    assert response.status_code == 200


def test_monte_carlo_page(client, db):
    """Test Monte Carlo page loads."""
    resp = client.post("/activities", json={"name": "MC Activity", "category": "Sport"})
    activity_id = resp.json()["id"]

    response = client.get(f"/activities/{activity_id}/mc")
    assert response.status_code == 200


def test_what_if(client, db):
    """Test what-if analysis endpoint."""
    resp = client.post("/metrics", json={"name": "WhatIf Metric", "category": "Physical"})
    metric_id = resp.json()["id"]

    resp = client.post("/candidates", json={
        "name": "WhatIf",
        "scores": {str(metric_id): 50.0}
    })
    candidate_id = resp.json()["id"]

    response = client.get(f"/analysis/what-if?candidate_id={candidate_id}&metric_id={metric_id}&new_score=90")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data


def test_compare_candidates(client, db):
    """Test candidate comparison."""
    resp = client.post("/metrics", json={"name": "Compare Metric", "category": "Physical"})
    metric_id = resp.json()["id"]

    resp1 = client.post("/candidates", json={
        "name": "Compare A",
        "scores": {str(metric_id): 80.0}
    })
    resp2 = client.post("/candidates", json={
        "name": "Compare B",
        "scores": {str(metric_id): 60.0}
    })

    response = client.post("/candidates/compare", json={
        "candidate_ids": [resp1.json()["id"], resp2.json()["id"]]
    })
    assert response.status_code == 200


# ── New decision flow tests ──

def test_decide_flow_parsed(client, db):
    """Test the full decide flow with a parsable question."""
    response = client.post("/decide", data={"q": "Should I buy a house or an apartment?"})
    assert response.status_code == 200
    # Should show the review page
    assert "Decision Review" in response.text
    assert "house" in response.text.lower() or "House" in response.text
    assert "apartment" in response.text.lower() or "Apartment" in response.text


def test_decision_list_page(client, db):
    """Test decisions list page."""
    response = client.get("/decisions")
    assert response.status_code == 200


def test_decision_refine_and_score(client, db):
    """Test the refine and score endpoints."""
    # First create a decision via /decide
    resp = client.post("/decide", data={"q": "House or Apartment?"})
    assert resp.status_code == 200

    # Extract decision ID from the response - look for it in form action
    import re
    match = re.search(r'/decisions/(\d+)/refine', resp.text)
    assert match, "Could not find decision ID in response"
    decision_id = int(match.group(1))

    # Refine the decision
    refine_resp = client.post(
        f"/decisions/{decision_id}/refine",
        data={
            "alt_name_0": "House",
            "alt_name_1": "Apartment",
            "criterion_name_0": "Cost",
            "criterion_desc_0": "How much it costs",
            "criterion_weight_0": "80",
            "criterion_higher_0": "false",
            "criterion_name_1": "Location",
            "criterion_desc_1": "Where it is",
            "criterion_weight_1": "70",
            "criterion_higher_1": "true",
            "criterion_name_2": "Space",
            "criterion_desc_2": "Size of the place",
            "criterion_weight_2": "60",
            "criterion_higher_2": "true",
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

    # Step 2: Refine with 2 alternatives, 3 criteria
    refine_resp = client.post(
        f"/decisions/{decision_id}/refine",
        data={
            "alt_name_0": "Tea",
            "alt_name_1": "Coffee",
            "criterion_name_0": "Taste",
            "criterion_desc_0": "Flavor profile",
            "criterion_weight_0": "85",
            "criterion_higher_0": "true",
            "criterion_name_1": "Caffeine",
            "criterion_desc_1": "Energy boost",
            "criterion_weight_1": "70",
            "criterion_higher_1": "true",
            "criterion_name_2": "Cost",
            "criterion_desc_2": "Price per serving",
            "criterion_weight_2": "50",
            "criterion_higher_2": "false",
        },
    )
    assert refine_resp.status_code in (200, 303)

    # Step 3: Score page should load
    score_page = client.get(f"/decisions/{decision_id}/score")
    assert score_page.status_code == 200
    assert "Score Your Alternatives" in score_page.text
    # Should show both alternatives and all criteria
    for s in ["Tea", "Coffee", "Taste", "Caffeine", "Cost"]:
        assert s in score_page.text

    # Step 4: Submit scores
    # Extract the field names from the score page
    score_fields = re.findall(r'name="(score_\d+_\d+)"', score_page.text)
    assert len(score_fields) == 6, f"Expected 6 score fields, got {score_fields}: {len(score_fields)}"

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
    # Should show percentages
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
    # Should still show review page with generic alternatives
    assert "Decision Review" in response.text or "decision" in response.text.lower()


def test_metrics_page_requires_no_auth(client, db):
    """Test that metrics page loads."""
    response = client.get("/metrics")
    assert response.status_code == 200


def test_suggest_metric(client, db):
    """Test metric suggestion endpoint."""
    resp = client.post("/metrics", json={"name": "SuggestTest", "category": "Physical"})
    metric_id = resp.json()["id"]

    response = client.get(f"/metrics/{metric_id}/suggest")
    assert response.status_code == 200


def test_update_metric(client, db):
    """Test updating a metric."""
    resp = client.post("/metrics", json={"name": "UpdateMe", "category": "Physical"})
    metric_id = resp.json()["id"]

    response = client.put(f"/metrics/{metric_id}", json={
        "name": "Updated",
        "category": "Mental"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated"


def test_delete_candidate(client, db):
    """Test deleting a candidate."""
    resp = client.post("/metrics", json={"name": "DelMetric", "category": "Physical"})
    metric_id = resp.json()["id"]

    resp = client.post("/candidates", json={
        "name": "DeleteMe",
        "scores": {str(metric_id): 50.0}
    })
    candidate_id = resp.json()["id"]

    response = client.delete(f"/candidates/{candidate_id}")
    assert response.status_code == 200


def test_candidate_detail(client, db):
    """Test candidate detail page."""
    resp = client.post("/metrics", json={"name": "CDMetric", "category": "Physical"})
    metric_id = resp.json()["id"]

    resp = client.post("/candidates", json={
        "name": "DetailCheck",
        "scores": {str(metric_id): 75.0}
    })
    candidate_id = resp.json()["id"]

    response = client.get(f"/candidates/{candidate_id}")
    assert response.status_code == 200


def test_candidate_list(client, db):
    """Test candidate list loads."""
    response = client.get("/candidates")
    assert response.status_code == 200
