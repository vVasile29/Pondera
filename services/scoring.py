import math

from sqlalchemy.orm import Session

from models import ActivityWeight


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


def compute_alternative_fit_scores(decision_id: int, db: Session) -> list[dict]:
    """Compute fit scores for alternative scoring (decision engine flow).

    Each alternative is an Activity. Each criterion is a Metric.
    Scores come from AlternativeScore table.
    Weights come from ActivityWeight table.

    Returns sorted list of {activity_id, activity_name, fit_score, weighted_score}.
    """
    from models import Activity, AlternativeScore

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
