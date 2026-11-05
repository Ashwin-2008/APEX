"""Prediction Feedback and Learning Loop (Phase 4).

Allows authorized engineering users to record ground-truth validation feedback
without mutating model weights directly or causing single-event drift.
"""
from __future__ import annotations

from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PredictiveFeedbackRecord, PredictivePredictionRecord
from .constants import FeedbackCategory


class PredictionFeedbackService:
    """Manages recording, validation, and analytics for prediction feedback."""

    @classmethod
    def record_feedback(
        cls,
        session: Session,
        *,
        project_id: int,
        prediction_id: str,
        user_id: int | None,
        feedback_category: FeedbackCategory | str,
        notes: str | None = None,
    ) -> PredictiveFeedbackRecord:
        """Stores feedback isolated from original prediction outputs."""
        prediction = session.scalar(
            select(PredictivePredictionRecord).where(
                PredictivePredictionRecord.prediction_id == prediction_id,
                PredictivePredictionRecord.project_id == project_id,
            )
        )
        if not prediction:
            raise ValueError(f"Prediction {prediction_id} not found in project {project_id}.")

        cat_str = feedback_category.value if isinstance(feedback_category, FeedbackCategory) else str(feedback_category)
        if cat_str not in {c.value for c in FeedbackCategory}:
            raise ValueError(f"Invalid feedback category: {cat_str}")

        record = PredictiveFeedbackRecord(
            prediction_id=prediction_id,
            project_id=project_id,
            user_id=user_id,
            feedback_category=cat_str,
            notes=notes,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record

    @classmethod
    def get_feedback_metrics(cls, session: Session, project_id: int) -> dict[str, Any]:
        """Calculates feedback distribution and user agreement rates."""
        records = list(
            session.scalars(
                select(PredictiveFeedbackRecord).where(PredictiveFeedbackRecord.project_id == project_id)
            ).all()
        )
        total = len(records)
        counts = {c.value: 0 for c in FeedbackCategory}
        for r in records:
            counts[r.feedback_category] = counts.get(r.feedback_category, 0) + 1

        correct = counts.get(FeedbackCategory.CORRECT.value, 0)
        partially = counts.get(FeedbackCategory.PARTIALLY_CORRECT.value, 0)
        accuracy_rate = round((correct + 0.5 * partially) / total, 4) if total > 0 else 0.0

        return {
            "total_feedback_events": total,
            "distribution": counts,
            "user_confirmed_accuracy_rate": accuracy_rate,
            "eligible_for_retraining_review": total >= 10,
        }

