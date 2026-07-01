"""Optium JSON API layer.

Deterministic MCDA decision engine. All endpoints under /api/*.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from models import Activity, DecisionWeight, AlternativeScore, Decision, Metric
from services.decision_limits import enforce_decision_size
from services.export import generate_markdown_brief, get_decision_export_data
from services.robustness import build_decision_robustness
from services.scoring import (
    compute_alternative_fit_scores,
    compute_dimension_scores,
    filter_by_thresholds,
    gap_analysis,
)

router = APIRouter(prefix="/api", tags=["api"])


# ── Shared helpers ──


def _robustness_for_results(
    decision_id: int, db: Session, results: list
) -> dict | None:
    activity_ids = [result["activity_id"] for result in results]
    return build_decision_robustness(decision_id, db, activity_ids=activity_ids)


def _parse_thresholds(decision: Decision) -> list:
    if not decision.thresholds:
        return []
    try:
        return json.loads(decision.thresholds)
    except (json.JSONDecodeError, TypeError):
        return []


def _build_decision_detail(decision_id: int, db: Session) -> dict:
    """Assemble the full decision detail JSON."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()

    # Get metrics from DecisionWeight for this decision
    metric_ids = set()
    for dw in (
        db.query(DecisionWeight).filter(DecisionWeight.decision_id == decision_id).all()
    ):
        metric_ids.add(dw.metric_id)
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
        "robustness": None,
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
        dw = (
            db.query(DecisionWeight)
            .filter(
                DecisionWeight.decision_id == decision_id,
                DecisionWeight.metric_id == m.id,
            )
            .first()
        )
        if dw:
            weight = dw.weight

        row = {
            "metric_id": m.id,
            "metric_name": m.name,
            "metric_desc": m.description or "",
            "higher_is_better": m.higher_is_better,
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

    # Dimension scores + gap analysis (for diagnose mode)
    mode = decision.mode if decision.mode else "choose"
    if mode == "diagnose":
        dim_scores = compute_dimension_scores(decision_id, db)
        result["dimension_scores"] = dim_scores
        result["gap_analysis"] = gap_analysis(dim_scores) if dim_scores else None

    result["robustness"] = _robustness_for_results(decision_id, db, results)
    result["significance"] = None

    # Threshold filtering
    thresholds = _parse_thresholds(decision)
    if thresholds:
        filter_result = filter_by_thresholds(decision_id, db)
        result["filter_result"] = filter_result
        result["robustness"] = _robustness_for_results(
            decision_id, db, filter_result.get("survivor_results", [])
        )

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
    """Parse a free-text question, create decision + activities, return decision_id."""
    from services.ontology import UNIVERSAL_METRICS
    from services.parser import extract_list, extract_subject, parse_question

    query = (body.get("q") or "").strip()

    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # ── Helper: seed default weights for a decision (decision-level) ──
    def _seed_default_weights(decision_id: int) -> None:
        existing = (
            db.query(DecisionWeight)
            .filter(DecisionWeight.decision_id == decision_id)
            .first()
        )
        if existing:
            return
        all_metrics = db.query(Metric).all()
        metric_map = {m.name: m for m in all_metrics}
        for m in UNIVERSAL_METRICS:
            metric = metric_map.get(m["name"])
            if metric:
                db.add(
                    DecisionWeight(
                        decision_id=decision_id,
                        metric_id=metric.id,
                        weight=m["default_weight"],
                    )
                )

    # ── Heuristic routing (auto-detect mode from query) ──
    parsed = parse_question(query)
    alternatives = parsed["alternatives"]
    category = parsed["category"]
    is_parsed = parsed["parsed"]

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
            _seed_default_weights(decision.id)
            db.commit()

            return {
                "decision_id": decision.id,
                "mode": "diagnose",
                "next": "review",
            }

        list_parsed = extract_list(query)
        if list_parsed["parsed"]:
            enforce_decision_size(
                len(list_parsed["alternatives"]), len(UNIVERSAL_METRICS)
            )
            decision = Decision(query=query, category="General", mode="rank")
            db.add(decision)
            db.flush()

            for name in list_parsed["alternatives"]:
                activity = Activity(
                    name=name, category="General", decision_id=decision.id
                )
                db.add(activity)
                db.flush()
            _seed_default_weights(decision.id)

            db.commit()
            return {
                "decision_id": decision.id,
                "mode": "rank",
                "next": "review",
            }

    enforce_decision_size(len(alternatives), len(UNIVERSAL_METRICS))
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
    _seed_default_weights(decision.id)

    db.commit()

    return {
        "decision_id": decision.id,
        "mode": decision.mode if decision.mode else "choose",
        "next": "review",
    }


@router.get("/decisions")
def list_decisions(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List decisions ordered by created_at desc."""
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
            }
            for d in decisions
        ]
    }


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: int, db: Session = Depends(get_db)):
    """Return complete decision state including results, series, robustness."""
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
    enforce_decision_size(len(alternatives), len(metrics_input))

    db.query(DecisionWeight).filter(DecisionWeight.decision_id == decision_id).delete()
    for activity in decision.activities:
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id == activity.id
        ).delete()
        db.delete(activity)
    db.flush()

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
        dw = DecisionWeight(
            decision_id=decision_id,
            metric_id=mitem["metric_id"],
            weight=mitem.get("weight", 50),
        )
        db.add(dw)

    db.commit()

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

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    for activity in activities:
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id == activity.id
        ).delete()
    db.flush()

    for s in scores_input:
        alt_score = AlternativeScore(
            activity_id=s["activity_id"],
            metric_id=s["metric_id"],
            score=s["score"],
        )
        db.add(alt_score)
    db.commit()

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    metric_ids = set()
    for dw in (
        db.query(DecisionWeight).filter(DecisionWeight.decision_id == decision_id).all()
    ):
        metric_ids.add(dw.metric_id)
    metrics = (
        db.query(Metric).filter(Metric.id.in_(metric_ids)).order_by(Metric.id).all()
        if metric_ids
        else []
    )

    results = compute_alternative_fit_scores(decision_id, db)
    metric_names = [m.name for m in metrics]

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

    robustness = _robustness_for_results(decision_id, db, results)

    return {
        "results": results,
        "series": series,
        "metric_names": metric_names,
        "robustness": robustness,
        "significance": None,
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

    filter_result = filter_by_thresholds(decision_id, db) if validated else None

    metric_ids = set()
    for dw in (
        db.query(DecisionWeight).filter(DecisionWeight.decision_id == decision_id).all()
    ):
        metric_ids.add(dw.metric_id)

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


@router.get("/decisions/{decision_id}/export-markdown")
def export_decision_markdown(decision_id: int, db: Session = Depends(get_db)):
    """Export a decision brief as a downloadable Markdown file."""
    data = get_decision_export_data(decision_id, db)
    if not data:
        raise HTTPException(status_code=404, detail="Decision not found")
    markdown = generate_markdown_brief(data)
    return Response(
        content=markdown,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="decision-{decision_id}-brief.md"'
        },
    )


@router.get("/metrics")
def list_metrics(db: Session = Depends(get_db)):
    """List all metrics, grouped by dimension (category)."""
    all_metrics = db.query(Metric).order_by(Metric.category, Metric.name).all()

    grouped: dict[str, list] = {}
    for m in all_metrics:
        category = m.category or "General"
        if category not in grouped:
            grouped[category] = []
        grouped[category].append(
            {
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "description": m.description or "",
                "higher_is_better": m.higher_is_better,
            }
        )

    return {"grouped_metrics": grouped}


@router.post("/decisions/{decision_id}/delete")
def delete_decision(decision_id: int, db: Session = Depends(get_db)):
    """Delete a decision and all associated data."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    activity_ids = [a.id for a in decision.activities]
    if activity_ids:
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id.in_(activity_ids)
        ).delete()

    db.delete(decision)
    db.commit()

    return {"status": "deleted"}
