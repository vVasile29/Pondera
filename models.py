from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    DateTime,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from database import Base


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(String(500), nullable=False)
    category = Column(String, nullable=True)
    mode = Column(String, default="choose", nullable=False)
    thresholds = Column(
        String, nullable=True
    )  # JSON string: [{"metric_id": 1, "operator": ">=", "value": 60}]
    ko_criteria = Column(
        String, nullable=True
    )  # JSON string: [{"metric_id": 1, "ko_operator": "<=", "ko_value": 50}]
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    activities = relationship(
        "Activity", back_populates="decision", cascade="all, delete-orphan"
    )

    weights = relationship(
        "DecisionWeight", back_populates="decision", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Decision(id={self.id}, query={self.query!r})>"


class DecisionWeight(Base):
    __tablename__ = "decision_weights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(
        Integer,
        ForeignKey("decisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_id = Column(
        Integer, ForeignKey("metrics.id", ondelete="CASCADE"), nullable=False
    )
    weight = Column(Float, nullable=False)  # 0.0–100.0

    decision = relationship("Decision", back_populates="weights")
    metric = relationship("Metric")

    __table_args__ = (
        UniqueConstraint("decision_id", "metric_id", name="uq_decision_metric_weight"),
    )

    def __repr__(self):
        return f"<DecisionWeight(decision={self.decision_id}, metric={self.metric_id}, weight={self.weight})>"


class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, index=True, nullable=False)
    category = Column(String, nullable=False)
    description = Column(String, nullable=True)
    decision_id = Column(
        Integer,
        ForeignKey("decisions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scope = Column(String, nullable=False, default="global")
    source = Column(String, nullable=False, default="template")

    def __repr__(self):
        return f"<Metric(id={self.id}, name={self.name!r}, category={self.category!r})>"


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, index=True, nullable=False)
    category = Column(String, nullable=False)
    description = Column(String, nullable=True)
    decision_id = Column(
        Integer, ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    decision = relationship("Decision", back_populates="activities")

    __table_args__ = (
        UniqueConstraint("name", "decision_id", name="uq_activity_name_decision"),
    )

    def __repr__(self):
        return f"<Activity(id={self.id}, name={self.name!r})>"


class AlternativeScore(Base):
    __tablename__ = "alternative_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    activity_id = Column(
        Integer, ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    metric_id = Column(
        Integer, ForeignKey("metrics.id", ondelete="CASCADE"), nullable=False
    )
    score = Column(Float, nullable=False)  # 0.0–100.0

    __table_args__ = (
        UniqueConstraint("activity_id", "metric_id", name="uq_alt_metric_score"),
    )

    def __repr__(self):
        return f"<AlternativeScore(activity={self.activity_id}, metric={self.metric_id}, score={self.score})>"


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(Integer, ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False, index=True)
    activity_id = Column(Integer, ForeignKey("activities.id", ondelete="CASCADE"), nullable=True, index=True)
    metric_id = Column(Integer, ForeignKey("metrics.id", ondelete="CASCADE"), nullable=True, index=True)
    claim = Column(String(1000), nullable=False)
    rationale = Column(String(2000), nullable=True)
    source_type = Column(String(20), nullable=False, default="human")
    source_label = Column(String(120), nullable=True)
    source_url = Column(String(1000), nullable=True)
    confidence = Column(Float, nullable=True)
    polarity = Column(String(20), nullable=True)
    review_status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_evidence_decision_activity_metric", "decision_id", "activity_id", "metric_id"),
        Index("ix_evidence_decision_status", "decision_id", "review_status"),
    )


class ScoreDraft(Base):
    __tablename__ = "score_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(Integer, ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False, index=True)
    activity_id = Column(Integer, ForeignKey("activities.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_id = Column(Integer, ForeignKey("metrics.id", ondelete="CASCADE"), nullable=False, index=True)
    suggested_score = Column(Float, nullable=False)
    human_adjusted_score = Column(Float, nullable=True)
    rationale = Column(String(2000), nullable=True)
    source_type = Column(String(20), nullable=False, default="human")
    source_label = Column(String(120), nullable=True)
    confidence = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    applied_score_id = Column(Integer, ForeignKey("alternative_scores.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    applied_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_score_drafts_decision_status", "decision_id", "status"),
        Index("ix_score_drafts_decision_cell", "decision_id", "activity_id", "metric_id"),
    )


class ScoreDraftEvidence(Base):
    __tablename__ = "score_draft_evidence"

    score_draft_id = Column(Integer, ForeignKey("score_drafts.id", ondelete="CASCADE"), primary_key=True)
    evidence_item_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), primary_key=True, index=True)
