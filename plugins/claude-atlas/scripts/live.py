#!/usr/bin/env python3
"""Local server for Atlas: live session telemetry + editable memories.

A file:// page cannot read fresh data or write to disk, so the live view and
memory editing need a server. It binds to 127.0.0.1 only and requires a
per-run token on every API call, so nothing on your network can reach it.

What "live" can and cannot show: Claude's internal reasoning is not
observable. This tails the active transcript and reports what is actually
recorded -- tokens per turn, cache behaviour, which tools fired, stop reasons.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or HERE.parent)
PROJECTS = Path.home() / ".claude" / "projects"
MEMORY_ROOT = PROJECTS.resolve()
MAX_RECORD = 500_000
TOKEN = secrets.token_urlsafe(24)

sys.path.insert(0, str(HERE))
import inspect_env  # noqa: E402


# --------------------------------------------------------------------------
# live telemetry
# --------------------------------------------------------------------------

def newest_transcript() -> Path | None:
    best, best_m = None, 0.0
    if not PROJECTS.is_dir():
        return None
    for f in PROJECTS.glob("*/*.jsonl"):
        try:
            m = f.stat().st_mtime
        except OSError:
            continue
        if m > best_m:
            best, best_m = f, m
    return best


def tail_session(path: Path, limit: int = 60) -> dict:
    """Summarise a transcript's recent activity. Deduped by message id."""
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
              "cache_write_1h": 0, "cache_write_5m": 0}
    seen: set[str] = set()
    events: list[dict] = []
    models: dict[str, int] = {}
    turns = thinking = fast = 0

    try:
        size = path.stat().st_size
        fh = open(path, "rb")
    except OSError:
        return {"error": "unreadable"}

    with fh:
        if size > 24_000_000:
            fh.seek(size - 24_000_000)
            fh.readline()
        for raw in fh:
            if b'"usage"' not in raw or len(raw) > MAX_RECORD:
                continue
            try:
                rec = json.loads(raw.decode("utf-8", "replace"))
            except (ValueError, RecursionError):
                continue
            if not isinstance(rec, dict) or rec.get("type") != "assistant":
                continue
            msg = rec.get("message") or {}
            u = msg.get("usage") or {}
            if not u:
                continue
            mid = msg.get("id")
            if mid:
                if mid in seen:
                    continue
                seen.add(mid)
            turns += 1
            cc = u.get("cache_creation") or {}
            step = {
                "input": int(u.get("input_tokens") or 0),
                "output": int(u.get("output_tokens") or 0),
                "cache_read": int(u.get("cache_read_input_tokens") or 0),
                "cache_creation": int(u.get("cache_creation_input_tokens") or 0),
                "cache_write_1h": int(cc.get("ephemeral_1h_input_tokens") or 0),
                "cache_write_5m": int(cc.get("ephemeral_5m_input_tokens") or 0),
            }
            for k, v in step.items():
                totals[k] += v
            model = msg.get("model") or "unknown"
            models[model] = models.get(model, 0) + 1
            if u.get("speed") == "fast":
                fast += 1
            tools = [b.get("name") for b in msg.get("content") or []
                     if isinstance(b, dict) and b.get("type") == "tool_use"]
            thought = any(isinstance(b, dict) and b.get("type") == "thinking"
                          for b in msg.get("content") or [])
            if thought:
                thinking += 1
            events.append({
                "ts": rec.get("timestamp"), "model": model,
                "stop": msg.get("stop_reason"), "tools": [t for t in tools if t],
                "thinking": thought, "fast": u.get("speed") == "fast",
                "out": step["output"],
                "total": step["input"] + step["output"] + step["cache_read"] + step["cache_creation"],
            })

    return {
        "file": str(path), "session": path.stem, "project": path.parent.name,
        "totals": totals, "turns": turns, "thinking_turns": thinking,
        "fast_turns": fast, "models": models,
        "events": events[-limit:],
        "mtime": path.stat().st_mtime if path.exists() else 0,
    }


# --------------------------------------------------------------------------
# memory editing
# --------------------------------------------------------------------------

def safe_memory_path(raw: str) -> Path:
    """Resolve a client-supplied path and refuse anything outside a memory dir.

    The client is local, but a path is still untrusted input: resolve it, then
    require that it sits under ~/.claude/projects/<project>/memory/ and ends
    in .md. This blocks traversal and symlink escapes.
    """
    p = Path(raw).expanduser().resolve()
    if p.suffix.lower() != ".md":
        raise ValueError("only .md files may be written")
    try:
        rel = p.relative_to(MEMORY_ROOT)
    except ValueError:
        raise ValueError("path is outside the memory root")
    parts = rel.parts
    if len(parts) < 3 or parts[1] != "memory":
        raise ValueError("path is not inside a project memory directory")
    return p


class Handler(BaseHTTPRequestHandler):
    server_version = "ClaudeAtlas"

    def log_message(self, *a):  # keep the console clean
        pass

    def _authed(self, q) -> bool:
        return (q.get("t", [""])[0] == TOKEN
                or self.headers.get("X-Atlas-Token") == TOKEN)

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            try:
                html = Path(self.server.page).read_bytes()
            except OSError:
                return self._send(500, b"dashboard missing", "text/plain")
            return self._send(200, html, "text/html; charset=utf-8")
        if not self._authed(q):
            return self._json(403, {"error": "bad token"})
        if u.path == "/api/live":
            f = newest_transcript()
            if not f:
                return self._json(200, {"error": "no transcript found"})
            return self._json(200, tail_session(f))
        if u.path == "/api/env":
            return self._json(200, inspect_env.collect(PROJECTS))
        if u.path == "/api/memory":
            try:
                p = safe_memory_path(q.get("file", [""])[0])
                return self._json(200, {"file": str(p),
                                        "text": p.read_text(encoding="utf-8")})
            except (ValueError, OSError) as e:
                return self._json(400, {"error": str(e)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authed(q):
            return self._json(403, {"error": "bad token"})
        if u.path != "/api/memory":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                raise ValueError("payload too large")
            payload = json.loads(self.rfile.read(n) or b"{}")
            p = safe_memory_path(payload.get("file", ""))
            text = payload.get("text")
            if not isinstance(text, str):
                raise ValueError("text must be a string")
            # Keep a one-deep backup so an edit is always recoverable.
            if p.exists():
                p.with_suffix(p.suffix + ".bak").write_text(
                    p.read_text(encoding="utf-8"), encoding="utf-8")
            p.write_text(text, encoding="utf-8")
            return self._json(200, {"ok": True, "file": str(p), "bytes": len(text)})
        except (ValueError, OSError, json.JSONDecodeError) as e:
            return self._json(400, {"error": str(e)})


def build_page(out: Path, no_tree: bool) -> None:
    cmd = [sys.executable, str(HERE / "dashboard.py"), "--out", str(out)]
    if no_tree:
        cmd.append("--no-tree")
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Atlas live server.")
    ap.add_argument("--port", type=int, default=0, help="0 picks a free port")
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--no-tree", action="store_true")
    ap.add_argument("--refresh", type=int, default=180,
                    help="seconds between full rescans (0 disables)")
    args = ap.parse_args()

    page = Path.home() / ".claude" / "atlas" / "dashboard.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    build_page(page, args.no_tree)

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.page = str(page)
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/?t={TOKEN}"

    if args.refresh > 0:
        def rescan():
            while True:
                time.sleep(args.refresh)
                try:
                    build_page(page, args.no_tree)
                except Exception:
                    pass
        threading.Thread(target=rescan, daemon=True).start()

    print(f"Atlas live at {url}")
    print("  127.0.0.1 only · token required · Ctrl-C to stop")
    print(f"  full rescan every {args.refresh}s" if args.refresh else "  rescan disabled")
    if not args.no_open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
