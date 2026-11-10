"""Which library donors of the Mercenaries builds fit their native slot, from what the builds' receipts recorded.

Operator 2026-11-10: "some of these characters are a bit oversized and stretched out of proportion beyond my ability
to be able to even see them ... models that I don't even want to see in the rotation". Every writer of the RE4 / RE5
/ RE6 Switch donor builds already wrote the fitted bind-pose box of each donor (or its fitted height and rest-pose
deviation) into its receipt. This module reads those receipts, one row per donor on a slot, and judges each row
against the native slot:

* `tall` / `short`: the fitted height against the native height (a donor stretched past the slot, or collapsed);
* `wide`: the fitted width against the native width (the native T-pose span, or the height when none is recorded);
* `deep`: the fitted depth against the native height (Leon's Alpine guard: 3.1 m deep on a 2.5 m body);
* `flat`: a depth no person has (Ada's Razor: 7.6 cm deep) - the fit squashed the body into a sheet;
* `floats` / `sinks`: the box's floor off the slot's floor by more than a tenth of the native height;
* `box`: wider and deeper than tall - not a standing person (a prop, or a fit that folded the body);
* `stretched`: RE6's keep-bind fit with limbs far off the native rest pose (the mesh is pulled along the bones);
* `prop`: the library entry is not a character (its own metadata says so).

Thresholds are ratios to the native slot, so they hold across the titles' units (RE4 millimetres, RE5 / RE6
centimetres). A slot whose native size is not in its receipt is measured against the median of all donors on that
slot kind of the title (the fit brings a passing donor to the native joints, so the median is the native size), and
that reference is named in the row.

    rows = audit_paths([...receipt files or folders...])  -> [{title, build, role, slot, donor, fitted, native, flags}]
    rejects(rows)                                          -> {title: {slug: entry}} for donor_rejects.merge
    index(rows, builds)                                    -> {build: {players, enemies, files}} (donor_rejects)
    table(rows)                                            -> a Markdown table per title

CLI: python -m gbox.donor_fit_audit --receipts DIR [DIR...] [--builds builds.json] [--write [FILE]] [--table]
Nothing here builds, installs or launches anything; `--write` only merges into the reject file.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from . import donor_rejects

#: metres per model unit
UNITS = {"re4": 0.001, "re5": 0.01, "re6": 0.01}
#: A native humanoid when nothing else is known (metres): height, T-pose width, depth.
NATIVE_DEFAULT = {"height": 1.80, "width": 1.80, "depth": 0.45}
LIMITS = {
    "tall": 1.35,          # fitted height / native height above this
    "short": 0.55,         # ... below this
    "wide": 1.60,          # fitted width / native width above this
    "deep": 0.80,          # fitted depth / native height above this
    "flat": 0.06,          # fitted depth / native height below this (10.8 cm on a 1.8 m body)
    "floor": 0.10,         # |box floor| / native height above this
    "stretched_degrees": 45.0,   # RE6 keep-bind rest-pose deviation above this
    "feet_stretch": 4.0,         # watch: RE5 player feet scaled this many times the body scale
    "part_spread": 3.5,          # watch: RE5 enemy part scales this far apart (largest / smallest)
}
CODES = {"tall": "oversized", "short": "collapsed", "wide": "too wide", "deep": "too deep", "flat": "squashed flat",
         "floats": "floats above the floor", "sinks": "sinks below the floor", "box": "not a standing person",
         "stretched": "limbs stretched off the bind pose", "prop": "not a character",
         "feet": "feet stretched (watch)", "parts": "parts scaled unevenly (watch)"}
NON_CHARACTER_KINDS = {"prop", "object", "item", "weapon", "vehicle", "stage", "scenery", "effect"}


def _m(value, title):
    return None if value is None else round(float(value) * UNITS[title], 4)


def _dims_of_bounds(bounds: dict | None, title: str) -> dict | None:
    """{height, width, depth, floor} in metres of a {min: {x,y,z}, max: {x,y,z}} box."""
    if not isinstance(bounds, dict) or not isinstance(bounds.get("min"), dict) or not isinstance(bounds.get("max"), dict):
        return None
    lo, hi = bounds["min"], bounds["max"]
    try:
        return {"height": _m(hi["y"] - lo["y"], title), "width": _m(hi["x"] - lo["x"], title),
                "depth": _m(hi["z"] - lo["z"], title), "floor": _m(lo["y"], title), "top": _m(hi["y"], title)}
    except (KeyError, TypeError):
        return None


def _dims_of_bbox(bbox, title: str) -> dict | None:
    """The same from a [[x0, y0, z0], [x1, y1, z1]] box (RE4's receipts)."""
    try:
        (x0, y0, z0), (x1, y1, z1) = bbox
    except (TypeError, ValueError):
        return None
    return {"height": _m(y1 - y0, title), "width": _m(x1 - x0, title), "depth": _m(z1 - z0, title),
            "floor": _m(y0, title), "top": _m(y1, title)}


def _row(title, build, role, slot, donor, *, fitted=None, native=None, source="", files=(), name=None, extra=None):
    return {"title": title, "build": build, "role": role, "slot": slot, "donor": donor, "name": name,
            "fitted": fitted, "native": native, "source": source, "files": list(files), **(extra or {})}


def _slug(value) -> str | None:
    if isinstance(value, dict):
        return value.get("slug")
    return value if isinstance(value, str) else None


# --- readers: one per receipt shape -----------------------------------------------------------------------------

def _spread(scales) -> float | None:
    """The largest over the smallest of RE5's per-part fit scales (limbs, torso, head, hands): how unevenly the fit
    stretched the body's parts against each other."""
    values = [v for v in (scales or {}).values() if isinstance(v, (int, float)) and v > 0]
    return round(max(values) / min(values), 2) if len(values) > 1 else None


def _re5_players(doc: dict, build: str, source: str) -> list[dict]:
    rows = []
    for key, slot in (doc.get("slots") or {}).items():
        if not isinstance(slot, dict) or "fit" not in slot:
            continue
        fit = slot.get("fit") or {}
        fitted = _dims_of_bounds(fit.get("bounds"), "re5")
        native = _dims_of_bounds(fit.get("native_bounds"), "re5")
        if native and fit.get("native_height"):
            native["height"] = _m(fit["native_height"], "re5")
        label = (slot.get("slot") or {}).get("label") or key
        scale = fit.get("scale") or {}
        feet = [v for v in (scale.get("feet_vertical_scale") or {}).values() if isinstance(v, (int, float))]
        stretch = round(max(feet) / scale["body_scale"], 2) if feet and scale.get("body_scale") else None
        rows.append(_row("re5", build, "player", key, _slug(slot.get("donor")) or _slug(slot.get("source")),
                         name=(slot.get("source") or {}).get("name"), fitted=fitted, native=native,
                         source=f"{source}#slots.{key}.fit", files=[(slot.get("output") or {}).get("path")],
                         extra={"label": label, "feet_stretch": stretch}))
    return rows


def _re5_enemies(doc: dict, build: str, source: str) -> list[dict]:
    rows = []
    for cls, arc in (doc.get("archives") or {}).items():
        if not isinstance(arc, dict):
            continue
        receipt = arc.get("receipt") or {}
        native = _dims_of_bounds((receipt.get("fit") or {}).get("native_bounds") or (arc.get("fit") or {}).get(
            "native_bounds"), "re5")
        path = arc.get("archive")
        carriers = arc.get("carriers") or []
        if carriers:
            for number, carrier in enumerate(carriers):
                fit = carrier.get("fit") or {}
                nat = dict(native) if native else None
                if fit.get("native_height_cm"):
                    nat = (nat or {}) | {"height": _m(fit["native_height_cm"], "re5")}
                rows.append(_row("re5", build, "enemy", f"{cls}:{carrier.get('carrier', number)}",
                                 _slug(carrier.get("donor")), fitted=_dims_of_bounds(fit.get("bounds"), "re5"),
                                 native=nat, source=f"{source}#archives.{cls}.carriers[{number}].fit", files=[path],
                                 extra={"class": cls, "part_spread": _spread(fit.get("scales"))}))
        elif arc.get("fit") or receipt.get("fit"):
            fit = arc.get("fit") or receipt.get("fit") or {}
            nat = dict(native) if native else None
            if fit.get("native_height_cm"):
                nat = (nat or {}) | {"height": _m(fit["native_height_cm"], "re5")}
            donor = _slug(arc.get("donor")) or next((_slug(d) for d in (doc.get("donors") or {}).get(cls) or []), None)
            rows.append(_row("re5", build, "enemy", cls, donor, fitted=_dims_of_bounds(fit.get("bounds"), "re5"),
                             native=nat, source=f"{source}#archives.{cls}.fit", files=[path],
                             extra={"class": cls, "part_spread": _spread(fit.get("scales"))}))
    return rows


def _re4_cast(doc: dict, build: str, source: str) -> list[dict]:
    rows = []
    for slot, row in (doc.get("slots") or {}).items():
        fit = row.get("fit") or {}
        rows.append(_row("re4", build, "player", slot, _slug(row.get("donor")), name=(row.get("donor") or {}).get("name"),
                         fitted=_dims_of_bbox(fit.get("bbox"), "re4"), source=f"{source}#slots.{slot}.fit.bbox",
                         files=[f"romfs/bio4/em/{row.get('pack')}.udas"] if row.get("pack") else [],
                         extra={"pack": row.get("pack"), "archive": row.get("archive")}))
    return rows


def _re4_enemies(doc: dict, build: str, source: str) -> list[dict]:
    rows = []
    for cls, row in (doc.get("classes") or {}).items():
        for number, group in enumerate(row.get("groups") or []):
            fit = group.get("fit") or {}
            rows.append(_row("re4", build, "enemy", f"{cls}:{group.get('body')}", _slug(group.get("donor")),
                             name=(group.get("donor") or {}).get("name"), fitted=_dims_of_bbox(fit.get("bbox"), "re4"),
                             source=f"{source}#classes.{cls}.groups[{number}].fit.bbox",
                             files=[f"romfs/bio4/em/{row.get('pack') or cls}.udas"], extra={"class": cls}))
    return rows


def _re6_rest(row: dict) -> float | None:
    dev = row.get("rest_pose_deviation")
    if isinstance(dev, dict) and dev.get("max_degrees") is not None:
        return float(dev["max_degrees"])
    for key in ("rest_pose_max_degrees", "rest_degrees"):
        if row.get(key) is not None:
            return float(row[key])
    return None


def _re6_enemies(doc: dict, build: str, source: str) -> list[dict]:
    rows = []
    for number, row in enumerate(doc.get("classes") or []):
        if not row.get("donor"):
            continue
        body = row.get("body") or {}
        native = {"height": _m(body.get("height_cm"), "re6"), "width": _m(body.get("width_cm"), "re6")} \
            if body.get("height_cm") else None
        fitted = {"height": _m(row.get("fitted_height"), "re6")} if row.get("fitted_height") else None
        rows.append(_row("re6", build, "enemy", row.get("class"), row.get("donor"), name=row.get("donor_name"),
                         fitted=fitted, native=native, source=f"{source}#classes[{number}]",
                         files=[f"romfs/nativeNXx64/arc/NX/{row.get('archive')}"] if row.get("archive") else [],
                         extra={"class": row.get("class"), "rest_degrees": _re6_rest(row),
                                "bind_mode": row.get("bind_mode"), "height_clamped": row.get("height_clamped")}))
    return rows


def _re6_cast(doc: dict, build: str, source: str) -> list[dict]:
    rows = []
    for number, row in enumerate(doc.get("slots") or []):
        if not isinstance(row, dict):
            continue
        if row.get("wearer"):                 # the roster shuffle: a native RE6 costume on another costume's slot
            files = [f"romfs/nativeNXx64/arc/NX/{row['slot_arc']}.arc"] + [
                f"romfs/nativeNXx64/arc/NX/{t['arc']}.arc" for t in row.get("texsets") or [] if t.get("arc")]
            slot = str(row.get("slot") or "").split(" (")[0]          # 'leon/c0 (variant 0)' -> 'leon/c0'
            rows.append(_row("re6", build, "player", slot, row["wearer"], source=f"{source}#slots[{number}]",
                             files=files, extra={"native_costume": True, "bones": row.get("bones"),
                                                 "verts": row.get("verts")}))
        elif row.get("donor"):
            fitted = {"height": _m(row.get("fitted_height_cm"), "re6")} if row.get("fitted_height_cm") else None
            rows.append(_row("re6", build, "player", row.get("slot"), row["donor"], name=row.get("donor_name"),
                             fitted=fitted, native={"height": 1.80}, source=f"{source}#slots[{number}]",
                             files=[f"romfs/nativeNXx64/arc/NX/{row.get('archive')}"] if row.get("archive") else [],
                             extra={"rest_degrees": _re6_rest(row), "bind_mode": row.get("bind_mode"),
                                    "height_clamped": row.get("height_clamped")}))
    return rows


def _re6_gallery(doc: dict, build: str, source: str) -> list[dict]:
    rows = []
    for number, row in enumerate(doc.get("donors") or []):
        if not row.get("donor") or row.get("refused"):
            continue
        slot = row.get("slot") or ["?", 0]
        rows.append(_row("re6", build, "player", f"{str(slot[0]).lower()}/c{slot[1]}", row["donor"], name=row.get("name"),
                         source=f"{source}#donors[{number}]",
                         files=[f"romfs/nativeNXx64/arc/NX/{a}" for a in row.get("archives") or []],
                         extra={"rest_degrees": _re6_rest(row), "bind_mode": "keep",
                                "base": Path(str(doc.get("base") or "")).name or None}))
    return rows


def _sizes(doc: dict) -> dict[str, int]:
    """{overlay path: bytes} of the files a receipt says it wrote (its `files` table, a player slot's `output`, an
    enemy archive's `output_bytes`), so a live build can be matched to the receipt by content size."""
    out: dict[str, int] = {}
    files = doc.get("files")
    if isinstance(files, list):
        for row in files:
            if isinstance(row, dict) and row.get("path") and isinstance(row.get("bytes"), int):
                out[row["path"]] = row["bytes"]
    elif isinstance(files, dict):
        for key, row in files.items():
            if isinstance(row, dict) and isinstance(row.get("bytes"), int):
                out[key] = row["bytes"]
    for slot in (doc.get("slots") or {}).values() if isinstance(doc.get("slots"), dict) else []:
        output = slot.get("output") if isinstance(slot, dict) else None
        if isinstance(output, dict) and output.get("path") and isinstance(output.get("bytes"), int):
            out[output["path"]] = output["bytes"]
    for arc in (doc.get("archives") or {}).values() if isinstance(doc.get("archives"), dict) else []:
        if isinstance(arc, dict) and arc.get("archive") and isinstance(arc.get("output_bytes"), int):
            out[arc["archive"]] = arc["output_bytes"]
    return out


def read_receipt(path: Path, build: str | None = None) -> list[dict]:
    """The donor rows of one receipt file (an unknown shape gives none); each row's `files` are [{path, size}]
    (size None where the receipt does not give it)."""
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict):
        return []
    rows = _read_receipt(doc, path, build)
    sizes = _sizes(doc) if rows else {}
    for row in rows:
        row["files"] = [{"path": f, "size": sizes.get(f)} for f in row.get("files") or [] if f]
    return rows


def _read_receipt(doc: dict, path: Path, build: str | None) -> list[dict]:
    build = build or doc.get("build") or doc.get("name") or path.parent.name
    source = str(path)
    recipe = str(doc.get("recipe") or doc.get("route") or "")
    if recipe == "re5_cast_writer" or (doc.get("slots") and isinstance(doc["slots"], dict)
                                       and any("fit" in v and "native_bounds" in (v.get("fit") or {})
                                               for v in doc["slots"].values() if isinstance(v, dict))):
        return _re5_players(doc, build, source)
    if recipe == "re5_enemy_cast":
        return _re5_enemies(doc, build, source)
    if recipe == "re4_switch_models.cast_pool":
        return _re4_cast(doc, build, source)
    if recipe == "re4_switch_enemies.enemy_pool":
        return _re4_enemies(doc, build, source)
    if recipe == "re6_switch_enemies.build_pool":
        return _re6_enemies(doc, build, source)
    if recipe == "re6_gallery_skin.build_overlay":
        return _re6_gallery(doc, build, source)
    if doc.get("title_id") == "01002A000CD48000" or str(build).startswith(("recovery-re6", "re6")):
        return _re6_cast(doc, build, source)
    return []


def _build_of(path: Path, names: dict | None) -> str | None:
    """The build a receipt belongs to: an explicit {receipt folder: build} map first, else None (the receipt's own)."""
    if not names:
        return None
    for key in (str(path), str(path.parent), path.parent.name):
        if key in names:
            return names[key]
    return None


def audit_paths(paths, *, names: dict | None = None, library: Path | None = None) -> list[dict]:
    """Every donor row of the receipts under `paths` (files, or folders searched for receipt*.json), judged."""
    rows = []
    for item in paths:
        item = Path(item)
        files = [item] if item.is_file() else sorted(p for p in item.rglob("receipt*.json"))
        for file in files:
            rows.extend(read_receipt(file, _build_of(file, names)))
    return judge_all(rows, library=library)


# --- the judge ---------------------------------------------------------------------------------------------------

def _references(rows: list[dict]) -> dict:
    """{title: {height, width, depth}}: the median of the fitted boxes of all the title's donors, players and
    enemies together (the native size where the receipts do not record it: a passing fit lands on the native
    joints, and one slot's handful of donors is too few - RE4's five cast donors have a 2.5 m median)."""
    out = {}
    groups: dict = {}
    for row in rows:
        fitted = row.get("fitted") or {}
        if fitted.get("height"):
            groups.setdefault(row["title"], []).append(fitted)
    for key, boxes in groups.items():
        ref = {}
        for dim in ("height", "width", "depth"):
            values = [b[dim] for b in boxes if b.get(dim)]
            if values:
                ref[dim] = round(statistics.median(values), 4)
        out[key] = ref
    return out


def _meta_kind(library: Path | None, slug: str | None) -> str | None:
    if not library or not slug:
        return None
    try:
        meta = json.loads((Path(library) / slug / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(meta.get("kind") or "").lower() or None


def judge(row: dict, reference: dict | None = None, *, kind: str | None = None) -> list[dict]:
    """The flags of one row: [{code, text}] (empty: the donor fits as far as the receipt shows)."""
    flags = []
    fitted = row.get("fitted") or {}
    native = dict(reference or {}) | {k: v for k, v in (row.get("native") or {}).items() if v}
    nh = native.get("height") or NATIVE_DEFAULT["height"]
    nw = native.get("width") or nh
    h, w, d, floor = fitted.get("height"), fitted.get("width"), fitted.get("depth"), fitted.get("floor")

    def flag(code, text):
        flags.append({"code": code, "text": text})

    if h:
        if h / nh > LIMITS["tall"]:
            flag("tall", f"{h:.2f} m tall on a {nh:.2f} m slot ({h / nh:.1f}x)")
        elif h / nh < LIMITS["short"]:
            flag("short", f"{h:.2f} m tall on a {nh:.2f} m slot ({h / nh:.2f}x)")
    if w and w / nw > LIMITS["wide"]:
        flag("wide", f"{w:.2f} m wide against {nw:.2f} m native ({w / nw:.1f}x)")
    if d is not None and d:
        if d / nh > LIMITS["deep"]:
            flag("deep", f"{d:.2f} m deep on a {nh:.2f} m slot")
        elif d / nh < LIMITS["flat"]:
            flag("flat", f"{d * 100:.1f} cm deep: squashed into a sheet")
    if floor is not None and abs(floor) / nh > LIMITS["floor"]:
        flag("floats" if floor > 0 else "sinks", f"floor at {floor:+.2f} m")
    if h and w and d and w > h and d > h:
        flag("box", f"{w:.2f} x {d:.2f} m footprint under a {h:.2f} m top")
    rest = row.get("rest_degrees")
    if rest is not None and rest > LIMITS["stretched_degrees"] and (row.get("bind_mode") or "keep") == "keep":
        flag("stretched", f"limbs {rest:.0f} degrees off the native bind, kept bound")
    if kind and kind in NON_CHARACTER_KINDS:
        flag("prop", f"the library entry is a {kind}")
    # watch only (reported in the table, never a reject): RE5's per-part fit drawing the body's parts unevenly - the
    # feet stretched far past the body (Dr. Mario's soles 7x), limbs against torso (Luigi 3.7x). The body still stands
    # at the native height on the floor, so the operator judges these in a round (the live swap), not the audit.
    feet = row.get("feet_stretch")
    if feet and feet > LIMITS["feet_stretch"]:
        flags.append({"code": "feet", "text": f"feet stretched {feet:.1f}x the body scale", "severity": "watch"})
    spread = row.get("part_spread")
    if spread and spread > LIMITS["part_spread"]:
        flags.append({"code": "parts", "text": f"parts scaled {spread:.1f}x apart", "severity": "watch"})
    return flags


def rejecting(flags: list[dict]) -> list[dict]:
    """The flags that refuse a donor (the rest are `watch` notes)."""
    return [f for f in flags or [] if f.get("severity", "reject") == "reject"]


def judge_all(rows: list[dict], *, library: Path | None = None) -> list[dict]:
    refs = _references(rows)
    out = []
    for row in rows:
        ref = refs.get(row["title"]) if not (row.get("native") or {}).get("height") else None
        kind = _meta_kind(library, row.get("donor"))
        flags = judge(row, ref, kind=kind)
        out.append(row | {"flags": flags, "reference": None if not ref else {"from": "median of the title's donors",
                                                                             **ref},
                          "verdict": "reject" if rejecting(flags) else "watch" if flags else (
                              "pass" if row.get("fitted") or row.get("native_costume")
                              or row.get("rest_degrees") is not None else "unmeasured")})
    return out


# --- outputs -----------------------------------------------------------------------------------------------------

def _measurement(row: dict) -> dict:
    return {"fitted_m": row.get("fitted"), "native_m": row.get("native") or row.get("reference"),
            **({"rest_degrees": row["rest_degrees"]} if row.get("rest_degrees") is not None else {})}


def rejects(rows: list[dict], *, now: float | None = None) -> dict:
    """{title: {slug: entry}} of the rows judged 'reject', one entry per donor (its worst-flagged row first)."""
    now = time.time() if now is None else now
    out: dict = {}
    for row in sorted(rows, key=lambda r: -len(rejecting(r.get("flags")))):
        if row.get("verdict") != "reject" or not row.get("donor"):
            continue
        flags = rejecting(row["flags"])
        rows_of = out.setdefault(row["title"], {})
        if row["donor"] in rows_of:
            rows_of[row["donor"]]["source"].setdefault("also", []).append(
                {"build": row["build"], "slot": row["slot"], "codes": [f["code"] for f in flags]})
            continue
        rows_of[row["donor"]] = {
            "reason": f"{row['role']} {row['slot']} of {row['build']}: " + "; ".join(f["text"] for f in flags),
            "codes": sorted({f["code"] for f in flags}), "measurement": _measurement(row),
            "source": {"by": "audit", "build": row["build"], "slot": row["slot"], "role": row["role"],
                       "receipt": row["source"]},
            "at": now}
    return out


def _carried(files: list[dict], have: dict[str, int], live_name: str, source: str) -> bool:
    """Does a live build hold these receipt files? Every path present with the receipt's size; a file whose size
    the receipt does not give only counts in a build named after the receipt's (its companion or variant)."""
    if not files:
        return False
    for f in files:
        if f["path"] not in have:
            return False
        if f.get("size") is None:
            if not live_name.startswith(source):
                return False
        elif have[f["path"]] != f["size"]:
            return False
    return True


def index(rows: list[dict], builds: dict | None = None) -> dict:
    """{build: {title, game_id, players: {slot: {donor, label, files}}, enemies: {class: {donors, files}}}} of the
    receipts' builds, then of every live build in `builds` ({build: {game_id, files: [{path, size}]}}) that holds a
    receipt's files (same path and size: a blueprint companion, a derived build like fitgate-grey). `files` are
    [{path, size}]; a slot whose files a live build does not hold is not that build's."""
    out: dict = {}
    for row in rows:
        entry = out.setdefault(row["build"], {"title": row["title"], "game_id": donor_rejects.TITLE_GAMES.get(row["title"]),
                                              "players": {}, "enemies": {}, "receipts": []})
        if row["source"].split("#")[0] not in entry["receipts"]:
            entry["receipts"].append(row["source"].split("#")[0])
        if row.get("base"):
            entry["base"] = row["base"]
        files = [f for f in row.get("files") or [] if f and f.get("path")]
        if row["role"] == "player":
            entry["players"][row["slot"]] = {"donor": row["donor"], "label": row.get("label") or row["slot"],
                                             "files": files, "verdict": row.get("verdict")}
        else:
            cls = row.get("class") or str(row["slot"]).split(":")[0]
            group = entry["enemies"].setdefault(cls, {"donors": [], "files": []})
            if row["donor"] and row["donor"] not in group["donors"]:
                group["donors"].append(row["donor"])
            known = {f["path"] for f in group["files"]}
            group["files"] += [f for f in files if f["path"] not in known]
    for entry in out.values():
        # a build made over another (the RE6 gallery probe over shuffle-01): the base's slots it does not replace are
        # its slots too, their files re-written in place (patches), so matched by path only
        base = out.get(entry.get("base") or "")
        if base and base is not entry:
            for slot, row in base["players"].items():
                entry["players"].setdefault(slot, row | {"from": entry["base"],
                                                         "files": [{"path": f["path"], "size": None} for f in row["files"]]})
    for name, live in (builds or {}).items():
        have = {f["path"]: f.get("size") for f in live.get("files") or []}
        if name in out:
            # the receipt's own build: keep only the slots the live copy still holds (a later edit replaced the rest)
            if have:
                entry = out[name]
                entry["players"] = {k: v for k, v in entry["players"].items() if _carried(v["files"], have, name, name)}
                entry["enemies"] = {k: v for k, v in entry["enemies"].items() if _carried(v["files"], have, name, name)}
            continue
        merged = {"title": donor_rejects.GAME_TITLES.get(live.get("game_id"), ""), "game_id": live.get("game_id"),
                  "players": {}, "enemies": {}, "receipts": [], "derived_from": []}
        # the build the live one is named after first (its companion / variant), then the rest
        for source, entry in sorted(out.items(), key=lambda kv: (not name.startswith(kv[0]), kv[0])):
            if entry.get("game_id") != live.get("game_id") or "derived_from" in entry:
                continue
            for slot, row in entry["players"].items():
                if slot not in merged["players"] and _carried(row["files"], have, name, source):
                    merged["players"][slot] = row | {"from": source}
            for cls, row in entry["enemies"].items():
                if cls not in merged["enemies"] and _carried(row["files"], have, name, source):
                    merged["enemies"][cls] = row | {"from": source}
            if any(r.get("from") == source for r in list(merged["players"].values()) + list(merged["enemies"].values())):
                merged["derived_from"].append(source)
        if merged["players"] or merged["enemies"]:
            out[name] = merged
    return out


def table(rows: list[dict]) -> str:
    """A Markdown table per title: build, role, slot, donor, fitted h/w/d, native h, verdict and flags."""
    lines = []
    for title in ("re4", "re5", "re6"):
        mine = [r for r in rows if r["title"] == title]
        if not mine:
            continue
        lines += [f"### {title.upper()} ({len(mine)} donor rows, {sum(r['verdict'] == 'reject' for r in mine)} rejected)",
                  "", "| build | role | slot | donor | fitted h x w x d (m) | floor | native h | verdict | why |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(mine, key=lambda r: (r["verdict"] != "reject", r["build"], r["role"], str(r["slot"]))):
            f = r.get("fitted") or {}
            dims = " x ".join(f"{f[k]:.2f}" if f.get(k) else "-" for k in ("height", "width", "depth"))
            nat = (r.get("native") or {}).get("height") or (r.get("reference") or {}).get("height")
            why = "; ".join(x["text"] for x in r.get("flags") or []) or (
                "native RE6 costume" if r.get("native_costume") else
                (f"rest {r['rest_degrees']:.0f} deg" if r.get("rest_degrees") is not None else ""))
            floor = f"{f['floor']:+.2f}" if f.get("floor") is not None else "-"
            lines.append(f"| {r['build']} | {r['role']} | {r['slot']} | {r['donor']} | {dims} | {floor} | "
                         f"{f'{nat:.2f}' if nat else '-'} | {r['verdict']} | {why} |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Donor fit audit of the Mercenaries builds' receipts")
    parser.add_argument("--receipts", nargs="+", required=True, help="receipt files or folders (receipt*.json)")
    parser.add_argument("--names", help="JSON {receipt folder or file: build name} for receipts named otherwise")
    parser.add_argument("--builds", help="JSON {build: {game_id, files: [{path, size}]}} of the live builds")
    parser.add_argument("--library", help="the character library (meta.json kinds)")
    parser.add_argument("--write", nargs="?", const="", default=None,
                        help="merge the rejects and the build index into the reject file (default path)")
    parser.add_argument("--replace-audit", action="store_true",
                        help="drop earlier audit rejects of the audited titles that this run no longer flags (after a "
                             "fit fix: audit the rebuilt receipts with --title re4 --replace-audit; operator rejects "
                             "always stay)")
    parser.add_argument("--title", action="append", choices=donor_rejects.TITLES,
                        help="only these titles (repeatable)")
    parser.add_argument("--table", action="store_true", help="print the Markdown tables")
    parser.add_argument("--json", help="write the judged rows here")
    args = parser.parse_args(argv)
    names = json.loads(Path(args.names).read_text(encoding="utf-8")) if args.names else None
    rows = audit_paths(args.receipts, names=names, library=Path(args.library) if args.library else None)
    if args.title:
        rows = [r for r in rows if r["title"] in args.title]
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    if args.table:
        print(table(rows))
    found = rejects(rows)
    for title in sorted({r["title"] for r in rows} | set(args.title or ())):
        found.setdefault(title, {})                # an audited title with no reject: --replace-audit clears it
    print(json.dumps({"rows": len(rows), "rejects": {t: sorted(v) for t, v in found.items()}}, indent=1))
    if args.write is not None:
        builds = json.loads(Path(args.builds).read_text(encoding="utf-8")) if args.builds else None
        donor_rejects.merge(found, index(rows, builds), override=args.write or None, replace_audit=args.replace_audit)
        print(f"written: {donor_rejects.path(args.write or None)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
