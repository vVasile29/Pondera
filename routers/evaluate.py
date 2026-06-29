from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from database import get_db
from models import Activity, ActivityWeight, AlternativeScore, Decision, Metric
from services.export import generate_markdown_brief, get_decision_export_data
from services.parser import extract_subject
from services.scoring import (
    compute_alternative_fit_scores,
    compute_dimension_scores,
    gap_analysis,
)

router = APIRouter(prefix="/evaluate", tags=["evaluate"])


def _serialize(obj):
    if obj is None:
        return None
    if hasattr(obj, "__table__"):
        return {c.name: _serialize(getattr(obj, c.name)) for c in obj.__table__.columns}
    if isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    try:
        return str(obj)
    except Exception:
        return None


class JsonTemplates:
    @staticmethod
    def TemplateResponse(request, name, context):
        data = {k: _serialize(v) for k, v in context.items() if k != "request"}
        data["_template"] = name
        return JSONResponse(content=data)


templates = JsonTemplates()


def _markdown_response(decision_id: int, db: Session) -> Response:
    data = get_decision_export_data(decision_id, db)
    if not data:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return Response(
        content=generate_markdown_brief(data),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="decision-{decision_id}-brief.md"'
        },
    )


@router.post("")
async def evaluate(request: Request, db: Session = Depends(get_db)):
    """Entry point — parse query, create decision + activity, redirect to review."""
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

    parsed = extract_subject(query)
    subject = parsed["subject"]

    # Create the Decision record with mode='diagnose'
    decision = Decision(query=query, category="General", mode="diagnose")
    db.add(decision)
    db.flush()

    # Create a single Activity for the subject
    activity = Activity(
        name=subject,
        category="General",
        decision_id=decision.id,
    )
    db.add(activity)
    db.flush()

    # Create ActivityWeight records for all universal metrics (default weights)
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

    return RedirectResponse(url=f"/evaluate/{decision.id}/review", status_code=303)


@router.get("/{decision_id}/review")
def evaluate_review(request: Request, decision_id: int, db: Session = Depends(get_db)):
    """Review/edit page — shows subject name and criteria selection."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    from services.ontology import UNIVERSAL_METRICS

    # Get existing activity
    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    subject = activities[0].name if activities else "This option"

    # Get all metrics with DB IDs
    all_metrics_db = db.query(Metric).order_by(Metric.category, Metric.name).all()
    metric_map = {m.name: m for m in all_metrics_db}

    # Determine which metrics are already selected and their weights
    selected_metric_ids = set()
    weights_by_metric_id = {}
    if activities:
        for aw in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id == activities[0].id)
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

    # Extract goal from query using extract_subject
    parsed = extract_subject(decision.query)

    return templates.TemplateResponse(
        request,
        "evaluate_review.html",
        {
            "request": request,
            "decision": decision,
            "subject": subject,
            "goal": parsed["goal"],
            "criteria": criteria,
            "category": decision.category or "General",
            "parsed": parsed["parsed"],
            "active_page": "decisions",
        },
    )


@router.post("/{decision_id}/refine")
async def evaluate_refine(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Save criteria choices and update subject name."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    form = await request.form()

    # Parse subject name
    subject = form.get("alt_name_0", "").strip()
    if not subject:
        subject = "This option"

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

    if not metric_items:
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
            "evaluate_review.html",
            {
                "request": request,
                "decision": decision,
                "subject": subject,
                "goal": extract_subject(decision.query).get("goal"),
                "criteria": criteria_with_ids,
                "category": "General",
                "error": "Please select at least one criterion.",
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

    # Re-create activity with updated subject name
    activity = Activity(
        name=subject,
        category=decision.category or "General",
        decision_id=decision_id,
    )
    db.add(activity)
    db.flush()

    # Create weight rows for each selected metric
    for mitem in metric_items:
        aw = ActivityWeight(
            activity_id=activity.id,
            metric_id=mitem["metric_id"],
            weight=mitem["default_weight"],
        )
        db.add(aw)

    db.commit()

    return RedirectResponse(url=f"/evaluate/{decision_id}/score", status_code=303)


@router.get("/{decision_id}/score")
def evaluate_score_page(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Score page — reuses decision_score.html with URL context variables."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Evaluation not found")

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
            "back_url": f"/evaluate/{decision_id}/review",
            "score_url": f"/evaluate/{decision_id}/score",
            "result_url": f"/evaluate/{decision_id}/result",
        },
    )


@router.post("/{decision_id}/score")
async def evaluate_score(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Submit scores and redirect to result."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Evaluation not found")

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

    return RedirectResponse(url=f"/evaluate/{decision_id}/result", status_code=303)


@router.get("/{decision_id}/result")
async def evaluate_result(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Result page — shows fit score, dimension breakdown, gap analysis, radar chart."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Evaluation not found")

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
            "evaluate_result.html",
            {
                "request": request,
                "decision": decision,
                "results": [],
                "metric_names": [],
                "series": [],
                "dimension_scores": [],
                "gap_analysis_result": None,
                "significance": None,
                "active_page": "decisions",
            },
        )

    # Compute fit scores
    results = compute_alternative_fit_scores(decision_id, db)

    # Compute dimension breakdown
    dim_scores = compute_dimension_scores(decision_id, db)

    # Compute gap analysis
    gap_result = gap_analysis(dim_scores)

    # Build chart data
    metric_names = [m.name for m in metrics]
    higher_is_better = {m.id: m.higher_is_better for m in metrics}

    # Get scores for each activity
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

    return templates.TemplateResponse(
        request,
        "evaluate_result.html",
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
            "dimension_scores": dim_scores,
            "gap_analysis_result": gap_result,
            "significance": None,
            "active_page": "decisions",
        },
    )


@router.get("/{decision_id}/export-markdown")
def export_markdown(decision_id: int, db: Session = Depends(get_db)):
    return _markdown_response(decision_id, db)


@router.post("/{decision_id}/delete")
async def delete_evaluation(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Delete an evaluation and all associated data."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    # Delete AlternativeScore first (not in ORM cascade)
    activity_ids = [a.id for a in decision.activities]
    if activity_ids:
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id.in_(activity_ids)
        ).delete()

    db.delete(decision)  # cascades to Activity → ActivityWeight
    db.commit()

    redirect = request.query_params.get("redirect", "/")
    return RedirectResponse(url=redirect, status_code=303)
