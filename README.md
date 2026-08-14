# sreeni-plugins

A Claude Code plugin marketplace.

## Install

```bash
/plugin marketplace add sreenichinthakunta/claude-atlas
```

Then install any plugin from it:

```bash
/plugin install claude-atlas@sreeni-plugins
```

Update later with `/plugin marketplace update sreeni-plugins`.

## Plugins

### [Claude Atlas](plugins/claude-atlas) · `claude-atlas`

Folder-structure navigation for your Claude **chats** and **code projects**, with a
right-side panel visualizing how each Claude model is consuming tokens.

- `/atlas` — build and open the dashboard (nav tree left, detail centre, token panel right)
- `/atlas-savings` — cheaper-model suggestions with the evidence behind each
- `/atlas-tokens [model|project|session]` — same breakdown as terminal bars
- `/atlas-tree [project]` — folder structure and sessions for one project
- optional statusline showing live tokens, cache hit rate, and estimated cost

Python 3.9+, standard library only. Reads your local `~/.claude/projects/*.jsonl`
transcripts; nothing is uploaded anywhere. See the
[plugin README](plugins/claude-atlas/README.md) for details.

## License

MIT — see [LICENSE](LICENSE).
