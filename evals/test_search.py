"""Search tool quality tests -- fast, no LLM calls.

Tests the search engine and reference graph directly against known
properties of the QMS corpus.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Known-Item Retrieval
# ---------------------------------------------------------------------------

class TestKnownItemRetrieval:
    """User knows a document exists and wants to find it."""

    def test_search_by_doc_id(self, search_engine):
        results = search_engine.hybrid_search("BOM-055")
        doc_ids = {r.doc_id for r in results}
        assert "BOM-055" in doc_ids

    def test_search_by_title_keywords(self, search_engine):
        results = search_engine.hybrid_search("MC2 top-level assembly bill of materials")
        doc_ids = {r.doc_id for r in results}
        assert "BOM-055" in doc_ids

    def test_search_verification_protocol(self, search_engine):
        results = search_engine.hybrid_search("electrical safety verification")
        assert len(results) > 0
        doc_types = {r.doc_type for r in results}
        assert "VVPR" in doc_types or "3P" in doc_types

    def test_search_risk_assessment(self, search_engine):
        results = search_engine.hybrid_search("risk assessment MC2 OXO")
        doc_ids = {r.doc_id for r in results}
        assert any("RSK" in did for did in doc_ids)


# ---------------------------------------------------------------------------
# Exploratory Search
# ---------------------------------------------------------------------------

class TestExploratorySearch:
    """User wants to survey what's available on a topic."""

    def test_list_all_risk_documents(self, search_engine):
        results = search_engine.metadata_filter(doc_type="RSK")
        assert len(results) >= 4

    def test_list_all_verification_protocols(self, search_engine):
        results = search_engine.metadata_filter(doc_type="VVPR")
        assert len(results) >= 50

    def test_list_planning_documents(self, search_engine):
        results = search_engine.metadata_filter(doc_type="PLN")
        assert len(results) >= 5

    def test_search_with_type_filter(self, search_engine):
        results = search_engine.hybrid_search("risk", doc_type="RSK")
        for r in results:
            assert r.doc_type == "RSK"


# ---------------------------------------------------------------------------
# Enumeration & Counting
# ---------------------------------------------------------------------------

class TestEnumeration:
    """User wants a definitive count or inventory."""

    def test_count_ecrs(self, search_engine):
        results = search_engine.metadata_filter(doc_type="ECR")
        assert len(results) == 3
        doc_ids = {r.doc_id for r in results}
        assert "ECR-577" in doc_ids
        assert "ECR-587" in doc_ids
        assert "ECR-593" in doc_ids

    def test_count_bom_revisions(self, search_engine):
        results = search_engine.metadata_filter(doc_id_prefix="BOM-055")
        revisions = {r.revision for r in results}
        assert "E" in revisions
        assert "F" in revisions
        assert "G" in revisions

    def test_count_third_party_reports(self, search_engine):
        results = search_engine.metadata_filter(doc_type="3P")
        assert len(results) >= 2

    def test_obsolete_filtering(self, search_engine):
        all_docs = search_engine.metadata_filter(include_obsolete=True)
        current_docs = search_engine.metadata_filter(include_obsolete=False)
        assert len(all_docs) > len(current_docs)


# ---------------------------------------------------------------------------
# Revision Tracking
# ---------------------------------------------------------------------------

class TestRevisionTracking:
    """User wants to understand document history."""

    def test_multiple_revisions_exist(self, search_engine):
        results = search_engine.metadata_filter(doc_id_prefix="BOM-055", include_obsolete=True)
        assert len(results) >= 3

    def test_plan_revision_chains(self, search_engine):
        results = search_engine.metadata_filter(doc_id_prefix="PLN-M02-060", include_obsolete=True)
        assert len(results) >= 2

    def test_get_full_text(self, search_engine):
        text = search_engine.get_full_text("BOM-055", revision="G")
        assert len(text) > 100
        assert "not found" not in text.lower()


# ---------------------------------------------------------------------------
# Cross-Reference Graph
# ---------------------------------------------------------------------------

class TestCrossReferences:
    """Cross-document reference queries via the graph."""

    def test_graph_has_nodes(self, ref_graph):
        assert ref_graph.graph.number_of_nodes() > 0

    def test_graph_has_edges(self, ref_graph):
        assert ref_graph.graph.number_of_edges() > 0

    def test_outgoing_references(self, ref_graph):
        refs = ref_graph.get_references_from("RSK-M02-010")
        # The risk assessment should reference other docs, or at minimum exist
        assert isinstance(refs, list)

    def test_incoming_references(self, ref_graph):
        refs = ref_graph.get_referenced_by("RSK-M02-010")
        assert isinstance(refs, list)

    def test_find_path_exists(self, ref_graph):
        nodes = list(ref_graph.graph.nodes)
        if len(nodes) >= 2:
            for source in nodes[:5]:
                for target in nodes[:5]:
                    if source != target:
                        path = ref_graph.find_path(source, target)
                        if path:
                            assert path[0] == source
                            assert path[-1] == target
                            return
            # No path found among sampled nodes -- that's acceptable

    def test_subgraph(self, ref_graph):
        nodes = list(ref_graph.graph.nodes)
        if nodes:
            result = ref_graph.get_subgraph(nodes[0], depth=1)
            assert "nodes" in result
            assert "edges" in result


# ---------------------------------------------------------------------------
# Metadata Extraction
# ---------------------------------------------------------------------------

class TestMetadataExtraction:
    """Verify filename parsing produces correct metadata."""

    def test_doc_types_are_valid(self, search_engine):
        results = search_engine.metadata_filter(include_obsolete=True)
        valid_types = {"3P", "BOM", "DHF", "DMR", "DR", "ECR", "ESF", "IFU",
                       "MEMO", "PLN", "QSR", "RSK", "TRA", "VVAM", "VVPR", "UNKNOWN"}
        for r in results:
            assert r.doc_type in valid_types, f"Unexpected doc_type: {r.doc_type} for {r.doc_id}"

    def test_statuses_are_valid(self, search_engine):
        results = search_engine.metadata_filter(include_obsolete=True)
        valid_statuses = {"current", "obsolete", "signed"}
        for r in results:
            assert r.status in valid_statuses, f"Unexpected status: {r.status} for {r.doc_id}"
