"""Agent factory with QMS search tools."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain.chat_models import init_chat_model
from deepagents import create_deep_agent

from agent.ingest import load_or_build_index
from agent.search import SearchEngine
from agent.graph import ReferenceGraph
from agent.tools import build_tools
from agent.prompts import QMS_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

DEFAULT_CORPUS_DIR = "data/Example QMS"


def make_agent(
    model_str: str = "anthropic:claude-haiku-4-5-20251001",
    system_prompt: str | None = None,
    corpus_dir: str | Path = DEFAULT_CORPUS_DIR,
    force_ingest: bool = False,
):
    """Create a deep agent with QMS search tools.

    Args:
        model_str: Provider and model in "provider:model" format.
        system_prompt: Optional system prompt override.
        corpus_dir: Path to the QMS document corpus directory.
        force_ingest: If True, rebuild the index even if it exists.

    Returns:
        A compiled LangGraph agent supporting .invoke(), .stream(), .astream().
    """
    corpus_dir = Path(corpus_dir)
    index_dir = corpus_dir.parent / "index"

    db, graph = load_or_build_index(corpus_dir, index_dir, force=force_ingest)

    engine = SearchEngine(db, corpus_dir)
    ref_graph = ReferenceGraph(graph)
    tools = build_tools(engine, ref_graph)

    model = init_chat_model(model_str)

    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt or QMS_SYSTEM_PROMPT,
    )
