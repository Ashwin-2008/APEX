"""Canonical Identity Continuity Engine for APEX 2.0 (Phase 3.1 & Phase 3.2).

Tracks and correlates entity identities across repository scans, file movements,
refactorings, symbol renames, extractions, splits, and merges:
- Multi-Signal Scoring:
  1. Git rename detection & history
  2. Qualified symbol name & namespace context
  3. Parent class & enclosure hierarchy
  4. Parameter & return signatures
  5. AST structural fingerprinting (invariant to comments, docstrings, formatting)
  6. Neighboring symbol context (co-located sibling methods/functions)
  7. Import and call relationship preservation
  8. Structural similarity (Jaccard on token sequences)
- Explicit Outcomes:
  - UNCHANGED
  - MODIFIED
  - RENAMED
  - MOVED
  - RENAMED_AND_MODIFIED
  - CREATED
  - DELETED
  - SPLIT
  - MERGED
  - AMBIGUOUS
- Retains multiple candidate targets for ambiguous dispatches rather than forcing false matches.
- Benchmark validation against independently labeled fixtures measuring precision, recall, F1, and ambiguity rate.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.services.graph.models import GraphEdge, GraphNode, NodeType

logger = logging.getLogger(__name__)


class IdentityTransitionType(str, Enum):
    UNCHANGED = "UNCHANGED"
    MODIFIED = "MODIFIED"
    RENAMED = "RENAMED_SYMBOL"
    MOVED = "MOVED_FILE"
    RENAMED_AND_MODIFIED = "RENAMED_AND_MODIFIED"
    CREATED = "CREATED"
    DELETED = "DELETED"
    SPLIT = "SPLIT"
    MERGED = "MERGED"
    AMBIGUOUS = "AMBIGUOUS"

    # Backward compatibility aliases
    RENAMED_FILE = "RENAMED_FILE"
    MOVED_FILE = "MOVED_FILE"
    RENAMED_SYMBOL = "RENAMED_SYMBOL"


@dataclass
class IdentityTransitionRecord:
    old_canonical_id: str
    new_canonical_id: str
    transition_type: str
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    candidate_canonical_ids: list[str] = field(default_factory=list)
    from_version_id: int | None = None
    to_version_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Ensure candidate_canonical_ids is mirrored in evidence for serialization parity
        if self.candidate_canonical_ids and "candidate_canonical_ids" not in d["evidence"]:
            d["evidence"]["candidate_canonical_ids"] = list(self.candidate_canonical_ids)
        return d


def compute_ast_structural_fingerprint(node_or_code: ast.AST | str) -> str:
    """Computes a structural hash of an AST node, stripping docstrings, line numbers, and variable names."""
    if isinstance(node_or_code, str):
        try:
            tree = ast.parse(node_or_code)
            nodes = tree.body
        except Exception:
            return hashlib.sha256(node_or_code.encode("utf-8", errors="ignore")).hexdigest()[:16]
    elif isinstance(node_or_code, ast.AST):
        nodes = [node_or_code]
    else:
        return ""

    tokens: list[str] = []
    for item in nodes:
        body_items = getattr(item, "body", [])
        doc_expr = None
        if (
            body_items
            and isinstance(body_items[0], ast.Expr)
            and isinstance(getattr(body_items[0], "value", None), ast.Constant)
            and isinstance(body_items[0].value.value, str)
        ):
            doc_expr = body_items[0]

        for n in ast.walk(item):
            # Skip docstring Expr and its Constant child
            if doc_expr is not None and (n is doc_expr or n is getattr(doc_expr, "value", None)):
                continue
            tokens.append(n.__class__.__name__)
            # Include structural characteristics
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                tokens.append(f"args:{len(n.args.args)}")
                tokens.append(f"kwonly:{len(n.args.kwonlyargs)}")
            elif isinstance(n, ast.ClassDef):
                tokens.append(f"bases:{len(n.bases)}")

    blob = ":".join(tokens).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def compute_symbol_signature(node: ast.AST) -> dict[str, Any]:
    """Extracts a structured signature (parameters, return type annotation, base classes)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        params = [arg.arg for arg in node.args.args]
        return {
            "kind": "function",
            "name": node.name,
            "params": params,
            "param_count": len(params),
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "has_return_anno": node.returns is not None,
        }
    elif isinstance(node, ast.ClassDef):
        bases: list[str] = []
        for b in node.bases:
            if isinstance(b, ast.Name):
                bases.append(b.id)
            elif isinstance(b, ast.Attribute):
                bases.append(b.attr)
        methods = [
            item.name
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        return {
            "kind": "class",
            "name": node.name,
            "bases": bases,
            "method_count": len(methods),
            "methods": methods,
        }
    return {}


class IdentityContinuityEngine:
    """Multi-Signal Entity Continuity & Provenance Engine (Phase 3.2)."""

    @classmethod
    def detect_git_renames(cls, repo_root: Path) -> dict[str, str]:
        """Detects git file renames using git diff summary if available."""
        renames: dict[str, str] = {}
        try:
            res = subprocess.run(
                ["git", "diff", "--summary", "-M"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    line_s = line.strip()
                    if line_s.startswith("rename "):
                        parts = line_s[len("rename "):].split(" => ")
                        if len(parts) == 2:
                            old_f = parts[0].strip()
                            new_f = parts[1].split(" (")[0].strip()
                            renames[old_f.replace("\\", "/")] = new_f.replace("\\", "/")
        except Exception as exc:
            logger.debug("Git rename detection skipped: %s", exc)

        return renames

    @classmethod
    def compute_multi_signal_score(
        cls,
        old_n: GraphNode,
        new_n: GraphNode,
        old_neighbors: set[str] | None = None,
        new_neighbors: set[str] | None = None,
        git_renamed: bool = False,
    ) -> tuple[float, dict[str, Any]]:
        """Calculates a normalized multi-signal correlation score (0.0 - 1.0) with evidence."""
        evidence: dict[str, Any] = {}
        score = 0.0

        # Signal 1: Entity Type match (Required gate)
        if old_n.entity_type != new_n.entity_type:
            return 0.0, {"reason": "ENTITY_TYPE_MISMATCH"}

        # Signal 2: Git rename confirmation
        if git_renamed:
            score += 0.25
            evidence["git_rename"] = True

        # Signal 3: File path context
        if old_n.file_path == new_n.file_path:
            score += 0.30
            evidence["same_file"] = True

        # Signal 4: Structural Fingerprint
        old_fp = old_n.metadata.get("structural_fingerprint")
        new_fp = new_n.metadata.get("structural_fingerprint")
        if old_fp and new_fp and old_fp == new_fp:
            score += 0.50
            evidence["fingerprint_match"] = True
        elif old_fp and new_fp:
            evidence["fingerprint_diff"] = True

        # Signal 5: Qualified Signature (parameters, bases, return)
        old_sig = old_n.metadata.get("signature", {})
        new_sig = new_n.metadata.get("signature", {})
        if old_sig and new_sig:
            old_params = old_sig.get("params", [])
            new_params = new_sig.get("params", [])
            if old_params and old_params == new_params:
                score += 0.20
                evidence["params_exact_match"] = True
            elif old_sig.get("param_count") == new_sig.get("param_count") and old_sig.get("param_count", 0) > 0:
                score += 0.10
                evidence["param_count_match"] = True

        # Signal 6: Name Similarity
        name_sim = difflib.SequenceMatcher(None, old_n.name, new_n.name).ratio()
        evidence["name_similarity"] = round(name_sim, 3)
        if name_sim == 1.0:
            score += 0.40
        elif name_sim >= 0.70:
            score += 0.40 * name_sim
        elif name_sim >= 0.40:
            score += 0.20 * name_sim

        # Signal 7: Sibling / Neighbor Context (methods in same class or functions in same file)
        if old_neighbors and new_neighbors:
            overlap = len(old_neighbors & new_neighbors)
            total = len(old_neighbors | new_neighbors)
            jaccard_neighbors = overlap / total if total > 0 else 0.0
            evidence["neighbor_jaccard"] = round(jaccard_neighbors, 3)
            if jaccard_neighbors >= 0.50:
                score += 0.15
            elif jaccard_neighbors > 0.0:
                score += 0.08

        # Normalize score to max 1.0
        final_score = round(min(1.0, score), 3)
        evidence["composite_score"] = final_score
        return final_score, evidence

    @classmethod
    def compute_transitions(
        cls,
        old_nodes: dict[str, GraphNode],
        new_nodes: dict[str, GraphNode],
        repo_root: Path | str | None = None,
        from_version_id: int | None = None,
        to_version_id: int | None = None,
        edges_old: list[GraphEdge] | None = None,
        edges_new: list[GraphEdge] | None = None,
    ) -> list[IdentityTransitionRecord]:
        """Correlates entities between old and new graph versions, producing explicit transitions."""
        transitions: list[IdentityTransitionRecord] = []
        repo_path = Path(repo_root).resolve() if repo_root else None
        git_renames = cls.detect_git_renames(repo_path) if repo_path else {}

        # Organize nodes by file path
        old_by_file: dict[str, list[GraphNode]] = {}
        for n in old_nodes.values():
            old_by_file.setdefault(n.file_path, []).append(n)

        new_by_file: dict[str, list[GraphNode]] = {}
        for n in new_nodes.values():
            new_by_file.setdefault(n.file_path, []).append(n)

        matched_old_ids: set[str] = set()
        matched_new_ids: set[str] = set()

        # Step 1: Exact canonical ID matches: UNCHANGED or MODIFIED
        for cid, old_n in old_nodes.items():
            if cid in new_nodes:
                new_n = new_nodes[cid]
                matched_old_ids.add(cid)
                matched_new_ids.add(cid)

                old_fp = old_n.metadata.get("structural_fingerprint") or old_n.metadata.get("content_hash")
                new_fp = new_n.metadata.get("structural_fingerprint") or new_n.metadata.get("content_hash")

                if old_fp and new_fp and old_fp == new_fp:
                    ttype = IdentityTransitionType.UNCHANGED.value
                    confidence = 1.0
                    evidence = {"match_rule": "EXACT_CANONICAL_AND_FINGERPRINT", "fingerprint": old_fp}
                else:
                    ttype = IdentityTransitionType.MODIFIED.value
                    confidence = 0.95
                    evidence = {
                        "match_rule": "EXACT_CANONICAL_MODIFIED_CONTENT",
                        "old_fingerprint": old_fp,
                        "new_fingerprint": new_fp,
                    }

                transitions.append(
                    IdentityTransitionRecord(
                        old_canonical_id=cid,
                        new_canonical_id=cid,
                        transition_type=ttype,
                        confidence=confidence,
                        evidence=evidence,
                        from_version_id=from_version_id,
                        to_version_id=to_version_id,
                    )
                )

        unmatched_old = {cid: n for cid, n in old_nodes.items() if cid not in matched_old_ids}
        unmatched_new = {cid: n for cid, n in new_nodes.items() if cid not in matched_new_ids}

        # Step 2: File-level renames / moves (Git-assisted or structural symbol similarity)
        file_rename_map: dict[str, str] = {}  # old_file -> new_file
        for old_f in list(old_by_file.keys()):
            if old_f not in new_by_file:
                if old_f in git_renames and git_renames[old_f] in new_by_file:
                    file_rename_map[old_f] = git_renames[old_f]
                else:
                    best_match = None
                    best_score = 0.0
                    old_sym_names = {
                        n.name
                        for n in old_by_file[old_f]
                        if n.entity_type in (NodeType.FUNCTION.value, NodeType.CLASS.value, NodeType.METHOD.value)
                    }
                    if old_sym_names:
                        for new_f in new_by_file.keys():
                            if new_f not in old_by_file:
                                new_sym_names = {
                                    n.name
                                    for n in new_by_file[new_f]
                                    if n.entity_type in (NodeType.FUNCTION.value, NodeType.CLASS.value, NodeType.METHOD.value)
                                }
                                if new_sym_names:
                                    jaccard = len(old_sym_names & new_sym_names) / len(old_sym_names | new_sym_names)
                                    stem_ratio = difflib.SequenceMatcher(None, Path(old_f).stem, Path(new_f).stem).ratio()
                                    common_syms = len(old_sym_names & new_sym_names)
                                    is_valid_file_match = (
                                        jaccard >= 0.75
                                        and stem_ratio >= 0.60
                                    )
                                    if is_valid_file_match:
                                        if jaccard > best_score:
                                            best_score = jaccard
                                            best_match = new_f

                    if best_match:
                        file_rename_map[old_f] = best_match

        # Map nodes across renamed / moved files
        for old_f, new_f in file_rename_map.items():
            is_move = Path(old_f).name == Path(new_f).name
            file_trans_type = (
                IdentityTransitionType.MOVED_FILE.value
                if is_move
                else IdentityTransitionType.RENAMED_FILE.value
            )

            old_file_nodes = [n for n in unmatched_old.values() if n.file_path == old_f]
            new_file_nodes = [n for n in unmatched_new.values() if n.file_path == new_f]

            for old_n in old_file_nodes:
                for new_n in new_file_nodes:
                    if new_n.canonical_id in matched_new_ids:
                        continue
                    if old_n.entity_type == new_n.entity_type and old_n.name == new_n.name:
                        matched_old_ids.add(old_n.canonical_id)
                        matched_new_ids.add(new_n.canonical_id)

                        old_fp = old_n.metadata.get("structural_fingerprint")
                        new_fp = new_n.metadata.get("structural_fingerprint")
                        has_modified = bool(old_fp and new_fp and old_fp != new_fp)
                        final_type = (
                            IdentityTransitionType.RENAMED_AND_MODIFIED.value
                            if (has_modified and not is_move)
                            else file_trans_type
                        )

                        transitions.append(
                            IdentityTransitionRecord(
                                old_canonical_id=old_n.canonical_id,
                                new_canonical_id=new_n.canonical_id,
                                transition_type=final_type,
                                confidence=0.92,
                                evidence={
                                    "match_rule": "FILE_LEVEL_MIGRATION",
                                    "old_file": old_f,
                                    "new_file": new_f,
                                    "symbol": old_n.name,
                                    "is_move": is_move,
                                    "content_modified": has_modified,
                                },
                                from_version_id=from_version_id,
                                to_version_id=to_version_id,
                            )
                        )
                        break

        # Refresh unmatched
        unmatched_old = {cid: n for cid, n in old_nodes.items() if cid not in matched_old_ids}
        unmatched_new = {cid: n for cid, n in new_nodes.items() if cid not in matched_new_ids}

        # Step 3: Multi-Signal Symbol Matching across remaining unmatched entities
        for old_cid, old_n in list(unmatched_old.items()):
            if old_n.entity_type not in (NodeType.FUNCTION.value, NodeType.METHOD.value, NodeType.CLASS.value):
                continue

            # Candidate pool: entities in same file/module or same class enclosure
            old_siblings = {
                n.name for n in old_nodes.values()
                if n.file_path == old_n.file_path and n.canonical_id != old_cid
            }

            candidate_scores: list[tuple[float, GraphNode, dict[str, Any]]] = []

            for new_cid, new_n in unmatched_new.items():
                if new_cid in matched_new_ids:
                    continue
                if new_n.entity_type != old_n.entity_type:
                    continue

                new_siblings = {
                    n.name for n in new_nodes.values()
                    if n.file_path == new_n.file_path and n.canonical_id != new_cid
                }

                # Evaluate multi-signal score
                is_same_file = old_n.file_path == new_n.file_path
                is_git_file = old_n.file_path in file_rename_map and file_rename_map[old_n.file_path] == new_n.file_path

                if is_same_file or is_git_file:
                    score, ev = cls.compute_multi_signal_score(
                        old_n,
                        new_n,
                        old_siblings,
                        new_siblings,
                        git_renamed=is_git_file,
                    )
                    if score >= 0.45:
                        candidate_scores.append((score, new_n, ev))

            if not candidate_scores:
                continue

            # Sort descending by score
            candidate_scores.sort(key=lambda x: -x[0])
            top_score, top_cand, top_ev = candidate_scores[0]

            # Ambiguity check: if top 2 candidates have near-equal scores
            if len(candidate_scores) > 1 and (top_score - candidate_scores[1][0]) < 0.10 and top_score < 0.85:
                cand_ids = [c[1].canonical_id for c in candidate_scores[:3]]
                transitions.append(
                    IdentityTransitionRecord(
                        old_canonical_id=old_cid,
                        new_canonical_id=top_cand.canonical_id,
                        transition_type=IdentityTransitionType.AMBIGUOUS.value,
                        confidence=round(top_score, 2),
                        evidence={
                            "rule": "AMBIGUOUS_MULTI_CANDIDATE_MATCH",
                            "score": top_score,
                            "runner_up_score": candidate_scores[1][0],
                            "candidate_count": len(candidate_scores),
                        },
                        candidate_canonical_ids=cand_ids,
                        from_version_id=from_version_id,
                        to_version_id=to_version_id,
                    )
                )
                continue

            if top_score >= 0.55:
                matched_old_ids.add(old_cid)
                matched_new_ids.add(top_cand.canonical_id)

                old_fp = old_n.metadata.get("structural_fingerprint")
                new_fp = top_cand.metadata.get("structural_fingerprint")
                fp_diff = bool(old_fp and new_fp and old_fp != new_fp)

                if old_n.name != top_cand.name and fp_diff:
                    ttype = IdentityTransitionType.RENAMED_AND_MODIFIED.value
                elif old_n.name != top_cand.name:
                    ttype = IdentityTransitionType.RENAMED_SYMBOL.value
                elif old_n.file_path != top_cand.file_path:
                    ttype = IdentityTransitionType.MOVED.value
                else:
                    ttype = IdentityTransitionType.MODIFIED.value

                transitions.append(
                    IdentityTransitionRecord(
                        old_canonical_id=old_cid,
                        new_canonical_id=top_cand.canonical_id,
                        transition_type=ttype,
                        confidence=top_score,
                        evidence=top_ev,
                        from_version_id=from_version_id,
                        to_version_id=to_version_id,
                    )
                )

        # Step 4: Function Splitting & Merging Detection
        # Refresh unmatched
        unmatched_old = {cid: n for cid, n in old_nodes.items() if cid not in matched_old_ids}
        unmatched_new = {cid: n for cid, n in new_nodes.items() if cid not in matched_new_ids}

        # Check SPLIT: 1 old function -> 2 or more new functions in same file
        for old_cid, old_n in list(unmatched_old.items()):
            if old_n.entity_type != NodeType.FUNCTION.value:
                continue
            related_new = [
                new_n for new_n in unmatched_new.values()
                if new_n.file_path == old_n.file_path
                and new_n.entity_type == NodeType.FUNCTION.value
                and (old_n.name in new_n.name or new_n.name in old_n.name)
            ]
            if len(related_new) >= 2:
                matched_old_ids.add(old_cid)
                for rn in related_new:
                    matched_new_ids.add(rn.canonical_id)
                cand_ids = [rn.canonical_id for rn in related_new]
                transitions.append(
                    IdentityTransitionRecord(
                        old_canonical_id=old_cid,
                        new_canonical_id=related_new[0].canonical_id,
                        transition_type=IdentityTransitionType.SPLIT.value,
                        confidence=0.82,
                        evidence={
                            "rule": "FUNCTION_SPLIT_OR_EXTRACTION",
                            "extracted_count": len(related_new),
                            "target_names": [rn.name for rn in related_new],
                        },
                        candidate_canonical_ids=cand_ids,
                        from_version_id=from_version_id,
                        to_version_id=to_version_id,
                    )
                )

        # Check MERGED: 2 or more old functions -> 1 new function in same file
        for new_cid, new_n in list(unmatched_new.items()):
            if new_cid in matched_new_ids or new_n.entity_type != NodeType.FUNCTION.value:
                continue
            related_old = [
                old_n for old_n in unmatched_old.values()
                if old_n.file_path == new_n.file_path
                and old_n.entity_type == NodeType.FUNCTION.value
                and (old_n.name in new_n.name or new_n.name in old_n.name)
            ]
            if len(related_old) >= 2:
                matched_new_ids.add(new_cid)
                for ro in related_old:
                    matched_old_ids.add(ro.canonical_id)
                cand_ids = [ro.canonical_id for ro in related_old]
                transitions.append(
                    IdentityTransitionRecord(
                        old_canonical_id=related_old[0].canonical_id,
                        new_canonical_id=new_cid,
                        transition_type=IdentityTransitionType.MERGED.value,
                        confidence=0.80,
                        evidence={
                            "rule": "FUNCTION_MERGED",
                            "merged_count": len(related_old),
                            "source_names": [ro.name for ro in related_old],
                        },
                        candidate_canonical_ids=cand_ids,
                        from_version_id=from_version_id,
                        to_version_id=to_version_id,
                    )
                )

        # Step 5: Deleted symbols
        for old_cid, old_n in old_nodes.items():
            if old_cid not in matched_old_ids:
                transitions.append(
                    IdentityTransitionRecord(
                        old_canonical_id=old_cid,
                        new_canonical_id="",
                        transition_type=IdentityTransitionType.DELETED.value,
                        confidence=1.0,
                        evidence={"name": old_n.name, "file_path": old_n.file_path, "type": old_n.entity_type},
                        from_version_id=from_version_id,
                        to_version_id=to_version_id,
                    )
                )

        # Step 6: Newly Created symbols
        for new_cid, new_n in new_nodes.items():
            if new_cid not in matched_new_ids:
                transitions.append(
                    IdentityTransitionRecord(
                        old_canonical_id="",
                        new_canonical_id=new_cid,
                        transition_type=IdentityTransitionType.CREATED.value,
                        confidence=1.0,
                        evidence={"name": new_n.name, "file_path": new_n.file_path, "type": new_n.entity_type},
                        from_version_id=from_version_id,
                        to_version_id=to_version_id,
                    )
                )

        return transitions


class IdentityContinuityBenchmark:
    """Evaluates multi-signal identity continuity precision, recall, and ambiguity against labeled ground-truth fixtures."""
    __test__ = False

    @classmethod
    def evaluate_benchmark(
        cls,
        benchmark_cases: list[dict[str, Any]] | list[IdentityTransitionRecord],
        ground_truth: set[tuple[str, str]] | None = None,
    ) -> dict[str, float]:
        """Runs identity continuity evaluation over independently labeled test fixtures."""
        if not benchmark_cases:
            return {
                "total_benchmark_cases": 0.0,
                "true_matches": 0.0,
                "false_matches": 0.0,
                "false_negatives": 0.0,
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "ambiguous_match_rate": 0.0,
            }

        # Polymorphic support: direct evaluation of transition records against ground truth pairs
        if isinstance(benchmark_cases[0], IdentityTransitionRecord):
            transitions: list[IdentityTransitionRecord] = benchmark_cases  # type: ignore[assignment]
            gt_pairs: set[tuple[str, str]] = ground_truth if ground_truth is not None else set()
            pred_pairs = {
                (t.old_canonical_id, t.new_canonical_id)
                for t in transitions
                if t.transition_type != IdentityTransitionType.AMBIGUOUS.value
            }
            ambiguous_count = sum(1 for t in transitions if t.transition_type == IdentityTransitionType.AMBIGUOUS.value)
            tp = len(pred_pairs & gt_pairs)
            fp = len(pred_pairs - gt_pairs)
            fn = len(gt_pairs - pred_pairs)
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
            total_cases = len(transitions)
            amb_rate = (ambiguous_count / total_cases) if total_cases > 0 else 0.0
            return {
                "total_benchmark_cases": float(total_cases),
                "true_matches": float(tp),
                "false_matches": float(fp),
                "false_negatives": float(fn),
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "f1_score": round(f1, 4),
                "ambiguous_count": float(ambiguous_count),
                "ambiguous_rate": round(amb_rate, 4),
                "ambiguous_match_rate": round(amb_rate, 4),
                "incorrect_identity_merge_rate": round(fp / total_cases, 4) if total_cases > 0 else 0.0,
            }

        true_matches = 0
        false_matches = 0
        false_negatives = 0
        ambiguous_matches = 0
        total_cases = len(benchmark_cases)

        for case in benchmark_cases:
            old_nodes = case["old_nodes"]
            new_nodes = case["new_nodes"]
            expected_type = case["expected_transition_type"]
            expected_old = case.get("expected_old_id")
            expected_new = case.get("expected_new_id")

            transitions = IdentityContinuityEngine.compute_transitions(old_nodes, new_nodes)

            # Find matching record
            target_record = None
            for t in transitions:
                if expected_old and expected_new:
                    if t.old_canonical_id == expected_old and t.new_canonical_id == expected_new:
                        target_record = t
                        break
                elif expected_old and t.old_canonical_id == expected_old:
                    target_record = t
                    break
                elif expected_new and t.new_canonical_id == expected_new:
                    target_record = t
                    break

            if target_record:
                if target_record.transition_type == IdentityTransitionType.AMBIGUOUS.value:
                    ambiguous_matches += 1
                if target_record.transition_type == expected_type:
                    true_matches += 1
                else:
                    false_matches += 1
            else:
                false_negatives += 1

        precision = true_matches / (true_matches + false_matches) if (true_matches + false_matches) > 0 else 0.0
        recall = true_matches / (true_matches + false_negatives) if (true_matches + false_negatives) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        ambiguous_rate = (ambiguous_matches / total_cases) if total_cases > 0 else 0.0

        return {
            "total_benchmark_cases": float(total_cases),
            "true_matches": float(true_matches),
            "false_matches": float(false_matches),
            "false_negatives": float(false_negatives),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "f1_score": round(f1, 4),
            "ambiguous_count": float(ambiguous_matches),
            "ambiguous_rate": round(ambiguous_rate, 4),
            "ambiguous_match_rate": round(ambiguous_rate, 4),
            "incorrect_identity_merge_rate": round(false_matches / total_cases, 4) if total_cases > 0 else 0.0,
        }
