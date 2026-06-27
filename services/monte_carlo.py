import math
import random
from typing import List

from sqlalchemy.orm import Session

from models import Activity, ActivityWeight, Candidate, CandidateScore, Metric
from services.scoring import compute_fit_score, resolve_submetrics


def _generate_random_candidate(name: str, db: Session) -> Candidate:
    """Generate a random candidate with scores for all metrics."""
    candidate = Candidate(name=name)
    db.add(candidate)
    db.flush()

    metrics = db.query(Metric).filter(Metric.parent_id.is_(None)).all()
    for metric in metrics:
        score = random.uniform(0, 100)
        cs = CandidateScore(
            candidate_id=candidate.id,
            metric_id=metric.id,
            score=round(score, 1),
        )
        db.add(cs)
    db.flush()
    return candidate


def run_monte_carlo(
    activity_id: int, db: Session, n: int = 200
) -> List[dict]:
    """Run Monte Carlo simulation for an activity.

    Generates n random candidates, scores them against the activity,
    takes the top 10%, and computes variance per metric within the top 10%.
    Lower variance = higher importance (more discriminating).

    Returns list of metric dictionaries with importance metrics.
    """
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        return []

    # Get metric weights for this activity
    weights_rows = (
        db.query(ActivityWeight)
        .filter(ActivityWeight.activity_id == activity_id)
        .all()
    )
    metric_ids = [aw.metric_id for aw in weights_rows]

    if not metric_ids:
        return []

    # Generate random candidates
    candidates = []
    fit_scores = []
    for i in range(n):
        cand = _generate_random_candidate(f"MC_{activity.name}_{i}", db)
        fit = compute_fit_score(cand.id, activity_id, db)
        candidates.append(cand)
        fit_scores.append(fit)

    # Sort by fit score descending, take top 10%
    paired = list(zip(candidates, fit_scores))
    paired.sort(key=lambda x: x[1], reverse=True)
    top_count = max(1, n // 10)
    top_candidates = [p[0] for p in paired[:top_count]]

    # For each metric, collect scores from top candidates
    metric_stats = []
    for metric_id in metric_ids:
        metric = db.query(Metric).filter(Metric.id == metric_id).first()
        scores = []
        for cand in top_candidates:
            score = resolve_submetrics(cand.id, metric_id, db)
            scores.append(score)

        if not scores:
            continue

        avg = sum(scores) / len(scores)
        min_val = min(scores)
        max_val = max(scores)
        variance = sum((s - avg) ** 2 for s in scores) / len(scores)
        stddev = math.sqrt(variance)

        # Importance: lower stddev = more discriminating = higher importance
        # Normalize so max possible importance is 100
        importance = max(0, 100.0 - stddev)

        metric_stats.append(
            {
                "metric_id": metric_id,
                "metric_name": metric.name if metric else f"Metric #{metric_id}",
                "avg": round(avg, 2),
                "min": round(min_val, 2),
                "max": round(max_val, 2),
                "stddev": round(stddev, 2),
                "importance": round(importance, 2),
            }
        )

    # Sort by importance descending
    metric_stats.sort(key=lambda x: x["importance"], reverse=True)

    # Clean up generated candidates
    for cand in candidates:
        db.query(CandidateScore).filter(
            CandidateScore.candidate_id == cand.id
        ).delete()
        db.delete(cand)
    db.flush()

    return metric_stats
