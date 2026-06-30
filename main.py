from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from routers import metrics
from routers.api import router as api_router
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


app = FastAPI(title="Optium", lifespan=lifespan)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip() and origin.strip() != "*"
]

# CORS — allow explicit origins only; Docker production is same-origin via nginx
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=bool(cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(metrics.router)
app.include_router(api_router)
app.include_router(decisions_router)
app.include_router(evaluate_router)
app.include_router(screen_router)
app.include_router(rank_router)


@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


@app.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    from models import Decision

    decisions = db.query(Decision).order_by(Decision.created_at.desc()).all()
    result = []
    for d in decisions:
        mode = d.mode if hasattr(d, "mode") and d.mode else "choose"
        result_url = {
            "diagnose": f"/evaluate/{d.id}/result",
            "screen": f"/screen/{d.id}/result",
            "rank": f"/rank/{d.id}/result",
        }.get(mode, f"/decisions/{d.id}/result")
        result.append(
            {
                "id": d.id,
                "query": d.query,
                "mode": mode,
                "category": d.category,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "result_url": result_url,
            }
        )
    return {"decisions": result}


@app.post("/decide")
async def decide(request: Request, db: Session = Depends(get_db)):
    from models import Activity, ActivityWeight, Decision, Metric
    from services.ontology import UNIVERSAL_METRICS

    form = await request.form()
    query = form.get("q", "").strip()

    # ── Helper: seed default weights for one activity ──
    def _seed_default_weights(activity_id: int) -> None:
        all_metrics = db.query(Metric).all()
        metric_map = {m.name: m for m in all_metrics}
        for m in UNIVERSAL_METRICS:
            metric = metric_map.get(m["name"])
            if metric:
                db.add(
                    ActivityWeight(
                        activity_id=activity_id,
                        metric_id=metric.id,
                        weight=m["default_weight"],
                    )
                )

    if not query:
        return JSONResponse(
            {"error": "Please enter a question."},
            status_code=400,
        )

    # ── Heuristic routing (auto-detect mode from query) ──
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
            decision = Decision(query=query, category="General", mode="diagnose")
            db.add(decision)
            db.flush()

            subject = diag["subject"]
            activity = Activity(
                name=subject, category="General", decision_id=decision.id
            )
            db.add(activity)
            db.flush()
            _seed_default_weights(activity.id)
            db.commit()
            return RedirectResponse(
                url=f"/evaluate/{decision.id}/review", status_code=303
            )

        # If DIAGNOSE didn't match, try RANK
        from services.parser import extract_list

        list_parsed = extract_list(query)
        if list_parsed["parsed"]:
            # Route as RANK
            decision = Decision(query=query, category="General", mode="rank")
            db.add(decision)
            db.flush()

            for name in list_parsed["alternatives"]:
                activity = Activity(
                    name=name, category="General", decision_id=decision.id
                )
                db.add(activity)
                db.flush()
                _seed_default_weights(activity.id)

            db.commit()
            return RedirectResponse(url=f"/rank/{decision.id}/review", status_code=303)

    # Continue as CHOOSE
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
        _seed_default_weights(activity.id)

    db.commit()

    all_metrics = db.query(Metric).all()
    metric_map = {m.name: m for m in all_metrics}
    criteria_with_ids = []
    for c in criteria_list:
        metric = metric_map.get(c["name"])
        criteria_with_ids.append(
            {
                **c,
                "id": metric.id if metric else None,
            }
        )

    return {
        "decision_id": decision.id,
        "mode": decision.mode if decision.mode else "choose",
        "query": decision.query,
        "category": category,
        "alternatives": alternatives,
        "criteria": criteria_with_ids,
        "parsed": is_parsed,
        "redirect_url": f"/decisions/{decision.id}/review",
    }
