"""Search engine wrapping LanceDB for hybrid vector+FTS queries and metadata filtering."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import lancedb
from openai import OpenAI

from agent.ingest import parse_document

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    text: str
    doc_id: str
    doc_type: str
    title: str
    revision: str
    status: str
    section: str
    filename: str
    score: float = 0.0


@dataclass
class DocumentMeta:
    doc_id: str
    doc_type: str
    title: str
    revision: str
    status: str
    filename: str


class SearchEngine:
    """Wraps a LanceDB table for hybrid search, metadata filtering, and document retrieval."""

    def __init__(self, db: lancedb.DBConnection, corpus_dir: str | Path):
        self.db = db
        self.table = db.open_table("chunks")
        self.corpus_dir = Path(corpus_dir)
        self._openai = OpenAI()

    def _embed_query(self, query: str) -> list[float]:
        response = self._openai.embeddings.create(
            input=[query], model="text-embedding-3-small"
        )
        return response.data[0].embedding

    def hybrid_search(
        self,
        query: str,
        doc_type: str | None = None,
        include_obsolete: bool = False,
        top_k: int = 20,
    ) -> list[SearchResult]:
        """Run hybrid vector + full-text search with optional metadata filters."""
        where_clauses: list[str] = []
        if not include_obsolete:
            where_clauses.append("status != 'obsolete'")
        if doc_type:
            where_clauses.append(f"doc_type = '{doc_type.upper()}'")

        where = " AND ".join(where_clauses) if where_clauses else None

        query_vector = self._embed_query(query)

        try:
            builder = self.table.search(query_type="hybrid").vector(query_vector).text(query)
            if where:
                builder = builder.where(where, prefilter=True)
            rows = builder.limit(top_k).to_list()
        except Exception:
            logger.warning("Hybrid search failed, falling back to vector-only search")
            builder = self.table.search(query_vector, query_type="vector")
            if where:
                builder = builder.where(where, prefilter=True)
            rows = builder.limit(top_k).to_list()

        results = []
        for row in rows:
            results.append(SearchResult(
                text=row.get("text", ""),
                doc_id=row.get("doc_id", ""),
                doc_type=row.get("doc_type", ""),
                title=row.get("title", ""),
                revision=row.get("revision", ""),
                status=row.get("status", ""),
                section=row.get("section", ""),
                filename=row.get("filename", ""),
                score=row.get("_relevance_score", row.get("_distance", 0.0)),
            ))

        return results

    def metadata_filter(
        self,
        doc_type: str | None = None,
        doc_id: str | None = None,
        doc_id_prefix: str | None = None,
        include_obsolete: bool = False,
    ) -> list[DocumentMeta]:
        """Query document metadata exhaustively (no ranking, no top-K limit)."""
        where_clauses: list[str] = []
        if not include_obsolete:
            where_clauses.append("status != 'obsolete'")
        if doc_type:
            where_clauses.append(f"doc_type = '{doc_type.upper()}'")

        where = " AND ".join(where_clauses) if where_clauses else None

        arrow_table = self.table.to_arrow()
        cols = ["doc_id", "doc_type", "title", "revision", "status", "filename"]

        rows = arrow_table.select(cols).to_pylist()

        if where:
            filtered = []
            for row in rows:
                if not include_obsolete and row["status"] == "obsolete":
                    continue
                if doc_type and row["doc_type"] != doc_type.upper():
                    continue
                filtered.append(row)
            rows = filtered

        if doc_id:
            rows = [r for r in rows if r["doc_id"].upper() == doc_id.upper()]
        if doc_id_prefix:
            rows = [r for r in rows if r["doc_id"].upper().startswith(doc_id_prefix.upper())]

        seen: set[tuple[str, str]] = set()
        unique_rows = []
        for row in rows:
            key = (row["doc_id"], row["revision"])
            if key not in seen:
                seen.add(key)
                unique_rows.append(row)

        unique_rows.sort(key=lambda r: (r["doc_id"], r["revision"]))

        return [
            DocumentMeta(
                doc_id=r["doc_id"],
                doc_type=r["doc_type"],
                title=r["title"],
                revision=r["revision"],
                status=r["status"],
                filename=r["filename"],
            )
            for r in unique_rows
        ]

    def get_full_text(
        self,
        doc_id: str,
        revision: str | None = None,
    ) -> str:
        """Re-parse a document from the corpus directory to get its full text."""
        arrow_table = self.table.to_arrow()
        rows = arrow_table.select(["doc_id", "revision", "filename"]).to_pylist()

        matches = [r for r in rows if r["doc_id"].upper() == doc_id.upper()]
        if revision:
            matches = [r for r in matches if r["revision"].upper() == revision.upper()]

        if not matches:
            return f"Document {doc_id} (revision {revision or 'any'}) not found."

        filename = matches[0]["filename"]
        filepath = self.corpus_dir / filename

        if not filepath.exists():
            return f"Source file not found: {filename}"

        sections = parse_document(filepath)
        if not sections:
            return f"Could not parse document: {filename}"

        full_text = "\n\n".join(
            f"## {heading}\n{text}" if heading else text
            for heading, text in sections
        )

        return full_text
