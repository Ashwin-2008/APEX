"""Controlled Dataset Growth and Engineering Telemetry Ingestion Pipeline (Phase 4.2 / 4.2.1).

Captures genuine real-world engineering lifecycle events:
1. Git Commit Transitions (commit SHA, parent SHA, changed files/symbols, diff statistics)
2. Finding Lifecycle Transitions (detected, confirmed, remediated, regressed)
3. Test Execution Outcomes (execution status, test failures, flakiness, CI run timestamp)
4. Remediation Results (patch applied, behavioral verification result, rollback trigger)
5. User Confirmations (finding confirmed, false positive, patch accepted)

Guarantees:
- Semantic event idempotency independent of transient retry timestamps
- Thread-safe concurrent ingestion locking
- Strict multi-tenant isolation
- Immutable event audit trail for corrections
- Cryptographic composite verification digests
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import threading
from typing import Any


@dataclass
class TelemetryEvent:
    """An immutable, tenant-isolated engineering telemetry event."""

    event_id: str
    tenant_id: str
    repository_id: str
    event_type: str  # "git_transition", "finding_lifecycle", "test_outcome", "remediation_result", "user_confirmation"
    timestamp: str
    payload: dict[str, Any]
    idempotency_key: str = ""
    verification_status: str = "PENDING_VERIFICATION"  # "PENDING_VERIFICATION", "VERIFIED", "REJECTED"
    provenance: str = "engineering_telemetry"
    event_hash: str = ""

    def __post_init__(self):
        # 1. Establish stable semantic idempotency key if not explicitly provided
        if not self.idempotency_key:
            self.idempotency_key = self._derive_semantic_idempotency_key()

        # 2. Derive deterministic event hash over tenant, repository, event type, idempotency key, and payload
        # Note: Transient wall-clock timestamps are strictly excluded so retries remain idempotent.
        if not self.event_hash:
            canonical_payload = json.dumps(self.payload, sort_keys=True)
            content = f"{self.tenant_id}:{self.repository_id}:{self.event_type}:{self.idempotency_key}:{canonical_payload}"
            self.event_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _derive_semantic_idempotency_key(self) -> str:
        """Computes a stable semantic identity independent of submission timestamp."""
        p = self.payload
        if self.event_type == "git_transition":
            sha = p.get("commit_sha", "unknown_sha")
            return f"git:{sha}"
        if self.event_type == "finding_lifecycle":
            f_id = p.get("finding_id", "unknown_finding")
            state = p.get("lifecycle_state", "unknown_state")
            return f"finding:{f_id}:{state}"
        if self.event_type == "test_outcome":
            c_sha = p.get("commit_sha", "")
            t_name = p.get("test_name", "unknown_test")
            run_id = p.get("ci_run_id", "")
            return f"test:{c_sha}:{t_name}:{run_id}".rstrip(":")
        if self.event_type == "remediation_result":
            patch_id = p.get("patch_id", "unknown_patch")
            v_status = p.get("verification_status", "unknown_status")
            return f"remediation:{patch_id}:{v_status}"
        if self.event_type == "user_confirmation":
            pred_id = p.get("prediction_id", "unknown_pred")
            feedback = p.get("user_feedback", "unknown_feedback")
            return f"feedback:{pred_id}:{feedback}"

        payload_hash = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]
        return f"generic:{payload_hash}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IngestionBatchReport:
    """Summary of a telemetry ingestion batch."""

    total_submitted: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    tenant_id: str
    repository_id: str
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditRecord:
    """Audit log entry for event lifecycle mutations or corrections."""

    timestamp: str
    event_id: str
    action: str  # "INGESTED", "CORRECTED", "PROMOTED_VERIFIED", "REJECTED"
    actor_id: str
    details: dict[str, Any]
    tenant_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DatasetGrowthPipeline:
    """Manages telemetry event validation, tenant isolation, concurrency, and dataset governance."""

    ALLOWED_EVENT_TYPES = {
        "git_transition",
        "finding_lifecycle",
        "test_outcome",
        "remediation_result",
        "user_confirmation",
    }

    def __init__(self):
        self._lock = threading.Lock()
        # Keyed by idempotency_key for true semantic deduplication
        self._events_by_idempotency: dict[str, TelemetryEvent] = {}
        # Keyed by event_id for fast lookup
        self._events_by_id: dict[str, TelemetryEvent] = {}
        # Backward-compatible _events dict
        self._events: dict[str, TelemetryEvent] = {}
        # Append-only audit history
        self._audit_trail: list[AuditRecord] = []

    def ingest_event(
        self,
        tenant_id: str,
        repository_id: str,
        event_type: str,
        payload: dict[str, Any],
        timestamp: str | None = None,
        idempotency_key: str | None = None,
    ) -> TelemetryEvent:
        """Validates and registers an incoming telemetry event with tenant isolation."""
        event, _ = self.ingest_event_ex(
            tenant_id=tenant_id,
            repository_id=repository_id,
            event_type=event_type,
            payload=payload,
            timestamp=timestamp,
            idempotency_key=idempotency_key,
        )
        return event

    def ingest_event_ex(
        self,
        tenant_id: str,
        repository_id: str,
        event_type: str,
        payload: dict[str, Any],
        timestamp: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[TelemetryEvent, bool]:
        """Validates and registers an incoming telemetry event with tenant isolation.

        Returns:
            (event, is_duplicate) tuple.
        """
        if not tenant_id or not repository_id:
            raise ValueError("tenant_id and repository_id are strictly required for data governance.")

        if event_type not in self.ALLOWED_EVENT_TYPES:
            raise ValueError(f"Invalid event_type '{event_type}'. Allowed: {self.ALLOWED_EVENT_TYPES}")

        ts = timestamp or datetime.now(timezone.utc).isoformat()

        # Build candidate event to compute semantic key
        temp_event = TelemetryEvent(
            event_id="",
            tenant_id=tenant_id,
            repository_id=repository_id,
            event_type=event_type,
            timestamp=ts,
            payload=payload,
            idempotency_key=idempotency_key or "",
            verification_status="PENDING_VERIFICATION",
        )

        scoped_key = f"{tenant_id}:{repository_id}:{temp_event.idempotency_key}"

        with self._lock:
            # Check for existing event under this idempotency key
            if scoped_key in self._events_by_idempotency:
                existing = self._events_by_idempotency[scoped_key]
                return existing, True

            # Generate stable event ID from semantic hash
            evt_id = f"evt_{temp_event.event_hash[:16]}"
            temp_event.event_id = evt_id

            self._events_by_idempotency[scoped_key] = temp_event
            self._events_by_id[evt_id] = temp_event
            self._events[temp_event.event_hash] = temp_event

            self._audit_trail.append(
                AuditRecord(
                    timestamp=ts,
                    event_id=evt_id,
                    action="INGESTED",
                    actor_id=tenant_id,
                    details={"event_type": event_type, "idempotency_key": temp_event.idempotency_key},
                    tenant_id=tenant_id,
                )
            )

            return temp_event, False

    def ingest_batch(
        self,
        tenant_id: str,
        repository_id: str,
        raw_events: list[dict[str, Any]],
    ) -> IngestionBatchReport:
        """Processes a batch of telemetry events with duplicate and tenant check."""
        accepted = 0
        rejected = 0
        duplicate = 0
        errors: list[str] = []

        for item in raw_events:
            try:
                evt_type = item.get("event_type")
                payload = item.get("payload", {})
                ts = item.get("timestamp")
                idem_key = item.get("idempotency_key")

                if not evt_type or evt_type not in self.ALLOWED_EVENT_TYPES:
                    rejected += 1
                    errors.append(f"Invalid or missing event_type in record: {item.get('event_id', 'unknown')}")
                    continue

                _, is_dup = self.ingest_event_ex(
                    tenant_id=tenant_id,
                    repository_id=repository_id,
                    event_type=evt_type,
                    payload=payload,
                    timestamp=ts,
                    idempotency_key=idem_key,
                )

                if is_dup:
                    duplicate += 1
                else:
                    accepted += 1
            except Exception as e:
                rejected += 1
                errors.append(str(e))

        return IngestionBatchReport(
            total_submitted=len(raw_events),
            accepted_count=accepted,
            rejected_count=rejected,
            duplicate_count=duplicate,
            tenant_id=tenant_id,
            repository_id=repository_id,
            errors=errors,
        )

    def correct_event(
        self,
        tenant_id: str,
        event_id: str,
        updated_payload: dict[str, Any],
        actor_id: str,
        reason: str = "audit_correction",
    ) -> TelemetryEvent:
        """Audited correction of an ingested event's payload."""
        with self._lock:
            if event_id not in self._events_by_id:
                raise KeyError(f"Event {event_id} not found.")

            event = self._events_by_id[event_id]
            if event.tenant_id != tenant_id:
                raise PermissionError("Access denied: Tenant isolation violation during correction.")

            prev_payload = dict(event.payload)
            event.payload = updated_payload

            # Re-hash with new payload
            canonical_payload = json.dumps(updated_payload, sort_keys=True)
            content = f"{event.tenant_id}:{event.repository_id}:{event.event_type}:{event.idempotency_key}:{canonical_payload}"
            event.event_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            event.verification_status = "PENDING_VERIFICATION"

            ts = datetime.now(timezone.utc).isoformat()
            self._audit_trail.append(
                AuditRecord(
                    timestamp=ts,
                    event_id=event_id,
                    action="CORRECTED",
                    actor_id=actor_id,
                    details={"reason": reason, "prev_payload": prev_payload, "new_payload": updated_payload},
                    tenant_id=tenant_id,
                )
            )
            return event

    def verify_and_promote_events(
        self,
        tenant_id: str,
        repository_id: str,
    ) -> list[TelemetryEvent]:
        """Marks pending events as VERIFIED after passing schema and consistency checks."""
        promoted = []
        with self._lock:
            for evt in self._events_by_id.values():
                if evt.tenant_id == tenant_id and evt.repository_id == repository_id:
                    if evt.verification_status == "PENDING_VERIFICATION":
                        if self._verify_payload_integrity(evt):
                            evt.verification_status = "VERIFIED"
                            promoted.append(evt)
                            self._audit_trail.append(
                                AuditRecord(
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    event_id=evt.event_id,
                                    action="PROMOTED_VERIFIED",
                                    actor_id="system_validator",
                                    details={"idempotency_key": evt.idempotency_key},
                                    tenant_id=tenant_id,
                                )
                            )
                        else:
                            evt.verification_status = "REJECTED"
                            self._audit_trail.append(
                                AuditRecord(
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    event_id=evt.event_id,
                                    action="REJECTED",
                                    actor_id="system_validator",
                                    details={"reason": "payload_integrity_failed"},
                                    tenant_id=tenant_id,
                                )
                            )
        return promoted

    def _verify_payload_integrity(self, evt: TelemetryEvent) -> bool:
        """Verifies semantic completeness of the event payload."""
        payload = evt.payload
        if evt.event_type == "git_transition":
            return bool(payload.get("commit_sha") and ("changed_files" in payload or "target_findings_count" in payload))
        if evt.event_type == "test_outcome":
            return bool(payload.get("test_name") and payload.get("execution_status"))
        if evt.event_type == "remediation_result":
            return bool(payload.get("patch_id") and payload.get("verification_status"))
        if evt.event_type == "finding_lifecycle":
            return bool(payload.get("finding_id") and payload.get("lifecycle_state"))
        if evt.event_type == "user_confirmation":
            return bool(payload.get("user_feedback") in {"CONFIRMED", "REJECTED", "FALSE_POSITIVE"})
        return False

    def list_verified_events(
        self,
        tenant_id: str,
        repository_id: str,
    ) -> list[TelemetryEvent]:
        """Returns all verified events for a given tenant and repository."""
        with self._lock:
            return [
                evt
                for evt in self._events_by_id.values()
                if evt.tenant_id == tenant_id
                and evt.repository_id == repository_id
                and evt.verification_status == "VERIFIED"
            ]

    def compute_pipeline_digest(self, tenant_id: str, repository_id: str) -> str:
        """Computes composite cryptographic digest across all verified events."""
        with self._lock:
            verified_hashes = sorted(
                [
                    evt.event_hash
                    for evt in self._events_by_id.values()
                    if evt.tenant_id == tenant_id
                    and evt.repository_id == repository_id
                    and evt.verification_status == "VERIFIED"
                ]
            )
            composite = ":".join(verified_hashes)
            return hashlib.sha256(composite.encode("utf-8")).hexdigest()

    def get_audit_trail(self, tenant_id: str) -> list[dict[str, Any]]:
        """Returns audit trail for a tenant."""
        with self._lock:
            return [
                a.to_dict()
                for a in self._audit_trail
                if a.tenant_id == tenant_id
                or (a.event_id in self._events_by_id and self._events_by_id[a.event_id].tenant_id == tenant_id)
            ]
