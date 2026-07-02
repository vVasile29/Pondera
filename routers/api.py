"""Optium JSON API layer.

Deterministic MCDA decision engine. All endpoints under /api/*.
"""

import json
import math
import re

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
    evaluate_ko_criteria,
    filter_by_thresholds,
    gap_analysis,
    sanitize_persisted_ko_criteria,
    sanitize_persisted_thresholds,
)
from services.ontology import (
    RESERVED_LEGACY_METRIC_NAMES,
    ontology_metric_metadata,
    serialize_metric_metadata,
)

router = APIRouter(prefix="/api", tags=["api"])


# ── Shared helpers ──


def _robustness_for_results(
    decision_id: int, db: Session, results: list
) -> dict | None:
    activity_ids = [result["activity_id"] for result in results]
    return build_decision_robustness(decision_id, db, activity_ids=activity_ids)


def _parse_thresholds(decision: Decision, db: Session) -> list:
    # DB-safety layer for malformed persisted thresholds or manual edits.
    return sanitize_persisted_thresholds(decision.id, db)


def _parse_ko_criteria(decision: Decision, db: Session) -> list:
    # DB-safety layer for malformed persisted KO criteria or manual edits.
    return sanitize_persisted_ko_criteria(decision.id, db)


def _strip_custom_suffix(name: str) -> str:
    """Strip trailing '(custom)' or '(custom N)' suffix from a metric name."""
    stripped = re.sub(r'\s*\(custom(?:\s+\d+)?\)\s*$', '', name)
    return stripped.rstrip()


def _validate_metric_id(value, selected_metric_ids: set[int], label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{label} must be an integer")
    if value not in selected_metric_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Metric {value} is not selected for this decision",
        )
    return value


def _validate_score_value(value, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{label} must be numeric")
    value_float = float(value)
    if not math.isfinite(value_float):
        raise HTTPException(status_code=422, detail=f"{label} must be finite")
    if value_float < 0.0 or value_float > 100.0:
        raise HTTPException(
            status_code=422,
            detail=f"{label} {value_float} is outside the 0–100 scale",
        )
    return value_float


def _validate_metric_name_not_reserved(name: str) -> None:
    if name in RESERVED_LEGACY_METRIC_NAMES:
        raise HTTPException(
            status_code=422,
            detail="Metric name is reserved for legacy seed migration",
        )


MAX_METRIC_NAME_LENGTH = 255
MAX_METRIC_CATEGORY_LENGTH = 255


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
            "created_at": decision.created_at.isoformat()
            if decision.created_at
            else None,
        },
        "activities": [{"id": a.id, "name": a.name} for a in activities],
        "metrics": [serialize_metric_metadata(m) for m in metrics],
        "results": [],
        "series": [],
        "metric_names": [],
        "rows": [],
        "robustness": None,
        "dimension_scores": None,
        "gap_analysis": None,
        "filter_result": None,
        "threshold_criteria": [],
        "thresholds": [],
        "ko_criteria": [],
        "ko_result": None,
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
            "metric_question": serialize_metric_metadata(m)["question"],
            "metric_anchors": serialize_metric_metadata(m)["anchors"],
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

    # Evaluate KO criteria
    ko_criteria_raw = _parse_ko_criteria(decision, db)
    result["ko_criteria"] = ko_criteria_raw

    if ko_criteria_raw:
        ko_result = evaluate_ko_criteria(decision_id, db)
        result["ko_result"] = ko_result
        if ko_result and ko_result["eligible_activity_ids"]:
            eligible_set = set(ko_result["eligible_activity_ids"])
            result["results"] = [
                r for r in result["results"] if r["activity_id"] in eligible_set
            ]
            # Rebuild series for eligible only
            eligible_names = {
                a["activity_name"]
                for a in ko_result["results"]
                if a["status"] == "passed"
            }
            result["series"] = [
                s for s in result["series"] if s["name"] in eligible_names
            ]
            # Robustness on eligible only
            result["robustness"] = _robustness_for_results(
                decision_id, db, result["results"]
            )
        elif ko_result:
            # All knocked out
            result["results"] = []
            result["series"] = []
            result["robustness"] = None
    else:
        result["ko_result"] = None

    # Threshold filtering
    thresholds = _parse_thresholds(decision, db)
    result["thresholds"] = thresholds
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
                    "operator": existing_t.get("operator", ">="),
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
        all_metrics = db.query(Metric).filter(Metric.decision_id.is_(None)).all()
        default_weight_by_name = {m["name"]: m["default_weight"] for m in UNIVERSAL_METRICS}
        for metric in all_metrics:
            weight = default_weight_by_name.get(metric.name, 50)
            db.add(
                DecisionWeight(
                    decision_id=decision_id,
                    metric_id=metric.id,
                    weight=weight,
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
    ko_criteria_input = body.get("ko_criteria")

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
    db.flush()

    # ── KO criteria validation & storage ──
    selected_metric_ids = {m["metric_id"] for m in metrics_input}
    valid_ko_operators = {"<=", ">=", "<", ">"}

    if ko_criteria_input is not None:
        if not isinstance(ko_criteria_input, list):
            raise HTTPException(
                status_code=422,
                detail="ko_criteria must be a list",
            )

        validated_ko = []
        for kc in ko_criteria_input:
            if not isinstance(kc, dict):
                raise HTTPException(
                    status_code=422, detail="Each KO criterion must be an object"
                )

            metric_id = kc.get("metric_id")
            if not isinstance(metric_id, int) or isinstance(metric_id, bool):
                raise HTTPException(
                    status_code=422, detail="KO criterion metric_id must be an integer"
                )
            if metric_id not in selected_metric_ids:
                raise HTTPException(
                    status_code=422,
                    detail=f"KO criterion metric {metric_id} is not selected for this decision",
                )

            ko_operator = kc.get("ko_operator")
            ko_value = kc.get("ko_value")

            has_op = ko_operator is not None
            has_val = ko_value is not None

            if has_op != has_val:
                raise HTTPException(
                    status_code=422,
                    detail="ko_operator and ko_value must both be present or both absent",
                )

            if not has_op and not has_val:
                continue

            if not isinstance(ko_operator, str):
                raise HTTPException(
                    status_code=422,
                    detail="KO criterion ko_operator must be a string",
                )
            if ko_operator not in valid_ko_operators:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid KO operator '{ko_operator}'. Must be one of: {', '.join(sorted(valid_ko_operators))}",
                )

            try:
                ko_value_float = float(ko_value)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid KO value '{ko_value}'",
                )
            if not math.isfinite(ko_value_float):
                raise HTTPException(
                    status_code=422, detail="KO value must be finite"
                )
            if ko_value_float < 0.0 or ko_value_float > 100.0:
                raise HTTPException(
                    status_code=422,
                    detail=f"KO value {ko_value_float} is outside the 0–100 scale",
                )

            validated_ko.append(
                {
                    "metric_id": metric_id,
                    "ko_operator": ko_operator,
                    "ko_value": ko_value_float,
                }
            )

        decision.ko_criteria = json.dumps(validated_ko) if validated_ko else None
    # else: ko_criteria_input is None, leave existing KO criteria unchanged

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
                    **serialize_metric_metadata(m),
                    "weight": mitem.get("weight", 50),
                }
            )

    # Read back stored KO criteria for response
    stored_ko = []
    if decision.ko_criteria:
        try:
            stored_ko = json.loads(decision.ko_criteria)
        except (json.JSONDecodeError, TypeError):
            stored_ko = []

    return {
        "activities": [{"id": a.id, "name": a.name} for a in new_activities],
        "criteria": criteria_result,
        "ko_criteria": stored_ko,
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

    scores_input = body.get("scores", [])

    if not scores_input:
        raise HTTPException(status_code=422, detail="At least one score is required")
    if not isinstance(scores_input, list):
        raise HTTPException(status_code=422, detail="Scores must be a list")

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    activity_ids = {activity.id for activity in activities}
    selected_metric_ids = {
        dw.metric_id
        for dw in db.query(DecisionWeight)
        .filter(DecisionWeight.decision_id == decision_id)
        .all()
    }

    validated_scores = []
    seen_scores = set()
    for s in scores_input:
        if not isinstance(s, dict):
            raise HTTPException(status_code=422, detail="Each score must be an object")
        if "activity_id" not in s:
            raise HTTPException(status_code=422, detail="Score activity_id is required")
        if "metric_id" not in s:
            raise HTTPException(status_code=422, detail="Score metric_id is required")
        if "score" not in s:
            raise HTTPException(status_code=422, detail="Score value is required")

        activity_id = s["activity_id"]
        if not isinstance(activity_id, int) or isinstance(activity_id, bool):
            raise HTTPException(status_code=422, detail="activity_id must be an integer")
        if activity_id not in activity_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Activity {activity_id} does not belong to this decision",
            )

        metric_id = _validate_metric_id(s["metric_id"], selected_metric_ids, "metric_id")
        score = _validate_score_value(s["score"], "Score")
        score_key = (activity_id, metric_id)
        if score_key in seen_scores:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate score for activity {activity_id} and metric {metric_id}",
            )
        seen_scores.add(score_key)
        validated_scores.append(
            {"activity_id": activity_id, "metric_id": metric_id, "score": score}
        )

    for activity in activities:
        db.query(AlternativeScore).filter(
            AlternativeScore.activity_id == activity.id
        ).delete()
    db.flush()

    for s in validated_scores:
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

    thresholds_input = body.get("thresholds", [])
    if not isinstance(thresholds_input, list):
        raise HTTPException(status_code=422, detail="Thresholds must be a list")

    selected_metric_ids = {
        dw.metric_id
        for dw in db.query(DecisionWeight)
        .filter(DecisionWeight.decision_id == decision_id)
        .all()
    }

    # Request-boundary validation: reject malformed threshold payloads before persisting.
    valid_operators = {"<=", ">=", "<", ">"}
    validated = []
    for t in thresholds_input:
        if not isinstance(t, dict):
            raise HTTPException(status_code=422, detail="Each threshold must be an object")
        if "metric_id" not in t:
            raise HTTPException(status_code=422, detail="Threshold metric_id is required")
        operator = t.get("operator", ">=")
        value = t.get("value")
        metric_id = _validate_metric_id(
            t.get("metric_id"), selected_metric_ids, "metric_id"
        )

        if not isinstance(operator, str):
            raise HTTPException(status_code=422, detail="Threshold operator must be a string")
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
        if not math.isfinite(value_float):
            raise HTTPException(status_code=422, detail="Threshold value must be finite")
        if value_float < 0.0 or value_float > 100.0:
            raise HTTPException(
                status_code=422,
                detail=f"Threshold value {value_float} is outside the 0–100 scale",
            )
        validated.append(
            {
                "metric_id": metric_id,
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
                    "operator": existing_t.get("operator", ">="),
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
    """List all metrics, grouped by dimension (category).

    Stale duplicate metrics (rows whose name is a built-in metric
    with a '(custom)' suffix from seed reconciliation) are filtered
    out so only one canonical row per built-in metric appears.
    """
    all_metrics = (
        db.query(Metric)
        .filter(Metric.decision_id.is_(None))
        .order_by(Metric.category, Metric.name)
        .all()
    )

    grouped: dict[str, list] = {}
    for m in all_metrics:
        # Filter out stale (custom) duplicates of built-in metrics
        if ontology_metric_metadata(m.name) is None:
            base = _strip_custom_suffix(m.name)
            if ontology_metric_metadata(base) is not None:
                continue

        category = m.category or "General"
        if category not in grouped:
            grouped[category] = []
        grouped[category].append(serialize_metric_metadata(m))

    return {"grouped_metrics": grouped}


def custom_metric_serializer(metric: Metric) -> dict:
    """Serialize a custom metric using the scope-aware serializer."""
    return serialize_metric_metadata(metric)


@router.post("/decisions/{decision_id}/custom-metrics", status_code=201)
def create_custom_metric(
    decision_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """Create a decision-scoped custom metric."""
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    name = body.get("name")
    category = body.get("category")
    description = body.get("description", "")

    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=422, detail="Metric name is required")
    if not isinstance(category, str) or not category.strip():
        raise HTTPException(status_code=422, detail="Metric category is required")
    if not isinstance(description, str):
        description = ""

    name = name.strip()
    category = category.strip()

    if len(name) > MAX_METRIC_NAME_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Metric name must not exceed {MAX_METRIC_NAME_LENGTH} characters"
        )
    if len(category) > MAX_METRIC_CATEGORY_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Category must not exceed {MAX_METRIC_CATEGORY_LENGTH} characters"
        )

    _validate_metric_name_not_reserved(name)

    existing = (
        db.query(Metric)
        .filter(Metric.name == name, Metric.decision_id == decision_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=422,
            detail="A metric with this name already exists in this decision",
        )

    metric = Metric(
        name=name,
        category=category,
        description=description,
        scope="decision",
        source="user",
        decision_id=decision_id,
    )
    db.add(metric)
    db.flush()

    # Auto-create DecisionWeight with default weight 50
    dw = DecisionWeight(
        decision_id=decision_id,
        metric_id=metric.id,
        weight=50.0,
    )
    db.add(dw)
    db.commit()
    db.refresh(metric)

    return custom_metric_serializer(metric)


@router.put("/decisions/{decision_id}/custom-metrics/{metric_id}")
def update_custom_metric(
    decision_id: int,
    metric_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """Update a decision-scoped custom metric."""
    metric = (
        db.query(Metric)
        .filter(
            Metric.id == metric_id,
            Metric.decision_id == decision_id,
            Metric.scope == "decision",
        )
        .first()
    )
    if not metric:
        raise HTTPException(status_code=404, detail="Custom metric not found")

    name = body.get("name")
    category = body.get("category")
    description = body.get("description")

    if name is not None:
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=422, detail="Metric name is required")
        name = name.strip()
        if len(name) > MAX_METRIC_NAME_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Metric name must not exceed {MAX_METRIC_NAME_LENGTH} characters"
            )
        _validate_metric_name_not_reserved(name)
        if name != metric.name:
            existing = (
                db.query(Metric)
                .filter(Metric.name == name, Metric.decision_id == decision_id)
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=422,
                    detail="A metric with this name already exists in this decision",
                )
        metric.name = name

    if category is not None:
        if not isinstance(category, str) or not category.strip():
            raise HTTPException(status_code=422, detail="Metric category is required")
        category = category.strip()
        if len(category) > MAX_METRIC_CATEGORY_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Category must not exceed {MAX_METRIC_CATEGORY_LENGTH} characters"
            )
        metric.category = category

    if description is not None:
        if not isinstance(description, str):
            description = ""
        metric.description = description

    db.commit()
    db.refresh(metric)
    return custom_metric_serializer(metric)


@router.delete("/decisions/{decision_id}/custom-metrics/{metric_id}")
def delete_custom_metric(
    decision_id: int,
    metric_id: int,
    db: Session = Depends(get_db),
):
    """Delete a decision-scoped custom metric. FK cascade handles weights and scores."""
    metric = (
        db.query(Metric)
        .filter(
            Metric.id == metric_id,
            Metric.decision_id == decision_id,
            Metric.scope == "decision",
        )
        .first()
    )
    if not metric:
        raise HTTPException(status_code=404, detail="Custom metric not found")

    db.delete(metric)
    db.commit()
    return {"status": "deleted"}


@router.post("/metrics", status_code=201)
def create_metric(body: dict, db: Session = Depends(get_db)):
    name = body.get("name")
    category = body.get("category")
    description = body.get("description", "")

    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=422, detail="Metric name is required")
    if not isinstance(category, str) or not category.strip():
        raise HTTPException(status_code=422, detail="Metric category is required")
    if not isinstance(description, str):
        description = ""

    name = name.strip()
    category = category.strip()

    if len(name) > MAX_METRIC_NAME_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Metric name must not exceed {MAX_METRIC_NAME_LENGTH} characters"
        )
    if len(category) > MAX_METRIC_CATEGORY_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Category must not exceed {MAX_METRIC_CATEGORY_LENGTH} characters"
        )

    _validate_metric_name_not_reserved(name)

    existing = (
        db.query(Metric)
        .filter(Metric.name == name, Metric.decision_id.is_(None))
        .first()
    )
    if existing:
        raise HTTPException(status_code=422, detail="Metric with this name already exists")

    metric = Metric(
        name=name,
        category=category,
        description=description,
        scope="global",
        source="user",
    )
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return serialize_metric_metadata(metric)


@router.put("/metrics/{metric_id}")
def update_metric(metric_id: int, body: dict, db: Session = Depends(get_db)):
    metric = db.query(Metric).filter(
        Metric.id == metric_id,
        Metric.decision_id.is_(None)
    ).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    name = body.get("name")
    category = body.get("category")
    description = body.get("description")

    if name is not None:
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=422, detail="Metric name is required")
        name = name.strip()
        if len(name) > MAX_METRIC_NAME_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Metric name must not exceed {MAX_METRIC_NAME_LENGTH} characters"
            )
        _validate_metric_name_not_reserved(name)
        if name != metric.name:
            existing = (
                db.query(Metric)
                .filter(Metric.name == name, Metric.decision_id.is_(None), Metric.id != metric_id)
                .first()
            )
            if existing:
                raise HTTPException(status_code=422, detail="Metric with this name already exists")
        metric.name = name

    if category is not None:
        if not isinstance(category, str) or not category.strip():
            raise HTTPException(status_code=422, detail="Metric category is required")
        category = category.strip()
        if len(category) > MAX_METRIC_CATEGORY_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Category must not exceed {MAX_METRIC_CATEGORY_LENGTH} characters"
            )
        metric.category = category

    if description is not None:
        if not isinstance(description, str):
            description = ""
        metric.description = description

    db.commit()
    db.refresh(metric)
    return serialize_metric_metadata(metric)


@router.delete("/metrics/{metric_id}")
def delete_metric(metric_id: int, db: Session = Depends(get_db)):
    metric = db.query(Metric).filter(
        Metric.id == metric_id,
        Metric.decision_id.is_(None)
    ).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    # FK cascade (ondelete="CASCADE") handles DecisionWeight and AlternativeScore rows
    db.delete(metric)
    db.commit()
    return {"status": "deleted"}


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
