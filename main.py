from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from routers import activities, metrics, candidates, analysis
from routers.decisions import router as decisions_router
from services.parser import parse_question


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="MetricMatch", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(activities.router)
app.include_router(metrics.router)
app.include_router(candidates.router)
app.include_router(analysis.router)
app.include_router(decisions_router)

templates = Jinja2Templates(directory="templates")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    from models import Decision

    decisions = db.query(Decision).order_by(Decision.created_at.desc()).all()
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

    # Parse the question
    parsed = parse_question(query)
    alternatives = parsed["alternatives"]
    criteria_list = parsed["criteria"]
    category = parsed["category"]
    is_parsed = parsed["parsed"]

    # Create the Decision record
    decision = Decision(query=query, category=category)
    db.add(decision)
    db.flush()

    # Create Metric records for each criterion
    metric_objects = {}
    for crit in criteria_list:
        metric = Metric(
            name=crit["name"],
            category=category,
            description=crit["description"],
            higher_is_better=crit["higher_is_better"],
            decision_id=decision.id,
        )
        db.add(metric)
        db.flush()
        metric_objects[crit["name"]] = metric

    # Create Activity records for each alternative
    for alt_name in alternatives:
        activity = Activity(
            name=alt_name,
            category=category,
            decision_id=decision.id,
        )
        db.add(activity)
        db.flush()

        # Create ActivityWeight records for each (activity, metric) pair
        for crit in criteria_list:
            metric = metric_objects[crit["name"]]
            aw = ActivityWeight(
                activity_id=activity.id,
                metric_id=metric.id,
                weight=crit["default_weight"],
            )
            db.add(aw)

    db.commit()

    return templates.TemplateResponse(
        request,
        "decision_review.html",
        {
            "request": request,
            "decision": decision,
            "alternatives": alternatives,
            "criteria": criteria_list,
            "category": category,
            "parsed": is_parsed,
            "active_page": "decisions",
        },
    )
