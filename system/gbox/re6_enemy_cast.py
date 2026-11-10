"""RE6 Switch enemy cast: library characters on the Mercenaries enemy classes, as one LayeredFS probe build.

Operator 2026-11-10, watching RE6: "why are no zombies replaced with characters? ... i basically only want character
swapped builds from here on out." RE5 already plays its enemies as library donors (`re5_enemy_writer`, the
`recovery-series-*` builds); this is the RE6 counterpart on top of the players the gallery probe already swaps.

What it does, offline (nothing here launches a game, installs a build or touches a session):

1. **Which classes, where.** `mercs_sets` reads the 20 Mercenaries stage sets (`s120NSoft` THE MERCENARIES,
   `s121NSoft` NO MERCY): the enemy census (`re6_switch_enemies.stage_census`) and every other archive a set names
   (weapons `uWp`, items `uIt`, set models `uSm`). The No Mercy placements order the classes.
2. **Which classes can be dressed.** `re6_switch_enemies.humanoid_gate`: an upright T-posed humanoid with the 18 role
   ids. The J'avo (`uEm1000`, `uEm1200`, `uEm1400`) and the zombies pass; the B.O.W.s (Napad, Strelats, the dogs ...)
   are reported and left native.
3. **Which donor.** A seeded draw from the library (`re6_switch_cast.donor_pool`, the `full` 18-role tier, source games
   taken in turn, no character twice, nobody the gallery probe already put on a player), minus the cross-title reject
   list (`gbox-data/mercs/donor_rejects.json`, role `enemy`, titles `re6` and `all`) and anything the library does not
   call a character. Each candidate is authored and measured (`re6_switch_enemies.build_class` / `fit_report`); a
   refusal is recorded with its fit report and the next candidate is tried.
4. **The build.** Each dressed class archive goes to `<out>/romfs/nativeNXx64/arc/NX/<class>.arc` with `receipt.json`
   beside it; `manifest` lists a base build's files as unchanged `{"from": ...}` entries plus these archives, for one
   `switch_mods op=write`.

Every receipt says `live_verified: false`: no RE6 enemy archive written by gBox has been booted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import struct
import time
from pathlib import Path

from . import mt_arc, mt_model, re6_switch_enemies as E, re6_switch_models as M

GAME_ID = M.GAME_ID
TITLE_ID = M.TITLE_ID
TITLE = "re6"
DEFAULT_NAME = "recovery-re6-enemy-cast-01-20261110"
TEX_HASH = 0x241F5DEB
_REF = re.compile(rb"(?<![A-Za-z0-9])(u[A-Z][a-z][0-9A-Za-z_]{2,40})(?![0-9A-Za-z_])")
STAGE_NAMES = {"s1200": "Rail Yard", "s1201": "Requiem for War", "s1202": "Urban Chaos", "s1203": "Mining the Depths",
               "s1204": "High Seas Fortress", "s1205": "The Catacombs", "s1206": "Steel Beast",
               "s1207": "Rooftop Mission", "s1208": "Creature Workshop", "s1209": "Liquid Fire"}
#: Archives every Mercenaries round may hold beside a stage's own: the players, the mode's UI and the families' shared
#: motion archives. A texture path in one of these is never written for a donor.
ALWAYS = re.compile(r"^(uPl|Merce|uEm\d{4}Base)")
MAX_TRIES = 14


def toc(path: Path) -> list[tuple[str, int]]:
    """(name, type hash) of every entry of an MT archive, from its table only."""
    with open(path, "rb") as fh:
        head = fh.read(8)
        if len(head) < 8 or head[:4] != b"ARC\0":
            return []
        count = struct.unpack_from("<H", head, 6)[0]
        table = fh.read(count * 0x50)
    out = []
    for i in range(min(count, len(table) // 0x50)):
        base = i * 0x50
        out.append((table[base:base + 0x40].split(b"\0", 1)[0].decode("ascii", "replace"),
                    struct.unpack_from("<I", table, base + 0x40)[0]))
    return out


def texture_index(nx: Path) -> dict[str, set[str]]:
    """{TEX path: the archive stems that carry it} over every archive of the title."""
    index: dict[str, set[str]] = {}
    for path in sorted(Path(nx).glob("*.arc")):
        for name, digest in toc(path):
            if digest == TEX_HASH:
                index.setdefault(name, set()).add(path.stem)
    return index


def set_refs(soft_archive: bytes, existing: set[str]) -> dict[str, int]:
    """{archive stem: mentions} of every existing archive a stage set's entries name."""
    import zlib

    found: dict[str, int] = {}
    for entry in mt_arc.parse(bytes(soft_archive)).entries:
        try:
            raw = zlib.decompress(entry.data)
        except zlib.error:
            raw = entry.data
        for match in _REF.finditer(raw):
            name = match.group(1).decode()
            if name in existing:
                found[name] = found.get(name, 0) + 1
    return found


def mercs_sets(nx: Path) -> dict[str, dict]:
    """{set code: {stage, mode, census, refs}} for the 20 Mercenaries sets present under `nx`."""
    nx = Path(nx)
    existing = {p.stem for p in nx.glob("*.arc")}
    out = {}
    for n in range(10):
        for mode, code in (("mercenaries", f"s120{n}Soft"), ("no_mercy", f"s121{n}Soft")):
            path = nx / f"{code}.arc"
            if not path.is_file():
                continue
            data = path.read_bytes()
            out[code] = {"stage": f"s120{n}", "stage_name": STAGE_NAMES.get(f"s120{n}"), "mode": mode,
                         "census": E.stage_census(data)["classes"], "refs": set_refs(data, existing)}
    return out


def placements(sets: dict, mode: str = "no_mercy") -> dict[str, int]:
    """{class: placements over every set of `mode`}, most placed first."""
    total: dict[str, int] = {}
    for row in sets.values():
        if row["mode"] == mode:
            for cls, count in row["census"].items():
                total[cls] = total.get(cls, 0) + count
    return dict(sorted(total.items(), key=lambda kv: (-kv[1], kv[0])))


def coload(sets: dict, existing: set[str]) -> dict[str, set[str]]:
    """{class: the archive stems that can be loaded beside it}: for every set that places the class, the set, its
    stage, every class and archive the set names and their own sub-archives (`uEm5000Helmet` ...), plus `ALWAYS`."""
    always = {stem for stem in existing if ALWAYS.match(stem)}
    out: dict[str, set[str]] = {}
    for code, row in sets.items():
        names = set(row["census"]) | set(row["refs"]) | {code, row["stage"]}
        subs = family_subs(names, existing)
        for cls in row["census"]:
            out.setdefault(cls, set()).update(names | subs | always)
    return out


def family_subs(names: set[str], existing: set[str]) -> set[str]:
    """The sub-archives a class may load with it: its own (`uEm5000Helmet`, `uEm5000Axe`) and its family's lettered
    ones (`uEm4301Pipe` beside `uEm4300`: one hundred-block, a digit, then letters). Never another plain class
    (`uEm5005`). Measured 2026-11-10: Ubistvo's only usable albedo `em4300_pipe00_BM` is also in `uEm4301Pipe`."""
    out = set()
    for name in names:
        family = name[:6] + r"\d" if re.fullmatch(r"uEm\d{4}", name) else re.escape(name)
        pattern = re.compile(rf"^(?:{re.escape(name)}|{family})[A-Za-z_]+$")
        out |= {stem for stem in existing if pattern.match(stem)}
    return out


def conflicts(index: dict[str, set[str]], loaded: set[str], cls: str) -> dict[str, list[str]]:
    """{TEX path of `cls`: the other loaded archives that carry the same path}."""
    return {path: sorted((stems & loaded) - {cls}) for path, stems in index.items()
            if cls in stems and (stems & loaded) - {cls}}


# --- donors --------------------------------------------------------------------------------------------------------

def rejected(path: Path | None = None) -> dict[str, str]:
    """{slug: reason} of the donors the reject list refuses for RE6 enemies (titles `re6` and `all`, role `enemy`).
    Uses `gbox.donor_rejects` when present; else reads the file in its format. A missing file refuses nothing."""
    try:
        from . import donor_rejects                                   # the cross-title list's own reader
        return donor_rejects.rejected(TITLE, "enemy", override=path)
    except ImportError:
        pass
    target = Path(path) if path else Path(os.environ.get("GBOX_DONOR_REJECTS") or
                                          Path(__file__).resolve().parents[1] / "gbox-data" / "mercs" /
                                          "donor_rejects.json")
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for key in ("all", TITLE):
        for slug, entry in ((doc.get("titles") or {}).get(key) or {}).items():
            roles = entry.get("roles") if isinstance(entry, dict) else None
            if isinstance(entry, dict) and (not roles or "enemy" in roles):
                out[slug] = f"donor_rejects ({key}): {entry.get('reason') or 'rejected'}"
    return out


def candidates(library: Path, *, seed: int, refused: dict[str, str] | None = None,
               exclude: tuple[str, ...] = ()) -> tuple[list[dict], dict[str, int]]:
    """(the seeded donor order, what was left out and why). Full 18-role rigs only, source games in turn, no character
    twice (`base_name`: two costumes of one character are one character); the reject list, the excluded slugs (and
    their characters) and non-characters are left out."""
    from . import re6_switch_cast as C

    pool = C.donor_pool(Path(library), tier="full")
    refused = refused or {}
    excluded_ids = {C.identity(meta) for meta in pool if meta["slug"] in exclude}
    excluded_names = {base_name(meta) for meta in pool if meta["slug"] in exclude}
    kept, skipped = [], {}
    for meta in pool:
        why = None
        if meta["slug"] in refused:
            why = "donor_rejects"
        elif meta["slug"] in exclude or C.identity(meta) in excluded_ids or base_name(meta) in excluded_names:
            why = "already a player in the base build"
        elif str(meta.get("kind") or "").lower() != "character":
            why = f"library kind {meta.get('kind')!r}"
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        kept.append(meta)
    order, seen = [], set()
    for meta in C._draw(kept, len(kept), random.Random(seed), True):
        name = base_name(meta)
        if name in seen:
            skipped["another costume of a character already drawn"] = skipped.get(
                "another costume of a character already drawn", 0) + 1
            continue
        seen.add(name)
        order.append(meta)
    return order, skipped


def base_name(meta: dict) -> str:
    """The character a library entry is, without its costume: 'Toni Cipriani (mask)' and 'Toni Cipriani
    (short-sleeved shirt)' are one; 'Tank (costume 2) (Def Jam Vendetta PS2)' is 'tank'."""
    name = str(meta.get("name") or meta.get("slug") or "").lower()
    name = re.sub(r"\([^)]*\)", " ", name)
    name = re.sub(r"\b(costume|outfit|alt|variant|ver)\s*[\w.]*", " ", name)
    return re.sub(r"[^a-z0-9]+", " ", name).strip() or str(meta.get("slug"))


# --- the build -----------------------------------------------------------------------------------------------------

class Paths:
    """Who may write which albedo path. MT Framework keeps one resource per path, so every archive that can be loaded
    beside another carrying the same path must hold the same bytes for it. A path is usable for `cls`'s donor when
    every archive that carries it and can load beside any dressed carrier is itself dressed (`dressed`: their native
    records are collapsed, nothing native samples it) and no other class's donor claimed it; the cast then writes the
    donor's atlas into every dressed copy (`share_atlases`)."""

    def __init__(self, index: dict[str, set[str]], loaded: dict[str, set[str]], dressed: set[str]):
        self.index, self.loaded, self.dressed = index, loaded, set(dressed)
        self.claims: dict[str, str] = {}

    def check(self, cls: str):
        def check(path: str):
            carriers = self.index.get(path, set())
            for holder in (carriers & self.dressed) | {cls}:
                bad = (self.loaded.get(holder, set()) & carriers) - self.dressed - {cls}
                if bad:
                    return False, f"albedo also loaded from {', '.join(sorted(bad)[:5])} (not dressed)", ()
            owner = self.claims.get(path)
            if owner and owner != cls:
                return False, f"albedo claimed by {owner}'s donor", ()
            return True, None, sorted((carriers & self.dressed) - {cls})
        return check


def _class_plan(nx: Path, cls: str, path_check=None, others: dict | None = None) -> dict:
    """The class's gate, carrier groups and donor material (no donor yet)."""
    data = (Path(nx) / f"{cls}.arc").read_bytes()
    arc = mt_arc.parse(data)
    gate = E.humanoid_gate(arc, cls)
    plan = {"class": cls, "archive": f"{cls}.arc", "gate": gate, "source_bytes": len(data)}
    if not gate["passed"]:
        return plan
    index, mrl, raw = E.class_body(arc, cls)
    model = mt_model.parse_mod(raw)
    plan["carriers"] = E.carrier_groups(model)
    plan["native_vertices"] = model.header()["vertex_count"]
    plan["native_records"] = model.header()["mesh_count"]
    try:
        plan["material"] = E.donor_material_choice(arc, model, mrl, others=others, path_check=path_check)
    except E.EnemyError as exc:
        plan["material_error"] = str(exc)
        plan["material_refused"] = getattr(exc, "refused", None)
    return plan


def _franchise(meta: dict) -> str:
    from . import re6_switch_cast as C
    return C.franchise(meta)


def dressable(nx: Path, classes: list[str], paths: Paths) -> tuple[set[str], dict]:
    """The classes the cast can dress (the humanoid gate and a usable material), as a fixpoint: a class whose only
    materials share their albedo with an undressable class drops out, which can drop others."""
    gates = {cls: _class_plan(nx, cls) for cls in classes}
    dressed = {cls for cls, plan in gates.items() if plan["gate"]["passed"] and plan.get("carriers", {}).get("groups")}
    while True:
        paths.dressed = set(dressed)
        keep = {cls for cls in dressed if "material" in _class_plan(nx, cls, paths.check(cls))}
        if keep == dressed:
            return dressed, gates
        dressed = keep


def share_atlases(folder: Path, assignments: dict[str, dict], written: dict[str, dict]) -> dict[str, list]:
    """Write each claimed albedo path's donor atlas into every other written class archive that carries the path, so
    whichever archive the game loads the path from, it holds that donor's atlas. Returns {class: [rows]}."""
    from PIL import Image

    from .re6_switch_tex import TexError, from_arc_entry, replace_albedo

    out: dict[str, list] = {}
    for cls, row in written.items():
        path = Path(folder) / f"{cls}.arc"
        data = path.read_bytes()
        arc = mt_arc.parse(data)
        names = {e.name.lower(): e for e in arc.entries if e.hash == TEX_HASH}
        replacements = {}
        for albedo, claim in assignments.items():
            if claim["class"] == cls or albedo.lower() not in names:
                continue
            try:
                surface = from_arc_entry(names[albedo.lower()])
            except TexError:
                continue
            if surface.format != E.ALBEDO_FORMAT:
                continue

            def writer(surface, _image=claim["atlas"]):
                scaled = _image if _image.size == (surface.width, surface.height) else _image.resize(
                    (surface.width, surface.height), Image.LANCZOS)
                return replace_albedo(surface.data, scaled, chroma=True)
            replacements[albedo] = writer
            out.setdefault(cls, []).append({"texture": albedo, "donor": claim["donor"], "for_class": claim["class"]})
        if replacements:
            data, rows = M.replace_textures(data, replacements)
            path.write_bytes(data)
            row["archive_sha256"] = hashlib.sha256(data).hexdigest()
            row["archive_bytes"] = len(data)
            for entry in rows:
                for shared in out[cls]:
                    if shared["texture"] == entry.get("texture"):
                        shared.update({k: entry.get(k) for k in ("entry", "width", "height", "output_sha256")})
    return out


def consistency(sets: dict, existing: set[str], index: dict[str, set[str]], assignments: dict[str, dict],
                written: set[str]) -> list[dict]:
    """Every stage set where an archive that can load carries a claimed albedo path but was not written (it would hold
    the native texture under the donor's path). Empty when the cast is consistent."""
    always = {stem for stem in existing if ALWAYS.match(stem)}
    out = []
    for code, row in sets.items():
        names = set(row["census"]) | set(row["refs"]) | {code, row["stage"]}
        names |= family_subs(names, existing) | always
        for albedo, claim in assignments.items():
            stale = sorted((index.get(albedo, set()) & names) - written)
            if stale and claim["class"] in names:
                out.append({"set": code, "texture": albedo, "donor": claim["donor"], "native_copies": stale})
    return out


def build(romfs: Path, library: Path, out_dir: Path, *, name: str = DEFAULT_NAME, seed: int = 20261110,
          classes: list[str] | None = None, exclude: tuple[str, ...] = (), rejects_path: Path | None = None,
          max_tries: int = MAX_TRIES, previews: bool = False, progress=print) -> dict:
    """Dress every humanoid Mercenaries class (or `classes`) as a different library donor and write the archives and
    the receipt under `out_dir`. Returns the receipt."""
    from . import mtf_materials

    romfs, library, out_dir = Path(romfs), Path(library), Path(out_dir)
    nx = romfs / M.ARCHIVE_DIR
    folder = out_dir / "romfs" / M.ARCHIVE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    started = time.time()
    sets = mercs_sets(nx)
    counts = placements(sets)
    existing = {p.stem for p in nx.glob("*.arc")}
    index = texture_index(nx)
    loaded = coload(sets, existing)
    refused_list = rejected(rejects_path)
    order, skipped = candidates(library, seed=seed, refused=refused_list, exclude=exclude)
    progress(f"{len(order)} donor candidates ({skipped}); {len(refused_list)} on the reject list")
    wanted = classes or list(counts)
    paths = Paths(index, loaded, set())
    dressed, gates = dressable(nx, wanted, paths)
    progress(f"dressable: {sorted(dressed)}")
    built: dict[tuple, tuple] = {}          # (class, donor, material, carriers) -> (payload, receipt, atlas)
    refusals: dict[tuple, dict] = {}        # (class, donor) -> the attempt
    for round_number in range(1, 5):
        paths.dressed, paths.claims = set(dressed), {}
        rows, plans, used, assignments, written = [], {}, set(), {}, {}
        failed = []
        cursor = 0
        for f in folder.glob("*.arc"):
            f.unlink()
        for cls in wanted:
            if cls not in dressed:
                plan = gates[cls]
                plans[cls] = {k: v for k, v in plan.items() if k != "material"}
                why = ("not a humanoid the writer dresses" if not plan["gate"]["passed"] else
                       "no carrier group covers the chest" if not plan.get("carriers", {}).get("groups") else
                       "no material can carry a donor (shared albedo or none opaque)")
                rows.append({"class": cls, "placements": counts.get(cls, 0), "skipped": why, "gate": plan["gate"]})
                continue
            plan = _class_plan(nx, cls, paths.check(cls))
            plans[cls] = {k: v for k, v in plan.items() if k != "material"} | (
                {"material": {k: v for k, v in plan["material"].items() if k != "refused"},
                 "material_refused": plan["material"]["refused"]} if "material" in plan else {})
            if "material" not in plan:
                failed.append(cls)
                rows.append({"class": cls, "placements": counts.get(cls, 0), "skipped": plan.get("material_error")})
                continue
            choice, carriers = plan["material"], plan["carriers"]["groups"]
            native = (nx / f"{cls}.arc").read_bytes()
            budget = max(90000, int(1.5 * plan["native_vertices"]))
            attempts, done = [], None
            while len(attempts) < max_tries and cursor < len(order):
                meta = order[cursor]
                cursor += 1
                if meta["slug"] in used:
                    continue
                key = (cls, meta["slug"])
                if key in refusals:
                    attempts.append(refusals[key])
                    continue
                source = library / meta["slug"] / meta["model"]
                roles = meta["rig"]["roles"]
                attempt = {"donor": meta["slug"], "name": meta.get("name"), "source_game": _franchise(meta)}
                estimate = int((meta.get("stats") or {}).get("vertices") or 0)
                cache = (cls, meta["slug"], choice["index"], tuple(carriers))
                try:
                    if cache in built:
                        payload, receipt, atlas = built[cache]
                    else:
                        if estimate and estimate * len(carriers) > 1.3 * budget:
                            raise E.DonorRefused(f"about {estimate} vertices x {len(carriers)} carriers is past the "
                                                 f"{budget} budget", {"codes": ["heavy"], "vertices": estimate,
                                                                      "copies": len(carriers), "vertex_budget": budget})
                        deviation = M.pose_deviation(native, source, roles)
                        if deviation["max_degrees"] > E.FIT["rest_degrees"]:
                            raise E.DonorRefused(f"rests {deviation['max_degrees']:.0f} degrees off the bind pose "
                                                 f"(keep only)", {"codes": ["stretched"],
                                                                  "rest_pose_deviation": deviation})
                        vertices, triangles, atlas, _appearance = mtf_materials.source_mesh(
                            source, atlas_size=(1024, 1024), strict_samplers=False)
                        atlas = E.opaque_atlas(atlas)
                        payload, receipt = E.build_class(native, cls, source, roles, choice=choice, carriers=carriers,
                                                         geometry=(vertices, triangles), atlas=atlas,
                                                         kind=meta.get("kind"), vertex_budget=budget,
                                                         deviation=deviation)
                        built[cache] = (payload, receipt, atlas)
                except E.DonorRefused as exc:
                    attempt.update(refused=str(exc), fit=exc.report)
                    refusals[key] = attempt
                    attempts.append(attempt)
                    continue
                except Exception as exc:                      # noqa: BLE001 - one donor never stops the build
                    attempt["refused"] = f"{type(exc).__name__}: {exc}"[:400]
                    refusals[key] = attempt
                    attempts.append(attempt)
                    continue
                (folder / f"{cls}.arc").write_bytes(payload)
                used.add(meta["slug"])
                paths.claims[choice["albedo"]] = cls
                assignments[choice["albedo"]] = {"class": cls, "donor": meta["slug"], "atlas": atlas}
                done = receipt | {"donor": meta["slug"], "donor_name": meta.get("name"),
                                  "donor_source": (meta.get("source") or {}).get("game_title"),
                                  "donor_franchise": _franchise(meta), "donor_kind": meta.get("kind"),
                                  "placements": counts.get(cls, 0), "archive": f"{cls}.arc",
                                  "body": {"height_cm": receipt["fit"]["native"]["height_cm"],
                                           "width_cm": receipt["fit"]["native"]["width_cm"]},
                                  "refused_before": attempts}
                if previews:
                    try:
                        done["preview"] = preview(payload, cls, out_dir / "previews", albedo=choice["albedo"])
                    except Exception as exc:                  # noqa: BLE001 - evidence only
                        done["preview"] = f"failed: {type(exc).__name__}: {exc}"[:200]
                progress(f"[round {round_number}] {cls}: {meta['slug']} ({meta.get('name')}) in {len(carriers)} "
                         f"carriers, fit {receipt['fit']['ratios']}, after {len(attempts)} refusals")
                break
            if done is None:
                failed.append(cls)
                rows.append({"class": cls, "placements": counts.get(cls, 0), "skipped": "no donor passed",
                             "refused": attempts})
                progress(f"[round {round_number}] {cls}: no donor passed in {len(attempts)} tries")
                continue
            rows.append(done)
            written[cls] = done
        if not failed:
            break
        dressed -= set(failed)                               # their native copies of shared paths stay native
        progress(f"round {round_number}: {failed} not dressed; replanning without them")
    shared = share_atlases(folder, assignments, written)
    for cls, extra in shared.items():
        written[cls]["shared_atlases"] = extra
    for cls, row in written.items():                         # re-read every written archive against the shipped one
        row["verify"] = E.verify_class((nx / f"{cls}.arc").read_bytes(), (folder / f"{cls}.arc").read_bytes(), cls,
                                       carriers=row["carrier_groups"], material_index=row["material"]["index"],
                                       albedos=(row["material"]["albedo"],) + tuple(
                                           s["texture"] for s in row.get("shared_atlases", ())))
    stale = consistency(sets, existing, index, assignments, set(written))
    files = {f"romfs/{M.ARCHIVE_DIR.as_posix()}/{row['archive']}": {"bytes": row["archive_bytes"],
                                                                    "sha256": row["archive_sha256"]}
             for row in written.values()}
    stage_rows = {}
    for code, row in sets.items():
        dressed_by = {cls: (written.get(cls) or {}).get("donor") for cls in row["census"]}
        stage_rows[code] = {"stage": row["stage"], "stage_name": row["stage_name"], "mode": row["mode"],
                            "classes": row["census"], "dressed": dressed_by,
                            "dressed_share": round(sum(n for c, n in row["census"].items() if dressed_by.get(c)) /
                                                   max(1, sum(row["census"].values())), 3)}
    receipt = {"name": name, "build": name, "title_id": TITLE_ID, "game_id": GAME_ID, "route": "re6_enemy_cast.build",
               "recipe": "re6_switch_enemies.build_pool",      # the donor-fit audit reads RE6 enemy pools by this
               "seed": seed, "live_verified": False, "gameplay_verified": False,
               "built": time.time(), "seconds": round(time.time() - started, 1), "rounds": round_number,
               "files": files, "classes": rows, "plans": plans, "stages": stage_rows,
               "shared_texture_consistency": stale or "every loadable copy of each claimed albedo holds its donor",
               "donor_pool": {"candidates": len(order), "left_out": skipped,
                              "reject_list": str(rejects_path or "default"), "rejected": len(refused_list),
                              "excluded": list(exclude)},
               "placements_no_mercy": counts, "fit_limits": {k: list(v) if isinstance(v, tuple) else v
                                                             for k, v in E.FIT.items()},
               "what_must_be_seen": [
                   "at a stage that places a dressed class, those enemies drawn as the listed donors, about the native "
                   "height, feet on the floor, moving with the class's own motions (walk, grab, stagger, death)",
                   "the donors in their own colours (the atlas through the Y'CbCr albedo model Sonic was proven on)",
                   "every enemy of a class the same donor; other classes, the players and the stage as in the base build",
                   "a J'avo that mutates keeps the donor and grows the native mutation from the other archive"],
               "failure_signs": [
                   "a hang or a black screen at stage load: a rewritten archive - bisect by class (one archive per build)",
                   "stock enemies: the overlay was not read, or the stage loads another archive for the class",
                   "invisible enemies that still attack and take hits: no carrier group is drawn for that spawn - the "
                   "chest-band rule missed the groups the game shows (each class's carrier_groups)",
                   "black or garbled donors: the albedo or its material (each class's material: function, "
                   "transparency, mask) - or a shared albedo loaded from an archive the cast did not write",
                   "a donor that vanishes when hurt or at death: the carriers do not cover that state's groups",
                   "holes in a zombie donor at rest: the alpha-clip / damage-map transparency is not opaque at rest"]}
    (out_dir / "receipt.json").write_text(json.dumps(receipt, indent=1, default=_json), encoding="utf-8")
    return receipt


def _json(value):
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, Path):
        return str(value)
    return str(value)


def preview(archive: bytes, cls: str, folder: Path, *, albedo: str | None = None, size: int = 384) -> dict:
    """An offline render of the first donor record of a written class archive: its positions, UVs and triangles read
    back from the bytes, textured with the written albedo decoded through the Y'CbCr model (`Surface.albedo`), flat
    shaded, bind pose. What the writer put there, not a game frame."""
    import numpy as np
    from PIL import Image

    from . import characters, melee_models, mtf_author
    from .re6_switch_tex import from_arc_entry

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    arc = mt_arc.parse(bytes(archive))
    index, _mrl, _raw = E.class_body(arc, cls)
    model = mt_model.parse_mod(E._raw(arc.entries[index]))
    record = next(i for i, r in enumerate(model.meshes()) if r["level_of_detail"] == 0xFF
                  and r["vertex_format"] == E.FOUR_WEIGHTS and r["vertex_index"] == 0 and r["mesh_type"] == 0xFFFF)
    positions = model.positions(record)
    uvs = model.uvs(record)
    triangles = mtf_author.mesh_triangles(model, record)
    atlas = None
    if albedo:
        entry = next((e for e in arc.entries if e.name.lower() == albedo.lower() and e.hash == TEX_HASH), None)
        if entry is not None:
            rgb, _opacity = from_arc_entry(entry).albedo(0)
            atlas = Image.fromarray(rgb, "RGB")
            atlas.save(folder / f"{cls}_albedo.png")
    table = model.bone_table()
    joints = []
    for i, x, y, z in model.bone_world():
        parent = int(table["parents"][i])
        matrix = np.eye(4)
        matrix[:3, 3] = (x, y, z)
        joints.append({"parent": parent if 0 <= parent < len(table["parents"]) else -1, "world": matrix})
    count = len(positions)
    prim = {"pos": np.asarray(positions, np.float32), "nrm": np.tile(np.float32([0, 0, 1]), (count, 1)),
            "uv": np.asarray(uvs or [(0, 0)] * count, np.float32), "tris": np.asarray(triangles, np.int64),
            "J": np.zeros((count, 4), np.int64), "W": np.zeros((count, 4), np.float32), "color": (200, 200, 200, 255)}
    prim["W"][:, 0] = 1.0
    if atlas is not None:
        prim["tex"] = np.asarray(atlas.convert("RGBA"), np.uint8)
    gltf = folder / f"{cls}.gltf"
    png = folder / f"{cls}.png"
    melee_models.write_gltf(gltf, joints, [prim], 1.0, "re6_enemy", [f"j{i:03d}" for i in range(len(joints))])
    characters.render_preview(gltf, png, size=size, depth=True)
    return {"png": str(png), "record": record, "vertices": count, "triangles": len(triangles),
            "albedo_decoded": bool(atlas is not None), "what": "offline render of the written bytes, not a game frame"}


def manifest(out_dir: Path, base_dir: Path | None = None) -> dict[str, dict]:
    """The `switch_mods op=write` changes: every overlay file of `base_dir` (a build folder: romfs/..., exefs/...) as
    an unchanged {"from": absolute path}, then the dressed class archives of `out_dir`. A path in both is refused."""
    changes: dict[str, dict] = {}
    if base_dir is not None:
        base_dir = Path(base_dir).resolve()
        for top in ("exefs", "romfs"):
            for path in sorted((base_dir / top).rglob("*")) if (base_dir / top).is_dir() else []:
                if path.is_file() and not path.name.endswith((".part", ".tmp")):
                    changes[path.relative_to(base_dir).as_posix()] = {"from": str(path)}
    out_dir = Path(out_dir).resolve()
    for path in sorted((out_dir / "romfs").rglob("*.arc")):
        rel = path.relative_to(out_dir).as_posix()
        if rel in changes:
            raise ValueError(f"{rel} is in the base build too: the enemy cast would overwrite it")
        changes[rel] = {"from": str(path)}
    return changes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gbox.re6_enemy_cast", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="dress the classes and write the archives + receipt")
    b.add_argument("--romfs", required=True, help="the extracted RE6 RomFS (holds nativeNXx64/arc/NX)")
    b.add_argument("--library", required=True, help="the character library (gbox-cache/characters)")
    b.add_argument("--out", required=True)
    b.add_argument("--name", default=DEFAULT_NAME)
    b.add_argument("--seed", type=int, default=20261110)
    b.add_argument("--classes", nargs="*", default=None)
    b.add_argument("--exclude", nargs="*", default=[], help="donor slugs already on the players")
    b.add_argument("--rejects", default=None, help="the donor reject list (default gbox-data/mercs/donor_rejects.json)")
    b.add_argument("--previews", action="store_true")
    m = sub.add_parser("manifest", help="the switch_mods changes: a base build's files + the dressed archives")
    m.add_argument("--out", required=True)
    m.add_argument("--base", default=None)
    m.add_argument("--write", default=None, help="write the changes JSON here")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        receipt = build(Path(args.romfs), Path(args.library), Path(args.out), name=args.name, seed=args.seed,
                        classes=args.classes, exclude=tuple(args.exclude),
                        rejects_path=Path(args.rejects) if args.rejects else None, previews=args.previews)
        print(json.dumps({"files": receipt["files"], "seconds": receipt["seconds"],
                          "classes": [{k: r.get(k) for k in ("class", "donor", "donor_name", "skipped")}
                                      for r in receipt["classes"]]}, indent=1))
        return 0
    changes = manifest(Path(args.out), Path(args.base) if args.base else None)
    text = json.dumps(changes, indent=1)
    if args.write:
        Path(args.write).write_text(text, encoding="utf-8")
        print(f"{len(changes)} changes -> {args.write}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
