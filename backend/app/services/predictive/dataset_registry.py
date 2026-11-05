"""Dataset Registry and Provenance Auditing Service (Phase 4).

Manages dataset registration, provenance auditing, and sample count inspections.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PredictiveDatasetRecord, ReviewedProject
from .constants import FEATURE_SCHEMA_VERSION, PREDICTIVE_DATASET_VERSION, ProvenanceClassification
from .label_quality import LabelQualityAssessor
from .temporal_dataset import TemporalObservation


class DatasetRegistry:
    """Manages versioned temporal engineering datasets with provenance auditing."""

    @classmethod
    def register_dataset(
        cls,
        session: Session,
        *,
        dataset_id: str,
        project_id: int | None,
        observations: list[TemporalObservation],
        dataset_version: str = PREDICTIVE_DATASET_VERSION,
        provenance_classification: ProvenanceClassification | str = ProvenanceClassification.CURATED_REAL,
        label_source: str = "chronological_review_transitions",
    ) -> PredictiveDatasetRecord:
        """Registers a dataset record in the database."""
        prov_str = (
            provenance_classification.value
            if isinstance(provenance_classification, ProvenanceClassification)
            else str(provenance_classification)
        )

        n = len(observations)
        t_start = min((o.source_timestamp for o in observations if o.source_timestamp), default=None)
        t_end = max((o.source_timestamp for o in observations if o.source_timestamp), default=None)

        avg_conf = (
            round(sum(o.label_confidence for o in observations) / n, 4) if n > 0 else 0.0
        )

        # Category distribution
        cats: dict[str, int] = {}
        for o in observations:
            cats[o.target] = cats.get(o.target, 0) + 1

        metadata = {
            "category_distribution": cats,
            "synthetic_count": sum(1 for o in observations if o.is_synthetic),
            "real_count": sum(1 for o in observations if not o.is_synthetic),
            "distinct_repository_groups": len(set(o.repository_group for o in observations)),
        }

        record = PredictiveDatasetRecord(
            dataset_id=dataset_id,
            project_id=project_id,
            dataset_version=dataset_version,
            provenance_classification=prov_str,
            label_source=label_source,
            label_confidence=avg_conf,
            time_range_start=t_start,
            time_range_end=t_end,
            sample_count=n,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            metadata_json=metadata,
        )

        existing = session.scalar(
            select(PredictiveDatasetRecord).where(PredictiveDatasetRecord.dataset_id == dataset_id)
        )
        if existing:
            existing.sample_count = n
            existing.metadata_json = metadata
            existing.label_confidence = avg_conf
            existing.time_range_start = t_start
            existing.time_range_end = t_end
            session.commit()
            session.refresh(existing)
            return existing

        session.add(record)
        session.commit()
        session.refresh(record)
        return record

    @classmethod
    def list_datasets(cls, session: Session, project_id: int | None = None) -> list[dict[str, Any]]:
        """Lists registered datasets with provenance audits."""
        query = select(PredictiveDatasetRecord).order_by(PredictiveDatasetRecord.created_at.desc())
        if project_id is not None:
            query = query.where(
                (PredictiveDatasetRecord.project_id == project_id) | (PredictiveDatasetRecord.project_id.is_(None))
            )
        records = list(session.scalars(query).all())
        return [
            {
                "id": r.id,
                "dataset_id": r.dataset_id,
                "project_id": r.project_id,
                "dataset_version": r.dataset_version,
                "provenance_classification": r.provenance_classification,
                "label_source": r.label_source,
                "label_confidence": r.label_confidence,
                "time_range_start": r.time_range_start,
                "time_range_end": r.time_range_end,
                "sample_count": r.sample_count,
                "feature_schema_version": r.feature_schema_version,
                "metadata": r.metadata_json,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]

