from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import Activity, ActivityWeight, Metric
from schemas import (
    ActivityCreate,
    ActivityOut,
    ActivityUpdate,
    WeightsUpsert,
)
from services.monte_carlo import run_monte_carlo

router = APIRouter(tags=["activities"])
templates = Jinja2Templates(directory="templates")


@router.get("/activities", response_class=HTMLResponse)
def list_activities(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(url="/", status_code=302)


@router.post("/activities")
def create_activity(data: ActivityCreate, db: Session = Depends(get_db)):
    existing = db.query(Activity).filter(Activity.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Activity already exists")
    activity = Activity(**data.model_dump())
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return {"id": activity.id, "name": activity.name}


@router.get("/activities/{activity_id}", response_class=HTMLResponse)
def get_activity(request: Request, activity_id: int, db: Session = Depends(get_db)):
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    weights = (
        db.query(ActivityWeight)
        .filter(ActivityWeight.activity_id == activity_id)
        .all()
    )
    weight_map = {w.metric_id: w.weight for w in weights}

    metrics = (
        db.query(Metric)
        .filter(Metric.parent_id.is_(None))
        .order_by(Metric.category, Metric.name)
        .all()
    )

    # Group metrics by category
    from collections import defaultdict

    grouped = defaultdict(list)
    for m in metrics:
        grouped[m.category].append(
            {
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "description": m.description,
                "weight": weight_map.get(m.id, 0),
                "has_weight": m.id in weight_map,
                "sub_metrics": [
                    {
                        "id": sm.id,
                        "name": sm.name,
                        "category": sm.category,
                    }
                    for sm in db.query(Metric)
                    .filter(Metric.parent_id == m.id)
                    .all()
                ],
            }
        )

    return templates.TemplateResponse(
        request,
        "activity_detail.html",
        {
            "request": request,
            "activity": activity,
            "grouped_metrics": dict(grouped),
            "active_page": "activities",
        },
    )


@router.put("/activities/{activity_id}")
def update_activity(
    activity_id: int, data: ActivityUpdate, db: Session = Depends(get_db)
):
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(activity, key, value)
    db.commit()
    return {"id": activity.id, "name": activity.name}


@router.post("/activities/{activity_id}/weights")
def upsert_weights(
    activity_id: int, data: WeightsUpsert, db: Session = Depends(get_db)
):
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    for item in data.weights:
        existing = (
            db.query(ActivityWeight)
            .filter(
                ActivityWeight.activity_id == activity_id,
                ActivityWeight.metric_id == item.metric_id,
            )
            .first()
        )
        if existing:
            existing.weight = item.weight
        else:
            aw = ActivityWeight(
                activity_id=activity_id,
                metric_id=item.metric_id,
                weight=item.weight,
            )
            db.add(aw)
    db.commit()
    return {"status": "ok"}


@router.get("/activities/{activity_id}/mc", response_class=HTMLResponse)
def monte_carlo_page(
    request: Request,
    activity_id: int,
    db: Session = Depends(get_db),
    generate: bool = Query(False),
):
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    results = []
    if generate:
        results = run_monte_carlo(activity_id, db)

    return templates.TemplateResponse(
        request,
        "activity_mc.html",
        {
            "request": request,
            "activity": activity,
            "results": results,
            "active_page": "activities",
        },
    )
