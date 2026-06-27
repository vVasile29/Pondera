from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Activity, Candidate, Metric
from services.scoring import compute_fit_score, compute_preview_fit_scores

router = APIRouter(tags=["analysis"])


class PreviewRequest(BaseModel):
    scores: Dict[str, float]  # metric_id -> score (0–100)


@router.post("/analysis/preview")
def preview_scores(data: PreviewRequest, db: Session = Depends(get_db)):
    """Compute top-3 activity fits from a scores dict (live preview)."""
    scores = {int(k): v for k, v in data.scores.items()}
    results = compute_preview_fit_scores(scores, db)
    return {"results": results}


@router.get("/analysis/what-if")
def what_if(
    candidate_id: int = Query(...),
    metric_id: int = Query(...),
    new_score: float = Query(..., ge=0.0, le=100.0),
    db: Session = Depends(get_db),
):
    """Recompute fit scores for all activities if a metric score changes."""
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    metric = db.query(Metric).filter(Metric.id == metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    # Temporarily override the score in-memory to compute what-if
    # We do this by creating a temporary score object
    from models import CandidateScore

    original_score = (
        db.query(CandidateScore)
        .filter(
            CandidateScore.candidate_id == candidate_id,
            CandidateScore.metric_id == metric_id,
        )
        .first()
    )

    # Save original for restoration
    orig_value = original_score.score if original_score else None

    # Temporarily update or create in-memory
    if original_score:
        original_score.score = new_score
        db.flush()
    else:
        temp_score = CandidateScore(
            candidate_id=candidate_id,
            metric_id=metric_id,
            score=new_score,
        )
        db.add(temp_score)
        db.flush()

    # Compute new fit scores
    activities = db.query(Activity).all()
    results = []
    for activity in activities:
        fit = compute_fit_score(candidate_id, activity.id, db)
        results.append(
            {
                "activity_id": activity.id,
                "activity_name": activity.name,
                "fit_score": round(fit, 4),
            }
        )

    results.sort(key=lambda x: x["fit_score"], reverse=True)

    # Restore original
    if original_score:
        if orig_value is not None:
            original_score.score = orig_value
        else:
            db.delete(original_score)
    else:
        # Remove the temp score we added
        db.query(CandidateScore).filter(
            CandidateScore.candidate_id == candidate_id,
            CandidateScore.metric_id == metric_id,
        ).delete()
    db.flush()

    return {"candidate_id": candidate_id, "results": results[:10]}
