import json

from sqlalchemy.orm import Session

from models import Activity, ActivityWeight, AlternativeScore, Decision, Metric
from services.scoring import (
    apply_ko_criteria,
    build_significance_summary,
    compute_alternative_fit_scores,
    filter_by_thresholds,
)


def _selected_metrics(decision_id: int, db: Session) -> list[Metric]:
    activity_ids = [
        a.id
        for a in db.query(Activity).filter(Activity.decision_id == decision_id).all()
    ]
    if not activity_ids:
        return []
    metric_ids = {
        aw.metric_id
        for aw in db.query(ActivityWeight)
        .filter(ActivityWeight.activity_id.in_(activity_ids))
        .all()
    }
    if not metric_ids:
        return []
    return db.query(Metric).filter(Metric.id.in_(metric_ids)).order_by(Metric.id).all()


def _parse_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _build_significance(
    results: list[dict],
    metrics: list[Metric],
    scores_by_activity: dict[int, dict[int, float]],
) -> dict | None:
    if len(results) < 2 or len(metrics) < 2:
        return None
    winner = results[0]
    runner = results[1]
    metric_ids = [m.id for m in metrics]
    winner_scores = scores_by_activity.get(winner["activity_id"], {})
    runner_scores = scores_by_activity.get(runner["activity_id"], {})
    return build_significance_summary(
        winner["activity_name"],
        runner["activity_name"],
        [winner_scores.get(metric_id, 0) for metric_id in metric_ids],
        [runner_scores.get(metric_id, 0) for metric_id in metric_ids],
        winner["fit_score"] * 100,
        runner["fit_score"] * 100,
    )


def get_decision_export_data(decision_id: int, db: Session) -> dict | None:
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        return None

    activities = (
        db.query(Activity)
        .filter(Activity.decision_id == decision_id)
        .order_by(Activity.id)
        .all()
    )
    metrics = _selected_metrics(decision_id, db)
    results = compute_alternative_fit_scores(decision_id, db)
    thresholds = _parse_json_list(getattr(decision, "thresholds", None))
    filter_result = filter_by_thresholds(decision_id, db) if thresholds else None
    result_basis = (
        filter_result.get("survivor_results", results) if filter_result else results
    )

    scores_by_activity = {}
    for activity in activities:
        scores_by_activity[activity.id] = {
            score.metric_id: score.score
            for score in db.query(AlternativeScore)
            .filter(AlternativeScore.activity_id == activity.id)
            .all()
        }

    weights_by_metric = {}
    if activities:
        for weight in (
            db.query(ActivityWeight)
            .filter(ActivityWeight.activity_id == activities[0].id)
            .all()
        ):
            weights_by_metric[weight.metric_id] = weight.weight

    rows = []
    for metric in metrics:
        rows.append(
            {
                "metric_id": metric.id,
                "metric_name": metric.name,
                "metric_desc": metric.description or "",
                "weight": weights_by_metric.get(metric.id, 50),
                "scores": {
                    activity.name: scores_by_activity.get(activity.id, {}).get(
                        metric.id, 0
                    )
                    for activity in activities
                },
            }
        )

    series = [
        {
            "name": activity.name,
            "scores": [
                scores_by_activity.get(activity.id, {}).get(metric.id, 0)
                for metric in metrics
            ],
        }
        for activity in activities
    ]

    return {
        "decision": {
            "id": decision.id,
            "query": decision.query,
            "mode": getattr(decision, "mode", None) or "choose",
            "created_at": decision.created_at,
            "category": decision.category,
        },
        "activities": [
            {"id": activity.id, "name": activity.name} for activity in activities
        ],
        "metrics": [
            {
                "id": metric.id,
                "name": metric.name,
                "description": metric.description or "",
            }
            for metric in metrics
        ],
        "results": results,
        "series": series,
        "significance": _build_significance(result_basis, metrics, scores_by_activity),
        "ko_result": apply_ko_criteria(decision_id, db),
        "rows": rows,
        "thresholds": thresholds,
        "filter_result": filter_result,
    }


def generate_markdown_brief(data: dict) -> str:
    decision = data["decision"]
    lines = [
        f"# Decision Brief: {decision['query']}",
        "",
        f"- Mode: {decision['mode']}",
        f"- Category: {decision.get('category') or 'General'}",
        f"- Created: {decision['created_at']}",
        "",
        "## Alternatives",
    ]
    for activity in data["activities"]:
        lines.append(f"- {activity['name']}")

    lines.extend(["", "## Ranking"])
    if data["results"]:
        for idx, result in enumerate(data["results"], start=1):
            lines.append(f"{idx}. {result['activity_name']} — {result['fit_pct']}%")
    else:
        lines.append("No scored results yet.")

    ko_result = data.get("ko_result") or {}
    if ko_result.get("eliminated"):
        lines.extend(["", "## Knock-out Criteria"])
        for item in ko_result["eliminated"]:
            lines.append(
                f"- {item['activity_name']}: {'; '.join(item.get('ko_reasons', []))}"
            )

    if data.get("thresholds"):
        lines.extend(["", "## Threshold Filters"])
        metric_names = {m["id"]: m["name"] for m in data["metrics"]}
        for threshold in data["thresholds"]:
            metric_name = metric_names.get(threshold.get("metric_id"), "Unknown metric")
            lines.append(
                f"- {metric_name} {threshold.get('operator', '<=')} {threshold.get('value')}"
            )

    significance = data.get("significance")
    if significance:
        lines.extend(
            [
                "",
                "## Statistical Significance",
                f"- Result: {significance['label']}",
                f"- Compared: {significance['winner_name']} ({significance['winner_avg']}%) vs {significance['runner_name']} ({significance['runner_avg']}%)",
                f"- t-statistic: {significance['t_statistic']}",
                f"- df: {significance['df']}",
                f"- p-value: {significance['p_value']}",
                f"- Mean difference: {significance.get('mean_diff')}",
            ]
        )

    lines.extend(
        [
            "",
            "## Detailed Scores",
            "",
            "| Criterion | Weight | "
            + " | ".join(a["name"] for a in data["activities"])
            + " |",
        ]
    )
    lines.append("|---|---:|" + "---:|" * len(data["activities"]))
    for row in data["rows"]:
        scores = " | ".join(
            str(row["scores"].get(activity["name"], 0))
            for activity in data["activities"]
        )
        lines.append(f"| {row['metric_name']} | {row['weight']} | {scores} |")

    return "\n".join(lines) + "\n"
