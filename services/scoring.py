from typing import Dict

from sqlalchemy.orm import Session

from models import ActivityWeight, CandidateScore, Metric


def resolve_submetrics(candidate_id: int, metric_id: int, db: Session) -> float:
    """Resolve a metric's score for a candidate, handling sub-metrics.

    If the metric has children, compute the weighted average of children's scores.
    Each child's score is weighted equally (since sub-metrics don't have per-activity weights).
    If no children, return the direct candidate score (or 0 if missing).
    """
    metric = db.query(Metric).filter(Metric.id == metric_id).first()
    if not metric:
        return 0.0

    # Check for children
    children = db.query(Metric).filter(Metric.parent_id == metric_id).all()

    if not children:
        # Direct score lookup
        cs = (
            db.query(CandidateScore)
            .filter(
                CandidateScore.candidate_id == candidate_id,
                CandidateScore.metric_id == metric_id,
            )
            .first()
        )
        return cs.score if cs else 0.0

    # Children exist — compute weighted average of children
    total_weight = 0.0
    weighted_sum = 0.0
    for child in children:
        cs = (
            db.query(CandidateScore)
            .filter(
                CandidateScore.candidate_id == candidate_id,
                CandidateScore.metric_id == child.id,
            )
            .first()
        )
        child_score = cs.score if cs else 0.0
        # Sub-metrics are equally weighted relative to each other
        weight = 1.0
        total_weight += weight
        weighted_sum += child_score * weight

    if total_weight == 0:
        return 0.0
    return weighted_sum / total_weight


def compute_fit_score(candidate_id: int, activity_id: int, db: Session) -> float:
    """Compute the fit score for a candidate against an activity.

    Returns a float 0.0–1.0 representing the fit percentage.
    """
    weights: Dict[int, float] = {}
    for aw in (
        db.query(ActivityWeight)
        .filter(ActivityWeight.activity_id == activity_id)
        .all()
    ):
        weights[aw.metric_id] = aw.weight

    if not weights:
        return 0.0

    numerator = 0.0
    denominator = 0.0

    for metric_id, weight in weights.items():
        score = resolve_submetrics(candidate_id, metric_id, db)
        numerator += score * weight
        denominator += weight

    if denominator == 0:
        return 0.0

    return numerator / denominator / 100.0


def compute_fit_scores_for_all_activities(
    candidate_id: int, db: Session
) -> list[dict]:
    """Compute fit scores for a candidate against all activities.

    Returns sorted list of {activity_id, activity_name, fit_score}.
    """
    from models import Activity

    activities = db.query(Activity).all()
    results = []
    for activity in activities:
        fit = compute_fit_score(candidate_id, activity.id, db)
        results.append(
            {
                "activity_id": activity.id,
                "activity_name": activity.name,
                "category": activity.category,
                "fit_score": round(fit, 4),
            }
        )
    results.sort(key=lambda x: x["fit_score"], reverse=True)
    return results


def compute_preview_fit_scores(
    scores: Dict[int, float], db: Session
) -> list[dict]:
    """Compute fit scores from a scores dict directly, without a candidate.

    Used for the live preview on the candidate creation form.
    Returns top-3 activities sorted by fit score.
    """
    from models import Activity

    activities = db.query(Activity).all()
    results = []

    for activity in activities:
        weights: Dict[int, float] = {}
        for aw in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id == activity.id)
            .all()
        ):
            weights[aw.metric_id] = aw.weight

        if not weights:
            continue

        numerator = 0.0
        denominator = 0.0

        for metric_id, weight in weights.items():
            score = scores.get(metric_id, 0.0)
            numerator += score * weight
            denominator += weight

        fit = (numerator / denominator / 100.0) if denominator > 0 else 0.0
        results.append(
            {
                "activity_id": activity.id,
                "activity_name": activity.name,
                "fit_score": round(fit, 4),
            }
        )

    results.sort(key=lambda x: x["fit_score"], reverse=True)
    return results[:3]


def compute_alternative_fit_scores(decision_id: int, db: Session) -> list[dict]:
    """Compute fit scores for alternative scoring (decision engine flow).

    Each alternative is an Activity. Each criterion is a Metric.
    Scores come from AlternativeScore table.
    Weights come from ActivityWeight table.

    Returns sorted list of {activity_id, activity_name, fit_score, weighted_score}.
    """
    from models import Activity, ActivityWeight, AlternativeScore, Metric

    activities = (
        db.query(Activity)
        .filter(Activity.decision_id == decision_id)
        .all()
    )
    if not activities:
        return []

    results = []
    for activity in activities:
        # Get weights for this activity
        weights: dict[int, float] = {}
        for aw in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id == activity.id)
            .all()
        ):
            weights[aw.metric_id] = aw.weight

        if not weights:
            continue

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
            weighted_scores.append({
                "metric_id": metric_id,
                "score": score,
                "weight": weight,
            })

        fit = (numerator / denominator / 100.0) if denominator > 0 else 0.0
        results.append({
            "activity_id": activity.id,
            "activity_name": activity.name,
            "fit_score": round(fit, 4),
            "fit_pct": round(fit * 100, 1),
            "weighted_scores": weighted_scores,
        })

    results.sort(key=lambda x: x["fit_score"], reverse=True)
    return results
