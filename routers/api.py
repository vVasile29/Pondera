"""Backend JSON API layer for Pondera.

Provides RESTful JSON endpoints mirroring the existing HTML form-based flow.
Allows headless access for frontend frameworks (e.g., Vue, React via localhost:5173).
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Activity, ActivityWeight, AlternativeScore, Decision, Metric
from schemas import MetricCreate, MetricUpdate
from services.scoring import (
    build_significance_summary,
    compute_alternative_fit_scores,
    compute_dimension_scores,
    filter_by_thresholds,
    gap_analysis,
)

router = APIRouter(prefix="/api", tags=["api"])


# ── Shared helpers ──


def _decision_result_url(decision: Decision) -> str:
    mode = decision.mode if hasattr(decision, "mode") and decision.mode else "choose"
    return {
        "diagnose": f"/evaluate/{decision.id}/result",
        "screen": f"/screen/{decision.id}/result",
        "rank": f"/rank/{decision.id}/result",
    }.get(mode, f"/decisions/{decision.id}/result")


def _review_url(decision: Decision) -> str:
    mode = decision.mode if hasattr(decision, "mode") and decision.mode else "choose"
    return {
        "diagnose": f"/evaluate/{decision.id}/review",
        "rank": f"/rank/{decision.id}/review",
    }.get(mode, f"/decisions/{decision.id}/review")


def _significance_for_results(
    results: list, series: list, metrics: list
) -> dict | None:
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


def _parse_thresholds(decision: Decision) -> list:
    if not decision.thresholds:
        return []
    try:
        return json.loads(decision.thresholds)
    except (json.JSONDecodeError, TypeError):
        return []


def _build_decision_detail(
    decision_id: int,
    db: Session,
    *,
    force_dimension_scores: bool = False,
    force_filter: bool = False,
) -> dict:
    """Assemble the full decision detail JSON.

    Used by GET /api/decisions/{id}, /api/evaluate/{id}, /api/rank/{id}, /api/screen/{id}.
    """
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

    result = {
        "decision": {
            "id": decision.id,
            "query": decision.query,
            "mode": decision.mode if decision.mode else "choose",
            "category": decision.category,
            "created_at": decision.created_at.isoformat()
            if decision.created_at
            else None,
        },
        "activities": [{"id": a.id, "name": a.name} for a in activities],
        "metrics": [
            {
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "description": m.description or "",
                "higher_is_better": m.higher_is_better,
            }
            for m in metrics
        ],
        "results": [],
        "series": [],
        "metric_names": [],
        "rows": [],
        "significance": None,
        "dimension_scores": None,
        "gap_analysis": None,
        "filter_result": None,
        "threshold_criteria": [],
        "thresholds": _parse_thresholds(decision),
    }

    if not activities or not metrics:
        return result

    # Compute fit scores
    results = compute_alternative_fit_scores(decision_id, db)
    result["results"] = results

    # Build chart data
    metric_names = [m.name for m in metrics]
    result["metric_names"] = metric_names

    # Build series (for radar chart)
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
    result["series"] = series

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
    result["rows"] = rows

    # Dimension scores + gap analysis (for diagnose mode or evaluate endpoint)
    mode = decision.mode if decision.mode else "choose"
    if force_dimension_scores or mode == "diagnose":
        dim_scores = compute_dimension_scores(decision_id, db)
        result["dimension_scores"] = dim_scores
        result["gap_analysis"] = gap_analysis(dim_scores) if dim_scores else None

    # Statistical significance
    result["significance"] = _significance_for_results(results, series, metrics)

    # Threshold filtering
    thresholds = _parse_thresholds(decision)
    if thresholds or force_filter:
        filter_result = filter_by_thresholds(decision_id, db)
        result["filter_result"] = filter_result

        # Build threshold_criteria
        threshold_criteria = []
        existing_by_metric = {}
        for t in thresholds:
            if isinstance(t, dict) and "metric_id" in t:
                existing_by_metric[t["metric_id"]] = t

        if metric_ids:
            metrics_in_use = db.query(Metric).filter(Metric.id.in_(metric_ids)).all()
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
        result["threshold_criteria"] = threshold_criteria

    return result


# ── Endpoints ──


@router.post("/decide")
def decide(body: dict, db: Session = Depends(get_db)):
    """Parse a free-text question, create decision + activities, return JSON redirect."""
    from services.ontology import UNIVERSAL_METRICS
    from services.parser import extract_list, extract_subject, parse_question

    query = (body.get("q") or "").strip()

    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # ── Helper: seed default weights for one activity ──
    def _seed_default_weights(activity_id: int) -> None:
        all_metrics = db.query(Metric).all()
        metric_map = {m.name: m for m in all_metrics}
        for m in UNIVERSAL_METRICS:
            metric = metric_map.get(m["name"])
            if metric:
                db.add(
                    ActivityWeight(
                        activity_id=activity_id,
                        metric_id=metric.id,
                        weight=m["default_weight"],
                    )
                )

    # ── Heuristic routing (auto-detect mode from query) ──
    parsed = parse_question(query)
    alternatives = parsed["alternatives"]
    category = parsed["category"]
    is_parsed = parsed["parsed"]

    # If CHOOSE didn't find alternatives, try DIAGNOSE parsing
    if not is_parsed:
        diag = extract_subject(query)
        if diag["parsed"]:
            decision = Decision(query=query, category="General", mode="diagnose")
            db.add(decision)
            db.flush()

            subject = diag["subject"]
            activity = Activity(
                name=subject, category="General", decision_id=decision.id
            )
            db.add(activity)
            db.flush()
            _seed_default_weights(activity.id)
            db.commit()

            return {
                "decision_id": decision.id,
                "mode": "diagnose",
                "redirect_url": f"/evaluate/{decision.id}/review",
            }

        # If DIAGNOSE didn't match, try RANK
        list_parsed = extract_list(query)
        if list_parsed["parsed"]:
            decision = Decision(query=query, category="General", mode="rank")
            db.add(decision)
            db.flush()

            for name in list_parsed["alternatives"]:
                activity = Activity(
                    name=name, category="General", decision_id=decision.id
                )
                db.add(activity)
                db.flush()
                _seed_default_weights(activity.id)

            db.commit()
            return {
                "decision_id": decision.id,
                "mode": "rank",
                "redirect_url": f"/rank/{decision.id}/review",
            }

    # Continue as CHOOSE
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
        _seed_default_weights(activity.id)

    db.commit()

    return {
        "decision_id": decision.id,
        "mode": decision.mode if decision.mode else "choose",
        "redirect_url": f"/decisions/{decision.id}/review",
    }


@router.get("/decisions")
def list_decisions(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List decisions ordered by created_at desc with mode-aware result_url."""
    decisions = (
        db.query(Decision)
        .order_by(Decision.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "decisions": [
            {
                "id": d.id,
                "query": d.query,
                "mode": d.mode if d.mode else "choose",
                "category": d.category,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "result_url": _decision_result_url(d),
            }
            for d in decisions
        ]
    }


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: int, db: Session = Depends(get_db)):
    """Return complete decision state."""
    return _build_decision_detail(decision_id, db)


@router.post("/decisions/{decision_id}/refine")
def refine_decision(
    decision_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """Update alternatives and metric weights for a decision."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    alternatives: list[str] = body.get("alternatives", [])
    metrics_input: list[dict] = body.get("metrics", [])

    if not alternatives:
        raise HTTPException(
            status_code=422, detail="At least one alternative is required"
        )
    if not metrics_input:
        raise HTTPException(status_code=422, detail="At least one metric is required")

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

    # Create activities and weights
    new_activities = []
    for alt_name in alternatives:
        activity = Activity(
            name=alt_name,
            category=decision.category if decision.category else "General",
            decision_id=decision_id,
        )
        db.add(activity)
        db.flush()
        new_activities.append(activity)

        for mitem in metrics_input:
            aw = ActivityWeight(
                activity_id=activity.id,
                metric_id=mitem["metric_id"],
                weight=mitem.get("weight", 50),
            )
            db.add(aw)

    db.commit()

    # Build response with DB IDs
    metrics_db = (
        db.query(Metric)
        .filter(Metric.id.in_([m["metric_id"] for m in metrics_input]))
        .all()
    )
    metric_map = {m.id: m for m in metrics_db}

    criteria_result = []
    for mitem in metrics_input:
        m = metric_map.get(mitem["metric_id"])
        if m:
            criteria_result.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "weight": mitem.get("weight", 50),
                    "higher_is_better": m.higher_is_better,
                }
            )

    return {
        "activities": [{"id": a.id, "name": a.name} for a in new_activities],
        "criteria": criteria_result,
    }


@router.post("/decisions/{decision_id}/score")
def score_decision(
    decision_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """Submit scores and return results."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    scores_input: list[dict] = body.get("scores", [])

    if not scores_input:
        raise HTTPException(status_code=422, detail="At least one score is required")

    # Delete old scores
    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    for activity in activities:
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id == activity.id
        ).delete()
    db.flush()

    # Insert new scores
    for s in scores_input:
        alt_score = AlternativeScore(
            activity_id=s["activity_id"],
            metric_id=s["metric_id"],
            score=s["score"],
        )
        db.add(alt_score)
    db.commit()

    # Reload activities and metrics for the result
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
        db.query(Metric).filter(Metric.id.in_(metric_ids)).order_by(Metric.id).all()
        if metric_ids
        else []
    )

    # Compute fit scores
    results = compute_alternative_fit_scores(decision_id, db)
    metric_names = [m.name for m in metrics]

    # Build series
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

    # Significance
    significance = _significance_for_results(results, series, metrics)

    return {
        "results": results,
        "series": series,
        "metric_names": metric_names,
        "significance": significance,
    }


@router.post("/decisions/{decision_id}/thresholds")
def apply_thresholds(
    decision_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """Apply threshold filters. Store as JSON on decision."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    thresholds_input: list[dict] = body.get("thresholds", [])

    valid_operators = {"<=", ">=", "<", ">"}
    validated = []
    for t in thresholds_input:
        operator = t.get("operator", "<=")
        value = t.get("value")

        if operator not in valid_operators:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid operator '{operator}'. Must be one of: {', '.join(sorted(valid_operators))}",
            )
        if value is None:
            raise HTTPException(status_code=422, detail="Threshold value is required")
        try:
            value_float = float(value)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422, detail=f"Invalid threshold value '{value}'"
            )
        if value_float < 0.0 or value_float > 100.0:
            raise HTTPException(
                status_code=422,
                detail=f"Threshold value {value_float} is outside the 0–100 scale",
            )
        validated.append(
            {
                "metric_id": t["metric_id"],
                "operator": operator,
                "value": value_float,
            }
        )

    decision.thresholds = json.dumps(validated) if validated else None
    db.commit()

    # Compute filter result
    filter_result = filter_by_thresholds(decision_id, db) if validated else None

    # Build threshold_criteria
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

    threshold_criteria = []
    existing_by_metric = {}
    for t in validated:
        if isinstance(t, dict) and "metric_id" in t:
            existing_by_metric[t["metric_id"]] = t

    if metric_ids:
        metrics_in_use = db.query(Metric).filter(Metric.id.in_(metric_ids)).all()
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

    return {
        "filter_result": filter_result,
        "threshold_criteria": threshold_criteria,
    }


@router.post("/decisions/{decision_id}/thresholds/clear")
def clear_thresholds(decision_id: int, db: Session = Depends(get_db)):
    """Clear all threshold filters for a decision."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision.thresholds = None
    db.commit()

    return {"status": "cleared"}


@router.get("/evaluate/{decision_id}")
def get_evaluate(decision_id: int, db: Session = Depends(get_db)):
    """Same as GET /api/decisions/{id} but always includes dimension_scores and gap_analysis."""
    return _build_decision_detail(decision_id, db, force_dimension_scores=True)


@router.get("/rank/{decision_id}")
def get_rank(decision_id: int, db: Session = Depends(get_db)):
    """Same as GET /api/decisions/{id}."""
    return _build_decision_detail(decision_id, db)


@router.get("/screen/{decision_id}")
def get_screen(decision_id: int, db: Session = Depends(get_db)):
    """Same as GET /api/decisions/{id} but always computes filter_result."""
    return _build_decision_detail(decision_id, db, force_filter=True)


@router.get("/metrics")
def list_metrics(db: Session = Depends(get_db)):
    """List all metrics, grouped by dimension (category)."""
    all_metrics = db.query(Metric).order_by(Metric.category, Metric.name).all()

    grouped: dict[str, list] = {}
    for m in all_metrics:
        category = m.category or "General"
        if category not in grouped:
            grouped[category] = []
        entry = {
            "id": m.id,
            "name": m.name,
            "category": m.category,
            "description": m.description or "",
            "unit": m.unit or "",
            "higher_is_better": m.higher_is_better,
        }
        # Children (sub-metrics)
        children = []
        if m.children:
            for child in m.children:
                children.append(
                    {
                        "id": child.id,
                        "name": child.name,
                        "category": child.category,
                        "description": child.description or "",
                        "unit": child.unit or "",
                        "higher_is_better": child.higher_is_better,
                    }
                )
        if children:
            entry["children"] = children

        grouped[category].append(entry)

    return {"grouped_metrics": grouped}


@router.post("/metrics")
def create_metric(data: MetricCreate, db: Session = Depends(get_db)):
    """Create a new metric."""
    existing = db.query(Metric).filter(Metric.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Metric already exists")
    metric = Metric(**data.model_dump())
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return {"id": metric.id, "name": metric.name, "category": metric.category}


@router.put("/metrics/{metric_id}")
def update_metric(metric_id: int, data: MetricUpdate, db: Session = Depends(get_db)):
    """Update an existing metric."""
    metric = db.query(Metric).filter(Metric.id == metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(metric, key, value)
    db.commit()
    return {"id": metric.id, "name": metric.name}


@router.delete("/metrics/{metric_id}")
def delete_metric(metric_id: int, db: Session = Depends(get_db)):
    """Delete a metric and its related data."""
    metric = db.query(Metric).filter(Metric.id == metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    # Delete related activity weights
    db.query(ActivityWeight).filter(ActivityWeight.metric_id == metric_id).delete()
    # Delete sub-metrics first
    db.query(Metric).filter(Metric.parent_id == metric_id).delete()
    db.delete(metric)
    db.commit()
    return {"status": "deleted"}


@router.post("/decisions/{decision_id}/delete")
def delete_decision(decision_id: int, db: Session = Depends(get_db)):
    """Delete a decision and all associated data."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    # AlternativeScore is not in the ORM cascade chain, delete manually
    activity_ids = [a.id for a in decision.activities]
    if activity_ids:
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id.in_(activity_ids)
        ).delete()

    db.delete(decision)  # cascades to Activity → ActivityWeight
    db.commit()

    return {"status": "deleted"}
