"""Streaming CLI chat agent with tool call and source visibility."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import warnings

from dotenv import load_dotenv

from agent.core import make_agent

DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BOLD = "\033[1m"

OUR_TOOLS = {"search_documents", "list_documents", "get_document_content", "trace_references", "compare_revisions"}

RESULT_COUNT_RE = re.compile(r"Found (\d+) (?:result|document)")
REFERENCES_RE = re.compile(r"references (\d+) document")
REFERENCED_BY_RE = re.compile(r"referenced by (\d+) document")
CHAIN_RE = re.compile(r"Reference chain .+?:\n(.+)")
NOT_FOUND_RE = re.compile(r"not found|No matching|No documents match|No reference chain")


def print_reasoning(content: str) -> None:
    text = content.strip()
    if not text:
        return
    lines = text.split("\n")
    compact = " ".join(l.strip() for l in lines if l.strip())
    if len(compact) > 200:
        compact = compact[:200] + "..."
    print(f"  {DIM}{compact}{RESET}")


def print_tool_call(name: str, args: dict) -> None:
    args_str = ", ".join(f'{k}={json.dumps(v)}' for k, v in args.items() if v is not None)
    print(f"  {CYAN}> {name}({args_str}){RESET}")


def summarize_tool_result(tool_name: str, content: str) -> str | None:
    """Extract a compact summary from structured tool output."""
    if NOT_FOUND_RE.search(content):
        return "no results"

    if tool_name == "search_documents":
        m = RESULT_COUNT_RE.search(content)
        if m:
            return f"{m.group(1)} results"

    elif tool_name == "list_documents":
        m = RESULT_COUNT_RE.search(content)
        if m:
            return f"{m.group(1)} documents"

    elif tool_name == "get_document_content":
        lines = content.split("\n", 2)
        if lines and lines[0].startswith("Document:"):
            return lines[0].replace("Document: ", "")
        chars = len(content)
        if chars > 1000:
            return f"loaded ({chars:,} chars)"
        return "loaded"

    elif tool_name == "trace_references":
        parts = []
        m_out = REFERENCES_RE.search(content)
        m_in = REFERENCED_BY_RE.search(content)
        m_chain = CHAIN_RE.search(content)
        if m_chain:
            return f"chain: {m_chain.group(1).strip()}"
        if m_out:
            parts.append(f"{m_out.group(1)} outgoing")
        if m_in:
            parts.append(f"{m_in.group(1)} incoming")
        if parts:
            return ", ".join(parts)

    elif tool_name == "compare_revisions":
        return "loaded both revisions"

    return None


def main():
    load_dotenv()

    warnings.filterwarnings("ignore")

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    for logger_name in ("httpx", "openai", "anthropic", "httpcore", "langchain", "langgraph", "deepagents"):
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    parser = argparse.ArgumentParser(description="QMS Document Search Agent")
    parser.add_argument(
        "--model",
        default="anthropic:claude-haiku-4-5-20251001",
        help="Model string, e.g. openai:gpt-4o, anthropic:claude-haiku-4-5-20251001",
    )
    parser.add_argument(
        "--corpus",
        default="data/Example QMS",
        help="Path to corpus directory",
    )
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Force re-indexing of the corpus",
    )
    parser.add_argument(
        "--system",
        default=None,
        help="Custom system prompt override",
    )
    args = parser.parse_args()

    print(f"{DIM}Loading agent and search index...{RESET}")
    agent = make_agent(
        model_str=args.model,
        system_prompt=args.system,
        corpus_dir=args.corpus,
        force_ingest=args.ingest,
    )
    print(f"{DIM}Ready.{RESET} Type {BOLD}quit{RESET} to exit.\n")

    messages = []

    while True:
        try:
            user_input = input(f"{GREEN}{BOLD}You:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break

        messages.append({"role": "user", "content": user_input})

        print()
        final_messages = None

        for event in agent.stream({"messages": messages}):
            if "model" in event:
                msg = event["model"]["messages"][-1]

                content = getattr(msg, "content", "")
                if isinstance(content, list):
                    content = " ".join(
                        block.get("text", "") for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )

                tool_calls = getattr(msg, "tool_calls", None)

                if content and tool_calls:
                    print_reasoning(content)
                elif content and not tool_calls:
                    print(f"\n{content}\n")

                if tool_calls:
                    for tc in tool_calls:
                        name = tc["name"]
                        if name in OUR_TOOLS:
                            print_tool_call(name, tc["args"])

                final_messages = event["model"]["messages"]

            elif "tools" in event:
                tool_msg = event["tools"]["messages"][-1]
                tool_name = getattr(tool_msg, "name", "")
                if tool_name not in OUR_TOOLS:
                    continue
                tool_content = getattr(tool_msg, "content", "")
                if isinstance(tool_content, str):
                    summary = summarize_tool_result(tool_name, tool_content)
                    if summary:
                        print(f"  {DIM}  → {summary}{RESET}")

        if final_messages is not None:
            messages = final_messages

        print()


if __name__ == "__main__":
    main()
