import json
import logging
import math

from sqlalchemy.orm import Session

from models import ActivityWeight


# ── Threshold-based elimination (Elimination by Aspects) ──


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

    # Parse thresholds JSON
    thresholds = []
    if decision.thresholds:
        try:
            thresholds = json.loads(decision.thresholds)
        except (json.JSONDecodeError, TypeError):
            thresholds = []

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
            metric_id = t.get("metric_id")
            operator = t.get("operator", "<=")
            threshold_value = float(t.get("value", 0))

            # Validate threshold value — clamp with warning if out of range
            if threshold_value < 0.0 or threshold_value > 100.0:
                logging.warning(
                    "filter_by_thresholds: threshold value %s out of range for metric %s — clamped to 0-100",
                    threshold_value,
                    metric_id,
                )
                threshold_value = max(0.0, min(100.0, threshold_value))

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

            # Clamp score to 0-100
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


# ── Paired t-test for statistical significance ──


def _betainc(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function using continued fraction.

    Uses modified Lentz's method (from Numerical Recipes).
    I_x(a, b) = B(x; a, b) / B(a, b)
    """
    if x < 0 or x > 1:
        raise ValueError(f"x must be in [0, 1], got {x}")
    if x == 0 or x == 1:
        return 0.0 if x == 0 else 1.0
    if a <= 0 or b <= 0:
        raise ValueError(f"a and b must be positive, got a={a}, b={b}")

    # Symmetry transformation for efficiency
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _betainc(1.0 - x, b, a)

    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log1p(-x) - lbeta - math.log(a))

    MAX_ITER = 200
    EPS = 3e-12

    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d

    for m in range(1, MAX_ITER + 1):
        m2 = 2 * m
        # Even step
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta

        # Odd step
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta

        if abs(delta - 1.0) < EPS:
            break

    return front * h


def _student_t_cdf(t: float, df: int) -> float:
    """CDF of Student's t-distribution P(T <= t) for df degrees of freedom."""
    if df < 1:
        return float("nan")
    if t == float("inf"):
        return 1.0
    if t == float("-inf"):
        return 0.0

    x = df / (df + t * t)
    a = df / 2.0
    ibeta = _betainc(x, a, 0.5)

    if t >= 0:
        return 1.0 - 0.5 * ibeta
    else:
        return 0.5 * ibeta


def paired_t_test(scores_a: list[float], scores_b: list[float]) -> dict:
    """Perform a paired two-tailed t-test on two sets of scores.

    The null hypothesis is that the mean paired difference is zero.
    This is appropriate when the two alternatives share the same criteria
    (paired by criterion), which is the MCDA case.

    Returns a dict with keys:
        t_statistic, p_value, degrees_of_freedom, mean_difference,
        std_difference, significant (p < 0.05), num_criteria.
    """
    n = len(scores_a)
    if n != len(scores_b):
        return {"error": f"Score lists have different lengths: {n} vs {len(scores_b)}"}
    if n < 2:
        return {"error": f"Need at least 2 paired criteria, got {n}"}

    differences = [a - b for a, b in zip(scores_a, scores_b)]
    mean_diff = sum(differences) / n

    if n < 2:
        return {"error": f"Need at least 2 paired criteria, got {n}"}

    variance = sum((d - mean_diff) ** 2 for d in differences) / (n - 1)
    std_diff = math.sqrt(variance)
    df = n - 1

    if std_diff == 0:
        # All differences identical
        if mean_diff == 0:
            p_value = 1.0
            t_stat = 0.0
        else:
            t_stat = float("inf")
            p_value = 0.0
    else:
        se = std_diff / math.sqrt(n)
        t_stat = mean_diff / se
        p_value = 2.0 * _student_t_cdf(-abs(t_stat), df)

    return {
        "t_statistic": round(t_stat, 4),
        "p_value": round(p_value, 4),
        "degrees_of_freedom": df,
        "mean_difference": round(mean_diff, 4),
        "std_difference": round(std_diff, 4),
        "significant": p_value < 0.05,
        "num_criteria": n,
    }


def significance_label(p_value: float) -> str:
    if p_value < 0.01:
        return "highly significant"
    if p_value < 0.05:
        return "significant"
    if p_value < 0.10:
        return "marginally significant"
    return "not significant"


def build_significance_summary(
    winner_name: str,
    runner_name: str,
    winner_scores: list[float],
    runner_scores: list[float],
    winner_avg: float,
    runner_avg: float,
) -> dict | None:
    test = paired_t_test(winner_scores, runner_scores)
    if "error" in test:
        return None

    p_value = test["p_value"]
    return {
        "t_statistic": test["t_statistic"],
        "df": test["degrees_of_freedom"],
        "p_value": p_value,
        "label": significance_label(p_value),
        "winner_avg": round(winner_avg, 1),
        "runner_avg": round(runner_avg, 1),
        "winner_name": winner_name,
        "runner_name": runner_name,
        "mean_diff": test.get("mean_difference"),
        "std_diff": test.get("std_difference"),
        "num_criteria": test.get("num_criteria"),
        "significant": test.get("significant", False),
    }


def apply_ko_criteria(decision_id: int, db: Session) -> dict:
    from models import Activity, AlternativeScore, Decision, Metric

    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    if not decision or not hasattr(decision, "ko_criteria"):
        return {
            "eliminated": [],
            "survivor_ids": [a.id for a in activities],
            "all_eliminated": False,
        }

    criteria_raw = getattr(decision, "ko_criteria", None)
    if not criteria_raw:
        return {
            "eliminated": [],
            "survivor_ids": [a.id for a in activities],
            "all_eliminated": False,
        }

    try:
        criteria = json.loads(criteria_raw)
    except (json.JSONDecodeError, TypeError):
        criteria = []

    if not criteria:
        return {
            "eliminated": [],
            "survivor_ids": [a.id for a in activities],
            "all_eliminated": False,
        }

    metrics = {m.id: m for m in db.query(Metric).all()}
    eliminated = []
    survivor_ids = []

    for activity in activities:
        scores = {
            s.metric_id: s.score
            for s in db.query(AlternativeScore)
            .filter(AlternativeScore.activity_id == activity.id)
            .all()
        }
        reasons = []
        for criterion in criteria:
            metric_id = criterion.get("metric_id")
            operator = criterion.get("operator", ">=")
            value = float(criterion.get("value", 0))
            metric_name = (
                metrics.get(metric_id).name
                if metric_id in metrics
                else "Unknown metric"
            )
            score = scores.get(metric_id)
            failed = score is None
            if score is not None:
                failed = (
                    (operator == ">=" and score < value)
                    or (operator == ">" and score <= value)
                    or (operator == "<=" and score > value)
                    or (operator == "<" and score >= value)
                )
            if failed:
                if score is None:
                    reasons.append(
                        f"No score available for {metric_name} (KO {operator} {value})"
                    )
                else:
                    reasons.append(
                        f"{metric_name} ({score}) fails KO {operator} {value}"
                    )
        if reasons:
            eliminated.append(
                {
                    "activity_id": activity.id,
                    "activity_name": activity.name,
                    "ko_reasons": reasons,
                }
            )
        else:
            survivor_ids.append(activity.id)

    return {
        "eliminated": eliminated,
        "survivor_ids": survivor_ids,
        "all_eliminated": bool(activities) and not survivor_ids,
    }


def compute_alternative_fit_scores(decision_id: int, db: Session) -> list[dict]:
    """Compute fit scores for alternative scoring (decision engine flow).

    Each alternative is an Activity. Each criterion is a Metric.
    Scores come from AlternativeScore table.
    Weights come from ActivityWeight table.

    Returns sorted list of {activity_id, activity_name, fit_score, weighted_score}.
    """
    from models import Activity, AlternativeScore, Metric

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
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

        # Build higher_is_better map for metrics in this activity's weights
        metric_ids = list(weights.keys())
        metrics = db.query(Metric).filter(Metric.id.in_(metric_ids)).all()
        higher_is_better_map = {m.id: m.higher_is_better for m in metrics}

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
            effective_score = (
                score if higher_is_better_map.get(metric_id, True) else (100.0 - score)
            )
            numerator += effective_score * weight
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

    Groups metrics by their category (dimension name like 'Financial', 'Quality', etc.)
    For each dimension, computes the weighted average of its metrics' scores.

    Returns: [
        {"dimension": "Financial", "score": 45.2, "metrics": [...], "metric_count": 2},
        ...
    ]
    """
    from models import Activity, AlternativeScore, Metric

    activities = db.query(Activity).filter(Activity.decision_id == decision_id).all()
    if not activities:
        return []

    # Get weights for the first activity (all share same weights)
    weights: dict[int, float] = {}
    for aw in (
        db.query(ActivityWeight)
        .filter(ActivityWeight.activity_id == activities[0].id)
        .all()
    ):
        weights[aw.metric_id] = aw.weight

    if not weights:
        return []

    # Get metric-to-dimension mapping and higher_is_better map
    metric_ids = list(weights.keys())
    metrics = db.query(Metric).filter(Metric.id.in_(metric_ids)).all()
    metric_category: dict[int, str] = {m.id: m.category for m in metrics}
    higher_is_better_map: dict[int, bool] = {m.id: m.higher_is_better for m in metrics}

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
        effective_avg_score = (
            avg_score
            if higher_is_better_map.get(metric_id, True)
            else (100.0 - avg_score)
        )
        dim_groups[cat].append(
            {
                "metric_id": metric_id,
                "score": effective_avg_score,
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


def gap_analysis(dimension_scores: list[dict]) -> dict:
    """Compare each dimension score to the overall average.

    Returns: {
        "strengths": [{"dimension": "Quality", "score": 85, "gap": 20}],
        "weaknesses": [{"dimension": "Cost", "score": 35, "gap": -30}],
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
