"""Whole-cast swap: replace the entire cast of one game with the entire cast of another ("everyone in Phantasy Star
Online as the Def Jam wrestlers", "the Jet Grind Radio crew as the SmackDown! 2 roster"), built as ONE mod.

`characters op=cast_swap target_game=<id|title> source=<game id|title|group> [mapping=auto|random|by_role|alternate]
[assign=random] [seed] [prefer=<source>] [slots=all|main|enemies|bots|campaign|<comma list>]
[assignments=[{slot, character}]] [plan_only] [launch]` routes here. `assign=random` (any game) deals the source's
donors at random over the chosen slots: seeded, no donor repeats before every donor has been used, every character name
once before a name repeats, `prefer=` donors first.

1. Slots: the target's writer lists them (gbox.char_coverage.cast_slots: the writer module's cast_slots()). Aggregate
   slots (enemy:boomas, drivers, pedestrians, peds:all, roster) and aliases (JGR / Crazy Taxi `player`) are dropped so
   every model is assigned once; slots the writer marks not_working (the PSO player class) are skipped with the reason.
2. Donors: every collection entry of the source (a game id / title / abbreviation, an extractor name, or a group such
   as "wrestlers": No Mercy, WCW, SmackDown! 2 and Def Jam entries), costumes deduplicated (one per character), head-
   size variants left out. The quality gate refuses an entry that fails the collection's retarget check (model +
   preview verified, body roles mapped) with the reason, and re-extracts an entry made by an older reader than the
   current DEDICATED one (JGR reader v1 -> v2: v1 entries carry the cel-shading outline shell and wrong textures).
3. Mapping: by_role puts the lead donors on player slots and deals the rest by body size (slot size hints vs the
   donor's height relative to its own game's cast), random deals a seeded shuffle; both are deterministic per seed
   and never repeat a donor before every donor has been used. The operator can edit the plan (assignments).
4. Build, one mod: writers that take a pairs list get it (DOA2 roster, the wrestling games' match, PSO enemies in one
   GDI rebuild, Vice City peds in one gta3.img rebuild); the others run the common chained path (`chain`): each slot's
   writer step is applied to the output of the previous step on one staged copy of the changed files (JGR's
   PLAYER.AFS, Crazy Taxi's polDC0.all), never the original, and the image is written once. Every slot reports its
   donor and built / failed with the reason.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import statistics
import struct
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------- source groups and names

# Named groups of source games, by the DEDICATED extractor that made the entries (characters.DEDICATED names).
GROUPS = {
    "doa": {"label":"Dead or Alive universe (DOA2 + DOA++)","extractors":["doa2","doapp"],
            "aliases":["doa","dead or alive","dead or alive universe","doa universe","dead or alive characters"]},
    "wrestlers": {"label": "Wrestlers (No Mercy, WCW, SmackDown! 2, Def Jam)",
                  "extractors": ["nomercy", "worldtour", "revenge", "smackdown2", "defjam_vendetta_ps2", "defjam_vendetta"],
                  "aliases": ["wrestlers", "wrestler", "wrestling", "wrestling games", "the wrestlers"]},
    "fighters": {"label": "Fighters (DOA2, DOA++, MvC2, Melee)", "extractors": ["doa2", "doapp", "mvc2", "melee"],
                 "aliases": ["fighters", "fighting games", "fighting game characters"]},
    "sega": {"label": "Dreamcast Sega casts (JGR, SA1, SA2, PSO, Shenmue)",
             "extractors": ["jgr", "sa1", "sa2", "pso", "shenmue"], "aliases": ["sega", "dreamcast"]},
    "sonic": {"label": "Sonic characters (Sonic Adventure 1 + 2)", "extractors": ["sa1", "sa2"],
              "aliases": ["sonic", "sonic characters", "sonic games", "sonic adventures", "sonic adventure 1 and 2",
                          "sonic adventure 1 + 2", "sa1 + sa2", "sa1 and sa2"]},
    # every Mario-series model in the collection (Super Mario 64 DS, Super Mario 64 from the ROM, the Render96 HD
    # models imported through the Blender round trip with donor_group "mario"), collapsed to the best one per
    # character after the quality gate (best_per_character: HD > SM64 decomp reader > SM64 DS > the 20-joint SM64 entry)
    "mario": {"label": "Mario characters (best of HD / Super Mario 64 / Super Mario 64 DS per character)",
              "extractors": ["sm64ds", "sm64"], "donor_group": "mario", "best_per_character": True,
              "aliases": ["mario", "mario characters", "mario games", "super mario", "nintendo", "mushroom kingdom",
                          "mario hd", "hd mario"]},
}
# donor rank inside a best_per_character group: meta donor_quality first, then the reader that made the entry
QUALITY_RANK = {"hd": 30, "rom": 20}
EXTRACTOR_RANK = {"sm64ds": 10, "sm64": 5}
CHARACTER_PREFIX = re.compile(r"^(?:sm64ds|sm64|r96|render96)_")
CHARACTER_SUFFIX = re.compile(r"_(?:hd|r96|render96)(?:_\d+)?$")


def character_key(meta: dict) -> str:
    """Which character an entry is, across games and packs: meta['character'] (the SM64 decomp reader and the
    Render96 import set it), else the slug without its game prefix / pack suffix (sm64ds_mario, sm64_mario,
    mario_hd -> mario; metal_wario stays metal_wario)."""
    c = str(meta.get("character") or "").strip().lower()
    if c:
        return re.sub(r"[^a-z0-9]+", "_", c).strip("_")
    s = CHARACTER_SUFFIX.sub("", CHARACTER_PREFIX.sub("", str(meta.get("slug") or "").lower()))
    return s or re.sub(r"[^a-z0-9]+", "_", re.sub(r"\(.*?\)", "", base_name(meta))).strip("_")


def donor_rank(meta: dict) -> tuple:
    """Higher is better: the source quality, then the triangle count (more detail survives decimation better)."""
    q = QUALITY_RANK.get(str(meta.get("donor_quality") or ""), EXTRACTOR_RANK.get(extractor_of(meta) or "", 0))
    return (q, int((meta.get("stats") or {}).get("triangles") or 0))


def best_per_character(donors: list[dict]) -> tuple[list[dict], list[dict]]:
    """One donor per character (character_key), the best ranked one; -> (kept in the input order, superseded rows
    [{slug, name, character, by}])."""
    best: dict[str, dict] = {}
    for m in donors:
        k = character_key(m)
        if k not in best or donor_rank(m) > donor_rank(best[k]):
            best[k] = m
    keep = [m for m in donors if best[character_key(m)] is m]
    gone = [{"slug": m["slug"], "name": m.get("name"), "character": character_key(m),
             "by": best[character_key(m)]["slug"]} for m in donors if best[character_key(m)] is not m]
    return keep, gone


def in_group(meta: dict, group: str) -> bool:
    """Is this entry part of a named source group (by the reader that made it, or its own donor_group)?"""
    g = GROUPS[group]
    dg = meta.get("donor_group")
    return extractor_of(meta) in set(g["extractors"]) or (bool(g.get("donor_group")) and (
        dg == g["donor_group"] or (isinstance(dg, list) and g["donor_group"] in dg)))


def group_best(chars: list[dict], group: str = "mario", ready_only: bool = True) -> dict[str, str]:
    """{character: best slug} of a best_per_character group in a collection list (no gate run): the builders'
    `--mario-group` / `--pool mario`. ready_only drops entries whose replacement readiness is blocked / limited."""
    pool = [m for m in _candidates(chars) if in_group(m, group)]
    if ready_only:
        pool = [m for m in pool if ((m.get("readiness") or {}).get("status") or "ready") == "ready"]
    keep, _gone = best_per_character(pool)
    return {character_key(m): m["slug"] for m in keep}


DS_SOURCE = "Super Mario 64 DS (USA)"


def mario_side(slugs) -> tuple[str, str]:
    """(cast_source label, title words) for a build's Mario-side donors: the 'mario' group's label once any of them
    is an HD (*_hd) or Super Mario 64 (sm64_*) model, so special_builds.source_spec maps the marker back to
    source=mario; plain Super Mario 64 DS otherwise (the SM64 DS builds keep their wording)."""
    upgraded = any(s.endswith("_hd") or (s.startswith("sm64_") and not s.startswith("sm64ds_")) for s in slugs)
    if upgraded:
        return GROUPS["mario"]["label"], "Super Mario HD (best model per character)"
    return DS_SOURCE, "Super Mario 64 DS"


def library_metas(root: Path) -> list[dict]:
    """Every entry's meta.json in a library folder (the builders' CLI, no API)."""
    out = []
    for p in sorted(Path(root).glob("*/meta.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def upgrade_slugs(slugs: list[str], chars: list[dict], group: str = "mario") -> dict[str, str]:
    """{slug: best slug of the same character in the group} for the given slugs (unchanged when the group has no
    better entry): sm64ds_mario -> mario_hd when the HD model is in the collection."""
    best = group_best(chars, group)
    by_slug = {m.get("slug"): m for m in chars}
    out = {}
    for s in slugs:
        m = by_slug.get(s) or {"slug": s}
        out[s] = best.get(character_key(m), s)
    return out
# Short names the operator uses for games (target and source).
ABBREV = {"pso": "phantasy star online ver. 2", "jgr": "jet grind radio", "jsr": "jet grind radio",
          "jet set radio": "jet grind radio", "sa2": "sonic adventure 2", "sa1": "sonic adventure",
          "sonic adventure 1": "sonic adventure", "doa2": "dead or alive 2",
          "doa": "dead or alive 2", "sd2": "smackdown! 2", "smackdown 2": "smackdown! 2", "def jam": "def jam vendetta",
          "djv": "def jam vendetta", "no mercy": "wwf no mercy", "ct": "crazy taxi", "gta vc": "grand theft auto vice city",
          "vice city": "grand theft auto vice city", "mvc2": "marvel vs. capcom 2", "ff7": "final fantasy vii",
          "pe2": "parasite eve ii", "sm64": "super mario 64", "oot": "ocarina of time", "wcw": "wcw"}
AGGREGATE = {"enemies", "enemy", "enemy:all", "drivers", "pedestrians", "passengers", "peds", "peds:all", "all",
             "roster", "cast", "fares"}
SEQUEL = re.compile(r"\d+|ii|iii|iv|vi|vii|viii|ix")
MAIN_KINDS = {"player", "character", "fighter", "wrestler", "driver", "sage"}
STOP = {"the", "a", "of", "in", "usa", "europe", "japan", "ver", "disc", "and", "with", "as", "game", "games"}


def _words(s) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(s or "").lower())) - STOP


def expand(name: str) -> str:
    """'PSO' -> 'phantasy star online ver. 2' (operator abbreviations), else the name itself."""
    n = (name or "").strip()
    return ABBREV.get(n.lower(), n)


def extractor_of(meta: dict) -> str | None:
    """The DEDICATED reader that made a collection entry (from its source game's title / platform), or None."""
    from . import characters as C
    s = meta.get("source") or {}
    t, plat = (s.get("game_title") or "").lower(), s.get("platform") or ""
    for name, test, _roster, _run in C.DEDICATED:
        try:
            if test(t, plat):
                return name
        except Exception:                                  # noqa: BLE001 - a reader test never breaks the planner
            continue
    return None


def base_name(meta: dict) -> str:
    """The name without its costume tag: costumes of one character dedupe to one donor."""
    n = str(meta.get("texture_base_name") or meta.get("name") or meta.get("slug") or "").lower()
    n = re.sub(r"\s*\((?:costume|outfit|variant|alt)\.?\s*(?:\d+|[a-z])\)", "", n)
    n = re.sub(r"\s+(?:costume|outfit|alt)\s*(?:\d+|[a-z])\b", "", n)          # "fighter 000 costume a" (Def Jam GC)
    return re.sub(r"\s+", " ", n).strip()


def source_groups(chars: list[dict]) -> list[dict]:
    """The source menu: named groups first, then every source game of the collection, each with its usable count
    (retargetable characters after the costume dedupe)."""
    by_game: dict[str, dict] = {}
    ex_count: dict[str, int] = {}
    for m in _candidates(chars):
        s = m.get("source") or {}
        gid = s.get("game_id") or s.get("game_title") or "?"
        g = by_game.setdefault(gid, {"key": gid, "label": s.get("game_title") or gid, "kind": "game", "count": 0,
                                     "extractor": extractor_of(m), "names": set()})
        if base_name(m) in g["names"]:
            continue
        g["names"].add(base_name(m))
        g["count"] += 1
        if g["extractor"]:
            ex_count[g["extractor"]] = ex_count.get(g["extractor"], 0) + 1
    out = []
    for key, grp in GROUPS.items():
        if grp.get("best_per_character"):                  # one per character across its games and packs
            n = len({character_key(m) for m in _candidates(chars) if in_group(m, key)})
        else:
            n = sum(ex_count.get(e, 0) for e in grp["extractors"])
        if n:
            out.append({"key": key, "label": grp["label"], "kind": "group", "count": n})
    games = sorted(by_game.values(), key=lambda g: g["label"].lower())
    return out + [{k: v for k, v in g.items() if k != "names"} for g in games if g["count"]]


def _candidates(chars: list[dict], kind: str = "character") -> list[dict]:
    """Collection entries that can be donors at all: the right kind, not a head-size variant, with a source game."""
    base=[m for m in chars if (m.get("kind") or "character")==kind and (m.get("source") or {}).get("game_title")]
    by_slug={m['slug']:m for m in base};approved={}
    for m in base:
        a=m.get('texture_approval') or {};digest=a.get('candidate','')
        if not m.get('variant_of') or not digest or not m['slug'].endswith('_tex_'+digest[:12]):continue
        parent=m['variant_of'];seen=set()
        while parent in by_slug and by_slug[parent].get('variant_of') and parent not in seen:
            seen.add(parent);parent=by_slug[parent]['variant_of']
        if parent not in approved or a.get('at',0)>(approved[parent].get('texture_approval') or {}).get('at',0):approved[parent]=m
    return [approved.get(m['slug'],m) for m in base if not m.get('variant_of')]


def resolve_source(spec: str, chars: list[dict], kind: str = "character") -> dict:
    """source=<group | game id | extractor | title words>[, ...] -> {label, entries, filters}. Raises ValueError with
    the available sources when nothing matches."""
    pool = _candidates(chars, kind)
    picked: dict[str, dict] = {}
    groups: dict[str, str] = {}
    pool_order: list[str] = []
    same_members: dict[frozenset[str], str] = {}
    labels, best_groups = [], []
    for part in [p.strip() for p in re.split(r"[,+]|\band\b", spec or "") if p.strip()]:
        q = part.lower()
        hits: list[dict] = []
        grp = next((k for k, g in GROUPS.items() if q == k or q in g["aliases"]), None)
        if grp:
            hits = [m for m in pool if in_group(m, grp)]
            labels.append(GROUPS[grp]["label"])
            pool_key = grp
            if GROUPS[grp].get("best_per_character"):
                best_groups.append(grp)
        elif re.fullmatch(r"[0-9a-f]{16}", q):
            hits = [m for m in pool if (m.get("source") or {}).get("game_id") == q]
            labels.append(next(((m["source"].get("game_title")) for m in hits), q))
            pool_key = "game:" + q
        else:
            from . import characters as C
            names = {n for n, *_r in C.DEDICATED}
            if q in names:
                hits = [m for m in pool if extractor_of(m) == q]
                labels.append(next((m["source"]["game_title"] for m in hits), q))
                pool_key = "extractor:" + q
            else:
                want = _words(expand(part))
                titles: dict[str, int] = {}
                for m in pool:
                    t = m["source"]["game_title"]
                    titles.setdefault(t, len(want & _words(t)))
                best = max(titles.values(), default=0)
                if want and best >= max(1, len(want) - 1):
                    keep = {t for t, s in titles.items() if s == best}
                    # "Sonic Adventure" is not "Sonic Adventure 2": a title whose extra words carry a sequel number
                    # loses to an equally matching one without, unless the request names a number itself
                    sequel = {t for t in keep if any(SEQUEL.fullmatch(w) for w in _words(t) - want)}
                    if keep - sequel:
                        keep -= sequel
                    hits = [m for m in pool if m["source"]["game_title"] in keep]
                    labels.append(" / ".join(sorted(keep)))
                    pool_key = "titles:" + " | ".join(sorted(t.casefold() for t in keep))
        if not hits:
            have = ", ".join(f"{g['label']} ({g['count']})" for g in source_groups(chars)) or "nothing yet"
            raise ValueError(f"no {kind} entries in the collection match source {part!r}; sources: {have}")
        # A requested component is one pool even if it matches several games. Aliases
        # with identical members share a pool; otherwise the first component owns overlaps.
        pool_key = same_members.setdefault(frozenset(m["slug"] for m in hits), pool_key)
        if pool_key not in pool_order:
            pool_order.append(pool_key)
        for m in hits:
            picked.setdefault(m["slug"], m)
            groups.setdefault(m["slug"], pool_key)
    if not picked:
        raise ValueError("source is empty: name a game, a game id or a group (wrestlers, fighters, ...)")
    return {"label": " + ".join(labels), "entries": list(picked.values()), "best_per_character": best_groups,
            "groups": groups, "pool_order": pool_order}


def dedupe(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """One donor per character: costumes (same base name, same source game) collapse onto the first one."""
    seen: dict[tuple, dict] = {}
    keep, dropped = [], []
    for m in sorted(entries, key=lambda m: (m["source"].get("game_title", ""), m.get("slug", ""))):
        key = ((m.get("source") or {}).get("game_id") or m["source"].get("game_title"), base_name(m))
        if key in seen:
            dropped.append({"slug": m["slug"], "name": m.get("name"), "costume_of": seen[key]["slug"]})
            continue
        seen[key] = m
        keep.append(m)
    return keep, dropped


# ---------------------------------------------------------------- the donor quality gate

def retarget_check(meta: dict, root: Path | None = None, kind: str = "character") -> str | None:
    """None when the entry can be retargeted (the collection's check: verified model + preview, body roles mapped),
    else why not."""
    if kind == "sprites":
        if (meta.get("kind") or "") != "sprites":
            return "not a sprites entry (this game's writer re-draws sprite frames)"
    else:
        roles = (meta.get("rig") or {}).get("roles") or {}
        if not roles:
            return "no body roles (rig.roles): the model is not mapped onto a skeleton, so it can't be retargeted"
        if "hip" not in roles:
            return f"body roles lack the hip ({', '.join(sorted(roles)[:6])}): can't be retargeted"
    if root is not None and Path(root).is_dir() and (Path(root) / meta["slug"] / "meta.json").is_file():
        from . import characters as C
        try:
            chk = C.verify_entry(Path(root), meta)
        except (OSError, KeyError, ValueError) as e:
            return f"collection check failed: {e}"
        if not chk.get("ok"):
            prev = chk.get("preview") or {}
            return ("collection check failed: " + ("no model file" if not chk.get("model_bytes") else
                                                   "no triangles" if not chk.get("triangles") and kind != "sprites" else
                                                   f"preview shows no model ({prev.get('error') or prev})"))
    return None


def gate(entries: list[dict], root: Path | None = None, kind: str = "character",
         refresh=None) -> tuple[list[dict], list[dict], list[dict]]:
    """-> (donors, refused [{slug, name, reason}], refreshed [{slug, reader, status}]). Stale entries (an older
    DEDICATED reader) go through `refresh(meta) -> new meta` first (re-extraction); without one they are refused."""
    from . import characters as C
    donors, refused, refreshed = [], [], []
    for m in entries:
        rs = C.reader_status(m)
        if rs and rs.get("stale"):
            row = {"slug": m["slug"], "name": m.get("name"), "reader": rs}
            if refresh is None:
                refused.append(row | {"reason": f"made by {rs['extractor']} reader v{rs['entry']}, current v{rs['current']}: "
                                                "re-extract it first (the build does that automatically)", "stale": True})
                continue
            try:
                m = refresh(m)
            except Exception as e:                        # noqa: BLE001 - one donor's re-extraction never stops the cast
                refused.append(row | {"reason": f"re-extraction (reader v{rs['entry']} -> v{rs['current']}) failed: {e}"})
                continue
            rs2 = C.reader_status(m) or {}
            if rs2.get("stale"):
                refused.append(row | {"reason": f"still reader v{rs2.get('entry')} after re-extraction"})
                continue
            refreshed.append(row | {"status": f"re-extracted with reader v{rs['current']}"})
        why = retarget_check(m, root, kind)
        if why:
            refused.append({"slug": m["slug"], "name": m.get("name"), "reason": why})
            continue
        donors.append(m)
    return donors, refused, refreshed


def model_height(root: Path | None, meta: dict) -> float | None:
    """The donor's standing height in its own units, read from the glTF accessor bounds (no buffers decoded)."""
    if root is None:
        return None
    p = Path(root) / meta.get("slug", "") / str(meta.get("model") or "")
    try:
        if p.suffix.lower() == ".glb":
            with p.open("rb") as f:
                head = f.read(20)
                if head[:4] != b"glTF":
                    return None
                gl = json.loads(f.read(struct.unpack_from("<I", head, 12)[0]))
        elif p.suffix.lower() == ".gltf":
            gl = json.loads(p.read_text("utf-8"))
        else:
            return None
    except (OSError, ValueError, struct.error):
        return None
    lo, hi = None, None
    for me in gl.get("meshes", []):
        for pr in me.get("primitives", []):
            a = gl["accessors"][pr["attributes"]["POSITION"]] if "POSITION" in pr.get("attributes", {}) else {}
            if "min" in a and "max" in a:
                lo = a["min"][1] if lo is None else min(lo, a["min"][1])
                hi = a["max"][1] if hi is None else max(hi, a["max"][1])
    return (hi - lo) if lo is not None and hi is not None and hi > lo else None


def donor_rows(donors: list[dict], root: Path | None = None) -> list[dict]:
    """Planner rows: slug, name, preview, lead (a game's own player character), height relative to its own game."""
    rows = []
    for m in donors:
        rows.append({"slug": m["slug"], "name": m.get("name") or m["slug"],
                     "source": (m.get("source") or {}).get("game_title"),
                     "source_game_id": (m.get("source") or {}).get("game_id"),
                     "preview_url": m.get("preview_url") or f"/api/characters/{m['slug']}/preview",
                     "lead": bool(m.get("native_player")) or any(str(a).lower() in ("player", "hero", "protagonist")
                                                                  for a in m.get("aliases") or []),
                     "height": model_height(root, m), "name_key": name_key(m)})
    by_game: dict[str, list[float]] = {}
    for r in rows:
        if r["height"]:
            by_game.setdefault(r["source_game_id"] or r["source"], []).append(r["height"])
    for r in rows:
        hs = by_game.get(r["source_game_id"] or r["source"]) or []
        r["size"] = round(r["height"] / statistics.median(hs), 3) if r["height"] and hs else None
    return rows


# ---------------------------------------------------------------- target slots

def slot_rows(game: dict, rows: list[dict] | None = None) -> list[dict]:
    """The target's replaceable slots: the writer's cast_slots(), aggregates and aliases dropped (each model once)."""
    from . import char_coverage as CC
    rows = CC.cast_slots(game) if rows is None else rows
    lead = {str(r["alias_of"]) for r in rows if r.get("slot") == "player" and r.get("alias_of")}
    out, seen = [], set()
    for r in rows:
        s = str(r.get("slot") or "")
        if not s or s in seen or r.get("aggregate") or r.get("alias_of") or s.lower() in AGGREGATE:
            continue
        seen.add(s)
        row = dict(r, kind=r.get("kind") or ("player" if s == "player" else "slot"))
        if s in lead:                                      # the slot the game's `player` alias names (Axel)
            row["lead_slot"] = True
        out.append(row)
    return out


KIND_WORDS = {"enemies": "enemy", "npcs": "npc", "pedestrians": "pedestrian", "passengers": "passenger",
              "drivers": "driver", "fighters": "fighter", "wrestlers": "wrestler", "characters": "character",
              "bosses": "boss", "sages": "sage", "bots": "bot"}


def filter_slots(rows: list[dict], which: str = "all") -> list[dict]:
    """slots=all | main (players, fighters, drivers, cast members) | enemies | npcs | bosses | bots | pedestrians |
    passengers | <kind> | a group the writer's rows name (`groups`: AUF's campaign, multiplayer, bots, model:<body>) |
    a slot name, or a comma list of any of these (the union, in the writer's order: slots=campaign,bots)."""
    w = (which or "all").strip().lower()
    if w in ("", "all", "everyone", "*"):
        return rows
    toks = [x.strip() for x in w.split(",") if x.strip()]
    kinds_present = {r["kind"] for r in rows}
    groups_present = {str(g).lower() for r in rows for g in r.get("groups") or []}
    keep, unknown = set(), []
    for t in toks:
        if t in ("all", "everyone", "*"):
            return rows
        known = t == "main" or t in KIND_WORDS or t in kinds_present or t in groups_present
        hit = {i for i, r in enumerate(rows)
               if (t == "main" and r["kind"] in MAIN_KINDS) or r["kind"] == KIND_WORDS.get(t, t)
               or t in {str(g).lower() for g in r.get("groups") or []} or r["slot"].lower() == t}
        if not hit and not known:
            unknown.append(t)
        keep |= hit
    if unknown or not keep and len(toks) > 1:
        raise ValueError(f"slots={which!r}: {', '.join(unknown) or 'nothing'} matches none of "
                         f"{', '.join(sorted(groups_present)[:12] or [r['slot'] for r in rows[:20]])}")
    return [r for i, r in enumerate(rows) if i in keep]


def slot_sets(rows: list[dict]) -> list[list[str]]:
    """The menu's "Slots" choices for this target: everyone, main cast, enemies, then the groups its rows name (AUF:
    campaign, bots, bosses, npcs ...), each with how many slots it covers."""
    out = [["all", f"Everyone ({len(rows)})"]]
    main = sum(r["kind"] in MAIN_KINDS for r in rows)
    if main and main < len(rows):
        out.append(["main", f"Main cast only ({main})"])
    seen = {"all", "main"}
    for key, label in (("enemies", "Enemies"), ("bosses", "Bosses"), ("npcs", "NPCs / allies"), ("bots", "Bots"),
                       ("campaign", "Campaign (story mode)"), ("multiplayer", "Multiplayer"), ("player", "Player")):
        try:
            n = len(filter_slots(rows, key))
        except ValueError:
            continue
        if n and n < len(rows) and key not in seen:
            out.append([key, f"{label} ({n})"])
            seen.add(key)
    if any(r.get("groups") for r in rows) and "campaign" in seen and "bots" in seen:
        n = len(filter_slots(rows, "campaign,bots"))
        if n < len(rows):
            out.append(["campaign,bots", f"Campaign + multiplayer bots ({n})"])
    return out


# ---------------------------------------------------------------- the mapping

def assign(slots: list[dict], donors: list[dict], mapping: str = "auto", seed: str = "", *,
           pool_order: list[str] | None = None) -> list[dict]:
    """Deterministic assignments for slots/donors/mapping/seed. by_role places leads on player slots
    and taller donors on larger slots; random shuffles the donor deck. alternate balances source
    pool counts, deals every distinct name once per pool pass, and rotates each name's variants
    without replacement. Unequal pools/name-variant counts can repeat a donor before all donors
    globally have appeared; alternate guarantees name passes, not global donor exhaustion."""
    mapping = (mapping or "auto").lower().replace("-", "_")
    if mapping not in ("auto", "random", "by_role", "alternate"):
        raise ValueError(f"mapping={mapping!r}: auto | random | by_role | alternate")
    todo = [s for s in slots if not s.get("skip")]
    if not donors or not todo:
        return []
    rng = random.Random(f"cast:{seed}:{mapping}:" + ",".join(s["slot"] for s in todo) + "|" +
                        ",".join(d["slug"] for d in donors))
    if mapping == "random":
        order = list(todo)
        deck: list[dict] = []
        out = []
        for s in order:
            if not deck:
                deck = list(donors)
                rng.shuffle(deck)
                deck = spread(deck)
            d = deck.pop(0)
            out.append((s, d, "random (seeded" + (", preferred source)" if d.get("preferred") else ")")))
        return [_row(s, d, why) for s, d, why in out]
    if mapping == "alternate":
        return _alternate(todo, donors, rng, pool_order=pool_order)
    # by_role (auto is by_role: it falls back to the seeded order when sizes are unknown)
    tie = {d["slug"]: rng.random() for d in donors}
    leads = sorted([d for d in donors if d.get("lead")], key=lambda d: (not d.get("preferred"), tie[d["slug"]]))
    rest = sorted([d for d in donors if not d.get("lead")],
                  key=lambda d: (not d.get("preferred"), -(d.get("size") or 1.0), tie[d["slug"]]))
    order = leads + rest
    players = [s for s in todo if s["kind"] == "player" or (s.get("lead_slot") and leads)]
    others = sorted([s for s in todo if s not in players],
                    key=lambda s: (-float(s.get("size") or 1.0), todo.index(s)))
    out = []
    deck = list(order)
    for s in players + others:
        if not deck:
            deck = list(order)
            rng.shuffle(deck)
        d = deck.pop(0)
        if s["kind"] == "player" and d.get("lead"):
            why = "lead character on the player slot"
        elif s.get("lead_slot") and d.get("lead"):
            why = "lead character on the game's own player (the slot its player alias names)"
        elif s.get("size") and d.get("size"):
            why = f"body size: slot x{float(s['size']):g}, donor x{d['size']:g} of its cast"
        else:
            why = "by role (seeded order)"
        out.append(_row(s, d, why))
    pos = {s["slot"]: i for i, s in enumerate(todo)}
    return sorted(out, key=lambda r: pos[r["slot"]])


def name_key(meta: dict) -> str:
    """One character across games: the base name without costume tags or a "(Game)" suffix, letters and digits only
    ("The Rock" of No Mercy and of SmackDown! 2 are one wrestler)."""
    n = re.sub(r"\([^)]*\)", " ", base_name(meta))
    return re.sub(r"[^a-z0-9]+", "", n.lower()) or str(meta.get("slug") or "")


def spread(deck: list[dict]) -> list[dict]:
    """One shuffled round of donors reordered so preferred donors (prefer=) come first and every character name is
    dealt once before any name repeats (the same wrestler from another game goes to the end of the round). A deck
    with no preferred donors and no shared names keeps its shuffled order."""
    seen: dict[str, int] = {}
    keyed = []
    for i, d in enumerate(sorted(deck, key=lambda d: not d.get("preferred"))):   # stable: the shuffle within each tier
        k = d.get("name_key") or d["slug"]
        keyed.append(((seen.get(k, 0), not d.get("preferred"), i), d))
        seen[k] = seen.get(k, 0) + 1
    return [d for _k, d in sorted(keyed, key=lambda kd: kd[0])]


def _row(s: dict, d: dict, why: str) -> dict:
    return {"slot": s["slot"], "slot_name": s.get("name") or s["slot"], "kind": s["kind"], "character": d["slug"],
            "donor": d["name"], "source": d.get("source"), "preview_url": d.get("preview_url"), "why": why}


def _alternate(todo: list[dict], donors: list[dict], rng: random.Random, *,
               pool_order: list[str] | None = None) -> list[dict]:
    """mapping=alternate: round-robin the donors across their source pools, one donor per pool per pass.

    A donor's pool is its `pool` tag (the source group it came from), else its source game id / title, else its
    slug. Requested component order wins when supplied, otherwise pools keep first-seen order.
    Each seeded pool pass deals each distinct name once; variants of a name rotate without
    replacement. An exhausted name pass reshuffles. Pool slot counts stay within one."""
    pools: dict[str, list[dict]] = {}
    order: list[str] = []
    for d in donors:
        key = str(d.get("pool") or d.get("source_game_id") or d.get("source") or d["slug"])
        if key not in pools:
            pools[key] = []
            order.append(key)
        pools[key].append(d)

    if pool_order is not None:
        missing = [key for key in pool_order if key not in pools]
        if missing:
            raise ValueError(f"alternate source pools have no eligible donors: {', '.join(missing)}")
        order = list(dict.fromkeys(pool_order)) + [key for key in order if key not in pool_order]

    # Each pass contains each distinct character name exactly once. A character
    # with several game/costume variants must not crowd out the other names.
    variants: dict[str, dict[str, list[dict]]] = {}
    remaining: dict[str, dict[str, list[dict]]] = {}
    for key in order:
        variants[key] = {}
        for donor in pools[key]:
            variants[key].setdefault(donor.get("name_key") or donor["slug"], []).append(donor)
        remaining[key] = {name: [] for name in variants[key]}

    def fresh(key: str) -> list[dict]:
        names = list(variants[key])
        rng.shuffle(names)
        deck = []
        for name in names:
            choices = remaining[key][name]
            if not choices:
                choices.extend(variants[key][name])
                rng.shuffle(choices)
            deck.append(choices.pop())
        return deck

    decks = {k: fresh(k) for k in order}
    idx = {k: 0 for k in order}
    out = []
    for i, s in enumerate(todo):
        key = order[i % len(order)]
        if idx[key] >= len(decks[key]):
            decks[key] = fresh(key)
            idx[key] = 0
        d = decks[key][idx[key]]
        idx[key] += 1
        out.append((s, d, f"alternate pool {key}"))
    return [_row(s, d, why) for s, d, why in out]


def apply_edits(plan: list[dict], edits: list[dict], donors: list[dict], slots: list[dict]) -> list[dict]:
    """The operator's reviewed plan: [{slot, character}] overrides (character '' drops the slot). The menu sends every
    row it showed, so the build is exactly what was reviewed even if a donor's re-extraction changed its size."""
    by_slug = {d["slug"]: d for d in donors}
    by_slot = {s["slot"]: s for s in slots}
    rows = {r["slot"]: r for r in plan}
    for e in edits or []:
        s, c = str(e.get("slot") or ""), str(e.get("character") or "")
        if s not in by_slot:
            raise ValueError(f"assignment for unknown slot {s!r}")
        if not c:
            rows.pop(s, None)
            continue
        if c not in by_slug:
            raise ValueError(f"{c!r} is not an eligible donor of this source (refused or not in the collection)")
        if rows.get(s, {}).get("character") != c:
            rows[s] = _row(by_slot[s], by_slug[c], "edited")
    pos = {s["slot"]: i for i, s in enumerate(slots)}
    return sorted(rows.values(), key=lambda r: pos.get(r["slot"], 1 << 30))


def texture_assignment_aliases(edits, chars, donors):
    """An old recipe may name the original superseded by an explicitly approved texture donor."""
    metas={m['slug']:m for m in chars};aliases={};eligible={m['slug'] for m in donors}
    for donor in donors:
        item=metas.get(donor['slug'],{});seen=set()
        while item.get('texture_approval') and item.get('variant_of') and item['slug'] not in seen:
            seen.add(item['slug']);parent=item['variant_of']
            if parent not in eligible:aliases[parent]=donor['slug']
            item=metas.get(parent,{})
    return [{**e,'character':aliases.get(e.get('character'),e.get('character'))} for e in (edits or [])]


# ---------------------------------------------------------------- how each writer builds many slots at once

STRATEGIES = {
    "gbox.gta_stories_models": ("pairs", "LCS PS2: streamed pedestrians in one disc; special story/cutscene models remain separate"),
    "gbox.pso_player": ("pairs", "PSO Ver.2: every enemy pack rebuilt with its donors in one GD-ROM (gbox.pso_enemy.build_cast)"),
    "gbox.doa2_swap": ("pairs", "DOA2: the roster build (doa2_swap.use_roster: every selectable fighter in one disc)"),
    "gbox.doa3_cast": ("pairs", "DOA3 Xbox: every fighter family's costumes rewritten in one loadfile.afs, one disc "
                                "build for the native runner (doa3_cast.build_cast)"),
    "gbox.soulcalibur_swap": ("pairs", "SoulCalibur DC: every fighter's costumes rebuilt in one HUMAN.DAT, one GD-ROM "
                                       "(soulcalibur_swap.build_cast)"),
    "gbox.defjam_writer": ("pairs", "Def Jam Vendetta: op=match (every wrestler container in one data.bin)"),
    "gbox.yukes_sd": ("pairs", "SmackDown! 2: op=match (every wrestler in one disc)"),
    "gbox.aki_wrestling": ("pairs", "No Mercy / WCW: op=match (every wrestler in one ROM)"),
    "gbox.gta_vc_swap": ("pairs", "Vice City PC: every ped in one gta3.img rebuild (gta_vc_swap.build_cast)"),
    "gbox.etm_swap": ("pairs", "Enter the Matrix PS2: every cast slot's .dcn models rewritten in one WAD1.DFU "
                               "(etm_swap.build_cast)"),
    "gbox.mgs2_swap": ("pairs", "Metal Gear Solid 2 PS2: every slot's kms models (every stage that carries them) "
                                "rebuilt in one STAGE.DAT / STAGE2.DAT image (mgs2_swap.build_cast)"),
    "gbox.oot_swap": ("pairs", "Ocarina of Time: every NPC / enemy object and Link rebuilt in one ROM "
                               "(oot_swap.build_cast: DMA + object table + CRC, object space shared per room)"),
    "gbox.jgr_swap": ("chain", "JGR: each cast member's writer step on the previous step's PLAYER.AFS, one GD-ROM"),
    "gbox.crazy_taxi_swap": ("chain", "Crazy Taxi: each slot's writer step on the previous step's polDC0.all, one disc"),
    "gbox.mgs_vr_swap": ("pairs", "Metal Gear Solid VR Missions: Snake, every soldier and the other 16-object figures "
                                  "fitted into one disc (mgs_vr_swap.build_cast: each mission stage's copy of a model "
                                  "and its texture archive, native STAGE.DIR rewrite)"),
    "gbox.twin_snakes_swap": ("pairs", "Twin Snakes GC: every slot's model in one stage.dat rebuild "
                                       "(twin_snakes_swap.build_cast: each gameplay stage rebuilt in place)"),
    "gbox.soulcalibur2_swap": ("pairs", "Soul Calibur II GC: every fighter's costume packages rewritten in place in "
                                        "human.olk, one disc image (soulcalibur2_swap.build_cast)"),
    "gbox.stranglehold_swap": ("pairs", "Stranglehold PS3: every slot's char_*.xxx package rewritten in one folder mod "
                                        "(stranglehold_swap.build_cast; PS3TOC.txt updated once)"),
    "gbox.auf_swap": ("pairs", "007 Agent Under Fire GC: every body in the missions (campaign:<body>) and in the "
                               "multiplayer maps (mp:<body>, the bots) gets its donor; every level rebuilt once, one disc "
                               "image (auf_swap.build_cast)"),
    "gbox.ff7_swap": ("pairs", "FF7: every party member's field + battle model rebuilt on that member's own skeletons "
                               "in one disc image (ff7_swap.build_cast; Yuffie's and Cait Sith's field skeletons are "
                               "not_working)"),
}


def strategy(writer: str | None) -> tuple[str, str]:
    return STRATEGIES.get(writer or "", ("single", "one slot per mod (characters op=use); no multi-slot path yet"))


def chain(files: dict, steps: list[tuple[str, object]], progress=lambda p, m: None) -> tuple[dict, dict]:
    """The common multi-slot path: apply each slot's writer step to the output of the previous one. files: the
    staged copy {path: bytes} (never the original image); steps: [(slot, step(files) -> {path: new bytes})]. A
    failing step leaves the files as they were and is reported; the next step continues from there.
    -> (final files, {slot: {status, reason?}})."""
    from . import fit_events as FE
    state = dict(files)
    report: dict[str, dict] = {}
    for i, (slot, step) in enumerate(steps):
        progress(5 + 80 * i / max(1, len(steps)), f"{slot} ({i + 1}/{len(steps)})")
        FE.model(slot)                                    # this step's fits belong to the slot's model
        try:
            new = step(dict(state)) or {}
            unknown = set(new) - set(state)
            if unknown and state:
                raise ValueError(f"step wrote files outside the staged copy: {sorted(unknown)[:3]}")
            state.update(new)
            report[slot] = {"status": "built", "files": sorted(new)}
        except Exception as e:                            # noqa: BLE001 - one slot never stops the cast
            report[slot] = {"status": "failed", "reason": str(e)[:500] or type(e).__name__}
            FE.stage("write", "failed", {"reason": report[slot]["reason"][:150]})
    return state, report


def chain_written(report: dict, mod: str, image: str, files: dict | None = None):
    """The write stage of every chained slot once the one image is written: the image, and how big the staged files
    it changed are (each slot's step rewrote them in place)."""
    from . import fit_events as FE
    for slot, r in report.items():
        if r.get("status") != "built":
            continue
        FE.model(slot)
        FE.stage("write", data={"mod": mod, "image": image, "files": len(r.get("files") or []),
                                "bytes": sum(len(files[f]) for f in r.get("files") or [] if f in (files or {}))})


class StagedDisc:
    """A disc reader (.files {path: (lba, size)}, .read(path)) that answers the staged copy's bytes for files an
    earlier step changed, so a writer reading through it builds on the previous step's output."""

    def __init__(self, disc, staged: dict):
        self.disc, self.staged = disc, staged
        self.files = {p: (lba, len(staged[p]) if p in staged else size) for p, (lba, size) in disc.files.items()}

    def read(self, path):
        return self.staged[path] if path in self.staged else self.disc.read(path)


def link_tree(src: Path, dst: Path) -> Path:
    """dst = a copy of the built mod folder src made of hard links (no extra bytes); the marker is a real copy so the
    new folder's record never writes through to the source. A file that can't be linked is copied."""
    import os
    import shutil
    src, dst = Path(src), Path(dst)
    if not (src / ".gbox-mod.json").is_file():
        raise ValueError(f"{src.name} is not a built mod folder")
    if dst.exists():
        shutil.rmtree(dst)
    for d, dirs, files in os.walk(src):
        rel = Path(d).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        dirs[:] = [x for x in dirs if not (Path(d) / x).is_symlink()]
        for f in files:
            s, t = Path(d) / f, dst / rel / f
            if s.is_symlink():
                continue
            if f == ".gbox-mod.json" and rel == Path("."):
                shutil.copyfile(s, t)
                continue
            try:
                os.link(s, t)
            except OSError:
                shutil.copy2(s, t)
    return dst


def plan_digest(plan: list[dict]) -> str:
    """The plan hash: which donor goes on which slot. The same digest means the same build (cast_<...>_<digest> mods,
    the Sonic showcase's rebuild check)."""
    return hashlib.sha256(json.dumps([(r["slot"], r["character"]) for r in plan]).encode()).hexdigest()[:8]


def mod_name(game: dict, source_label: str, plan: list[dict]) -> str:
    """cast_<game words>_<source words>_<digest of the plan>: the same plan reuses its mod."""
    def short(s, n):
        return "_".join(re.findall(r"[a-z0-9]+", str(s).lower()))[:n].strip("_")
    return f"cast_{short(expand(game.get('title', '')), 18)}_{short(source_label, 18)}_{plan_digest(plan)}"


def _named(inp) -> str:
    """mod_name= (the Sonic showcase's showcase_sonic_<title>): one folder name, else ''."""
    n = str(getattr(inp, "mod_name", "") or "").strip()
    if n and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", n):
        raise ValueError(f"mod_name={n!r}: letters, digits, '_', '-', '.' only (one cache folder name)")
    return n


# ---------------------------------------------------------------- the tool

def plan(game: dict, chars: list[dict], source: str, mapping: str = "auto", seed: str = "", slots: str = "all",
         assignments: list[dict] | None = None, root: Path | None = None, slot_list: list[dict] | None = None,
         refresh=None, prefer: str = "", lead_character: str = '', lead_slot: str = 'player') -> dict:
    """The whole plan, without building: target slots, eligible / refused / deduplicated donors, assignments.
    prefer: a source spec (same forms as source) whose donors are dealt first by the random mapping (assign=random)
    and by by_role among equals ("wrestlers, preferring the WWF games": prefer=smackdown2,nomercy)."""
    from . import char_coverage as CC
    w = CC.writer_for(game)
    if not w or not w.get("routed"):
        return {"status": "unsupported", "game_id": game.get("game_id"), "title": game.get("title"),
                "message": f"{game.get('title')} has no routed character writer (characters op=coverage); "
                           "no cast can be built into it yet", "slots": [], "assignments": []}
    kind = "sprites" if w["writer"] == "gbox.clayfighter_swap" else "character"
    all_slots = slot_rows(game, slot_list)
    chosen = filter_slots(all_slots, slots)
    for s in chosen:
        if s.get("status") == "not_working":
            s["skip"] = s.get("reason") or "the game doesn't draw this writer's output yet (status not_working); left as it is"
    if strategy(w["writer"])[0] == "single" and str(slots or "all").strip().lower() == "all":
        return {"status":"unsupported_cast", "game_id":game["game_id"], "title":game.get("title"),
                "writer":w["writer"], "slots":all_slots, "assignments":[], "mod":None,
                "requested_scope":"whole_cast", "message":f"{w['writer']} only supports individual replacements. "
                "A whole-cast request cannot be reduced to one player or a set of separate single-character ROMs. "
                "Inventory the missing cast/cinematic slots and implement a combined writer. Explicit slots=player is a diagnostic only."}
    if strategy(w["writer"])[0] == "single":               # one slot per mod: the player (or the first slot) only
        first = next((s for s in chosen if not s.get("skip") and s["kind"] == "player"),
                     next((s for s in chosen if not s.get("skip")), None))
        for s in chosen:
            if s is not first and not s.get("skip"):
                s["skip"] = (f"{w['writer']} has no multi-slot path (pairs API or chained step) yet: one mod holds "
                             f"one slot; build it alone with characters op=use slot={s['slot']}")
    mapping = (mapping or "auto").lower().replace("-", "_")
    src = resolve_source(source, chars, kind)
    entries, costumes = dedupe(src["entries"])
    donors, refused, refreshed = gate(entries, root, kind, refresh)
    stale = set()
    if refresh is None:                                    # planning only: stale donors are re-extracted at build time
        flagged = [r for r in refused if r.get("stale")]
        old = {m["slug"]: m for m in entries}
        stale = {r["slug"] for r in flagged if not retarget_check(old[r["slug"]], None, kind)}
        donors += [old[s] for s in stale]
        refused = [r for r in refused if r["slug"] not in stale]
        refreshed = [{"slug": r["slug"], "name": r["name"], "reader": r["reader"], "status": "will be re-extracted "
                      f"(reader v{r['reader']['entry']} -> v{r['reader']['current']})"} for r in flagged if r["slug"] in stale]
    # the writer's own donor requirement (doa3_cast.donor_problem: a DOA3 fighter needs two legs) refuses a donor
    # before the deal, so a group's best model per character and the alternate passes count only buildable donors
    problem = getattr(CC._mod(w["writer"].split(".")[-1]), "donor_problem", None)
    if callable(problem):
        usable = []
        for m in donors:
            why = problem(m)
            if why:
                refused.append({"slug": m["slug"], "name": m.get("name"), "reason": why})
            else:
                usable.append(m)
        donors = usable
    superseded = []
    if src.get("best_per_character"):                      # source=mario: the best gated model of each character
        def member(m):
            return any(in_group(m, g) for g in src["best_per_character"])
        keep, superseded = best_per_character([m for m in donors if member(m)])
        kept = {m["slug"] for m in keep}
        donors = [m for m in donors if not member(m) or m["slug"] in kept]
    pos = {m["slug"]: i for i, m in enumerate(entries)}    # the source's own order, re-extracted or not: same plan
    rows = donor_rows(sorted((m for m in donors if m['slug']!=lead_character), key=lambda m: pos.get(m["slug"], 1 << 30)), root)
    for r in rows:
        pool_key = src.get("groups", {}).get(r["slug"])
        if mapping == "alternate" and pool_key is None:
            raise ValueError(f"refreshed donor {r['slug']} has no source-component attribution; replan the source")
        r["pool"] = pool_key or r.get("source_game_id") or r.get("source")
    pref = {m["slug"] for m in resolve_source(prefer, chars, kind)["entries"]} if (prefer or "").strip() else set()
    for r in rows:
        if r["slug"] in stale:
            r["stale"] = True
        if r["slug"] in pref:
            r["preferred"] = True
    if pref and not any(r.get("preferred") for r in rows):
        raise ValueError(f"prefer={prefer!r} names none of the usable donors of source={source!r}")
    why = {r["slug"]: r["reason"] for r in refused}
    for e in assignments or []:                            # a reviewed row whose donor the gate refused is left out
        if e.get("character") in why:
            for s in chosen:
                if s["slot"] == e.get("slot") and not s.get("skip"):
                    s["skip"] = f"donor {e['character']} refused: {why[e['character']]}"
    dealt=[s for s in chosen if not (lead_character and (s['slot']==lead_slot or (lead_slot=='player' and s.get('lead_slot'))))]
    out = assign(dealt, rows, mapping, seed, pool_order=src.get("pool_order") if mapping == "alternate" else None)
    if assignments:
        out = apply_edits(out, texture_assignment_aliases([e for e in assignments if e.get("character") not in why and not (lead_character and e.get('slot')==lead_slot)],chars,rows), rows,
                          [s for s in chosen if not s.get("skip")])
    locked=None
    if lead_character:
        lead=next((m for m in chars if m.get('slug')==lead_character),None)
        if not lead:raise ValueError('Lead character must name an exact collection slug')
        problem=retarget_check(lead,root,kind)
        if problem:raise ValueError('Lead character cannot be built: '+problem)
        target=next((s for s in chosen if s['slot']==lead_slot or (lead_slot=='player' and s.get('lead_slot'))),None)
        if not target or target.get('skip'):
            raise ValueError('The requested lead slot is not buildable; refusing to put the lead on a supporting character')
        # A seed or supporting-cast edit can never replace the explicitly locked lead.
        lead_slot=target['slot'];locked=_row(target,donor_rows([lead],root)[0],'locked lead')
        out=[r for r in out if r['slot']!=lead_slot]+[locked]
        order={s['slot']:i for i,s in enumerate(chosen)};out.sort(key=lambda r:order[r['slot']])
    strat, how = strategy(w["writer"])
    scope = {}
    if w['writer'] == 'gbox.jgr_swap':
        from .jgr_swap import replacement_scope
        scope['replacement_scope'] = replacement_scope()
    return {"status": "planned" if out else "empty", "game_id": game["game_id"], "title": game.get("title"),
            "writer": w["writer"], "strategy": strat, "how": how, "source": src["label"], "mapping": mapping,
            **scope,
            "seed": seed, "slots_filter": slots, **({"prefer": prefer} if pref else {}),
            "slot_sets": slot_sets(all_slots),
            "slots": [{k: s.get(k) for k in ("slot", "name", "kind", "status", "skip", "size", "context", "groups")
                       if s.get(k) is not None} for s in chosen],
            "donors": rows, "refused": refused, "costumes_merged": costumes, "refreshed": refreshed,
            **({"superseded": superseded} if superseded else {}),
            "assignments": out, "skipped": [{"slot": s["slot"], "reason": s["skip"]} for s in chosen if s.get("skip")],
            **({'locked_lead':{'slot':lead_slot,'character':lead_character}} if locked else {}),
            "mod": mod_name(game, src["label"], out) if out else None,
            "message": (f"{len(out)} slots of {game.get('title')} get {src['label']} donors ({len(rows)} usable, "
                        f"{len(refused)} refused, {len(costumes)} costumes merged)") if out else
                       "nothing to build: no buildable slots or no usable donors"}


def _refresher(ctx, root: Path):
    """refresh(meta) for the gate: re-run the entry's DEDICATED reader on its source game (characters.extract_dedicated
    re-extracts stale entries), then read the new entry back."""
    from . import characters as C

    def refresh(meta):
        game = C._api(ctx, "GET", f"/api/catalog/{meta['source']['game_id']}")
        res = C.extract_dedicated(ctx, game, meta["slug"], root)
        if not res or res.get("status") not in ("extracted", "in_collection"):
            raise RuntimeError(f"reader answered {res and res.get('status')}")
        new = C.get(root, res["entry"]["slug"])
        return new | {"preview_url": meta.get("preview_url") or f"/api/characters/{new['slug']}/preview"}
    return refresh


def _target_game(ctx, inp) -> dict:
    from . import characters as C
    name = inp.target_game or inp.game_id or inp.game
    if not name and not inp.session_id:
        raise ValueError("cast_swap needs target_game (a game id or title)")
    q = SimpleNamespace(game_id=name if re.fullmatch(r"[0-9a-f]{16}", name or "") else "",
                        game=expand(name) if name and not re.fullmatch(r"[0-9a-f]{16}", name) else "",
                        session_id=inp.session_id if not name else "")
    return C._game(ctx, q)


def mapping_of(inp) -> str:
    """assign= (random | by_role | auto | alternate) wins over mapping=: `assign=random seed=x` deals the source's donors at random
    over the chosen slots for any game (seeded, no donor repeats before every donor has been used once, every
    character name once before any name repeats, prefer= donors first)."""
    a = str(getattr(inp, "assign", "") or "").strip().lower()
    return a or str(getattr(inp, "mapping", "") or "auto")


def run(ctx, inp) -> dict:
    """characters op=cast_swap: plan (plan_only) or plan + quality gate + one build; per-slot report."""
    from . import characters as C
    game = _target_game(ctx, inp)
    root = C.library_root(ctx.config)
    local = root.is_dir()
    chars = C._api(ctx, "GET", "/api/characters?fresh=1", timeout=900)   # a full re-read: 35-80 s on the HDD under load   # a collect may just have run in another process
    if not inp.source:
        return {"status": "needs_source", "game_id": game["game_id"], "title": game.get("title"),
                "sources": source_groups(chars), "message": "name a source: a game or a group (wrestlers, fighters, ...)"}
    live = _live_slots(ctx, game) if local else None
    mapping, prefer = mapping_of(inp), str(getattr(inp, "prefer", "") or "")
    if inp.plan_only or not local:
        p = plan(game, chars, inp.source, mapping, inp.seed, inp.slots, inp.assignments, root if local else None,
                 live, prefer=prefer,lead_character=getattr(inp,'lead_character',''),lead_slot=getattr(inp,'lead_slot','player'))
        if p["status"] == "planned" and _named(inp):
            p["mod"] = _named(inp)
        if inp.plan_only or p["status"] != "planned":
            return p
        return _on_control_plane(ctx, game, inp)
    p = plan(game, chars, inp.source, mapping, inp.seed, inp.slots, inp.assignments, root, live,
             refresh=_refresher(ctx, root), prefer=prefer,lead_character=getattr(inp,'lead_character',''),lead_slot=getattr(inp,'lead_slot','player'))
    if p["status"] != "planned":
        return p
    if _named(inp):                                        # a fixed name: the plan hash decides a rebuild instead
        p["mod"] = _named(inp)
    launch = "launch" in getattr(inp, "model_fields_set", set()) and bool(inp.launch)
    return p | build(ctx, game, p, chars, root, inp, launch)


def _live_slots(ctx, game: dict) -> list[dict] | None:
    """Slots a writer can only list off the game's files (Vice City's peds): its cast_slots_live(ctx, game), else None
    (the static cast_slots() list)."""
    from . import char_coverage as CC
    w = CC.writer_for(game)
    m = CC._mod(w["writer"].split(".")[-1]) if w else None
    fn = getattr(m, "cast_slots_live", None)
    if not callable(fn):
        return None
    try:
        rows = fn(ctx, game)
    except Exception:                                      # noqa: BLE001 - the static list stands
        return None
    return rows or None


def _on_control_plane(ctx, game: dict, inp) -> dict:
    """The collection lives on the Linux control plane (the Spark): build there, launch (if asked) from here."""
    from . import characters as C
    me = getattr(ctx, "worker", None)
    plane = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux" and w.get("online")
                  and w.get("id") != me), None)
    if not plane:
        raise RuntimeError("the cast build needs the character collection on the Linux control plane, which is offline")
    j = C._job(ctx, "characters", inp.model_dump() | {"session_id": "", "target_game": game["game_id"], "launch": False},
               plane, 14400)
    if j.get("state") != "succeeded":
        raise RuntimeError(f"cast build on the control plane {j.get('state')}: {j.get('error')}")
    res = dict(j["output"]["result"])
    if "launch" in getattr(inp, "model_fields_set", set()) and inp.launch and res.get("mod"):
        res["launch"] = C._launch(ctx, game["game_id"], res["mod"], C.HOST_OS)
    return res | {"built_by": j.get("id")}


def build(ctx, game: dict, p: dict, chars: list[dict], root: Path, inp, launch: bool = False) -> dict:
    """One mod for the whole plan through the writer's multi-slot path; per-slot rows {slot, donor, status, reason}."""
    from . import characters as C, filemods
    gid, name = game["game_id"], p["mod"]
    if p.get("writer") in ("gbox.twin_snakes_swap", "gbox.oot_swap"):
        # Do not overwrite or silently reuse a gameplay-only build made under the old policy.
        suffix = "_cs0" if p["writer"] == "gbox.oot_swap" and not getattr(inp, "strict_cutscenes", True) else "_cs1"
        if not name.endswith(suffix):
            base = name if len(name) <= 90 else name[:79] + "_" + hashlib.sha256(name.encode()).hexdigest()[:10]
            name = base + suffix
            p["mod"] = name
    metas = {m["slug"]: m for m in chars}
    for r in p["assignments"]:                            # re-read: the gate may have re-extracted the donor
        try:
            metas[r["character"]] = C.get(root, r["character"])
        except KeyError:
            pass
    from . import fit_events as FE, retarget_profile as RP
    # the operator's Retarget editor profiles (per donor, per slot) go into each donor's meta before any fit
    pairs = [(r["slot"], RP.apply_to_meta(metas[r["character"]], gid, r["slot"])) for r in p["assignments"]]
    profiles = ",".join(sorted({f"{s}={m.get('retarget_profile_digest')}" for s, m in pairs
                                if m.get("retarget_profile_digest")}))
    digest = plan_digest(p["assignments"])
    if p.get('writer') == 'gbox.gta_stories_models':
        # A changed plan/profile, or an explicit rebuild, must preserve the last disc.
        suffix='_plan'+digest[:8]+('_fit'+hashlib.sha256(profiles.encode()).hexdigest()[:8] if profiles else '')
        if not name.endswith(suffix):name=name[:max(1,95-len(suffix))]+suffix
        if inp.rebuild:name=name[:82]+'_r'+uuid.uuid4().hex[:10]
        p['mod']=name
    showcase = bool(getattr(inp, "showcase", False))
    have = filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json"
    if have.is_file() and not inp.rebuild:
        try:
            rec = json.loads(have.read_text())
            slots = rec.get("cast") or []
            # cast_<...>_<digest> names carry the plan; a fixed name (mod_name=) compares the recorded plan hash
            if rec.get("retarget_profiles", "") == profiles and rec.get("cast_plan") in (None, digest):
                return _report(p, {s["slot"]: s for s in slots}, name, "ready", launch and _launch(ctx, gid, name))
            inp = _rebuild(inp)                           # a profile (Retarget editor) or the plan changed since the build
        except (OSError, ValueError):
            pass
    root_dir = filemods.mod_dir(ctx.config, gid, name).parent
    before = {d.name for d in root_dir.iterdir()} if root_dir.is_dir() else set()
    FE.target(gid)                                        # every Fitting row opens the Retarget editor on its slot
    FE.plan([(s, m["slug"], f"{m.get('name', m['slug'])} -> {_slot_name(p, s)}") for s, m in pairs])
    strat = p["strategy"]
    builder = BUILDERS.get(p["writer"])
    if builder is None:
        if len(pairs) == 1:
            builder = _single
        else:
            per = {s: {"status": "failed", "reason": f"{p['writer']} has no multi-slot path (pairs API or chained "
                                                     "step) yet; build slots one at a time with characters op=use"}
                   for s, _m in pairs}
            return _report(p, per, None, "failed", None)
    ctx.progress(3, f"Building the {game.get('title')} cast ({len(pairs)} slots, {strat})")
    res = builder(ctx, game, pairs, name, inp)
    per = res.get("slots") or {}
    mod = res.get("mod")
    linked_from = None
    if mod and mod != name and _named(inp):
        # a writer that names its own build (DOA2 roster, one-slot characters op=use): the fixed name gets a hard-linked
        # copy of it (no extra bytes), the writer's build stays where characters op=use finds it
        try:
            link_tree(filemods.mod_dir(ctx.config, gid, mod), filemods.mod_dir(ctx.config, gid, name))
            linked_from = {"mod": mod, "made_by_this_build": mod not in before}
            mod = name
        except (OSError, ValueError) as e:
            per = {s: {"status": "failed", "reason": f"built as {mod}, not copied to {name}: {e}"[:500]} for s in per}
            mod = None
    built = [s for s, r in per.items() if r.get("status") in ("built", "partial")]
    for s, _m in pairs:                                   # every model's last stage in the Fitting pop-up
        if FE.written(s):                                 # the writer reported its own write (bytes, new place)
            continue
        FE.model(s)
        ok = s in built and mod
        FE.stage("write", "done" if ok else "failed",
                 {"mod": mod} if ok else {"reason": str((per.get(s) or {}).get("reason") or "not built")[:150]})
    if mod and built:
        d = filemods.mod_dir(ctx.config, gid, mod)
        rec_path = d / ".gbox-mod.json"
        try:
            rec = json.loads(rec_path.read_text()) if rec_path.is_file() else {"name": mod, "game_id": gid}
        except (OSError, ValueError):
            rec = {"name": mod, "game_id": gid}
        rec |= {"cast": [{"slot": r["slot"], "character": r["character"], **per.get(r["slot"], {"status": "failed"})}
                         for r in p["assignments"]], "cast_source": p["source"], "cast_mapping": p["mapping"],
                "cast_seed": p["seed"], "title": f"{game.get('title')}: cast as {p['source']}", "verified_in_game": False,
                "retarget_profiles": profiles, "cast_plan": digest, "built": time.time()}
        if p.get("prefer"):
            rec["cast_prefer"] = p["prefer"]
        if p.get("slots_filter") not in (None, "", "all"):
            rec["cast_slots"] = p["slots_filter"]
        # "What this changes" (gbox.build_summary reads `what` / `where_to_look`): the writer's own summary when it
        # gives one (AUF: mission and multiplayer characters, donors, levels)
        for k in ("what", "where_to_look"):
            if (res.get("summary") or {}).get(k):
                rec[k] = res["summary"][k]
        if showcase:
            rec["title"] = f"{game.get('title')}: Sonic showcase ({p['source']})"
            rec["showcase"] = {"source": p["source"], "plan": digest, "writer": p["writer"], "strategy": p["strategy"],
                               **({"linked_from": linked_from} if linked_from else {})}
        from . import build_record                       # who went where, by name (the Builds view's 360 pairs)
        rec = build_record.stamp(
            rec, kind="cast", slots=[{"slot": r["slot"], "slot_name": r.get("slot_name") or r["slot"],
                                      "donor": r["character"], "donor_name": r.get("donor") or r["character"],
                                      "source": r.get("source") or ""} for r in p["assignments"]],
            **build_record.from_ctx(ctx))
        if rec_path.parent.is_dir():
            if rec_path.is_file() and rec_path.stat().st_nlink > 1:
                rec_path.unlink()                         # a hard-linked marker: never write through to the source
            rec_path.write_text(json.dumps(rec, default=str))
        for r in p["assignments"]:
            # a showcase build is a test version: the Mods page and the game's Special builds list it, Play-as doesn't
            # (an evicted showcase mod leaves no character target pointing at a missing folder)
            if not showcase and per.get(r["slot"], {}).get("status") in ("built", "partial"):
                try:
                    C._api(ctx, "POST", f"/api/characters/{r['character']}/targets",
                           json={"game_id": gid, "slot": r["slot"], "mod": mod, "nodes": [C.HOST_OS],
                                 "notes": f"whole-cast build ({p['source']} -> {game.get('title')}); "
                                          "unverified in game"})
                except Exception:                         # noqa: BLE001 - the record is a convenience
                    pass
    full = [s for s, r in per.items() if r.get("status") == "built"]
    status = "built" if mod and len(full) == len(pairs) else "partial" if mod and built else "failed"
    return _report(p, per, mod if built else None, status, launch and mod and built and _launch(ctx, gid, mod),
                   res.get("detail"))


def _launch(ctx, gid, mod):
    from . import characters as C
    return C._launch(ctx, gid, mod, C.HOST_OS)


def _report(p: dict, per: dict, mod, status: str, launch, detail=None) -> dict:
    rows = []
    for r in p["assignments"]:
        x = per.get(r["slot"]) or {"status": "failed", "reason": "the writer did not report this slot"}
        rows.append({"slot": r["slot"], "slot_name": r["slot_name"], "character": r["character"], "donor": r["donor"],
                     "status": x.get("status"), **({"reason": x["reason"]} if x.get("reason") else {})})
    rows += [{"slot": s["slot"], "status": "skipped", "reason": s["reason"]} for s in p.get("skipped") or []]
    n = sum(r["status"] == "built" for r in rows)
    out = {"status": status, "mod": mod, "report": rows, "launch": launch or None,
           "message": (f"{n}/{len(p['assignments'])} slots built into {mod}" if mod else
                       "no slot was built") + (f"; {len(p.get('refused') or [])} donors refused" if p.get("refused") else "")
                      + "; unverified in game until launched"}
    if detail:
        out["detail"] = detail
    return out


# ---------------------------------------------------------------- per-writer multi-slot builders

def _rebuild(inp):
    """The same request with rebuild=True (pydantic CharIn or a SimpleNamespace)."""
    if hasattr(inp, "model_copy"):
        return inp.model_copy(update={"rebuild": True})
    return SimpleNamespace(**{**vars(inp), "rebuild": True})


def _slot_name(p: dict, slot: str) -> str:
    return next((r.get("slot_name") or slot for r in p.get("assignments") or [] if r.get("slot") == slot), slot)


def _shim(inp, **kw):
    """A CharIn-like copy for a writer's own use()/match() (never launches)."""
    d = inp.model_dump() if hasattr(inp, "model_dump") else dict(vars(inp))
    d.update(kw, launch=False, session_id="")
    return type(inp)(**d) if hasattr(inp, "model_dump") else SimpleNamespace(**d)


def _single(ctx, game, pairs, name, inp):
    """A writer with one slot: its own characters op=use build."""
    from . import characters as C
    slot, meta = pairs[0]
    try:
        res = C.characters_tool(_shim(inp, op="use", character=meta["slug"], slot=slot, game_id=game["game_id"],
                                      pairs=[]), ctx)["result"]
    except Exception as e:                                # noqa: BLE001
        return {"mod": None, "slots": {slot: {"status": "failed", "reason": str(e)[:500]}}}
    ok = bool(res.get("mod")) and not re.search(r"missing|fail|not_working", str(res.get("status")))
    return {"mod": res.get("mod"), "slots": {slot: {"status": "built" if ok else "failed",
                                                     **({} if ok else {"reason": res.get("message") or res.get("status")})}}}


def _match_builder(module: str):
    def b(ctx, game, pairs, name, inp):
        import importlib
        m = importlib.import_module(f"gbox.{module}")
        chars = [meta for _s, meta in pairs]
        try:
            res = m.match(ctx, chars, game, _shim(inp, op="match", pairs=[{"character": c["slug"], "slot": s}
                                                                           for s, c in pairs]),
                          [(meta["slug"], s) for s, meta in pairs], name)
        except Exception as e:                            # noqa: BLE001 - one wrestler's failure fails this disc build
            return {"mod": None, "slots": {s: {"status": "failed", "reason": str(e)[:500]} for s, _m in pairs}}
        ok = bool(res.get("mod")) and res.get("status") in ("built", "ready", "built+launched", "launched")
        why = res.get("error") or res.get("message") or res.get("status")
        return {"mod": res.get("mod") if ok else None, "detail": {k: res.get(k) for k in ("replaces", "status")},
                "slots": {s: {"status": "built"} if ok else {"status": "failed", "reason": str(why)[:500]}
                          for s, _m in pairs}}
    return b


def _doa2(ctx, game, pairs, name, inp):
    from . import doa2_swap
    try:
        res = doa2_swap.use_roster(ctx, pairs[0][1], game, _shim(inp, slot="roster", title=inp.seed or "",
                                   pairs=[{"character": m["slug"], "slot": s.split(":", 1)[-1]} for s, m in pairs]))
    except Exception as e:                                # noqa: BLE001
        return {"mod": None, "slots": {s: {"status": "failed", "reason": str(e)[:500]} for s, _m in pairs}}
    return {"mod": res.get("mod"), "detail": {"roster": res.get("roster")},
            "slots": {s: {"status": "built"} for s, _m in pairs}}


def _pso(ctx, game, pairs, name, inp):
    from . import characters as C, pso_enemy
    return pso_enemy.build_cast(ctx.config, game, C._dc_gdi(ctx, game), pairs, name, ctx.progress)


def _gta_lcs(ctx, game, pairs, name, inp):
    from . import characters as C, gta_lcs_cast
    return gta_lcs_cast.build_cast(ctx.config, game, C._rom(ctx, game), pairs, name, ctx.progress)


def _gta_vc(ctx, game, pairs, name, inp):
    from . import characters as C, gta_vc_swap
    return gta_vc_swap.build_cast(ctx.config, game, C._rom(ctx, game), pairs, name, ctx.progress)


def _etm(ctx, game, pairs, name, inp):
    from . import etm_swap
    return etm_swap.build_cast(ctx.config, game, pairs, name, ctx.progress)
def _mgs2(ctx, game, pairs, name, inp):
    from . import mgs2_swap
    return mgs2_swap.build_cast(ctx.config, game, pairs, name, ctx.progress)
def _ff7(ctx, game, pairs, name, inp):
    from . import ff7_swap
    return ff7_swap.build_cast(ctx.config, game, pairs, name, ctx.progress)


def _oot(ctx, game, pairs, name, inp):
    from . import oot_swap
    return oot_swap.build_cast(ctx.config, game, pairs, name, ctx.progress,
                               strict_cutscenes=bool(getattr(inp, "strict_cutscenes", True)))


def _jgr(ctx, game, pairs, name, inp):
    from . import characters as C, filemods, jgr, jgr_swap
    from .gdrom import GDRom, patch_gdi
    gdi = C._dc_gdi(ctx, game)
    disc = GDRom(str(gdi))
    staged = {jgr.PLAYER_AFS: disc.read(jgr.PLAYER_AFS)}
    work = Path(ctx.config.cache) / "characters_build" / "cast" / name
    bl = C._blender(ctx.config)

    def step(slot, meta):
        def run(files):
            data = files[jgr.PLAYER_AFS]
            index = jgr_swap.resolve_slot(slot, data)["archive"]
            roles = (meta.get("rig") or {}).get("roles") or {}
            b = jgr.build_swap(gdi, C.library_root(ctx.config) / meta["slug"] / meta["model"], roles,
                               work / f"{index:02d}", meta["name"], index, bl, lambda p, m: None,
                               (meta.get("rig") or {}).get("scale"), data=data)
            return b["files"]
        return run
    files, per = chain(staged, [(s, step(s, m)) for s, m in pairs], ctx.progress)
    if not any(r["status"] == "built" for r in per.values()):
        return {"mod": None, "slots": per}
    d = filemods.mod_dir(ctx.config, game["game_id"], name)
    if d.exists():
        import shutil
        shutil.rmtree(d)
    img = patch_gdi(gdi, d, name, files, ctx.progress)
    (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": game["game_id"], "image": img.name,
                                                  "files": sorted(files), "writer": "gbox.jgr (cast chain)"}))
    chain_written(per, name, img.name, files)
    return {"mod": name, "slots": per}


def _mgs_vr(ctx, game, pairs, name, inp):
    from . import mgs_vr_swap
    try:
        return mgs_vr_swap.build_cast(ctx, game, pairs, name, inp)
    except Exception as e:                                # noqa: BLE001 - the report names why
        return {"mod": None, "slots": {s: {"status": "failed", "reason": str(e)[:500]} for s, _m in pairs}}


def _crazy_taxi(ctx, game, pairs, name, inp):
    from . import characters as C, crazy_taxi as ct, crazy_taxi_swap as CTS
    from .gcdisc import GCDisc
    iso = C._gc_iso(ctx, game)
    disc = GCDisc(iso)
    bank = disc.read(CTS.BANK)
    texbank = disc.read(CTS.TEXBANK) if CTS.TEXBANK in getattr(disc, "files", {}) else None
    disc.f.close()
    groups = CTS.people(ct.read_bank(bank))

    def step(slot, meta):
        def run(files):
            sl = CTS.parse_slot(slot, "axel", groups)
            glb = C._local_or_fetch(ctx, meta, meta["model"])
            from .retarget_profile import profile_of
            new, _rep = CTS.swap_files(files, glb, dict((meta.get("rig") or {}).get("roles") or {}), sl,
                                       profile=profile_of((meta.get("rig") or {}).get("scale")))
            return new
        return run
    staged = {CTS.BANK: bank, **({CTS.TEXBANK: texbank} if texbank is not None else {})}
    files, per = chain(staged, [(s, step(s, m)) for s, m in pairs], ctx.progress)
    if not any(r["status"] == "built" for r in per.values()):
        return {"mod": None, "slots": per}
    extra = {CTS.TEXBANK: files[CTS.TEXBANK]} if texbank is not None and files[CTS.TEXBANK] != texbank else {}
    b = ct.build_mod(ctx.config, game, iso, files[CTS.BANK], name, f"Crazy Taxi {name}.iso", progress=ctx.progress,
                     **({"extra": extra} if extra else {}))
    chain_written(per, name, Path(str((b or {}).get("image") or f"Crazy Taxi {name}.iso")).name, files)
    return {"mod": name, "slots": per}


def _twin_snakes(ctx, game, pairs, name, inp):
    from . import twin_snakes_swap
    return twin_snakes_swap.build_cast(ctx.config, game, pairs, name, ctx.progress)


def _soulcalibur(ctx, game, pairs, name, inp):
    from . import soulcalibur_swap
    try:
        return soulcalibur_swap.build_cast(ctx, game, pairs, name)
    except Exception as e:                                # noqa: BLE001 - the disc build failed as a whole
        return {"mod": None, "slots": {s: {"status": "failed", "reason": str(e)[:500]} for s, _m in pairs}}


def _soulcalibur2(ctx, game, pairs, name, inp):
    from . import soulcalibur2_swap
    return soulcalibur2_swap.build_cast(ctx.config, game, pairs, name, ctx.progress)


def _stranglehold(ctx, game, pairs, name, inp):
    from . import stranglehold_swap
    return stranglehold_swap.build_cast(ctx.config, game, pairs, name, ctx.progress)


def _doa3(ctx, game, pairs, name, inp):
    from . import doa3_cast
    try:
        return doa3_cast.build_cast(ctx, game, pairs, name)
    except Exception as e:                                # noqa: BLE001 - the disc build failed as a whole
        return {"mod": None, "slots": {s: {"status": "failed", "reason": str(e)[:500]} for s, _m in pairs}}


def _auf(ctx, game, pairs, name, inp):
    from . import auf_swap
    return auf_swap.build_cast(ctx, game, pairs, name, ctx.progress)


BUILDERS = {
    "gbox.twin_snakes_swap": _twin_snakes,
    "gbox.stranglehold_swap": _stranglehold,
    "gbox.soulcalibur2_swap": _soulcalibur2,
    "gbox.pso_player": _pso,
    "gbox.doa2_swap": _doa2,
    "gbox.doa3_cast": _doa3,
    "gbox.soulcalibur_swap": _soulcalibur,
    "gbox.defjam_writer": _match_builder("defjam_writer"),
    "gbox.yukes_sd": _match_builder("yukes_sd"),
    "gbox.aki_wrestling": _match_builder("aki_wrestling"),
    "gbox.gta_vc_swap": _gta_vc,
    "gbox.gta_stories_models": _gta_lcs,
    "gbox.etm_swap": _etm,
    "gbox.mgs2_swap": _mgs2,
    "gbox.oot_swap": _oot,
    "gbox.jgr_swap": _jgr,
    "gbox.crazy_taxi_swap": _crazy_taxi,
    "gbox.mgs_vr_swap": _mgs_vr,
    "gbox.auf_swap": _auf,
    "gbox.ff7_swap": _ff7,
}
