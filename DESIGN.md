# Design Document: QMS Document Search System

## Problem

Search over a customer's internal QMS document corpus is the lowest-performing category in Valkai's product. Users need to find, cross-reference, and extract information from ~189 regulated documents spanning verification protocols, risk assessments, design history, BOMs, and engineering changes. The query types are diverse: known-item retrieval, exploratory search, compliance cross-referencing, content extraction, revision tracking, and enumeration. No single naive approach handles all of them well.

## Architecture

Four layers: **ingestion**, **search infrastructure**, **agent tools**, and **interfaces** (CLI + web).

### Ingestion Pipeline (`src/agent/ingest.py`)

1. **Filename metadata extraction** — regex-based parsing of QMS naming conventions (`PREFIX-ID - Title_Revision[-Status].ext`) into structured fields: `doc_id`, `doc_type`, `title`, `revision`, `status`, `filename`.

2. **Document parsing** — `python-docx` for `.docx` (paragraphs, tables, heading hierarchy), `openpyxl` for `.xlsx` (sheets as structured rows). Extensionless files are tried as docx first.

3. **Section-aware chunking** — docx files split at heading boundaries (H1/H2/H3), with `RecursiveCharacterTextSplitter` (1500 chars, 200 overlap) as fallback for long or headingless sections. xlsx sheets kept whole to preserve tabular structure. Every chunk carries parent document metadata.

4. **Cross-reference extraction** — regex scan of each document's full text for document ID patterns. Each match becomes a directed edge in a NetworkX graph: `(source_doc_id, target_doc_id, context_snippet, source_filename)`. The corpus produced 2,774 nodes and 5,258 edges.

5. **Embedding** — all chunk texts embedded via OpenAI `text-embedding-3-small` (1536 dimensions). 19,183 chunks from 165 parseable documents.

### Search Infrastructure

**LanceDB** (`src/agent/search.py`) — single embedded database handling:
- **Hybrid search**: vector similarity + Tantivy full-text search, fused via Reciprocal Rank Fusion (RRF). One call, no manual fusion code.
- **Metadata filtering**: columnar scans for exhaustive document inventory queries.
- **Document retrieval**: re-parses source files from disk on demand (no full text duplication per chunk). Large results truncated at 15K chars with a message directing the agent to use targeted search instead.

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

### System Prompt (`src/agent/prompts.py`)

Domain-specific prompt covering:
- Document naming conventions and status semantics (current/signed = completed, not "planned")
- Tool selection routing with explicit examples per query type
- Mandatory `trace_references`-first policy for traceability queries
- Regulatory knowledge protocol: search corpus for the company's own regulatory plan before using training knowledge, and always label the source
- Citation format: `[DOC_ID Rev X]` for every factual claim

### Interfaces

**Streaming CLI** (`src/agent/cli.py`) — uses `agent.stream()` to display reasoning, tool calls with natural-language summaries, and the final answer.

**Web UI** (`frontend/`) — React + Tailwind + react-markdown. Streams responses via SSE from a FastAPI endpoint (`POST /chat/stream`). Displays a chronological timeline of reasoning steps and tool calls (with inline pulse animation during execution), markdown-rendered answers, and source citation chips. Includes clickable example queries on the empty state.

**SSE Streaming Endpoint** (`src/agent/server.py`) — `POST /chat/stream` yields structured JSON events (`reasoning`, `tool_call`, `tool_result`, `answer`, `sources`, `done`). The existing `POST /chat` (synchronous) is preserved.

## Evaluation Framework (`evals/`)

Three tiers of evaluation:

**1. Search quality tests** (`evals/test_search.py`) — 23 pytest tests covering known-item retrieval, exploratory search, enumeration, revision tracking, cross-references, and metadata extraction. No LLM calls, runs in ~4 seconds.

**2. End-to-end agent tests** (`evals/test_agent.py`) — smoke tests and query-pattern tests that invoke the full agent and assert on response content.

**3. Golden dataset evaluation** (`evals/golden/` + `evals/framework/`) — 22 golden cases across 7 YAML files (one per query pattern). Each case specifies expected tool selection, document IDs, must-contain strings, and natural-language judge criteria. The framework has four components:
- **Simulator** — runs each case through `agent.stream()`, collects tool calls, reasoning, and final answer into a structured result
- **Evaluator** — deterministic checks (first tool, count, must-contain) weighted alongside LLM-as-judge scoring (gpt-4o-mini scores each criterion as PASS/FAIL)
- **Metric store** — saves JSON run reports with per-case and aggregate scores, compares against baselines, detects regressions (>0.1 drop in any category)
- **Runner** — CLI entry point (`uv run python run_eval.py`) with flags for `--case`, `--category`, `--no-judge`, `--compare`

Baseline eval score: **0.914 overall** (0.932 deterministic, 0.890 judge) across all 22 cases.

## Key Design Decisions

### Why LanceDB over ChromaDB + BM25?

LanceDB provides vector search, full-text search (via Tantivy), and columnar metadata filtering in a single embedded database. This eliminated two dependencies (`chromadb`, `rank-bm25`) and the manual RRF fusion code. For a 189-document corpus, performance differences are negligible — the choice is about API simplicity.

### Why five tools instead of one?

Different query types have fundamentally different retrieval characteristics:
- **Enumeration** ("How many ECRs?") needs exhaustive recall → `list_documents`
- **Content search** ("acceptance criteria for...") needs ranked relevance → `search_documents`
- **Traceability** ("what references the risk file?") needs graph traversal → `trace_references`

A single mega-tool would force the LLM to encode this routing logic in its arguments. Separate tools make the agent's reasoning explicit and debuggable.

### Why a cross-reference graph?

QMS documents are heavily cross-referenced by design — verification protocols reference requirements, risk files, and design inputs; ECRs reference the BOMs they change; the trace matrix references practically everything. Building this graph at ingestion time enables instant traceability queries (single tool call, <1s) that would otherwise require 10-15 iterative search calls.

### Why section-based chunking?

QMS documents have meaningful structure — sections like "Acceptance Criteria", "Test Results", and "Scope" are semantically coherent units. Splitting at heading boundaries preserves this context. Fixed-size chunking would split mid-table or mid-paragraph, losing semantic coherence.

### Why re-parse for full text instead of caching?

Full document text is NOT stored per chunk (which would duplicate a 50-page document across all 30+ of its chunks). `get_document_content` re-parses the original file from disk on demand. For files of this size, re-parsing is negligible and avoids index bloat.

### Why SSE streaming for the web UI?

The agent makes multiple tool calls per query (avg 3.8, max 15). Without streaming, the user stares at a blank screen for 10-60 seconds. SSE lets the frontend show each reasoning step and tool call as it happens, with pulse animations during execution — making the wait feel purposeful rather than broken.

## What I'd Do With More Time

1. **Internet retrieval tool** — add a web search tool so the agent can look up external regulatory standards (FDA guidance documents, IEC standard text, PubMed) at query time rather than relying on training knowledge. Critical for compliance cross-reference queries where the user asks about a specific regulation.

2. **Programmatic diff for revision comparison** — replace the current approach (dumping both revisions for the LLM to compare) with a structured diff that aligns sections between revisions and highlights additions, deletions, and modifications. The LLM would then summarize the diff rather than comparing raw text, improving accuracy and reducing token usage.

3. **Query classification** — a lightweight classifier (or few-shot prompt) that routes queries to the optimal tool before the main LLM sees search results. Would reduce unnecessary tool calls on traceability and enumeration queries where the agent sometimes picks the wrong tool first.

4. **Automated eval in CI** — run the eval suite on every PR to catch search quality and tool routing regressions; alert on category-level score drops >0.1. Store results as artifacts for trend tracking. Important to run on prompt changes, model changes, and pipeline changes.

5. **Contextual chunking** — use the document's table of contents or section numbering to create hierarchically-aware chunks, where each chunk knows its position in the document structure.

6. **Reranking** — add a cross-encoder reranker after initial hybrid retrieval to improve precision on the top results.

7. **Incremental ingestion** — detect changed/added files and update only affected chunks and graph edges instead of rebuilding the entire index.

8. **Graph-enhanced retrieval** — use the cross-reference graph to expand search results: if a VVPR is relevant, automatically surface the risk file it references.

9. **Multi-revision awareness** — teach the agent to automatically prefer the latest non-obsolete revision unless the user specifically asks for a historical version.

10. **Citation verification** — post-process agent responses to verify that every `[DOC_ID Rev X]` citation actually matches content from the cited document.
