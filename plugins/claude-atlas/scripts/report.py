#!/usr/bin/env python3
"""Terminal token report — the in-terminal counterpart to the HTML dashboard."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BLOCKS = "▏▎▍▌▋▊▉█"
KEYS = ["input", "output", "cache_read", "cache_creation"]
LABEL = {"input": "input", "output": "output",
         "cache_read": "cache read", "cache_creation": "cache write"}


def abbr(n: float) -> str:
    n = n or 0
    if n >= 1e9:
        return f"{n/1e9:.2f}B"
    if n >= 1e6:
        return f"{n/1e6:.1f}M"
    if n >= 1e3:
        return f"{n/1e3:.1f}K"
    return str(int(n))


def bar(frac: float, width: int = 34) -> str:
    """Sub-character resolution bar so small shares stay visible."""
    frac = max(0.0, min(1.0, frac))
    full = int(frac * width)
    rem = (frac * width) - full
    tail = BLOCKS[int(rem * len(BLOCKS))] if full < width and rem > 0.02 else ""
    return ("█" * full + tail).ljust(width)


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")
    print("\033[2m" + "─" * 72 + "\033[0m")


def rate_for(model, pricing):
    models = pricing["models"]
    if model in models:
        return models[model]
    low = (model or "").lower()
    for tier in pricing["fallback_order"]:
        if tier in low:
            return models[pricing["fallback_tiers"][tier]]
    return models[pricing["fallback_tiers"]["_default"]]


def cost_of(u, model, pricing):
    r = rate_for(model, pricing)
    inp = r["input"]
    return (u["input"] * inp
            + u["output"] * r["output"]
            + u["cache_read"] * inp * pricing["cache_read_multiplier"]
            + u["cache_creation"] * inp * pricing["cache_write_multiplier"]) / 1e6


def main() -> int:
    ap = argparse.ArgumentParser(description="Terminal token report.")
    ap.add_argument("--data", help="collect.py JSON (default: run a fresh scan)")
    ap.add_argument("--by", choices=["model", "project", "session"], default="model")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    if args.data:
        raw = Path(args.data).expanduser().read_text(encoding="utf-8")
    else:
        raw = subprocess.run(
            [sys.executable, str(here / "collect.py"), "--out", "-", "--no-tree"],
            capture_output=True, text=True, check=True,
        ).stdout
    d = json.loads(raw)
    pricing = d["pricing"]

    total = d["total_tokens"] or 1
    u = d["usage"]

    section("TOTALS")
    print(f"  {d['session_count']} sessions across {len(d['projects'])} projects")
    print(f"  {abbr(total):>8} tokens      ~${d['cost']:,.2f} estimated (list price)\n")
    for k in KEYS:
        share = u[k] / total
        print(f"  {LABEL[k]:>11}  {bar(share)} {share*100:5.1f}%  {abbr(u[k]):>8}")

    section("BY MODEL")
    rows = sorted(
        ((m, v, sum(v["usage"].values()), cost_of(v["usage"], m, pricing))
         for m, v in d["models"].items()),
        key=lambda r: -r[2],
    )
    mx = rows[0][2] if rows else 1
    for m, v, tot, c in rows[:args.top]:
        if tot == 0:
            continue
        print(f"  {m:<20} {bar(tot / mx, 26)} {abbr(tot):>8}  ${c:>10,.2f}  {v['messages']:>5} msgs")

    if args.by in ("project", "session"):
        section("BY PROJECT")
        pm = d["projects"][0]["total_tokens"] if d["projects"] else 1
        for p in d["projects"][:args.top]:
            print(f"  {p['name'][:20]:<20} {bar(p['total_tokens'] / (pm or 1), 26)} "
                  f"{abbr(p['total_tokens']):>8}  ${p['cost']:>10,.2f}  {len(p['sessions']):>3} sess")

    if args.by == "session":
        section("TOP SESSIONS")
        sess = [(s, p) for p in d["projects"] for s in p["sessions"]]
        sess.sort(key=lambda sp: -sp[0]["total_tokens"])
        sm = sess[0][0]["total_tokens"] if sess else 1
        for s, p in sess[:args.top]:
            title = (s["title"] or "untitled")[:34]
            print(f"  {title:<34} {bar(s['total_tokens'] / (sm or 1), 18)} "
                  f"{abbr(s['total_tokens']):>8}  ${s['cost']:>9,.2f}")

    cached = u["cache_read"] + u["cache_creation"] + u["input"]
    if cached:
        hit = u["cache_read"] / cached * 100
        section("CACHE")
        print(f"  hit rate    {bar(hit / 100)} {hit:5.1f}%")
        print(f"\033[2m  Cache reads bill at ~{pricing['cache_read_multiplier']}x the input rate, "
              f"writes at ~{pricing['cache_write_multiplier']}x.\033[0m")

    print("\n\033[2m  Costs are estimates from pricing.json, not billed amounts.\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
