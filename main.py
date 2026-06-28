import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from routers import metrics
from routers.decisions import router as decisions_router
from routers.evaluate import router as evaluate_router
from routers.screen import router as screen_router
from routers.rank import router as rank_router
from services.parser import parse_question


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    Base.metadata.create_all(bind=engine)
    # Seed universal metrics if they don't exist
    from services.ontology import UNIVERSAL_DIMENSIONS
    from models import Metric
    from database import SessionLocal

    db = SessionLocal()
    try:
        existing = db.query(Metric).count()
        if existing == 0:
            for dim in UNIVERSAL_DIMENSIONS:
                for m in dim["metrics"]:
                    metric = Metric(
                        name=m["name"],
                        category=dim["name"],
                        description=m["description"],
                        higher_is_better=m["higher_is_better"],
                    )
                    db.add(metric)
            db.commit()
    finally:
        db.close()
    yield


app = FastAPI(title="Pondera", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(metrics.router)
app.include_router(decisions_router)
app.include_router(evaluate_router)
app.include_router(screen_router)
app.include_router(rank_router)

templates = Jinja2Templates(directory="templates")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    from models import Decision

    decisions = db.query(Decision).order_by(Decision.created_at.desc()).all()
    for d in decisions:
        mode = d.mode if hasattr(d, "mode") and d.mode else "choose"
        d.result_url = {
            "diagnose": f"/evaluate/{d.id}/result",
            "screen": f"/screen/{d.id}/result",
            "rank": f"/rank/{d.id}/result",
        }.get(mode, f"/decisions/{d.id}/result")
    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request, "decisions": decisions, "active_page": "home"},
    )


@app.post("/decide")
async def decide(request: Request, db: Session = Depends(get_db)):
    from models import Activity, ActivityWeight, Decision, Metric

    form = await request.form()
    query = form.get("q", "").strip()

    if not query:
        decisions = db.query(Decision).order_by(Decision.created_at.desc()).all()
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "decisions": decisions,
                "query": query,
                "error": "Please enter a question.",
                "active_page": "home",
            },
        )

    # Parse the question — try CHOOSE first
    parsed = parse_question(query)
    alternatives = parsed["alternatives"]
    criteria_list = parsed["criteria"]
    category = parsed["category"]
    is_parsed = parsed["parsed"]

    # If CHOOSE didn't find alternatives, try DIAGNOSE parsing
    if not is_parsed:
        from services.parser import extract_subject

        diag = extract_subject(query)
        if diag["parsed"]:
            # Route as DIAGNOSE
            from services.ontology import UNIVERSAL_METRICS

            decision = Decision(query=query, category="General", mode="diagnose")
            db.add(decision)
            db.flush()

            subject = diag["subject"]
            activity = Activity(
                name=subject, category="General", decision_id=decision.id
            )
            db.add(activity)
            db.flush()

            all_metrics = db.query(Metric).all()
            metric_map = {m.name: m for m in all_metrics}
            for m in UNIVERSAL_METRICS:
                metric = metric_map.get(m["name"])
                if metric:
                    aw = ActivityWeight(
                        activity_id=activity.id,
                        metric_id=metric.id,
                        weight=m["default_weight"],
                    )
                    db.add(aw)
            db.commit()
            return RedirectResponse(
                url=f"/evaluate/{decision.id}/review", status_code=303
            )

        # If DIAGNOSE didn't match, try SCREEN
        from services.parser import extract_thresholds, extract_list

        thresholds = extract_thresholds(query)
        if thresholds:
            # Route as SCREEN
            decision = Decision(query=query, category="General", mode="screen")
            # Map metric names to IDs
            all_metrics = db.query(Metric).all()
            metric_map = {m.name: m for m in all_metrics}
            thresholds_with_ids = []
            for t in thresholds:
                metric = metric_map.get(t["metric_name"])
                if metric:
                    thresholds_with_ids.append(
                        {
                            "metric_id": metric.id,
                            "operator": t["operator"],
                            "value": t["value"],
                        }
                    )
            if thresholds_with_ids:
                decision.thresholds = json.dumps(thresholds_with_ids)
            db.add(decision)
            db.flush()

            from services.ontology import UNIVERSAL_METRICS as UM

            for name in ["Option A", "Option B"]:
                activity = Activity(
                    name=name, category="General", decision_id=decision.id
                )
                db.add(activity)
                db.flush()
                all_metrics = db.query(Metric).all()
                metric_map = {m.name: m for m in all_metrics}
                for m in UM:
                    metric = metric_map.get(m["name"])
                    if metric:
                        aw = ActivityWeight(
                            activity_id=activity.id,
                            metric_id=metric.id,
                            weight=m["default_weight"],
                        )
                        db.add(aw)
            db.commit()
            return RedirectResponse(
                url=f"/screen/{decision.id}/review", status_code=303
            )

        # Try RANK
        list_parsed = extract_list(query)
        if list_parsed["parsed"]:
            # Route as RANK
            decision = Decision(query=query, category="General", mode="rank")
            db.add(decision)
            db.flush()

            from services.ontology import UNIVERSAL_METRICS as UM

            for name in list_parsed["alternatives"]:
                activity = Activity(
                    name=name, category="General", decision_id=decision.id
                )
                db.add(activity)
                db.flush()
                all_metrics = db.query(Metric).all()
                metric_map = {m.name: m for m in all_metrics}
                for m in UM:
                    metric = metric_map.get(m["name"])
                    if metric:
                        aw = ActivityWeight(
                            activity_id=activity.id,
                            metric_id=metric.id,
                            weight=m["default_weight"],
                        )
                        db.add(aw)
            db.commit()
            return RedirectResponse(url=f"/rank/{decision.id}/review", status_code=303)

    # Continue as CHOOSE
    all_metrics = db.query(Metric).all()
    metric_map = {m.name: m for m in all_metrics}

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

        for crit in criteria_list:
            metric = metric_map.get(crit["name"])
            if metric:
                aw = ActivityWeight(
                    activity_id=activity.id,
                    metric_id=metric.id,
                    weight=crit["default_weight"],
                )
                db.add(aw)

    db.commit()

    criteria_with_ids = []
    for c in criteria_list:
        metric = metric_map.get(c["name"])
        criteria_with_ids.append(
            {
                **c,
                "id": metric.id if metric else None,
            }
        )

    return templates.TemplateResponse(
        request,
        "decision_review.html",
        {
            "request": request,
            "decision": decision,
            "alternatives": alternatives,
            "criteria": criteria_with_ids,
            "category": category,
            "parsed": is_parsed,
            "active_page": "decisions",
        },
    )
