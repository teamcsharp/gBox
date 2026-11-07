"""The integrations box: local MCP servers registered as gBox tools.

An "integration" is a command that starts an MCP server plus the name to call it by. That is the whole model, because it
is the whole truth: REA, the Ghidra bridge and Playwright are all just argv. Keeping them in one registry means a route,
an operator, a bot or a scheduled task can all ask "what tools does this system have" and get the same answer.

Registry file: `gBox-data/integrations.json`. Entries are plain dicts:

    {"name": "rea", "command": "/path/to/rea --mcp", "kind": "mcp", "source": "npm:rea-agents@6.8.0",
     "enabled": true, "created": 1762...}

An entry can be added by name+command, or derived from a GitHub URL when a known recipe exists (no code is executed from
the URL itself; the recipe names what to install).
"""
import json
import os
import pathlib
import shutil
import time

from .mcp_stdio import McpError, McpServer

FILE_ENV = "GBOX_INTEGRATIONS"
DEFAULT_FILE = pathlib.Path.home() / "gBox" / "gBox-data" / "integrations.json"

# Recipes for repositories this system knows how to install. The key is what a paste of the repo URL matches.
RECIPES = {
    "morluto/rea": {"name": "rea", "kind": "npm", "package": "rea-agents", "start": "rea --mcp",
                    "note": "Reverse-engineer Anything: one MCP server over binaries, apps and runtimes (229 tools)"},
    "NationalSecurityAgency/ghidra": {"name": "ghidra", "kind": "local",
                                      "start": "~/reverse/ghidramcp/.venv/bin/python "
                                               "~/reverse/ghidramcp/bridge_mcp_ghidra.py",
                                      "note": "the Ghidra MCP bridge already used by this system"},
    "microsoft/playwright-mcp": {"name": "playwright", "kind": "npm", "package": "@playwright/mcp",
                                 "start": "npx -y @playwright/mcp@latest", "note": "browser automation"},
}


def path() -> pathlib.Path:
    override = os.environ.get(FILE_ENV)
    return pathlib.Path(override) if override else DEFAULT_FILE


def load() -> dict:
    """The registry as `{name: entry}`; a missing or broken file is an empty registry, not an error."""
    target = path()
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    entries = data.get("integrations") if isinstance(data, dict) else None
    if isinstance(entries, dict):
        return entries
    if isinstance(entries, list):
        return {row["name"]: row for row in entries if isinstance(row, dict) and row.get("name")}
    return {}


def save(entries: dict) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"integrations": entries}, indent=1, sort_keys=True), encoding="utf-8")


def add(name: str, command: str, *, kind: str = "mcp", source: str = "", note: str = "",
        env: dict | None = None, enabled: bool = True) -> dict:
    """Register (or replace) one integration. `command` is the argv line that starts its MCP server."""
    name = (name or "").strip()
    if not name or not command.strip():
        raise ValueError("an integration needs a name and a command")
    entries = load()
    entry = {"name": name, "command": command.strip(), "kind": kind, "source": source, "note": note,
             "enabled": bool(enabled), "created": entries.get(name, {}).get("created") or time.time(),
             "updated": time.time()}
    if env:
        entry["env"] = {str(k): str(v) for k, v in env.items()}
    entries[name] = entry
    save(entries)
    return entry


def remove(name: str) -> bool:
    entries = load()
    if name not in entries:
        return False
    del entries[name]
    save(entries)
    return True


def recipe_for(url: str) -> dict | None:
    """Match a pasted repository URL against the known recipes."""
    text = (url or "").strip().lower().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    for key, recipe in RECIPES.items():
        if key.lower() in text:
            return {**recipe, "repo": key}
    return None


def install_from_repo(url: str, *, dry_run: bool = True) -> dict:
    """Turn a pasted URL into a registered integration, using a recipe.

    Nothing is downloaded or built here: the recipe names the install that provides the server, and this records the
    command that starts it. `dry_run` reports what would be registered without writing, because a pasted URL is not
    evidence that the package is installed.
    """
    recipe = recipe_for(url)
    if recipe is None:
        return {"ok": False, "reason": "no recipe for this repository",
                "known": sorted(RECIPES), "would_register": None}
    argv = recipe.get("start") or ""
    executable = argv.split()[0] if argv else ""
    # a package installed for this system lives in its own tools directory, not on PATH: look there before saying it is
    # missing (measured: the box reported "install first" for rea while ~/gBox_alt/tools/rea held a working install)
    local = pathlib.Path.home() / "gBox_alt" / "tools" / recipe["name"] / "node_modules" / ".bin" / recipe["name"]
    if recipe.get("kind") == "npm" and local.is_file():
        argv = f"{local} {' '.join(argv.split()[1:])}".strip()
        executable = str(local)
    resolved = os.path.expanduser(executable) if executable else ""
    present = bool(resolved) and (pathlib.Path(resolved).exists() or shutil.which(executable))
    plan = {"name": recipe["name"], "command": argv, "kind": recipe.get("kind", "mcp"),
            "source": recipe.get("repo") or url, "note": recipe.get("note", "")}
    if dry_run:
        return {"ok": True, "dry_run": True, "would_register": plan, "start_present": present,
                "hint": "" if present else f"install first: {recipe.get('package') or recipe.get('note')}"}
    entry = add(**plan, enabled=present)
    return {"ok": True, "dry_run": False, "registered": entry, "start_present": present}


_CLIENTS: dict[str, McpServer] = {}


def client(name: str) -> McpServer:
    """The shared client for one integration, started on first use (servers hold state between calls)."""
    entries = load()
    entry = entries.get(name)
    if entry is None:
        raise McpError(f"no such integration: {name}")
    if not entry.get("enabled", True):
        raise McpError(f"integration is disabled: {name}")
    existing = _CLIENTS.get(name)
    if existing is None or not existing.alive():
        existing = _CLIENTS[name] = McpServer(entry["command"], name=name, env=entry.get("env"))
    return existing


def close_all() -> None:
    for server in list(_CLIENTS.values()):
        server.close()
    _CLIENTS.clear()


def catalogue(*, probe: bool = False) -> list[dict]:
    """Every registered integration with, when `probe`, whether it starts and how many tools it has."""
    rows = []
    for name, entry in sorted(load().items()):
        row = {"name": name, "command": entry.get("command"), "kind": entry.get("kind"),
               "enabled": entry.get("enabled", True), "note": entry.get("note"), "source": entry.get("source")}
        if probe and row["enabled"]:
            try:
                tools = client(name).list_tools()
                row.update({"tools": len(tools), "server": client(name).server, "ok": True})
            except McpError as exc:
                row.update({"tools": 0, "ok": False, "error": str(exc)[:200]})
        rows.append(row)
    return rows
