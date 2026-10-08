"""`re_inventory`: one inventory helper for every Resident Evil gBox can reach live. Register with:
    from . import re_inventory  # noqa: F401

One shape for every game:  {game, game_id, backend, character, slots: [{slot, item_id, name, kind, amount, max, icon?}],
health: {hp, max}, loadout: {characters} | None, ops: [...]}  and the ops  give {item, amount} | remove {slot} |
set {slot, item?, amount?} | loadout {character, items} | health {amount}.

Backends (by catalog game_id):
  re4      Resident Evil 4 GameCube (G4BE08, both discs): ItemMgr item array (gbox/re_games.py), give/replace through
           re_mods_tool (the game's own take-item routine), remove/set amount by direct writes, loadout = Mercenaries.
  re6      Resident Evil 6 Xbox 360 (Xenia): reads the player's live inventory (re6_tool constants); give/remove/set/
           loadout go through the `re6` tool's own ops (give_now, remove_item, set_slot, set_loadout).
  struct   any game whose profiles/gamedata/<game_id>-items.json has an "inventory" layout (classic REs: a fixed slot
           array {id, count, ...}): read/write the slots directly.
Item names resolve per game: the game's own names, then the cross-game alias table (CANON: "Rocket Launcher",
"First Aid Spray", "Green Herb", ... -> that game's id), then fuzzy. Reads also run on the control plane through the
read-only session channel (re_inventory_api.py), so the on-screen helper can refresh every second without jobs.
"""
from __future__ import annotations

import difflib
import json
import re
import struct
from pathlib import Path

from pydantic import BaseModel

from .models import Permission as P
from .registry import Unsupported, tool

GAMEDATA = Path(__file__).resolve().parent.parent / "profiles" / "gamedata"
RE4_GC = {"78ab9efa2e310db4", "e42c9b780c07c437"}
RE4_WII = {"79c3a3eccb34fe62"}
RE6 = {"0871eee3b68cdea3"}
RE4_NOT_LIVE = {"2364c91bf295d0c3": "Xbox 360", "109d8ee7747a7dd8": "PS2", "0a53cf740fc0f3f7": "PC (Ultimate HD)",
                "4d8b13b6b5657313": "PS4"}
RE6_CHARS = ["Leon", "Helena", "Chris", "Piers", "Jake", "Sherry", "Ada", "Agent"]
RE4_CHARS = ["Leon", "Ada", "HUNK", "Krauser", "Wesker"]

# ---------------------------------------------------------------- catalogs + cross-game names

KINDS = {"weapon": "weapon", "grenade": "weapon", "ammo": "ammo", "healing": "heal", "heal": "heal", "recovery": "heal",
         "key": "key", "treasure": "other", "other": "other"}
_CAT: dict[str, tuple[float, dict]] = {}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).replace("’", "'").replace("*", "").strip().lower())


def _int(v) -> int:
    return v if isinstance(v, int) else int(str(v), 0)


def catalog(game_id: str) -> dict:
    """profiles/gamedata/<game_id>-items.json, items normalised to {id:int, name, kind, max?, icon?}."""
    f = GAMEDATA / f"{game_id}-items.json"
    if not f.is_file():
        return {}
    mt = f.stat().st_mtime
    if game_id in _CAT and _CAT[game_id][0] == mt:
        return _CAT[game_id][1]
    raw = json.loads(f.read_text(encoding="utf-8"))
    items = []
    for it in raw.get("items", []):
        try:
            iid = _int(it["id"])
        except (KeyError, ValueError):
            continue
        row = {"id": iid, "name": str(it.get("name", f"item {iid}")).rstrip("*"),
               "kind": KINDS.get(str(it.get("kind", "other")).lower(), "other")}
        for k in ("max", "icon", "owner", "special", "flag"):
            if it.get(k) not in (None, ""):
                row[k] = it[k]
        items.append(row)
    out = dict(raw, items=items)
    _CAT[game_id] = (mt, out)
    return out


# canonical name, kind, the names different REs give it (most specific first)
CANON = [
    ("Handgun", "weapon", ["handgun", "hand gun", "handgun (leon)", "nine-oh-nine (909)", "beretta", "beretta m92f", "m92f", "h&k vp70",
                           "vp70", "sigpro", "sigpro sp 2009", "browning", "browning hp", "glock 17", "wing shooter"]),
    ("Shotgun", "weapon", ["shotgun", "benelli m3s", "remington m1100-p", "w-870", "pump action shotgun"]),
    ("Magnum", "weapon", ["magnum", "colt python", "s&w m629c", "broken butterfly", "elephant killer", "lightning hawk",
                          "desert eagle", "custom magnum"]),
    ("Rocket Launcher", "weapon", ["rocket launcher", "r. launcher"]),
    ("Infinite Rocket Launcher", "weapon", ["infinite launcher", "infinite rocket launcher", "rocket launcher (infinite)"]),
    ("Grenade Launcher", "weapon", ["grenade launcher", "grenade launcher (grenade)", "grenade launcher (explosive)", "g. launcher (grenade rounds)", "g. launcher"]),
    ("Machine Gun", "weapon", ["sub machine gun", "submachine gun", "s. machine gun", "smg", "tmp", "m-100p", "ingram", "mp-af",
                               "assault rifle", "chicago typewriter"]),
    ("Sniper Rifle", "weapon", ["sniper rifle", "rifle", "semi-auto sniper rifle", "rifle (semi-auto)"]),
    ("Gatling Gun", "weapon", ["gatling gun", "minigun", "mini gun"]),
    ("Flamethrower", "weapon", ["flamethrower", "flame thrower"]),
    ("Crossbow", "weapon", ["crossbow", "bowgun", "bow gun", "krauser's bow"]),
    ("Knife", "weapon", ["knife", "combat knife", "survival knife"]),
    ("Hand Grenade", "weapon", ["hand grenade"]),
    ("Flash Grenade", "weapon", ["flash grenade"]),
    ("Incendiary Grenade", "weapon", ["incendiary grenade"]),
    ("Handgun Ammo", "ammo", ["handgun ammo", "handgun bullets", "h. gun bullets", "h.g. bullets", "handgun rounds", "9mm ammo", "clip", "handgun clip"]),
    ("Shotgun Shells", "ammo", ["shotgun shells", "12-gauge shells", "shells"]),
    ("Magnum Ammo", "ammo", ["magnum ammo", "magnum rounds", "magnum bullets", "m. bullets", ".50 action-express magnum ammo"]),
    ("Rifle Ammo", "ammo", ["rifle ammo", "rifle bullets", "7.62mm nato ammo"]),
    ("Machine Gun Ammo", "ammo", ["tmp ammo", "machine gun bullets", "m.g. bullets", "sub machine gun bullets", "smg ammo", "5.56mm nato ammo",
                                  "assault rifle clip"]),
    ("Grenade Rounds", "ammo", ["grenade rounds", "g. rounds", "explosive rounds", "40mm explosive rounds"]),
    ("First Aid Spray", "heal", ["first aid spray", "f. aid spray", "first aid"]),
    ("Green Herb", "heal", ["green herb", "herb (green)"]),
    ("Red Herb", "heal", ["red herb", "herb (red)"]),
    ("Blue Herb", "heal", ["blue herb"]),
    ("Yellow Herb", "heal", ["yellow herb"]),
    ("Mixed Herb (G+G)", "heal", ["mixed herb (g+g)", "mixed herbs (g+g)", "green herb (x2)", "herb (g+g)"]),
    ("Mixed Herb (G+R)", "heal", ["mixed herb (g+r)", "mixed herbs (g+r)", "herb (g+r)"]),
    ("Ink Ribbon", "other", ["ink ribbon"]),
]
CANON_EXTRA = {"rpg": "Rocket Launcher", "bazooka": "Rocket Launcher", "rocket": "Rocket Launcher", "pistol": "Handgun",
               "gun": "Handgun", "spray": "First Aid Spray", "medkit": "First Aid Spray", "herb": "Green Herb",
               "hand cannon": "Magnum", "handcannon": "Magnum", "revolver": "Magnum", "smg": "Machine Gun",
               "uzi": "Machine Gun", "minigun": "Gatling Gun", "sniper": "Sniper Rifle", "frag": "Hand Grenade",
               "flashbang": "Flash Grenade", "molotov": "Incendiary Grenade", "bullets": "Handgun Ammo", "ammo": "Handgun Ammo"}


def canon_id(cat: dict, canon: str) -> dict | None:
    """The game's item for a cross-game name (None = that game has no such item)."""
    c = next((x for x in CANON if _norm(x[0]) == _norm(canon)), None)
    if not c:
        return None
    _, kind, pats = c
    items = [i for i in cat.get("items", []) if not i.get("special")]
    pool = [i for i in items if i["kind"] == kind] or items
    names = [(_norm(i["name"]), i) for i in pool]
    for p in pats:                                       # exact first, in the order of the alias list
        hit = next((i for n, i in names if n == p), None)
        if hit:
            return hit
    for p in pats:
        hit = next((i for n, i in names if n.startswith(p + " ") or n.startswith(p + "(")), None)
        if hit:
            return hit
    for p in (p for p in pats if " " in p):              # loose match only for specific (multi-word) names
        hit = next((i for n, i in names if re.search(r"(^|\W)" + re.escape(p) + r"($|\W)", n)), None)
        if hit:
            return hit
    return None


def cross(game_id: str) -> list[dict]:
    cat = catalog(game_id)
    out = []
    for name, kind, _ in CANON:
        it = canon_id(cat, name) if cat else None
        out.append({"name": name, "kind": kind, "id": it["id"] if it else None, "game_name": it["name"] if it else None})
    return out


def resolve(game_id: str, q) -> dict:
    """Item name / id / cross-game name -> the game's catalog row. Raises ValueError with the closest names."""
    cat = catalog(game_id)
    items = cat.get("items", [])
    if not items:
        raise ValueError(f"no item catalog for this game (profiles/gamedata/{game_id}-items.json)")
    if isinstance(q, dict):
        q = q.get("id", q.get("item", q.get("name")))
    s = _norm(q)
    by_id = {i["id"]: i for i in items}
    if isinstance(q, int) or re.fullmatch(r"0x[0-9a-f]+|\d+", s):
        iid = q if isinstance(q, int) else int(s, 0)
        if iid in by_id:
            return by_id[iid]
        raise ValueError(f"item id {iid} isn't in this game's catalog")
    sq = re.sub(r"[^a-z0-9]", "", s)
    exact = [i for i in items if _norm(i["name"]) == s] or \
        [i for i in items if sq and re.sub(r"[^a-z0-9]", "", _norm(i["name"])) == sq]
    if exact:
        return next((i for i in exact if not i.get("special")), exact[0])
    canon = CANON_EXTRA.get(s) or next((c[0] for c in CANON if _norm(c[0]) == s or s in c[2]), None)
    if canon:
        hit = canon_id(cat, canon)
        if hit:
            return hit
        raise ValueError(f"{canon} doesn't exist in {cat.get('game', 'this game')}")
    part = [i for i in items if s in _norm(i["name"]) and not i.get("special")]
    if part:
        return sorted(part, key=lambda i: len(i["name"]))[0]
    names = {_norm(i["name"]): i for i in items}
    close = difflib.get_close_matches(s, list(names), n=3, cutoff=0.55)
    if close:
        return names[close[0]]
    raise ValueError(f"no item matches {q!r} in {cat.get('game', 'this game')}")


# ---------------------------------------------------------------- per-game backends

def backend_of(game_id: str) -> str | None:
    if game_id in RE4_GC:
        return "re4"
    if game_id in RE4_WII:
        return "re4wii"
    if game_id in RE6:
        return "re6"
    if game_id in RE4_NOT_LIVE:
        return "not_live"
    if catalog(game_id).get("inventory"):
        return "struct"
    return None


def support(game_id: str) -> dict:
    b = backend_of(game_id)
    cat = catalog(game_id)
    loadout = {"re4": {"characters": RE4_CHARS, "mode": "The Mercenaries start loadout (set it before picking the character)"},
               "re6": {"characters": RE6_CHARS, "mode": "The Mercenaries start loadout (used from the next match)"}}.get(b)
    ops = {"re4": ["give", "remove", "set", "loadout", "health"], "re6": ["give", "remove", "set", "loadout"],
           "struct": ["give", "remove", "set", "health"], "re4wii": [], "not_live": []}.get(b, [])
    note = {"re4wii": "Resident Evil 4: Wii Edition: the item manager isn't located in the Wii build yet (only the GameCube "
                      "release has live inventory); items can be picked, not applied",
            "not_live": f"Resident Evil 4 ({RE4_NOT_LIVE.get(game_id)}) has no live memory access in gBox; play the GameCube "
                        "release (Dolphin on the Spark) for the inventory helper"}.get(b)
    return {"game_id": game_id, "game": cat.get("game"), "backend": b, "live": b in ("re4", "re6", "struct"),
            "ops": ops, "loadout": loadout, "note": note, "has_catalog": bool(cat.get("items"))}


def _slot(i: int, iid, name, kind="other", amount=0, mx=None, **kw) -> dict:
    return {"slot": i, "item_id": iid, "name": name, "kind": kind, "amount": amount, "max": mx, **kw}


def _row(cat_by_id: dict, iid: int) -> dict:
    return cat_by_id.get(iid) or {"id": iid, "name": f"item {iid:#x}", "kind": "other"}


# ---- RE4 GameCube (ItemMgr: 14-byte items {u16 id, u16 count, u8 in_use, u8 owner, u8, u8 level, u16 loaded, u8 x, y,
# outside_case, in_case}) -- see gbox/re_games.py
def _re4_ver(mem):
    from . import re_games as R
    gid = bytes(mem.read_memory(0x80000000, 6))
    if gid not in R.VERSIONS:
        raise Unsupported(f"not Resident Evil 4 GameCube NTSC-U ({gid!r})")
    V = R.VERSIONS[gid]
    if not V.has("ITEM_MGR"):
        raise Unsupported(f"the item manager isn't located in {V.name} yet (GameCube release only)")
    return V


def _re4_items(mem, V) -> list[dict]:
    arr, _, n = struct.unpack(">III", bytes(mem.read_memory(V.ITEM_MGR + 0x14, 12)))
    if not (0x80000000 <= arr < 0x81800000) or not 0 < n <= 512:
        return []
    d = bytes(mem.read_memory(arr, n * 14))
    out = []
    for k in range(n):
        e = d[k * 14:k * 14 + 14]
        if e[4] & 1:
            iid, cnt = struct.unpack_from(">HH", e)
            out.append({"slot": k, "addr": arr + k * 14, "id": iid, "count": cnt,
                        "loaded": struct.unpack_from(">H", e, 8)[0] & 0x1FFF, "in_case": bool(e[13]), "raw": e})
    return out


def re4_read(mem, game_id: str) -> dict:
    V = _re4_ver(mem)
    cat = catalog(game_id)
    by_id = {i["id"]: i for i in cat.get("items", [])}
    pg = struct.unpack(">I", bytes(mem.read_memory(V.P_GLOBAL, 4)))[0]
    g = bytes(mem.read_memory(pg + V.G_MONEY, 0x14))
    room = struct.unpack_from(">H", g, V.G_ROOM - V.G_MONEY)[0]
    hp, hpmax = struct.unpack_from(">hh", g, V.G_HP - V.G_MONEY)
    slots = []
    for it in _re4_items(mem, V):
        r = _row(by_id, it["id"])
        weapon = r["kind"] == "weapon" and "grenade" not in r["name"].lower()
        slots.append(_slot(it["slot"], it["id"], r["name"], r["kind"], it["loaded"] if weapon else it["count"], r.get("max"),
                           in_case=it["in_case"], amount_is="loaded ammo" if weapon else "count"))
    slots.sort(key=lambda s: (not s["in_case"], s["slot"]))
    return {"character": "Mercenaries" if room >> 8 == 4 else "Leon", "room": f"r{room:03x}",
            "money": struct.unpack_from(">I", g, 0)[0], "health": {"hp": hp, "max": hpmax if 0 < hpmax <= 30000 else None},
            "slots": slots, "capacity": None}


class _RM:
    """read_memory over re_mods_tool.Mem (its retries ride out Dolphin GDB-stub hiccups)."""

    def __init__(self, m):
        self.m = m

    def read_memory(self, a, n):
        return self.m.rd(a, n)


def re4_apply(ad, game_id: str, op: str, inp) -> dict:
    from . import re_mods_tool as RM
    g = RM.RE4(ad)
    V = g.V
    if op == "give":
        it = resolve(game_id, inp.item)
        r = RM.run(ad, "give", item=f"0x{it['id']:02X}", count=max(0, inp.amount), g=g)
        return {"message": f"{it['name']} is in your attache case." if r.get("placed") else
                f"No room in the attache case for {it['name']}.", "ok": bool(r.get("placed")), "item": it["name"]}
    if op in ("remove", "set"):
        cur = next((x for x in _re4_items(_RM(g.m), V) if x["slot"] == inp.slot), None)
        if not cur:
            raise ValueError(f"slot {inp.slot} is empty")
        old = _row({i["id"]: i for i in catalog(game_id).get("items", [])}, cur["id"])
        raw = cur["raw"]
        if op == "remove":
            g.m.wr(cur["addr"], raw[:4] + b"\x00" + raw[5:13] + b"\x00")       # free the item and its case cells
            ok = not any(x["addr"] == cur["addr"] for x in _re4_items(_RM(g.m), V))
            return {"message": f"Removed {old['name']}.", "ok": ok, "item": old["name"]}
        new = resolve(game_id, inp.item) if inp.item not in ("", None) else old
        if new["id"] != cur["id"]:
            held = g.m.u32(V.ITEM_MGR + 0x0C) == cur["addr"]        # ItemMgr+0xC = the equipped entry: the gun in Leon's hands
            r = RM.run(ad, "replace", item=f"0x{new['id']:02X}", target=str(inp.slot), count=max(0, inp.amount or 0), g=g)
            if not r.get("placed"):
                return {"message": r.get("note") or f"{new['name']} doesn't fit; {old['name']} put back", "ok": False}
            if inp.amount:                                      # the new item's amount: set it on the placed entry
                hit = next((x for x in _re4_items(_RM(g.m), V) if x["id"] == new["id"]), None)
                if hit:
                    _re4_amount(g, hit, new, inp.amount)
            note = ""
            if held and new["id"] in RM.weapon_classes(g):
                try:                                            # the game's own weapon change: model + code follow
                    RM.equip_item(g, new["id"])
                    note = " Equipped."
                except Exception as e:                          # noqa: BLE001 - the item is in place either way
                    note = f" (equip it from the case: {e})"
            return {"message": f"{old['name']} -> {new['name']}.{note}", "ok": True, "item": new["name"]}
        _re4_amount(g, cur, new, inp.amount)
        return {"message": f"{new['name']}: {inp.amount}.", "ok": True, "item": new["name"]}
    if op == "loadout":
        names = [f"0x{resolve(game_id, x)['id']:02X}" for x in (inp.items or [])]
        r = RM.run(ad, "merc_loadout", character=inp.character or "any", items=names, on=True, count=max(0, inp.amount), g=g)
        return {"message": f"Mercenaries loadout for {inp.character or 'everyone'}: " +
                (", ".join(r.get("items") or []) or "game default") + ". " + (r.get("note") or ""), "ok": bool(r.get("verified"))}
    if op == "health":
        pg = g.pg()
        g.m.wr(pg + V.G_HP, struct.pack(">h", max(1, min(30000, int(inp.amount)))))
        return {"message": f"HP set to {inp.amount}.", "ok": True}
    raise ValueError(f"op {op} isn't supported for Resident Evil 4")


def _re4_amount(g, cur: dict, row: dict, amount: int):
    weapon = row["kind"] == "weapon" and "grenade" not in row["name"].lower()
    raw = cur["raw"]
    if weapon:
        v = (struct.unpack_from(">H", raw, 8)[0] & 0xE000) | (max(0, int(amount)) & 0x1FFF)
        g.m.wr(cur["addr"] + 8, struct.pack(">H", v))
    else:
        g.m.wr(cur["addr"] + 2, struct.pack(">H", max(1, min(0xFFFF, int(amount)))))


# ---- RE6 (Xbox 360): player inventory = 24 slots of 0x1C bytes at player+INV (re6_tool constants)
def re6_read(mem, game_id: str) -> dict:
    from . import re6_tool as T
    by_id = {i["id"]: i for i in catalog(game_id).get("items", [])}
    ps = T.players(mem)
    if not ps:
        return {"character": None, "slots": [], "health": None, "message": "No player right now (menu / loading)."}
    p = ps[0]
    inv = bytes(mem.read_memory(p + T.INV, T.SLOT_SZ * 24))
    slots = []
    for k in range(24):
        s = inv[k * T.SLOT_SZ:(k + 1) * T.SLOT_SZ]
        if not s[4]:
            continue
        iid = T.code_item(struct.unpack_from(">H", s, 6)[0])
        r = _row(by_id, iid)
        slots.append(_slot(k, iid, r["name"], r["kind"], struct.unpack_from(">H", s, 0xA)[0], struct.unpack_from(">H", s, 0x10)[0],
                           icon=r.get("icon")))
    life, mx = struct.unpack(">hh", bytes(mem.read_memory(p + T.LIFE, 4)))
    return {"character": None, "players": len(ps), "slots": slots, "health": {"hp": life, "max": mx}, "capacity": 24}


def _re6_call(ctx, raw: dict) -> dict:
    from .registry import REGISTRY
    t = REGISTRY["re6"]
    try:
        return t.fn(t.In.model_validate(raw), ctx)["result"]
    except ValueError as e:
        if str(e).startswith("op:"):
            raise Unsupported(f"RE6 '{raw['op']}' isn't available in the re6 tool yet (being added); try again after the "
                              "next gBox update") from e
        raise


def re6_apply(ad, game_id: str, op: str, inp, ctx) -> dict:
    sid = inp.session_id
    if op == "give":
        it = resolve(game_id, inp.item)
        r = _re6_call(ctx, {"op": "give_now", "session_id": sid, "item": str(it["id"]), "amount": inp.amount,
                            "character": inp.character})
        return {"message": r.get("message") or f"{it['name']} given.", "ok": bool(r.get("live", True)), "item": it["name"], "re6": r}
    if op == "remove":
        r = _re6_call(ctx, {"op": "remove_item", "session_id": sid, "slot": inp.slot})
        return {"message": r.get("message") or f"Slot {inp.slot} emptied.", "ok": True, "re6": r}
    if op == "set":
        raw = {"op": "set_slot", "session_id": sid, "slot": inp.slot, "amount": inp.amount}
        if inp.item not in ("", None):
            raw["item"] = str(resolve(game_id, inp.item)["id"])
        r = _re6_call(ctx, raw)
        return {"message": r.get("message") or f"Slot {inp.slot} set.", "ok": True, "re6": r}
    if op == "loadout":
        items = []
        for x in inp.items or []:
            amt = int(x.get("amount") or 0) if isinstance(x, dict) else 0
            items.append({"id": resolve(game_id, x)["id"], "amount": amt})
        r = _re6_call(ctx, {"op": "set_loadout", "session_id": sid, "items": items, "character": inp.character or "any",
                            "replace": True})
        return {"message": r.get("message") or "Loadout set.", "ok": True, "re6": r}
    raise ValueError(f"op {op} isn't supported for Resident Evil 6")


# ---- generic slot array (classic REs; layout in the catalog JSON's "inventory")
def _layout(game_id: str, mem) -> dict:
    lay = dict(catalog(game_id).get("inventory") or {})
    if not lay:
        raise Unsupported("no inventory layout for this game")
    lay["endian"] = "<" if lay.get("endian", "little").startswith("l") else ">"
    lay["character"] = None
    for ch in lay.get("characters") or []:
        m = ch.get("match")
        ok = True
        if m:
            sz = int(m.get("size", 1))
            v = int.from_bytes(bytes(mem.read_memory(_int(m["addr"]), sz)), "little" if lay["endian"] == "<" else "big")
            ok = v == _int(m["value"])
        if ok:
            lay.update({k: v for k, v in ch.items() if k in ("addr", "slots", "stride")})
            lay["character"] = ch.get("name")
            break
    if isinstance(lay.get("slots"), dict):                      # slot count read from the game
        sz = int(lay["slots"].get("size", 1))
        lay["slots"] = int.from_bytes(bytes(mem.read_memory(_int(lay["slots"]["addr"]), sz)),
                                      "little" if lay["endian"] == "<" else "big")
    lay["addr"], lay["slots"], lay["stride"] = _int(lay["addr"]), int(lay.get("slots", 8)), int(lay.get("stride", 2))
    return lay


def _field(buf: bytes, f, endian: str) -> int:
    off, size = f
    return int.from_bytes(buf[off:off + size], "little" if endian == "<" else "big")


def _put(buf: bytearray, f, v: int, endian: str):
    off, size = f
    buf[off:off + size] = (int(v) & ((1 << (8 * size)) - 1)).to_bytes(size, "little" if endian == "<" else "big")


def struct_read(mem, game_id: str) -> dict:
    lay = _layout(game_id, mem)
    by_id = {i["id"]: i for i in catalog(game_id).get("items", [])}
    d = bytes(mem.read_memory(lay["addr"], lay["slots"] * lay["stride"]))
    empty, fid, fcnt = _int(lay.get("empty", 0)), lay.get("id", [0, 1]), lay.get("count", [1, 1])
    slots = []
    used = lay["slots"]
    if lay.get("item_count"):                                   # RE1: only slots 0..count-1 exist for the game
        used = min(used, bytes(mem.read_memory(_int(lay["item_count"]["addr"]), 1))[0])
    for k in range(used):
        s = d[k * lay["stride"]:(k + 1) * lay["stride"]]
        iid = _field(s, fid, lay["endian"])
        if iid == empty:
            continue
        r = _row(by_id, iid)
        slots.append(_slot(k, iid, r["name"], r["kind"], _field(s, fcnt, lay["endian"]), r.get("max"), icon=r.get("icon")))
    out = {"character": lay["character"], "slots": slots, "health": None, "capacity": lay["slots"]}
    h = lay.get("health")
    if h:
        sz = int(h.get("size", 2))
        hp = int.from_bytes(bytes(mem.read_memory(_int(h["addr"]), sz)), "little" if lay["endian"] == "<" else "big",
                            signed=bool(h.get("signed", True)))
        mx = h.get("max")
        if h.get("max_addr"):
            mx = int.from_bytes(bytes(mem.read_memory(_int(h["max_addr"]), sz)), "little" if lay["endian"] == "<" else "big",
                                signed=bool(h.get("signed", True)))
        out["health"] = {"hp": hp, "max": mx}
    return out


def struct_apply(ad, game_id: str, op: str, inp) -> dict:
    lay = _layout(game_id, ad)
    ic = lay.get("item_count")
    if not ic:
        return _struct_apply(ad, game_id, op, inp, lay)
    # the game keeps a count of occupied slots (RE1): slots past it are invisible, so the list stays packed from slot 0
    n = bytes(ad.read_memory(_int(ic["addr"]), 1))[0]
    size, st, fid = lay["slots"] * lay["stride"], lay["stride"], lay.get("id", [0, 1])
    d = bytearray(bytes(ad.read_memory(lay["addr"], size)))
    for k in range(min(n, lay["slots"]), lay["slots"]):         # stale bytes past the count are empty slots to us
        d[k * st:(k + 1) * st] = bytes(st)
    ad.write_memory(lay["addr"], bytes(d))
    res = _struct_apply(ad, game_id, op, inp, lay)
    d = bytes(ad.read_memory(lay["addr"], size))
    full = [d[k * st:(k + 1) * st] for k in range(lay["slots"]) if _field(d[k * st:(k + 1) * st], fid, lay["endian"]) != _int(lay.get("empty", 0))]
    packed = b"".join(full) + bytes(size - len(full) * st)
    if packed != d:
        ad.write_memory(lay["addr"], packed)
    ad.write_memory(_int(ic["addr"]), bytes([len(full)]))
    return res


def _struct_apply(ad, game_id: str, op: str, inp, lay: dict) -> dict:
    e, fid, fcnt = lay["endian"], lay.get("id", [0, 1]), lay.get("count", [1, 1])
    empty = _int(lay.get("empty", 0))
    extra = {int(k): _int(v) for k, v in (lay.get("extra") or {}).items()}
    cmax = (1 << (8 * fcnt[1])) - 1

    def read_slot(k):
        return bytearray(bytes(ad.read_memory(lay["addr"] + k * lay["stride"], lay["stride"])))

    def write_slot(k, buf):
        ad.write_memory(lay["addr"] + k * lay["stride"], bytes(buf))
        return bytes(ad.read_memory(lay["addr"] + k * lay["stride"], lay["stride"])) == bytes(buf)

    def fill(buf, row, amount):
        _put(buf, fid, row["id"], e)
        amt = amount if amount and amount > 0 else (row.get("max") or 1)
        _put(buf, fcnt, max(0, min(cmax, int(amt))), e)
        for off, v in extra.items():
            buf[off] = v & 0xFF
        if lay.get("flag") and row.get("flag") is not None:       # per-item display flag (RE3: how the count is drawn)
            _put(buf, lay["flag"], _int(row["flag"]), e)

    def check(k):
        if not 0 <= k < lay["slots"]:
            raise ValueError(f"slot must be 0..{lay['slots'] - 1}")

    if op == "give":
        row = resolve(game_id, inp.item)
        for k in range(lay["slots"]):
            buf = read_slot(k)
            if _field(buf, fid, e) == empty:
                fill(buf, row, inp.amount)
                return {"message": f"{row['name']} put in slot {k + 1}.", "ok": write_slot(k, buf), "item": row["name"], "slot": k}
        return {"message": f"No free slot for {row['name']} (inventory full): pick a slot to replace.", "ok": False}
    if op == "remove":
        check(inp.slot)
        buf = read_slot(inp.slot)
        _put(buf, fid, empty, e)
        _put(buf, fcnt, 0, e)
        for off in extra:
            buf[off] = 0
        return {"message": f"Slot {inp.slot + 1} emptied.", "ok": write_slot(inp.slot, buf)}
    if op == "set":
        check(inp.slot)
        buf = read_slot(inp.slot)
        if inp.item not in ("", None):
            row = resolve(game_id, inp.item)
            fill(buf, row, inp.amount)
        else:
            if _field(buf, fid, e) == empty:
                raise ValueError(f"slot {inp.slot + 1} is empty: choose an item")
            row = _row({i["id"]: i for i in catalog(game_id).get("items", [])}, _field(buf, fid, e))
            _put(buf, fcnt, max(0, min(cmax, int(inp.amount))), e)
        return {"message": f"Slot {inp.slot + 1}: {row['name']}.", "ok": write_slot(inp.slot, buf), "item": row["name"]}
    if op == "health":
        h = lay.get("health") or {}
        if not h:
            raise Unsupported("HP isn't located in this game yet")
        sz = int(h.get("size", 2))
        ad.write_memory(_int(h["addr"]), max(1, int(inp.amount)).to_bytes(sz, "little" if e == "<" else "big", signed=True))
        return {"message": f"HP set to {inp.amount}.", "ok": True}
    raise ValueError(f"op {op} isn't supported for this game (give | remove | set | health)")


# ---------------------------------------------------------------- one entry point (reads work with any read_memory object)

def read(mem, game_id: str) -> dict:
    sup = support(game_id)
    b = sup["backend"]
    base = {"game_id": game_id, "game": sup["game"], "backend": b, "ops": sup["ops"], "loadout": sup["loadout"]}
    if b == "re4":
        return base | re4_read(mem, game_id)
    if b == "re6":
        return base | re6_read(mem, game_id)
    if b == "struct":
        return base | struct_read(mem, game_id)
    raise Unsupported(sup["note"] or f"no live inventory for this game ({game_id})")


def apply(ad, game: dict, inp, ctx) -> dict:
    gid = game.get("game_id", "")
    b = backend_of(gid)
    op = inp.op.strip().lower()
    op = {"add": "give", "delete": "remove", "clear": "remove", "replace": "set", "change": "set", "hp": "health"}.get(op, op)
    if b == "re4":
        return re4_apply(ad, gid, op, inp)
    if b == "re6":
        return re6_apply(ad, gid, op, inp, ctx)
    if b == "struct":
        return struct_apply(ad, gid, op, inp)
    raise Unsupported(support(gid)["note"] or f"{game.get('title')}: no live inventory in gBox yet")


class Retry:
    """read_memory with a few retries (Dolphin's GDB stub refuses an access that lands in an exception handler)."""

    def __init__(self, mem, tries: int = 6):
        self.mem, self.tries = mem, tries

    def read_memory(self, a, n):
        import time
        last = None
        for i in range(self.tries):
            try:
                return bytes(self.mem.read_memory(a, n))
            except Exception as e:                                # noqa: BLE001 - retried
                last = e
                time.sleep(0.04 * (i + 1))
        raise last


class REInvIn(BaseModel):
    session_id: str
    op: str = "get"          # get | give | remove | set | loadout | health | catalog
    item: str = ""           # give / set: item name, id, or a cross-game name ("rocket launcher", "first aid spray")
    amount: int = 0          # give / set: count or ammo (0 = a sensible default); health: HP
    slot: int = -1           # remove / set: slot number as `get` lists it
    character: str = ""      # loadout: Mercenaries character (RE4: leon|ada|hunk|krauser|wesker; RE6: leon|helena|...)
    items: list = []         # loadout: item names or {item|id, amount}


class REInvOut(BaseModel):
    result: dict


@tool("re_inventory", "1.0", REInvIn, REInvOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=120,
      side_effects=["writes the running game's inventory slots / HP (or calls the game's own give routine)"])
def re_inventory(inp: REInvIn, ctx):
    """Inventory of the selected character in any Resident Evil running live (RE4 GameCube, RE6 Xbox 360, classic REs
    with a known slot layout): get, give item (any item; cross-game names like 'rocket launcher' map to each game's own
    id), remove slot, set slot item/amount, Mercenaries loadout, set HP."""
    from .tools import SESSIONS
    ad, game = SESSIONS[inp.session_id]
    gid = game.get("game_id", "")
    op = inp.op.strip().lower()
    if op == "catalog":
        return {"result": support(gid) | {"items": catalog(gid).get("items", []), "cross": cross(gid)}}
    res = {} if op in ("get", "list", "inventory", "status") else apply(ad, game, inp, ctx)
    try:
        inv = read(Retry(ad), gid)
    except Unsupported:
        raise
    except Exception as e:                                       # noqa: BLE001 - the write happened; report the read failure
        inv = {"error": f"{type(e).__name__}: {e}"}
    return {"result": res | {"inventory": inv}}
