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
B, D, R = "\033[1m", "\033[2m", "\033[0m"
GREEN, YELLOW = "\033[32m", "\033[33m"


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
    frac = max(0.0, min(1.0, frac))
    full = int(frac * width)
    rem = (frac * width) - full
    tail = BLOCKS[int(rem * len(BLOCKS))] if full < width and rem > 0.02 else ""
    return ("█" * full + tail).ljust(width)


def section(title: str) -> None:
    print(f"\n{B}{title}{R}")
    print(f"{D}" + "─" * 74 + f"{R}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Terminal token report.")
    ap.add_argument("--data")
    ap.add_argument("--by", choices=["model", "project", "session", "savings"], default="model")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    if args.data:
        raw = Path(args.data).expanduser().read_text(encoding="utf-8")
    else:
        raw = subprocess.run(
            [sys.executable, str(here / "collect.py"), "--out", "-", "--no-tree"],
            capture_output=True, text=True, check=True).stdout
    d = json.loads(raw)

    total = d["total_tokens"] or 1
    u = d["usage"]

    section("TOTALS")
    print(f"  {d['session_count']} sessions across {len(d['projects'])} projects")
    print(f"  {abbr(total):>8} tokens      ~${d['cost']:,.2f} estimated (list price)")
    think = d["thinking_turns"] / (d["turns"] or 1) * 100
    print(f"  {d['turns']:,} turns · reasoning on {think:.0f}% · {d['fast_turns']:,} fast\n")
    for k in KEYS:
        share = u[k] / total
        print(f"  {LABEL[k]:>11}  {bar(share)} {share*100:5.1f}%  {abbr(u[k]):>8}")
    if u.get("cache_write_1h") or u.get("cache_write_5m"):
        print(f"{D}    cache writes: {abbr(u.get('cache_write_1h',0))} at 1h TTL "
              f"({d['pricing']['cache_write_1h_multiplier']}x), "
              f"{abbr(u.get('cache_write_5m',0))} at 5m ({d['pricing']['cache_write_5m_multiplier']}x){R}")

    section("BY MODEL")
    rows = sorted(((m, v) for m, v in d["models"].items()), key=lambda r: -r[1]["total"])
    mx = rows[0][1]["total"] if rows else 1
    for m, v in rows[:args.top]:
        if not v["total"]:
            continue
        fast = f"  {v['fast_messages']} fast" if v["fast_messages"] else ""
        print(f"  {m:<20} {bar(v['total']/mx, 24)} {abbr(v['total']):>8}  "
              f"${v['cost']:>10,.2f}  {v['messages']:>5} turns{fast}")

    if args.by in ("project", "session"):
        section("BY PROJECT")
        pm = d["projects"][0]["total_tokens"] if d["projects"] else 1
        for p in d["projects"][:args.top]:
            print(f"  {p['name'][:20]:<20} {bar(p['total_tokens']/(pm or 1), 24)} "
                  f"{abbr(p['total_tokens']):>8}  ${p['cost']:>10,.2f}  {len(p['sessions']):>3} sess")

    if args.by == "session":
        section("TOP SESSIONS")
        sess = sorted(((s, p) for p in d["projects"] for s in p["sessions"]),
                      key=lambda sp: -sp[0]["total_tokens"])
        sm = sess[0][0]["total_tokens"] if sess else 1
        for s, p in sess[:args.top]:
            print(f"  {(s['title'] or 'untitled')[:34]:<34} {bar(s['total_tokens']/(sm or 1), 16)} "
                  f"{abbr(s['total_tokens']):>8}  ${s['cost']:>9,.2f}")

    rec = d.get("recommendations") or {}
    if args.by == "savings" or rec.get("count"):
        section("CHEAPER-MODEL SUGGESTIONS")
        if not rec.get("count"):
            print("  No downgrade candidates. Your sessions show reasoning and edit/exec")
            print("  activity consistent with work that needs a frontier model.")
        else:
            print(f"  {GREEN}${rec['total_saving']:,.2f}{R} potential across {rec['count']} sessions "
                  f"({rec['total_saving']/(d['cost'] or 1)*100:.1f}% of spend)\n")
            for t in rec["top"][:args.top if args.by == "savings" else 5]:
                c = {"high": GREEN, "medium": "", "low": YELLOW}.get(t["confidence"], "")
                print(f"  {t['title'][:44]:<46} {GREEN}save ${t['saving']:>8,.2f}{R}")
                print(f"{D}    {t['from']} → {t['target']}   "
                      f"${t['current_cost']:,.2f} → ${t['projected_cost']:,.2f}{R}  "
                      f"{c}[{t['confidence']} confidence]{R}")
                for why in t["reasons"]:
                    print(f"{D}      · {why}{R}")
            print(f"\n{D}  These read behaviour, not answer quality. Atlas cannot tell whether a"
                  f"\n  task was hard. Treat them as prompts to check, not verdicts.{R}")

    levers = d.get("levers") or []
    if levers:
        section("WHERE ELSE THE MONEY GOES")
        for lv in levers:
            amt = f"${lv['amount']:,.2f}" if lv["amount"] else "—"
            tag = f"{GREEN}actionable{R}" if lv["actionable"] else f"{D}info{R}"
            print(f"  {lv['title']:<24} {amt:>11}  [{tag}]")
            print(f"{D}    {lv['detail']}\n    {lv['note']}{R}")

    print(f"\n{D}  Costs are estimates from pricing.json, not billed amounts.{R}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
