"""What a build changes, in plain words (#1656): the "What this changes" lines on the Mods cards, the Builds rows and the
game menu's Special builds, plus "Where to look in game".

summarize(name, game_id, meta, card, diff) -> {lines, where, status, badge, inferred, sources}

  status    recorded   - the marker (writer notes, slots and donors, cast, changes / changesets, cheats, patches,
                         compile facts, file changes) or the mod card's own description says what it does
            compared   - nothing recorded, but the build's files differ from the game's base copy (gbox.built_mods
                         base_diff: the background sizer compares each file with modbase/<game_id>/)
            no_changes - nothing recorded and every file is the stock game's: badge "No changes from the original game
                         found: this looks like a test build"
            inferred   - nothing recorded or compared; read from the build name (writer vocabularies: AUF maps and
                         bodies, ...) and the writer module's own docstring. Every such line is labelled inferred.
            unknown    - badge "Changes not recorded"

Pure: reads the marker dict, the card and the index's diff; the only file read is a writer module's docstring (parsed
with ast, never imported), cached per module.
"""
from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path

NO_CHANGES = "No changes from the original game found: this looks like a test build"
NOT_RECORDED = "Changes not recorded"
TEXT_KEYS = ("what", "what_changes", "summary", "description", "desc", "notes", "note", "changes_summary", "purpose")
WHERE_KEYS = ("where_to_look", "where", "how_to_see", "see_it", "level", "levels", "map", "maps", "stage", "mode", "menu")
MAX_LINES = 3
MAX_LEN = 220

# name prefix -> (game, the writer module whose vocabulary reads the rest of the name)
PREFIXES = {"auf": ("007 Agent Under Fire", "auf_swap")}


def _s(v, n: int = MAX_LEN) -> str:
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v if x not in (None, "", [], {}))
    elif isinstance(v, dict):
        v = ", ".join(f"{k} {x}" for k, x in v.items() if x not in (None, "", [], {}))
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    return v if len(v) <= n else v[:n - 1].rstrip() + "…"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _pairs(rows: list[dict], limit: int = 4) -> str:
    out = [f"{r.get('donor') or '?'} → {r.get('slot_name') or r.get('slot') or '?'}" for r in rows[:limit]]
    return ", ".join(out) + (f" +{len(rows) - limit} more" if len(rows) > limit else "")


# ------------------------------------------------------------------------------------------------- recorded

def recorded(name: str, meta: dict, card: dict | None) -> tuple[list[str], list[str]]:
    """(lines, sources) from what the writer and the mod card recorded."""
    from . import built_mods as BM
    from . import builds as B
    lines, sources = [], []
    for k in TEXT_KEYS:
        v = meta.get(k)
        if isinstance(v, str) and v.strip() or isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            lines.append(_s(v))
            sources.append(f"marker {k}")
            break
    rows = BM.changes_of(meta)
    if isinstance(meta.get("cast"), list):
        built = [r for r in rows if r.get("status") in ("built", "", None)]
        failed = [r for r in rows if r.get("status") and r.get("status") != "built"]
        src = f" with {meta['cast_source']}" if meta.get("cast_source") else ""
        lines.append(f"Replaces the game's cast{src}: {_plural(len(built), 'character')} swapped ({_pairs(built)})"
                     + (f"; {len(failed)} not swapped" if failed else ""))
        sources.append("marker cast")
    elif rows:
        lines.append(("Puts " if len(rows) == 1 else f"Swaps {len(rows)} characters: ") + _pairs(rows)
                     + (" in its slot" if len(rows) == 1 else ""))
        sources.append("marker slots")
    codes = B.marker_codes(meta) + B.card_codes(card)
    if codes:
        kinds = sorted({str(c.get("type") or "code") for c in codes})
        labels = [_s(c.get("label") or c.get("desc") or c.get("name") or c.get("tool") or "", 60) for c in codes]
        labels = [x for x in labels if x][:3]
        lines.append(f"Applies {_plural(len(codes), 'code')} ({', '.join(kinds)})" + (f": {'; '.join(labels)}" if labels else ""))
        sources.append("cheats / patches")
    comp = B.compile_of(meta)
    if comp:
        lines.append("Rebuilt from source" + (f" ({_s(comp.get('compiler') or comp.get('compiler_flags') or comp.get('flags'), 80)})"
                                               if comp.get("compiler") or comp.get("compiler_flags") or comp.get("flags") else ""))
        sources.append("compile")
    mods = B.modifications(meta, None, stat=False).get("files") or []
    if mods and not rows:
        named = [f"{Path(str(r['path'])).name} ({r.get('change') or 'changed'}{': ' + _s(r['what'], 60) if r.get('what') else ''})"
                 for r in mods[:3]]
        lines.append(f"Changes {_plural(len(mods), 'file')}: " + ", ".join(named) + (f" +{len(mods) - 3} more" if len(mods) > 3 else ""))
        sources.append("marker files")
    desc = (card or {}).get("desc")
    if isinstance(desc, str) and desc.strip() and not (card or {}).get("auto_registered") and not lines:
        lines.append(_s(desc))
        sources.append("mod card")
    return lines, sources


def where_of(meta: dict, recipe: dict | None = None) -> str:
    for k in WHERE_KEYS:
        v = meta.get(k)
        if v not in (None, "", [], {}):
            return _s(v, 160) if k in ("where_to_look", "where", "how_to_see", "see_it") else f"{k.replace('_', ' ')}: {_s(v, 140)}"
    from . import built_mods as BM
    slots = [r.get("slot_name") or r.get("slot") for r in BM.changes_of(meta) if r.get("slot_name") or r.get("slot")]
    inp = (recipe or {}).get("input") if isinstance((recipe or {}).get("input"), dict) else {}
    if not slots and inp.get("slot"):
        slots = [inp["slot"]]
    if slots:
        uniq = list(dict.fromkeys(str(s) for s in slots))
        return ("the " + uniq[0] + " slot") if len(uniq) == 1 else "slots: " + ", ".join(uniq[:6]) + (" …" if len(uniq) > 6 else "")
    return ""


# ------------------------------------------------------------------------------------------------- compared with the base

def compared(diff: dict | None) -> tuple[list[str], str]:
    """(lines, status) from the index's file comparison with the game's base copy; status '' when it can't tell."""
    if not isinstance(diff, dict) or not diff.get("base"):
        return [], ""
    ch, new, unv = int(diff.get("changed_n") or 0), int(diff.get("new_n") or 0), int(diff.get("unverified_n") or 0)
    if not (ch or new or unv):
        return [], "no_changes"
    out = []
    if ch or new:
        files = [f"{Path(p).name} (changed)" for p in (diff.get("changed") or [])[:3]] + \
                [f"{Path(p).name} (new)" for p in (diff.get("new") or [])[:3]]
        out.append(f"Differs from the original game in {_plural(ch + new, 'file')}: " + ", ".join(files[:4])
                   + (" …" if ch + new > 4 else ""))
    if unv:
        out.append(f"{_plural(unv, 'file')} may differ (the same size as the original, too large to compare): "
                   + ", ".join(Path(p).name for p in (diff.get("unverified") or [])[:3]))
    return out, "compared"


# ------------------------------------------------------------------------------------------------- inferred

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


@lru_cache(maxsize=64)
def writer_doc(module: str) -> str:
    """The first sentence of gbox/<module>.py's docstring (parsed, never imported); '' when there is none."""
    if not re.fullmatch(r"[a-z0-9_]{2,40}", module or ""):
        return ""
    f = Path(__file__).with_name(f"{module}.py")
    try:
        doc = ast.get_docstring(ast.parse(f.read_text(encoding="utf-8")), clean=True) or ""
    except (OSError, SyntaxError, ValueError):
        return ""
    first = re.split(r"(?<=[.!?])\s|\n\n", doc.strip(), maxsplit=1)[0]
    return _s(first, 200)


@lru_cache(maxsize=8)
def _vocab(module: str) -> dict:
    """A writer's name vocabulary: {"bodies": {token: (name, kind)}, "maps": set, "missions": set}."""
    out = {"bodies": {}, "maps": set(), "missions": set()}
    try:
        import importlib
        mod = importlib.import_module(f"gbox.{module}")
    except Exception:                                            # noqa: BLE001 - inference is best effort
        return out
    for key, v in (getattr(mod, "NAMES", None) or {}).items():
        parts = [p for p in str(key).split("_") if p != "body"]
        label = v if isinstance(v, tuple) else (str(v), "")
        for t in {"".join(parts), "".join(reversed(parts)), _norm(str(key))}:
            out["bodies"].setdefault(t, label)
    out["maps"] = {_norm(m) for m in getattr(mod, "MP_MAPS", ()) or ()}
    out["missions"] = {_norm(m) for m in (getattr(mod, "MISSION_CAST", None) or {})}
    return out


def inferred(name: str, writer: str = "") -> tuple[list[str], str]:
    """(lines, where) read from the build name and the writer's docs, each line marked inferred."""
    tokens = [t for t in re.split(r"[_\-~.]+", name.lower()) if t]
    lines, where = [], ""
    pre = PREFIXES.get(tokens[0]) if tokens else None
    if pre:
        game, module = pre
        voc = _vocab(module)
        maps = [t for t in tokens[1:] if t in voc["maps"] or re.fullmatch(r"dm\d+(4p)?", t)]
        missions = [t for t in tokens[1:] if t in voc["missions"]]
        bodies = [voc["bodies"][t] for t in tokens[1:] if t in voc["bodies"]]
        rest = [t for t in tokens[1:] if t not in maps and t not in missions and t not in voc["bodies"] and not re.fullmatch(r"[0-9a-f]{8}", t)]
        bits = []
        if maps:
            bits.append(f"multiplayer map {', '.join(maps)}")
        if missions:
            bits.append(f"mission level {', '.join(missions)}")
        if bodies:
            bits.append("characters " + " and ".join(b[0] for b in bodies))
        if rest:
            bits.append("also " + ", ".join(rest))
        lines.append(f"Inferred from the name: {game}" + (": " + "; ".join(bits) if bits else ""))
        players = [b[0] for b in bodies if len(b) > 1 and b[1] == "player"]
        if maps:
            where = f"Multiplayer > map {maps[0]}" + (f" > play as {players[0]}" if players else "")
        elif missions:
            where = f"Mission level {missions[0]}"
    doc = writer_doc(writer) or (writer_doc(pre[1]) if pre else "")
    if doc:
        lines.append(f"Inferred from the writer ({writer or pre[1]}): {doc}")
    return lines, where


# ------------------------------------------------------------------------------------------------- the summary

def summarize(name: str, game_id: str, meta: dict | None, card: dict | None = None, diff: dict | None = None,
              writer: str = "", recipe: dict | None = None) -> dict:
    meta = meta if isinstance(meta, dict) else {}
    lines, sources = recorded(name, meta, card)
    where = where_of(meta, recipe)
    where_inferred = False
    status, badge = "recorded", ""
    guess_lines, guess_where = inferred(name, writer) if not lines or not where else ([], "")
    if not lines:
        lines, status = compared(diff)
        if status == "no_changes":
            badge = NO_CHANGES
            lines = guess_lines[:1]                  # what the name says it was meant to be, under the badge
            sources = ["files compared with the game's base copy"]
        elif status == "compared":
            sources = ["files compared with the game's base copy"]
        elif guess_lines:
            lines, status, sources = guess_lines, "inferred", ["build name", "writer docs"]
        else:
            status, badge, sources = "unknown", NOT_RECORDED, []
    if not where and guess_where:
        where, where_inferred = guess_where, True
    return {"lines": [_s(x) for x in lines[:MAX_LINES]], "where": where, "where_inferred": where_inferred,
            "status": status, "badge": badge, "inferred": status == "inferred", "sources": sources}
