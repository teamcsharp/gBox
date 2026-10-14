"""Jet Grind Radio (USA, Dreamcast) character writer: a collection character in place of one of the playable cast.

`characters op=use game="Jet Grind Radio (USA)" character=<slug> slot=<slot>` routes here. Slots:

- ``player``: the character the operator skates as. A new game starts as Beat (native character ID 0, PLAYER.AFS
  archive 04, ``erekidat.bin``); the pick-whip frames of #1150 / #1153 / #1156 all showed him at first control. When
  the operator plays someone else, pass ``active_id`` (that character's native ID 0-15) or name them with
  ``character:<name>``. The result always says which character was replaced and whether it was assumed.
- ``character:<name>``: one cast member by the disc's own names: ``beat`` (``ereki``), ``gum``, ``corn``,
  ``combo`` (``conpo``), ``code``, ``nuts`` (``nat``), ``reco``, ``bis``, ``yoyo``, ``plug`` (``pench``),
  ``goji``, ``pots`` and the rival leaders ``rival_lshocker``, ``rival_ntank``, ``rival_pjam``, ``rival_snpjam``.
- ``id:N`` (native character ID) and ``NN`` / ``jgr_charNN`` (archive position) as gbox.jgr.swap_index reads them.

The build is gbox.jgr's writer: the donor is fitted to the shared 20-node JGR body (gbox.ninja_swap.fit with the
rig roles in jgr.BODY_ROLES), decimated until it fits the PLAY entry's own AFS room, its strips re-encoded as Ninja
chunk lists inside every textured body group (gameplay, low detail, spray-can variants) under each group's own
texlist id for the body atlas, and the atlas re-encoded in place of that PTEX texture (same PVR format and size).
PLAYER.AFS keeps its length and every other entry; gbox.gdrom.patch_gdi writes a new GD-ROM image into a new mod
directory (never the owned disc, never an existing mod). gbox.pso_player's writer is not used: a PLAY is a raw node
tree without the NJCM wrapper, and its node structs must stay where 1ST_READ's binding record points.

Native gameplay replacement is runtime-unverified until a launch shows the donor skating (docs/jgr_pipeline.md).
"""
from __future__ import annotations

from types import SimpleNamespace

from . import jgr

GAME_IDS = dict(jgr.GAME_IDS)
PLAYER_DEFAULT_ID = 0          # Beat: the new-game player (USA disc; native debug label "BEAT(EREKI)")
SLOT_PREFIX = "character:"


def replacement_scope() -> dict:
    """Distinguish the implemented PLAYER path from the operator's whole-world request."""
    return {'complete_world_replacement': False,
            'implemented': ['PLAYER.AFS textured body groups for 16 character slots'],
            'missing': ['ENEMY.AFS police and enforcement actors', 'ENEMY.AFS rival gang members',
                        'Professor K model/resource binding', 'character-select and title presentation models',
                        'cinematic/demo archive model instances'],
            'message': 'A PLAYER.AFS cast build does not replace police, all gang members, Professor K or every scene. '
                       'Keep those contexts unverified until their separate resources are mapped, written and inspected.'}


def _label(index: int) -> tuple[str, str]:
    """(slot name, display name) of archive `index` on the USA disc: the native debug label when it has one."""
    name = jgr.ARCHIVE_NAMES[index]
    label = jgr.NATIVE_DEBUG_NAMES[jgr.USA_NATIVE_IDS[index]]
    if label:
        first = label.split("(")[0]
        return first.lower().replace("_", ""), first.replace("_", "-").title()
    return name, name.replace("_", " ").title()


def cast() -> list[dict]:
    """The 16 PLAYER.AFS characters (verified USA names): slot, display name, native ID, archive index, aliases."""
    out = []
    for index, name in enumerate(jgr.ARCHIVE_NAMES):
        slot_name, display = _label(index)
        native = jgr.USA_NATIVE_IDS[index]
        label = jgr.NATIVE_DEBUG_NAMES[native]
        aliases = sorted({name, slot_name, *(label.replace(")", "").lower().split("(") if label else [])})
        out.append({"slot": SLOT_PREFIX + slot_name, "name": display, "native_id": native, "archive": index,
                    "aliases": aliases, "rival": name.startswith("rival_"), "collection_slug": f"jgr_char{index:02d}"})
    return out


def cast_slots() -> list[dict]:
    """The cast menu for characters op=collect / char_coverage.cast_slots: player first, then every cast member."""
    beat = next(c for c in cast() if c["native_id"] == PLAYER_DEFAULT_ID)
    rows = [{"slot": "player", "name": f"Player ({beat['name']} at a new game; pass active_id for another)",
             "kind": "player", "native_id": PLAYER_DEFAULT_ID, "archive": beat["archive"],
             "alias_of": beat["slot"]}]                     # the same model as Beat's slot (a cast swap fills it once)
    for c in cast():
        rows.append({"slot": c["slot"], "name": c["name"], "kind": "character", "native_id": c["native_id"],
                     "archive": c["archive"]})
    return rows


def resolve_slot(slot: str | None, data=None, active_id: int | None = None) -> dict:
    """slot -> {archive, native_id, slot, assumed}. data: PLAYER.AFS bytes or a callable returning them (needed for
    id:N; names use the archive's own directory when given, else the verified USA table)."""
    s = (slot or "player").strip()
    low = s.lower()
    if low == "player":
        if active_id is not None:
            if type(active_id) is not int or not 0 <= active_id < jgr.CHARACTER_COUNT:
                raise ValueError("active_id must be a native integer ID from 0 to 15")
            index, assumed = jgr.swap_index("player", data, active_id), False
        else:
            index, assumed = jgr.USA_NATIVE_IDS.index(PLAYER_DEFAULT_ID), True
            buf = data() if callable(data) else data
            if buf is not None:                              # the disc's own binding wins over the USA table
                index = jgr.archive_index_for_native_id(buf, PLAYER_DEFAULT_ID)
    elif low.startswith(SLOT_PREFIX):
        name = s[len(SLOT_PREFIX):].strip()
        if not name:
            raise ValueError("slot 'character:' needs a name, e.g. character:beat")
        index, assumed = jgr.swap_index(name, data), False
    else:
        index, assumed = jgr.swap_index(s, data, active_id), False
    native = jgr.USA_NATIVE_IDS[index]
    buf = data() if callable(data) else data
    if buf is not None:
        native = jgr.native_id_for_archive(buf, index)
    slot_name, display = _label(index)
    return {"archive": index, "native_id": native, "name": display, "slot": SLOT_PREFIX + slot_name,
            "assumed": assumed}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for JGR: resolve the slot, then build (or reuse) the identity-checked mod with gbox.jgr."""
    from . import characters as C
    from .gdrom import GDRom
    if game.get("game_id") not in GAME_IDS:
        raise ValueError(f"the JGR writer covers {', '.join(GAME_IDS.values())} only")
    source = {}

    def load():
        if "data" not in source:
            source["data"] = GDRom(str(C._dc_gdi(ctx, game))).read(jgr.PLAYER_AFS)
        return source["data"]
    target = resolve_slot(getattr(inp, "slot", None), load, getattr(inp, "active_id", None))
    shim = SimpleNamespace(slot=f"{target['archive']:02d}", active_id=None,
                           rebuild=bool(getattr(inp, "rebuild", False)), launch=bool(getattr(inp, "launch", False)))
    out = jgr.use(ctx, meta, game, shim)
    note = (f"slot=player was taken as {target['name']} (native ID {target['native_id']}), the character a new game "
            "starts with; pass active_id or slot=character:<name> when playing someone else.") if target["assumed"] else ""
    return out | {"slot": getattr(inp, "slot", None) or "player", "replaced": target,"replacement_scope":replacement_scope(),
                  **({"player_assumed": note} if note else {})}
