from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Decision ──

class DecisionCreate(BaseModel):
    query: str


class DecisionOut(BaseModel):
    id: int
    query: str
    created_at: datetime

    class Config:
        from_attributes = True


class DecisionReview(BaseModel):
    query: str
    alternatives: List[str]
    criteria: List[dict]
    parsed: bool


# ── Metric ──

class MetricBase(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    unit: Optional[str] = None
    higher_is_better: bool = True
    parent_id: Optional[int] = None


class MetricCreate(MetricBase):
    pass


class MetricUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    unit: Optional[str] = None
    higher_is_better: Optional[bool] = None


class MetricOut(MetricBase):
    id: int

    class Config:
        from_attributes = True


class SubMetricCreate(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    unit: Optional[str] = None
    higher_is_better: bool = True


# ── Activity ──

class ActivityBase(BaseModel):
    name: str
    category: str
    description: Optional[str] = None


class ActivityCreate(ActivityBase):
    pass


class ActivityUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None


class ActivityOut(ActivityBase):
    id: int

    class Config:
        from_attributes = True


# ── ActivityWeight ──

class WeightItem(BaseModel):
    metric_id: int
    weight: float = Field(ge=0.0, le=100.0)


class WeightsUpsert(BaseModel):
    weights: List[WeightItem]


class ActivityWeightOut(BaseModel):
    id: int
    activity_id: int
    metric_id: int
    weight: float

    class Config:
        from_attributes = True


# ── Alternative Score ──

class AlternativeScoreCreate(BaseModel):
    activity_id: int
    metric_id: int
    score: float = Field(ge=0.0, le=100.0)


class AlternativeScoreOut(BaseModel):
    id: int
    activity_id: int
    metric_id: int
    score: float

    class Config:
        from_attributes = True
