"""Cross-reference dependency graph for QMS documents."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import networkx as nx

logger = logging.getLogger(__name__)


@dataclass
class ReferenceInfo:
    doc_id: str
    doc_type: str
    title: str
    context: str
    source_file: str


class ReferenceGraph:
    """Wraps a NetworkX DiGraph for cross-document reference queries."""

    def __init__(self, graph: nx.DiGraph):
        self.graph = graph

    def get_references_from(self, doc_id: str) -> list[ReferenceInfo]:
        """What documents does this document reference?"""
        doc_id = self._normalize_id(doc_id)
        if doc_id not in self.graph:
            return []

        results = []
        for _, target, data in self.graph.out_edges(doc_id, data=True):
            node_data = self.graph.nodes.get(target, {})
            results.append(ReferenceInfo(
                doc_id=target,
                doc_type=node_data.get("doc_type", ""),
                title=node_data.get("title", ""),
                context=data.get("context", ""),
                source_file=data.get("source_file", ""),
            ))

        return results

    def get_referenced_by(self, doc_id: str) -> list[ReferenceInfo]:
        """What documents reference this one?"""
        doc_id = self._normalize_id(doc_id)
        if doc_id not in self.graph:
            return []

        results = []
        for source, _, data in self.graph.in_edges(doc_id, data=True):
            node_data = self.graph.nodes.get(source, {})
            results.append(ReferenceInfo(
                doc_id=source,
                doc_type=node_data.get("doc_type", ""),
                title=node_data.get("title", ""),
                context=data.get("context", ""),
                source_file=data.get("source_file", ""),
            ))

        return results

    def find_path(self, source_id: str, target_id: str) -> list[str] | None:
        """Find shortest reference chain between two documents."""
        source_id = self._normalize_id(source_id)
        target_id = self._normalize_id(target_id)

        if source_id not in self.graph or target_id not in self.graph:
            return None

        try:
            return nx.shortest_path(self.graph, source_id, target_id)
        except nx.NetworkXNoPath:
            return None

    def get_subgraph(self, doc_id: str, depth: int = 2) -> dict:
        """Get the neighborhood of a document up to a given depth.

        Returns a dict with 'nodes' and 'edges' for the subgraph.
        """
        doc_id = self._normalize_id(doc_id)
        if doc_id not in self.graph:
            return {"nodes": [], "edges": []}

        visited: set[str] = set()
        queue = [(doc_id, 0)]
        visited.add(doc_id)

        while queue:
            current, d = queue.pop(0)
            if d >= depth:
                continue
            for neighbor in list(self.graph.successors(current)) + list(self.graph.predecessors(current)):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, d + 1))

        subgraph = self.graph.subgraph(visited)
        nodes = []
        for n in subgraph.nodes:
            data = dict(subgraph.nodes[n])
            data["doc_id"] = n
            nodes.append(data)

        edges = []
        for u, v, data in subgraph.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "context": data.get("context", ""),
            })

        return {"nodes": nodes, "edges": edges}

    def _normalize_id(self, doc_id: str) -> str:
        """Find the best matching node for a doc_id (case-insensitive)."""
        if doc_id in self.graph:
            return doc_id

        upper = doc_id.upper()
        for node in self.graph.nodes:
            if node.upper() == upper:
                return node

        return doc_id
