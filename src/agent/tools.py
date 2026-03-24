"""LangChain @tool definitions for QMS document search."""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool

from agent.search import SearchEngine
from agent.graph import ReferenceGraph


def build_tools(engine: SearchEngine, ref_graph: ReferenceGraph) -> list:
    """Create LangChain tools bound to a search engine and reference graph."""

    @tool
    def search_documents(
        query: str,
        doc_type: Optional[str] = None,
        top_k: int = 20,
    ) -> str:
        """Search QMS documents using hybrid vector + full-text search.

        Use this for finding documents by content, topic, or keyword. Returns
        ranked results with text snippets and metadata.

        Args:
            query: Natural language search query or document ID/keyword.
            doc_type: Optional filter by document type prefix (e.g., "VVPR", "RSK", "BOM", "ECR", "PLN", "MEMO").
            top_k: Maximum number of results to return (default 20).
        """
        results = engine.hybrid_search(query, doc_type=doc_type, top_k=top_k)

        if not results:
            return "No matching documents found."

        output_parts = []
        seen_docs: set[str] = set()
        for r in results:
            doc_key = f"{r.doc_id} Rev {r.revision}" if r.revision else r.doc_id
            section_label = f" > {r.section}" if r.section else ""
            snippet = r.text[:300] + "..." if len(r.text) > 300 else r.text

            output_parts.append(
                f"[{doc_key}]{section_label} ({r.doc_type}, {r.status})\n"
                f"  Title: {r.title}\n"
                f"  Content: {snippet}\n"
            )
            seen_docs.add(doc_key)

        header = f"Found {len(results)} results across {len(seen_docs)} documents:\n\n"
        return header + "\n".join(output_parts)

    @tool
    def list_documents(
        doc_type: Optional[str] = None,
        doc_id_prefix: Optional[str] = None,
        include_obsolete: bool = False,
    ) -> str:
        """List all documents matching filters. Returns a complete, exhaustive inventory.

        Use this for counting documents, enumerating all documents of a type,
        or finding all revisions of a document. Prefer this over search_documents
        when you need an exact count or complete list.

        Args:
            doc_type: Filter by type prefix (e.g., "ECR", "VVPR", "RSK", "PLN", "BOM", "MEMO").
            doc_id_prefix: Filter by document ID prefix (e.g., "BOM-055" to find all revisions).
            include_obsolete: Whether to include obsolete documents (default False).
        """
        results = engine.metadata_filter(
            doc_type=doc_type,
            doc_id_prefix=doc_id_prefix,
            include_obsolete=include_obsolete,
        )

        if not results:
            return "No documents match the specified filters."

        lines = [f"Found {len(results)} document(s):\n"]
        for r in results:
            rev_str = f" Rev {r.revision}" if r.revision else ""
            lines.append(f"- {r.doc_id}{rev_str} ({r.status}) — {r.title}")

        return "\n".join(lines)

    @tool
    def get_document_content(
        doc_id: str,
        revision: Optional[str] = None,
        max_chars: int = 15000,
    ) -> str:
        """Retrieve the full text content of a specific document.

        Use this to read a document's full content after finding it via search
        or list. The document is re-parsed from its source file on disk.
        Very large documents are truncated; use search_documents to find
        specific sections instead.

        Args:
            doc_id: The document ID (e.g., "VVPR-M02-182", "BOM-055").
            revision: Optional revision letter (e.g., "C", "G"). If omitted, returns the first match.
            max_chars: Maximum characters to return (default 15000). Increase if you need more.
        """
        text = engine.get_full_text(doc_id, revision=revision)

        meta = engine.metadata_filter(doc_id=doc_id)
        header = ""
        if meta:
            m = meta[0]
            rev_str = f" Rev {m.revision}" if m.revision else ""
            header = f"Document: {m.doc_id}{rev_str} — {m.title}\nStatus: {m.status}\n\n"

        full = header + text
        if len(full) > max_chars:
            return full[:max_chars] + f"\n\n[TRUNCATED — document is {len(full):,} chars. Use search_documents to find specific sections.]"

        return full

    @tool
    def trace_references(
        doc_id: str,
        direction: str = "both",
        target_id: Optional[str] = None,
    ) -> str:
        """Query the cross-reference graph to find document relationships.

        Use this to trace which documents reference a given document, what a
        document references, or to find a reference chain between two documents.

        Args:
            doc_id: The document ID to query (e.g., "RSK-M02-010").
            direction: "outgoing" (what this doc references), "incoming" (what references this doc), or "both".
            target_id: If provided, find the shortest reference path from doc_id to target_id.
        """
        if target_id:
            path = ref_graph.find_path(doc_id, target_id)
            if path:
                chain = " -> ".join(path)
                return f"Reference chain from {doc_id} to {target_id}:\n{chain}\n\nChain length: {len(path) - 1} hops"
            path_reverse = ref_graph.find_path(target_id, doc_id)
            if path_reverse:
                chain = " -> ".join(path_reverse)
                return f"Reference chain from {target_id} to {doc_id}:\n{chain}\n\nChain length: {len(path_reverse) - 1} hops"
            return f"No reference chain found between {doc_id} and {target_id}."

        parts = []

        if direction in ("outgoing", "both"):
            outgoing = ref_graph.get_references_from(doc_id)
            if outgoing:
                parts.append(f"{doc_id} references {len(outgoing)} document(s):")
                for ref in outgoing:
                    title_str = f" — {ref.title}" if ref.title else ""
                    parts.append(f"  -> {ref.doc_id}{title_str}")
                    if ref.context:
                        parts.append(f"     Context: ...{ref.context}...")
            else:
                parts.append(f"{doc_id} does not reference any other documents.")

        if direction in ("incoming", "both"):
            incoming = ref_graph.get_referenced_by(doc_id)
            if incoming:
                parts.append(f"\n{doc_id} is referenced by {len(incoming)} document(s):")
                for ref in incoming:
                    title_str = f" — {ref.title}" if ref.title else ""
                    parts.append(f"  <- {ref.doc_id}{title_str}")
                    if ref.context:
                        parts.append(f"     Context: ...{ref.context}...")
            else:
                parts.append(f"\n{doc_id} is not referenced by any other documents.")

        return "\n".join(parts)

    @tool
    def compare_revisions(
        doc_id: str,
        rev_a: str,
        rev_b: str,
    ) -> str:
        """Retrieve the content of two revisions of the same document for comparison.

        Use this when a user wants to understand what changed between revisions.
        Returns both documents' full text so you can summarize the differences.

        Args:
            doc_id: The document ID (e.g., "RSK-M02-010", "BOM-055").
            rev_a: First revision letter (e.g., "A", "C").
            rev_b: Second revision letter (e.g., "B", "D").
        """
        text_a = engine.get_full_text(doc_id, revision=rev_a)
        text_b = engine.get_full_text(doc_id, revision=rev_b)

        return (
            f"=== {doc_id} Rev {rev_a} ===\n\n"
            f"{text_a}\n\n"
            f"{'=' * 60}\n\n"
            f"=== {doc_id} Rev {rev_b} ===\n\n"
            f"{text_b}"
        )

    return [search_documents, list_documents, get_document_content, trace_references, compare_revisions]
