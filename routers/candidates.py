import random
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import Activity, Candidate, CandidateScore, Metric
from schemas import CandidateCreate, CompareRequest
from services.scoring import compute_fit_scores_for_all_activities

router = APIRouter(tags=["candidates"])
templates = Jinja2Templates(directory="templates")


@router.get("/candidates", response_class=HTMLResponse)
def list_candidates(request: Request, db: Session = Depends(get_db)):
    candidates = db.query(Candidate).order_by(Candidate.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "candidate_list.html",
        {
            "request": request,
            "candidates": candidates,
            "active_page": "candidates",
        },
    )


@router.post("/candidates")
def create_candidate(data: CandidateCreate, db: Session = Depends(get_db)):
    candidate = Candidate(name=data.name)
    db.add(candidate)
    db.flush()

    for metric_id, score in data.scores.items():
        cs = CandidateScore(
            candidate_id=candidate.id,
            metric_id=metric_id,
            score=score,
        )
        db.add(cs)
    db.commit()
    db.refresh(candidate)
    return {"id": candidate.id, "name": candidate.name}


@router.get("/candidates/new", response_class=HTMLResponse)
def new_candidate_form(request: Request, db: Session = Depends(get_db)):
    """Show the candidate creation form with all metric sliders."""
    metrics = (
        db.query(Metric)
        .filter(Metric.parent_id.is_(None))
        .order_by(Metric.category, Metric.name)
        .all()
    )

    from collections import defaultdict

    grouped = defaultdict(list)
    for m in metrics:
        grouped[m.category].append(
            {
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "description": m.description,
                "unit": m.unit,
            }
        )

    candidates = db.query(Candidate).order_by(Candidate.created_at.desc()).all()

    return templates.TemplateResponse(
        request,
        "candidate_form.html",
        {
            "request": request,
            "grouped_metrics": dict(grouped),
            "candidates": candidates,
            "active_page": "candidates",
        },
    )


@router.get("/candidates/random", response_class=HTMLResponse)
def random_candidate(request: Request, db: Session = Depends(get_db)):
    """Generate a random candidate and show results."""
    candidate = Candidate(name=f"Random #{random.randint(1000, 9999)}")
    db.add(candidate)
    db.flush()

    metrics = (
        db.query(Metric)
        .filter(Metric.parent_id.is_(None))
        .all()
    )
    for metric in metrics:
        score = round(random.uniform(0, 100), 1)
        cs = CandidateScore(
            candidate_id=candidate.id,
            metric_id=metric.id,
            score=score,
        )
        db.add(cs)
    db.commit()
    db.refresh(candidate)

    return RedirectResponse(
        url=f"/candidates/{candidate.id}", status_code=303
    )


@router.get("/candidates/{candidate_id}", response_class=HTMLResponse)
def get_candidate(request: Request, candidate_id: int, db: Session = Depends(get_db)):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    scores = {cs.metric_id: cs.score for cs in candidate.scores}
    results = compute_fit_scores_for_all_activities(candidate_id, db)
    top_results = results[:10]

    metrics = (
        db.query(Metric)
        .filter(Metric.parent_id.is_(None))
        .order_by(Metric.category, Metric.name)
        .all()
    )

    metric_scores = []
    for m in metrics:
        metric_scores.append(
            {
                "metric_id": m.id,
                "metric_name": m.name,
                "category": m.category,
                "score": scores.get(m.id, 0),
            }
        )

    return templates.TemplateResponse(
        request,
        "candidate_result.html",
        {
            "request": request,
            "candidate": candidate,
            "results": top_results,
            "metric_scores": metric_scores,
            "active_page": "candidates",
        },
    )


@router.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    db.delete(candidate)
    db.commit()
    return {"status": "deleted"}


@router.post("/candidates/compare", response_class=HTMLResponse)
def compare_candidates(
    request: Request,
    data: CompareRequest,
    db: Session = Depends(get_db),
):
    candidates = (
        db.query(Candidate)
        .filter(Candidate.id.in_(data.candidate_ids))
        .all()
    )
    if len(candidates) < 2:
        raise HTTPException(
            status_code=400,
            detail="Need at least 2 candidates to compare",
        )

    all_metric_ids = set()
    candidate_data = []
    for cand in candidates:
        scores = {cs.metric_id: cs.score for cs in cand.scores}
        all_metric_ids.update(scores.keys())
        results = compute_fit_scores_for_all_activities(cand.id, db)
        candidate_data.append(
            {
                "id": cand.id,
                "name": cand.name,
                "scores": scores,
                "results": results[:5],
            }
        )

    metrics = (
        db.query(Metric)
        .filter(Metric.id.in_(all_metric_ids))
        .all()
    )
    metric_map = {m.id: m.name for m in metrics}
    metric_categories = {m.id: m.category for m in metrics}

    return templates.TemplateResponse(
        request,
        "compare.html",
        {
            "request": request,
            "candidates": candidate_data,
            "metrics": metrics,
            "metric_map": metric_map,
            "metric_categories": metric_categories,
            "all_metric_ids": sorted(all_metric_ids),
            "active_page": "candidates",
        },
    )
