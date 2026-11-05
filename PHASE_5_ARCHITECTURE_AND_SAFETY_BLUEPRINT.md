# APEX 2.0 — PHASE 5: AUTONOMOUS REMEDIATION & SELF-HEALING ENGINEERING INTELLIGENCE
# Phase 5.0 — Architecture, Safety Engineering & Implementation Blueprint

**Document Version**: 5.0.0-PROD-SPEC  
**Author**: Principal Software Architect & Autonomous Systems Engineering Lead (Antigravity Core Team)  
**Date**: November 4, 2026  
**Status**: APPROVED ARCHITECTURAL BLUEPRINT  
**Preceding Phases Certified**: Phase 1, 2A–2D.2, 3, 3.1, 3.2, 3.2.1, 4, 4.1, 4.2, 4.2.1  

---

## 1. Executive Summary & Architectural Vision

APEX 2.0 has established repository multi-analyzer intelligence, runtime trace reconciliation, transactional remediation primitives, multi-hop engineering knowledge graphs, and temporal failure prediction. 

**Phase 5** advances APEX from an analytical and predictive advisor into an **Autonomous Project Engineering Intelligence Platform** capable of detecting problems, diagnosing root causes, synthesizing multi-file patches, executing rigorous isolated sandbox verification, enforcing risk-calibrated human approval governance, applying changes transactionally, and closing the learning loop.

### Foundational Principle: Controlled Autonomy
> **APEX must become autonomous without becoming uncontrolled.**  
> Intelligence helps decide what to investigate and what to fix.  
> Deterministic safety rules decide what is permitted.  
> Layered sandbox verification establishes whether the patch works.  
> Risk-calibrated authorization determines whether changes may be applied.  
> Transactional journaling and leases ensure crash recovery and deterministic rollback.  
> **Under no circumstances may a statistical model or confidence score bypass human authorization.**

---

## 2. Complete Existing Architecture Audit

### 2.1 Multi-User Authentication & Tenant Isolation
- **Authentication**: JWT Bearer token authentication backed by `app.models.entities.User` with hashed passwords (`passlib.bcrypt`).
- **Isolation Guarantee**: Every project entity (`ReviewedProject`), review record (`ProjectReview`), finding (`ProjectFinding`), transaction (`RemediationTransaction`), and telemetry event (`TelemetryEvent`) carries `user_id` and `tenant_id` scopes.
- **Tenant Integrity**: All database queries enforce tenant filtering (`where(ReviewedProject.user_id == current_user.id)`). In Phase 4.2.1, cross-tenant telemetry ingestion or mutation throws immediate `PermissionError`.

### 2.2 Ten Specialized Engineering Analyzers
APEX incorporates 10 deterministic analyzers executed during review runs:
1. `architecture_analyzer.py`: Circular dependencies, layer separation violations, fan-in/fan-out bounds.
2. `security_analyzer.py`: AST-based pattern matching (CWE-89 SQLi, CWE-78 command injection, CWE-79 XSS, hardcoded secrets, weak crypto).
3. `type_analyzer.py`: Static type coverage, type inconsistency, signature mismatches.
4. `runtime_analyzer.py`: Dynamic execution trace capture, exception capture, hot-path bottleneck profiling.
5. `concurrency_analyzer.py`: Thread contention, race conditions, shared mutable state hazards.
6. `testing_analyzer.py`: Test suite discovery, coverage gaps, flaky test indicators.
7. `dependency_analyzer.py`: Outdated packages, known CVE lookup, transitive license risks.
8. `configuration_analyzer.py`: Dockerfile, CI/CD YAML, environment configuration drift.
9. `database_analyzer.py`: Unindexed foreign keys, N+1 query patterns, schema migration drift.
10. `api_analyzer.py`: OpenAPI contract drift, undocumented endpoints, breaking route mutations.

### 2.3 Knowledge Graph Subsystem (Phase 3 – 3.2.1)
- **Node Entities**: `EngineeringGraphNode` tracking canonical identities across 10 node types (`FILE`, `MODULE`, `CLASS`, `FUNCTION`, `API_ROUTE`, `DATABASE_TABLE`, `TEST_CASE`, `DEPENDENCY`, `CONFIG_SETTING`, `ANALYZER_FINDING`).
- **Edge Types**: `CALLS`, `IMPORTS`, `CONTAINS`, `TESTS`, `WRITES_TABLE`, `READS_TABLE`, `EXPOSES_API`, `DEPENDS_ON`, `AFFECTS`.
- **Identity Continuity**: Multi-signal similarity matcher (`identity_continuity.py`) preserving node identity across git commit renames and refactoring.
- **Transactional Updater**: Graph modifications staged in `EngineeringGraphUpdateJournal` before atomic commit with rollback safety.
- **Impact & Test Selection**: Multi-hop blast-radius calculation (`blast_radius.py`) and targeted test selection (`test_selector.py`) achieving MRR = 0.833 over file proximity baselines.

### 2.4 Remediation Subsystem (Phase 2D.1 – 2D.2)
APEX already possesses an enterprise-grade remediation foundation in `backend/app/services/remediation/`:
- **`MultiFileTransactionEngine`**: Transaction journals in `.apex_backup/transactions/<txn_id>/`, pre/post SHA-256 source hash validation, staged replacement files, and rollback conflict detection (`RollbackConflictError`).
- **`RepositoryLockManager`**: Lease acquisition, heartbeat renewal, and fencing tokens preventing concurrent writer collisions.
- **`CrashRecoveryEngine`**: Recovers half-applied transactions on server restart via journal replay or rollback.
- **`PatchGenerator`**: AST transformations, unified diff generation, and deterministic regex replacements.
- **`PatchVerifier`**: Syntax verification (`ast.parse`), isolated directory sandbox testing, and pytest execution.
- **`SemanticVerifier`**: Function contract preservation (parameter counts, return types, exception safety).
- **`BehavioralVerifier`**: Regression detection comparing pre-patch and post-patch test execution results.
- **`PatchLifecycleManager`**: State tracking (`GENERATED`, `VERIFICATION_PENDING`, `VERIFIED`, `APPLIED`, `REMEDIATION_CONFIRMED`).

### 2.5 Predictive Intelligence Subsystem (Phase 4 – 4.2.1)
- **Authority Structure**: `Rule-Based Engineering Risk` is the sole production authority (Macro-F1: 0.835 on LORO). Machine learning models (Random Forest, Logistic Regression) remain strictly `EXPERIMENTAL`.
- **Dataset Growth Pipeline**: Idempotent telemetry ingestion (`DatasetGrowthPipeline`), semantic hashing excluding retry timestamps, and audited event correction.
- **Selective Prediction**: Abstention engine with exact sample accounting and 100% OOD detection sensitivity.

---

## 3. Phase 4 Final Closeout & Verification Summary

Prior to initiating Phase 5 architectural specifications, the Phase 4 and 4.2.1 implementations were independently verified:

### 3.1 Dataset Reconciliation (129 vs. 30 Observations)
1. **129-Observation Curated Dataset (`dataset_v001.jsonl`)**: Represents the full multi-class (9 classes: security, architecture, testing, dependency, error_handling, data_integrity, requirements, deployment, configuration) historical repository transition dataset harvested across 9 real projects.
2. **30-Observation Acceptance Benchmark**: Represents a controlled, multi-repository benchmark fixture (balanced distributions across 3 isolated repositories) specifically calibrated to prove protocol mathematical independence without fold-level class starvation.
3. **Cross-Protocol Partitioning**:
   - Walk-Forward: Evaluates 3 chronological folds ($T_{\text{train}} < T_{\text{test}}$). Rule-Based Brier = `0.0644`.
   - Repo-Grouped: Evaluates 5 repository-isolated folds ($R_{\text{train}} \cap R_{\text{val}} = \emptyset$). Rule-Based Brier = `0.0788`.
   - LORO: Evaluates 6 held-out repository folds. Rule-Based Brier = `0.0769`.
   - **Conclusion**: The identical Brier score reported in Phase 4.2 documentation was caused by static template text in the frontend/markdown view. Mathematical independence is fully proven.

### 3.2 Multi-Process Telemetry Idempotency
- **Test Executed**: Multi-process concurrent stress script spawning 4 independent operating system processes submitting identical events with varying timestamps.
- **Result**: All processes produced identical semantic hashes (`a3a936801ec8b95d...`) and identical event IDs (`evt_a3a936801ec8b95d`). Multi-process idempotency: **PASSED**.

### 3.3 Database Uniqueness & Transactional Ingestion
- Database schema enforces unique indexes across `remediation_transactions.transaction_id`, `remediation_locks.project_id`, `predictive_datasets.dataset_id`, `predictive_models.model_id`, and `predictive_predictions.prediction_id`.
- Foreign key cascading deletes (`ondelete="CASCADE"`) guarantee referential integrity without orphaned records.

### 3.4 Full Verification Suite Results
- **Backend Unit Tests**: `603 passed in 92.60s` across all 25 backend test suites.
- **Frontend Vitest Suite**: `98 passed in 48.80s` across all 8 test suites.
- **Frontend Production Build**: `tsc --noEmit && vite build` completed in 22.96s with zero errors.

---

## 4. Existing Remediation Component Reuse Matrix

To avoid duplication, Phase 5 directly leverages existing Phase 2D.1 and 2D.2 subsystems:

| Phase 5 Capability | Existing APEX Module | Action / Role in Phase 5 |
|---|---|---|
| **Workflow State Machine** | `patch_lifecycle.py` (`PatchLifecycleManager`) | **Extend**: Expand `PatchLifecycleState` to encompass full orchestration states (`DISCOVERED`, `ROOT_CAUSE_IDENTIFIED`, `PLAN_VALIDATED`, etc.). |
| **Transaction Journaling** | `transaction_engine.py` (`MultiFileTransactionEngine`) | **Reuse As-Is**: Maintain `.apex_backup/transactions/`, pre/post hashing, and journal event stream. |
| **Leases & Fencing** | `repository_lock.py` (`RepositoryLockManager`) | **Reuse As-Is**: Acquire database + file locks with expiration leases and monotonic fencing tokens. |
| **Crash Recovery** | `crash_recovery.py` (`CrashRecoveryEngine`) | **Reuse As-Is**: Automatic rollback or roll-forward of interrupted transactions during orchestrator boot. |
| **Patch Generation** | `patch_generator.py` (`PatchGenerator`) | **Extend**: Add multi-candidate generation and cross-file patch coordination. |
| **Syntax Verification** | `patch_verifier.py` (`PatchVerifier`) | **Reuse As-Is**: AST parsing, token analysis, and diff integrity checking. |
| **Contract Verification** | `semantic_verifier.py` (`SemanticVerifier`) | **Reuse As-Is**: Function signature, scope integrity, and control flow preservation. |
| **Behavioral Testing** | `behavioral_verifier.py` (`BehavioralVerifier`) | **Extend**: Route test execution through the isolated Docker sandbox wrapper. |
| **Post-Apply Verification**| `post_apply_verifier.py` (`PostApplyVerifier`) | **Reuse & Extend**: Re-run affected analyzers and verify finding resolution. |
| **Impact & Test Selection**| `blast_radius.py`, `test_selector.py` | **Reuse As-Is**: Rank candidate verification tests and score blast radius. |
| **Predictive Risk** | `prediction_engine.py`, `baseline_models.py` | **Advisory Integration**: Rule-Based Engineering Risk provides advisory risk classification. |

---

## 5. Phase 5 Autonomous Remediation Architecture

```
                                  +-------------------------------------------------------+
                                  |                 APEX FINDING TRIGGER                  |
                                  |  (Security, Architecture, Dependency, Runtime, etc.)  |
                                  +---------------------------+---------------------------+
                                                              |
                                                              v
+-------------------------------------------------------------------------------------------------------------------------+
|                                              REMEDIATION ORCHESTRATOR                                                   |
|                                                                                                                         |
|  [DISCOVERED] ---> [INVESTIGATING] ---> [ROOT_CAUSE_IDENTIFIED] ---> [PLAN_GENERATED] ---> [PLAN_VALIDATED]              |
|                                                                                                  |                      |
|  [COMPLETED] <--- [POST_ANALYSIS] <--- [APPLIED] <--- [APPLYING] <--- [APPROVED] <--- [AWAITING_APPROVAL] <---+       |
|                                                                                                  |                      |
|                                                                                     [PATCH_VERIFIED]                    |
|                                                                                                  ^                      |
|                                                                                      [PATCH_VALIDATING]                 |
|                                                                                                  ^                      |
|                                                                                      [PATCH_GENERATED]                  |
+-------------------------------------------------------------+------------------------------------+----------------------+
                                                              |                                    |
                    +-----------------------------------------+                                    |
                    v                                                                              v
+---------------------------------------+                              +---------------------------------------+
|        ROOT CAUSE INTELLIGENCE        |                              |       PATCH VERIFICATION ENGINE       |
|                                       |                              |          (Isolated Sandbox)           |
| - Knowledge Graph Dependency Traversal|                              |                                       |
| - Cross-Analyzer Evidence Correlation |                              | 1. Patch Integrity & Syntax AST       |
| - Git Commit & Churn History          |                              | 2. Semantic Function Contract Guard   |
| - Root-Cause Hypothesis Generator     |                              | 3. Static & Security Re-Analysis      |
|   (Confirmed vs Inferred Candidates)  |                              | 4. Targeted Regression Test Execution |
+-------------------+-------------------+                              | 5. Runtime Behavior & Diff Check      |
                    |                                                  +-------------------+-------------------+
                    v                                                                      ^
+---------------------------------------+                                                  |
|      REMEDIATION PLANNING ENGINE      |                                                  |
|                                       |                                                  |
| - Finding Grouping & Conflict Check   |                                                  |
| - Multi-File Modification Blueprint   |                                                  |
| - Rollback Strategy Definition        |                                                  |
| - Risk Classification (LOW - CRITICAL)|                                                  |
+-------------------+-------------------+                                                  |
                    |                                                                      |
                    v                                                                      |
+---------------------------------------+                                                  |
|        PATCH GENERATION ENGINE        |                                                  |
|                                       |                                                  |
| - AST Transformations (Deterministic) |--------------------------------------------------+
| - Multi-Candidate Patch Synthesis     |
| - Source Hash Pre-Condition Guard     |
+-------------------+-------------------+
                    |
                    v (Upon Approval)
+-------------------------------------------------------------------------------------------------------------------------+
|                                           TRANSACTIONAL APPLICATION ENGINE                                              |
|                                                                                                                         |
| 1. Re-verify source hashes  2. Acquire lease & fencing token  3. Stage candidate files  4. Journaled multi-file swap    |
| 5. Post-apply analyzer run  6. Deterministic rollback on conflict  7. Emit verified telemetry to DatasetGrowthPipeline  |
+-------------------------------------------------------------------------------------------------------------------------+
```

---

## 6. Durable Workflow State Machine

The remediation workflow is modeled as a formal, deterministic state machine. Illegal state transitions are rejected with `InvalidStateTransitionError`.

```
                    +------------------+
                    |    DISCOVERED    |
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |  INVESTIGATING   |
                    +--------+---------+
                             |
                             v
                    +------------------------+
                    | ROOT_CAUSE_IDENTIFIED  |
                    +--------+---------------+
                             |
                             v
                    +------------------+
                    |  PLAN_GENERATED  |
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |  PLAN_VALIDATED  |
                    +--------+---------+
                             |
                             v
                    +------------------+
                    | PATCH_GENERATED  |
                    +--------+---------+
                             |
                             v
                    +-------------------+
                    | PATCH_VALIDATING  |
                    +--------+----------+
                             |
            +----------------+----------------+
            |                                 |
            v                                 v
   +------------------+             +--------------------+
   |  PATCH_VERIFIED  |             | VERIFICATION_FAILED|
   +--------+---------+             +---------+----------+
            |                                 |
            v                                 |
  +-------------------+                       |
  | AWAITING_APPROVAL |                       |
  +----+----------+---+                       |
       |          |                           |
       |          +--------------------+      |
       v                               v      v
  +----------+                   +--------------------+
  | APPROVED |                   |      REJECTED      |
  +----+-----+                   +--------------------+
       |
       v
  +----------+
  | APPLYING |
  +----+-----+
       |
       +-----------------------+
       |                       |
       v                       v
  +---------+         +------------------+
  | APPLIED |         | ROLLBACK_PENDING |
  +----+----+         +--------+---------+
       |                       |
       v                       v
+---------------+     +------------------+
| POST_ANALYSIS |     |   ROLLED_BACK    |
+------+--------+     +--------+---------+
       |                       |
       +-----------+           |
       |           |           |
       v           v           v
+-----------+  +-------------------------------+
| COMPLETED |  |   NEEDS_HUMAN_INTERVENTION    |
+-----------+  +-------------------------------+
```

### 6.1 Legal State Transitions

```python
VALID_REMEDIATION_TRANSITIONS = {
    "DISCOVERED": {"INVESTIGATING", "REJECTED"},
    "INVESTIGATING": {"ROOT_CAUSE_IDENTIFIED", "FAILED", "NEEDS_HUMAN_INTERVENTION"},
    "ROOT_CAUSE_IDENTIFIED": {"PLAN_GENERATED", "FAILED", "NEEDS_HUMAN_INTERVENTION"},
    "PLAN_GENERATED": {"PLAN_VALIDATED", "REJECTED", "FAILED"},
    "PLAN_VALIDATED": {"PATCH_GENERATED", "FAILED", "REJECTED"},
    "PATCH_GENERATED": {"PATCH_VALIDATING", "FAILED"},
    "PATCH_VALIDATING": {"PATCH_VERIFIED", "VERIFICATION_FAILED", "FAILED"},
    "PATCH_VERIFIED": {"AWAITING_APPROVAL", "APPROVED"},  # LOW risk may transition directly if policy permits
    "AWAITING_APPROVAL": {"APPROVED", "REJECTED"},
    "APPROVED": {"APPLYING", "REJECTED"},
    "APPLYING": {"APPLIED", "ROLLBACK_PENDING", "FAILED"},
    "APPLIED": {"POST_ANALYSIS", "ROLLBACK_PENDING"},
    "POST_ANALYSIS": {"COMPLETED", "ROLLBACK_PENDING", "NEEDS_HUMAN_INTERVENTION"},
    "ROLLBACK_PENDING": {"ROLLED_BACK", "NEEDS_HUMAN_INTERVENTION"},
    "ROLLED_BACK": {"COMPLETED", "FAILED", "NEEDS_HUMAN_INTERVENTION"},
    "VERIFICATION_FAILED": {"REJECTED", "INVESTIGATING", "NEEDS_HUMAN_INTERVENTION"},
    "FAILED": {"NEEDS_HUMAN_INTERVENTION"},
    "REJECTED": set(),  # Terminal
    "COMPLETED": set(),  # Terminal
    "NEEDS_HUMAN_INTERVENTION": {"INVESTIGATING", "ROLLBACK_PENDING", "REJECTED"},
}
```

### 6.2 Crash Recovery & Timeout Handling
- **Heartbeat & Lease Timeout**: Every active orchestration job maintains a `lease_expires_at` (default 5 minutes). If the orchestrator process crashes, a background sweeper identifies orphaned jobs with expired leases.
- **Recovery Policy**:
  - If state is `APPLYING`: Trigger `CrashRecoveryEngine` to inspect the transaction journal. If staging completed, rollback files to `pre_hash` state and transition to `ROLLED_BACK`.
  - If state is `PATCH_VALIDATING`: Terminate orphan Docker container, purge temp workspace, set state to `FAILED`.
  - If state is `INVESTIGATING` or `PLAN_GENERATED`: Reset to `DISCOVERED` with incremented retry count (max 3 retries).

---

## 7. Database & Persistence Design

New relational entities integrate directly with existing models in `backend/app/models/entities.py`:

```
               +--------------------+
               |  ReviewedProject   |
               +---------+----------+
                         | 1
                         |
                         | *
            +------------+------------+
            |  RemediationWorkflow    |
            |                         |
            | id: PK                  |
            | workflow_id: String(80) |
            | state: String(50)       |
            | risk_level: String(20)  |
            +------------+------------+
                         |
         +---------------+---------------+
         | 1                           1 |
         | *                           | *
+--------+-----------+       +---------+----------+
|  RemediationPlan   |       | RemediationCandidate|
|                    |       |                    |
| id: PK             |       | id: PK             |
| plan_id: String(80)|       | patch_id: String   |
| target_findings    |       | diff_unified: Text |
| root_cause_json    |       | original_hashes    |
+--------------------+       +---------+----------+
                                       | 1
                                       |
                                       | *
                             +---------+----------+
                             | VerificationReport |
                             |                    |
                             | id: PK             |
                             | status: String(50) |
                             | stage_results_json |
                             | regressions_found  |
                             +--------------------+
```

### 7.1 Entity Definitions (SQLAlchemy 2.0 Mapped)

```python
class RemediationWorkflowRecord(Base):
    __tablename__ = "remediation_workflows"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("reviewed_projects.id", ondelete="CASCADE"), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    target_finding_id: Mapped[int] = mapped_column(ForeignKey("project_findings.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="DISCOVERED")
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    approval_policy: Mapped[str] = mapped_column(String(50), nullable=False, default="REQUIRE_HUMAN")
    root_cause_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    active_plan_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active_patch_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_history: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    
    project: Mapped[ReviewedProject] = relationship()
    finding: Mapped[ProjectFinding] = relationship()
    plans: Mapped[list["RemediationPlanRecord"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    candidates: Mapped[list["RemediationCandidateRecord"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")


class RemediationPlanRecord(Base):
    __tablename__ = "remediation_plans"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("remediation_workflows.workflow_id", ondelete="CASCADE"), index=True, nullable=False)
    target_findings: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    affected_files: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    root_cause_reference: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    proposed_changes_summary: Mapped[str] = mapped_column(Text, nullable=False)
    regression_risks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    required_tests: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    rollback_strategy: Mapped[str] = mapped_column(String(100), nullable=False, default="MULTI_FILE_JOURNAL_RESTORE")
    risk_assessment: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    
    workflow: Mapped[RemediationWorkflowRecord] = relationship(back_populates="plans")


class RemediationCandidateRecord(Base):
    __tablename__ = "remediation_candidates"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    patch_id: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("remediation_workflows.workflow_id", ondelete="CASCADE"), index=True, nullable=False)
    plan_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)  # AST_TRANSFORM, CONTEXT_AWARE, DEPENDENCY_PIN
    diff_unified: Mapped[str] = mapped_column(Text, nullable=False)
    files_manifest: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {path: {pre_hash, post_hash}}
    verification_status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    verification_results: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    
    workflow: Mapped[RemediationWorkflowRecord] = relationship(back_populates="candidates")
```

---

## 8. Root Cause Intelligence Architecture

The Root Cause Intelligence Engine correlates multi-analyzer findings across the Knowledge Graph:

### 8.1 Evidence Correlation Sources
1. **Knowledge Graph Reachability**: Finds caller chains and dependency paths from the finding's AST node to upstream inputs.
2. **Finding Triangulation**: Correlates static security alerts with runtime trace exceptions (e.g., static SQL injection finding matched with dynamic SQLite operational error).
3. **Historical Churn & Transitions**: Checks if the affected component was touched in recent commits with high change failure risk.
4. **Configuration & Dependency Linkage**: Links library vulnerability findings directly to `requirements.txt` / `package.json` AST entries.

### 8.2 Hypothesis Data Contract
```python
@dataclass
class RootCauseHypothesis:
    hypothesis_id: str
    target_finding_id: int
    classification: str  # CONFIRMED vs INFERRED
    primary_root_cause: str
    confidence_score: float  # 0.0 to 1.0 (Calibrated)
    supporting_evidence: list[dict[str, Any]]
    contradictory_evidence: list[dict[str, Any]]
    affected_components: list[str]
    graph_reachability_paths: list[list[str]]
    alternative_explanations: list[str]
    uncertainty_reasons: list[str]
```

---

## 9. Layered Sandbox & Execution Safety Engineering

### 9.1 Threat Model for Untrusted Repository Execution

| Threat Vector | Attack Scenario | Prevention & Mitigation Architecture |
|---|---|---|
| **Malicious Test Scripts** | Hostile repo tests executing `os.system("rm -rf /")` or stealing `.env` | Run in non-root Docker sandbox with read-only host mount and dropped Linux capabilities. |
| **Network Exfiltration** | Generated patch or test sending tokens to external command-and-control | `--network none` flag enforced on container execution. Complete network isolation. |
| **Filesystem Escape** | Patch attempting directory traversal (`../../etc/passwd`) | Strict path resolution checking: `abs_target.resolve().is_relative_to(repo_root)`. |
| **Fork Bomb / CPU Denial** | Test script spawning unbounded threads or infinite while loop | `pids-limit=100`, `cpus="1.0"`, `memory="1g"`, strict execution timeout (default 30s). |
| **Docker Socket Abuse** | Mounting `/var/run/docker.sock` allowing container escape | No docker socket or host system paths mounted into sandbox. |
| **Credential Bleed** | Container inspecting host environment variables (`AWS_SECRET_ACCESS_KEY`) | Minimal whitelist environment: `PATH`, `PYTHONPATH`, `PYTHONDONTWRITEBYTECODE=1`. |

### 9.2 Layered Verification Pipeline (12 Stages)

```
[1. Integrity] ----> [2. Syntax AST] ---> [3. Function Contracts] ---> [4. Static Analyzers]
                                                                                |
[8. Incompatibilities] <--- [7. Regressions] <--- [6. Target Tests] <--- [5. Security Check]
         |
         v
[9. Runtime Trace] -> [10. Perf Bounds] -> [11. Diff Inspection] ---> [12. Verified State]
```

1. **Patch Integrity**: SHA-256 validation of target file pre-hashes; verifies patch applies cleanly without fuzz.
2. **Syntax Validation**: `ast.parse` validates valid Python syntax across all modified files.
3. **Function Contract Validation**: `SemanticVerifier` confirms parameters, return types, and class interfaces remain intact.
4. **Static Analyzer Comparison**: Re-runs 10 analyzers to ensure finding severity decreases and no new code smells appear.
5. **Security Analyzer Guard**: Re-runs AST security scanner; fails immediately if new CWE patterns are detected.
6. **Targeted Test Execution**: Runs targeted test selector tests in the isolated container.
7. **Regression Detection**: `BehavioralVerifier` verifies that 100% of previously passing tests continue to pass.
8. **Dependency Compatibility**: Verifies package resolution without version conflicts.
9. **Runtime Behavior Comparison**: Compares execution trace of patched component against baseline trace.
10. **Performance Bounds**: Checks execution time and memory bounds ($\le 120\%$ of baseline).
11. **Diff Inspection**: Enforces maximum diff size limits and blocks changes to protected files (`.apex_backup`, migrations).
12. **Outcome Classification**: Assigns explicit vocabulary: `VERIFIED`, `PARTIALLY_VERIFIED`, `VERIFICATION_FAILED`, `VERIFICATION_INCOMPLETE`, `UNSUPPORTED`, `NEEDS_HUMAN_REVIEW`.

---

## 10. Risk-Based Approval Governance Matrix

Every remediation plan receives a formal risk classification. MISTIQ predictions are strictly advisory; they can **elevate** risk, but **never lower or bypass** mandatory authorization.

| Risk Level | Trigger Criteria | Verification Requirements | Approval Policy |
|---|---|---|---|
| **LOW** | Single-file change, non-security, low blast radius ($< 0.15$), $\ge 3$ relevant unit tests pass. | All 12 verification stages pass with 100% test success. | **Eligible for Autonomous Application** only after policy gate sign-off. |
| **MEDIUM** | Multi-file ($\le 3$), API or database touch, moderate blast radius ($0.15 - 0.40$). | All 12 verification stages pass + contract preservation. | **Mandatory Human Approval** during Phase 5 rollout. |
| **HIGH** | Blast radius $> 0.40$, core architecture module, dependency upgrade, or multiple affected findings. | Full verification + full test suite execution. | **Explicit Human Approval Required**. |
| **CRITICAL** | Auth/authz touch, crypto, secret handling, permissions, destructive DB operations. | Full verification + security re-audit. | **Explicit Dual Human Authorization Required**. Never autonomous. |

### Mandatory Human Approval Policy
The following actions **always** require explicit human approval, regardless of ML confidence:
1. Modifications to `app/core/security.py`, `app/api/deps.py`, or password hashing routines.
2. Deletion or renaming of database tables, columns, or migration files.
3. Network listener or CORS configuration alterations.
4. Dependency major version upgrades.
5. Changes where root-cause confidence $< 0.80$.

---

## 11. Transaction Integration Design (Phase 2D.1/2D.2 Reuse)

Patch application utilizes `MultiFileTransactionEngine` and `RepositoryLockManager` with zero architectural duplication:

```
[Acquire Lease] ---> [Verify Pre-Hashes] ---> [Stage Replacements] ---> [Atomic File Swap]
       |                      |                       |                       |
       v (Failure)            v (Mismatch)            v (Write error)         v (Conflict)
[Abort & Release]      [Reject: STALE_SRC]     [Purge Staging & Abort] [Journal Rollback]
```

### Application Sequence:
1. **Acquire Lease**: `RepositoryLockManager.acquire_lock(project_id, transaction_id, timeout=60)` ensures exclusive write access and generates monotonic fencing token.
2. **Verify Pre-Hashes**: `MultiFileTransactionEngine` inspects current disk contents. If any file SHA-256 differs from `pre_hash`, transaction aborts with `STALE_SOURCE_ERROR`.
3. **Stage Candidate Files**: Writes candidate contents into `.apex_backup/transactions/<txn_id>/staged/`.
4. **Journal Event**: Appends `STAGED` record to `journal.json`.
5. **Atomic Multi-File Swap**: Replaces original files with staged files while backing up originals to `.apex_backup/transactions/<txn_id>/backups/`.
6. **Verify Resulting Hashes**: Confirms applied file contents match `post_hash`.
7. **Release Lock**: Renews or releases the repository lock lease.
8. **Crash Rollback Recovery**: If power fails or the process terminates during step 5, `CrashRecoveryEngine` detects incomplete transaction state on startup and restores backups using the journal.

---

## 12. Frontend Experience: Dedicated Autonomous Remediation Workspace

A unified engineering workspace is added to the frontend navigation alongside Project Review:

```
+--------------------------------------------------------------------------------------------------------+
| APEX 2.0  |  Project Review  |  Knowledge Graph  |  Failure Intelligence  |  *Autonomous Remediation*  |
+--------------------------------------------------------------------------------------------------------+
|                                                                                                        |
|  [ REMEDIATION WORKFLOWS ]                       [ ACTIVE WORKFLOW: WF-2026-0042 ]                    |
|  +-----------------------------------------+     +---------------------------------------------------+ |
|  | WF-0042: SQL Injection in auth_api.py   |     | Target: ProjectFinding #184 (HIGH - CWE-89)       | |
|  | State: AWAITING_APPROVAL | Risk: CRITICAL|     | Root Cause: Unsanitized raw f-string query in DB  | |
|  +-----------------------------------------+     | Status: PATCH_VERIFIED (12/12 stages passed)      | |
|  | WF-0041: N+1 Query in review_routes.py  |     +---------------------------------------------------+ |
|  | State: COMPLETED | Applied: 14m ago     |                                                           |
|  +-----------------------------------------+     [ TABS: Plan | Unified Diff | Verification | Audit ] |
|  | WF-0040: Unhandled Exception in parser  |     +---------------------------------------------------+ |
|  | State: INVESTIGATING                    |     | Unified Diff:                                     | |
|  +-----------------------------------------+     | -  cursor.execute(f"SELECT * FROM users WHERE...")| |
|                                                  | +  cursor.execute("SELECT * FROM users WHERE...", | |
|                                                  | +                 (user_param,))                  | |
|                                                  |                                                   | |
|                                                  | Verification Results:                             | |
|                                                  | [x] AST Syntax Valid   [x] Security CWE Eliminated| |
|                                                  | [x] Tests: 4 Passed, 0 Regressions                | |
|                                                  |                                                   | |
|                                                  | [ REJECT PATCH ]          [ APPROVE & APPLY ]     | |
|                                                  +---------------------------------------------------+ |
+--------------------------------------------------------------------------------------------------------+
```

### 10 Dedicated Views:
1. **Remediation Dashboard**: High-level workflow throughput, active remediations, success rates, and rollback metrics.
2. **Finding Investigation**: Detailed finding context, AST position, and dynamic execution evidence.
3. **Root Cause Explorer**: Interactive Knowledge Graph visualization highlighting candidate root causes.
4. **Remediation Plan**: Multi-file blueprint, regression risks, and required tests.
5. **Patch Comparison**: Side-by-side syntax-highlighted unified diff with affected symbol annotations.
6. **Verification Results**: Layer-by-layer breakdown of the 12 verification stages.
7. **Approval Queue**: Dedicated triage interface for pending human authorizations with risk badges.
8. **Transaction History**: Audit timeline of journaled file swaps and verification outcomes.
9. **Rollback & Recovery**: Emergency single-click rollback button and manual conflict reconciliation tools.
10. **Remediation Intelligence**: Real-time telemetry feed tracking learned remediation success rates.

---

## 13. API Contract Specifications

### 13.1 Workflow Lifecycle Endpoints

```
POST   /api/projects/{project_id}/remediation/workflows
       Body: { "finding_id": 184, "auto_investigate": true }
       Response: 201 Created -> RemediationWorkflowResponse

GET    /api/projects/{project_id}/remediation/workflows
       Response: 200 OK -> list[RemediationWorkflowSummary]

GET    /api/projects/{project_id}/remediation/workflows/{workflow_id}
       Response: 200 OK -> RemediationWorkflowDetailResponse

POST   /api/projects/{project_id}/remediation/workflows/{workflow_id}/investigate
       Response: 200 OK -> RootCauseHypothesisResponse

POST   /api/projects/{project_id}/remediation/workflows/{workflow_id}/plan
       Body: { "root_cause_id": "rc_01" }
       Response: 200 OK -> RemediationPlanResponse

POST   /api/projects/{project_id}/remediation/workflows/{workflow_id}/generate-patch
       Body: { "plan_id": "plan_01", "strategy": "AST_TRANSFORM" }
       Response: 200 OK -> RemediationCandidateResponse

POST   /api/projects/{project_id}/remediation/workflows/{workflow_id}/verify
       Body: { "patch_id": "patch_01" }
       Response: 200 OK -> VerificationReportResponse

POST   /api/projects/{project_id}/remediation/workflows/{workflow_id}/approve
       Body: { "patch_id": "patch_01", "rationale": "Verified safe by security team" }
       Response: 200 OK -> WorkflowStateResponse

POST   /api/projects/{project_id}/remediation/workflows/{workflow_id}/apply
       Body: { "patch_id": "patch_01" }
       Response: 200 OK -> TransactionApplicationResponse

POST   /api/projects/{project_id}/remediation/workflows/{workflow_id}/rollback
       Body: { "transaction_id": "txn_01", "reason": "Post-analysis regression" }
       Response: 200 OK -> RollbackResponse
```

---

## 14. Failure Injection & Recovery Testing Strategy

Phase 5 includes an exhaustive test matrix covering 19 failure scenarios:

1. **Process Crash During Generation**: Simulates SIGKILL during patch creation; verifies state resets cleanly or marks as failed without orphaned files.
2. **Process Crash During Application**: Simulates crash after staging but before swap completion; verifies `CrashRecoveryEngine` restores files to `pre_hash`.
3. **Process Crash During Rollback**: Verifies journal replay recovers from mid-rollback interruptions.
4. **Concurrent Remediation Requests**: Verifies second writer is blocked by `RepositoryLockManager` with `LockAcquisitionError`.
5. **Stale Source Hashes**: Modifies file on disk after patch generation; verifies application is rejected with `STALE_SOURCE_ERROR`.
6. **Developer Edits During Staging**: Protects manual developer edits from silent overwrite.
7. **Malicious Generated Patches**: Tests patch attempting directory traversal (`../`); verifies sandbox blocks file access.
8. **Malicious Repository Scripts**: Verifies test runner cannot access host environment or network.
9. **Docker Sandbox Unavailable**: Verifies system fails closed rather than executing untrusted code on host.
10. **Sandbox Timeout**: Simulates infinite loop in candidate code; verifies timeout kills container at 30s.
11. **Test Execution Regressions**: Injects broken test; verifies patch transitions to `VERIFICATION_FAILED`.
12. **Database Outage**: Verifies journal file on disk preserves transaction integrity when DB disconnects.
13. **Transaction Journal Corruption**: Verifies detection of corrupted journal with safe transition to `MANUAL_RECONCILIATION_REQUIRED`.
14. **Expired Lease Handling**: Verifies stale writer is fenced out when lease expires.
15. **Stale Fencing Tokens**: Verifies rejection of write commands carrying outdated token numbers.
16. **Unauthorized Approval Attempt**: Verifies non-admin / non-owner user cannot approve CRITICAL changes.
17. **Cross-Tenant Access Rejection**: Verifies user from Tenant A cannot view or manipulate workflows for Tenant B.
18. **Duplicate Remediation Requests**: Verifies idempotency deduplication on workflow creation.
19. **Post-Application Regression**: Simulates post-apply analyzer failure; triggers automatic rollback to baseline.

---

## 15. Implementation Roadmap (Phases 5.0 – 5.7)

```
[Phase 5.0] Architecture, Safety Blueprint & Phase 4 Closeout (CURRENT)
    |
    v
[Phase 5.1] Remediation Orchestrator Core (Workflow state machine, DB models, APIs)
    |
    v
[Phase 5.2] Root Cause Intelligence & Planning Engine (KG integration, hypothesis synthesis)
    |
    v
[Phase 5.3] Patch Generation & Layered Sandbox Verification (AST transforms, Docker isolation)
    |
    v
[Phase 5.4] Approval Governance & Transactional Application (Lease fencing, journaled swap)
    |
    v
[Phase 5.5] Post-Remediation Learning & Telemetry Ingestion (DatasetGrowthPipeline linkage)
    |
    v
[Phase 5.6] Frontend Workspace & End-to-End User Experience (React views, real-time SSE)
    |
    v
[Phase 5.7] Autonomous Safety Acceptance & Adversarial Hardening (19 failure injection tests)
```

---

## 16. Identified Architectural Risks & Open Questions

1. **Docker Availability Across Environments**: In minimal developer environments or CI runners without Docker-in-Docker, containerized sandboxing may be unavailable.  
   *Mitigation*: Implement a strict, pluggable sandbox provider interface (`DockerSandboxProvider` vs `RestrictedProcessSandboxProvider`). Default to Docker in production; fail-closed if required sandbox level is not met.
2. **Multi-Finding Patch Coupling**: Fixing one architectural cycle may require changing files tied to a separate security finding.  
   *Mitigation*: The Planning Engine must perform transitive closure grouping to ensure dependent findings are planned and applied in a single transactional manifest.
3. **Observation Window for Remediation Outcomes**: Learning whether a remediation truly resolved a bug without regressions requires observing repository activity for up to 30 days.  
   *Mitigation*: Telemetry records emitted upon patch application remain in `PENDING_VERIFICATION` state until the 30-day maturity window closes without defect recurrence, strictly adhering to the Phase 4.2.1 data governance standard.

---

## 17. Target Repository Files for Phase 5.1 Implementation

The following files are designated for modification and creation in Phase 5.1:

### New Backend Modules:
1. `backend/app/services/remediation/orchestrator.py`: Central workflow state machine, job scheduling, and failure recovery.
2. `backend/app/models/remediation_models.py` (or additions to `entities.py`): `RemediationWorkflowRecord`, `RemediationPlanRecord`, `RemediationCandidateRecord`.
3. `backend/app/api/routes/remediation_routes.py`: RESTful endpoints for workflow creation, status inspection, approval, and application.

### Existing Modules to Extend:
1. `backend/app/models/entities.py`: Add workflow foreign keys and relationships to `ReviewedProject` and `ProjectFinding`.
2. `backend/app/main.py`: Register `/api/remediation` router.
3. `backend/app/services/remediation/patch_lifecycle.py`: Align existing `PatchLifecycleState` with `RemediationWorkflowState`.
4. `tests/unit/test_phase5_1_orchestrator.py`: Unit tests validating state transitions, illegal state rejections, and crash recovery.

