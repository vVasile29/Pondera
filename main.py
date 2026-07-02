from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.api import router as api_router


def _next_custom_metric_name(base_name: str, existing_names: set[str]) -> str:
    candidate = f"{base_name} (custom)"
    index = 2
    while candidate in existing_names:
        candidate = f"{base_name} (custom {index})"
        index += 1
    return candidate


def reconcile_seed_metrics(db) -> None:
    """Reconcile built-in fit metrics while preserving old seed metric IDs.

    Old user-entered 0–100 scores are preserved with their metric rows. Startup
    renames/re-categorizes mapped seed metrics; it does not invert or transform
    old score values because all ontology metrics are now interpreted as direct
    0–100 fit scores where higher means better fit.
    """
    from models import Metric
    from services.ontology import OLD_TO_NEW_METRIC_NAMES, UNIVERSAL_DIMENSIONS

    existing_by_name = {m.name: m for m in db.query(Metric).all()}
    existing_names = set(existing_by_name)

    def refresh_name_map() -> None:
        existing_by_name.clear()
        existing_by_name.update({m.name: m for m in db.query(Metric).all()})
        existing_names.clear()
        existing_names.update(existing_by_name)

    seed_by_name = {
        metric["name"]: (dimension, metric)
        for dimension in UNIVERSAL_DIMENSIONS
        for metric in dimension["metrics"]
    }

    for old_name, mapped in OLD_TO_NEW_METRIC_NAMES.items():
        new_name = mapped["name"]
        dimension, seed_metric = seed_by_name[new_name]
        old_metric = existing_by_name.get(old_name)
        new_metric = existing_by_name.get(new_name)

        if old_metric and new_metric and old_metric.id != new_metric.id:
            custom_name = _next_custom_metric_name(new_name, existing_names - {new_name})
            new_metric.name = custom_name
            existing_names.discard(new_name)
            existing_names.add(custom_name)
            db.flush()
            refresh_name_map()
            old_metric = existing_by_name.get(old_name)

        metric = old_metric or existing_by_name.get(new_name)
        if metric:
            metric.name = new_name
            metric.category = dimension["name"]
            metric.description = seed_metric["description"]
            db.flush()
            refresh_name_map()

    refresh_name_map()
    for dimension in UNIVERSAL_DIMENSIONS:
        for seed_metric in dimension["metrics"]:
            metric = existing_by_name.get(seed_metric["name"])
            if metric:
                metric.category = dimension["name"]
                metric.description = seed_metric["description"]
            else:
                metric = Metric(
                    name=seed_metric["name"],
                    category=dimension["name"],
                    description=seed_metric["description"],
                )
                db.add(metric)
                db.flush()
                refresh_name_map()

    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    from database import Base, engine, SessionLocal

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        reconcile_seed_metrics(db)
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
app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
