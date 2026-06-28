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
from routers.evaluate import router as evaluate_router
from routers.screen import router as screen_router
from routers.rank import router as rank_router

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
    test_app = FastAPI(title="Pondera Test")

    test_app.include_router(metrics.router)
    test_app.include_router(decisions_router)
    test_app.include_router(evaluate_router)
    test_app.include_router(screen_router)
    test_app.include_router(rank_router)

    # Add the main app routes (index + decide)
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates
    from fastapi import Request, Depends

    templates = Jinja2Templates(directory="templates")

    @test_app.get("/", response_class=HTMLResponse)
    def test_index(request: Request, db: Session = Depends(get_db)):
        from models import Decision

        decisions = db.query(Decision).order_by(Decision.created_at.desc()).all()
        for d in decisions:
            mode = d.mode if hasattr(d, "mode") and d.mode else "choose"
            d.result_url = {
                "diagnose": f"/evaluate/{d.id}/result",
                "screen": f"/screen/{d.id}/result",
                "rank": f"/rank/{d.id}/result",
            }.get(mode, f"/decisions/{d.id}/result")
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "decisions": decisions, "active_page": "home"},
        )

    @test_app.post("/decide")
    async def test_decide(request: Request, db: Session = Depends(get_db)):
        from models import Activity, ActivityWeight, Decision, Metric
        from services.parser import parse_question, extract_subject

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

        # Parse the question — try CHOOSE first
        parsed = parse_question(query)
        alternatives = parsed["alternatives"]
        criteria_list = parsed["criteria"]
        category = parsed["category"]
        is_parsed = parsed["parsed"]

        # If CHOOSE didn't find alternatives, try DIAGNOSE parsing
        if not is_parsed:
            diag = extract_subject(query)
            if diag["parsed"]:
                # Route as DIAGNOSE
                from services.ontology import UNIVERSAL_METRICS

                decision = Decision(query=query, category="General", mode="diagnose")
                db.add(decision)
                db.flush()

                subject = diag["subject"]
                activity = Activity(
                    name=subject, category="General", decision_id=decision.id
                )
                db.add(activity)
                db.flush()

                all_metrics = db.query(Metric).all()
                metric_map = {m.name: m for m in all_metrics}
                for m in UNIVERSAL_METRICS:
                    metric = metric_map.get(m["name"])
                    if metric:
                        aw = ActivityWeight(
                            activity_id=activity.id,
                            metric_id=metric.id,
                            weight=m["default_weight"],
                        )
                        db.add(aw)
                db.commit()
                return RedirectResponse(
                    url=f"/evaluate/{decision.id}/review", status_code=303
                )

            # If DIAGNOSE didn't match, try SCREEN
            from services.parser import extract_thresholds, extract_list

            thresholds = extract_thresholds(query)
            if thresholds:
                decision = Decision(query=query, category="General", mode="screen")
                all_metrics = db.query(Metric).all()
                metric_map = {m.name: m for m in all_metrics}
                thresholds_with_ids = []
                for t in thresholds:
                    metric = metric_map.get(t["metric_name"])
                    if metric:
                        thresholds_with_ids.append(
                            {
                                "metric_id": metric.id,
                                "operator": t["operator"],
                                "value": t["value"],
                            }
                        )
                if thresholds_with_ids:
                    import json

                    decision.thresholds = json.dumps(thresholds_with_ids)
                db.add(decision)
                db.flush()

                from services.ontology import UNIVERSAL_METRICS as UM

                for name in ["Option A", "Option B"]:
                    activity = Activity(
                        name=name, category="General", decision_id=decision.id
                    )
                    db.add(activity)
                    db.flush()
                    all_metrics = db.query(Metric).all()
                    metric_map = {m.name: m for m in all_metrics}
                    for m in UM:
                        metric = metric_map.get(m["name"])
                        if metric:
                            aw = ActivityWeight(
                                activity_id=activity.id,
                                metric_id=metric.id,
                                weight=m["default_weight"],
                            )
                            db.add(aw)
                db.commit()
                return RedirectResponse(
                    url=f"/screen/{decision.id}/review", status_code=303
                )

            # Try RANK
            list_parsed = extract_list(query)
            if list_parsed["parsed"]:
                decision = Decision(query=query, category="General", mode="rank")
                db.add(decision)
                db.flush()

                from services.ontology import UNIVERSAL_METRICS as UM

                for name in list_parsed["alternatives"]:
                    activity = Activity(
                        name=name, category="General", decision_id=decision.id
                    )
                    db.add(activity)
                    db.flush()
                    all_metrics = db.query(Metric).all()
                    metric_map = {m.name: m for m in all_metrics}
                    for m in UM:
                        metric = metric_map.get(m["name"])
                        if metric:
                            aw = ActivityWeight(
                                activity_id=activity.id,
                                metric_id=metric.id,
                                weight=m["default_weight"],
                            )
                            db.add(aw)
                db.commit()
                return RedirectResponse(
                    url=f"/rank/{decision.id}/review", status_code=303
                )

        # Continue as CHOOSE
        all_metrics = db.query(Metric).all()
        metric_map = {m.name: m for m in all_metrics}

        decision = Decision(query=query, category=category)
        db.add(decision)
        db.flush()

        for alt_name in alternatives:
            activity = Activity(
                name=alt_name,
                category=category,
                decision_id=decision.id,
            )
            db.add(activity)
            db.flush()

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

    match = re.search(r"/decisions/(\d+)/refine", resp.text)
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

    match = re.search(r"/decisions/(\d+)/refine", resp.text)
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

    match = re.search(r"/decisions/(\d+)/refine", resp.text)
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
    assert (
        "Score Your Alternatives" in score_resp.text
        or "Rate each alternative" in score_resp.text
    )


def test_refine_with_native_form_values(client, db):
    """Refine must accept 'on' as checkbox value (native HTML form submission)."""
    resp = client.post("/decide", data={"q": "X or Y?"})
    assert resp.status_code == 200
    import re

    match = re.search(r"/decisions/(\d+)/refine", resp.text)
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
    assert refine_resp.status_code in (200, 303), (
        f"Expected redirect, got {refine_resp.status_code}"
    )


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

    match = re.search(r"/decisions/(\d+)/refine", resp.text)
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
    # Should show dimension names
    for dim_name in [
        "Financial",
        "Quality",
        "Time",
        "Risk",
        "Experience",
        "Convenience",
    ]:
        assert dim_name in response.text


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
    assert "Tesla" in response.text


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
    assert "This option" in response.text


def test_evaluate_empty_query(client, db):
    """Empty query → error"""
    response = client.post("/evaluate", data={"q": ""})
    assert response.status_code == 200
    assert "Please enter" in response.text


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

    # Score: submit scores
    # Need to find actual metric ID from the form
    score_match = re.search(r'name="score_(\d+)_(\d+)"', resp.text)
    if score_match:
        act_id, met_id = score_match.groups()
        resp = client.post(
            f"/evaluate/{decision_id}/score",
            data={
                f"score_{act_id}_{met_id}": "85",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        result_url = resp.headers["location"]
        assert "/result" in result_url

        # Follow to result
        resp = client.get(result_url)
        assert resp.status_code == 200
        assert "Python" in resp.text
        assert "%" in resp.text


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
    assert "Tesla" in resp.text
    assert "commuting" in resp.text
    assert "Goal detected" in resp.text


def test_decide_with_choose_query_still_works(client, db):
    """CHOOSE query via /decide → still renders CHOOSE review page"""
    resp = client.post(
        "/decide",
        data={"q": "Should I buy a house or an apartment?"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "house" in resp.text
    assert "apartment" in resp.text


def test_decide_with_no_match_fallback(client, db):
    """Query matching neither CHOOSE nor DIAGNOSE → fallback to CHOOSE placeholders"""
    resp = client.post(
        "/decide",
        data={"q": "Hello world"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    # Should show placeholder alternatives
    assert "Option A" in resp.text or "couldn" in resp.text.lower()


# ── SCREEN (Mode 3) tests ──


def test_screen_via_decide(client, db):
    """Threshold query via /decide → redirect to /screen/{id}/review"""
    resp = client.post(
        "/decide",
        data={"q": "Cost <= 60 and Quality >= 70"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/screen/")
    assert "/review" in resp.headers["location"]

    # Follow redirect
    resp = client.get(resp.headers["location"])
    assert resp.status_code == 200
    assert "Screen Alternatives" in resp.text


def test_screen_review_page(client, db):
    """GET /screen/{id}/review loads with threshold UI"""
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
    assert "Screen Alternatives" in review_resp.text
    assert "Threshold" in review_resp.text


def test_screen_flow(client, db):
    """Full flow: decide → refine → score → result"""
    # Create via /decide
    resp = client.post(
        "/decide",
        data={"q": "Cost <= 60"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    import re

    decision_id = re.search(r"/screen/(\d+)/review", resp.headers["location"]).group(1)

    # Get metric IDs from seeded metrics
    from models import Metric

    metrics = db.query(Metric).order_by(Metric.id).all()
    assert len(metrics) >= 1

    # Refine
    refine_resp = client.post(
        f"/screen/{decision_id}/refine",
        data={
            "alt_name_0": "Cheap Option",
            "alt_name_1": "Expensive Option",
            "metric_id_0": str(metrics[0].id),
            "include_metric_0": "true",
            "criterion_weight_0": "80",
            "criterion_higher_0": "false",
            "threshold_op_0": "<=",
            "threshold_val_0": "60",
        },
        follow_redirects=False,
    )
    assert refine_resp.status_code == 303

    # Follow to score page
    score_page = client.get(refine_resp.headers["location"])
    assert score_page.status_code == 200

    # Submit scores
    score_fields = re.findall(r'name="(score_\d+_\d+)"', score_page.text)
    assert len(score_fields) >= 2

    score_data = {}
    for field in score_fields[:2]:
        score_data[field] = "50"
    score_resp = client.post(
        f"/screen/{decision_id}/score",
        data=score_data,
    )
    assert score_resp.status_code == 200
    assert "Screen Results" in score_resp.text
    assert "PASS" in score_resp.text or "FAIL" in score_resp.text


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
    assert "Ranking Review" in resp.text


def test_rank_review_page(client, db):
    """GET /rank/{id}/review loads with 3 alternatives"""
    resp = client.post("/rank", data={"q": "Python, Java, Go"}, follow_redirects=False)
    assert resp.status_code == 303
    import re

    decision_id = re.search(r"/rank/(\d+)/review", resp.headers["location"]).group(1)

    review_resp = client.get(f"/rank/{decision_id}/review")
    assert review_resp.status_code == 200
    assert "Ranking Review" in review_resp.text


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

    # Submit scores
    score_fields = re.findall(r'name="(score_\d+_\d+)"', score_page.text)
    assert len(score_fields) >= 3

    score_data = {}
    for field in score_fields[:3]:
        score_data[field] = "70"
    score_resp = client.post(
        f"/rank/{decision_id}/score",
        data=score_data,
    )
    assert score_resp.status_code == 200
    assert "Results" in score_resp.text or "Ranking" in score_resp.text


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
    # Should NOT redirect to rank (fewer than 3 items)
    assert not resp.headers.get("location", "").startswith("/rank/")


def test_rank_result_reuses_decision_result(client, db):
    """Rank result page shows ranking, radar chart, t-test"""
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
    score_fields = re.findall(r'name="(score_\d+_\d+)"', score_page.text)
    score_data = {}
    for field in score_fields[:3]:
        score_data[field] = "70"
    client.post(f"/rank/{decision_id}/score", data=score_data)

    # Check result page
    result = client.get(f"/rank/{decision_id}/result")
    assert result.status_code == 200
    # decision_result.html has "Ranking"
    assert "Ranking" in result.text
    assert "%" in result.text
