from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.api import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    from database import Base, engine, SessionLocal

    Base.metadata.create_all(bind=engine)
    # Seed re-creation: on every startup, metrics with names matching UNIVERSAL_DIMENSIONS
    # are upserted by name. If a seed metric was deleted, it is re-inserted. If renamed,
    # the old name is re-inserted as a new row and the renamed metric is preserved.
    # If a seed metric's category or description was edited, it is overwritten by the
    # seed defaults on restart.
    # Seed universal metrics and sync built-in metadata by name.
    from services.ontology import UNIVERSAL_DIMENSIONS
    from models import Metric

    db = SessionLocal()
    try:
        existing_by_name = {m.name: m for m in db.query(Metric).all()}
        for dim in UNIVERSAL_DIMENSIONS:
            for m in dim["metrics"]:
                metric = existing_by_name.get(m["name"])
                if metric:
                    metric.category = dim["name"]
                    metric.description = m["description"]
                else:
                    metric = Metric(
                        name=m["name"],
                        category=dim["name"],
                        description=m["description"],
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
app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
