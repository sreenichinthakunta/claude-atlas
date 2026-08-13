# Claude Atlas

Folder-structure navigation for your Claude **chats** and **code projects**, with a
right-side panel visualizing how each Claude model is consuming tokens.

## What this is (and the one thing it can't be)

Claude Code plugins are made of commands, agents, skills, hooks, and MCP servers.
**None of those can draw a persistent panel inside the terminal window** — plugins
cannot modify Claude Code's UI chrome. So the right-side token panel lives where it
can actually exist:

| Surface | What you get |
|---|---|
| **HTML dashboard** (`/atlas`) | Three-column layout: nav tree on the left, detail in the middle, **token panel pinned right**. This is the real deliverable. |
| **Terminal report** (`/atlas-tokens`) | Same numbers, rendered as bars in the terminal. |
| **Statusline** (opt-in) | One live line in Claude Code showing the current session's tokens, cache hit rate, and cost. |

Everything reads your local `~/.claude/projects/*.jsonl` transcripts. Nothing is
uploaded anywhere.

## Install

```bash
/plugin marketplace add sreenichinthakunta/claude-atlas
```

```bash
/plugin install claude-atlas@sreeni-plugins
```

Requires Python 3.9+ (standard library only — no pip installs).

## Commands

| Command | Does |
|---|---|
| `/atlas` | Build the dashboard and open it. `--no-tree` skips the filesystem walk; `--no-open` just prints the path. |
| `/atlas-tokens [model\|project\|session]` | Terminal breakdown with bars. |
| `/atlas-tree [project]` | Folder structure + sessions for one project. |

## The dashboard

**Left — navigation.** Two trees: *Chats* (project → session, each with its token
count) and *Code Projects* (the actual on-disk folder structure). Twisties expand
without changing selection, so you can browse and compare.

**Middle — detail.** Sortable tables of projects / sessions / tool calls. Rows are
clickable and drive the right panel.

**Right — token consumption.** Updates with whatever you select:

- composition donut (input / output / cache read / cache write)
- per-model bars, each internally stacked by component
- usage-over-time area chart
- cache hit-rate meter

### The Tokens ⇄ Cost toggle matters more than it sounds

On a real workload, cache reads are typically **~97% of all tokens** — a raw token
chart is one giant slice that tells you nothing. Cache reads bill at ~0.1× the input
rate, so the *cost* picture is completely different. On the scan used to build this:

| | share of tokens | share of cost |
|---|---:|---:|
| Cache read | 96.7% | 66.2% |
| Cache write | 3.1% | 26.8% |
| Output | 0.2% | **6.9%** |
| Input | <0.1% | 0.1% |

Output is a rounding error by token count and a meaningful line item by cost. Flip
the toggle before drawing conclusions.

## Statusline (optional)

Adds a live readout of the **current** session. In `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/plugins/marketplaces/sreeni-plugins/plugins/claude-atlas/scripts/statusline.py"
  }
}
```

Renders as:

```
⛁ 3.5M  ↑405.4K  ↓36.6K  ⚡88%  ▁▁▇▂  ~$5.00  · Opus 5
```

total · input+cache-write · output · cache hit rate · composition bar · est. cost · model.
It prints nothing on any error rather than corrupting your status bar. Confirm the
path above matches where the plugin actually installed.

## Pricing and cost accuracy

Every dollar figure is an **estimate**, not a bill. Rates live in `pricing.json`
(USD per million tokens); cache reads bill at `cache_read_multiplier` × the input
rate and writes at `cache_write_multiplier` ×. Defaults use the 5-minute cache
write rate (1.25×) — change it to `2.0` if you rely on the 1-hour TTL. Unknown or
newly released models fall back by tier (`opus` / `sonnet` / `haiku`) rather than
silently costing zero. Edit the file freely; it's read at scan time.

## Implementation notes

Two things here are easy to get wrong, and both were verified against real transcripts:

- **Usage blocks are duplicated.** Claude Code writes one assistant record per
  content block, each carrying an *identical* `usage` object. Summing them naively
  inflates totals — measured at **1.8×** on a sample transcript. The collector
  de-duplicates by `message.id`.
- **A session's `cwd` is not stable.** Transcripts record whatever directory the
  session was in at the time; one real transcript here held five distinct values
  (worktrees and `/tmp` checkouts). Taking the first-seen value mislabels the
  project, so the collector takes the *modal* value pooled across the project.

Performance: ~500 MB of transcripts scan in about **1.5s**, because lines are
filtered by cheap substring checks before any JSON parsing, and records above
500 KB are never parsed (a multi-megabyte tool result can contain the literal
text `"usage"` without being an assistant record).

## Layout

```
plugins/claude-atlas/
├── .claude-plugin/plugin.json
├── commands/          atlas.md · atlas-tokens.md · atlas-tree.md
├── scripts/
│   ├── collect.py     transcripts + file tree → JSON
│   ├── dashboard.py   JSON → self-contained HTML
│   ├── report.py      JSON → terminal bars
│   └── statusline.py  live current-session line
├── pricing.json
└── README.md
```

`collect.py` is usable on its own if you want the raw data:

```bash
python3 scripts/collect.py --out usage.json
```
