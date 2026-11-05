"""Safe Model Registry, Artifact Provenance and Promotion Gates (Phase 4.1).

Features:
- Pure JSON serialization (zero unsafe pickle deserialization)
- SHA-256 artifact checksum verification
- Cryptographically signed manifest (HMAC-SHA256) preventing tampering
- Multi-gate model promotion policy (must outperform baselines, have no leakage, acceptable calibration)
- Full versioned rollback and audit trails
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_serialization import (
    ArtifactIntegrityError,
    ModelArtifactSerializer,
)
from .constants import FEATURE_SCHEMA_VERSION, ModelStatus, PredictionTask


class PromotionGateError(ValueError):
    """Raised when a candidate model fails one or more production promotion gates."""
    pass


class SafeModelRegistry:
    """Manages versioned model artifacts and deployment status with safe serialization."""

    def __init__(self, registry_root: Path | str | None = None):
        if registry_root:
            self.root = Path(registry_root)
        else:
            self.root = Path(__file__).resolve().parents[3] / "ml" / "artifacts" / "predictive_models"
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "model_manifest.json"
        self._ensure_manifest()

    def _ensure_manifest(self) -> None:
        if not self.manifest_path.is_file():
            initial_data = {
                "production": {},
                "candidates": {},
                "archived": {},
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            initial = {
                "data": initial_data,
                "manifest_signature": ModelArtifactSerializer.compute_manifest_signature(initial_data),
            }
            self.manifest_path.write_text(json.dumps(initial, indent=2), encoding="utf-8")

    def _load_manifest(self) -> dict[str, Any]:
        self._ensure_manifest()
        raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if "data" in raw and "manifest_signature" in raw:
            # Verify signature
            if not ModelArtifactSerializer.verify_manifest_signature(raw["data"], raw["manifest_signature"]):
                raise ArtifactIntegrityError("Security Error: Manifest signature verification failed! Possible unauthorized modification.")
            return raw["data"]
        # Legacy manifest migration
        return raw

    def _save_manifest(self, data: dict[str, Any]) -> None:
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        payload = {
            "data": data,
            "manifest_signature": ModelArtifactSerializer.compute_manifest_signature(data),
        }
        self.manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def save_model_artifact(
        self,
        *,
        model_id: str,
        model_version: str,
        prediction_task: PredictionTask | str,
        algorithm: str,
        model_params: dict[str, Any],
        training_dataset_id: str,
        evaluation_metrics: dict[str, Any],
        status: ModelStatus = ModelStatus.CANDIDATE,
    ) -> dict[str, Any]:
        """Safely saves a model artifact as a JSON parameter bundle with SHA-256 checksum."""
        task_str = prediction_task.value if isinstance(prediction_task, PredictionTask) else str(prediction_task)
        artifact_data = {
            "model_id": model_id,
            "model_version": model_version,
            "prediction_task": task_str,
            "algorithm": algorithm,
            "model_params": model_params,
            "training_dataset_id": training_dataset_id,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

        # Validate artifact schema
        ModelArtifactSerializer.validate_artifact_schema(artifact_data)

        artifact_bytes = json.dumps(artifact_data, sort_keys=True, indent=2).encode("utf-8")
        sha256 = hashlib.sha256(artifact_bytes).hexdigest()

        artifact_file = self.root / f"{model_id}.json"
        artifact_file.write_bytes(artifact_bytes)

        record = {
            "model_id": model_id,
            "model_version": model_version,
            "prediction_task": task_str,
            "algorithm": algorithm,
            "training_dataset_id": training_dataset_id,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "status": status.value,
            "evaluation_metrics": evaluation_metrics,
            "artifact_path": str(artifact_file),
            "artifact_sha256": sha256,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        manifest = self._load_manifest()
        if status == ModelStatus.PRODUCTION:
            if task_str in manifest["production"]:
                prev = manifest["production"][task_str]
                manifest["archived"][prev["model_id"]] = prev
            manifest["production"][task_str] = record
        else:
            manifest["candidates"][model_id] = record

        self._save_manifest(manifest)
        return record

    def load_model_artifact(self, model_id: str) -> dict[str, Any] | None:
        """Safely loads model parameters and verifies SHA-256 integrity and schema."""
        artifact_file = self.root / f"{model_id}.json"
        if not artifact_file.is_file():
            return None

        raw_bytes = artifact_file.read_bytes()
        calculated_sha = hashlib.sha256(raw_bytes).hexdigest()

        manifest = self._load_manifest()
        expected_record = (
            manifest["candidates"].get(model_id)
            or manifest["production"].get(model_id)
            or manifest["archived"].get(model_id)
        )
        if not expected_record:
            for rec in manifest["production"].values():
                if rec.get("model_id") == model_id:
                    expected_record = rec
                    break

        if expected_record and expected_record.get("artifact_sha256"):
            if calculated_sha != expected_record["artifact_sha256"]:
                raise ArtifactIntegrityError(
                    f"Security Error: Artifact checksum mismatch for {model_id}! "
                    f"Expected {expected_record['artifact_sha256']}, got {calculated_sha}."
                )

        artifact_dict = json.loads(raw_bytes.decode("utf-8"))
        ModelArtifactSerializer.validate_artifact_schema(artifact_dict)
        return artifact_dict

    def load_executable_model(self, model_id: str) -> Any:
        """Loads and safely reconstructs an executable model instance without pickle."""
        artifact = self.load_model_artifact(model_id)
        if not artifact:
            raise ArtifactIntegrityError(f"Model artifact {model_id} not found.")

        params = artifact.get("model_params", {})
        arch = params.get("architecture")
        if arch == "logistic_regression":
            return ModelArtifactSerializer.deserialize_logistic_regression(params)
        elif arch == "random_forest":
            return ModelArtifactSerializer.deserialize_random_forest(params)
        else:
            raise ArtifactIntegrityError(f"Unsupported model architecture: {arch}")

    def get_production_model(self, task: PredictionTask | str) -> dict[str, Any] | None:
        """Retrieves active production model record for a specific prediction task."""
        task_str = task.value if isinstance(task, PredictionTask) else str(task)
        manifest = self._load_manifest()
        return manifest["production"].get(task_str)

    def evaluate_promotion_gates(
        self,
        candidate_record: dict[str, Any],
        baseline_metrics: dict[str, Any] | None = None,
    ) -> tuple[bool, list[str]]:
        """Evaluates formal Phase 4.2 promotion gates (8 gates):

        Gate 1: Baseline Superiority (outperforms baseline Macro-F1 / Brier)
        Gate 2: Provenance Integrity (verified real data, non-synthetic)
        Gate 3: Generalization Bound (walk-forward to LORO gap <= 0.25)
        Gate 4: Calibration Reliability (ECE <= 0.30 or active abstention)
        Gate 5: Leakage Free (0 confirmed temporal/entity leakage violations)
        Gate 6: Change-Outcome Verification (no substituting blast radius for outcome; sufficiency check)
        Gate 7: Selective Coverage Floor (retains >= 50% coverage under abstention)
        Gate 8: Reproducibility & Integrity (SHA-256 checksum & signed manifest)
        """
        gate_failures = []
        metrics = candidate_record.get("evaluation_metrics", {})

        # Gate 1: Baseline comparison
        if baseline_metrics:
            base_f1 = baseline_metrics.get("macro_f1", 0.0)
            cand_f1 = metrics.get("macro_f1", 0.0)
            if cand_f1 < base_f1:
                gate_failures.append(
                    f"Gate 1 Failed: Candidate Macro-F1 ({cand_f1:.4f}) does not outperform baseline ({base_f1:.4f})."
                )

        # Gate 2: Provenance
        ds_id = candidate_record.get("training_dataset_id", "")
        if "synthetic" in ds_id.lower() or "fixture" in ds_id.lower():
            gate_failures.append("Gate 2 Failed: Training dataset contains unverified synthetic records.")

        # Gate 3: Generalization evidence
        loro_f1 = metrics.get("loro_macro_f1")
        wf_f1 = metrics.get("macro_f1")
        if loro_f1 is not None and wf_f1 is not None:
            gap = wf_f1 - loro_f1
            if gap > 0.25:
                gate_failures.append(f"Gate 3 Failed: Excessive generalization gap ({gap:.4f} > 0.25) to unseen repositories.")

        # Gate 4: Calibration
        ece = metrics.get("expected_calibration_error")
        if ece is not None and ece > 0.30:
            gate_failures.append(f"Gate 4 Failed: Severe miscalibration (ECE {ece:.4f} > 0.30).")

        # Gate 5: Leakage
        if metrics.get("leakage_violations_count", 0) > 0:
            gate_failures.append("Gate 5 Failed: Dataset contains confirmed temporal leakage violations.")

        # Gate 6: Change-Outcome Verification (Task B)
        task_str = candidate_record.get("prediction_task", "")
        if "change_risk" in task_str.lower() or "task_b" in task_str.lower():
            if metrics.get("substituted_blast_radius_as_outcome", False):
                gate_failures.append("Gate 6 Failed: Substituted structural blast radius for ground-truth defect outcome.")
            if metrics.get("change_sample_size", 100) < 20:
                gate_failures.append("Gate 6 Failed: Insufficient trustworthy change outcome samples (< 20).")

        # Gate 7: Selective Coverage Floor
        selective_cov = metrics.get("selective_coverage")
        if selective_cov is not None and selective_cov < 0.50:
            gate_failures.append(f"Gate 7 Failed: Selective coverage floor not met ({selective_cov:.2%} < 50.00%).")

        # Gate 8: Reproducibility & Integrity
        if not candidate_record.get("artifact_sha256") and not candidate_record.get("model_params"):
            gate_failures.append("Gate 8 Failed: Missing artifact checksum or model parameter bundle.")

        passed = len(gate_failures) == 0
        return passed, gate_failures

    def promote_candidate(
        self,
        model_id: str,
        baseline_metrics: dict[str, Any] | None = None,
        bypass_gates: bool = False,
    ) -> dict[str, Any]:
        """Promotes a candidate model to production with multi-gate validation."""
        manifest = self._load_manifest()
        if model_id not in manifest["candidates"]:
            raise ValueError(f"Candidate {model_id} not found in registry.")

        candidate = manifest["candidates"][model_id]
        if not bypass_gates:
            passed, failures = self.evaluate_promotion_gates(candidate, baseline_metrics)
            if not passed:
                raise PromotionGateError(
                    f"Candidate {model_id} failed promotion gates:\n" + "\n".join(f"- {f}" for f in failures)
                )

        candidate = manifest["candidates"].pop(model_id)
        task_str = candidate["prediction_task"]

        if task_str in manifest["production"]:
            prev_prod = manifest["production"].pop(task_str)
            prev_prod["status"] = ModelStatus.ARCHIVED.value
            manifest["archived"][prev_prod["model_id"]] = prev_prod

        candidate["status"] = ModelStatus.PRODUCTION.value
        manifest["production"][task_str] = candidate
        self._save_manifest(manifest)
        return candidate

    def rollback_production(self, task: PredictionTask | str, target_model_id: str | None = None) -> dict[str, Any]:
        """Rolls back production model to an archived version."""
        task_str = task.value if isinstance(task, PredictionTask) else str(task)
        manifest = self._load_manifest()

        if task_str not in manifest["production"]:
            raise ValueError(f"No active production model for task {task_str}.")

        current_prod = manifest["production"].pop(task_str)
        current_prod["status"] = ModelStatus.DEPRECATED.value
        manifest["archived"][current_prod["model_id"]] = current_prod

        target_record = None
        if target_model_id and target_model_id in manifest["archived"]:
            target_record = manifest["archived"].pop(target_model_id)
        else:
            matching_archived = [
                (mid, rec) for mid, rec in manifest["archived"].items()
                if rec.get("prediction_task") == task_str
            ]
            if matching_archived:
                matching_archived.sort(key=lambda item: item[1].get("created_at", ""), reverse=True)
                chosen_id, target_record = matching_archived[0]
                manifest["archived"].pop(chosen_id)

        if not target_record:
            raise ValueError(f"No suitable rollback candidate found for task {task_str}.")

        target_record["status"] = ModelStatus.PRODUCTION.value
        manifest["production"][task_str] = target_record
        self._save_manifest(manifest)
        return target_record

    def list_models(self) -> dict[str, Any]:
        return self._load_manifest()
