# APEX / MISTIQ-APR — Stage 1 & Stage 2 Audit and Baseline Report (`v001`)

**Date:** `2026-10-28`  
**Status:** Verified against persisted SQLite database (`mistiq.db`) and saved model artifacts (`backend/ml/artifacts/mistiq_apr/model.pkl`).

---

## 1. Existing Model Artifacts Inventory (Preserved Untouched)

| Artifact Path | Role | Size (Bytes) | SHA-256 Checksum | Created (UTC) | Modified (UTC) |
|---|---|---:|---|---|---|
| `backend/ml/artifacts/mistiq_apr/model.pkl` | Active production MISTIQ-APR model bundle (`MISTIQAPRModelArtifact` pickle) | `13,593` | `fc28f408390b2b53d62f40e276a8b9b60896cc54a34fbd2369604c6dd89d6be5` | `2026-10-07T17:39:28Z` | `2026-10-09T04:33:37Z` |
| `backend/ml/artifacts/mistiq_apr/model_metadata.json` | Sidecar metadata for `model.pkl` | `9,750` | `e174ed0d5c9e8f84b5e4df12dc5c2c75948b16c03417c6912201b78c438170bc` | `2026-10-07T17:39:28Z` | `2026-10-09T04:33:37Z` |
| `backend/ml/artifacts/mistiq_apr/MISTIQ_APR_RESEARCH_REPORT.md` | Walk-forward research report for v1.0 | `37,319` | `cadf6c08873855f24222014186257ad21b96cfd6e7fae16626bd072375f250a2` | `2026-10-06T13:24:27Z` | `2026-10-09T04:33:37Z` |
| `backend/ml/artifacts/mistiq_apr/MISTIQ_APR_ABLATION_REPORT.md` | Feature-group ablation study for v1.0 | `1,764` | `a63939759df214961659724a4a06a2287e32836805ce1b39b506e3e653e297a6` | `2026-10-06T14:47:11Z` | `2026-10-09T04:33:36Z` |
| `backend/ml/artifacts/ampa.npz` | Learner mistake-intelligence model (`AMPA`) | `2,172` | `df8bae8c3e3309fde5d0616d9c6db35766cfbff581ab04e3d29d92721e75aafc` | `2026-10-06T11:52:58Z` | `2026-10-06T11:52:58Z` |

---

## 2. Dataset Audit (`mistiq.db`)

The "440" figure corresponds to the **444 persisted rows in `project_reviews`**, not 444 distinct repositories.

### Key Quantitative Facts
- **Total rows in `reviewed_projects`:** `205` (with `204` unique project names and `205` unique `repository_path` values).
- **Actual unique real repositories in `mistiq.db`:** **`3`** (`SakshaDatathon`, `MISTIQ`, `EduMentor`), represented across **`5`** `ReviewedProject` rows (`id=1` and `id=3` are parent/child folders of `SakshaDatathon`; `id=2` and `id=184` are parent/child folders of `MISTIQ`; `id=124` is `EduMentor`). Additionally, `backend/mistiq.db` contains `Aadhithya-balu-NAALVAR_SALESTORM_SYSTEM-DESIGN` and `AISKills`.
- **Synthetic E2E temporary test project rows in `mistiq.db`:** **`200`** (`C:\Users\ASHWIN\AppData\Local\Temp\mistiq_direct_e2e_test_*`, `mistiq_complete_test_*`, `mistiq_e2e_test_*`, `mistiq_live_sse_*`). These were created by E2E tests (`tests/e2e/test_direct_project_review.py`, `tests/e2e/test_complete_workflow.py`, `run_direct_e2e_test.py`) that connected directly to the default `SessionLocal` (`sqlite:///./mistiq.db`) and wrote 1-file synthetic temp projects into the production database.
- **Total reviews (`project_reviews`):** `444` (`37` on the 5 real project rows; `407` on the 200 E2E temp test directories).
- **Chronological transitions (`review[i] -> review[i+1]`):** `239` (`32` from real projects; `207` from E2E temp test directories). At the time `model.pkl` v1.0 was trained (`2026-10-09T04:33:37Z`), there were `184` projects, `395` reviews, and `211` transitions.
- **Training observations (`build_observations`):** `741` current (`665` when `model.pkl` v1.0 was trained).
  - `40` observations come from the 5 real project rows.
  - `701` observations (`94.6%`) come from the 200 synthetic E2E temp test directories.
- **Why 239 transitions produce 741 observations (Multi-label Explosion Flaw):**
  - In `backend/ml/mistiq_apr/dataset.py`, `build_observations()` takes a single chronological transition `(review[i] -> review[i+1])`, computes `next_categories = sorted({finding.category for finding in following.findings})`, and emits **one `Observation` per category in `next_categories`** with the **identical feature vector `X`**.
  - Specifically, across the 239 transitions: `24` transitions emit 1 target, `9` emit 2 targets, `125` emit 3 targets, and `81` emit 4 targets (`24*1 + 9*2 + 125*3 + 81*4 = 741`).
  - Because single-label `LogisticRegression` predicts a single class per feature vector `X`, exploding a 3- or 4-label transition into 3 or 4 single-label rows with identical `X` imposes an artificial ceiling of `1/3 ≈ 33.3%` or `1/4 = 25.0%` top-1 accuracy on those transitions while inflating top-3 accuracy to `~88.9%`.
- **Duplicate observations & feature vectors:**
  - Out of `741` observations, there are only **`39` unique feature vectors** and **`62` unique `(feature_vector, target)` pairs**.
  - **`679` of `741` observations (`91.63%`)** are exact duplicates of `(feature_vector, target)` from repeated E2E test runs.
- **Failure categories:**
  - Taxonomy size: `16` categories.
  - Observed in dataset: `5` categories (`testing`: 213, `dependency`: 207, `requirements`: 205, `security`: 114, `integration`: 2).
  - Missing-label percentage: `0.0%` among generated observations (`75` single-review projects have 0 transitions and generate 0 observations).
- **Repository sizes & languages:**
  - `199` temp projects have `file_count = 1` (`src/main.py`), `1` temp project has `file_count = 2`.
  - Real projects have `file_count = 72` (`EduMentor`), `346` (`MISTIQ`), and `1311` (`SakshaDatathon`).
- **Repositories with sufficient chronological history:**
  - `>= 2` reviews: `130` total (`4` real, `126` synthetic temp)
  - `>= 3` reviews: `79` total (`4` real, `75` synthetic temp)
  - `>= 5` reviews: `6` total (`3` real, `3` synthetic temp)
  - `>= 10` reviews: `1` total (`1` real: `MISTIQ` with 21 reviews)

---

## 3. Training Pipeline Audit

1. **Dataset used:** Chronological review pairs loaded from `mistiq.db` via `build_observations(session)`.
2. **Target predicted:** Each category `c` present in `review[i+1].findings` (exploded into separate single-label rows).
3. **Features (`112` total):**
   - `12` static features (`static_total_findings`, `static_{critical,high,medium,low}_findings`, `static_{security,testing,architecture,dependency,config}_risk`, `static_requirement_coverage`, `static_complexity_index`).
   - `16` one-hot `latest_failure_{cat}` features (note: uses `categories[-1]`, which is the alphabetically last category in `current.findings` because `current.findings` are iterated in order).
   - `16` `seq_freq_{cat}` (cumulative finding count in `review[0..i]`).
   - `16` `seq_recency_{cat}` (distance from end of flattened finding list).
   - `16` `seq_repetition_{cat}` (consecutive review streak ending at `review[i]`).
   - `16` `seq_transition_{cat}` (adjacent category transitions in flattened finding list).
   - `16` `seq_component_{cat}` (count of findings with `component` or `file` non-null).
   - `4` scalar summary features (`seq_failure_diversity_recent`, `seq_change_intensity`, `seq_testing_weakness`, `seq_severity_trajectory`).
4. **Algorithm trained:** `sklearn.pipeline.Pipeline(StandardScaler(), LogisticRegression(max_iter=1000, random_state=42))`.
5. **Validation / Split strategy:** Walk-forward expanding window (`generate_walk_forward_splits`) grouped by `(timestamp, project_id, review_number)`.
6. **Repository overlap & Leakage:**
   - Within a single project's timeline, training observations are strictly earlier than test observations.
   - **Critical Undetected Contamination:** Because `200` projects in `mistiq.db` are identical synthetic E2E test runs created sequentially over time, walk-forward cutoffs train on earlier clones of the exact same synthetic E2E test script and test on later clones of the exact same synthetic E2E test script. Furthermore, no repository-grouped holdout evaluation existed to measure generalization to unseen repositories.
7. **API Model Usage & Side-Effect Hazard:**
   - Online prediction (`GET /api/project-reviews/{project_id}/research-prediction`) loads `backend/ml/artifacts/mistiq_apr/model.pkl` via `load_valid_artifact()`.
   - **Hazard identified:** `GET /api/project-reviews/research/evaluation` previously called `train_and_save_model()` unconditionally, which overwrote `model.pkl` whenever the evaluation endpoint was queried.

---

## 4. Baseline Evaluation Report

### A. Original 665-Observation Dataset (Saved in `model_metadata.json`, 207 Walk-Forward Cutoffs, 656 Pooled Predictions)

| Model | Accuracy | Macro Precision | Macro Recall | Macro F1 | Weighted F1 | Top-2 Accuracy | Top-3 Accuracy | Log Loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Majority Class | 0.2866 | 0.1437 | 0.2029 | 0.1528 | 0.2100 | 0.5470 | 0.7195 | 25.7767 |
| Latest Failure | 0.3155 | 0.2599 | 0.2388 | 0.1472 | 0.1823 | 0.4394 | 0.7165 | 24.5206 |
| Static Logistic Regression | 0.3125 | 0.3137 | 0.2431 | 0.2319 | 0.2987 | 0.6061 | 0.8872 | 1.2605 |
| Random Forest | 0.3095 | 0.2540 | 0.3077 | 0.2230 | 0.2595 | 0.6000 | 0.8826 | 1.3026 |
| **MISTIQ-APR v1.0** | **0.3155** | **0.2611** | **0.2550** | **0.2512** | **0.3112** | **0.6067** | **0.8887** | **1.2163** |

#### Per-Category Precision, Recall, F1, and Support (`MISTIQ-APR v1.0`, 656 Pooled Predictions)

| Category | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| `dependency` | 186 | 0.2888 | 0.3602 | 0.3206 |
| `integration` | 0 | 0.0000 | 0.0000 | 0.0000 |
| `requirements` | 184 | 0.3053 | 0.1576 | 0.2079 |
| `security` | 94 | 0.3929 | 0.3511 | 0.3708 |
| `testing` | 192 | 0.3184 | 0.4062 | 0.3570 |

#### Confusion Matrix (`MISTIQ-APR v1.0`, Labels: `[dependency, integration, requirements, security, testing]`)
```text
[[67,  0, 29, 17, 73],
 [ 0,  0,  0,  0,  0],
 [66,  0, 29, 16, 73],
 [32,  0,  8, 33, 21],
 [67,  0, 29, 18, 78]]
```

#### Calibration (`MISTIQ-APR v1.0`)
- **Multiclass Brier Score:** `0.6884`
- **Expected Calibration Error (ECE):** `0.0042`

### B. Real-Repository-Only Subset (`40` Observations across `4` Real Project Timelines)

| Model | Accuracy | Macro F1 | Top-2 Accuracy | Top-3 Accuracy | Log Loss |
|---|---:|---:|---:|---:|---:|
| Majority Class | 0.8485 | 0.3060 | 1.0000 | 1.0000 | 5.4612 |
| Latest Failure | 0.8485 | 0.5229 | 1.0000 | 1.0000 | 5.4612 |
| Static Logistic Regression | 0.8485 | 0.3060 | 1.0000 | 1.0000 | 0.2584 |
| Random Forest | 0.8485 | 0.5070 | 1.0000 | 1.0000 | 0.2903 |
| MISTIQ-APR | 0.8485 | 0.5229 | 1.0000 | 1.0000 | 0.2267 |

*(Note: On the 40 real observations, 32/40 targets are `security`, 6/40 are `testing`, and 2/40 are `integration`, so `MISTIQ-APR` ties `Latest Failure` on Accuracy and Macro F1 while improving log loss.)*

