#!/usr/bin/env python3
"""Inventory the Claude Code environment: MCP servers, memories, permissions.

Everything here is read from local config Claude Code already maintains:
  ~/.claude.json                     per-project MCP + trust state
  ~/.claude/settings.json            user settings, plugins, marketplaces
  <project>/.claude/settings*.json   project + local permission rules
  <project>/.mcp.json                project-scoped MCP servers
  ~/.claude/projects/*/memory/       per-project memory files
  managed-settings.json              org policy, if present

Secrets are never emitted: env-var values in MCP configs are replaced with a
presence marker, and headers are reduced to their key names.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

HOME = Path.home()
MANAGED = [
    Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
    Path("/etc/claude-code/managed-settings.json"),
]
SECRET_HINT = re.compile(r"(key|token|secret|password|auth|credential|bearer)", re.I)

# Patterns for the memory secret-scanner. Each captures a *location*, never
# the matched text -- collect_memories() records only (file, line, pattern
# name), so a real key is flagged for the user to rotate without ever being
# read back to them, logged, or embedded in the dashboard.
SECRET_PATTERNS = [
    ("AWS Access Key",      re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Anthropic API Key",   re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}")),
    ("OpenAI-style Key",    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("GitHub Token",        re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("GitLab Token",        re.compile(r"glpat-[A-Za-z0-9\-_]{20,}")),
    ("Slack Token",         re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Private Key Block",   re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----")),
    ("Generic secret assignment", re.compile(
        r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"][A-Za-z0-9_\-/+=]{16,}['\"]")),
]


def scan_secrets(text: str, location: str) -> list[dict]:
    """Flag lines that look like a leaked credential. Never returns the match."""
    findings = []
    for i, line in enumerate(text.splitlines(), start=1):
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append({"location": location, "line": i, "pattern": name})
                break  # one flag per line is enough signal
    return findings


def read_json(p: Path) -> dict | None:
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def redact(value: str, name: str = "") -> str:
    """Never emit a secret. Report presence and length only."""
    if not isinstance(value, str):
        return "<non-string>"
    if SECRET_HINT.search(name or "") or len(value) > 40:
        return f"<set, {len(value)} chars>"
    return value


# --------------------------------------------------------------------------
# MCP
# --------------------------------------------------------------------------

def describe_server(name: str, cfg: dict, scope: str, source: str) -> dict:
    cfg = cfg if isinstance(cfg, dict) else {}
    kind = cfg.get("type") or ("url" if cfg.get("url") else "stdio" if cfg.get("command") else "unknown")
    env = cfg.get("env") or {}
    headers = cfg.get("headers") or {}
    return {
        "name": name,
        "scope": scope,
        "source": source,
        "type": kind,
        "url": cfg.get("url"),
        "command": cfg.get("command"),
        "args": cfg.get("args") or [],
        "env_keys": sorted(env.keys()),
        "env_secret_count": sum(1 for k in env if SECRET_HINT.search(k)),
        "header_keys": sorted(headers.keys()),
    }


def collect_mcp() -> dict:
    servers, notes = [], []
    root = read_json(HOME / ".claude.json") or {}

    for name, cfg in (root.get("mcpServers") or {}).items():
        servers.append(describe_server(name, cfg, "user", "~/.claude.json"))

    projects = []
    for proj_path, pcfg in (root.get("projects") or {}).items():
        if not isinstance(pcfg, dict):
            continue
        local = [describe_server(n, c, "project", "~/.claude.json → projects")
                 for n, c in (pcfg.get("mcpServers") or {}).items()]
        servers.extend(dict(s, project=proj_path) for s in local)

        mcp_file = Path(proj_path) / ".mcp.json"
        from_file = []
        fj = read_json(mcp_file)
        if fj:
            for n, c in (fj.get("mcpServers") or {}).items():
                s = describe_server(n, c, "project-file", str(mcp_file))
                s["project"] = proj_path
                from_file.append(s)
        servers.extend(from_file)

        projects.append({
            "path": proj_path,
            "exists": Path(proj_path).is_dir(),
            "trusted": bool(pcfg.get("hasTrustDialogAccepted")),
            "allowed_tools": pcfg.get("allowedTools") or [],
            "enabled_mcpjson": pcfg.get("enabledMcpjsonServers") or [],
            "disabled_mcpjson": pcfg.get("disabledMcpjsonServers") or [],
            "context_uris": pcfg.get("mcpContextUris") or [],
            "external_includes_approved": bool(pcfg.get("hasClaudeMdExternalIncludesApproved")),
            "server_count": len(local) + len(from_file),
        })

    if not servers:
        notes.append("No MCP servers configured in any scope. Plugin-provided servers "
                     "(from a plugin's .mcp.json) are listed under Plugins instead.")
    projects.sort(key=lambda p: (not p["trusted"], p["path"]))
    return {"servers": servers, "projects": projects, "notes": notes}


# --------------------------------------------------------------------------
# memories
# --------------------------------------------------------------------------

def parse_memory(path: Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                if ":" in line and not line.startswith(" "):
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            body = text[end + 4:]
    links = sorted(set(re.findall(r"\[\[([^\]]+)\]\]", text)))
    try:
        st = path.stat()
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        size, mtime = 0, 0
    return {
        "file": str(path),
        "name": meta.get("name") or path.stem,
        "description": meta.get("description") or "",
        "type": (meta.get("metadata") and "") or meta.get("type") or "",
        "links": links,
        "size": size,
        "mtime": mtime,
        "is_index": path.name.upper() == "MEMORY.md".upper(),
        "body": body.strip()[:4000],
        "raw": text[:8000],
    }


def collect_memories(projects_root: Path) -> dict:
    groups, total, orphans, secret_flags = [], 0, [], []
    if projects_root.is_dir():
        for pdir in sorted(projects_root.iterdir()):
            mem = pdir / "memory"
            if not mem.is_dir():
                continue
            files = [parse_memory(f) for f in sorted(mem.glob("*.md"))]
            if not files:
                continue
            total += len(files)
            names = {f["name"] for f in files}
            for f in files:
                for link in f["links"]:
                    if link not in names:
                        orphans.append({"from": f["name"], "to": link, "dir": str(mem)})
                secret_flags.extend(scan_secrets(f["raw"], f"{pdir.name}/{f['name']}.md"))
            index = next((f for f in files if f["is_index"]), None)
            groups.append({
                "dir": str(mem),
                "project_id": pdir.name,
                "count": len(files),
                "bytes": sum(f["size"] for f in files),
                "has_index": index is not None,
                "files": sorted(files, key=lambda f: (not f["is_index"], f["name"])),
            })
    # A global CLAUDE.md is instruction context, not a memory, but users think
    # of them together -- surface it alongside rather than hiding it.
    globals_ = []
    for cand in (HOME / ".claude" / "CLAUDE.md", HOME / ".claude" / "MEMORY.md"):
        if cand.is_file():
            g = parse_memory(cand)
            globals_.append(g)
            secret_flags.extend(scan_secrets(g["raw"], cand.name))
    groups.sort(key=lambda g: -g["count"])
    return {"groups": groups, "total": total, "globals": globals_,
            "dangling_links": orphans[:50], "secret_flags": secret_flags[:50]}


# --------------------------------------------------------------------------
# permissions / access surface
# --------------------------------------------------------------------------

def perm_rules(d: dict, source: str) -> list[dict]:
    out = []
    perms = (d or {}).get("permissions") or {}
    for kind in ("allow", "deny", "ask"):
        for rule in perms.get(kind) or []:
            tool = str(rule).split("(", 1)[0]
            out.append({"effect": kind, "rule": str(rule), "tool": tool, "source": source})
    for key in ("defaultMode", "disableBypassPermissionsMode"):
        if key in perms:
            out.append({"effect": "mode", "rule": f"{key}={perms[key]}",
                        "tool": "—", "source": source})
    return out


def collect_access(mcp: dict) -> dict:
    rules, sources = [], []

    def add(path: Path, label: str, managed: bool = False):
        d = read_json(path)
        if d is None:
            return None
        sources.append({"path": str(path), "label": label, "managed": managed,
                        "keys": sorted(d.keys())})
        rules.extend(perm_rules(d, label))
        return d

    for p in MANAGED:
        add(p, "managed (org policy)", managed=True)
    user = add(HOME / ".claude" / "settings.json", "user") or {}

    for proj in mcp["projects"]:
        base = Path(proj["path"]) / ".claude"
        add(base / "settings.json", f"project: {proj['path']}")
        add(base / "settings.local.json", f"project-local: {proj['path']}")

    hooks = []
    for src in sources:
        d = read_json(Path(src["path"])) or {}
        for event, entries in (d.get("hooks") or {}).items():
            for e in entries if isinstance(entries, list) else []:
                for h in (e.get("hooks") or []):
                    hooks.append({"event": event, "type": h.get("type"),
                                  "command": redact(str(h.get("command", "")), ""),
                                  "source": src["label"]})

    trusted = [p for p in mcp["projects"] if p["trusted"]]
    counts = {k: sum(1 for r in rules if r["effect"] == k) for k in ("allow", "deny", "ask")}

    findings = []
    if not counts["deny"]:
        findings.append({
            "level": "info",
            "text": "No deny rules configured. Claude asks before sensitive actions by "
                    "default, but explicit deny rules are the durable guardrail.",
        })
    if counts["allow"] and not counts["deny"]:
        findings.append({
            "level": "warn",
            "text": f"{counts['allow']} allow rule(s) with no matching deny rules. "
                    "Allow rules skip the confirmation prompt for those commands.",
        })
    bypass = any("bypass" in r["rule"].lower() for r in rules)
    if bypass:
        findings.append({"level": "warn", "text": "A bypass-permissions setting is present."})
    if len(trusted) > 6:
        findings.append({
            "level": "info",
            "text": f"{len(trusted)} directories are trusted. Trust is per-directory and "
                    "persists; prune ones you no longer work in.",
        })

    return {
        "rules": rules, "sources": sources, "hooks": hooks,
        "counts": counts,
        "trusted_dirs": [{"path": p["path"], "exists": p["exists"]} for p in trusted],
        "statusline": bool(user.get("statusLine")),
        "enabled_plugins": sorted((user.get("enabledPlugins") or {}).keys()),
        "marketplaces": sorted((user.get("extraKnownMarketplaces") or {}).keys()),
        "env_keys": sorted((user.get("env") or {}).keys()),
        "findings": findings,
    }


def collect(projects_root: Path | None = None) -> dict:
    root = projects_root or (HOME / ".claude" / "projects")
    mcp = collect_mcp()
    return {
        "mcp": mcp,
        "memories": collect_memories(root),
        "access": collect_access(mcp),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Inventory MCP, memories, and permissions.")
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    payload = json.dumps(collect(), separators=(",", ":"))
    if a.out == "-":
        print(payload)
    else:
        Path(a.out).expanduser().write_text(payload, encoding="utf-8")
        print(a.out)
