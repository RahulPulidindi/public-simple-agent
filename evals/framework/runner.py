"""CLI runner for the eval framework."""

from __future__ import annotations

import argparse
import sys
import warnings
import logging
from pathlib import Path

from dotenv import load_dotenv


DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"

GOLDEN_DIR = Path(__file__).parent.parent / "golden"
RESULTS_DIR = Path(__file__).parent.parent / "results"


def format_score(score: float) -> str:
    if score >= 0.8:
        return f"{GREEN}{score:.3f}{RESET}"
    elif score >= 0.5:
        return f"{YELLOW}{score:.3f}{RESET}"
    else:
        return f"{RED}{score:.3f}{RESET}"


def format_delta(delta: float) -> str:
    if delta > 0.05:
        return f"{GREEN}{delta:+.3f}{RESET}"
    elif delta < -0.05:
        return f"{RED}{delta:+.3f}{RESET}"
    else:
        return f"{DIM}{delta:+.3f}{RESET}"


def main():
    load_dotenv()
    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.WARNING)
    for name in ("httpx", "openai", "anthropic", "httpcore", "langchain", "langgraph", "deepagents"):
        logging.getLogger(name).setLevel(logging.ERROR)

    parser = argparse.ArgumentParser(description="QMS Search Eval Framework")
    parser.add_argument(
        "--model",
        default="anthropic:claude-haiku-4-5-20251001",
        help="Model to evaluate",
    )
    parser.add_argument(
        "--judge-model",
        default="gpt-4o-mini",
        help="Model to use as judge (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip LLM-as-judge evaluation (deterministic checks only)",
    )
    parser.add_argument(
        "--compare",
        type=str,
        default=None,
        help="Path to baseline report JSON to compare against",
    )
    parser.add_argument(
        "--case",
        type=str,
        default=None,
        help="Run only a specific case ID",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Run only cases from a specific category YAML file (e.g., 'enumeration')",
    )
    args = parser.parse_args()

    from evals.framework.simulator import load_golden_cases, simulate_all
    from evals.framework.evaluator import evaluate_case
    from evals.framework.metrics import (
        build_report, save_report, load_report, compare_reports, get_latest_report,
    )

    golden_dir = GOLDEN_DIR
    if args.category:
        category_file = golden_dir / f"{args.category}.yaml"
        if not category_file.exists():
            available = [f.stem for f in golden_dir.glob("*.yaml")]
            print(f"{RED}Category '{args.category}' not found. Available: {', '.join(available)}{RESET}")
            sys.exit(1)

    print(f"{BOLD}QMS Search Eval Framework{RESET}")
    print(f"{DIM}Model: {args.model}{RESET}")
    print(f"{DIM}Judge: {'disabled' if args.no_judge else args.judge_model}{RESET}")
    print()

    # Load golden cases
    cases = load_golden_cases(golden_dir)
    if args.case:
        cases = [c for c in cases if c.id == args.case]
        if not cases:
            print(f"{RED}Case '{args.case}' not found.{RESET}")
            sys.exit(1)
    if args.category:
        category_file_stem = args.category
        import yaml
        with open(golden_dir / f"{category_file_stem}.yaml") as f:
            data = yaml.safe_load(f)
        category_name = data.get("name", category_file_stem)
        cases = [c for c in cases if c.category == category_name]

    print(f"{DIM}Loaded {len(cases)} golden cases{RESET}")
    print()

    # Build agent
    print(f"{DIM}Loading agent...{RESET}")
    from agent.core import make_agent
    from agent.prompts import QMS_SYSTEM_PROMPT

    agent = make_agent(model_str=args.model)

    # Simulate
    print(f"{BOLD}Running simulations...{RESET}")
    sim_results = simulate_all(agent, cases, verbose=True)
    print()

    # Evaluate
    print(f"{BOLD}Evaluating results...{RESET}")
    evaluations = []
    for case, sim in zip(cases, sim_results):
        ev = evaluate_case(
            case, sim,
            use_judge=not args.no_judge,
            judge_model=args.judge_model,
        )
        evaluations.append(ev)
        score_str = format_score(ev.overall_score)
        print(f"  {ev.case_id:30s} {score_str}  (det={ev.deterministic_score:.2f}, judge={ev.judge_score:.2f}, tools={ev.tool_calls})")
    print()

    # Build and save report
    report = build_report(evaluations, args.model, QMS_SYSTEM_PROMPT)
    report_path = save_report(report, RESULTS_DIR)

    # Print aggregates
    agg = report.aggregates
    print(f"{BOLD}Aggregates{RESET}")
    print(f"  Overall:       {format_score(agg['overall'])}")
    print(f"  Deterministic: {format_score(agg['deterministic'])}")
    print(f"  Judge:         {format_score(agg['judge'])}")
    print(f"  Tool calls:    avg={agg['tool_calls_avg']}, max={agg['tool_calls_max']}")
    print(f"  Time:          {agg['elapsed_total_s']}s total, {agg['elapsed_avg_s']}s avg")
    print()

    print(f"  {BOLD}By category:{RESET}")
    for cat, score in agg.get("by_category", {}).items():
        print(f"    {cat:35s} {format_score(score)}")
    print()

    # Compare
    baseline_path = args.compare
    if not baseline_path:
        baseline = get_latest_report(RESULTS_DIR)
        if baseline and baseline.run_id != report.run_id:
            baseline_path = str(RESULTS_DIR / f"{baseline.run_id}.json")

    if baseline_path:
        try:
            baseline_report = load_report(baseline_path)
            deltas = compare_reports(report, baseline_report)

            print(f"{BOLD}Comparison vs {baseline_report.run_id}{RESET}")
            print(f"  Overall:       {format_delta(deltas['overall'])}")
            print(f"  Deterministic: {format_delta(deltas['deterministic'])}")
            print(f"  Judge:         {format_delta(deltas['judge'])}")

            if deltas.get("by_category"):
                print(f"\n  {BOLD}By category:{RESET}")
                for cat, delta in deltas["by_category"].items():
                    print(f"    {cat:35s} {format_delta(delta)}")

            if deltas.get("regressions"):
                print(f"\n  {RED}{BOLD}Regressions detected:{RESET}")
                for reg in deltas["regressions"]:
                    print(f"    {RED}{reg}{RESET}")
            else:
                print(f"\n  {GREEN}No regressions detected.{RESET}")
            print()
        except Exception as e:
            print(f"{YELLOW}Could not compare: {e}{RESET}")

    print(f"{DIM}Report saved: {report_path}{RESET}")


if __name__ == "__main__":
    main()
