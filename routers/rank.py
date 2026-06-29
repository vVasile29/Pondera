"""RANK (Mode 4) — Multi-alternative ranking router."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import Activity, ActivityWeight, AlternativeScore, Decision, Metric
from services.parser import extract_list
from services.export import generate_markdown_brief, get_decision_export_data
from services.scoring import build_significance_summary, compute_alternative_fit_scores

router = APIRouter(prefix="/rank", tags=["rank"])
templates = Jinja2Templates(directory="templates")


def _significance_for_results(results, series, metrics):
    if len(results) < 2 or len(metrics) < 2:
        return None
    top_1 = results[0]
    top_2 = results[1]
    series_by_name = {s["name"]: s["scores"] for s in series}
    scores_1 = series_by_name.get(top_1["activity_name"])
    scores_2 = series_by_name.get(top_2["activity_name"])
    if scores_1 is None or scores_2 is None:
        return None
    return build_significance_summary(
        top_1["activity_name"],
        top_2["activity_name"],
        scores_1,
        scores_2,
        top_1["fit_score"] * 100,
        top_2["fit_score"] * 100,
    )


def _markdown_response(decision_id: int, db: Session) -> Response:
    data = get_decision_export_data(decision_id, db)
    if not data:
        raise HTTPException(status_code=404, detail="Ranking not found")
    return Response(
        content=generate_markdown_brief(data),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="decision-{decision_id}-brief.md"'
        },
    )


@router.post("", response_class=HTMLResponse)
async def rank_create(request: Request, db: Session = Depends(get_db)):
    """Entry point — parse list query, create Decision, redirect to review."""
    from services.ontology import UNIVERSAL_METRICS

    form = await request.form()
    query = form.get("q", "").strip()

    if not query:
        from models import Decision as DecModel

        decisions = db.query(DecModel).order_by(DecModel.created_at.desc()).all()
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

    # Extract list from query
    list_parsed = extract_list(query)
    alternatives = list_parsed["alternatives"] if list_parsed["parsed"] else []

    # Create Decision
    decision = Decision(query=query, category="General", mode="rank")
    db.add(decision)
    db.flush()

    # Create activities (minimum 3 placeholders if not parsed)
    alt_names = alternatives if alternatives else ["Option A", "Option B", "Option C"]
    for name in alt_names:
        activity = Activity(
            name=name,
            category="General",
            decision_id=decision.id,
        )
        db.add(activity)
        db.flush()

        # Add default weight for all universal metrics
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

    return RedirectResponse(url=f"/rank/{decision.id}/review", status_code=303)


@router.get("/{decision_id}/review", response_class=HTMLResponse)
def rank_review(request: Request, decision_id: int, db: Session = Depends(get_db)):
    """Review page — shows 3+ alternatives + criteria selection."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Ranking not found")

    from services.ontology import UNIVERSAL_METRICS

    # Get existing activities
    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    alternatives = (
        [a.name for a in activities]
        if activities
        else ["Option A", "Option B", "Option C"]
    )

    # Get all metrics with DB IDs
    all_metrics_db = db.query(Metric).order_by(Metric.category, Metric.name).all()
    metric_map = {m.name: m for m in all_metrics_db}

    # Determine which metrics are already selected and their weights
    selected_metric_ids = set()
    weights_by_metric_id = {}
    if activities:
        activity_ids = [a.id for a in activities]
        for aw in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id.in_(activity_ids))
            .all()
        ):
            selected_metric_ids.add(aw.metric_id)
            weights_by_metric_id[aw.metric_id] = aw.weight

    criteria = []
    for c in UNIVERSAL_METRICS:
        metric = metric_map.get(c["name"])
        metric_id = metric.id if metric else None
        is_selected = metric_id in selected_metric_ids
        weight = weights_by_metric_id.get(metric_id, c["default_weight"])
        criteria.append(
            {
                **c,
                "id": metric_id,
                "include": is_selected,
                "default_weight": weight,
            }
        )

    parsed = len(alternatives) >= 3

    return templates.TemplateResponse(
        request,
        "rank_review.html",
        {
            "request": request,
            "decision": decision,
            "alternatives": alternatives,
            "criteria": criteria,
            "category": decision.category or "General",
            "parsed": parsed,
            "active_page": "decisions",
        },
    )


@router.post("/{decision_id}/refine", response_class=HTMLResponse)
async def rank_refine(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Save alternatives + criteria; redirect to score."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Ranking not found")

    form = await request.form()

    # Parse alternative names
    alternatives = []
    i = 0
    while f"alt_name_{i}" in form:
        name = form.get(f"alt_name_{i}").strip()
        if name:
            alternatives.append(name)
        i += 1

    # Parse metrics
    metric_items = []
    j = 0
    while f"metric_id_{j}" in form:
        metric_id_str = form.get(f"metric_id_{j}").strip()
        include = form.get(f"include_metric_{j}", "false")
        if metric_id_str and include in ("true", "on"):
            weight_str = form.get(f"criterion_weight_{j}", "50")
            higher_str = form.get(f"criterion_higher_{j}", "true")
            metric_items.append(
                {
                    "metric_id": int(metric_id_str),
                    "default_weight": float(weight_str),
                    "higher_is_better": higher_str == "true",
                }
            )
        j += 1

    if not alternatives or not metric_items:
        from services.ontology import UNIVERSAL_METRICS

        all_metrics = db.query(Metric).order_by(Metric.category, Metric.name).all()
        metric_map = {m.name: m for m in all_metrics}
        criteria_with_ids = []
        for c in UNIVERSAL_METRICS:
            metric = metric_map.get(c["name"])
            criteria_with_ids.append(
                {
                    **c,
                    "id": metric.id if metric else None,
                }
            )
        return templates.TemplateResponse(
            request,
            "rank_review.html",
            {
                "request": request,
                "decision": decision,
                "alternatives": alternatives or ["Option A", "Option B", "Option C"],
                "criteria": criteria_with_ids,
                "category": "General",
                "error": "Please provide at least 3 alternatives and select at least one criterion.",
            },
        )

    if len(alternatives) < 3:
        from services.ontology import UNIVERSAL_METRICS

        all_metrics = db.query(Metric).order_by(Metric.category, Metric.name).all()
        metric_map = {m.name: m for m in all_metrics}
        criteria_with_ids = []
        for c in UNIVERSAL_METRICS:
            metric = metric_map.get(c["name"])
            criteria_with_ids.append(
                {
                    **c,
                    "id": metric.id if metric else None,
                }
            )
        return templates.TemplateResponse(
            request,
            "rank_review.html",
            {
                "request": request,
                "decision": decision,
                "alternatives": alternatives,
                "criteria": criteria_with_ids,
                "category": "General",
                "error": "Please provide at least 3 alternatives for a meaningful ranking.",
            },
        )

    # Delete old activities and their weights/scores
    for activity in decision.activities:
        db.query(ActivityWeight).filter(
            ActivityWeight.activity_id == activity.id
        ).delete()
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id == activity.id
        ).delete()
        db.delete(activity)
    db.flush()

    # Create activities for each alternative
    for alt_name in alternatives:
        activity = Activity(
            name=alt_name,
            category=decision.category or "General",
            decision_id=decision_id,
        )
        db.add(activity)
        db.flush()

        for mitem in metric_items:
            aw = ActivityWeight(
                activity_id=activity.id,
                metric_id=mitem["metric_id"],
                weight=mitem["default_weight"],
            )
            db.add(aw)

    db.commit()

    return RedirectResponse(url=f"/rank/{decision_id}/score", status_code=303)


@router.get("/{decision_id}/score", response_class=HTMLResponse)
def rank_score_page(request: Request, decision_id: int, db: Session = Depends(get_db)):
    """Score page — reuses decision_score.html with context URLs."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Ranking not found")

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()

    # Get metrics from ActivityWeight
    activity_ids = [a.id for a in activities]
    metric_ids = set()
    if activity_ids:
        for aw in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id.in_(activity_ids))
            .all()
        ):
            metric_ids.add(aw.metric_id)
    metrics = (
        db.query(Metric).filter(Metric.id.in_(metric_ids)).order_by(Metric.id).all()
        if metric_ids
        else []
    )

    # Build criteria list with DB IDs
    criteria = []
    for m in metrics:
        weight = 50
        if activities:
            aw = (
                db.query(ActivityWeight)
                .filter(
                    ActivityWeight.activity_id == activities[0].id,
                    ActivityWeight.metric_id == m.id,
                )
                .first()
            )
            if aw:
                weight = aw.weight
        criteria.append(
            {
                "id": m.id,
                "name": m.name,
                "description": m.description or m.name,
                "default_weight": weight,
                "higher_is_better": m.higher_is_better,
            }
        )

    # Check if already scored
    already_scored = False
    if activities:
        existing = (
            db.query(AlternativeScore)
            .filter(AlternativeScore.activity_id == activities[0].id)
            .first()
        )
        already_scored = existing is not None

    return templates.TemplateResponse(
        request,
        "decision_score.html",
        {
            "request": request,
            "decision": decision,
            "activities": activities,
            "criteria": criteria,
            "already_scored": already_scored,
            "active_page": "decisions",
            "back_url": f"/rank/{decision_id}/review",
            "score_url": f"/rank/{decision_id}/score",
            "result_url": f"/rank/{decision_id}/result",
        },
    )


@router.post("/{decision_id}/score", response_class=HTMLResponse)
async def rank_score(request: Request, decision_id: int, db: Session = Depends(get_db)):
    """Submit scores, redirect to result."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Ranking not found")

    form = await request.form()

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()

    # Get metrics from ActivityWeight
    activity_ids = [a.id for a in activities]
    metric_ids = set()
    if activity_ids:
        for aw in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id.in_(activity_ids))
            .all()
        ):
            metric_ids.add(aw.metric_id)
    metrics = (
        db.query(Metric).filter(Metric.id.in_(metric_ids)).all() if metric_ids else []
    )

    # Delete old alternative scores
    for activity in activities:
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id == activity.id
        ).delete()
    db.flush()

    # Parse scores from form: score_{activity_id}_{metric_id}
    for activity in activities:
        for metric in metrics:
            key = f"score_{activity.id}_{metric.id}"
            if key in form:
                val = form.get(key)
                if val and val.strip():
                    score_val = float(val)
                    alt_score = AlternativeScore(
                        activity_id=activity.id,
                        metric_id=metric.id,
                        score=score_val,
                    )
                    db.add(alt_score)

    db.commit()

    return RedirectResponse(url=f"/rank/{decision_id}/result", status_code=303)


@router.get("/{decision_id}/result", response_class=HTMLResponse)
async def rank_result(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Result page — reuses decision_result.html (ranking + radar + t-test)."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Ranking not found")

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()

    # Get metrics from ActivityWeight
    activity_ids = [a.id for a in activities]
    metric_ids = set()
    if activity_ids:
        for aw in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id.in_(activity_ids))
            .all()
        ):
            metric_ids.add(aw.metric_id)
    metrics = (
        db.query(Metric).filter(Metric.id.in_(metric_ids)).all() if metric_ids else []
    )

    if not activities or not metrics:
        return templates.TemplateResponse(
            request,
            "decision_result.html",
            {
                "request": request,
                "decision": decision,
                "results": [],
                "activities": [],
                "metrics": [],
                "metric_names": [],
                "series": [],
                "rows": [],
                "significance": None,
                "active_page": "decisions",
            },
        )

    # Compute fit scores
    results = compute_alternative_fit_scores(decision_id, db)

    # Build chart data
    metric_names = [m.name for m in metrics]
    higher_is_better = {m.id: m.higher_is_better for m in metrics}

    series = []
    for act in activities:
        scores_map = {}
        for alt_s in (
            db.query(AlternativeScore)
            .filter(AlternativeScore.activity_id == act.id)
            .all()
        ):
            scores_map[alt_s.metric_id] = alt_s.score
        series.append(
            {
                "name": act.name,
                "scores": [scores_map.get(m.id, 0) for m in metrics],
            }
        )

    # Build flat rows for the detailed scores table
    rows = []
    for m in metrics:
        weight = 50
        if activities:
            aw = (
                db.query(ActivityWeight)
                .filter(
                    ActivityWeight.activity_id == activities[0].id,
                    ActivityWeight.metric_id == m.id,
                )
                .first()
            )
            if aw:
                weight = aw.weight

        row = {
            "metric_name": m.name,
            "metric_desc": m.description or "",
            "weight": weight,
            "scores": {},
        }
        for act in activities:
            for alt_s in (
                db.query(AlternativeScore)
                .filter(
                    AlternativeScore.activity_id == act.id,
                    AlternativeScore.metric_id == m.id,
                )
                .all()
            ):
                row["scores"][act.id] = alt_s.score
        rows.append(row)

    # Statistical significance
    significance = _significance_for_results(results, series, metrics)

    return templates.TemplateResponse(
        request,
        "decision_result.html",
        {
            "request": request,
            "decision": decision,
            "activities": activities,
            "metrics": metrics,
            "metric_names": metric_names,
            "higher_is_better": higher_is_better,
            "series": series,
            "rows": rows,
            "results": results,
            "significance": significance,
            "active_page": "decisions",
        },
    )


@router.get("/{decision_id}/export-markdown")
def export_markdown(decision_id: int, db: Session = Depends(get_db)):
    return _markdown_response(decision_id, db)


@router.post("/{decision_id}/delete")
async def delete_rank(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Delete a ranking and all associated data."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Ranking not found")

    activity_ids = [a.id for a in decision.activities]
    if activity_ids:
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id.in_(activity_ids)
        ).delete()

    db.delete(decision)
    db.commit()

    redirect = request.query_params.get("redirect", "/")
    return RedirectResponse(url=redirect, status_code=303)
