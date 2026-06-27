from typing import List

from sqlalchemy.orm import Session

from models import Activity, Metric


def suggest_activities_for_metric(metric_name: str, db: Session) -> List[dict]:
    """Suggest which activities might use a newly created metric.

    Based on category similarity: activities whose category matches
    the metric's category are suggested.
    """
    metric = db.query(Metric).filter(Metric.name == metric_name).first()
    if not metric:
        return []

    # Activities in the same category as the metric
    activities = (
        db.query(Activity)
        .filter(Activity.category == metric.category)
        .all()
    )

    results = []
    for activity in activities:
        results.append(
            {
                "activity_id": activity.id,
                "activity_name": activity.name,
                "reason": f"Shares category '{metric.category}' with this metric",
            }
        )

    # Also suggest activities that already have metrics from the same category
    from models import ActivityWeight

    related = (
        db.query(Activity)
        .join(ActivityWeight, ActivityWeight.activity_id == Activity.id)
        .join(Metric, Metric.id == ActivityWeight.metric_id)
        .filter(Metric.category == metric.category)
        .filter(Activity.id.notin_([a.id for a in activities]))
        .distinct()
        .all()
    )
    for activity in related:
        results.append(
            {
                "activity_id": activity.id,
                "activity_name": activity.name,
                "reason": f"Already uses metrics from category '{metric.category}'",
            }
        )

    return results
