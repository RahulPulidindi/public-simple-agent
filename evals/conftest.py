"""Shared fixtures for eval tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

CORPUS_DIR = Path("data/Example QMS")
INDEX_DIR = Path("data/index")


@pytest.fixture(scope="session")
def search_engine():
    """Build or load the search index once per test session."""
    from agent.ingest import load_or_build_index
    from agent.search import SearchEngine

    db, _graph = load_or_build_index(CORPUS_DIR, INDEX_DIR)
    return SearchEngine(db, CORPUS_DIR)


@pytest.fixture(scope="session")
def ref_graph():
    """Build or load the reference graph once per test session."""
    from agent.ingest import load_or_build_index
    from agent.graph import ReferenceGraph

    _db, graph = load_or_build_index(CORPUS_DIR, INDEX_DIR)
    return ReferenceGraph(graph)


@pytest.fixture(scope="session")
def agent():
    """Create the full agent once per test session."""
    from agent.core import make_agent

    return make_agent()
