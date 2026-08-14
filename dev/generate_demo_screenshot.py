#!/usr/bin/env python3
"""Dev-only tool: build a dashboard from entirely synthetic data, for taking
a README screenshot without exposing any real project names, session
titles, or dollar amounts.

Not part of the shipped plugin -- lives at the repo root, outside
plugins/claude-atlas/, so it's never installed to a user's machine.

Usage:
    python3 dev/generate_demo_screenshot.py [--out path.html]

The synthetic transcripts are run through the real collect.py pipeline (not
hand-built JSON), so the demo data is schema-correct by construction and
won't drift out of sync with the real collector.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugins" / "claude-atlas" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import collect  # noqa: E402

random.seed(7)  # deterministic demo data across regenerations

MODELS = ["claude-opus-5", "claude-opus-4-8", "claude-sonnet-5"]

PROJECTS = [
    {
        "id": "acme-webapp",
        "path_name": "acme-webapp",
        "files": {
            "src/app.py": "print('hello')\n",
            "src/routes/auth.py": "# auth routes\n",
            "src/routes/billing.py": "# billing routes\n",
            "tests/test_auth.py": "def test_login(): ...\n",
            "README.md": "# Acme Webapp\n",
            "package.json": '{"name":"acme-webapp"}\n',
        },
        "sessions": [
            {"title": "Set up CI pipeline", "turns": 42, "model": MODELS[0],
             "heavy": True, "thinking": 0.55, "avg_out": 700},
            {"title": "Fix flaky login test", "turns": 12, "model": MODELS[1],
             "heavy": False, "thinking": 0.15, "avg_out": 220},
            {"title": "Explain the billing webhook flow", "turns": 6, "model": MODELS[0],
             "heavy": False, "thinking": 0.10, "avg_out": 180, "fast": True},
            {"title": "Add dark mode toggle", "turns": 65, "model": MODELS[0],
             "heavy": True, "thinking": 0.50, "avg_out": 650},
        ],
    },
    {
        "id": "internal-tools",
        "path_name": "internal-tools",
        "files": {
            "cli/main.go": "package main\n",
            "cli/commands/deploy.go": "// deploy command\n",
            "docs/runbook.md": "# Runbook\n",
        },
        "sessions": [
            {"title": "Investigate memory leak in worker pool", "turns": 88, "model": MODELS[0],
             "heavy": True, "thinking": 0.60, "avg_out": 800},
            {"title": "Summarize last week's deploy logs", "turns": 8, "model": MODELS[1],
             "heavy": False, "thinking": 0.05, "avg_out": 150},
            {"title": "Migrate config loader to new schema", "turns": 30, "model": MODELS[0],
             "heavy": True, "thinking": 0.40, "avg_out": 500},
        ],
    },
]


def content_blocks(n_tools, thinking):
    blocks = []
    if thinking:
        blocks.append({"type": "thinking", "thinking": ""})
    tool_pool = ["Bash", "Edit", "Read", "Grep", "Write"]
    for _ in range(n_tools):
        blocks.append({"type": "tool_use", "name": random.choice(tool_pool)})
    blocks.append({"type": "text", "text": "ok"})
    return blocks


def make_transcript(path: Path, cwd: str, spec: dict, day_offset: int) -> None:
    ts_base = datetime.now(timezone.utc) - timedelta(days=day_offset,
                                                       hours=random.randint(0, 20))
    lines = []
    for i in range(spec["turns"]):
        ts = (ts_base + timedelta(minutes=i * 3)).isoformat().replace("+00:00", "Z")
        is_fast = spec.get("fast") and i % 5 == 0
        n_tools = random.randint(0, 3) if spec["heavy"] else random.randint(0, 1)
        thinking = random.random() < spec["thinking"]
        out = int(spec["avg_out"] * random.uniform(0.6, 1.4))
        cw1 = random.randint(200, 2000)
        rec = {
            "type": "assistant", "timestamp": ts, "cwd": cwd, "gitBranch": "main",
            "message": {
                "id": f"msg_{path.stem}_{i}", "model": spec["model"],
                "stop_reason": "tool_use" if n_tools else "end_turn",
                "content": content_blocks(n_tools, thinking),
                "usage": {
                    "input_tokens": random.randint(50, 400), "output_tokens": out,
                    "cache_read_input_tokens": random.randint(1000, 20000),
                    "cache_creation_input_tokens": cw1,
                    "cache_creation": {"ephemeral_1h_input_tokens": cw1,
                                       "ephemeral_5m_input_tokens": 0},
                    "speed": "fast" if is_fast else "standard",
                    "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
                },
            },
        }
        lines.append(json.dumps(rec, separators=(",", ":")))
        lines.append(json.dumps({"type": "user", "timestamp": ts}, separators=(",", ":")))
    lines.append(json.dumps({"type": "custom-title", "customTitle": spec["title"]},
                             separators=(",", ":")))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(tmp: Path) -> Path:
    projects_root = tmp / "projects"
    projects_root.mkdir()
    for proj in PROJECTS:
        real_dir = tmp / "workspace" / proj["path_name"]
        for rel, content in proj["files"].items():
            f = real_dir / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content, encoding="utf-8")

        proj_dir = projects_root / f"-Users-demo-{proj['id']}"
        proj_dir.mkdir()
        for i, sess in enumerate(proj["sessions"]):
            path = proj_dir / f"demo-session-{i}.jsonl"
            make_transcript(path, str(real_dir), sess, day_offset=i * 4 + 1)
    return projects_root


def main() -> int:
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv \
        else Path(tempfile.gettempdir()) / "atlas-demo-dashboard.html"

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        projects_root = build(tmp)

        pricing = collect.load_pricing(SCRIPTS.parent)
        data = collect.build(projects_root, pricing, want_tree=True,
                             tree_depth=4, tree_budget=4000)
        data["projects_root"] = "~/.claude/projects"  # cosmetic: hide the tmp scratch path
        data_path = tmp / "demo.json"
        data_path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

        subprocess.run(
            [sys.executable, str(SCRIPTS / "dashboard.py"),
             "--data", str(data_path), "--demo", "--out", str(out)],
            check=True,
        )

    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
