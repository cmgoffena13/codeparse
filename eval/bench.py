#!/usr/bin/env python3
"""Token-usage benchmark: codeparse MCP (+ read/grep/glob/ls) vs read/grep on a
pinned SQLMesh checkout.

Supports --provider cursor (Cursor SDK) or claude (Claude Agent SDK).
"""

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.codeparse_mcp.skill import SKILL_INSTRUCTIONS

EVAL_DIR = REPO_ROOT / "eval"
TASKS_PATH = EVAL_DIR / "tasks.json"
CACHE_DIR = EVAL_DIR / "cache"
RESULTS_DIR = EVAL_DIR / "results"
SQLMESH_DIR = CACHE_DIR / "sqlmesh"

DEFAULT_MODELS = {
    "cursor": "grok-4.7",
    "claude": "claude-opus-5-5-medium",
}

ANSWER_FORMAT = """\
Follow the exact field labels requested in the question. Put each field on its own line.
Do not invent paths. Prefer precise qualified names when the tools provide them.
"""

CURSOR_DISALLOWED = ["shell", "task", "webSearch", "edit"]

# Claude Code built-ins that would break a fair read/grep baseline.
CLAUDE_DISALLOWED_WRITE = [
    "Bash",
    "Write",
    "Edit",
    "NotebookEdit",
    "WebSearch",
    "WebFetch",
    "Agent",
    "Task",
    "Skill",
    "SlashCommand",
]
CURSOR_BASELINE_TOOLS = ["read", "grep", "glob", "ls"]
CURSOR_CODEPARSE_TOOLS = ["read", "grep", "glob", "ls", "mcp"]
CLAUDE_BASELINE_TOOLS = ["Read", "Grep", "Glob", "LS"]
CLAUDE_CODEPARSE_TOOLS = ["Read", "Grep", "Glob", "LS"]


def _load_tasks() -> dict[str, Any]:
    return json.loads(TASKS_PATH.read_text(encoding="utf-8"))


def ensure_sqlmesh(sha: str, repo_url: str) -> Path:
    if not SQLMESH_DIR.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", repo_url, str(SQLMESH_DIR)],
            check=True,
        )
    current = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=SQLMESH_DIR,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if current != sha:
        subprocess.run(["git", "fetch", "--depth", "1", "origin", sha], cwd=SQLMESH_DIR, check=True)
        subprocess.run(["git", "checkout", "--force", sha], cwd=SQLMESH_DIR, check=True)
    return SQLMESH_DIR.resolve()


def index_sqlmesh(sqlmesh: Path) -> None:
    subprocess.run(
        [
            "uv",
            "run",
            "--directory",
            str(REPO_ROOT),
            "--",
            "python",
            "-m",
            "src.app",
            "index",
            "--cwd",
            str(sqlmesh),
        ],
        check=True,
    )


def grade(
    answer: str,
    must_contain: list[str],
    must_contain_any: list[list[str]] | None = None,
) -> tuple[bool, list[str]]:
    missing = [item for item in must_contain if item not in answer]
    for group in must_contain_any or []:
        if not any(item in answer for item in group):
            missing.append(f"any_of:{'|'.join(group)}")
    return (not missing, missing)


def _cursor_usage_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "total_tokens": usage.total_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
    }


def _claude_usage_dict(usage: dict[str, Any] | None) -> dict[str, Any] | None:
    if not usage:
        return None
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "total_tokens": input_tokens + output_tokens + cache_read + cache_write,
        "reasoning_tokens": None,
    }


def _mcp_server_args(sqlmesh: Path) -> list[str]:
    return [
        "run",
        "--directory",
        str(REPO_ROOT),
        "--",
        "python",
        "-m",
        "src.app",
        "mcp",
        "--cwd",
        str(sqlmesh),
    ]


def build_prompt(task: dict[str, Any], *, arm: str) -> str:
    parts = [
        f"Repository root: {SQLMESH_DIR.resolve()}",
        "You are answering one benchmark question about this checkout.",
        task["prompt"],
        ANSWER_FORMAT,
    ]
    if arm == "codeparse":
        parts.insert(
            0,
            "You have read/grep/glob/ls plus the codeparse MCP server. "
            "Prefer ``get_file_overview`` / ``get_symbol`` for file and "
            "symbol contents when those tools fit (follow this skill).\n\n" + SKILL_INSTRUCTIONS,
        )
    else:
        parts.insert(
            0,
            "You may only use read/grep/glob/ls. Do not invent file contents.",
        )
    return "\n\n".join(parts)


_MCP_ARG_META = frozenset({"toolName", "tool_name", "server", "serverName", "name"})


def _tool_name_from_mapping(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    # Cursor toolCall.message: {"type": "grep", "args": ..., "result": ...}
    # MCP wraps as {"type": "mcp", "args": {"toolName": "search_symbols", ...}}
    typ = payload.get("type")
    if not isinstance(typ, str) or not typ.strip():
        return None
    typ = typ.strip()
    if typ == "mcp":
        args = payload.get("args")
        if isinstance(args, dict):
            tool = args.get("toolName")
            if isinstance(tool, str) and tool.strip():
                return tool.strip()
    return typ


def _normalize_tool_name(name: str) -> str:
    prefix = "mcp__codeparse__"
    if name.startswith(prefix):
        return name[len(prefix) :]
    return name


def _sorted_tool_counts(counts: Counter[str]) -> dict[str, int]:
    return dict(sorted(counts.items()))


def _counts_from_timeline(timeline: list[dict[str, Any]]) -> dict[str, int]:
    return _sorted_tool_counts(Counter(str(e.get("tool") or "unknown") for e in timeline))


def _compact_tool_args(args: Any, *, max_val: int = 120) -> dict[str, Any] | None:
    """Keep scalar tool args only (no result blobs). Truncate long strings."""
    if not isinstance(args, dict) or not args:
        return None
    out: dict[str, Any] = {}
    for key, value in args.items():
        if key in _MCP_ARG_META or key == "ctx":
            continue
        if isinstance(value, str):
            out[key] = value if len(value) <= max_val else value[: max_val - 1] + "…"
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
    return out or None


def _raw_args_from_cursor_message(message: Any) -> Any:
    if not isinstance(message, dict):
        return None
    raw = message.get("args")
    if message.get("type") == "mcp" and isinstance(raw, dict):
        nested = raw.get("args")
        if nested is None:
            nested = raw.get("arguments")
        if isinstance(nested, dict):
            return nested
        return {k: v for k, v in raw.items() if k not in _MCP_ARG_META}
    return raw if isinstance(raw, dict) else None


def _timeline_entry(n: int, tool: str, args: Any = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"n": n, "tool": tool}
    compact = _compact_tool_args(args)
    if compact:
        entry["args"] = compact
    return entry


def _shorten_arg_value(value: Any) -> Any:
    """Collapse absolute sqlmesh-cache paths to repo-relative for display."""
    if not isinstance(value, str):
        return value
    marker = "/eval/cache/sqlmesh/"
    idx = value.find(marker)
    if idx >= 0:
        return value[idx + len(marker) :]
    return value


def _fmt_arg_bits(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={_shorten_arg_value(v)!r}" for k, v in args.items())


def _print_verbose_timeline(timeline: list[dict[str, Any]] | None) -> None:
    if not timeline:
        return
    print("  timeline:")
    for entry in timeline:
        if not isinstance(entry, dict):
            continue
        tool = entry.get("tool") or "?"
        n = entry.get("n", "?")
        args = entry.get("args") if isinstance(entry.get("args"), dict) else None
        if args:
            print(f"    {n}. {tool}  {_fmt_arg_bits(args)}")
        else:
            print(f"    {n}. {tool}")


def _render_timeline_report(rows: list[dict[str, Any]]) -> str:
    """Human-readable ordered tool calls for every run."""
    lines: list[str] = ["Tool call timelines", "===================", ""]
    for row in rows:
        timeline = row.get("tool_timeline")
        if not isinstance(timeline, list) or not timeline:
            continue
        header = (
            f"{row.get('task_id')} / {row.get('arm')} / "
            f"repeat={row.get('repeat')}  "
            f"passed={row.get('passed')}  status={row.get('status')}"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for entry in timeline:
            if not isinstance(entry, dict):
                continue
            tool = entry.get("tool") or "?"
            n = entry.get("n", "?")
            args = entry.get("args") if isinstance(entry.get("args"), dict) else None
            if args:
                lines.append(f"  {n}. {tool}  {_fmt_arg_bits(args)}")
            else:
                lines.append(f"  {n}. {tool}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _cursor_tool_timeline(run: Any) -> list[dict[str, Any]]:
    from cursor_sdk.types import AgentConversationTurn, ToolCallConversationStep

    try:
        turns = run.conversation()
    except Exception:  # noqa: BLE001 — conversation may be unavailable
        return []
    timeline: list[dict[str, Any]] = []
    for wrap in turns:
        turn = getattr(wrap, "turn", wrap)
        steps = getattr(turn, "steps", None)
        if steps is None and isinstance(turn, dict):
            steps = turn.get("steps") or []
        if not isinstance(turn, AgentConversationTurn) and steps is None:
            continue
        for step in steps or ():
            is_tool = (
                isinstance(step, ToolCallConversationStep)
                or getattr(step, "type", None) == "toolCall"
            )
            if not is_tool and isinstance(step, dict):
                is_tool = step.get("type") == "toolCall"
            if not is_tool:
                continue
            message = getattr(step, "message", None)
            if message is None and isinstance(step, dict):
                message = step.get("message")
            name = _normalize_tool_name(_tool_name_from_mapping(message) or "unknown")
            timeline.append(
                _timeline_entry(
                    len(timeline) + 1,
                    name,
                    _raw_args_from_cursor_message(message),
                )
            )
    return timeline


def run_cursor_agent(
    *,
    arm: str,
    prompt: str,
    model: str,
    api_key: str,
    sqlmesh: Path,
) -> tuple[str, str | None, dict[str, Any] | None, str, dict[str, int], list[dict[str, Any]]]:
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    from cursor_sdk.types import StdioMcpServerConfig

    if arm == "baseline":
        options = AgentOptions(
            model=model,
            api_key=api_key,
            tools=CURSOR_BASELINE_TOOLS,
            disallowed_tools=CURSOR_DISALLOWED,
            local=LocalAgentOptions(cwd=str(sqlmesh), setting_sources=[]),
        )
    elif arm == "codeparse":
        options = AgentOptions(
            model=model,
            api_key=api_key,
            tools=CURSOR_CODEPARSE_TOOLS,
            disallowed_tools=CURSOR_DISALLOWED,
            mcp_servers={
                "codeparse": StdioMcpServerConfig(
                    command="uv",
                    args=_mcp_server_args(sqlmesh),
                )
            },
            local=LocalAgentOptions(cwd=str(sqlmesh), setting_sources=[]),
        )
    else:
        raise ValueError(f"unknown arm: {arm}")

    with Agent.create(options) as agent:
        run = agent.send(prompt)
        result = run.wait()
        status = result.status
        text = run.text() if status == "finished" else ""
        if not text and hasattr(result, "result") and result.result:
            text = str(result.result)
        usage = _cursor_usage_dict(result.usage if result.usage is not None else run.usage)
        run_id = getattr(result, "id", None) or getattr(run, "id", None)
        timeline = _cursor_tool_timeline(run)
        tools_used = _counts_from_timeline(timeline)
        return (
            text,
            str(run_id) if run_id else None,
            usage,
            str(status),
            tools_used,
            timeline,
        )


async def _run_claude_query(
    *,
    arm: str,
    prompt: str,
    model: str,
    sqlmesh: Path,
) -> tuple[str, str | None, dict[str, Any] | None, str, dict[str, int], list[dict[str, Any]]]:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
        query,
    )

    if arm == "baseline":
        options = ClaudeAgentOptions(
            model=model,
            cwd=str(sqlmesh),
            tools=CLAUDE_BASELINE_TOOLS,
            allowed_tools=CLAUDE_BASELINE_TOOLS,
            disallowed_tools=CLAUDE_DISALLOWED_WRITE,
            permission_mode="bypassPermissions",
            setting_sources=[],
            strict_mcp_config=True,
        )
    elif arm == "codeparse":
        options = ClaudeAgentOptions(
            model=model,
            cwd=str(sqlmesh),
            tools=CLAUDE_CODEPARSE_TOOLS,
            mcp_servers={
                "codeparse": {
                    "command": "uv",
                    "args": _mcp_server_args(sqlmesh),
                }
            },
            allowed_tools=[*CLAUDE_CODEPARSE_TOOLS, "mcp__codeparse__*"],
            disallowed_tools=CLAUDE_DISALLOWED_WRITE,
            permission_mode="bypassPermissions",
            setting_sources=[],
            strict_mcp_config=True,
        )
    else:
        raise ValueError(f"unknown arm: {arm}")

    text_parts: list[str] = []
    usage: dict[str, Any] | None = None
    session_id: str | None = None
    status = "finished"
    result_text = ""
    timeline: list[dict[str, Any]] = []
    num_turns: int | None = None

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    timeline.append(
                        _timeline_entry(
                            len(timeline) + 1,
                            _normalize_tool_name(block.name or "unknown"),
                            block.input,
                        )
                    )
        elif isinstance(message, ResultMessage):
            session_id = message.session_id
            usage = _claude_usage_dict(message.usage if isinstance(message.usage, dict) else None)
            num_turns = message.num_turns
            if message.result:
                result_text = message.result
            if message.is_error or (message.subtype and message.subtype not in ("success",)):
                status = message.subtype or "error"

    if usage is not None and num_turns is not None:
        usage = {**usage, "num_turns": num_turns}

    text = result_text or "\n".join(text_parts)
    return (
        text,
        session_id,
        usage,
        status,
        _counts_from_timeline(timeline),
        timeline,
    )


def run_claude_agent(
    *,
    arm: str,
    prompt: str,
    model: str,
    sqlmesh: Path,
) -> tuple[str, str | None, dict[str, Any] | None, str, dict[str, int], list[dict[str, Any]]]:
    return asyncio.run(_run_claude_query(arm=arm, prompt=prompt, model=model, sqlmesh=sqlmesh))


def run_agent(
    *,
    provider: str,
    arm: str,
    prompt: str,
    model: str,
    api_key: str,
    sqlmesh: Path,
) -> tuple[str, str | None, dict[str, Any] | None, str, dict[str, int], list[dict[str, Any]]]:
    if provider == "cursor":
        return run_cursor_agent(
            arm=arm, prompt=prompt, model=model, api_key=api_key, sqlmesh=sqlmesh
        )
    if provider == "claude":
        return run_claude_agent(arm=arm, prompt=prompt, model=model, sqlmesh=sqlmesh)
    raise ValueError(f"unknown provider: {provider}")


def median_or_none(values: list[int]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def mean_or_none(values: list[int]) -> float | None:
    if not values:
        return None
    return float(statistics.mean(values))


def _fmt_tokens(n: float | None) -> str:
    if n is None:
        return "—"
    return f"{round(n):,}"


def _fmt_ratio(ratio: float | None) -> str:
    if ratio is None:
        return "—"
    return f"{ratio:.2f}x"


def _fmt_tools(n: float | None) -> str:
    if n is None:
        return "—"
    return str(round(n))


def _fmt_duration(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _overall_block(
    label: str,
    pass_tokens: dict[str, list[int]],
    pass_tools: dict[str, list[int]],
    *,
    agg,
) -> list[str]:
    base_tokens = agg(pass_tokens["baseline"])
    treat_tokens = agg(pass_tokens["codeparse"])
    ratio_tokens = (treat_tokens / base_tokens) if base_tokens and treat_tokens else None
    base_tools = agg(pass_tools["baseline"])
    treat_tools = agg(pass_tools["codeparse"])
    ratio_tools = (treat_tools / base_tools) if base_tools and treat_tools else None
    return [
        f"Overall {label} (of per-task passing medians)",
        f"  baseline : {_fmt_tokens(base_tokens)} tokens  ({_fmt_tools(base_tools)} tool calls)",
        f"  codeparse: {_fmt_tokens(treat_tokens)} tokens  ({_fmt_tools(treat_tools)} tool calls)",
        (
            f"  ratio    : {_fmt_ratio(ratio_tokens)} tokens  "
            f"{_fmt_ratio(ratio_tools)} tool calls  (codeparse / baseline)"
        ),
    ]


def _arm_stats(rows: list[dict[str, Any]], task_id: str, arm: str) -> dict[str, Any]:
    arm_rows = [r for r in rows if r["task_id"] == task_id and r["arm"] == arm]
    passes = [r for r in arm_rows if r["passed"]]
    pass_totals = [
        r["usage"]["total_tokens"]
        for r in passes
        if r.get("usage") and r["usage"].get("total_tokens") is not None
    ]
    all_totals = [
        r["usage"]["total_tokens"]
        for r in arm_rows
        if r.get("usage") and r["usage"].get("total_tokens") is not None
    ]
    pass_cache = [
        r["usage"]["cache_read_tokens"]
        for r in passes
        if r.get("usage") and r["usage"].get("cache_read_tokens") is not None
    ]
    pass_tools = [
        sum(int(v) for v in r["tools_used"].values())
        for r in passes
        if isinstance(r.get("tools_used"), dict)
    ]
    all_tools = [
        sum(int(v) for v in r["tools_used"].values())
        for r in arm_rows
        if isinstance(r.get("tools_used"), dict)
    ]
    return {
        "n": len(arm_rows),
        "passes": len(passes),
        "median_pass": median_or_none(pass_totals),
        "median_all": median_or_none(all_totals),
        "median_cache_pass": median_or_none(pass_cache),
        "median_tools_pass": median_or_none(pass_tools),
        "median_tools_all": median_or_none(all_tools),
    }


def summarize(rows: list[dict[str, Any]], *, elapsed_s: float | None = None) -> str:
    # Preserve run order (first appearance), not alphabetical.
    task_ids: list[str] = list(dict.fromkeys(r["task_id"] for r in rows))
    cols = ("task", "baseline", "codeparse", "ratio")
    widths = {c: len(c) for c in cols}
    table: list[dict[str, str]] = []
    overall_pass: dict[str, list[int]] = {"baseline": [], "codeparse": []}
    overall_tools: dict[str, list[int]] = {"baseline": [], "codeparse": []}

    for task_id in task_ids:
        base = _arm_stats(rows, task_id, "baseline")
        treat = _arm_stats(rows, task_id, "codeparse")
        for arm, stats in (("baseline", base), ("codeparse", treat)):
            if stats["median_pass"] is not None:
                overall_pass[arm].append(int(stats["median_pass"]))
            if stats["median_tools_pass"] is not None:
                overall_tools[arm].append(int(stats["median_tools_pass"]))

        def cell(stats: dict[str, Any]) -> str:
            score = f"{stats['passes']}/{stats['n']} pass"
            tools = _fmt_tools(
                stats["median_tools_pass"]
                if stats["median_pass"] is not None
                else stats["median_tools_all"]
            )
            if stats["median_pass"] is not None:
                tokens = _fmt_tokens(stats["median_pass"])
                cache = _fmt_tokens(stats["median_cache_pass"])
                return f"{score}  {tokens} tokens  (cache {cache}; {tools} tool calls)"
            tokens = _fmt_tokens(stats["median_all"])
            return f"{score}  {tokens} tokens*  ({tools} tool calls)"

        ratio = None
        if base["median_pass"] and treat["median_pass"]:
            ratio = treat["median_pass"] / base["median_pass"]

        row = {
            "task": task_id,
            "baseline": cell(base),
            "codeparse": cell(treat),
            "ratio": _fmt_ratio(ratio),
        }
        table.append(row)
        for c in cols:
            widths[c] = max(widths[c], len(row[c]))

    lines: list[str] = [
        "Summary",
        "=======",
        "  ".join(c.ljust(widths[c]) for c in cols),
        "  ".join("-" * widths[c] for c in cols),
    ]
    for row in table:
        lines.append("  ".join(row[c].ljust(widths[c]) for c in cols))

    lines.append("")
    lines.extend(_overall_block("median", overall_pass, overall_tools, agg=median_or_none))
    lines.extend(_overall_block("mean", overall_pass, overall_tools, agg=mean_or_none))
    if elapsed_s is not None:
        lines.append(f"  elapsed  : {_fmt_duration(elapsed_s)}")
    return "\n".join(lines) + "\n"


def select_tasks(
    catalog: dict[str, Any],
    *,
    task_ids: list[str] | None,
) -> list[dict[str, Any]]:
    tasks = catalog["tasks"]
    if task_ids:
        wanted = set(task_ids)
        selected = [t for t in tasks if t["id"] in wanted]
        missing = wanted - {t["id"] for t in selected}
        if missing:
            raise SystemExit(f"unknown task ids: {sorted(missing)}")
        return selected
    return tasks


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("cursor", "claude"),
        default="cursor",
        help="Agent runtime (default: cursor)",
    )
    parser.add_argument("--smoke", action="store_true", help="All tasks, one repeat each")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print per-step tool call timelines after each run",
    )
    parser.add_argument("--tasks", nargs="+", help="Task ids to run")
    parser.add_argument("--repeats", type=int, default=10, help="Repeats per arm (default 10)")
    parser.add_argument(
        "--model",
        default=None,
        help=("Model id (default: grok-4.7 for cursor, claude-opus-5-5-medium for claude)"),
    )
    return parser.parse_args(argv)


def _require_api_key(provider: str) -> str:
    if provider == "cursor":
        key = os.environ.get("CURSOR_API_KEY", "").strip()
        if not key:
            print(
                "CURSOR_API_KEY is required (set it in .env or the environment)",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return key
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print(
            "ANTHROPIC_API_KEY is required (set it in .env or the environment)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return key


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    provider = args.provider
    model = args.model or DEFAULT_MODELS[provider]
    api_key = _require_api_key(provider)

    catalog = _load_tasks()
    sqlmesh = ensure_sqlmesh(catalog["sha"], catalog["repo"])
    tasks = select_tasks(catalog, task_ids=args.tasks)
    repeats = 1 if args.smoke else args.repeats
    arms = ("baseline", "codeparse")

    index_sqlmesh(sqlmesh)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{stamp}.json"
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()

    print(f"provider={provider} model={model}")

    for task in tasks:
        for arm in arms:
            for repeat in range(repeats):
                prompt = build_prompt(task, arm=arm)
                print(f"RUN {task['id']} provider={provider} arm={arm} repeat={repeat}")
                try:
                    text, run_id, usage, status, tools_used, tool_timeline = run_agent(
                        provider=provider,
                        arm=arm,
                        prompt=prompt,
                        model=model,
                        api_key=api_key,
                        sqlmesh=sqlmesh,
                    )
                except Exception as exc:  # noqa: BLE001 — keep going
                    text, run_id, usage, status, tools_used, tool_timeline = (
                        "",
                        None,
                        None,
                        f"error:{exc}",
                        None,
                        None,
                    )
                passed, missing = grade(
                    text,
                    task.get("must_contain", []),
                    task.get("must_contain_any"),
                )
                row = {
                    "provider": provider,
                    "task_id": task["id"],
                    "arm": arm,
                    "repeat": repeat,
                    "passed": passed,
                    "missing": missing,
                    "status": status,
                    "run_id": run_id,
                    "usage": usage,
                    "tools_used": tools_used,
                    "tool_timeline": tool_timeline,
                    "answer": text,
                    "model": model,
                    "sqlmesh_sha": catalog["sha"],
                }
                rows.append(row)
                print(
                    f"  status={status} passed={passed} "
                    f"total={None if not usage else usage.get('total_tokens')} "
                    f"tools_used={tools_used} "
                    f"missing={missing}"
                )
                if args.verbose:
                    _print_verbose_timeline(tool_timeline)
        print()

    out_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")
    summary = summarize(rows, elapsed_s=time.perf_counter() - started)
    summary_path = out_path.with_suffix(".summary.txt")
    summary_path.write_text(summary, encoding="utf-8")
    print(f"Wrote {summary_path}")
    timeline_path = out_path.with_suffix(".timeline.txt")
    timeline_path.write_text(_render_timeline_report(rows), encoding="utf-8")
    print(f"Wrote {timeline_path}")
    print()
    print(summary, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
