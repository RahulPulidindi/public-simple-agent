"""End-to-end agent tests -- these make real LLM calls."""

from __future__ import annotations

import pytest
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Original smoke tests
# ---------------------------------------------------------------------------

def test_agent_responds(agent):
    """Agent should return a non-empty response to a simple question."""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "What is 2 + 2?"}]}
    )
    assert len(result["messages"]) > 1
    ai_msg = result["messages"][-1]
    assert ai_msg.content
    assert "4" in ai_msg.content


def test_agent_multi_turn(agent):
    """Agent should handle multi-turn conversation."""
    r1 = agent.invoke(
        {"messages": [{"role": "user", "content": "My name is Alice."}]}
    )
    msgs = r1["messages"]
    msgs.append({"role": "user", "content": "What is my name?"})
    r2 = agent.invoke({"messages": msgs})
    ai_msg = r2["messages"][-1]
    assert "Alice" in ai_msg.content


# ---------------------------------------------------------------------------
# QMS Search: Known-Item Retrieval
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_find_bom(agent):
    """Agent should find the Bill of Materials for MC2 OXO."""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Find the Bill of Materials for the MC2 OXO system"}]}
    )
    reply = result["messages"][-1].content
    assert "BOM-055" in reply or "BOM" in reply


# ---------------------------------------------------------------------------
# QMS Search: Enumeration
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_count_ecrs(agent):
    """Agent should accurately count engineering change requests."""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "How many engineering change requests are in the system?"}]}
    )
    reply = result["messages"][-1].content
    assert "3" in reply
    assert "ECR" in reply


# ---------------------------------------------------------------------------
# QMS Search: Exploratory
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_list_risk_documents(agent):
    """Agent should list risk-related documents."""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Show me all risk-related documents"}]}
    )
    reply = result["messages"][-1].content
    assert "RSK" in reply


# ---------------------------------------------------------------------------
# QMS Search: Cross-Reference
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_trace_references(agent):
    """Agent should trace document references."""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Which verification protocols trace back to the risk analysis?"}]}
    )
    reply = result["messages"][-1].content
    assert "RSK" in reply or "VVPR" in reply or "risk" in reply.lower()


# ---------------------------------------------------------------------------
# QMS Search: Content Extraction
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_extract_content(agent):
    """Agent should extract specific content from documents."""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "What verification test protocols do we have for the MC2 OXO?"}]}
    )
    reply = result["messages"][-1].content
    assert "VVPR" in reply
