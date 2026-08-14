---
description: Start the Atlas local server so memory files can be edited in place (needed because static HTML can't write to disk).
argument-hint: "[--port N] [--no-open] [--refresh SECONDS]"
allowed-tools: Bash(python3:*)
---

Start the Atlas edit server.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/server.py"
```

Pass through anything in `$ARGUMENTS`: `--port N`, `--no-open`, `--refresh SECONDS`
(0 disables periodic dashboard rescans).

This is a **local, foreground process** — it keeps running until interrupted
(Ctrl-C) or the shell closes. Run it with `run_in_background: true` and tell
the user how to stop it (`Ctrl-C` in that terminal, or `pkill -f server.py`
if run in the background).

What this unlocks over the static `/atlas` dashboard: memory files under the
**Context** tab become editable in place, with a `.bak` kept on every save.
Everything else in the dashboard is unchanged.

Explain plainly: it binds to `127.0.0.1` only (not reachable from the
network) and every request requires a per-run token embedded in the URL it
prints — nothing else on the machine can drive it without that token.
