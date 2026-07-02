"""Optium JSON API layer.

Deterministic MCDA decision engine. All endpoints under /api/*.
"""

import json
import math
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Activity,
    DecisionWeight,
    AlternativeScore,
    Decision,
    Metric,
    EvidenceItem,
    ScoreDraft,
    ScoreDraftEvidence,
)
from services.ai_decision import (
    AIProviderOutputError,
    AIUnavailableError,
    OpenAIDecisionClient,
    ai_status,
    build_decision_context,
    get_ai_caps,
)
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
MAX_EVIDENCE_CLAIM_LENGTH = 1000
MAX_RATIONALE_LENGTH = 2000
MAX_SOURCE_LABEL_LENGTH = 120
MAX_SOURCE_URL_LENGTH = 1000
EVIDENCE_SOURCE_TYPES = {"human", "llm", "api", "document", "system"}
EVIDENCE_REVIEW_STATUSES = {"pending", "approved", "rejected"}
EVIDENCE_POLARITIES = {"positive", "negative", "neutral", "mixed"}
DRAFT_SOURCE_TYPES = {"llm", "human", "system"}
DRAFT_STATUSES = {"pending", "approved", "edited", "rejected", "applied"}
DRAFT_MUTABLE_STATUSES = {"pending", "approved", "edited"}
AI_EVIDENCE_REVIEW_POLICIES = {"approved_only", "approved_and_pending"}


def _string_field(value, label: str, max_length: int, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise HTTPException(status_code=422, detail=f"{label} is required")
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{label} must be a string")
    value = value.strip()
    if required and not value:
        raise HTTPException(status_code=422, detail=f"{label} is required")
    if len(value) > max_length:
        raise HTTPException(status_code=422, detail=f"{label} must not exceed {max_length} characters")
    return value


def _enum_field(value, allowed: set[str], label: str, default: str | None = None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise HTTPException(status_code=422, detail=f"Invalid {label}")
    return value


def _validate_confidence(value, label: str = "confidence") -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0 or result > 1.0:
        raise HTTPException(status_code=422, detail=f"{label} must be between 0 and 1")
    return result


def _validate_ai_max_field(body: dict, field: str, cap: int) -> int:
    value = body.get(field)
    if value is None:
        return cap
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{field} must be an integer")
    if value < 1 or value > cap:
        raise HTTPException(status_code=422, detail=f"{field} must be between 1 and {cap}")
    return value


def _validate_ai_id_filter(body: dict, field: str, allowed_ids: set[int]) -> set[int]:
    values = body.get(field)
    if values is None:
        return set(allowed_ids)
    if not isinstance(values, list) or not values:
        raise HTTPException(status_code=422, detail=f"{field} must be a non-empty list")
    result = set()
    for value in values:
        if not isinstance(value, int) or isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"{field} must contain integers")
        if value not in allowed_ids:
            raise HTTPException(status_code=422, detail=f"{field} contains IDs outside this decision")
        result.add(value)
    return result


def _validate_ai_bool_field(body: dict, field: str, default: bool) -> bool:
    value = body.get(field, default)
    if not isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{field} must be a boolean")
    return value


def _provider_float(value, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _get_decision_or_404(decision_id: int, db: Session) -> Decision:
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision


def _decision_activity_ids(decision_id: int, db: Session) -> set[int]:
    return {a.id for a in db.query(Activity).filter(Activity.decision_id == decision_id).all()}


def _decision_metric_ids(decision_id: int, db: Session) -> set[int]:
    return {dw.metric_id for dw in db.query(DecisionWeight).filter(DecisionWeight.decision_id == decision_id).all()}


def _optional_scoped_activity(value, decision_id: int, db: Session) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=422, detail="activity_id must be an integer")
    if value not in _decision_activity_ids(decision_id, db):
        raise HTTPException(status_code=422, detail="activity_id does not belong to this decision")
    return value


def _optional_scoped_metric(value, decision_id: int, db: Session) -> int | None:
    if value is None:
        return None
    return _validate_metric_id(value, _decision_metric_ids(decision_id, db), "metric_id")


def _evidence_serializer(item: EvidenceItem) -> dict:
    return {
        "id": item.id,
        "decision_id": item.decision_id,
        "activity_id": item.activity_id,
        "metric_id": item.metric_id,
        "claim": item.claim,
        "rationale": item.rationale,
        "source_type": item.source_type,
        "source_label": item.source_label,
        "source_url": item.source_url,
        "confidence": item.confidence,
        "polarity": item.polarity,
        "review_status": item.review_status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _draft_evidence_ids(draft_id: int, db: Session) -> list[int]:
    rows = db.query(ScoreDraftEvidence).filter(ScoreDraftEvidence.score_draft_id == draft_id).all()
    return [row.evidence_item_id for row in rows]


def _draft_serializer(draft: ScoreDraft, db: Session) -> dict:
    effective_score = draft.human_adjusted_score if draft.human_adjusted_score is not None else draft.suggested_score
    return {
        "id": draft.id,
        "decision_id": draft.decision_id,
        "activity_id": draft.activity_id,
        "metric_id": draft.metric_id,
        "suggested_score": draft.suggested_score,
        "human_adjusted_score": draft.human_adjusted_score,
        "effective_score": effective_score,
        "rationale": draft.rationale,
        "source_type": draft.source_type,
        "source_label": draft.source_label,
        "confidence": draft.confidence,
        "status": draft.status,
        "evidence_ids": _draft_evidence_ids(draft.id, db),
        "applied_score_id": draft.applied_score_id,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        "applied_at": draft.applied_at.isoformat() if draft.applied_at else None,
    }


def _get_evidence_or_404(decision_id: int, evidence_id: int, db: Session) -> EvidenceItem:
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id, EvidenceItem.decision_id == decision_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    return item


def _get_draft_or_404(decision_id: int, draft_id: int, db: Session) -> ScoreDraft:
    draft = db.query(ScoreDraft).filter(ScoreDraft.id == draft_id, ScoreDraft.decision_id == decision_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Score draft not found")
    return draft


def _ensure_draft_mutable(draft: ScoreDraft) -> None:
    if draft.status not in DRAFT_MUTABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Score draft is immutable")


def _set_draft_evidence(draft: ScoreDraft, evidence_ids: list, db: Session) -> None:
    db.query(ScoreDraftEvidence).filter(ScoreDraftEvidence.score_draft_id == draft.id).delete()
    seen = set()
    for evidence_id in evidence_ids or []:
        if not isinstance(evidence_id, int) or isinstance(evidence_id, bool):
            raise HTTPException(status_code=422, detail="evidence_ids must contain integers")
        if evidence_id in seen:
            continue
        evidence = _get_evidence_or_404(draft.decision_id, evidence_id, db)
        if evidence.activity_id is not None and evidence.activity_id != draft.activity_id:
            raise HTTPException(status_code=422, detail="Evidence activity scope does not match draft")
        if evidence.metric_id is not None and evidence.metric_id != draft.metric_id:
            raise HTTPException(status_code=422, detail="Evidence metric scope does not match draft")
        db.add(ScoreDraftEvidence(score_draft_id=draft.id, evidence_item_id=evidence_id))
        seen.add(evidence_id)


def _set_ai_draft_evidence(
    draft: ScoreDraft,
    evidence_ids: list,
    allowed_evidence_statuses: set[str],
    db: Session,
) -> None:
    if not isinstance(evidence_ids, list):
        raise ValueError("evidence_ids must be a list")
    db.query(ScoreDraftEvidence).filter(ScoreDraftEvidence.score_draft_id == draft.id).delete()
    seen = set()
    for evidence_id in evidence_ids:
        if not isinstance(evidence_id, int) or isinstance(evidence_id, bool):
            raise ValueError("evidence_ids must contain integers")
        if evidence_id in seen:
            continue
        evidence = _get_evidence_or_404(draft.decision_id, evidence_id, db)
        if evidence.review_status not in allowed_evidence_statuses:
            raise ValueError("Evidence review status is not allowed by evidence_review_policy")
        if evidence.activity_id is not None and evidence.activity_id != draft.activity_id:
            raise ValueError("Evidence activity scope does not match draft")
        if evidence.metric_id is not None and evidence.metric_id != draft.metric_id:
            raise ValueError("Evidence metric scope does not match draft")
        db.add(ScoreDraftEvidence(score_draft_id=draft.id, evidence_item_id=evidence_id))
        seen.add(evidence_id)


def _apply_draft(draft: ScoreDraft, db: Session) -> AlternativeScore:
    _ensure_draft_mutable(draft)
    if draft.activity_id not in _decision_activity_ids(draft.decision_id, db):
        raise HTTPException(status_code=422, detail="Draft activity is outside decision scope")
    if draft.metric_id not in _decision_metric_ids(draft.decision_id, db):
        raise HTTPException(status_code=422, detail="Draft metric is outside decision scope")
    score_value = draft.human_adjusted_score if draft.human_adjusted_score is not None else draft.suggested_score
    score_value = _validate_score_value(score_value, "Draft score")
    score = db.query(AlternativeScore).filter(AlternativeScore.activity_id == draft.activity_id, AlternativeScore.metric_id == draft.metric_id).first()
    if score:
        score.score = score_value
    else:
        score = AlternativeScore(activity_id=draft.activity_id, metric_id=draft.metric_id, score=score_value)
        db.add(score)
        db.flush()
    draft.status = "applied"
    draft.applied_score_id = score.id
    draft.applied_at = datetime.utcnow()
    return score


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


@router.get("/ai/status")
def get_ai_status():
    return ai_status()


@router.get("/decisions/{decision_id}/evidence")
def list_evidence(
    decision_id: int,
    activity_id: int | None = None,
    metric_id: int | None = None,
    review_status: str | None = None,
    source_type: str | None = None,
    db: Session = Depends(get_db),
):
    _get_decision_or_404(decision_id, db)
    query = db.query(EvidenceItem).filter(EvidenceItem.decision_id == decision_id)
    if activity_id is not None:
        query = query.filter(EvidenceItem.activity_id == _optional_scoped_activity(activity_id, decision_id, db))
    if metric_id is not None:
        query = query.filter(EvidenceItem.metric_id == _optional_scoped_metric(metric_id, decision_id, db))
    if review_status is not None:
        query = query.filter(EvidenceItem.review_status == _enum_field(review_status, EVIDENCE_REVIEW_STATUSES, "review_status"))
    if source_type is not None:
        query = query.filter(EvidenceItem.source_type == _enum_field(source_type, EVIDENCE_SOURCE_TYPES, "source_type"))
    return {"evidence": [_evidence_serializer(item) for item in query.order_by(EvidenceItem.id).all()]}


@router.post("/decisions/{decision_id}/evidence", status_code=201)
def create_evidence(decision_id: int, body: dict, db: Session = Depends(get_db)):
    _get_decision_or_404(decision_id, db)
    source_type = _enum_field(body.get("source_type"), EVIDENCE_SOURCE_TYPES, "source_type", "human")
    if source_type != "human":
        raise HTTPException(status_code=422, detail="Manual evidence source_type must be human")
    item = EvidenceItem(
        decision_id=decision_id,
        activity_id=_optional_scoped_activity(body.get("activity_id"), decision_id, db),
        metric_id=_optional_scoped_metric(body.get("metric_id"), decision_id, db),
        claim=_string_field(body.get("claim"), "claim", MAX_EVIDENCE_CLAIM_LENGTH, True),
        rationale=_string_field(body.get("rationale"), "rationale", MAX_RATIONALE_LENGTH),
        source_type=source_type,
        source_label=_string_field(body.get("source_label"), "source_label", MAX_SOURCE_LABEL_LENGTH),
        source_url=_string_field(body.get("source_url"), "source_url", MAX_SOURCE_URL_LENGTH),
        confidence=_validate_confidence(body.get("confidence")),
        polarity=_enum_field(body.get("polarity"), EVIDENCE_POLARITIES, "polarity"),
        review_status=_enum_field(body.get("review_status"), EVIDENCE_REVIEW_STATUSES, "review_status", "pending"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _evidence_serializer(item)


@router.patch("/decisions/{decision_id}/evidence/{evidence_id}")
def update_evidence(decision_id: int, evidence_id: int, body: dict, db: Session = Depends(get_db)):
    item = _get_evidence_or_404(decision_id, evidence_id, db)
    if "activity_id" in body:
        item.activity_id = _optional_scoped_activity(body.get("activity_id"), decision_id, db)
    if "metric_id" in body:
        item.metric_id = _optional_scoped_metric(body.get("metric_id"), decision_id, db)
    if "claim" in body:
        item.claim = _string_field(body.get("claim"), "claim", MAX_EVIDENCE_CLAIM_LENGTH, True)
    if "rationale" in body:
        item.rationale = _string_field(body.get("rationale"), "rationale", MAX_RATIONALE_LENGTH)
    if "source_label" in body:
        item.source_label = _string_field(body.get("source_label"), "source_label", MAX_SOURCE_LABEL_LENGTH)
    if "source_url" in body:
        item.source_url = _string_field(body.get("source_url"), "source_url", MAX_SOURCE_URL_LENGTH)
    if "confidence" in body:
        item.confidence = _validate_confidence(body.get("confidence"))
    if "polarity" in body:
        item.polarity = _enum_field(body.get("polarity"), EVIDENCE_POLARITIES, "polarity")
    if "review_status" in body:
        item.review_status = _enum_field(body.get("review_status"), EVIDENCE_REVIEW_STATUSES, "review_status")
    db.commit()
    db.refresh(item)
    return _evidence_serializer(item)


@router.post("/decisions/{decision_id}/evidence/{evidence_id}/approve")
def approve_evidence(decision_id: int, evidence_id: int, db: Session = Depends(get_db)):
    item = _get_evidence_or_404(decision_id, evidence_id, db)
    item.review_status = "approved"
    db.commit()
    db.refresh(item)
    return _evidence_serializer(item)


@router.post("/decisions/{decision_id}/evidence/{evidence_id}/reject")
def reject_evidence(decision_id: int, evidence_id: int, db: Session = Depends(get_db)):
    item = _get_evidence_or_404(decision_id, evidence_id, db)
    item.review_status = "rejected"
    db.commit()
    db.refresh(item)
    return _evidence_serializer(item)


@router.delete("/decisions/{decision_id}/evidence/{evidence_id}")
def delete_evidence(decision_id: int, evidence_id: int, db: Session = Depends(get_db)):
    item = _get_evidence_or_404(decision_id, evidence_id, db)
    db.delete(item)
    db.commit()
    return {"status": "deleted"}


@router.get("/decisions/{decision_id}/score-drafts")
def list_score_drafts(
    decision_id: int,
    status: str | None = None,
    activity_id: int | None = None,
    metric_id: int | None = None,
    source_type: str | None = None,
    db: Session = Depends(get_db),
):
    _get_decision_or_404(decision_id, db)
    query = db.query(ScoreDraft).filter(ScoreDraft.decision_id == decision_id)
    if status is not None:
        query = query.filter(ScoreDraft.status == _enum_field(status, DRAFT_STATUSES, "status"))
    if activity_id is not None:
        query = query.filter(ScoreDraft.activity_id == _optional_scoped_activity(activity_id, decision_id, db))
    if metric_id is not None:
        query = query.filter(ScoreDraft.metric_id == _optional_scoped_metric(metric_id, decision_id, db))
    if source_type is not None:
        query = query.filter(ScoreDraft.source_type == _enum_field(source_type, DRAFT_SOURCE_TYPES, "source_type"))
    return {"drafts": [_draft_serializer(draft, db) for draft in query.order_by(ScoreDraft.id).all()]}


@router.post("/decisions/{decision_id}/score-drafts", status_code=201)
def create_score_draft(decision_id: int, body: dict, db: Session = Depends(get_db)):
    _get_decision_or_404(decision_id, db)
    source_type = _enum_field(body.get("source_type"), DRAFT_SOURCE_TYPES, "source_type", "human")
    if source_type != "human":
        raise HTTPException(status_code=422, detail="Manual score draft source_type must be human")
    draft = ScoreDraft(
        decision_id=decision_id,
        activity_id=_optional_scoped_activity(body.get("activity_id"), decision_id, db),
        metric_id=_optional_scoped_metric(body.get("metric_id"), decision_id, db),
        suggested_score=_validate_score_value(body.get("suggested_score"), "suggested_score"),
        rationale=_string_field(body.get("rationale"), "rationale", MAX_RATIONALE_LENGTH),
        source_type=source_type,
        source_label=_string_field(body.get("source_label"), "source_label", MAX_SOURCE_LABEL_LENGTH),
        confidence=_validate_confidence(body.get("confidence")),
        status="pending",
    )
    if draft.activity_id is None or draft.metric_id is None:
        raise HTTPException(status_code=422, detail="activity_id and metric_id are required")
    db.add(draft)
    db.flush()
    _set_draft_evidence(draft, body.get("evidence_ids", []), db)
    db.commit()
    db.refresh(draft)
    return _draft_serializer(draft, db)


@router.patch("/decisions/{decision_id}/score-drafts/{draft_id}")
def update_score_draft(decision_id: int, draft_id: int, body: dict, db: Session = Depends(get_db)):
    draft = _get_draft_or_404(decision_id, draft_id, db)
    _ensure_draft_mutable(draft)
    if "status" in body:
        raise HTTPException(status_code=422, detail="PATCH cannot approve score drafts")
    changed = False
    if "suggested_score" in body:
        draft.suggested_score = _validate_score_value(body.get("suggested_score"), "suggested_score")
        changed = True
    if "human_adjusted_score" in body:
        draft.human_adjusted_score = None if body.get("human_adjusted_score") is None else _validate_score_value(body.get("human_adjusted_score"), "human_adjusted_score")
        changed = True
    if "rationale" in body:
        draft.rationale = _string_field(body.get("rationale"), "rationale", MAX_RATIONALE_LENGTH)
        changed = True
    if "confidence" in body:
        draft.confidence = _validate_confidence(body.get("confidence"))
        changed = True
    if "evidence_ids" in body:
        if not isinstance(body.get("evidence_ids"), list):
            raise HTTPException(status_code=422, detail="evidence_ids must be a list")
        _set_draft_evidence(draft, body.get("evidence_ids"), db)
        changed = True
    if changed:
        draft.status = "edited"
    db.commit()
    db.refresh(draft)
    return _draft_serializer(draft, db)


@router.post("/decisions/{decision_id}/score-drafts/{draft_id}/approve")
def approve_score_draft(decision_id: int, draft_id: int, db: Session = Depends(get_db)):
    draft = _get_draft_or_404(decision_id, draft_id, db)
    _ensure_draft_mutable(draft)
    draft.status = "approved"
    db.commit()
    db.refresh(draft)
    return _draft_serializer(draft, db)


@router.post("/decisions/{decision_id}/score-drafts/{draft_id}/reject")
def reject_score_draft(decision_id: int, draft_id: int, db: Session = Depends(get_db)):
    draft = _get_draft_or_404(decision_id, draft_id, db)
    _ensure_draft_mutable(draft)
    draft.status = "rejected"
    db.commit()
    db.refresh(draft)
    return _draft_serializer(draft, db)


@router.post("/decisions/{decision_id}/score-drafts/{draft_id}/apply")
def apply_score_draft(decision_id: int, draft_id: int, db: Session = Depends(get_db)):
    draft = _get_draft_or_404(decision_id, draft_id, db)
    score = _apply_draft(draft, db)
    db.commit()
    db.refresh(draft)
    db.refresh(score)
    return {"draft": _draft_serializer(draft, db), "score": {"id": score.id, "activity_id": score.activity_id, "metric_id": score.metric_id, "score": score.score}}


@router.post("/decisions/{decision_id}/score-drafts/apply")
def apply_score_drafts(decision_id: int, body: dict, db: Session = Depends(get_db)):
    draft_ids = body.get("draft_ids")
    if not isinstance(draft_ids, list) or not draft_ids:
        raise HTTPException(status_code=422, detail="draft_ids must be a non-empty list")
    drafts = []
    seen = set()
    for draft_id in draft_ids:
        if not isinstance(draft_id, int) or isinstance(draft_id, bool):
            raise HTTPException(status_code=422, detail="draft_ids must contain integers")
        if draft_id in seen:
            continue
        draft = _get_draft_or_404(decision_id, draft_id, db)
        _ensure_draft_mutable(draft)
        drafts.append(draft)
        seen.add(draft_id)
    scores = [_apply_draft(draft, db) for draft in drafts]
    db.commit()
    return {
        "status": "applied",
        "applied_draft_ids": [draft.id for draft in drafts],
        "scores": [{"id": score.id, "activity_id": score.activity_id, "metric_id": score.metric_id, "score": score.score} for score in scores],
    }


def _ai_call_or_error(prompt: str) -> dict:
    try:
        return OpenAIDecisionClient().structured_json(prompt)
    except AIUnavailableError as exc:
        raise HTTPException(status_code=503, detail="AI is not available") from exc
    except AIProviderOutputError as exc:
        raise HTTPException(status_code=502, detail="AI provider returned malformed output") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="AI provider returned an error") from exc


@router.post("/decisions/{decision_id}/ai/suggest-metrics")
def ai_suggest_metrics(decision_id: int, body: dict, db: Session = Depends(get_db)):
    decision = _get_decision_or_404(decision_id, db)
    caps = get_ai_caps()
    max_suggestions = _validate_ai_max_field(body, "max_suggestions", caps["max_metric_suggestions"])
    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    metrics = db.query(Metric).filter(Metric.id.in_(_decision_metric_ids(decision_id, db))).all()
    output = _ai_call_or_error(build_decision_context(
        decision, activities, metrics, body.get("user_context") or "",
        instruction="Return a JSON object with a top-level key \"metric_suggestions\" containing an array of suggested criteria. Each item must have: name, category, description, why_it_matters, recommended_weight (0-100). Also include a top-level key \"questions_for_user\" (array of strings) if you need more context. Use \"metric_suggestions\" as the key name, not \"criteria\" or any other name.",
    ))
    suggestions = output.get("metric_suggestions", [])
    if not isinstance(suggestions, list):
        raise HTTPException(status_code=502, detail="AI provider returned malformed output")
    valid = []
    for item in suggestions[:max_suggestions]:
        try:
            if not isinstance(item, dict):
                raise ValueError("item is not an object")
            name = item.get("name")
            category = item.get("category")
            if not isinstance(name, str) or not name.strip() or not isinstance(category, str) or not category.strip():
                raise ValueError("name and category are required")
            weight = 50.0 if item.get("recommended_weight") is None else _provider_float(item.get("recommended_weight"), "recommended_weight")
            if weight < 0 or weight > 100:
                raise ValueError("recommended_weight must be between 0 and 100")
            valid.append({
                "name": name.strip()[:MAX_METRIC_NAME_LENGTH],
                "category": category.strip()[:MAX_METRIC_CATEGORY_LENGTH],
                "description": str(item.get("description") or "")[:1000],
                "recommended_weight": weight,
                "why_it_matters": str(item.get("why_it_matters") or "")[:1000],
                "source": "OpenAI",
            })
        except ValueError:
            continue
    return {"metric_suggestions": valid, "questions_for_user": output.get("questions_for_user", []) if isinstance(output.get("questions_for_user", []), list) else []}


@router.post("/decisions/{decision_id}/ai/draft-evidence", status_code=201)
def ai_draft_evidence(decision_id: int, body: dict, db: Session = Depends(get_db)):
    decision = _get_decision_or_404(decision_id, db)
    caps = get_ai_caps()
    max_items = _validate_ai_max_field(body, "max_items", caps["max_evidence_items_per_request"])
    all_activity_ids = _decision_activity_ids(decision_id, db)
    all_metric_ids = _decision_metric_ids(decision_id, db)
    allowed_activity_ids = _validate_ai_id_filter(body, "activity_ids", all_activity_ids)
    allowed_metric_ids = _validate_ai_id_filter(body, "metric_ids", all_metric_ids)
    include_general = _validate_ai_bool_field(body, "include_general_evidence", True)
    activities = db.query(Activity).filter(Activity.id.in_(allowed_activity_ids)).all() if allowed_activity_ids else []
    metrics = db.query(Metric).filter(Metric.id.in_(allowed_metric_ids)).all() if allowed_metric_ids else []
    output = _ai_call_or_error(build_decision_context(
        decision, activities, metrics, body.get("user_context") or "",
        instruction="Return JSON only. Draft evidence items (claims with supporting rationale) for scoring the given alternatives on the given metrics. Each evidence_item must have: activity_id, metric_id, claim, rationale, confidence (0-1), polarity (positive/negative/neutral/mixed). Include missing_context_questions if you need more context.",
    ))
    items = output.get("evidence_items", [])
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="AI provider returned malformed output")
    created = []
    skipped = []
    for raw in items[:max_items]:
        try:
            if not isinstance(raw, dict):
                raise ValueError("item is not an object")
            raw_activity_id = raw.get("activity_id")
            raw_metric_id = raw.get("metric_id")
            if raw_activity_id is None and not include_general:
                raise ValueError("general activity evidence is not allowed")
            if raw_metric_id is None and not include_general:
                raise ValueError("general metric evidence is not allowed")
            activity_id = _optional_scoped_activity(raw_activity_id, decision_id, db)
            metric_id = _optional_scoped_metric(raw_metric_id, decision_id, db)
            if activity_id is not None and activity_id not in allowed_activity_ids:
                raise ValueError("activity_id is outside requested filters")
            if metric_id is not None and metric_id not in allowed_metric_ids:
                raise ValueError("metric_id is outside requested filters")
            item = EvidenceItem(
                decision_id=decision_id,
                activity_id=activity_id,
                metric_id=metric_id,
                claim=_string_field(raw.get("claim"), "claim", MAX_EVIDENCE_CLAIM_LENGTH, True),
                rationale=_string_field(raw.get("rationale"), "rationale", MAX_RATIONALE_LENGTH),
                source_type="llm",
                source_label="OpenAI",
                confidence=_validate_confidence(raw.get("confidence")),
                polarity=_enum_field(raw.get("polarity"), EVIDENCE_POLARITIES, "polarity"),
                review_status="pending",
            )
            db.add(item)
            db.flush()
            created.append(item)
        except (HTTPException, ValueError) as exc:
            skipped.append({"reason": getattr(exc, "detail", str(exc))})
    if not created:
        raise HTTPException(status_code=502, detail="AI provider returned no valid evidence")
    db.commit()
    return {"evidence_items": [_evidence_serializer(item) for item in created], "missing_context_questions": output.get("missing_context_questions", []) if isinstance(output.get("missing_context_questions", []), list) else [], "skipped": skipped}


@router.post("/decisions/{decision_id}/ai/suggest-scores", status_code=201)
def ai_suggest_scores(decision_id: int, body: dict, db: Session = Depends(get_db)):
    decision = _get_decision_or_404(decision_id, db)
    caps = get_ai_caps()
    max_drafts = _validate_ai_max_field(body, "max_drafts", caps["max_score_drafts_per_request"])
    all_activity_ids = _decision_activity_ids(decision_id, db)
    all_metric_ids = _decision_metric_ids(decision_id, db)
    allowed_activity_ids = _validate_ai_id_filter(body, "activity_ids", all_activity_ids)
    allowed_metric_ids = _validate_ai_id_filter(body, "metric_ids", all_metric_ids)
    evidence_policy = _enum_field(body.get("evidence_review_policy"), AI_EVIDENCE_REVIEW_POLICIES, "evidence_review_policy", "approved_and_pending")
    allowed_evidence_statuses = {"approved"} if evidence_policy == "approved_only" else {"approved", "pending"}
    activities = db.query(Activity).filter(Activity.id.in_(allowed_activity_ids)).all() if allowed_activity_ids else []
    metrics = db.query(Metric).filter(Metric.id.in_(allowed_metric_ids)).all() if allowed_metric_ids else []
    output = _ai_call_or_error(build_decision_context(
        decision, activities, metrics, body.get("user_context") or "",
        instruction="Return JSON only. Suggest scores (0-100) for each activity on each metric based on available evidence. Each score_draft must have: activity_id, metric_id, suggested_score (0-100), rationale, confidence (0-1), evidence_ids (list of applicable evidence item IDs). Include warnings if data is insufficient.",
    ))
    raw_drafts = output.get("score_drafts", [])
    if not isinstance(raw_drafts, list):
        raise HTTPException(status_code=502, detail="AI provider returned malformed output")
    created = []
    skipped = []
    for raw in raw_drafts[:max_drafts]:
        try:
            if not isinstance(raw, dict):
                raise ValueError("item is not an object")
            activity_id = _optional_scoped_activity(raw.get("activity_id"), decision_id, db)
            metric_id = _optional_scoped_metric(raw.get("metric_id"), decision_id, db)
            if activity_id is None or metric_id is None:
                raise ValueError("activity_id and metric_id are required")
            if activity_id not in allowed_activity_ids:
                raise ValueError("activity_id is outside requested filters")
            if metric_id not in allowed_metric_ids:
                raise ValueError("metric_id is outside requested filters")
            draft = ScoreDraft(
                decision_id=decision_id,
                activity_id=activity_id,
                metric_id=metric_id,
                suggested_score=_validate_score_value(raw.get("suggested_score"), "suggested_score"),
                rationale=_string_field(raw.get("rationale"), "rationale", MAX_RATIONALE_LENGTH),
                source_type="llm",
                source_label="OpenAI",
                confidence=_validate_confidence(raw.get("confidence")),
                status="pending",
            )
            db.add(draft)
            db.flush()
            _set_ai_draft_evidence(draft, raw.get("evidence_ids", []), allowed_evidence_statuses, db)
            created.append(draft)
        except (HTTPException, ValueError) as exc:
            skipped.append({"reason": getattr(exc, "detail", str(exc))})
    if not created:
        raise HTTPException(status_code=502, detail="AI provider returned no valid score drafts")
    db.commit()
    return {"score_drafts": [_draft_serializer(draft, db) for draft in created], "warnings": output.get("warnings", []) if isinstance(output.get("warnings", []), list) else [], "skipped": skipped}


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

    requested_weight = body.get("weight", 50.0)
    weight = _validate_score_value(requested_weight, "weight")

    # Auto-create DecisionWeight with requested/default weight
    dw = DecisionWeight(
        decision_id=decision_id,
        metric_id=metric.id,
        weight=weight,
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
