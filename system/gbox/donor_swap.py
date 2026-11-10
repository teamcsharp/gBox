"""The operator's "this character's model is broken: swap it" for a MercMode round on a donor build.

Operator 2026-11-10: "if I had live swap, I would basically choose to swap this character to the next character mesh
because this one isn't working". A LayeredFS build is read when the title boots, so the mesh of a running round cannot
change; what the control does instead:

1. the round's player donor (and, when asked, an enemy class's donors) goes on the reject list
   (gbox.donor_rejects, source "operator"), so no writer deals it again for that title;
2. a job on the PC that plays (switch_mods op=donor_variant, off the request thread, bounded by MAX_ATTEMPTS and
   TIME_BUDGET_S) writes a variant of the round's build, `<build>-fixN` (and `<build>-fixN-blueprint` when the build
   has a blueprint companion): the build's files with that slot redrawn from the next donor that passes the fit audit
   (RE5 player slots), or put back to the native model when none passes or the title has no redraw yet (RE4: its fit is
   being rebuilt; RE6: native costumes and keep-bind donors);
3. when the job lands (switch_mods' on_accept -> `accept`), the variant supersedes its build for good
   (SUPERSEDE: every later queue entry or default build naming the old build plays the variant) and a purpose entry
   goes to the head of the host's queue: MercMode plays it at the next round boundary through the same-title
   different-build path of gbox.screensaver.round_boundary, before rounds_per_title is reached.

Status is honest at every step (`status`): queued -> building -> ready ("plays next round") -> playing, or failed
with the job's reason. Nothing here touches a running session or overwrites a build.
"""
from __future__ import annotations

import json
import random
import re
import time
import uuid
from pathlib import Path

from . import donor_rejects

STATE = "mercmode_donor_swap"        # host -> the newest swap record
SUPERSEDE = "mercmode_supersede"     # game id -> {build: the variant that replaced it}
PURPOSE = "donor_swap"               # the queue entry's purpose: allowed through before rounds_per_title
MAX_ATTEMPTS = 4                     # donors built for one slot before it goes native
MAX_RESOLVE = 24                     # library folders resolved while looking for those donors
TIME_BUDGET_S = 900.0                # the whole variant job (the tool's own limit is longer)
BLUEPRINT = "-blueprint"
FIX = re.compile(r"^(?P<base>.+?)-fix(?P<n>\d+)$")
REDRAW_TITLES = {"re5"}              # titles whose player slots are redrawn; the rest go native
NATIVE_WHY = {"re4": "RE4's donor fit is being rebuilt (re4_switch_models.fit, branch re4-donor-fit): a redraw "
                     "with today's fit is what broke this donor, so the slot plays its native model",
              "re6": "RE6 slots carry native costumes or keep-bind donors: the slot plays its native model"}
TERMINAL = {"ready", "playing", "played", "failed"}
RE5_TITLE_ID = "010018100CD46000"   # the extracted RomFS the redraw reads the slot's original archive from


class SwapError(ValueError):
    """The swap cannot be made for this round; the message says why (shown to the operator)."""


# --- names -------------------------------------------------------------------------------------------------------

def plain(build: str) -> str:
    return build[:-len(BLUEPRINT)] if build and build.endswith(BLUEPRINT) else build


def root_of(build: str) -> str:
    """`X-fix3-blueprint` -> `X`: the build a chain of variants came from."""
    name = plain(build or "")
    while (m := FIX.match(name)):
        name = m["base"]
    return name


def variant_name(build: str, existing=()) -> str:
    """The next free `<root>-fixN` for a build (its root's numbering continues: X-fix1 -> X-fix2)."""
    base = root_of(build)
    used = {int(m["n"]) for name in existing if (m := FIX.match(plain(name))) and m["base"] == base}
    current = FIX.match(plain(build or ""))
    if current and current["base"] == base:
        used.add(int(current["n"]))
    return f"{base}-fix{max(used, default=0) + 1}"


def superseded(store, game_id: str) -> dict:
    return dict(store.get(SUPERSEDE, game_id) or {})


def resolve(store, game_id: str, mod: str | None) -> str | None:
    """The build that plays for `mod` now: followed through the variants that replaced it (X -> X-fix1 -> X-fix2)."""
    if not mod:
        return mod
    table, seen, name = superseded(store, game_id), set(), mod
    while name in table and name not in seen:
        seen.add(name)
        name = table[name]
    return name


# --- which slot is the player's --------------------------------------------------------------------------------

def player_slots(title: str, entry: dict, character: str | None, costume=None) -> list[str]:
    """The slots of an audited build (`donor_rejects.build_index`) the playing character stands on."""
    players = (entry or {}).get("players") or {}
    if not character:
        return []
    name = str(character).strip()
    if title == "re5":
        return [slot for slot, row in players.items() if (row.get("label") or "").lower() == name.lower()]
    if title == "re4":
        key = {"hunk": "hunk"}.get(name.lower(), name.lower())
        return [slot for slot in players if slot == key]
    if title == "re6":
        prefix = name.lower() + "/"
        mine = sorted(slot for slot in players if slot.startswith(prefix) or slot == name.lower())
        if isinstance(costume, int):
            exact = [slot for slot in mine if slot == f"{name.lower()}/c{costume}"]
            if exact:
                return exact
        return mine
    return []


def plan(title: str, build: str, *, character: str | None, costume=None, enemy: str | None = None,
         doc: dict | None = None) -> dict:
    """What a swap of this round does: {title, build (plain), players: [{slot, donor, files}], enemies: [...]}.
    Raises SwapError when the round's build is not an audited donor build or the character has no donor slot."""
    doc = doc if doc is not None else donor_rejects.load()
    entry = donor_rejects.build_index(build, doc=doc)
    if not entry:
        raise SwapError(f"{build or 'the stock game'} is not a donor build the audit knows (python -m "
                        "gbox.donor_fit_audit --write indexes it): nothing to swap")
    slots = player_slots(title, entry, character, costume)
    players = [{"slot": s, **{k: entry["players"][s].get(k) for k in ("donor", "label", "files")}}
               for s in slots if entry["players"][s].get("donor")]
    enemies = []
    if enemy:
        rows = entry.get("enemies") or {}
        if enemy in rows:
            enemies.append({"class": enemy, "donors": list(rows[enemy].get("donors") or []),
                            "files": rows[enemy].get("files") or []})
        else:
            hit = [(cls, row) for cls, row in rows.items() if enemy in (row.get("donors") or [])]
            if not hit:
                raise SwapError(f"{enemy} is neither an enemy class nor an enemy donor of {build}")
            enemies += [{"class": cls, "donors": [enemy], "files": row.get("files") or []} for cls, row in hit]
    if not players and not enemies:
        raise SwapError(f"{character or 'the playing character'} wears no library donor in {plain(build)}"
                        + (" (its slot is native)" if character else " (the character is not known yet)"))
    return {"title": title, "build": plain(build), "running": build, "players": players, "enemies": enemies}


# --- the control-plane side ------------------------------------------------------------------------------------

def request(store, *, host: str, worker_id: str, run: dict, telemetry: dict, submit, actor: str = "operator",
            enemy: str | None = None, request_id: str | None = None, note: str = "", now: float | None = None,
            rejects_path=None, known_builds=()) -> dict:
    """The operator's click: reject the donor(s), queue the variant job on the playing PC, return the record.

    A click that repeats `request_id` returns the record it made; one while a swap of this host is still queued or
    building is refused (one variant at a time per PC)."""
    now = time.time() if now is None else now
    old = store.get(STATE, host) or {}
    if request_id and old.get("request_id") == request_id:
        return old
    if old and old.get("state") in ("queued", "building") and status_of(store, old).get("state") in ("queued",
                                                                                                       "building"):
        raise SwapError(f"a swap is already {old['state']} on {host} ({old.get('variant')}): wait for it")
    game_id = run.get("game_id")
    title = donor_rejects.title_of(game_id)
    if title not in donor_rejects.TITLES:
        raise SwapError("model swaps are for the RE4 / RE5 / RE6 Switch donor builds")
    build = run.get("mod") or (store.get("session", run.get("session_id")) or {}).get("mod") or ""
    stats = (telemetry or {}).get("stats") or {}
    character = stats.get("character") or ((run.get("mercmode") or {}).get("selection") or {}).get("character")
    doc = donor_rejects.load(rejects_path)
    swap = plan(title, build, character=character, costume=stats.get("costume"), enemy=enemy, doc=doc)
    source = {"by": "operator", "actor": str(actor), "build": swap["build"], "session_id": run.get("session_id"),
              "host": host, "note": str(note or "")[:200]}
    rejected = []
    for row in swap["players"]:
        audit_entry = donor_rejects.entry(title, row["donor"], doc=doc) or {}
        donor_rejects.add(title, row["donor"], reason=f"operator: the model on {row['label'] or row['slot']} is broken",
                          source=source | {"slot": row["slot"], "role": "player"},
                          measurement=audit_entry.get("measurement"), codes=["operator"], override=rejects_path,
                          now=now)
        rejected.append({"donor": row["donor"], "slot": row["slot"], "role": "player"})
    for row in swap["enemies"]:
        for donor in row["donors"]:
            donor_rejects.add(title, donor, reason=f"operator: the enemy model on {row['class']} is broken",
                              source=source | {"slot": row["class"], "role": "enemy"}, codes=["operator"],
                              override=rejects_path, now=now)
            rejected.append({"donor": donor, "slot": row["class"], "role": "enemy"})
    existing = list(superseded(store, game_id).values()) + [swap["build"]] + [str(b) for b in known_builds or ()]
    variant = variant_name(swap["build"], existing)
    exclude = donor_rejects.rejected(title, doc=donor_rejects.load(rejects_path))
    entry = donor_rejects.build_index(swap["build"], doc=doc) or {}
    taken = sorted({r.get("donor") for r in (entry.get("players") or {}).values() if r.get("donor")}
                   | {d for r in (entry.get("enemies") or {}).values() for d in r.get("donors") or []})
    sid = uuid.uuid4().hex[:12]
    job = submit({"tool": "switch_mods", "require_worker": worker_id,
                  "input": {"op": "donor_variant", "game_id": game_id, "build": swap["build"], "new_name": variant,
                            # the swap spec (gbox.donor_swap.build_variant): `taken` = the build's other donors, never
                            # dealt twice in one build; `exclude` = the reject list, never dealt at all
                            "changes": {"title": title, "players": swap["players"], "enemies": swap["enemies"],
                                        "exclude": exclude, "taken": taken, "running": swap["running"],
                                        "swap_id": sid},
                            "note": f"operator donor swap {sid}: {', '.join(r['donor'] for r in rejected)} out"}})
    record = {"id": sid, "request_id": request_id, "state": "queued", "host": host, "worker_id": worker_id,
              "session_id": run.get("session_id"), "game_id": game_id, "title": title, "build": swap["build"],
              "running": swap["running"], "variant": variant, "character": character, "rejected": rejected,
              "job": (job or {}).get("id") if isinstance(job, dict) else job, "at": now,
              "message": f"queued: {variant} is being prepared without "
                         + ", ".join(r["donor"] for r in rejected)}
    store.put(STATE, host, record)
    store.audit(actor, "mercmode.donor_swap", host, {k: record[k] for k in ("id", "build", "variant", "rejected", "job")})
    return record


def accept(store, result: dict, *, now: float | None = None, rejects_path=None) -> dict | None:
    """switch_mods op=donor_variant came back: the variant supersedes its build and plays at the next boundary."""
    from . import mercmode
    now = time.time() if now is None else now
    swap_id = result.get("swap_id")
    record = next((r for r in store.all(STATE) if r.get("id") == swap_id), None)
    if record is None:
        return None
    variant = result.get("variant")
    if not variant:
        record = record | {"state": "failed", "error": result.get("reason") or "the job wrote no variant",
                           "message": "failed: " + str(result.get("reason") or "no variant was written")}
        store.put(STATE, record["host"], record)
        return record
    table = superseded(store, record["game_id"])
    table[record["build"]] = variant
    table[root_of(record["build"])] = variant
    store.put(SUPERSEDE, record["game_id"], table)
    cfg = mercmode.settings(store, record["host"])
    head = {"title": record["title"], "mode": None, "character": record.get("character") if record["title"] != "re6"
            else None, "stage": None, "mod": variant, "purpose": PURPOSE}
    queue = [e for e in cfg.get("queue") or [] if e.get("purpose") != PURPOSE]
    try:
        mercmode.configure(store, record["host"], {"queue": [head] + queue})
        queued = True
    except ValueError:                                   # e.g. a character the catalog refuses: no character then
        try:
            mercmode.configure(store, record["host"], {"queue": [head | {"character": None}] + queue})
            queued = True
        except ValueError:
            queued = False
    slots = result.get("slots") or []
    _index_variant(record["build"], variant, slots, rejects_path=rejects_path)
    record = record | {"state": "ready", "variant": variant, "blueprint": result.get("blueprint"), "slots": slots,
                       "ready_at": now, "queued_next": queued,
                       "message": ("plays next round: " if queued else "ready (not queued: the queue refused it): ")
                       + "; ".join(f"{s.get('slot')} {s.get('old')} -> {s.get('new') or 'native'}" for s in slots)}
    store.put(STATE, record["host"], record)
    return record


def _index_variant(build: str, variant: str, slots: list[dict], *, rejects_path=None) -> None:
    """The variant's own entry in the audit index: its source build's slots with the swapped ones changed (a
    redrawn donor, or gone: the slot is native), so a later swap on the variant finds the right donor."""
    entry = donor_rejects.build_index(build, override=rejects_path)
    if not entry:
        return
    entry = json.loads(json.dumps(entry))
    for row in slots:
        slot = row.get("slot")
        if slot in (entry.get("players") or {}):
            if row.get("new"):
                entry["players"][slot] = entry["players"][slot] | {"donor": row["new"], "from": variant}
            else:
                entry["players"].pop(slot)
        elif slot in (entry.get("enemies") or {}) and not row.get("new"):
            entry["enemies"].pop(slot)
    entry["derived_from"] = [build]
    donor_rejects.merge({}, {variant: entry}, override=rejects_path)


def build_rejects(build: str | None, *, doc: dict | None = None) -> list[dict]:
    """The donors of a build (from the audit index) that are on the reject list now: what the operator would still
    see in that build, each with the reason - the swap's candidates."""
    doc = doc if doc is not None else donor_rejects.load()
    entry = donor_rejects.build_index(build or "", doc=doc) if build else None
    if not entry:
        return []
    listed = donor_rejects.rejected(entry.get("title") or "", doc=doc)
    out = [{"slot": slot, "role": "player", "donor": row["donor"], "reason": listed[row["donor"]]}
           for slot, row in (entry.get("players") or {}).items() if row.get("donor") in listed]
    out += [{"slot": cls, "role": "enemy", "donor": donor, "reason": listed[donor]}
            for cls, row in (entry.get("enemies") or {}).items() for donor in row.get("donors") or [] if donor in listed]
    return out


def status_of(store, record: dict | None, *, running_mod: str | None = None, running_title: str | None = None) -> dict:
    """The record with its live state: building while the job runs, failed with the job's error, playing once a
    round runs the variant; a ready variant of a title that is not playing now waits for that title's turn."""
    if not record:
        return {}
    record = dict(record)
    if record.get("state") in ("queued", "building") and record.get("job"):
        job = store.get("job", record["job"]) or {}
        state = job.get("state")
        if state in ("assigned", "running"):
            record["state"], record["message"] = "building", f"building {record['variant']} on the PC"
        elif state == "succeeded":
            record["state"], record["message"] = "building", f"{record['variant']} is written; queueing it"
        elif state in ("failed", "invalid", "cancelled", "canceled"):
            record["state"] = "failed"
            record["error"] = str(job.get("error") or state)[:300]
            record["message"] = "failed: " + record["error"]
    if running_mod and record.get("state") in ("ready", "playing") and plain(running_mod) == record.get("variant"):
        record["state"], record["message"] = "playing", f"playing {record['variant']}"
    elif record.get("state") == "ready" and running_title and running_title != record.get("title"):
        record["message"] = f"ready: {record['variant']} plays when {str(record.get('title')).upper()} comes up next"
    return record


def status(store, host: str, *, running_mod: str | None = None, running_title: str | None = None) -> dict:
    return status_of(store, store.get(STATE, host), running_mod=running_mod, running_title=running_title)


# --- the worker side: write the variant ----------------------------------------------------------------------

def _library(cfg) -> Path:
    return Path(getattr(cfg, "cache", "") or ".") / "characters"


def _candidates(library: Path, *, exclude: set[str], seed: str) -> list[str]:
    try:
        from . import characters
        metas = characters.list_all(library)
        slugs = [m["slug"] for m in metas if m.get("slug") and str(m.get("kind") or "character") == "character"]
    except Exception:                                    # noqa: BLE001 - no cache helper: the folders themselves
        slugs = sorted(p.name for p in library.iterdir() if p.is_dir()) if library.is_dir() else []
    pool = sorted(set(slugs) - set(exclude))
    random.Random(seed).shuffle(pool)
    return pool


def _redraw_re5_player(cfg, row: dict, *, exclude: set[str], seed: str, deadline: float, log) -> dict | None:
    """The next donor that builds on this RE5 player slot and passes the fit audit: {bytes, donor, receipt, tried}."""
    from . import donor_fit_audit as audit
    from . import re5_cast_writer as players
    from . import skin_swap
    slot = players.SLOTS.get(row["slot"])
    romfs = skin_swap.romfs_root(RE5_TITLE_ID)
    library = _library(cfg)
    if slot is None or romfs is None or not library.is_dir():
        log(f"{row['slot']}: no redraw here (slot, RomFS or library missing)")
        return None
    original = (romfs / slot.archive).read_bytes()
    tried, built, resolved = [], 0, 0
    for slug in _candidates(library, exclude=exclude, seed=seed):
        if time.monotonic() > deadline or built >= MAX_ATTEMPTS or resolved >= MAX_RESOLVE:
            break
        resolved += 1
        try:
            donor = players.donor_from(library, slug)
        except (players.CastWriterError, ValueError, OSError) as exc:
            tried.append({"donor": slug, "refused": str(exc)[:160]})
            continue
        built += 1
        try:
            data, receipt = players.build(original, library / donor.slug / donor.model, donor)
        except (ValueError, OSError) as exc:
            tried.append({"donor": slug, "refused": str(exc)[:160]})
            continue
        rows = audit.judge_all(audit._re5_players({"slots": {row["slot"]: receipt | {"donor": slug}}}, "redraw",
                                                  "donor_swap"))
        flags = audit.rejecting(rows[0]["flags"]) if rows else []
        if flags:
            tried.append({"donor": slug, "refused": "; ".join(f["text"] for f in flags), "codes": [f["code"] for f in flags],
                          "measurement": audit._measurement(rows[0])})
            continue
        log(f"{row['slot']}: {slug} passes the fit audit")
        return {"bytes": data, "donor": slug, "receipt": receipt, "tried": tried}
    log(f"{row['slot']}: no passing donor in {built} builds / {resolved} folders")
    return {"bytes": None, "donor": None, "tried": tried}


def build_variant(cfg, game_id: str, build: str, name: str, spec: dict, *, by: str = "", log=print,
                  clock=time.monotonic) -> dict:
    """Write `name` (and `name-blueprint` when `build-blueprint` exists) = `build` with the swap's slots redrawn or
    native. Never writes `build`. Returns {variant, blueprint, slots, swap_id, rejected_during}."""
    from . import switch_mods as SM
    deadline = clock() + TIME_BUDGET_S
    title = spec.get("title") or donor_rejects.title_of(game_id)
    exclude = set(spec.get("exclude") or {}) | set(spec.get("taken") or ())
    exclude |= {r["donor"] for r in spec.get("players") or [] if r.get("donor")}
    changes: dict[str, dict] = {}
    slots, rejected_during = [], []
    for row in spec.get("players") or []:
        files = [f["path"] if isinstance(f, dict) else f for f in row.get("files") or []]
        got = None
        if title in REDRAW_TITLES and files:
            got = _redraw_re5_player(cfg, row, exclude=exclude, seed=f"{build}:{row['slot']}:{name}",
                                     deadline=deadline, log=log)
            for t in (got or {}).get("tried") or []:
                if t.get("codes"):
                    rejected_during.append({"donor": t["donor"], "reason": t["refused"], "codes": t["codes"],
                                            "measurement": t.get("measurement"), "slot": row["slot"]})
        if got and got.get("bytes"):
            changes[files[0]] = {"bytes": got["bytes"]}
            exclude.add(got["donor"])
            slots.append({"slot": row["slot"], "old": row.get("donor"), "new": got["donor"], "how": "redrawn",
                          "tried": len(got.get("tried") or [])})
        else:
            for path in files:
                changes[path] = {"remove": True}
            why = NATIVE_WHY.get(title) or "no donor passed the fit audit within the job's bounds"
            slots.append({"slot": row["slot"], "old": row.get("donor"), "new": None, "how": "native", "why": why})
    for row in spec.get("enemies") or []:
        for f in row.get("files") or []:
            changes[f["path"] if isinstance(f, dict) else f] = {"remove": True}
        slots.append({"slot": row["class"], "old": "+".join(row.get("donors") or []), "new": None, "how": "native",
                      "why": "the class plays its native enemies (no per-carrier redraw yet)"})
    if not changes:
        raise ValueError("the swap names no overlay files to change")
    made = []
    pairs = [(build, name)]
    if SM.is_overlay(SM.read_meta(SM.build_dir(cfg, game_id, build + BLUEPRINT))):
        pairs.append((build + BLUEPRINT, name + BLUEPRINT))
    for src, dst in pairs:
        if SM.build_dir(cfg, game_id, dst).exists():
            raise ValueError(f"{dst} already exists: a variant is never overwritten")
        SM.copy_build(cfg, game_id, src, dst, by=by)
        held = {f["path"] for f in SM.overlay_files(SM.build_dir(cfg, game_id, dst))}
        mine = {p: ch for p, ch in changes.items() if not ch.get("remove") or p in held}
        if mine:
            SM.write_files(cfg, game_id, dst, mine, note=f"donor swap of {src}: "
                           + "; ".join(f"{s['slot']} {s['old']} -> {s['new'] or 'native'}" for s in slots), by=by)
        made.append(dst)
    return {"op": "donor_variant", "swap_id": spec.get("swap_id"), "variant": name,
            "blueprint": name + BLUEPRINT if len(made) > 1 else None, "of": build, "slots": slots,
            "rejected_during": rejected_during, "builds": made}


def record_redraw_rejects(result: dict, *, override=None) -> None:
    """Donors the variant job built and the fit audit refused: on the reject list too (source: the audit)."""
    title = donor_rejects.title_of(result.get("game_id") or "") or result.get("title")
    for row in result.get("rejected_during") or []:
        if title in donor_rejects.TITLES and row.get("donor") and not donor_rejects.entry(title, row["donor"],
                                                                                         override=override):
            donor_rejects.add(title, row["donor"], reason=f"redraw for {row.get('slot')}: {row.get('reason')}",
                              source={"by": "audit", "via": "donor_swap redraw", "slot": row.get("slot"),
                                      "build": result.get("of")},
                              measurement=row.get("measurement"), codes=row.get("codes") or [], override=override)


# --- per-match check from live frames (report only) ----------------------------------------------------------

def camera_filled(frame, *, share: float = 0.6, tolerance: int = 18, max_edges: float = 0.03) -> dict:
    """Does one uniform surface cover most of the view? An oversized donor standing in front of the camera fills
    the frame with its own magnified texture (the operator could not see past Vincent's 47 m body). `frame` is an
    HxWx3 uint8 array; in the centre 80 % (the HUD stays out) colours are quantised by `tolerance` on a grid and the
    largest bin's share is measured, with the edge density (neighbouring pixels more than 24 grey levels apart).
    Filled = one colour over `share` of the view, almost no edges, not a black frame. Calibrated on lilspark RE5
    frames (2026-11-10): rounds 0.08-0.13 edges, the dimmed pause menu 0.04-0.06 (the share alone took it for a
    filled camera). A flag is a hint for the audit, never an action."""
    import numpy as np
    arr = np.asarray(frame)
    if arr.ndim != 3 or arr.shape[0] < 8 or arr.shape[1] < 8:
        return {"filled": False, "share": 0.0, "reason": "no frame"}
    h, w = arr.shape[:2]
    crop = arr[h // 10: h - h // 10, w // 10: w - w // 10, :3]
    step = max(1, min(crop.shape[0], crop.shape[1]) // 64)
    sample = crop[::step, ::step].reshape(-1, 3).astype(np.int32) // max(1, tolerance)
    keys = sample[:, 0] * 65536 + sample[:, 1] * 256 + sample[:, 2]
    _values, counts = np.unique(keys, return_counts=True)
    top = float(counts.max()) / float(len(keys)) if len(keys) else 0.0
    grey = crop.astype(np.float32).mean(axis=2)
    edges = float(((np.abs(np.diff(grey, axis=1))[:-1, :] + np.abs(np.diff(grey, axis=0))[:, :-1]) > 24).mean())
    mean = crop.reshape(-1, 3).mean(axis=0)
    dark = bool(mean.max() < 12)                       # a black frame (loading, a hang) is not a filled camera
    return {"filled": bool(top >= share and edges < max_edges and not dark), "share": round(top, 3),
            "edges": round(edges, 4), "dark": dark, "colour": [int(c) for c in mean]}
