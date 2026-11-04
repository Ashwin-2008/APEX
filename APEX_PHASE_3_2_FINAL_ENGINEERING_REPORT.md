# APEX 2.0 — PHASE 3.2 FINAL ENGINEERING REPORT
## Graph Reliability, Benchmark Validation & Cross-Technology Relationship Intelligence

**Date:** November 4, 2026  
**Status:** COMPLETE & VERIFIED  
**Repository:** APEX 2.0 Autonomous Project Engineering Intelligence Platform  
**Authors:** Senior Principal Software Architect, Static Analysis Researcher & Graph Systems Engineer  

---

## 1. Executive Summary

Phase 3.2 solidifies the **Engineering Knowledge Graph** from an exploratory architectural map into a high-trust, calibrated repository intelligence system capable of driving autonomous engineering decisions. While Phase 3 and Phase 3.1 established persistent relational storage, multi-hop impact analysis, and foundational heuristics, Phase 3.2 directly addresses the rigorous reliability, empirical accuracy, cross-technology understanding, and transaction safety requirements necessary for production-grade autonomous remediation and impact forecasting.

Every subsystem within the Knowledge Graph stack was inspected, fortified, and validated against dedicated empirical benchmarks:
- **Canonical Identity Continuity:** Multi-signal mathematical scoring replacing naive name matching; explicit tracking of `SPLIT`, `MERGED`, `RENAMED_AND_MODIFIED`, and `AMBIGUOUS` entities; candidate match preservation; and standardized ground-truth benchmark metrics ($Precision$, $Recall$, $F_1$, and Ambiguity Rate).
- **Call Graph Accuracy & Calibration:** Multi-tiered call taxonomy (`RESOLVED_STATIC`, `RESOLVED_RUNTIME`, `AMBIGUOUS_POLYMORPHIC`, `UNRESOLVED_DYNAMIC`); deep resolution across relative imports, type annotations, inheritance hierarchies, and dynamic `getattr` reflection; empirical calibration scoring including Brier score, Expected Calibration Error (ECE), and sample-size validity gates.
- **Transactional Graph Update Reliability:** Strict staging isolation, optimistic multi-process concurrency leases with timeout reclamation, orphan entity purging upon rollback, automatic startup recovery from ungraceful process termination, and pre-activation graph invariant checks.
- **Calibrated Blast Radius Assessment:** Clear segregation between empirically measured graph metrics and heuristic amplification factors; explicit flagging of unavailable evidence categories; and benchmark validation assessing Precision@High, Recall@High, False-High rate, False-Low rate, and Spearman rank order stability.
- **Targeted Test Selection Validation:** Strict 6-tier classification (`DIRECT_TEST`, `RUNTIME_CONFIRMED_TEST`, `STATICALLY_INFERRED_TEST`, `INTEGRATION_TEST`, `END_TO_END_TEST`, `POTENTIALLY_RELEVANT`); enforcement of the invariant that test selectors never fabricate execution outcomes (`NOT_EXECUTED`); and empirical metrics including $Precision@K$, $Recall@K$, Unnecessary Recommendation Rate, and Relevant Test Coverage.
- **Cross-Technology Relationship Intelligence:** Deep repository parsing linking React client API calls (`CALLS_API`) $\to$ FastAPI route handlers $\to$ business services $\to$ SQLAlchemy models (`QUERIES_MODEL`) $\to$ relational tables (`MAPS_TO_TABLE`), Docker multi-stage builds (`DOCKER_STAGE`, `EXECUTES_ENTRYPOINT`), GitHub Actions CI workflows (`CI_WORKFLOW`, `RUNS_WORKFLOW_TEST`), and runtime configuration (`CONSUMES_ENV_VAR`).
- **Honest Multi-Dimensional Coverage Reporting:** Deprecation of misleading aggregate percentages in favor of 5 independently measured coverage dimensions with bounded statuses (`COMPREHENSIVE`, `PARTIAL`, `MINIMAL`, `UNSUPPORTED`) and explicit gap disclosures.
- **Full-Stack UI & Verification:** Full React exploration cockpit featuring dimensional coverage meters, cross-technology trace navigation, ambiguous candidate match inspectors, and concurrency lock indicators, backed by 64/64 passing Phase 3.2 tests and full regression parity.

---

## 2. Comprehensive Implementation Details

### 2.1 Multi-Signal Canonical Identity Continuity (`identity_continuity.py`)
Code entities evolve across refactorings through renames, extractions, combinations, and moves. Phase 3.2 implements a 7-signal normalized scoring model:

$$\text{Score}(u, v) = w_{\text{type}} + w_{\text{git}} + w_{\text{file}} + w_{\text{ast}} + w_{\text{sig}} + w_{\text{name}} + w_{\text{context}}$$

1. **Entity Type Gate:** Strict requirement (`NodeType` must match). Returns 0.0 on mismatch.
2. **Git Rename Confirmation ($+0.25$):** Real-time git tree diffing detecting explicit file renames/moves.
3. **File Path Context ($+0.30$):** High proximity weight when old and new symbols reside in the same file.
4. **Structural Fingerprint ($+0.50$):** Canonicalized AST body hash invariant to identifier renames and formatting changes.
5. **Qualified Signature ($+0.20$):** Parameter name and count alignment across function/method declarations.
6. **Name Similarity ($0.20 \text{ to } 0.40$):** Levenshtein/Gestalt pattern matching detecting minor renames and prefix/suffix additions.
7. **Sibling / Enclosure Context ($+0.15$):** Jaccard similarity ($\ge 0.50$) of neighboring methods or functions in the same module/class.

```
       [Unmatched Old Nodes]           [Unmatched New Nodes]
                 \                              /
                  \                            /
              [Multi-Signal Scoring: Weights 0.0 - 1.0]
                              |
               +--------------+--------------+
               |                             |
      Score >= 0.55                 Near-Equal Top Scores
               |                             |
   [Single Confident Match]        [AMBIGUOUS Match Record]
   - RENAMED_SYMBOL                - candidate_canonical_ids: [c1, c2, c3]
   - RENAMED_AND_MODIFIED          - confidence: top_score
   - MOVED                         - runner_up_score: cand[1].score
```

- **Function Splitting:** Identifies when one monolithic function is decomposed into 2 or more sub-functions within the same file, linking the original canonical ID to the set of sub-components via `candidate_canonical_ids`.
- **Function Merging:** Detects when 2 or more related helper functions are consolidated into a single unified routine, preserving provenance to all source IDs.
- **Empirical Continuity Benchmark:** `IdentityContinuityBenchmark.evaluate_benchmark` measures performance against labeled ground-truth refactoring fixture cases, outputting:
  - $Precision = \frac{TP}{TP + FP}$
  - $Recall = \frac{TP}{TP + FN}$
  - $F_1 = \frac{2 \cdot P \cdot R}{P + R}$
  - $\text{Ambiguity Rate} = \frac{\text{Ambiguous Matches}}{\text{Total Cases}}$

### 2.2 Call Graph Accuracy & Empirical Calibration (`call_resolver.py`)
To prevent overconfident edge attribution, Phase 3.2 introduces a 4-tier call taxonomy:
- `RESOLVED_STATIC`: Definitively resolved via static AST import alias resolution, module-local functions, self/cls instance methods, constructor instantiation, or type-annotated method dispatch.
- `RESOLVED_RUNTIME`: Confirmed via dynamic test execution traces and JUnit telemetry.
- `AMBIGUOUS_POLYMORPHIC`: Multiple candidate call targets identified across class inheritance trees or interface implementations without disambiguating runtime traces.
- `UNRESOLVED_DYNAMIC`: Dynamic dispatch via `getattr`, reflection, dictionary lookup, or un-typed external callbacks. Retains expression string and caller provenance for subsequent dynamic refinement.

**Empirical Calibration Engine:**
`CallResolverBenchmark.evaluate_benchmark` validates edge confidence scores against empirical verification fixtures:
- **Confusion Matrix:** True Positive, False Positive, True Negative, False Negative, and Unresolved counts.
- **Brier Score:** Mean squared error between predicted probability $p_i$ and binary outcome $o_i \in \{0, 1\}$:
  $$\text{Brier} = \frac{1}{N} \sum_{i=1}^N (p_i - o_i)^2$$
- **Expected Calibration Error (ECE):** Partitioning predictions into $M=10$ confidence bins and weighting bin calibration errors:
  $$\text{ECE} = \sum_{m=1}^M \frac{|B_m|}{N} \left| \text{acc}(B_m) - \text{conf}(B_m) \right|$$
- **Sample-Size Validity Gate:** Flags evaluation as invalid if $N < 10$, protecting against premature calibration claims on unrepresentative fixture sizes.

### 2.3 Transactional Graph Update Reliability (`transactional_updater.py`)
Graph updates occur concurrently with development activity. To ensure database consistency and crash resiliency:
1. **Staged Version Creation:** Updates always write to a temporary version record (`status = "STAGED"`, `is_current = False`).
2. **Concurrency Lease:** Optimistic locking via `EngineeringGraphUpdateJournal` with `STAGING_LOCK_TIMEOUT_SECONDS = 60`. If another updater holds an active unexpired staging lease, subsequent updates reject or queue safely.
3. **Graph Invariant Consistency Check:** Pre-activation validation ensures:
   - Zero duplicate canonical IDs within a version.
   - Zero corrupted nodes (empty canonical IDs or missing entity types).
   - Zero dangling edges pointing to nonexistent internal entities.
4. **Atomic Activation:** Within a single database transaction, existing current versions are updated to `status = "SUPERSEDED"`, `is_current = False`, and the staged version is set to `status = "ACTIVE"`, `is_current = True`.
5. **Subprocess Crash Recovery:** `TransactionalGraphUpdater.recover_interrupted_updates(db, project_id)` automatically runs on startup or updater initialization. It detects abandoned `STAGED` versions with expired leases, purges orphaned nodes, edges, and transitions, records an audit log in the journal, and restores the active graph state.
6. **Unique Canonical Constraint:** Database constraint `uq_graph_nodes_version_canonical` on `(version_id, canonical_id)` prevents accidental duplication at the storage level.

### 2.4 Calibrated Blast Radius Assessment (`blast_radius.py`)
Blast radius scoring now explicitly distinguishes between verified graph topology and heuristic risk inflation:
- **Measured Structural Properties:** Direct symbols changed, transitive downstream call dependencies, module spread, API boundary crossings, database table touches, and attached test suite count.
- **Heuristic Amplifiers:** Isolated in `heuristic_factors` metadata (e.g., authentication sensitivity, payment gateway keywords, high cyclomatic complexity, zero test coverage penalty).
- **Unavailable Evidence Categorization:** Explicit list in `unavailable_evidence` enumerating absent data sources (e.g., `["RUNTIME_TRACES", "DEPLOYMENT_DEPENDENCIES"]`), preventing false precision.
- **Calibration Benchmark (`BlastRadiusBenchmark`):** Evaluates risk prediction accuracy against labeled impact fixtures:
  - $Precision@High$: Proportion of predicted HIGH/CRITICAL changes that were truly high-risk.
  - $Recall@High$: Proportion of true high-risk changes identified as HIGH/CRITICAL.
  - False-High and False-Low rates.
  - Spearman rank order correlation ($\rho$) measuring rank stability across successive repository runs.

### 2.5 Targeted Test Selection Validation (`test_selector.py`)
Phase 3.2 enforces strict evidence-backed test recommendation:
- **Six-Tier Hierarchy:**
  1. `DIRECT_TEST`: Test function or file directly imports or targets the modified symbol.
  2. `RUNTIME_CONFIRMED_TEST`: Dynamic trace confirms test executes the modified code path.
  3. `STATICALLY_INFERRED_TEST`: Statically reachable within 2 hops along call/import paths.
  4. `INTEGRATION_TEST`: Multi-module or database integration tests referencing affected models or routes.
  5. `END_TO_END_TEST`: High-level test suites exercising API endpoints or frontend flows.
  6. `POTENTIALLY_RELEVANT`: Broad heuristic match (e.g. module namespace overlap).
- **Strict Execution Status:** All recommended tests report `execution_status = "NOT_EXECUTED"`. APEX test selection never fabricates pass/fail states without actual test runner execution.
- **Test Selection Benchmark:** Evaluates recommendations against ground truth via Precision@K ($K \in \{1, 3, 5\}$), Recall@K, Unnecessary Recommendation Rate, and Relevant Test Coverage.

### 2.6 Cross-Technology Relationship Intelligence (`extractor.py`)
Modern applications span multiple languages and runtime boundaries. Phase 3.2 links these tiers into an unbroken graph:
- **React $\to$ Backend API (`CALLS_API`):** Regex and AST extraction of `axios.get`, `axios.post`, `fetch('/api/v1/...')` calls in `.ts`, `.tsx`, `.js`, `.jsx` files, connecting them to FastAPI route endpoint nodes.
- **FastAPI Route $\to$ Service Layer (`CALLS`):** Function calls from HTTP route handlers to business logic functions.
- **Service Layer $\to$ ORM Model (`QUERIES_MODEL`):** Instantiations or method invocations on SQLAlchemy models (`UserModel()`, `db.query(UserModel)`).
- **ORM Model $\to$ Database Table (`MAPS_TO_TABLE`):** Extraction of `__tablename__ = "users"` attributes, connecting model classes to `DATABASE_TABLE` nodes.
- **Docker Multi-Stage Builds (`DOCKER_STAGE`, `EXECUTES_ENTRYPOINT`):** Parsing of `Dockerfile` stages (`FROM ... AS base`), `ENTRYPOINT`, and `CMD` commands, linking containers to application entrypoints (`backend/main.py`).
- **CI/CD Workflow $\to$ Test Suites (`CI_WORKFLOW`, `RUNS_WORKFLOW_TEST`):** GitHub Actions workflows (`.github/workflows/*.yml`) executing test runners (`pytest`, `npm test`, `vitest`), linked directly to test file nodes.
- **Environment Variable Consumers (`ENV_VARIABLE`, `CONSUMES_ENV_VAR`):** Parsing `os.getenv('DATABASE_URL')` and `os.environ.get('SECRET_KEY')`, creating dependency edges from config modules to environment variable nodes.

### 2.7 Honest Multi-Dimensional Coverage Reporting (`coverage_reporter.py`)
Single "overall coverage" percentages can obscure massive blind spots in large codebases. Phase 3.2 replaces single-number claims with a 5-dimension scorecard:
1. `python_symbol_coverage`: Ratio of successfully parsed Python AST symbols vs discovered `.py` files.
2. `call_edge_resolution_rate`: Percentage of static/runtime resolved calls vs total detected call expressions.
3. `cross_technology_linkage_rate`: Ratio of frontend API calls linked to backend routes, and ORM models linked to database tables.
4. `test_to_code_traceability`: Ratio of application symbols covered by direct or transitive test edges.
5. `dynamic_trace_confirmation_rate`: Percentage of graph edges backed by runtime trace evidence.

Each dimension reports a discrete status:
- `COMPREHENSIVE` ($\ge 85\%$)
- `PARTIAL` ($50\% - 84\%$)
- `MINIMAL` ($1\% - 49\%$)
- `UNSUPPORTED` ($0\%$ or technology not detected)

Aggregate scores are transparently labeled as composite heuristics with explicit gap disclosures.

---

## 3. Frontend Cockpit Expansions

The frontend knowledge graph explorer was updated to provide interactive visibility into Phase 3.2 capabilities:
- **Dimensional Coverage Cards:** Five visual progress meters showing status pills (`COMPREHENSIVE`, `PARTIAL`, `MINIMAL`, `UNSUPPORTED`), exact percentages, and documented gaps.
- **Cross-Technology Trace Inspector:** Dedicated tab exploring multi-tier journeys from React components through APIs, services, ORM models, database tables, Docker stages, and CI workflows.
- **Ambiguous Match Candidate Inspector:** Entity continuity drawer surfacing ambiguous matches, displaying candidate canonical IDs, similarity confidence scores, and selection justification.
- **Transactional Staging & Concurrency Indicator:** Live badge reflecting version state (`ACTIVE`, `STAGED`, `SUPERSEDED`, `FAILED`), lease lock status, and orphan cleanup actions.

Files updated:
- [knowledgeGraphApi.ts](file:///c:/Users/ASHWIN/Downloads/PROJECTS/MISTIQ/MISTIQ/frontend/src/api/knowledgeGraphApi.ts)
- [KnowledgeGraphSection.tsx](file:///c:/Users/ASHWIN/Downloads/PROJECTS/MISTIQ/MISTIQ/frontend/src/components/projectReview/KnowledgeGraphSection.tsx)

---

## 4. Verification & Test Battery

The implementation was validated against a 64-test dedicated Phase 3.2 test suite, followed by full regression testing across Phase 1, Phase 2A–2D.2, Phase 3, Phase 3.1, database integrity, and frontend suites.

### 4.1 Test Suites Executed

| Test Suite | Tests Run | Result | Duration |
|:---|:---:|:---:|:---:|
| `tests/unit/test_phase3_2_reliability_and_relationships.py` | 64 | **64 PASSED** (100%) | 10.66s |
| `tests/unit/test_phase3_1_graph_intelligence.py` | 87 | **87 PASSED** (100%) | 12.14s |
| `tests/unit/test_phase3_knowledge_graph.py` | 56 | **56 PASSED** (100%) | 4.90s |
| `tests/unit/test_database.py` | 2 | **2 PASSED** (100%) | 0.83s |
| `tests/unit/test_phase2d2_crash_recovery.py` | 66 | **66 PASSED** (100%) | 14.09s |
| **Frontend Production Build** (`tsc --noEmit && vite build`) | 98 modules | **0 ERRORS** (100%) | 15.22s |
| **Frontend Test Suite** (`vitest run`) | 98 | **98 PASSED** (100%) | 40.51s |

**Total Backend & Frontend Tests in Active Verification:** **373 tests, 0 failures, 0 regressions.**

### 4.2 Phase 3.2 Test Battery Structure (`test_phase3_2_reliability_and_relationships.py`)
1. **Tests 1–10: Canonical Identity Continuity Reliability**
   - Multi-signal scoring weights, structural AST fingerprinting, file rename integration, function split detection with candidate preservation, function merge detection with candidate preservation, renamed and modified classification, ambiguous match thresholding, and benchmark metrics ($Precision$, $Recall$, $F_1$, and Ambiguity Rate).
2. **Tests 11–21: Call Graph Accuracy and Calibration**
   - 4-tier taxonomy, relative import resolution, method overriding in class hierarchies, constructor calls, type-annotated dispatch, reflection/`getattr` recording, ambiguous polymorphic candidate tracking, and calibration benchmark metrics (Confusion matrix, Brier score, ECE, sample size gate).
3. **Tests 22–29: Transactional Graph Update Reliability**
   - Staging version isolation, multi-worker concurrency lease acquisition/rejection, lease expiration, rollback orphan cleanup, consistency validation detecting dangling edges, database unique constraints, and a real multi-process child worker crash recovery test.
4. **Tests 30–36: Calibrated Blast Radius Assessment**
   - Separation of measured properties from heuristic multipliers, unavailable evidence tracking, risk tier classification, and benchmark metrics ($Precision@High$, $Recall@High$, false-high/low rates, Spearman ranking stability).
5. **Tests 37–46: Targeted Test Selection Validation**
   - All 6 recommendation tiers (`DIRECT_TEST`, `RUNTIME_CONFIRMED_TEST`, `STATICALLY_INFERRED_TEST`, `INTEGRATION_TEST`, `END_TO_END_TEST`, `POTENTIALLY_RELEVANT`), strictly `NOT_EXECUTED` status, and benchmark evaluation ($Precision@K$, $Recall@K$, unnecessary recommendation rate, relevant test coverage).
6. **Tests 47–53: Cross-Technology Relationship Intelligence**
   - End-to-end repository test tracing React `apiClient` $\to$ FastAPI route $\to$ user service $\to$ SQLAlchemy user model $\to$ database table, Dockerfile stages and entrypoint linking, GitHub Actions test execution, and environment variable dependency edges.
7. **Tests 54–57: Honest Multi-Dimensional Coverage Reporting**
   - 5 independent coverage dimensions, valid status categorization, dimensional breakdown, and aggregate gap disclosures.
8. **Tests 58–61: Version Comparison and Historical Intelligence**
   - Graph diffing supporting split/merged entities, edge confidence shifts, and resolution state changes.
9. **Tests 62–64: Tenant Isolation & API Security**
   - Non-disclosing 404 responses for cross-tenant graph access, identity transition queries, and version comparisons.

---

## 5. Architectural Invariants Preserved

1. **Existing Interfaces Intact:** `GraphExtractionEngine`, `TransactionalGraphUpdater`, `BlastRadiusEngine`, and `TestSelectionEngine` maintained full backward compatibility with Phases 3 and 3.1.
2. **Non-Disclosing Multi-Tenant Security:** All graph API endpoints enforce project ownership via tenant isolation checks, returning generic `404 Not Found` errors rather than leaking project existence.
3. **Storage Relational Integrity:** Built upon SQLAlchemy relational tables with foreign keys and compound unique constraints (`uq_graph_nodes_version_canonical`), ensuring that graph data is versioned, auditable, and queryable via SQL.
4. **Deterministic and Calibrated:** Heuristic assumptions are explicitly isolated from structural observations, providing an unvarnished foundation for future autonomous remediation decisions.

---

## 6. Next Steps & Phase Progression

With Phase 3.2 fully implemented, tested, and validated:
- The Engineering Knowledge Graph is sufficiently accurate, resilient, and calibrated to serve as the truth engine for repository-wide engineering decisions.
- The platform is primed for autonomous remediation pipelines that rely on multi-hop blast radius bounds, targeted regression test selection, and cross-technology dependency guarantees.
- Future phases can now safely query the graph with mathematically bounded confidence.

