"""The knowledge base: field notes on how games were actually modded, written by agents for agents.

    um kb search "unreal pak mod"               # prior art before you start (local repo, or synced from GitHub)
    um kb search terraria --route loader-api    # filter by game / engine / route
    um kb show games/terraria/fal-arsenal.md
    um kb new --game "Hades II" --title "A new boon god" --from-scan "hades"   # scaffold a note, pre-filled
    um kb check knowledge/games/hades-ii/new-boon-god.md                       # validate before a PR
    um kb index                                  # regenerate knowledge/INDEX.md + index.json
    um kb sync                                   # refresh the cached copy from GitHub
    um kb pr knowledge/games/hades-ii/new-boon-god.md --yes                     # branch, commit, push to your fork, open a PR

Every note is Markdown with YAML front matter (knowledge/TEMPLATE.md). `check` enforces the schema, the
required sections, no secrets, no pasted decompiled code, no huge files. Contributions go through pull
requests: that's how one agent's hard-won gotchas reach the next one. Ask your human before `um kb pr --yes`.

Vendored into gBox: only note parsing and search are kept (see the gBox comments below).
"""
from __future__ import annotations

import re
from pathlib import Path

from .common import need

REPO = "rehan-remade/universal-modder"
ROUTES = ["data", "asset-only", "loader-api", "managed-patch", "native-hook", "reimplementation", "decomp-recomp",
          "passthrough", "emulator", "other"]
STATUSES = ["idea", "in-progress", "working", "released", "abandoned"]
PLATFORMS = ["windows", "linux", "macos", "proton", "emulator", "console", "other"]
GAME_KEYS = ["kind", "title", "game", "engine", "route", "status", "date", "agents"]
TECH_KEYS = ["kind", "title", "tags", "date", "agents"]
LIST_KEYS = ["games_also", "tools", "agents", "humans", "links", "tags"]
GAME_SECTIONS = ["setup", "route", "verification", "gotchas"]
MAX_BLOCK_WARN, MAX_BLOCK_FAIL = 60, 150
MAX_NOTE_KB, MAX_MEDIA_MB = 120, 1.5
# Notes and the index are UTF-8 with \n line ends on every OS. Without this, Windows reads and writes them in its
# ANSI code page with \r\n: the index's "·" separators come out as invalid UTF-8 and `um kb check --index` fails.
TEXT = {"encoding": "utf-8", "newline": "\n"}


# gBox: local_root / cache_root / sync / resolve_root removed (gbox.universal_modder fetches the notes itself,
# pinned to the vendored commit).


# --------------------------------------------------------------------------- notes

def parse(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    yaml = need("yaml", "pyyaml")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except (yaml.YAMLError, ValueError) as e:  # ValueError: a date YAML can't build, e.g. 2026-09-31
        return {"_yaml_error": str(e)}, m.group(2)
    return (meta if isinstance(meta, dict) else {}), m.group(2)


def notes(root: Path) -> list[tuple[Path, dict, str]]:
    out = []
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel in ("README.md", "INDEX.md", "TEMPLATE.md") or rel.startswith("engines/"):
            continue
        meta, body = parse(p)
        out.append((p, meta, body))
    return out


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "note"


def strs(v) -> list[str]:
    """A list field as text, whatever YAML made of it: an unquoted `[Cataclysm: Dark Days Ahead]` is a dict,
    `[2004]` an int, a bare `tools: Ghidra` a string."""
    if v is None or v == "":
        return []
    return [str(x) for x in (v if isinstance(v, list) else [v])]


# --------------------------------------------------------------------------- search

def _term(t: str) -> re.Pattern:
    """A search term that must start a word: "rust" finds "Rust" and "rusty", not "trust" or "frustum".
    A term that starts with punctuation (".esp", ".net") still matches anywhere, so it finds "plugin.esp"."""
    return re.compile((r"(?<![a-z0-9])" if t[:1].isalnum() else "") + re.escape(t))


def _groups(args: list[str]) -> list[list[re.Pattern]]:
    """One group per command-line argument: [term] for a word, [phrase, *words] for a quoted multi-word argument
    ("grand theft auto", "alpha test shader"). A note matches a group with the phrase or with all of its words, so a
    quoted topic query finds notes that use the words apart (a phrase alone returned nothing) without listing every
    note that has one of them. The phrase is scored as a term too, so notes with the exact phrase rank higher."""
    out = []
    for a in args:
        a = " ".join(a.lower().split())
        if a:
            out.append([_term(a)] + ([_term(w) for w in dict.fromkeys(a.split(" "))] if " " in a else []))
    return out


def search(root: Path, terms: list[str], game=None, engine=None, route=None, limit=10) -> list[dict]:
    groups = _groups(terms)
    terms = list({t.pattern: t for g in groups for t in g}.values())
    res = []
    for p, meta, body in notes(root):
        if game and slug(game) not in slug(str(meta.get("game", ""))) + " " + " ".join(slug(g) for g in strs(meta.get("games_also"))):
            continue
        if engine and str(meta.get("engine", "")).lower() != engine.lower():
            continue
        if route and str(meta.get("route", "")).lower() != route.lower():
            continue
        fields = {
            5: str(meta.get("title", "")),
            4: " ".join([str(meta.get("game", ""))] + strs(meta.get("games_also"))),
            3: " ".join(str(x) for x in [meta.get("engine", ""), meta.get("route", ""), *strs(meta.get("tags")), *strs(meta.get("tools"))]),
        }
        low = body.lower()
        text = low + "\n" + "\n".join(f.lower() for f in fields.values())
        # at least one argument must match (unquoted words stay OR-ed): a word anywhere, a quoted phrase as the
        # phrase or with all of its words
        if groups and not any(g[0].search(text) or (len(g) > 1 and all(t.search(text) for t in g[1:])) for g in groups):
            continue
        score = 0
        for t in terms:
            score += sum(w for w, f in fields.items() if t.search(f.lower()))
            score += min(5, len(t.findall(low)))
        if terms and score == 0:
            continue
        # the lines matching the most distinct terms first; sorted() is stable, so ties keep note order
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        counted = [(sum(1 for t in terms if t.search(ln.lower())), ln) for ln in lines]
        hits = [ln for n, ln in sorted((c for c in counted if c[0]), key=lambda c: -c[0])][:3]
        res.append(dict(score=score, path=p.relative_to(root).as_posix(), title=meta.get("title"), game=meta.get("game"),
                        engine=meta.get("engine"), route=meta.get("route"), status=meta.get("status"), hits=hits))
    res.sort(key=lambda r: -r["score"])
    return res[:limit]


# gBox: check_note / build_index / new_note / pr_head / open_pr / main / register removed (they write notes,
# push branches and open GitHub PRs; gBox keeps its own knowledge base and recipes).
