# Design Document: QMS Document Search System

## Problem

Search over a customer's internal QMS document corpus is the lowest-performing category in Valkai's product. Users need to find, cross-reference, and extract information from ~189 regulated documents spanning verification protocols, risk assessments, design history, BOMs, and engineering changes. The query types are diverse: known-item retrieval, exploratory search, compliance cross-referencing, content extraction, revision tracking, and enumeration. No single naive approach handles all of them well.

## Architecture

Three layers: **ingestion**, **search infrastructure**, and **agent tools**.

### Ingestion Pipeline (`src/agent/ingest.py`)

1. **Filename metadata extraction** — regex-based parsing of QMS naming conventions (`PREFIX-ID - Title_Revision[-Status].ext`) into structured fields: `doc_id`, `doc_type`, `title`, `revision`, `status`, `filename`.

2. **Document parsing** — `python-docx` for `.docx` (paragraphs, tables, heading hierarchy), `openpyxl` for `.xlsx` (sheets as structured rows). Extensionless files are tried as docx first.

3. **Section-aware chunking** — docx files split at heading boundaries (H1/H2/H3), with `RecursiveCharacterTextSplitter` (1500 chars, 200 overlap) as fallback for long or headingless sections. xlsx sheets kept whole to preserve tabular structure. Every chunk carries parent document metadata.

4. **Cross-reference extraction** — regex scan of each document's full text for document ID patterns. Each match becomes a directed edge in a NetworkX graph: `(source_doc_id, target_doc_id, context_snippet, source_filename)`.

5. **Embedding** — all chunk texts embedded via OpenAI `text-embedding-3-small` (1536 dimensions, ~$0.01 for the entire corpus).

### Search Infrastructure

**LanceDB** (`src/agent/search.py`) — single embedded database handling:
- **Hybrid search**: vector similarity + Tantivy full-text search, fused via Reciprocal Rank Fusion (RRF). One call, no manual fusion code.
- **Metadata filtering**: columnar scans for exhaustive document inventory queries.
- **Document retrieval**: re-parses source files from disk on demand (no full text duplication per chunk).

**NetworkX DiGraph** (`src/agent/graph.py`) — cross-reference dependency graph:
- Nodes = document IDs with metadata attributes
- Edges = references found in text with context snippets
- Supports: outgoing/incoming reference queries, shortest path between documents, BFS neighborhood extraction

### Agent Tools (`src/agent/tools.py`)

Five LangChain `@tool` functions, each targeting specific query patterns:

| Tool | Purpose | Query Patterns |
|------|---------|---------------|
| `search_documents` | Hybrid vector+FTS search | Known-item, exploratory, content extraction |
| `list_documents` | Exhaustive metadata inventory | Enumeration, exploratory |
| `get_document_content` | Full document text retrieval | Content extraction, revision tracking |
| `trace_references` | Cross-reference graph queries | Cross-doc analysis, compliance |
| `compare_revisions` | Two-revision content for diffing | Revision tracking |

### Streaming CLI (`src/agent/cli.py`)

Uses `agent.stream()` to display four elements in real-time:
- `[reasoning]` — LLM's explanation of its next step
- `[tool]` — tool name and arguments
- `[sources]` — document IDs extracted from tool results
- Final answer with citations

## Key Design Decisions

### Why LanceDB over ChromaDB + BM25?

LanceDB provides vector search, full-text search (via Tantivy), and columnar metadata filtering in a single embedded database. This eliminated two dependencies (`chromadb`, `rank-bm25`) and the manual RRF fusion code. For a 189-document corpus, performance differences are negligible — the choice is about API simplicity.

### Why five tools instead of one?

Different query types have fundamentally different retrieval characteristics:
- **Enumeration** ("How many ECRs?") needs exhaustive recall → `list_documents`
- **Content search** ("acceptance criteria for...") needs ranked relevance → `search_documents`
- **Traceability** ("what references the risk file?") needs graph traversal → `trace_references`

A single mega-tool would force the LLM to encode this routing logic in its arguments. Separate tools make the agent's reasoning explicit and debuggable.

### Why section-based chunking?

QMS documents have meaningful structure — sections like "Acceptance Criteria", "Test Results", and "Scope" are semantically coherent units. Splitting at heading boundaries preserves this context. Fixed-size chunking would split mid-table or mid-paragraph, losing semantic coherence. The tradeoff is variable chunk sizes, but for search quality this is worthwhile.

### Why a cross-reference graph?

QMS documents are heavily cross-referenced by design — verification protocols reference requirements, risk files, and design inputs; ECRs reference the BOMs they change; the trace matrix references practically everything. Building this graph at ingestion time enables instant traceability queries that would otherwise require repeated full-corpus searches.

### Why re-parse for full text instead of caching?

Full document text is NOT stored per chunk (which would duplicate a 50-page document across all 30+ of its chunks). Instead, `get_document_content` re-parses the original `.docx`/`.xlsx` file from disk. For files of this size, re-parsing is negligible (<100ms) and avoids index bloat.

## What I'd Do With More Time

1. **Contextual chunking** — use the document's table of contents or section numbering to create hierarchically-aware chunks, where each chunk knows its position in the document structure.

2. **Query classification** — a lightweight classifier (or prompt) that routes queries to the optimal tool before the LLM sees search results, reducing unnecessary tool calls.

3. **Reranking** — add a cross-encoder reranker (e.g., Cohere Rerank or a local model) after the initial hybrid retrieval to improve precision on the top results.

4. **Incremental ingestion** — detect changed/added files and update only affected chunks and graph edges instead of rebuilding the entire index.

5. **Graph-enhanced retrieval** — use the cross-reference graph to expand search results: if a VVPR is relevant, automatically surface the risk file it references.

6. **Evaluation automation** — LLM-as-judge evaluation for answer quality (not just doc ID presence), testing citation accuracy and completeness.

7. **Multi-revision awareness** — teach the agent to automatically prefer the latest non-obsolete revision unless the user specifically asks for a historical version.

8. **Semantic caching** — cache embedding results so re-ingestion of unchanged documents skips the embedding API call.
