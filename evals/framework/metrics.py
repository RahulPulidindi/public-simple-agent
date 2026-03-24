"""Metric store: save, load, and compare evaluation runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from evals.framework.evaluator import CaseEvaluation


@dataclass
class RunReport:
    run_id: str
    timestamp: str
    model: str
    prompt_hash: str
    results: list[dict]
    aggregates: dict

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "results": self.results,
            "aggregates": self.aggregates,
        }


def compute_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


def aggregate_evaluations(evaluations: list[CaseEvaluation]) -> dict:
    """Compute aggregate metrics from a list of case evaluations."""
    if not evaluations:
        return {}

    overall_scores = [e.overall_score for e in evaluations]
    deterministic_scores = [e.deterministic_score for e in evaluations if e.deterministic_scores]
    judge_scores = [e.judge_score for e in evaluations if e.judge_scores]
    tool_counts = [e.tool_calls for e in evaluations]
    elapsed = [e.elapsed_seconds for e in evaluations]
    errors = [e for e in evaluations if e.error]

    by_category: dict[str, list[float]] = {}
    for e in evaluations:
        by_category.setdefault(e.category, []).append(e.overall_score)

    return {
        "overall": round(sum(overall_scores) / len(overall_scores), 3) if overall_scores else 0,
        "deterministic": round(sum(deterministic_scores) / len(deterministic_scores), 3) if deterministic_scores else 0,
        "judge": round(sum(judge_scores) / len(judge_scores), 3) if judge_scores else 0,
        "by_category": {
            cat: round(sum(scores) / len(scores), 3)
            for cat, scores in sorted(by_category.items())
        },
        "cases_total": len(evaluations),
        "cases_with_errors": len(errors),
        "tool_calls_avg": round(sum(tool_counts) / len(tool_counts), 1) if tool_counts else 0,
        "tool_calls_max": max(tool_counts) if tool_counts else 0,
        "elapsed_total_s": round(sum(elapsed), 1),
        "elapsed_avg_s": round(sum(elapsed) / len(elapsed), 1) if elapsed else 0,
    }


def build_report(
    evaluations: list[CaseEvaluation],
    model: str,
    prompt: str,
) -> RunReport:
    """Build a complete run report from evaluations."""
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%d_%H%M%S")

    return RunReport(
        run_id=run_id,
        timestamp=now.isoformat(),
        model=model,
        prompt_hash=compute_prompt_hash(prompt),
        results=[e.to_dict() for e in evaluations],
        aggregates=aggregate_evaluations(evaluations),
    )


def save_report(report: RunReport, results_dir: str | Path) -> Path:
    """Save a run report as JSON."""
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{report.run_id}.json"
    with open(path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    return path


def load_report(path: str | Path) -> RunReport:
    """Load a run report from JSON."""
    with open(path) as f:
        data = json.load(f)
    return RunReport(**data)


def compare_reports(current: RunReport, baseline: RunReport) -> dict:
    """Compare two run reports and return deltas."""
    curr_agg = current.aggregates
    base_agg = baseline.aggregates

    deltas = {
        "overall": round(curr_agg.get("overall", 0) - base_agg.get("overall", 0), 3),
        "deterministic": round(curr_agg.get("deterministic", 0) - base_agg.get("deterministic", 0), 3),
        "judge": round(curr_agg.get("judge", 0) - base_agg.get("judge", 0), 3),
    }

    curr_cats = curr_agg.get("by_category", {})
    base_cats = base_agg.get("by_category", {})
    all_cats = set(list(curr_cats.keys()) + list(base_cats.keys()))

    category_deltas = {}
    for cat in sorted(all_cats):
        curr_val = curr_cats.get(cat, 0)
        base_val = base_cats.get(cat, 0)
        category_deltas[cat] = round(curr_val - base_val, 3)

    deltas["by_category"] = category_deltas

    regressions = []
    for cat, delta in category_deltas.items():
        if delta < -0.1:
            regressions.append(f"{cat}: {base_cats.get(cat, 0):.3f} -> {curr_cats.get(cat, 0):.3f} ({delta:+.3f})")

    deltas["regressions"] = regressions

    return deltas


def get_latest_report(results_dir: str | Path) -> RunReport | None:
    """Get the most recent run report from the results directory."""
    results_dir = Path(results_dir)
    if not results_dir.exists():
        return None

    reports = sorted(results_dir.glob("*.json"), reverse=True)
    if not reports:
        return None

    return load_report(reports[0])
