---
description: Start the Atlas local server for live session telemetry and editable memories, MCP config, and permissions.
argument-hint: "[--port N] [--no-open] [--refresh SECONDS]"
allowed-tools: Bash(python3:*)
---

Start the Atlas live server.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/live.py"
```

Pass through anything in `$ARGUMENTS`: `--port N`, `--no-open`, `--refresh SECONDS`
(0 disables periodic rescans of the Usage/Savings/Context/Access views; the
Live tab always polls independently every few seconds).

This is a **local, foreground process** — it keeps running until interrupted
(Ctrl-C) or the shell closes. Run it with `run_in_background: true` and tell
the user how to stop it (`Ctrl-C` in that terminal, or `pkill -f live.py`
if run in the background).

What this unlocks over the static `/atlas` dashboard:
- **Live tab**: tokens, cache hit rate, and tool calls for the session
  currently writing to a transcript, refreshed every few seconds
- **Context tab**: memory files become editable in place (with a `.bak`
  kept on every save) instead of read-only

Explain plainly: it binds to `127.0.0.1` only (not reachable from the
network) and every request requires a per-run token embedded in the URL it
prints — nothing else on the machine can drive it without that token.

Also explain what it does **not** do: it cannot show Claude's internal
reasoning or "algorithms." That isn't written anywhere on disk — thinking
text is omitted from transcripts by default. What it shows is everything
that *is* recorded: token counts, which tools ran, cache behavior, stop
reasons. Don't oversell this as more than it is.
