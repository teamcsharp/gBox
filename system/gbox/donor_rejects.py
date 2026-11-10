"""The persistent list of library donors that do not fit a Mercenaries title, and why.

Operator 2026-11-10: "some of these characters are a bit oversized and stretched out of proportion beyond my ability to
be able to even see them. So those are models that I don't even want to see in the rotation". Every donor writer of
the RE4 / RE5 / RE6 Switch builds (the RE5 cast and series, the RE4 cast and enemy pools, the RE6 cast / gallery /
enemy pools) reads this list before it deals: a rejected donor is never drawn again for that title and the next
candidate takes its place.

The file is `gbox-data/mercs/donor_rejects.json` (lilspark: ~/gBox/system/gbox-data/mercs/):

    {"format": 1, "updated": <epoch>,
     "titles": {"re4": {"<donor slug>": {"reason": "...", "codes": ["wide", ...], "measurement": {...},
                                         "source": {"by": "audit" | "operator", "build": ..., "slot": ..., ...},
                                         "at": <epoch>, "history": [<earlier entries>]}},
                "re5": {...}, "re6": {...}, "all": {...}},
     "audited_builds": {"<build>": {"title", "game_id", "players": {slot: {donor, label, files}},
                                    "enemies": {class: {donors, files}}, "receipts": [...]}}}

`all` holds donors refused for every title (a prop is a prop everywhere). `audited_builds` is the audit's index of
which donor stands on which slot of which build and which overlay files carry it: the operator's "swap this
character" (gbox.donor_swap) reads it to find the donor of the running round and the files to redraw.

Reads never raise: a missing or unreadable file is an empty list (the writers then deal as before). Writes are
atomic (a temp file replaced in place) under a process lock.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

FORMAT = 1
PATH = Path(__file__).resolve().parents[1] / "gbox-data" / "mercs" / "donor_rejects.json"
ENV = "GBOX_DONOR_REJECTS"            # another file (tests, an offline audit run)
TITLES = ("re4", "re5", "re6")
ALL = "all"
#: game id (the catalog's Switch editions) -> MercMode title
GAME_TITLES = {"270a15eb98dab4d7": "re4", "52d15709be0fda1a": "re5", "115f9cdbba115432": "re6"}
TITLE_GAMES = {title: game_id for game_id, title in GAME_TITLES.items()}
HISTORY_MAX = 10
_LOCK = threading.Lock()


def path(override=None) -> Path:
    """The file in use: an explicit path, else $GBOX_DONOR_REJECTS, else gbox-data/mercs/donor_rejects.json."""
    if override:
        return Path(override)
    env = os.environ.get(ENV)
    return Path(env) if env else PATH


def empty() -> dict:
    return {"format": FORMAT, "updated": None, "titles": {}, "audited_builds": {}}


def load(override=None) -> dict:
    """The whole document; an empty one when the file is missing or unreadable (never raises)."""
    try:
        doc = json.loads(path(override).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty()
    if not isinstance(doc, dict):
        return empty()
    out = empty() | {k: v for k, v in doc.items() if k in ("format", "updated", "what")}
    titles = doc.get("titles") if isinstance(doc.get("titles"), dict) else {}
    out["titles"] = {str(t): {str(s): e for s, e in rows.items() if isinstance(e, dict)}
                     for t, rows in titles.items() if isinstance(rows, dict)}
    builds = doc.get("audited_builds")
    out["audited_builds"] = builds if isinstance(builds, dict) else {}
    return out


def title_of(title_or_game: str) -> str:
    """'re5' | the RE5 Switch game id -> 're5' (anything else is returned as given)."""
    return GAME_TITLES.get(str(title_or_game or ""), str(title_or_game or ""))


def _applies(entry: dict, role: str | None) -> bool:
    roles = entry.get("roles")
    return not roles or role is None or role in roles


def rejected(title: str, role: str | None = None, *, doc: dict | None = None, override=None) -> dict[str, str]:
    """{slug: reason} of the donors refused for `title` (and for every title), optionally for one role only
    ('player' | 'enemy'; an entry without `roles` refuses the donor in every role)."""
    doc = doc if doc is not None else load(override)
    title = title_of(title)
    out: dict[str, str] = {}
    for key in (ALL, title):
        for slug, entry in (doc.get("titles") or {}).get(key, {}).items():
            if _applies(entry, role):
                out[slug] = f"donor_rejects ({key}): {entry.get('reason') or 'rejected'}"
    return out


def is_rejected(title: str, slug: str, role: str | None = None, *, doc: dict | None = None, override=None) -> bool:
    return slug in rejected(title, role, doc=doc, override=override)


def entry(title: str, slug: str, *, doc: dict | None = None, override=None) -> dict | None:
    doc = doc if doc is not None else load(override)
    rows = doc.get("titles") or {}
    return (rows.get(title_of(title)) or {}).get(slug) or (rows.get(ALL) or {}).get(slug)


def _write(doc: dict, override=None) -> Path:
    target = path(override)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(doc) | {"format": FORMAT, "updated": time.time()}
    tmp = target.with_name(target.name + f".{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=False, default=str), encoding="utf-8")
    os.replace(tmp, target)
    return target


def add(title: str, slug: str, *, reason: str, source: dict, measurement: dict | None = None,
        codes: list[str] | tuple = (), roles: list[str] | tuple = (), override=None, now: float | None = None) -> dict:
    """Refuse `slug` for `title` (or ALL) and return its entry. A donor already on the list keeps its first entry's
    place; the new reason and source become current and the earlier one moves to `history` (an operator's reject
    after the audit's, say). `source` says who and where: {"by": "audit" | "operator", "build", "slot", ...}."""
    title = ALL if title == ALL else title_of(title)
    if not slug or not isinstance(slug, str):
        raise ValueError("a reject names one donor slug")
    if title != ALL and title not in TITLES:
        raise ValueError(f"unknown title {title!r}: one of {', '.join(TITLES)} or {ALL}")
    with _LOCK:
        doc = load(override)
        rows = doc["titles"].setdefault(title, {})
        old = rows.get(slug)
        new = {"reason": str(reason)[:600], "codes": sorted(set(codes)), "measurement": measurement or None,
               "source": dict(source or {}), "at": time.time() if now is None else now}
        if roles:
            new["roles"] = sorted(set(roles))
        if old:
            history = list(old.get("history") or [])
            history.append({k: v for k, v in old.items() if k != "history"})
            new["history"] = history[-HISTORY_MAX:]
        rows[slug] = new
        _write(doc, override)
    return new


def remove(title: str, slug: str, *, override=None) -> bool:
    """Take a donor off the list again (the operator changed their mind); True when it was there."""
    with _LOCK:
        doc = load(override)
        rows = doc["titles"].get(ALL if title == ALL else title_of(title)) or {}
        if slug not in rows:
            return False
        rows.pop(slug)
        _write(doc, override)
    return True


def merge(rejects: dict, builds: dict | None = None, *, override=None, replace_audit: bool = False) -> dict:
    """Write an audit's result: `rejects` {title: {slug: entry}} and its `builds` index. Operator entries are never
    dropped; with `replace_audit` the audit's own earlier entries that this run no longer flags are removed (a fit
    fix made a donor pass), otherwise they stay. Returns the written document."""
    with _LOCK:
        doc = load(override)
        for title, rows in (rejects or {}).items():
            have = doc["titles"].setdefault(title, {})
            if replace_audit:
                for slug in [s for s, e in have.items() if (e.get("source") or {}).get("by") == "audit"
                             and slug not in rows]:
                    have.pop(slug)
            for slug, new in rows.items():
                old = have.get(slug)
                if old and (old.get("source") or {}).get("by") == "operator":
                    history = list(old.get("history") or []) + [{k: v for k, v in new.items() if k != "history"}]
                    have[slug] = old | {"history": history[-HISTORY_MAX:],
                                        "measurement": old.get("measurement") or new.get("measurement")}
                    continue
                have[slug] = new
        if builds:
            doc["audited_builds"] = dict(doc.get("audited_builds") or {}) | builds
        _write(doc, override)
        return doc


def build_index(build: str, *, doc: dict | None = None, override=None) -> dict | None:
    """The audit's record of a build (its slots, donors and files), or None. A blueprint companion
    (`<build>-blueprint`) and a donor-swap variant (`<build>-fixN`) carry the donors of their source build."""
    doc = doc if doc is not None else load(override)
    builds = doc.get("audited_builds") or {}
    name = str(build or "")
    seen = set()
    while name and name not in seen:
        seen.add(name)
        if name in builds:
            return builds[name]
        if name.endswith("-blueprint"):
            name = name[:-len("-blueprint")]
            continue
        head, _, tail = name.rpartition("-fix")
        if head and tail.isdigit():
            name = head
            continue
        break
    return None


def summary(*, doc: dict | None = None, override=None) -> dict:
    """{title: count, ...} and the newest operator rejects, for status views."""
    doc = doc if doc is not None else load(override)
    rows = doc.get("titles") or {}
    newest = sorted(((e.get("at") or 0, title, slug, e) for title, entries in rows.items()
                     for slug, e in entries.items() if (e.get("source") or {}).get("by") == "operator"),
                    reverse=True)[:5]
    return {"path": str(path(override)), "updated": doc.get("updated"),
            "counts": {title: len(entries) for title, entries in rows.items()},
            "operator_recent": [{"title": t, "donor": s, "reason": e.get("reason"), "at": at}
                                for at, t, s, e in newest]}
