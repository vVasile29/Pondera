from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import Activity, ActivityWeight, AlternativeScore, Decision, Metric
from services.scoring import compute_alternative_fit_scores

router = APIRouter(prefix="/decisions", tags=["decisions"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
def list_decisions(request: Request, db: Session = Depends(get_db)):
    decisions = db.query(Decision).order_by(Decision.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request, "decisions": decisions, "active_page": "home"},
    )


@router.post("/{decision_id}/refine", response_class=HTMLResponse)
async def refine_decision(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    form = await request.form()

    # Parse alternative names (alt_name_0, alt_name_1, ...)
    alternatives = []
    i = 0
    while f"alt_name_{i}" in form:
        name = form.get(f"alt_name_{i}").strip()
        if name:
            alternatives.append(name)
        i += 1

    # Parse criteria (criteria_name_0, criteria_name_1, ...)
    criteria_items = []
    j = 0
    while f"criterion_name_{j}" in form:
        name = form.get(f"criterion_name_{j}").strip()
        desc = form.get(f"criterion_desc_{j}", "").strip()
        weight_str = form.get(f"criterion_weight_{j}", "50")
        higher_str = form.get(f"criterion_higher_{j}", "true")
        if name:
            criteria_items.append({
                "name": name,
                "description": desc or name,
                "default_weight": float(weight_str),
                "higher_is_better": higher_str == "true",
            })
        j += 1

    if not alternatives or not criteria_items:
        return templates.TemplateResponse(
            request,
            "decision_review.html",
            {
                "request": request,
                "decision": decision,
                "alternatives": alternatives or ["Option A", "Option B"],
                "criteria": criteria_items or [],
                "category": "General",
                "error": "Please provide at least one alternative and one criterion.",
            },
        )

    # Delete old activities and metrics for this decision, then recreate
    for activity in decision.activities:
        db.query(ActivityWeight).filter(ActivityWeight.activity_id == activity.id).delete()
        db.query(AlternativeScore).filter(AlternativeScore.activity_id == activity.id).delete()
        db.delete(activity)
    db.flush()

    old_metrics = db.query(Metric).filter(Metric.decision_id == decision_id).all()
    for m in old_metrics:
        db.delete(m)
    db.flush()

    # Create metrics for each criterion
    metric_objects = {}
    for crit in criteria_items:
        metric = Metric(
            name=crit["name"],
            category=decision.category if hasattr(decision, 'category') else "General",
            description=crit["description"],
            higher_is_better=crit["higher_is_better"],
            decision_id=decision_id,
        )
        db.add(metric)
        db.flush()
        metric_objects[crit["name"]] = metric

    # Create activities for each alternative
    for alt_name in alternatives:
        activity = Activity(
            name=alt_name,
            category=decision.category if hasattr(decision, 'category') else "General",
            decision_id=decision_id,
        )
        db.add(activity)
        db.flush()

        # Create weight rows for each metric
        for crit in criteria_items:
            metric = metric_objects[crit["name"]]
            aw = ActivityWeight(
                activity_id=activity.id,
                metric_id=metric.id,
                weight=crit["default_weight"],
            )
            db.add(aw)

    db.commit()

    # Redirect to scoring page
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/decisions/{decision_id}/score", status_code=303)


@router.post("/{decision_id}/score", response_class=HTMLResponse)
async def score_decision(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    form = await request.form()

    activities = (
        db.query(Activity)
        .filter(Activity.decision_id == decision_id)
        .all()
    )
    metrics = (
        db.query(Metric)
        .filter(Metric.decision_id == decision_id)
        .all()
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

    # Redirect to results
    return await decision_result(request, decision_id, db)


@router.get("/{decision_id}/result", response_class=HTMLResponse)
async def decision_result(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    activities = (
        db.query(Activity)
        .filter(Activity.decision_id == decision_id)
        .all()
    )
    metrics = (
        db.query(Metric)
        .filter(Metric.decision_id == decision_id)
        .all()
    )

    if not activities or not metrics:
        return templates.TemplateResponse(
            request,
            "decision_result.html",
            {
                "request": request,
                "decision": decision,
                "results": [],
                "metric_names": [],
                "series": [],
                "active_page": "decisions",
            },
        )

    # Compute fit scores for each activity
    results = compute_alternative_fit_scores(decision_id, db)

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
        series.append({
            "name": act.name,
            "scores": [scores_map.get(m.id, 0) for m in metrics],
        })

    # Build flat rows for the detailed scores table
    rows = []
    for m in metrics:
        # Get weight for this metric from any activity's ActivityWeight
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
            "active_page": "decisions",
        },
    )


@router.get("/{decision_id}/score", response_class=HTMLResponse)
async def score_page(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    activities = (
        db.query(Activity)
        .filter(Activity.decision_id == decision_id)
        .all()
    )
    metrics = (
        db.query(Metric)
        .filter(Metric.decision_id == decision_id)
        .order_by(Metric.id)
        .all()
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
        criteria.append({
            "id": m.id,
            "name": m.name,
            "description": m.description or m.name,
            "default_weight": weight,
            "higher_is_better": m.higher_is_better,
        })

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
        },
    )
