import json
import math
from sqlalchemy.orm import Session

from models import DecisionWeight


# ── Threshold-based elimination (Elimination by Aspects) ──


def sanitize_persisted_thresholds(decision_id: int, db: Session) -> list[dict]:
    """Return valid saved thresholds for a decision, skipping corrupt entries."""
    from models import Decision

    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision or not decision.thresholds:
        return []

    try:
        raw_thresholds = json.loads(decision.thresholds)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw_thresholds, list):
        return []

    selected_metric_ids = {
        dw.metric_id
        for dw in db.query(DecisionWeight)
        .filter(DecisionWeight.decision_id == decision_id)
        .all()
    }
    valid_operators = {"<=", ">=", "<", ">"}
    thresholds = []
    for threshold in raw_thresholds:
        if not isinstance(threshold, dict):
            continue

        metric_id = threshold.get("metric_id")
        if not isinstance(metric_id, int) or isinstance(metric_id, bool):
            continue
        if metric_id not in selected_metric_ids:
            continue

        operator = threshold.get("operator", ">=")
        if not isinstance(operator, str):
            continue
        if operator not in valid_operators:
            continue

        try:
            value = float(threshold.get("value"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0.0 or value > 100.0:
            continue

        thresholds.append(
            {"metric_id": metric_id, "operator": operator, "value": value}
        )

    return thresholds


def filter_by_thresholds(decision_id: int, db: Session) -> dict:
    """Apply Elimination by Aspects filtering.

    Reads thresholds from Decision.thresholds JSON.
    Checks each activity's AlternativeScores against each threshold.

    Returns: {
        "passed": [...],
        "failed": [{"name": ..., "reason": ...}],
        "all_passed": True/False,
        "survivor_results": [...]  # compute_alternative_fit_scores on passed only
    }
    """
    from models import Activity, AlternativeScore, Decision, Metric

    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        return {"passed": [], "failed": [], "all_passed": True, "survivor_results": []}

    # Persisted thresholds may predate current route validation or be corrupted
    # directly in the DB, so sanitize once at this safety boundary.
    thresholds = sanitize_persisted_thresholds(decision_id, db)

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()

    if not thresholds:
        # No thresholds applied — all pass, return all fit scores
        all_results = compute_alternative_fit_scores(decision_id, db)
        passed = [{"activity_id": a.id, "activity_name": a.name} for a in activities]
        return {
            "passed": passed,
            "failed": [],
            "all_passed": True,
            "survivor_results": all_results,
        }

    # Build metric lookup
    all_metrics = db.query(Metric).all()
    metric_map = {m.id: m for m in all_metrics}

    passed = []
    failed = []

    for activity in activities:
        # Get scores for this activity
        scores_map: dict[int, float] = {}
        for ascore in (
            db.query(AlternativeScore)
            .filter(AlternativeScore.activity_id == activity.id)
            .all()
        ):
            scores_map[ascore.metric_id] = ascore.score

        fail_reasons = []
        for t in thresholds:
            metric_id = t["metric_id"]
            operator = t["operator"]
            threshold_value = t["value"]

            # Skip unknown metric_ids
            if metric_id not in metric_map:
                continue

            score = scores_map.get(metric_id)
            if score is None:
                # No score for this metric — fail
                metric_name = metric_map[metric_id].name
                fail_reasons.append(
                    f"No score available for {metric_name} (threshold: {operator} {threshold_value})"
                )
                continue

            # Clamp score to protect filtering from corrupt persisted AlternativeScore data.
            score = max(0.0, min(100.0, score))

            metric_name = metric_map[metric_id].name

            # Check threshold
            failed_check = False
            if operator == "<=" and not (score <= threshold_value):
                failed_check = True
            elif operator == ">=" and not (score >= threshold_value):
                failed_check = True
            elif operator == "<" and not (score < threshold_value):
                failed_check = True
            elif operator == ">" and not (score > threshold_value):
                failed_check = True

            if failed_check:
                fail_reasons.append(
                    f"{metric_name} ({score}) fails {operator} {threshold_value}"
                )

        if fail_reasons:
            failed.append(
                {
                    "activity_id": activity.id,
                    "activity_name": activity.name,
                    "reasons": fail_reasons,
                }
            )
        else:
            passed.append(
                {
                    "activity_id": activity.id,
                    "activity_name": activity.name,
                }
            )

    # Compute fit scores on survivors
    survivor_ids = [p["activity_id"] for p in passed]
    if survivor_ids:
        survivor_results = compute_alternative_fit_scores(decision_id, db)
        # Filter to only survivors (fit scores are already computed across all activities)
        survivor_results = [
            r for r in survivor_results if r["activity_id"] in survivor_ids
        ]
    else:
        survivor_results = []

    return {
        "passed": passed,
        "failed": failed,
        "all_passed": len(failed) == 0,
        "survivor_results": survivor_results,
    }


def compute_alternative_fit_scores(decision_id: int, db: Session) -> list[dict]:
    """Compute fit scores for alternative scoring (decision engine flow).

    Each alternative is an Activity. Each criterion is a Metric.
    Scores come from AlternativeScore table.
    Weights come from DecisionWeight table (decision-level, shared across all activities).

    Returns sorted list of {activity_id, activity_name, fit_score, weighted_score}.
    """
    from models import Activity, AlternativeScore

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    if not activities:
        return []

    # Load decision-level weights (shared across all activities)
    decision_weights = (
        db.query(DecisionWeight).filter(DecisionWeight.decision_id == decision_id).all()
    )
    weights: dict[int, float] = {dw.metric_id: dw.weight for dw in decision_weights}
    if not weights:
        return []

    results = []
    for activity in activities:
        # Get scores for this activity
        scores: dict[int, float] = {}
        for ascore in (
            db.query(AlternativeScore)
            .filter(AlternativeScore.activity_id == activity.id)
            .all()
        ):
            scores[ascore.metric_id] = ascore.score

        numerator = 0.0
        denominator = 0.0
        weighted_scores = []

        for metric_id, weight in weights.items():
            score = scores.get(metric_id, 0.0)
            numerator += score * weight
            denominator += weight
            weighted_scores.append(
                {
                    "metric_id": metric_id,
                    "score": score,
                    "weight": weight,
                }
            )

        fit = (numerator / denominator / 100.0) if denominator > 0 else 0.0
        results.append(
            {
                "activity_id": activity.id,
                "activity_name": activity.name,
                "fit_score": round(fit, 4),
                "fit_pct": round(fit * 100, 1),
                "weighted_scores": weighted_scores,
            }
        )

    results.sort(key=lambda x: x["fit_score"], reverse=True)
    return results


def compute_dimension_scores(decision_id: int, db: Session) -> list[dict]:
    """Group metric scores by dimension and compute weighted averages.

    Groups metrics by their fit category.
    For each dimension, computes the weighted average of its metrics' scores.

    Returns: [
        {"dimension": "Resource Fit", "score": 45.2, "metrics": [...], "metric_count": 2},
        ...
    ]
    """
    from models import Activity, AlternativeScore, Metric

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    if not activities:
        return []

    # Get decision-level weights
    decision_weights = (
        db.query(DecisionWeight).filter(DecisionWeight.decision_id == decision_id).all()
    )
    weights: dict[int, float] = {dw.metric_id: dw.weight for dw in decision_weights}

    if not weights:
        return []

    # Get metric-to-dimension mapping
    metric_ids = list(weights.keys())
    metrics = db.query(Metric).filter(Metric.id.in_(metric_ids)).all()
    metric_category: dict[int, str] = {m.id: m.category for m in metrics}

    # Get scores for each activity (we'll average across activities for diagnose mode
    # where there's typically just one activity)
    activity_scores: dict[int, dict[int, float]] = {}
    for act in activities:
        scores: dict[int, float] = {}
        for ascore in (
            db.query(AlternativeScore)
            .filter(AlternativeScore.activity_id == act.id)
            .all()
        ):
            scores[ascore.metric_id] = ascore.score
        activity_scores[act.id] = scores

    # Group by dimension
    dim_groups: dict[str, list[dict]] = {}
    for metric_id in metric_ids:
        cat = metric_category.get(metric_id, "General")
        if cat not in dim_groups:
            dim_groups[cat] = []
        # Average score across all activities
        scores_list = []
        for act in activities:
            s = activity_scores.get(act.id, {}).get(metric_id)
            if s is not None:
                scores_list.append(s)
        avg_score = sum(scores_list) / len(scores_list) if scores_list else 0.0
        dim_groups[cat].append(
            {
                "metric_id": metric_id,
                "score": avg_score,
                "weight": weights[metric_id],
            }
        )

    # Compute weighted average per dimension
    results = []
    for dim_name, metric_list in dim_groups.items():
        numerator = sum(m["score"] * m["weight"] for m in metric_list)
        denominator = sum(m["weight"] for m in metric_list)
        weighted_avg = (numerator / denominator) if denominator > 0 else 0.0
        results.append(
            {
                "dimension": dim_name,
                "score": round(weighted_avg, 1),
                "metrics": metric_list,
                "metric_count": len(metric_list),
            }
        )

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ── KO (Knock-Out) criteria ──


def sanitize_persisted_ko_criteria(decision_id: int, db: Session) -> list[dict]:
    """Return valid saved KO criteria for a decision, skipping corrupt entries."""
    from models import Decision

    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision or not decision.ko_criteria:
        return []

    try:
        raw_criteria = json.loads(decision.ko_criteria)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw_criteria, list):
        return []

    selected_metric_ids = {
        dw.metric_id
        for dw in db.query(DecisionWeight)
        .filter(DecisionWeight.decision_id == decision_id)
        .all()
    }
    valid_operators = {"<=", ">=", "<", ">"}
    criteria = []
    for criterion in raw_criteria:
        if not isinstance(criterion, dict):
            continue

        metric_id = criterion.get("metric_id")
        if not isinstance(metric_id, int) or isinstance(metric_id, bool):
            continue
        if metric_id not in selected_metric_ids:
            continue

        ko_operator = criterion.get("ko_operator")
        if not isinstance(ko_operator, str):
            continue
        if ko_operator not in valid_operators:
            continue

        try:
            ko_value = float(criterion.get("ko_value"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(ko_value) or ko_value < 0.0 or ko_value > 100.0:
            continue

        criteria.append(
            {"metric_id": metric_id, "ko_operator": ko_operator, "ko_value": ko_value}
        )

    return criteria


def evaluate_ko_criteria(decision_id: int, db: Session) -> dict | None:
    """Evaluate KO criteria against scored alternatives.

    Returns None if no KO criteria configured.
    Otherwise returns {
        "results": [
            {"activity_id": int, "activity_name": str, "status": "passed"|"knocked_out", "reasons": [str,...]}
        ],
        "all_passed": bool,
        "eligible_activity_ids": [int, ...]
    }
    """
    from models import Activity, AlternativeScore, Metric

    criteria = sanitize_persisted_ko_criteria(decision_id, db)
    if not criteria:
        return None

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    if not activities:
        return None

    # Build metric name lookup
    metric_ids = {c["metric_id"] for c in criteria}
    metrics = db.query(Metric).filter(Metric.id.in_(metric_ids)).all()
    metric_name_map = {m.id: m.name for m in metrics}

    # Get all scores for this decision
    activity_ids = [a.id for a in activities]
    all_scores = (
        db.query(AlternativeScore)
        .filter(AlternativeScore.activity_id.in_(activity_ids))
        .all()
    )
    # Build scores map: {activity_id: {metric_id: score}}
    scores_map: dict[int, dict[int, float]] = {}
    for sc in all_scores:
        if sc.activity_id not in scores_map:
            scores_map[sc.activity_id] = {}
        scores_map[sc.activity_id][sc.metric_id] = sc.score

    results = []
    eligible_ids = []

    for activity in activities:
        reasons = []
        for c in criteria:
            metric_id = c["metric_id"]
            op = c["ko_operator"]
            val = c["ko_value"]
            metric_name = metric_name_map.get(metric_id, f"Metric {metric_id}")

            score = scores_map.get(activity.id, {}).get(metric_id)
            if score is None:
                reasons.append(f"No score available for {metric_name}")
                continue

            # Clamp NaN/Inf to 0.0
            if not math.isfinite(score):
                score = 0.0

            # Check KO condition
            failed = False
            if op == "<=" and not (score <= val):
                failed = True
            elif op == ">=" and not (score >= val):
                failed = True
            elif op == "<" and not (score < val):
                failed = True
            elif op == ">" and not (score > val):
                failed = True

            if failed:
                reasons.append(f"{metric_name} ({score}) fails {op} {val}")

        status = "knocked_out" if reasons else "passed"
        if status == "passed":
            eligible_ids.append(activity.id)

        results.append(
            {
                "activity_id": activity.id,
                "activity_name": activity.name,
                "status": status,
                "reasons": reasons,
            }
        )

    return {
        "results": results,
        "all_passed": len([r for r in results if r["status"] == "knocked_out"]) == 0,
        "eligible_activity_ids": eligible_ids,
    }


def gap_analysis(dimension_scores: list[dict]) -> dict:
    """Compare each dimension score to the overall average.

    Returns: {
        "strengths": [{"dimension": "Quality", "score": 85, "gap": 20}],
        "weaknesses": [{"dimension": "Resource Fit", "score": 35, "gap": -30}],
        "overall_avg": 65.0,
        "balanced": False  # True if all gaps < 5
    }
    """
    if not dimension_scores:
        return {
            "strengths": [],
            "weaknesses": [],
            "overall_avg": 0.0,
            "balanced": True,
        }

    overall_avg = sum(d["score"] for d in dimension_scores) / len(dimension_scores)

    strengths = []
    weaknesses = []
    max_gap = 0.0

    for d in dimension_scores:
        gap = round(d["score"] - overall_avg, 1)
        d["gap"] = gap
        if abs(gap) > max_gap:
            max_gap = abs(gap)
        if gap > 0:
            strengths.append(
                {
                    "dimension": d["dimension"],
                    "score": d["score"],
                    "gap": gap,
                }
            )
        elif gap < 0:
            weaknesses.append(
                {
                    "dimension": d["dimension"],
                    "score": d["score"],
                    "gap": gap,
                }
            )

    strengths.sort(key=lambda x: x["gap"], reverse=True)
    weaknesses.sort(key=lambda x: x["gap"])

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "overall_avg": round(overall_avg, 1),
        "balanced": max_gap < 5.0,
    }
