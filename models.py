from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(String(500), nullable=False)
    category = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    activities = relationship("Activity", back_populates="decision", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Decision(id={self.id}, query={self.query!r})>"


class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, index=True, nullable=False)
    category = Column(String, nullable=False)
    description = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    higher_is_better = Column(Boolean, default=True, nullable=False)
    parent_id = Column(Integer, ForeignKey("metrics.id"), nullable=True)

    parent = relationship("Metric", remote_side="Metric.id", backref="children")

    __table_args__ = (
        UniqueConstraint("name", name="uq_metric_name"),
    )

    def __repr__(self):
        return f"<Metric(id={self.id}, name={self.name!r}, category={self.category!r})>"


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, index=True, nullable=False)
    category = Column(String, nullable=False)
    description = Column(String, nullable=True)
    decision_id = Column(Integer, ForeignKey("decisions.id"), nullable=True, index=True)

    weights = relationship("ActivityWeight", back_populates="activity", cascade="all, delete-orphan")
    decision = relationship("Decision", back_populates="activities")

    __table_args__ = (
        UniqueConstraint("name", "decision_id", name="uq_activity_name_decision"),
    )

    def __repr__(self):
        return f"<Activity(id={self.id}, name={self.name!r})>"


class ActivityWeight(Base):
    __tablename__ = "activity_weights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    activity_id = Column(Integer, ForeignKey("activities.id"), nullable=False)
    metric_id = Column(Integer, ForeignKey("metrics.id"), nullable=False)
    weight = Column(Float, nullable=False)  # 0.0–100.0

    activity = relationship("Activity", back_populates="weights")
    metric = relationship("Metric")

    __table_args__ = (
        UniqueConstraint("activity_id", "metric_id", name="uq_activity_metric"),
    )

    def __repr__(self):
        return f"<ActivityWeight(activity={self.activity_id}, metric={self.metric_id}, weight={self.weight})>"


class AlternativeScore(Base):
    __tablename__ = "alternative_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    activity_id = Column(Integer, ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    metric_id = Column(Integer, ForeignKey("metrics.id", ondelete="CASCADE"), nullable=False)
    score = Column(Float, nullable=False)  # 0.0–100.0

    __table_args__ = (
        UniqueConstraint("activity_id", "metric_id", name="uq_alt_metric_score"),
    )

    def __repr__(self):
        return f"<AlternativeScore(activity={self.activity_id}, metric={self.metric_id}, score={self.score})>"
