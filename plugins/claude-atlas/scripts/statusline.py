#!/usr/bin/env python3
"""Claude Code statusline: live token + cost readout for the current session.

Claude Code pipes a JSON blob on stdin containing at least `transcript_path`,
`model`, and `workspace`. We re-read the tail of that transcript and print one
line. Any failure prints nothing rather than corrupting the status bar.

Enable by adding to ~/.claude/settings.json:

    "statusLine": {
      "type": "command",
      "command": "python3 ~/.claude/plugins/.../scripts/statusline.py"
    }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MAX_RECORD_BYTES = 500_000
TAIL_BYTES = 12_000_000  # enough history for a long session, bounded for speed

BLOCKS = "▁▂▃▄▅▆▇█"


def load_pricing() -> dict:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    candidates = []
    if root:
        candidates.append(Path(root) / "pricing.json")
    candidates.append(Path(__file__).resolve().parent.parent / "pricing.json")
    for p in candidates:
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except OSError:
            continue
    return {}


def abbr(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n/1e9:.2f}B"
    if n >= 1_000_000:
        return f"{n/1e6:.1f}M"
    if n >= 1_000:
        return f"{n/1e3:.1f}K"
    return str(n)


def scan(path: Path) -> tuple[dict, dict]:
    """Return (totals, per-model totals) for one transcript, deduped by msg id."""
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    models: dict[str, dict] = {}
    seen: set[str] = set()

    size = path.stat().st_size
    with open(path, "rb") as fh:
        if size > TAIL_BYTES:
            fh.seek(size - TAIL_BYTES)
            fh.readline()  # discard the partial line
        for raw in fh:
            if b'"usage"' not in raw or len(raw) > MAX_RECORD_BYTES:
                continue
            try:
                rec = json.loads(raw.decode("utf-8", "replace"))
            except (ValueError, RecursionError):
                continue
            if not isinstance(rec, dict) or rec.get("type") != "assistant":
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
            u = {
                "input": int(usage.get("input_tokens") or 0),
                "output": int(usage.get("output_tokens") or 0),
                "cache_read": int(usage.get("cache_read_input_tokens") or 0),
                "cache_creation": int(usage.get("cache_creation_input_tokens") or 0),
            }
            for k, v in u.items():
                totals[k] += v
            slot = models.setdefault(
                msg.get("model") or "unknown",
                {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0},
            )
            for k, v in u.items():
                slot[k] += v
    return totals, models


def cost(models: dict, pricing: dict) -> float:
    if not pricing:
        return 0.0
    table = pricing["models"]
    total = 0.0
    for model, u in models.items():
        r = table.get(model)
        if not r:
            low = model.lower()
            r = next(
                (table[pricing["fallback_tiers"][t]] for t in pricing["fallback_order"] if t in low),
                table[pricing["fallback_tiers"]["_default"]],
            )
        total += (
            u["input"] * r["input"]
            + u["output"] * r["output"]
            + u["cache_read"] * r["input"] * pricing["cache_read_multiplier"]
            + u["cache_creation"] * r["input"] * pricing["cache_write_multiplier"]
        ) / 1_000_000.0
    return total


def sparkbar(fractions: list[float]) -> str:
    out = []
    for f in fractions:
        idx = min(len(BLOCKS) - 1, max(0, int(f * (len(BLOCKS) - 1) + 0.5)))
        out.append(BLOCKS[idx])
    return "".join(out)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    tpath = payload.get("transcript_path")
    if not tpath:
        return 0
    path = Path(tpath).expanduser()
    if not path.is_file():
        return 0

    try:
        totals, models = scan(path)
    except OSError:
        return 0

    grand = sum(totals.values())
    if grand == 0:
        return 0

    pricing = load_pricing()
    est = cost(models, pricing)

    # Proportional bar: input / output / cache-read / cache-write.
    order = ["input", "output", "cache_read", "cache_creation"]
    bar = sparkbar([totals[k] / grand for k in order])

    model = (payload.get("model") or {}).get("display_name") or ""
    cached = totals["cache_read"] + totals["cache_creation"] + totals["input"]
    hit = (totals["cache_read"] / cached * 100) if cached else 0.0

    parts = [
        f"⛁ {abbr(grand)}",
        f"↑{abbr(totals['input'] + totals['cache_creation'])}",
        f"↓{abbr(totals['output'])}",
        f"⚡{hit:.0f}%",
        bar,
    ]
    if est >= 0.01:
        parts.append(f"~${est:,.2f}")
    if model:
        parts.append(f"· {model}")

    sys.stdout.write("  ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
