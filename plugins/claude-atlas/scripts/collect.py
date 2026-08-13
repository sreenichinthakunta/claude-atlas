#!/usr/bin/env python3
"""Scan Claude Code transcripts and project trees into a single JSON model.

Reads ~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl, aggregates token
usage per session / per model / per day, and walks each project's working tree
so the dashboard can render a folder structure alongside the usage data.

Transcript facts this relies on (verified against real transcripts):
  * assistant records carry message.usage with input_tokens,
    output_tokens, cache_creation_input_tokens, cache_read_input_tokens
  * the SAME usage block is repeated once per content block, so usage must be
    de-duplicated by message.id or totals inflate several times over
  * titles arrive as separate {"type": "ai-title"} / {"type": "custom-title"}
    records, not on the message itself
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# A transcript line holding an assistant record is small. Tool results can be
# tens of megabytes and may contain the literal substring '"usage"' inside
# their text payload, so we refuse to json-parse anything implausibly large.
MAX_RECORD_BYTES = 500_000

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", "dist", "build", ".DS_Store", ".idea",
    ".gradle", "target", ".terraform", ".cache", "vendor", "Pods",
    ".ruff_cache", ".tox", "coverage", ".parcel-cache", ".turbo",
}

CODE_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".rb",
    ".php", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift", ".scala", ".sh",
    ".sql", ".html", ".css", ".scss", ".vue", ".svelte", ".md", ".json",
    ".yaml", ".yml", ".toml",
}


# --------------------------------------------------------------------------
# pricing
# --------------------------------------------------------------------------

def load_pricing(plugin_root: Path) -> dict:
    path = plugin_root / "pricing.json"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def rate_for(model: str, pricing: dict) -> dict:
    """Exact match first, then a tier fallback so unreleased/renamed models
    still get a sane estimate instead of silently costing zero."""
    models = pricing["models"]
    if model in models:
        return models[model]
    low = (model or "").lower()
    for tier in pricing["fallback_order"]:
        if tier in low:
            return models[pricing["fallback_tiers"][tier]]
    return pricing["models"][pricing["fallback_tiers"]["_default"]]


def cost_of(usage: dict, model: str, pricing: dict) -> float:
    r = rate_for(model, pricing)
    read_mult = pricing["cache_read_multiplier"]
    write_mult = pricing["cache_write_multiplier"]
    inp = r["input"]
    return (
        usage["input"] * inp
        + usage["output"] * r["output"]
        + usage["cache_read"] * inp * read_mult
        + usage["cache_creation"] * inp * write_mult
    ) / 1_000_000.0


# --------------------------------------------------------------------------
# transcript parsing
# --------------------------------------------------------------------------

def blank_usage() -> dict:
    return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}


def add_usage(dst: dict, src: dict) -> None:
    for k in ("input", "output", "cache_read", "cache_creation"):
        dst[k] += src[k]


def total_of(u: dict) -> int:
    return u["input"] + u["output"] + u["cache_read"] + u["cache_creation"]


def parse_session(path: Path) -> dict | None:
    """Stream one .jsonl transcript into a session summary."""
    session = {
        "id": path.stem,
        "file": str(path),
        "size_bytes": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "title": None,
        "last_prompt": None,
        "cwd": None,
        "branch": None,
        "version": None,
        "started": None,
        "ended": None,
        "messages": {"user": 0, "assistant": 0},
        "models": {},
        "usage": blank_usage(),
        "daily": {},
        "tools": {},
    }

    seen_message_ids: set[str] = set()
    ai_title = None
    custom_title = None
    # A session can move between directories (worktrees, /tmp checkouts), so a
    # transcript may carry several distinct cwd values. Take the modal one --
    # the first-seen value is often an incidental excursion, not the project.
    cwd_counts: dict[str, int] = {}

    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None

    with fh:
        for line in fh:
            n = len(line)
            if n < 2:
                continue

            # Sample cwd by string slicing on every line -- no JSON parse, so
            # this stays cheap even on multi-hundred-MB transcripts.
            ci = line.find('"cwd":"')
            if ci != -1:
                cj = line.find('"', ci + 7)
                if cj != -1:
                    val = line[ci + 7:cj]
                    if val:
                        cwd_counts[val] = cwd_counts.get(val, 0) + 1

            has_usage = '"usage"' in line
            has_title = '"aiTitle"' in line or '"customTitle"' in line
            wants_meta = session["branch"] is None and '"gitBranch"' in line
            is_user = session["started"] is None and '"type":"user"' in line

            if not (has_usage or has_title or wants_meta or is_user):
                # Still cheap to count user turns without a full parse.
                if '"type":"user"' in line:
                    session["messages"]["user"] += 1
                continue

            if has_usage and n > MAX_RECORD_BYTES:
                continue

            try:
                rec = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(rec, dict):
                continue

            rtype = rec.get("type")

            if rtype == "ai-title":
                ai_title = rec.get("aiTitle") or ai_title
                continue
            if rtype == "custom-title":
                custom_title = rec.get("customTitle") or rec.get("title") or custom_title
                continue
            if rtype == "last-prompt":
                session["last_prompt"] = rec.get("lastPrompt") or session["last_prompt"]
                continue

            ts = rec.get("timestamp")
            if ts:
                if session["started"] is None or ts < session["started"]:
                    session["started"] = ts
                if session["ended"] is None or ts > session["ended"]:
                    session["ended"] = ts

            if session["cwd"] is None and rec.get("cwd"):
                session["cwd"] = rec["cwd"]
            if session["branch"] is None and rec.get("gitBranch"):
                session["branch"] = rec["gitBranch"]
            if session["version"] is None and rec.get("version"):
                session["version"] = rec["version"]

            if rtype == "user":
                session["messages"]["user"] += 1
                continue

            if rtype != "assistant":
                continue

            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue

            # The same assistant message is emitted once per content block,
            # each copy carrying an identical usage object. Count it once.
            mid = msg.get("id")
            if mid:
                if mid in seen_message_ids:
                    continue
                seen_message_ids.add(mid)

            session["messages"]["assistant"] += 1

            model = msg.get("model") or "unknown"
            u = {
                "input": int(usage.get("input_tokens") or 0),
                "output": int(usage.get("output_tokens") or 0),
                "cache_read": int(usage.get("cache_read_input_tokens") or 0),
                "cache_creation": int(usage.get("cache_creation_input_tokens") or 0),
            }

            add_usage(session["usage"], u)
            slot = session["models"].setdefault(
                model, {"usage": blank_usage(), "messages": 0}
            )
            add_usage(slot["usage"], u)
            slot["messages"] += 1

            if ts:
                day = ts[:10]
                d = session["daily"].setdefault(day, blank_usage())
                add_usage(d, u)

            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name") or "unknown"
                    session["tools"][name] = session["tools"].get(name, 0) + 1

    if total_of(session["usage"]) == 0 and session["messages"]["assistant"] == 0:
        return None

    if cwd_counts:
        session["cwd"] = max(cwd_counts.items(), key=lambda kv: kv[1])[0]
        session["cwd_counts"] = cwd_counts
    session["title"] = custom_title or ai_title or session["last_prompt"]
    return session


# --------------------------------------------------------------------------
# project tree
# --------------------------------------------------------------------------

def walk_tree(root: Path, max_depth: int, budget: list[int]) -> dict | None:
    if budget[0] <= 0:
        return None
    node = {"name": root.name or str(root), "type": "dir", "children": []}
    if max_depth <= 0:
        node["truncated"] = True
        return node
    try:
        entries = sorted(
            os.scandir(root), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower())
        )
    except (OSError, PermissionError):
        return node

    for entry in entries:
        if budget[0] <= 0:
            node["truncated"] = True
            break
        if entry.name.startswith(".") and entry.name not in {".claude", ".github"}:
            continue
        if entry.name in IGNORE_DIRS:
            continue
        budget[0] -= 1
        try:
            if entry.is_dir(follow_symlinks=False):
                child = walk_tree(Path(entry.path), max_depth - 1, budget)
                if child:
                    node["children"].append(child)
            elif entry.is_file(follow_symlinks=False):
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    size = 0
                node["children"].append(
                    {
                        "name": entry.name,
                        "type": "file",
                        "size": size,
                        "code": Path(entry.name).suffix.lower() in CODE_EXT,
                    }
                )
        except (OSError, PermissionError):
            continue
    return node


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def decode_project_dir(name: str) -> str:
    """Best-effort fallback when no session record carried a cwd."""
    return "/" + name.lstrip("-").replace("-", "/")


def build(projects_root: Path, pricing: dict, want_tree: bool,
          tree_depth: int, tree_budget: int) -> dict:
    projects = []

    if not projects_root.is_dir():
        return {"projects": [], "error": f"{projects_root} not found"}

    for pdir in sorted(projects_root.iterdir()):
        if not pdir.is_dir():
            continue
        sessions = []
        for f in sorted(pdir.glob("*.jsonl")):
            s = parse_session(f)
            if s:
                sessions.append(s)
        if not sessions:
            continue

        # Pick the project path by pooled frequency across every session in the
        # directory, so one session's detour can't rename the whole project.
        pooled: dict[str, int] = {}
        for s in sessions:
            for path_val, count in (s.get("cwd_counts") or {}).items():
                pooled[path_val] = pooled.get(path_val, 0) + count
        cwd = (
            max(pooled.items(), key=lambda kv: kv[1])[0]
            if pooled
            else decode_project_dir(pdir.name)
        )
        for s in sessions:
            s.pop("cwd_counts", None)

        totals = blank_usage()
        models: dict[str, dict] = {}
        daily: dict[str, dict] = {}
        tools: dict[str, int] = {}
        for s in sessions:
            add_usage(totals, s["usage"])
            for m, slot in s["models"].items():
                agg = models.setdefault(m, {"usage": blank_usage(), "messages": 0})
                add_usage(agg["usage"], slot["usage"])
                agg["messages"] += slot["messages"]
            for day, u in s["daily"].items():
                add_usage(daily.setdefault(day, blank_usage()), u)
            for name, count in s["tools"].items():
                tools[name] = tools.get(name, 0) + count
            s["cost"] = sum(
                cost_of(slot["usage"], m, pricing) for m, slot in s["models"].items()
            )
            s["total_tokens"] = total_of(s["usage"])

        sessions.sort(key=lambda s: s["mtime"], reverse=True)

        tree = None
        if want_tree and Path(cwd).is_dir():
            tree = walk_tree(Path(cwd), tree_depth, [tree_budget])

        projects.append(
            {
                "id": pdir.name,
                "path": cwd,
                "name": Path(cwd).name or cwd,
                "sessions": sessions,
                "usage": totals,
                "total_tokens": total_of(totals),
                "models": models,
                "daily": daily,
                "tools": tools,
                "cost": sum(cost_of(v["usage"], m, pricing) for m, v in models.items()),
                "tree": tree,
                "tree_available": tree is not None,
            }
        )

    projects.sort(key=lambda p: p["total_tokens"], reverse=True)

    grand = blank_usage()
    gmodels: dict[str, dict] = {}
    gdaily: dict[str, dict] = {}
    gtools: dict[str, int] = {}
    for p in projects:
        add_usage(grand, p["usage"])
        for m, slot in p["models"].items():
            agg = gmodels.setdefault(m, {"usage": blank_usage(), "messages": 0})
            add_usage(agg["usage"], slot["usage"])
            agg["messages"] += slot["messages"]
        for day, u in p["daily"].items():
            add_usage(gdaily.setdefault(day, blank_usage()), u)
        for name, count in p["tools"].items():
            gtools[name] = gtools.get(name, 0) + count

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "projects_root": str(projects_root),
        "projects": projects,
        "usage": grand,
        "total_tokens": total_of(grand),
        "models": gmodels,
        "daily": gdaily,
        "tools": gtools,
        "cost": sum(cost_of(v["usage"], m, pricing) for m, v in gmodels.items()),
        "session_count": sum(len(p["sessions"]) for p in projects),
        "pricing": pricing,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect Claude usage + project structure.")
    ap.add_argument("--out", default="-", help="output JSON path, or - for stdout")
    ap.add_argument("--projects-root", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--no-tree", action="store_true", help="skip filesystem walk")
    ap.add_argument("--tree-depth", type=int, default=4)
    ap.add_argument("--tree-budget", type=int, default=4000,
                    help="max filesystem entries per project")
    ap.add_argument("--plugin-root", default=os.environ.get("CLAUDE_PLUGIN_ROOT", ""))
    args = ap.parse_args()

    plugin_root = Path(args.plugin_root) if args.plugin_root else Path(__file__).resolve().parent.parent
    pricing = load_pricing(plugin_root)

    started = time.time()
    data = build(
        Path(args.projects_root).expanduser(),
        pricing,
        not args.no_tree,
        args.tree_depth,
        args.tree_budget,
    )
    data["scan_seconds"] = round(time.time() - started, 2)

    payload = json.dumps(data, separators=(",", ":"))
    if args.out == "-":
        sys.stdout.write(payload)
    else:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        print(
            f"{out}  ({data.get('session_count', 0)} sessions, "
            f"{data.get('total_tokens', 0):,} tokens, {data['scan_seconds']}s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
