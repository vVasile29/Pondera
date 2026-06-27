from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import ActivityWeight, CandidateScore, Metric
from schemas import MetricCreate, MetricOut, MetricUpdate, SubMetricCreate
from services.suggestions import suggest_activities_for_metric

router = APIRouter(tags=["metrics"])
templates = Jinja2Templates(directory="templates")


@router.get("/metrics", response_class=HTMLResponse)
def list_metrics(request: Request, db: Session = Depends(get_db)):
    metrics = db.query(Metric).order_by(Metric.category, Metric.name).all()

    # Group by category
    grouped = defaultdict(list)
    for m in metrics:
        children = (
            db.query(Metric).filter(Metric.parent_id == m.id).all()
            if m.parent_id is None
            else []
        )
        grouped[m.category].append(
            {
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "description": m.description,
                "unit": m.unit,
                "higher_is_better": m.higher_is_better,
                "parent_id": m.parent_id,
                "children": [
                    {"id": c.id, "name": c.name} for c in children
                ],
                "is_sub_metric": m.parent_id is not None,
            }
        )

    return templates.TemplateResponse(
        request,
        "metric_manager.html",
        {
            "request": request,
            "grouped_metrics": dict(grouped),
            "active_page": "metrics",
        },
    )


@router.post("/metrics")
def create_metric(data: MetricCreate, db: Session = Depends(get_db)):
    existing = db.query(Metric).filter(Metric.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Metric already exists")
    metric = Metric(**data.model_dump())
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return {"id": metric.id, "name": metric.name, "category": metric.category}


@router.put("/metrics/{metric_id}")
def update_metric(
    metric_id: int, data: MetricUpdate, db: Session = Depends(get_db)
):
    metric = db.query(Metric).filter(Metric.id == metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(metric, key, value)
    db.commit()
    return {"id": metric.id, "name": metric.name}


@router.delete("/metrics/{metric_id}")
def delete_metric(metric_id: int, db: Session = Depends(get_db)):
    metric = db.query(Metric).filter(Metric.id == metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    # Delete related activity weights
    db.query(ActivityWeight).filter(
        ActivityWeight.metric_id == metric_id
    ).delete()

    # Delete related candidate scores
    db.query(CandidateScore).filter(
        CandidateScore.metric_id == metric_id
    ).delete()

    # Delete sub-metrics first
    db.query(Metric).filter(Metric.parent_id == metric_id).delete()

    db.delete(metric)
    db.commit()
    return {"status": "deleted"}


@router.post("/metrics/{metric_id}/sub")
def add_sub_metric(
    metric_id: int, data: SubMetricCreate, db: Session = Depends(get_db)
):
    parent = db.query(Metric).filter(Metric.id == metric_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent metric not found")

    # Ensure no grandchildren: parent must not already be a child
    if parent.parent_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot add sub-metrics to a sub-metric (max 1 level deep)",
        )

    sub = Metric(
        name=data.name,
        category=data.category or parent.category,
        description=data.description,
        unit=data.unit,
        higher_is_better=data.higher_is_better,
        parent_id=metric_id,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return {"id": sub.id, "name": sub.name, "parent_id": sub.parent_id}


@router.get("/metrics/{metric_id}/suggest")
def suggest_activities(
    metric_id: int, db: Session = Depends(get_db)
):
    metric = db.query(Metric).filter(Metric.id == metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    return suggest_activities_for_metric(metric.name, db)
