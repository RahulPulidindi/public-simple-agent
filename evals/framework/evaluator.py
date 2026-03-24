"""Evaluator: deterministic checks + LLM-as-judge scoring."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from openai import OpenAI

from evals.framework.simulator import GoldenCase, SimulationResult

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """\
You are evaluating a QMS (Quality Management System) document search assistant. \
Your job is to score the assistant's response against specific quality criteria.

## Context

User query: {query}

Assistant's final answer:
{answer}

Tool calls made by the assistant:
{tool_calls}

## Instructions

Score each criterion below as PASS (1) or FAIL (0). Provide a brief reason for each score.

Criteria:
{criteria}

Return ONLY valid JSON in this exact format:
{{"scores": [{{"criterion": "<criterion text>", "score": 1, "reason": "<brief reason>"}}, ...]}}\
"""


@dataclass
class CriterionScore:
    criterion: str
    score: int  # 0 or 1
    reason: str
    source: str  # "deterministic" or "judge"


@dataclass
class CaseEvaluation:
    case_id: str
    category: str
    query: str
    deterministic_scores: list[CriterionScore] = field(default_factory=list)
    judge_scores: list[CriterionScore] = field(default_factory=list)
    deterministic_score: float = 0.0
    judge_score: float = 0.0
    overall_score: float = 0.0
    tool_calls: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "query": self.query,
            "deterministic_score": self.deterministic_score,
            "judge_score": self.judge_score,
            "overall_score": self.overall_score,
            "tool_calls": self.tool_calls,
            "elapsed_seconds": self.elapsed_seconds,
            "error": self.error,
            "deterministic_details": [
                {"criterion": s.criterion, "score": s.score, "reason": s.reason}
                for s in self.deterministic_scores
            ],
            "judge_details": [
                {"criterion": s.criterion, "score": s.score, "reason": s.reason}
                for s in self.judge_scores
            ],
        }


def run_deterministic_checks(case: GoldenCase, sim: SimulationResult) -> list[CriterionScore]:
    """Run deterministic (non-LLM) checks on a simulation result."""
    scores = []

    if case.expected_first_tool:
        passed = sim.first_tool == case.expected_first_tool
        scores.append(CriterionScore(
            criterion=f"First tool should be {case.expected_first_tool}",
            score=1 if passed else 0,
            reason=f"First tool was {sim.first_tool}" if not passed else "Correct",
            source="deterministic",
        ))

    if case.expected_max_tool_calls is not None:
        passed = sim.total_tool_calls <= case.expected_max_tool_calls
        scores.append(CriterionScore(
            criterion=f"Tool calls should be <= {case.expected_max_tool_calls}",
            score=1 if passed else 0,
            reason=f"Used {sim.total_tool_calls} tool calls" if not passed else "Correct",
            source="deterministic",
        ))

    if case.expected_exact_count is not None:
        count_str = str(case.expected_exact_count)
        passed = count_str in sim.final_answer
        scores.append(CriterionScore(
            criterion=f"Answer should contain exact count {count_str}",
            score=1 if passed else 0,
            reason="Count not found in answer" if not passed else "Correct",
            source="deterministic",
        ))

    for term in case.answer_must_contain:
        passed = term.lower() in sim.final_answer.lower()
        scores.append(CriterionScore(
            criterion=f"Answer must contain '{term}'",
            score=1 if passed else 0,
            reason=f"'{term}' not found in answer" if not passed else "Correct",
            source="deterministic",
        ))

    for term in case.answer_must_not_contain:
        passed = term.lower() not in sim.final_answer.lower()
        scores.append(CriterionScore(
            criterion=f"Answer must NOT contain '{term}'",
            score=1 if passed else 0,
            reason=f"'{term}' found in answer" if not passed else "Correct",
            source="deterministic",
        ))

    for doc_id in case.expected_docs:
        passed = doc_id.upper() in sim.final_answer.upper()
        scores.append(CriterionScore(
            criterion=f"Answer should reference {doc_id}",
            score=1 if passed else 0,
            reason=f"{doc_id} not found in answer" if not passed else "Correct",
            source="deterministic",
        ))

    if sim.error:
        scores.append(CriterionScore(
            criterion="No runtime errors",
            score=0,
            reason=f"Error: {sim.error}",
            source="deterministic",
        ))

    return scores


def run_judge(
    case: GoldenCase,
    sim: SimulationResult,
    model: str = "gpt-4o-mini",
) -> list[CriterionScore]:
    """Run LLM-as-judge evaluation on a simulation result."""
    if not case.judge_criteria:
        return []

    tool_calls_str = "\n".join(
        f"  {i+1}. {tc.name}({json.dumps(tc.args)})"
        for i, tc in enumerate(sim.tool_calls)
    ) or "  (no tool calls)"

    criteria_str = "\n".join(
        f"  {i+1}. {c}" for i, c in enumerate(case.judge_criteria)
    )

    prompt = JUDGE_PROMPT.format(
        query=case.query,
        answer=sim.final_answer[:5000] if sim.final_answer else "(no answer)",
        tool_calls=tool_calls_str,
        criteria=criteria_str,
    )

    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        data = json.loads(content)

        scores = []
        for item in data.get("scores", []):
            scores.append(CriterionScore(
                criterion=item.get("criterion", ""),
                score=1 if item.get("score", 0) == 1 else 0,
                reason=item.get("reason", ""),
                source="judge",
            ))
        return scores

    except Exception as e:
        logger.warning("Judge failed for case %s: %s", case.id, e)
        return [CriterionScore(
            criterion="Judge execution",
            score=0,
            reason=f"Judge failed: {e}",
            source="judge",
        )]


def evaluate_case(
    case: GoldenCase,
    sim: SimulationResult,
    use_judge: bool = True,
    judge_model: str = "gpt-4o-mini",
) -> CaseEvaluation:
    """Evaluate a single simulation result against its golden case."""
    evaluation = CaseEvaluation(
        case_id=case.id,
        category=case.category,
        query=case.query,
        tool_calls=sim.total_tool_calls,
        elapsed_seconds=sim.elapsed_seconds,
        error=sim.error,
    )

    evaluation.deterministic_scores = run_deterministic_checks(case, sim)
    if evaluation.deterministic_scores:
        total = sum(s.score for s in evaluation.deterministic_scores)
        evaluation.deterministic_score = round(total / len(evaluation.deterministic_scores), 3)

    if use_judge and case.judge_criteria:
        evaluation.judge_scores = run_judge(case, sim, model=judge_model)
        if evaluation.judge_scores:
            total = sum(s.score for s in evaluation.judge_scores)
            evaluation.judge_score = round(total / len(evaluation.judge_scores), 3)

    all_scores = evaluation.deterministic_scores + evaluation.judge_scores
    if all_scores:
        total = sum(s.score for s in all_scores)
        evaluation.overall_score = round(total / len(all_scores), 3)

    return evaluation
