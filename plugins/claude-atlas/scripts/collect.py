#!/usr/bin/env python3
"""Scan Claude Code transcripts and project trees into a single JSON model.

Reads ~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl, aggregates usage
per session / model / day, derives behavioural metrics, and produces
model-downgrade suggestions grounded in observable signals.

Transcript facts this relies on (all verified against real transcripts):
  * assistant records carry message.usage with input_tokens, output_tokens,
    cache_creation_input_tokens, cache_read_input_tokens
  * the SAME usage block repeats once per content block -- usage must be
    de-duplicated by message.id or totals inflate (measured 1.8x)
  * usage.cache_creation splits into ephemeral_1h / ephemeral_5m, which bill
    at different multipliers (2.0x vs 1.25x of the input rate)
  * usage.speed == "fast" marks fast-mode turns, billed at premium rates
  * thinking blocks appear in content but their text is empty by default
    (display: omitted) -- presence is a signal, length is not available
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

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

READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead", "WebFetch", "WebSearch",
              "TaskGet", "TaskList", "ListAgents", "ListSkills", "ListPlugins"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
EXEC_TOOLS = {"Bash", "BashOutput", "KillShell"}

USAGE_KEYS = ("input", "output", "cache_read", "cache_creation",
              "cache_write_1h", "cache_write_5m")


# --------------------------------------------------------------------------
# pricing
# --------------------------------------------------------------------------

def load_pricing(plugin_root: Path) -> dict:
    with open(plugin_root / "pricing.json", encoding="utf-8") as fh:
        return json.load(fh)


def rate_for(model: str, pricing: dict, fast: bool = False) -> dict:
    models = pricing["models"]
    r = models.get(model)
    if r is None:
        low = (model or "").lower()
        r = next((models[pricing["fallback_tiers"][t]]
                  for t in pricing["fallback_order"] if t in low),
                 models[pricing["fallback_tiers"]["_default"]])
    if fast:
        if "fast" in r:
            return r["fast"]
        m = pricing.get("fast_fallback_multiplier", 2.0)
        return {"input": r["input"] * m, "output": r["output"] * m}
    return r


def cost_of(u: dict, model: str, pricing: dict, fast: bool = False) -> float:
    """Cost of one usage bucket. Cache writes are billed by their actual TTL."""
    r = rate_for(model, pricing, fast)
    inp = r["input"]
    cw1 = u.get("cache_write_1h", 0)
    cw5 = u.get("cache_write_5m", 0)
    # Older scans (or odd records) may only carry the combined figure.
    leftover = max(0, u.get("cache_creation", 0) - cw1 - cw5)
    return (
        u.get("input", 0) * inp
        + u.get("output", 0) * r["output"]
        + u.get("cache_read", 0) * inp * pricing["cache_read_multiplier"]
        + cw1 * inp * pricing["cache_write_1h_multiplier"]
        + (cw5 + leftover) * inp * pricing["cache_write_5m_multiplier"]
    ) / 1_000_000.0


def model_cost(slot: dict, model: str, pricing: dict) -> float:
    return (cost_of(slot["std"], model, pricing, False)
            + cost_of(slot["fast"], model, pricing, True))


# --------------------------------------------------------------------------
# usage helpers
# --------------------------------------------------------------------------

def blank_usage() -> dict:
    return {k: 0 for k in USAGE_KEYS}


def add_usage(dst: dict, src: dict) -> None:
    for k in USAGE_KEYS:
        dst[k] += src.get(k, 0)


def total_of(u: dict) -> int:
    return (u.get("input", 0) + u.get("output", 0)
            + u.get("cache_read", 0) + u.get("cache_creation", 0))


def blank_slot() -> dict:
    return {"std": blank_usage(), "fast": blank_usage(), "messages": 0,
            "fast_messages": 0, "thinking_turns": 0}


def merge_slot(dst: dict, src: dict) -> None:
    add_usage(dst["std"], src["std"])
    add_usage(dst["fast"], src["fast"])
    dst["messages"] += src["messages"]
    dst["fast_messages"] += src["fast_messages"]
    dst["thinking_turns"] += src["thinking_turns"]


def finalize_models(models: dict, pricing: dict) -> dict:
    """Attach display usage + cost to each model slot."""
    for m, slot in models.items():
        u = blank_usage()
        add_usage(u, slot["std"])
        add_usage(u, slot["fast"])
        slot["usage"] = u
        slot["total"] = total_of(u)
        slot["cost"] = model_cost(slot, m, pricing)
    return models


# --------------------------------------------------------------------------
# recommendation engine
# --------------------------------------------------------------------------

def score_session(s: dict) -> dict:
    """Behavioural signals for one session. Always computed, never a verdict.

    Absolute thresholds don't transfer between users: someone doing long
    agentic refactors has no 'simple' sessions in absolute terms, but still has
    a cheapest quartile worth reviewing. So we record raw signals here and let
    assign_recommendations() judge each session against its own cohort.
    """
    turns = max(s["turns"], 1)
    tc = s["tool_classes"]
    tool_total = sum(tc.values()) or 1
    avg_out = s["usage"]["output"] / turns
    think_rate = s["thinking_turns"] / turns
    heavy_ratio = (tc["write"] + tc["exec"]) / tool_total

    signals = {
        "few turns": 1 - min(turns / 40.0, 1.0),
        "short replies": 1 - min(avg_out / 900.0, 1.0),
        "little reasoning": 1 - min(think_rate, 1.0),
        "read-only work": 1 - min(heavy_ratio, 1.0),
    }
    return {
        "routine": round(sum(signals.values()) / len(signals), 4),
        "signals": {k: round(v, 3) for k, v in signals.items()},
        "turns": s["turns"],
        "avg_output": round(avg_out),
        "thinking_rate": round(think_rate, 3),
        "heavy_tool_ratio": round(heavy_ratio, 3),
    }


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


def assign_recommendations(sessions: list[dict], pricing: dict) -> None:
    """Flag the sessions that look most routine *relative to this user's own work*.

    Judged against the user's own distribution rather than fixed thresholds, so
    the feature stays useful for heavy agentic users (who have no absolutely
    simple sessions) without spraying false positives at light users.
    """
    ranks = pricing["tier_rank"]
    for s in sessions:
        s["recommendation"] = None

    candidates = [
        s for s in sessions
        if s["turns"] >= 3
        and s["cost"] >= 0.25
        and ranks.get(s["primary_model"], 2) > 2
    ]
    if not candidates:
        return

    # Adaptive thinking fires on most Opus turns regardless of difficulty, so an
    # absolute thinking threshold disqualifies everything for a heavy user. Judge
    # reasoning against this user's own median instead; keep heavy edit/exec work
    # as a genuine absolute disqualifier, since that reflects the task, not config.
    med_think = _percentile([s["score"]["thinking_rate"] for s in candidates], 0.50)
    think_ceiling = med_think + 0.05

    eligible = [
        s for s in candidates
        if s["score"]["heavy_tool_ratio"] <= 0.65
        and s["score"]["thinking_rate"] <= think_ceiling
    ]
    if not eligible:
        return

    scores = [s["score"]["routine"] for s in eligible]
    cut = _percentile(scores, 0.35) if len(eligible) >= 6 else 0.0

    for s in eligible:
        sc = s["score"]
        if sc["routine"] < cut:
            continue

        # Only claim a reason the metrics actually support -- comparative claims
        # are stated as comparative. If nothing is truthfully sayable, skip.
        reasons = []
        if sc["thinking_rate"] <= 0.20:
            reasons.append(f"reasoning on only {sc['thinking_rate']*100:.0f}% of turns")
        elif sc["thinking_rate"] < med_think - 0.02:
            reasons.append(f"reasoning on {sc['thinking_rate']*100:.0f}% of turns, "
                           f"below your {med_think*100:.0f}% median")
        if sc["heavy_tool_ratio"] <= 0.30:
            reasons.append(f"{(1-sc['heavy_tool_ratio'])*100:.0f}% read-only tool use")
        if sc["avg_output"] <= 450:
            reasons.append(f"short replies (~{sc['avg_output']} output tokens/turn)")
        if sc["turns"] <= 25:
            reasons.append(f"only {sc['turns']} turns")
        if not reasons:
            continue

        haiku_ok = (sc["thinking_rate"] <= 0.10 and sc["heavy_tool_ratio"] <= 0.20
                    and sc["turns"] <= 40 and sc["avg_output"] <= 500)
        tier = "haiku" if haiku_ok else "sonnet"
        target = pricing["downgrade_targets"][tier]
        if ranks.get(target, 9) >= ranks.get(s["primary_model"], 2):
            continue

        projected = sum(
            cost_of(sl["std"], target, pricing, False)
            + cost_of(sl["fast"], target, pricing, True)
            for sl in s["models"].values()
        )
        saving = s["cost"] - projected
        if saving <= 0.05:
            continue

        s["recommendation"] = {
            "target": target, "tier": tier, "from": s["primary_model"],
            "routine": sc["routine"],
            "confidence": "high" if len(reasons) >= 3 else "medium" if len(reasons) == 2 else "low",
            "current_cost": s["cost"], "projected_cost": projected,
            "saving": saving, "reasons": reasons[:3],
            "metrics": {k: sc[k] for k in
                        ("turns", "avg_output", "thinking_rate", "heavy_tool_ratio")},
        }


def compute_levers(root: dict, pricing: dict) -> list[dict]:
    """Cost levers that aren't model choice. Often the bigger lever in practice."""
    levers = []
    u = root["usage"]
    blended_in = 0.0
    tot_in_tokens = 0
    for m, slot in root["models"].items():
        w = total_of(slot["usage"])
        if w:
            blended_in += rate_for(m, pricing)["input"] * w
            tot_in_tokens += w
    rate = (blended_in / tot_in_tokens) if tot_in_tokens else 0.0

    cw1, cw5 = u["cache_write_1h"], u["cache_write_5m"]
    if cw1:
        delta = (pricing["cache_write_1h_multiplier"]
                 - pricing["cache_write_5m_multiplier"])
        levers.append({
            "id": "cache_ttl",
            "title": "1-hour cache writes",
            "amount": cw1 * rate * delta / 1e6,
            "detail": (f"{cw1/1e6:.1f}M tokens written at the 1-hour TTL "
                       f"({pricing['cache_write_1h_multiplier']}x input rate). "
                       f"The 5-minute TTL bills {pricing['cache_write_5m_multiplier']}x."),
            "actionable": False,
            "note": "Claude Code picks the TTL; shown so you can see where spend goes.",
        })

    ff = root.get("fast_finding")
    if ff:
        levers.append({
            "id": "fast_mode",
            "title": "Fast-mode premium",
            "amount": ff["premium"],
            "detail": f"{ff['turns']:,} turns ran with speed=fast, billed at premium rates.",
            "actionable": True,
            "note": "Toggle with /fast. Standard speed removes this premium entirely.",
        })

    cached_in = u["cache_read"] + u["cache_creation"] + u["input"]
    if cached_in:
        hit = u["cache_read"] / cached_in
        if hit < 0.85:
            levers.append({
                "id": "cache_hit",
                "title": "Cache hit rate",
                "amount": 0.0,
                "detail": f"{hit*100:.1f}% of input served from cache.",
                "actionable": True,
                "note": "Long-lived sessions cache better than many short ones.",
            })
    levers.sort(key=lambda x: -x["amount"])
    return levers


def fast_mode_finding(node: dict, pricing: dict) -> dict | None:
    """Fast mode bills at premium rates; quantify what it cost."""
    premium = 0.0
    turns = 0
    for m, slot in node["models"].items():
        if slot["fast_messages"] == 0:
            continue
        turns += slot["fast_messages"]
        premium += (cost_of(slot["fast"], m, pricing, True)
                    - cost_of(slot["fast"], m, pricing, False))
    if turns == 0 or premium <= 0.01:
        return None
    return {"turns": turns, "premium": premium}


# --------------------------------------------------------------------------
# transcript parsing
# --------------------------------------------------------------------------

def parse_session(path: Path) -> dict | None:
    st = path.stat()
    s = {
        "id": path.stem, "file": str(path), "size_bytes": st.st_size,
        "mtime": st.st_mtime, "title": None, "last_prompt": None,
        "cwd": None, "branch": None, "version": None,
        "started": None, "ended": None,
        "messages": {"user": 0, "assistant": 0},
        "turns": 0, "thinking_turns": 0, "fast_turns": 0,
        "models": {}, "usage": blank_usage(), "daily": {}, "hours": {},
        "tools": {}, "tool_classes": {"read": 0, "write": 0, "exec": 0, "other": 0},
        "stop_reasons": {}, "web_search": 0, "web_fetch": 0,
    }
    seen: set[str] = set()
    ai_title = custom_title = None
    cwd_counts: dict[str, int] = {}

    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None

    with fh:
        for line in fh:
            if len(line) < 2:
                continue

            ci = line.find('"cwd":"')
            if ci != -1:
                cj = line.find('"', ci + 7)
                if cj != -1 and line[ci + 7:cj]:
                    v = line[ci + 7:cj]
                    cwd_counts[v] = cwd_counts.get(v, 0) + 1

            has_usage = '"usage"' in line
            has_title = '"aiTitle"' in line or '"customTitle"' in line
            wants_meta = s["branch"] is None and '"gitBranch"' in line
            is_user = s["started"] is None and '"type":"user"' in line

            if not (has_usage or has_title or wants_meta or is_user):
                if '"type":"user"' in line:
                    s["messages"]["user"] += 1
                continue
            if has_usage and len(line) > MAX_RECORD_BYTES:
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
                s["last_prompt"] = rec.get("lastPrompt") or s["last_prompt"]
                continue

            ts = rec.get("timestamp")
            if ts:
                if s["started"] is None or ts < s["started"]:
                    s["started"] = ts
                if s["ended"] is None or ts > s["ended"]:
                    s["ended"] = ts
            if s["branch"] is None and rec.get("gitBranch"):
                s["branch"] = rec["gitBranch"]
            if s["version"] is None and rec.get("version"):
                s["version"] = rec["version"]

            if rtype == "user":
                s["messages"]["user"] += 1
                continue
            if rtype != "assistant":
                continue

            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            mid = msg.get("id")
            if mid:
                if mid in seen:
                    continue
                seen.add(mid)

            s["messages"]["assistant"] += 1
            s["turns"] += 1

            cc = usage.get("cache_creation") or {}
            u = {
                "input": int(usage.get("input_tokens") or 0),
                "output": int(usage.get("output_tokens") or 0),
                "cache_read": int(usage.get("cache_read_input_tokens") or 0),
                "cache_creation": int(usage.get("cache_creation_input_tokens") or 0),
                "cache_write_1h": int(cc.get("ephemeral_1h_input_tokens") or 0),
                "cache_write_5m": int(cc.get("ephemeral_5m_input_tokens") or 0),
            }
            fast = (usage.get("speed") == "fast")
            if fast:
                s["fast_turns"] += 1

            stu = usage.get("server_tool_use") or {}
            s["web_search"] += int(stu.get("web_search_requests") or 0)
            s["web_fetch"] += int(stu.get("web_fetch_requests") or 0)

            sr = msg.get("stop_reason") or "none"
            s["stop_reasons"][sr] = s["stop_reasons"].get(sr, 0) + 1

            model = msg.get("model") or "unknown"
            slot = s["models"].setdefault(model, blank_slot())
            add_usage(slot["fast"] if fast else slot["std"], u)
            slot["messages"] += 1
            if fast:
                slot["fast_messages"] += 1
            add_usage(s["usage"], u)

            thought = False
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "thinking":
                    thought = True
                elif bt == "tool_use":
                    name = b.get("name") or "unknown"
                    s["tools"][name] = s["tools"].get(name, 0) + 1
                    cls = ("read" if name in READ_TOOLS else
                           "write" if name in WRITE_TOOLS else
                           "exec" if name in EXEC_TOOLS else "other")
                    s["tool_classes"][cls] += 1
            if thought:
                s["thinking_turns"] += 1
                slot["thinking_turns"] += 1

            if ts:
                add_usage(s["daily"].setdefault(ts[:10], blank_usage()), u)
                try:
                    hr = int(ts[11:13])
                    s["hours"][hr] = s["hours"].get(hr, 0) + total_of(u)
                except ValueError:
                    pass

    if total_of(s["usage"]) == 0 and s["messages"]["assistant"] == 0:
        return None

    if cwd_counts:
        s["cwd"] = max(cwd_counts.items(), key=lambda kv: kv[1])[0]
        s["cwd_counts"] = cwd_counts
    s["title"] = custom_title or ai_title or s["last_prompt"]

    dur = 0.0
    if s["started"] and s["ended"]:
        try:
            a = datetime.fromisoformat(s["started"].replace("Z", "+00:00"))
            b = datetime.fromisoformat(s["ended"].replace("Z", "+00:00"))
            dur = max(0.0, (b - a).total_seconds() / 60.0)
        except ValueError:
            dur = 0.0
    s["duration_minutes"] = round(dur, 1)
    return s


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
        entries = sorted(os.scandir(root),
                         key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
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
                node["children"].append({
                    "name": entry.name, "type": "file", "size": size,
                    "code": Path(entry.name).suffix.lower() in CODE_EXT,
                })
        except (OSError, PermissionError):
            continue
    return node


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def decode_project_dir(name: str) -> str:
    return "/" + name.lstrip("-").replace("-", "/")


def roll_up(children: list[dict], pricing: dict) -> dict:
    agg = {
        "usage": blank_usage(), "models": {}, "daily": {}, "hours": {},
        "tools": {}, "tool_classes": {"read": 0, "write": 0, "exec": 0, "other": 0},
        "stop_reasons": {}, "turns": 0, "thinking_turns": 0, "fast_turns": 0,
        "web_search": 0, "web_fetch": 0, "duration_minutes": 0.0,
    }
    for c in children:
        add_usage(agg["usage"], c["usage"])
        for m, slot in c["models"].items():
            merge_slot(agg["models"].setdefault(m, blank_slot()), slot)
        for d, u in c["daily"].items():
            add_usage(agg["daily"].setdefault(d, blank_usage()), u)
        for h, v in c["hours"].items():
            agg["hours"][h] = agg["hours"].get(h, 0) + v
        for n, v in c["tools"].items():
            agg["tools"][n] = agg["tools"].get(n, 0) + v
        for k in agg["tool_classes"]:
            agg["tool_classes"][k] += c["tool_classes"][k]
        for k, v in c["stop_reasons"].items():
            agg["stop_reasons"][k] = agg["stop_reasons"].get(k, 0) + v
        for k in ("turns", "thinking_turns", "fast_turns", "web_search", "web_fetch"):
            agg[k] += c[k]
        agg["duration_minutes"] += c.get("duration_minutes", 0.0)
    finalize_models(agg["models"], pricing)
    agg["total_tokens"] = total_of(agg["usage"])
    agg["cost"] = sum(s["cost"] for s in agg["models"].values())
    agg["duration_minutes"] = round(agg["duration_minutes"], 1)
    return agg


def build(projects_root: Path, pricing: dict, want_tree: bool,
          tree_depth: int, tree_budget: int) -> dict:
    projects = []
    if not projects_root.is_dir():
        return {"projects": [], "error": f"{projects_root} not found"}

    for pdir in sorted(projects_root.iterdir()):
        if not pdir.is_dir():
            continue
        sessions = [x for x in (parse_session(f) for f in sorted(pdir.glob("*.jsonl"))) if x]
        if not sessions:
            continue

        pooled: dict[str, int] = {}
        for s in sessions:
            for k, v in (s.get("cwd_counts") or {}).items():
                pooled[k] = pooled.get(k, 0) + v
        cwd = (max(pooled.items(), key=lambda kv: kv[1])[0] if pooled
               else decode_project_dir(pdir.name))
        for s in sessions:
            s.pop("cwd_counts", None)
            finalize_models(s["models"], pricing)
            s["cost"] = sum(sl["cost"] for sl in s["models"].values())
            s["total_tokens"] = total_of(s["usage"])
            s["fast_finding"] = fast_mode_finding(s, pricing)
            s["primary_model"] = (max(s["models"].items(),
                                      key=lambda kv: kv[1]["total"])[0]
                                  if s["models"] else "unknown")
            s["score"] = score_session(s)
        sessions.sort(key=lambda x: x["mtime"], reverse=True)

        p = roll_up(sessions, pricing)
        p.update({
            "id": pdir.name, "path": cwd, "name": Path(cwd).name or cwd,
            "sessions": sessions,
            "tree": walk_tree(Path(cwd), tree_depth, [tree_budget])
                    if want_tree and Path(cwd).is_dir() else None,
        })
        p["tree_available"] = p["tree"] is not None
        p["fast_finding"] = fast_mode_finding(p, pricing)
        projects.append(p)

    projects.sort(key=lambda x: x["total_tokens"], reverse=True)

    root = roll_up(projects, pricing)
    all_sessions = [s for p in projects for s in p["sessions"]]

    # Recommendations are relative to the whole cohort, so they're assigned
    # after every session exists rather than per project.
    assign_recommendations(all_sessions, pricing)
    for p in projects:
        p["savings"] = sum(s["recommendation"]["saving"] for s in p["sessions"]
                           if s.get("recommendation"))

    recs = [s for s in all_sessions if s.get("recommendation")]
    recs.sort(key=lambda s: -s["recommendation"]["saving"])

    by_tier: dict[str, dict] = {}
    for s in recs:
        r = s["recommendation"]
        t = by_tier.setdefault(r["tier"], {"sessions": 0, "saving": 0.0, "target": r["target"]})
        t["sessions"] += 1
        t["saving"] += r["saving"]

    # fast_finding must land on root BEFORE compute_levers reads it -- evaluating
    # both inside one dict literal silently dropped the fast-mode lever.
    root["fast_finding"] = fast_mode_finding(root, pricing)

    root.update({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "projects_root": str(projects_root),
        "projects": projects,
        "session_count": len(all_sessions),
        "pricing": pricing,
        "levers": compute_levers(root, pricing),
        "recommendations": {
            "count": len(recs),
            "total_saving": sum(s["recommendation"]["saving"] for s in recs),
            "by_tier": by_tier,
            "top": [
                {"session": s["id"], "project": s["cwd"],
                 "title": s["title"] or "Untitled session", **s["recommendation"]}
                for s in recs[:25]
            ],
        },
    })
    return root


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect Claude usage + project structure.")
    ap.add_argument("--out", default="-")
    ap.add_argument("--projects-root", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--no-tree", action="store_true")
    ap.add_argument("--tree-depth", type=int, default=4)
    ap.add_argument("--tree-budget", type=int, default=4000)
    ap.add_argument("--plugin-root", default=os.environ.get("CLAUDE_PLUGIN_ROOT", ""))
    args = ap.parse_args()

    plugin_root = (Path(args.plugin_root) if args.plugin_root
                   else Path(__file__).resolve().parent.parent)
    pricing = load_pricing(plugin_root)

    t0 = time.time()
    data = build(Path(args.projects_root).expanduser(), pricing,
                 not args.no_tree, args.tree_depth, args.tree_budget)
    data["scan_seconds"] = round(time.time() - t0, 2)

    payload = json.dumps(data, separators=(",", ":"))
    if args.out == "-":
        sys.stdout.write(payload)
    else:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        rec = data.get("recommendations", {})
        print(f"{out}  ({data.get('session_count', 0)} sessions, "
              f"{data.get('total_tokens', 0):,} tokens, "
              f"~${data.get('cost', 0):,.2f}, "
              f"{rec.get('count', 0)} suggestions worth ~${rec.get('total_saving', 0):,.2f}, "
              f"{data['scan_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
