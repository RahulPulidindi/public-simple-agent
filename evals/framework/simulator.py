"""Simulator: runs golden cases through the agent and collects structured outputs."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

DOC_ID_RE = re.compile(
    r"(3P|BOM|DHF|DMR|DR|ECR|ESF|IFU|MEMO|PLN|QSR|RSK|TRA|VVAM|VVPR)"
    r"[-\s]*(?:(?:M02|MC2|SWV)[-\s]*)?\d+",
    re.IGNORECASE,
)

OUR_TOOLS = {"search_documents", "list_documents", "get_document_content", "trace_references", "compare_revisions"}


@dataclass
class GoldenCase:
    id: str
    query: str
    category: str
    expected_docs: list[str] = field(default_factory=list)
    expected_first_tool: str | None = None
    expected_exact_count: int | None = None
    expected_max_tool_calls: int | None = None
    answer_must_contain: list[str] = field(default_factory=list)
    answer_must_not_contain: list[str] = field(default_factory=list)
    judge_criteria: list[str] = field(default_factory=list)


@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class SimulationResult:
    case_id: str
    category: str
    query: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_steps: list[str] = field(default_factory=list)
    final_answer: str = ""
    total_tool_calls: int = 0
    first_tool: str | None = None
    doc_ids_in_answer: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "query": self.query,
            "tool_calls": [{"name": tc.name, "args": tc.args} for tc in self.tool_calls],
            "reasoning_steps": self.reasoning_steps,
            "final_answer": self.final_answer,
            "total_tool_calls": self.total_tool_calls,
            "first_tool": self.first_tool,
            "doc_ids_in_answer": self.doc_ids_in_answer,
            "elapsed_seconds": self.elapsed_seconds,
            "error": self.error,
        }


def load_golden_cases(golden_dir: str | Path) -> list[GoldenCase]:
    """Load all golden cases from YAML files."""
    golden_dir = Path(golden_dir)
    cases = []

    for yaml_file in sorted(golden_dir.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        category = data.get("name", yaml_file.stem)

        for case_data in data.get("cases", []):
            expected = case_data.get("expected", {})
            cases.append(GoldenCase(
                id=case_data["id"],
                query=case_data["query"],
                category=category,
                expected_docs=expected.get("docs", []),
                expected_first_tool=expected.get("first_tool"),
                expected_exact_count=expected.get("exact_count"),
                expected_max_tool_calls=expected.get("max_tool_calls"),
                answer_must_contain=expected.get("answer_must_contain", []),
                answer_must_not_contain=expected.get("answer_must_not_contain", []),
                judge_criteria=case_data.get("judge_criteria", []),
            ))

    return cases


def extract_doc_ids(text: str) -> list[str]:
    """Extract document IDs from text."""
    seen: set[str] = set()
    result: list[str] = []
    for match in DOC_ID_RE.finditer(text):
        doc_id = re.sub(r"\s+", "-", match.group(0).strip()).upper()
        if doc_id not in seen:
            seen.add(doc_id)
            result.append(doc_id)
    return result


def simulate_case(agent, case: GoldenCase) -> SimulationResult:
    """Run a single golden case through the agent and collect outputs."""
    result = SimulationResult(
        case_id=case.id,
        category=case.category,
        query=case.query,
    )

    start = time.time()

    try:
        messages = [{"role": "user", "content": case.query}]

        for event in agent.stream({"messages": messages}):
            if "model" in event:
                msg = event["model"]["messages"][-1]

                content = getattr(msg, "content", "")
                if isinstance(content, list):
                    content = " ".join(
                        block.get("text", "") for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )

                tool_calls_raw = getattr(msg, "tool_calls", None)

                if content and tool_calls_raw:
                    result.reasoning_steps.append(content.strip())

                if tool_calls_raw:
                    for tc in tool_calls_raw:
                        if tc["name"] in OUR_TOOLS:
                            result.tool_calls.append(ToolCall(name=tc["name"], args=tc["args"]))
                            if result.first_tool is None:
                                result.first_tool = tc["name"]

                if content and not tool_calls_raw:
                    result.final_answer = content.strip()

        result.total_tool_calls = len(result.tool_calls)
        result.doc_ids_in_answer = extract_doc_ids(result.final_answer)

    except Exception as e:
        result.error = str(e)

    result.elapsed_seconds = round(time.time() - start, 2)
    return result


def simulate_all(agent, cases: list[GoldenCase], verbose: bool = False) -> list[SimulationResult]:
    """Run all golden cases through the agent."""
    results = []
    for i, case in enumerate(cases):
        if verbose:
            print(f"  [{i+1}/{len(cases)}] {case.id}: {case.query[:60]}...")
        sim = simulate_case(agent, case)
        if verbose:
            status = "ERROR" if sim.error else f"{sim.total_tool_calls} tools, {sim.elapsed_seconds}s"
            print(f"           {status}")
        results.append(sim)
    return results
