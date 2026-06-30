import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Activity, ActivityWeight, AlternativeScore, Decision, Metric
from services.scoring import (
    build_significance_summary,
    compute_alternative_fit_scores,
    filter_by_thresholds,
)

router = APIRouter(prefix="/decisions", tags=["decisions"])


def _serialize(obj):
    """Recursively serialize objects to JSON-safe types."""
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
    """Minimal Jinja2Templates replacement that returns JSON instead of rendering HTML."""

    @staticmethod
    def TemplateResponse(request, name, context):
        data = {k: _serialize(v) for k, v in context.items() if k != "request"}
        data["_template"] = name
        return JSONResponse(content=data)


templates = JsonTemplates()


def decision_result_url(decision: Decision) -> str:
    mode = getattr(decision, "mode", None) or "choose"
    return {
        "diagnose": f"/evaluate/{decision.id}/result",
        "screen": f"/screen/{decision.id}/result",
        "rank": f"/rank/{decision.id}/result",
    }.get(mode, f"/decisions/{decision.id}/result")


def safe_delete_redirect(redirect: str | None) -> str:
    return redirect if redirect in {"/", "/decisions"} else "/"


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


@router.get("")
def list_decisions(request: Request, db: Session = Depends(get_db)):
    decisions = db.query(Decision).order_by(Decision.created_at.desc()).all()
    for decision in decisions:
        decision.result_url = decision_result_url(decision)
    return templates.TemplateResponse(
        request,
        "decisions_list.html",
        {"request": request, "decisions": decisions, "active_page": "decisions"},
    )


@router.post("/{decision_id}/refine")
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

    # Parse metrics: form sends metric_id_{j}, criterion_weight_{j}, criterion_higher_{j}
    # Only include metrics where include_metric_{j} is present
    metric_items = []
    j = 0
    while f"metric_id_{j}" in form:
        metric_id_str = form.get(f"metric_id_{j}").strip()
        include = form.get(f"include_metric_{j}", "false")
        # Accept both "true" (Alpine.js model) and "on" (native HTML form submission)
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
        # Re-render with error — enrich metrics with DB IDs
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
            "decision_review.html",
            {
                "request": request,
                "decision": decision,
                "alternatives": alternatives or ["Option A", "Option B"],
                "criteria": criteria_with_ids,
                "category": "General",
                "error": "Please provide at least one alternative and select at least one criterion.",
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
            category=decision.category if hasattr(decision, "category") else "General",
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

    # Redirect to scoring page
    return RedirectResponse(url=f"/decisions/{decision_id}/score", status_code=303)


@router.get("/{decision_id}/review")
def review_decision(request: Request, decision_id: int, db: Session = Depends(get_db)):
    """Review/refine page — edit alternatives and select criteria."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    from services.ontology import UNIVERSAL_METRICS

    # Get existing activities (previously saved alternatives)
    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    alternatives = (
        [a.name for a in activities] if activities else ["Option A", "Option B"]
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
            # Use the weight from the first activity (all share same weight by design)
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

    parsed = len(activities) >= 2

    return templates.TemplateResponse(
        request,
        "decision_review.html",
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


@router.post("/{decision_id}/score")
async def score_decision(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    form = await request.form()

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()

    # Get metrics from ActivityWeight for this decision's activities
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

    # Redirect to results
    return await decision_result(request, decision_id, db)


@router.get("/{decision_id}/result")
async def decision_result(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()

    # Get metrics from ActivityWeight for this decision's activities
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
        series.append(
            {
                "name": act.name,
                "scores": [scores_map.get(m.id, 0) for m in metrics],
            }
        )

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

    # ── Statistical significance (paired t-test of top 2 alternatives) ──
    significance = _significance_for_results(results, series, metrics)

    # ── Threshold-based filtering (post-hoc) ──
    filter_result = None
    threshold_criteria = []
    threshold_errors = []

    # Build threshold_criteria for Alpine prepopulation
    # Get all metrics that have ActivityWeight rows for this decision's activities
    activity_ids = [a.id for a in activities]
    metric_ids_with_weights = set()
    if activity_ids:
        for aw in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id.in_(activity_ids))
            .all()
        ):
            metric_ids_with_weights.add(aw.metric_id)

    # Parse existing thresholds from decision JSON
    existing_thresholds = []
    if decision.thresholds:
        try:
            existing_thresholds = json.loads(decision.thresholds)
        except (json.JSONDecodeError, TypeError):
            existing_thresholds = []

    existing_by_metric = {}
    for t in existing_thresholds:
        if isinstance(t, dict) and "metric_id" in t:
            existing_by_metric[t["metric_id"]] = t

    # Build threshold_criteria for all metrics with ActivityWeight rows
    if metric_ids_with_weights:
        metrics_in_use = (
            db.query(Metric).filter(Metric.id.in_(metric_ids_with_weights)).all()
        )
        for m in metrics_in_use:
            existing_t = existing_by_metric.get(m.id, {})
            threshold_criteria.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "operator": existing_t.get("operator", "<="),
                    "value": existing_t.get("value", ""),
                }
            )

    # Apply threshold filter if thresholds exist
    if existing_thresholds:
        filter_result = filter_by_thresholds(decision_id, db)

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
            "filter_result": filter_result,
            "threshold_criteria": threshold_criteria,
            "threshold_errors": threshold_errors,
            "active_page": "decisions",
        },
    )


@router.get("/{decision_id}/score")
async def score_page(request: Request, decision_id: int, db: Session = Depends(get_db)):
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()

    # Get metrics from ActivityWeight for this decision's activities
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
        },
    )


@router.post("/{decision_id}/delete")
async def delete_decision(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Delete a decision and all associated data."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    # AlternativeScore is not in the ORM cascade chain (no relationship from Activity),
    # so delete it manually. The rest (Activity → ActivityWeight) cascades via ORM.
    activity_ids = [a.id for a in decision.activities]
    if activity_ids:
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id.in_(activity_ids)
        ).delete()

    db.delete(decision)  # cascades to Activity → ActivityWeight
    db.commit()

    redirect = safe_delete_redirect(request.query_params.get("redirect"))
    return RedirectResponse(url=redirect, status_code=303)


@router.post("/{decision_id}/thresholds")
async def apply_thresholds(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Apply threshold filters to a decision's result page.

    Reads form data containing threshold operator/value pairs per metric,
    validates them, stores valid entries in Decision.thresholds JSON,
    and re-renders the result page with error feedback for invalid entries.
    """
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    form = await request.form()

    # Collect metric IDs with ActivityWeight rows
    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    activity_ids = [a.id for a in activities]
    metric_ids_with_weights = set()
    if activity_ids:
        for aw in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id.in_(activity_ids))
            .all()
        ):
            metric_ids_with_weights.add(aw.metric_id)

    thresholds_json = []
    threshold_errors = []
    j = 0

    while f"threshold_metric_id_{j}" in form:
        metric_id_str = form.get(f"threshold_metric_id_{j}").strip()
        if not metric_id_str:
            j += 1
            continue
        try:
            metric_id = int(metric_id_str)
        except (ValueError, TypeError):
            j += 1
            continue

        if metric_id not in metric_ids_with_weights:
            j += 1
            continue

        t_op = form.get(f"threshold_op_{j}", "<=")
        t_val = form.get(f"threshold_val_{j}", "").strip()

        if t_val:
            try:
                t_val_float = float(t_val)
                if t_val_float < 0.0 or t_val_float > 100.0:
                    threshold_errors.append(
                        f"Threshold value {t_val_float} is outside the 0–100 scale."
                    )
                else:
                    thresholds_json.append(
                        {
                            "metric_id": metric_id,
                            "operator": t_op,
                            "value": t_val_float,
                        }
                    )
            except ValueError:
                threshold_errors.append(
                    f"Invalid threshold value '{t_val}' (must be a number)."
                )
        j += 1

    if threshold_errors:
        # Re-render result page with error messages, don't save
        # Get existing context from decision_result
        return await _render_result_with_threshold_errors(
            request, decision_id, db, threshold_errors
        )

    # Store valid thresholds
    if thresholds_json:
        decision.thresholds = json.dumps(thresholds_json)
    else:
        decision.thresholds = None
    db.commit()

    return RedirectResponse(url=f"/decisions/{decision_id}/result", status_code=303)


@router.post("/{decision_id}/thresholds/clear")
async def clear_thresholds(
    request: Request, decision_id: int, db: Session = Depends(get_db)
):
    """Clear all threshold filters for a decision."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision.thresholds = None
    db.commit()

    return RedirectResponse(url=f"/decisions/{decision_id}/result", status_code=303)


async def _render_result_with_threshold_errors(
    request: Request, decision_id: int, db: Session, threshold_errors: list[str]
):
    """Helper to re-render the result page with threshold errors."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
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

    results = compute_alternative_fit_scores(decision_id, db)

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

    significance = _significance_for_results(results, series, metrics)

    # Build threshold_criteria from form values + stored thresholds
    filter_result = None
    if decision.thresholds:
        try:
            existing = json.loads(decision.thresholds)
            if existing:
                # Use the stored thresholds (before the error) if any exist
                filter_result = filter_by_thresholds(decision_id, db)
        except (json.JSONDecodeError, TypeError):
            pass

    threshold_criteria = []
    metric_ids_with_weights = set()
    if activity_ids:
        for aw in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id.in_(activity_ids))
            .all()
        ):
            metric_ids_with_weights.add(aw.metric_id)

    existing_thresholds = []
    if decision.thresholds:
        try:
            existing_thresholds = json.loads(decision.thresholds)
        except (json.JSONDecodeError, TypeError):
            existing_thresholds = []

    existing_by_metric = {}
    for t in existing_thresholds:
        if isinstance(t, dict) and "metric_id" in t:
            existing_by_metric[t["metric_id"]] = t

    if metric_ids_with_weights:
        metrics_in_use = (
            db.query(Metric).filter(Metric.id.in_(metric_ids_with_weights)).all()
        )
        for m in metrics_in_use:
            existing_t = existing_by_metric.get(m.id, {})
            threshold_criteria.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "operator": existing_t.get("operator", "<="),
                    "value": existing_t.get("value", ""),
                }
            )

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
            "filter_result": filter_result,
            "threshold_criteria": threshold_criteria,
            "threshold_errors": threshold_errors,
            "active_page": "decisions",
        },
    )
