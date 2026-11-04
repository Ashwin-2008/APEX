"""Graph Query Engine with Bounded Traversal for APEX 2.0.

Provides safe, bounded graph queries:
- Local neighborhood subgraphs with radius and node limit guards.
- Shortest dependency path exploration between components.
- Callers and Callees lookup.
- Filtered node and edge queries with pagination to prevent massive responses.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from app.services.graph.models import EdgeType, GraphEdge, GraphNode


class GraphQueryEngine:
    """Executes guarded queries over in-memory or persisted graph representations."""

    @classmethod
    def get_subgraph(
        cls,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        center_id: str,
        radius: int = 2,
        limit: int = 80,
    ) -> dict[str, Any]:
        """Extracts bounded neighborhood subgraph around center_id."""
        if center_id not in nodes:
            return {"center_id": center_id, "nodes": [], "edges": []}

        subgraph_node_ids = {center_id}
        queue = deque([(center_id, 0)])

        # Precompute forward and backward edge indices
        adj: dict[str, set[str]] = {}
        for edge in edges:
            adj.setdefault(edge.source_canonical_id, set()).add(edge.target_canonical_id)
            adj.setdefault(edge.target_canonical_id, set()).add(edge.source_canonical_id)

        while queue and len(subgraph_node_ids) < limit:
            curr_id, dist = queue.popleft()
            if dist >= radius:
                continue

            for neighbor in adj.get(curr_id, set()):
                if neighbor not in subgraph_node_ids and neighbor in nodes:
                    subgraph_node_ids.add(neighbor)
                    queue.append((neighbor, dist + 1))
                    if len(subgraph_node_ids) >= limit:
                        break

        sub_nodes = [nodes[nid].to_dict() for nid in subgraph_node_ids if nid in nodes]
        sub_edges = [
            e.to_dict()
            for e in edges
            if e.source_canonical_id in subgraph_node_ids and e.target_canonical_id in subgraph_node_ids
        ]

        return {
            "center_id": center_id,
            "radius": radius,
            "total_nodes": len(sub_nodes),
            "total_edges": len(sub_edges),
            "nodes": sub_nodes,
            "edges": sub_edges,
        }

    @classmethod
    def find_shortest_path(
        cls,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        source_id: str,
        target_id: str,
        directed: bool = True,
    ) -> dict[str, Any]:
        """Finds shortest dependency path from source to target using BFS."""
        if source_id not in nodes or target_id not in nodes:
            return {"found": False, "length": -1, "path": [], "edges": []}

        if source_id == target_id:
            return {
                "found": True,
                "length": 0,
                "path": [nodes[source_id].to_dict()],
                "edges": [],
            }

        fwd_edges: dict[str, list[GraphEdge]] = {}
        for e in edges:
            fwd_edges.setdefault(e.source_canonical_id, []).append(e)
            if not directed:
                fwd_edges.setdefault(e.target_canonical_id, []).append(e)

        queue = deque([(source_id, [source_id], [])])
        visited = {source_id}

        while queue:
            curr, path, edge_path = queue.popleft()
            for e in fwd_edges.get(curr, []):
                next_node = e.target_canonical_id if e.source_canonical_id == curr else e.source_canonical_id
                if next_node not in visited and next_node in nodes:
                    new_path = path + [next_node]
                    new_edges = edge_path + [e.to_dict()]
                    if next_node == target_id:
                        return {
                            "found": True,
                            "length": len(new_edges),
                            "path": [nodes[nid].to_dict() for nid in new_path],
                            "edges": new_edges,
                        }
                    visited.add(next_node)
                    queue.append((next_node, new_path, new_edges))

        return {"found": False, "length": -1, "path": [], "edges": []}

    @classmethod
    def get_callers(
        cls,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        target_id: str,
    ) -> list[dict[str, Any]]:
        """Returns direct callers of target_id."""
        callers = []
        for e in edges:
            if e.target_canonical_id == target_id and e.rel_type == EdgeType.CALLS.value:
                caller_node = nodes.get(e.source_canonical_id)
                if caller_node:
                    callers.append({
                        "caller": caller_node.to_dict(),
                        "evidence": e.evidence_location,
                        "confidence": e.confidence,
                    })
        return callers

    @classmethod
    def get_callees(
        cls,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        source_id: str,
    ) -> list[dict[str, Any]]:
        """Returns direct callees invoked by source_id."""
        callees = []
        for e in edges:
            if e.source_canonical_id == source_id and e.rel_type == EdgeType.CALLS.value:
                callee_node = nodes.get(e.target_canonical_id)
                callees.append({
                    "callee": callee_node.to_dict() if callee_node else {"canonical_id": e.target_canonical_id},
                    "evidence": e.evidence_location,
                    "confidence": e.confidence,
                    "unresolved": e.provenance.get("unresolved", False),
                })
        return callees

    @classmethod
    def filter_nodes(
        cls,
        nodes: dict[str, GraphNode],
        entity_type: str | None = None,
        search: str | None = None,
        file_path: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Filters nodes by type, query search, or file path with pagination."""
        res = []
        for n in nodes.values():
            if entity_type and n.entity_type.upper() != entity_type.upper():
                continue
            if file_path and file_path not in n.file_path:
                continue
            if search and search.lower() not in n.name.lower() and search.lower() not in n.qualified_name.lower():
                continue
            res.append(n.to_dict())

        total = len(res)
        paged = res[skip : skip + limit]
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "nodes": paged,
        }

