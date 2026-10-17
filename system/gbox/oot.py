"""Zelda: Ocarina of Time (N64 NTSC 1.0 / 1.1 / 1.2) live edits: story skips, items, equipment, warps.

Offsets and constants are from the zeldaret/oot decompilation (include/save.h, item.h, tables/entrance_table.h);
the v1.2 SaveContext / Play-state addresses were verified live (the save's "ZELDAZ" marker, play->nextEntranceIndex ==
save.entranceIndex). The 1.0 and 1.1 bases come from the decomp's per-version symbol maps and are confirmed at run
time by the same two checks (layout()). The SaveContext / PlayState layouts are shared by the three N64 NTSC revisions,
so every offset below is relative to the running ROM's bases: functions take them from bases(ad), and tables written
against the v1.2 constants (gbox/zelda_n64.py) go through remap(ad). ParaLLEl N64 exposes RDRAM as little-endian
32-bit words, so every access swaps per word.
"""
import struct

SAVE = 0x8011AC80                      # gSaveContext (v1.2): the canonical base the offset tables are written against
PLAY = 0x801C8D60                      # gPlayState (v1.2)
LAYOUTS = {"ntsc-1.0": (0x8011A5D0, 0x801C84A0),         # (gSaveContext, gPlayState) per N64 NTSC revision
           "ntsc-1.1": (0x8011A790, 0x801C8660),
           "ntsc-1.2": (SAVE, PLAY)}
SAVE_SIZE = 0x1450                     # sizeof(SaveContext): the window remap() moves
P_NEXT_ENTRANCE, P_TRANSITION, P_AGE_ON_LOAD = 0x11E1A, 0x11E15, 0x11DE8   # play->linkAgeOnLoad wins over save.linkAge
S_ENTRANCE, S_BUTTONS, S_CSLOTS, S_EQUIPS = 0x00, 0x68, 0x6C, 0x70
S_ITEMS, S_AMMO, S_INV_EQUIP, S_UPGRADES, S_QUEST = 0x74, 0x8C, 0x9C, 0xA0, 0xA4
S_EVENTCHKINF, S_NEXT_CUTSCENE = 0xED4, 0x1412
TRANS_START = 0x14

# items: name -> (item id, inventory slot). Bottles/trade items left out on purpose.
ITEMS = {"deku stick": (0x00, 0), "deku nut": (0x01, 1), "bombs": (0x02, 2), "bow": (0x03, 3), "fire arrow": (0x04, 4),
         "dins fire": (0x05, 5), "slingshot": (0x06, 6), "fairy ocarina": (0x07, 7), "ocarina of time": (0x08, 7),
         "bombchu": (0x09, 8), "hookshot": (0x0A, 9), "longshot": (0x0B, 9), "ice arrow": (0x0C, 10), "farores wind": (0x0D, 11),
         "boomerang": (0x0E, 12), "lens of truth": (0x0F, 13), "magic beans": (0x10, 14), "megaton hammer": (0x11, 15),
         "light arrow": (0x12, 16), "nayrus love": (0x13, 17)}
AMMO = {"deku stick": 10, "deku nut": 20, "bombs": 20, "bow": 30, "slingshot": 30, "bombchu": 20, "magic beans": 10}
QUEST = {"forest medallion": 0, "fire medallion": 1, "water medallion": 2, "spirit medallion": 3, "shadow medallion": 4,
         "light medallion": 5, "kokiri emerald": 18, "goron ruby": 19, "zora sapphire": 20}
ENTRANCES = {"kokiri forest": 0x0EE, "links house": 0x0BB, "deku tree": 0x000, "hyrule field": 0x0CD, "hyrule castle": 0x138,
             "kakariko": 0x0DB, "death mountain trail": 0x13D, "zoras river": 0x0EA, "lake hylia": 0x102, "temple of time": 0x053}


# named places: (entrance, kit). Entrances from zeldaret/oot include/tables/entrance_table.h
DESTINATIONS = {
    "kokiri forest": (0x211, None), "links house": (0x0BB, None), "hyrule field": (0x0CD, None), "kakariko": (0x0DB, None),
    "lon lon ranch": (0x157, None), "goron city": (0x14D, None), "zoras domain": (0x108, None), "gerudo valley": (0x117, None),
    "lake hylia": (0x102, None), "temple of time": (0x053, None), "hyrule castle": (0x138, None),
    "deku tree": (0x000, "child"), "dodongos cavern": (0x004, "child"), "jabu jabu": (0x028, "child"),
    "forest temple": (0x169, "adult"), "fire temple": (0x165, "adult"), "water temple": (0x010, "adult"),
    "shadow temple": (0x037, "adult"), "spirit temple": (0x082, "adult"),
    "gohma": (0x40F, "child"), "king dodongo": (0x40B, "child"), "barinade": (0x301, "child"),
    "phantom ganon": (0x00C, "adult"), "volvagia": (0x305, "adult"), "morpha": (0x417, "adult"),
    "bongo bongo": (0x413, "adult"), "twinrova": (0x08D, "adult"),
    "ganons castle": (0x467, "endgame"), "ganons tower": (0x41B, "endgame"),
    "ganondorf": (0x41F, "endgame"), "final battle": (0x41F, "endgame"),   # 0x517 (Ganon arena) hangs: only reachable from the collapse
}
ALIASES = {"end of the shadow temple": "bongo bongo", "shadow temple boss": "bongo bongo", "end of the forest temple": "phantom ganon",
           "end of the fire temple": "volvagia", "end of the water temple": "morpha", "end of the spirit temple": "twinrova",
           "end of the deku tree": "gohma", "final boss": "final battle", "last battle": "final battle"}


def _rd(ad, a, n):
    a0 = a & ~3
    n0 = ((a + n + 3) & ~3) - a0
    raw = ad.read_memory(a0, n0)
    be = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    return be[a - a0:a - a0 + n]


def _wr(ad, a, data: bytes):
    a0 = a & ~3
    n0 = ((a + len(data) + 3) & ~3) - a0
    be = bytearray(_rd(ad, a0, n0))
    be[a - a0:a - a0 + len(data)] = data
    ad.write_memory(a0, b"".join(bytes(be[i:i + 4][::-1]) for i in range(0, n0, 4)))


def layout(ad) -> dict:
    """{"version", "save", "play", "play_checked"} for the ROM this session runs. The save's "ZELDAZ" marker at the
    revision's gSaveContext picks the revision; play->nextEntranceIndex == save.entranceIndex confirms gPlayState (it can
    legitimately differ for a frame during a scene change, so a marker match alone is still accepted). Cached on the
    adapter and re-validated with one read, so a different ROM in the same session is picked up."""
    hit = getattr(ad, "_oot_layout", None)
    if hit and _rd(ad, hit["save"] + 0x1C, 6) == b"ZELDAZ":
        return hit
    found = []
    for ver, (save, play) in LAYOUTS.items():
        if _rd(ad, save + 0x1C, 6) != b"ZELDAZ":
            continue
        ent = struct.unpack(">I", _rd(ad, save + S_ENTRANCE, 4))[0] & 0xFFFF
        nxt = struct.unpack(">H", _rd(ad, play + P_NEXT_ENTRANCE, 2))[0]
        found.append({"version": ver, "save": save, "play": play, "play_checked": ent == nxt})
    if not found:
        raise RuntimeError("no OoT save loaded (title screen? other ROM revision?) - load a file first; known N64 "
                           "revisions: " + ", ".join(LAYOUTS))
    hit = next((f for f in found if f["play_checked"]), found[0])
    try:
        ad._oot_layout = hit
    except Exception:
        pass
    return hit


def bases(ad) -> tuple[int, int]:
    """(gSaveContext, gPlayState) of the running ROM."""
    l = layout(ad)
    return l["save"], l["play"]


def save(ad) -> int:
    return layout(ad)["save"]


def play(ad) -> int:
    return layout(ad)["play"]


def remap(ad):
    """Address translator for tables written against the v1.2 SaveContext (gbox/zelda_n64.py): addresses inside that
    window move to this ROM's gSaveContext; code addresses and pointers read from memory are left alone."""
    delta = save(ad) - SAVE
    return lambda a: a + delta if SAVE <= a < SAVE + SAVE_SIZE else a


def check(ad) -> dict:
    """Raise unless an OoT save is loaded; returns the detected layout."""
    return layout(ad)


def state(ad) -> dict:
    SAVE, PLAY = bases(ad)
    s = _rd(ad, SAVE, 0xF00)
    u16 = lambda o: struct.unpack_from(">H", s, o)[0]
    u32 = lambda o: struct.unpack_from(">I", s, o)[0]
    items = {n: True for n, (iid, slot) in ITEMS.items() if s[S_ITEMS + slot] == iid}
    return {"entrance": hex(u32(S_ENTRANCE)), "child": u32(4) == 1, "health": u16(0x30), "max": u16(0x2E), "rupees": u16(0x34),
            "items": sorted(items), "quest": [n for n, b in QUEST.items() if u32(S_QUEST) >> b & 1],
            "c_buttons": s[S_BUTTONS + 1:S_BUTTONS + 4].hex(), "deku_tree_done": bool(u16(S_EVENTCHKINF) >> 7 & 1)}


def give(ad, name: str, c_button: int | None = None) -> dict:
    """Put an item in its inventory slot (with ammo) and optionally on C-left/down/right (1-3)."""
    SAVE, PLAY = bases(ad)
    key = name.lower().replace("'", "").strip()
    if key not in ITEMS:
        raise ValueError(f"unknown item {name!r}; known: {sorted(ITEMS)}")
    iid, slot = ITEMS[key]
    _wr(ad, SAVE + S_ITEMS + slot, bytes([iid]))
    if key in AMMO:
        _wr(ad, SAVE + S_AMMO + slot, bytes([AMMO[key]]))
    if c_button:
        _wr(ad, SAVE + S_BUTTONS + c_button, bytes([iid]))
        _wr(ad, SAVE + S_CSLOTS + c_button - 1, bytes([slot]))
    got = _rd(ad, SAVE + S_ITEMS + slot, 1)[0]
    return {"item": key, "slot": slot, "on_c": c_button, "verified": got == iid}


def warp(ad, entrance: int, cutscene: int | None = None) -> dict:
    SAVE, PLAY = bases(ad)
    if cutscene is not None:
        _wr(ad, SAVE + S_NEXT_CUTSCENE, struct.pack(">H", cutscene))
    _wr(ad, PLAY + P_NEXT_ENTRANCE, struct.pack(">H", entrance))
    _wr(ad, PLAY + P_TRANSITION, bytes([TRANS_START]))
    return {"warp": hex(entrance)}


def in_gameplay(ad) -> bool:
    """Link exists and isn't in a cutscene / talking (player->stateFlags1 IN_CUTSCENE 0x20000000, TALKING 0x40)."""
    SAVE, PLAY = bases(ad)
    pl = struct.unpack(">I", _rd(ad, PLAY + 0x1C44, 4))[0]
    return bool(pl) and not struct.unpack(">I", _rd(ad, pl + 0x66C, 4))[0] & 0x20000040


def wait_gameplay(ad, timeout: float = 60.0) -> bool:
    import time
    end = time.time() + timeout
    while time.time() < end:
        if in_gameplay(ad):
            return True
        time.sleep(1)
    return False


def alive(ad, wait: float = 8.0) -> bool:
    """Did the warp land? play->gameplayFrames keeps ticking unless the game hung."""
    import time
    SAVE, PLAY = bases(ad)
    time.sleep(wait)
    a = _rd(ad, PLAY + 0x11DE4, 4)
    time.sleep(1)
    return _rd(ad, PLAY + 0x11DE4, 4) != a


def kit(ad, which: str) -> dict:
    """Make Link able to survive where he's going: child basics, adult gear, or the full endgame loadout."""
    SAVE, PLAY = bases(ad)
    u16 = lambda o: struct.unpack(">H", _rd(ad, SAVE + o, 2))[0]
    hearts = {"child": 6, "adult": 12, "endgame": 20}[which]
    if u16(0x2E) < hearts * 16:
        _wr(ad, SAVE + 0x2E, struct.pack(">H", hearts * 16))
    _wr(ad, SAVE + 0x30, struct.pack(">H", max(u16(0x2E), hearts * 16)))                # full health
    if which == "child":
        inv, eq = 0x1111, 0x1111                                                        # Kokiri Sword, Deku Shield, tunic, boots
        give(ad, "slingshot"); give(ad, "deku nut"); give(ad, "deku stick")
    else:
        inv, eq = 0x0022 | 0x0100 | 0x1000, 0x1122                                      # Master Sword, Hylian Shield, Kokiri tunic, boots
        for it in ("hookshot", "bow", "bombs", "ocarina of time"):
            give(ad, it)
        q = struct.unpack(">I", _rd(ad, SAVE + S_QUEST, 4))[0] | (0xFFF << 6)          # all songs: Sheik's teach cutscenes don't hijack the warp
        _wr(ad, SAVE + S_QUEST, struct.pack(">I", q))
        if which == "endgame":
            inv |= 0x0004 | 0x0040 | 0x0700 | 0x7000                                    # Biggoron, Mirror Shield, all tunics/boots
            for it in ("longshot", "light arrow", "fire arrow", "ice arrow", "megaton hammer", "lens of truth", "dins fire", "nayrus love"):
                give(ad, it)
            q = struct.unpack(">I", _rd(ad, SAVE + S_QUEST, 4))[0] | 0x3F | (7 << 18)     # all medallions + stones
            _wr(ad, SAVE + S_QUEST, struct.pack(">I", q))
    _wr(ad, SAVE + S_INV_EQUIP, struct.pack(">H", u16(S_INV_EQUIP) | inv))
    _wr(ad, SAVE + S_EQUIPS, struct.pack(">H", eq))
    age = 1 if which == "child" else 0                                                # linkAge: 0 adult, 1 child
    _wr(ad, SAVE + 0x04, struct.pack(">I", age))
    _wr(ad, PLAY + P_AGE_ON_LOAD, bytes([age]))                                        # applied on the warp's scene load
    return {"kit": which, "hearts": hearts}


def full_inventory(ad) -> dict:
    """Every item (max ammo + bag/quiver upgrades), every sword/shield/tunic/boots, 4 bottles, 20 hearts, 500 rupees.
    Link keeps his age; what's equipped is left alone."""
    SAVE, PLAY = bases(ad)
    for name in ITEMS:
        if name not in ("fairy ocarina", "hookshot"):                                # upgraded versions share the slot
            give(ad, name)
    for slot in range(18, 22):
        _wr(ad, SAVE + S_ITEMS + slot, bytes([0x14]))                                # empty bottles
    for slot, n in {0: 30, 1: 40, 2: 40, 3: 50, 6: 50, 8: 50, 14: 10}.items():       # sticks nuts bombs arrows seeds chus beans
        _wr(ad, SAVE + S_AMMO + slot, bytes([n]))
    upg = 3 | 3 << 3 | 3 << 6 | 2 << 9 | 2 << 12 | 3 << 14 | 3 << 17 | 3 << 20         # quiver bombs strength scale wallet seeds sticks nuts
    _wr(ad, SAVE + S_UPGRADES, struct.pack(">I", upg))
    _wr(ad, SAVE + S_INV_EQUIP, struct.pack(">H", 0x7777))                            # all swords/shields/tunics/boots (no broken knife)
    _wr(ad, SAVE + 0x2E, struct.pack(">H", 20 * 16))
    _wr(ad, SAVE + 0x30, struct.pack(">H", 20 * 16))
    _wr(ad, SAVE + 0x34, struct.pack(">H", 500))
    st = state(ad)
    return {"full_inventory": True, "items": len(st["items"]), "verified": len(st["items"]) >= len(ITEMS) - 2 and st["max"] == 320}


def goto(ad, place: str) -> dict:
    """Warp to a named place (dungeon, boss room, town, final battle) with the gear that place needs."""
    norm = lambda t: " ".join(w for w in t.lower().replace("'", "").split() if w != "the")
    key = norm(place)
    key = {norm(k): v for k, v in ALIASES.items()}.get(key, key)
    if key not in DESTINATIONS:
        hits = [k for k in DESTINATIONS if all(w in k for w in key.split())]
        if len(hits) != 1:
            raise ValueError(f"where is {place!r}? known: {sorted(DESTINATIONS)}")
        key = hits[0]
    ent, need = DESTINATIONS[key]
    out = {"place": key}
    if need:
        out.update(kit(ad, need))
    out.update(warp(ad, ent, 0xFFEF))                                                  # no entry cutscene
    return out


def skip_deku_tree(ad, cutscene: bool = False) -> dict:
    """What beating Gohma does (z_door_warp1.c): EVENTCHKINF 07 + 09, Kokiri Emerald, warp to Kokiri Forest with the
    farewell cutscene. Also: Mido / Deku Tree access flags (02, 03, 04), Kokiri Sword + Deku Shield owned and equipped."""
    SAVE, PLAY = bases(ad)
    ev = struct.unpack(">H", _rd(ad, SAVE + S_EVENTCHKINF, 2))[0]
    ev |= (1 << 2) | (1 << 3) | (1 << 4) | (1 << 7) | (1 << 9)
    _wr(ad, SAVE + S_EVENTCHKINF, struct.pack(">H", ev))
    q = struct.unpack(">I", _rd(ad, SAVE + S_QUEST, 4))[0] | (1 << QUEST["kokiri emerald"])
    _wr(ad, SAVE + S_QUEST, struct.pack(">I", q))
    inv = struct.unpack(">H", _rd(ad, SAVE + S_INV_EQUIP, 2))[0] | 0x1111           # Kokiri Sword, Deku Shield, tunic, boots owned
    _wr(ad, SAVE + S_INV_EQUIP, struct.pack(">H", inv))
    eq = struct.unpack(">H", _rd(ad, SAVE + S_EQUIPS, 2))[0]
    eq = eq if (eq & 0xFF) and (eq & 0xF00) else 0x1111                             # equip them if anything is missing
    _wr(ad, SAVE + S_EQUIPS, struct.pack(">H", eq))
    give(ad, "slingshot")                                                            # the Deku Tree's dungeon item
    out = warp(ad, 0x0EE, 0xFFF1) if cutscene else warp(ad, 0x211, 0xFFEF)            # farewell cutscene, or the forest (0x457 hangs v1.2)
    st = state(ad)
    return {"done": "Deku Tree cleared", **out, "verified": st["deku_tree_done"] and "kokiri emerald" in st["quest"], "state": st}


def _selftest():
    class Fake:
        def __init__(self):
            self.m = bytearray(0x200000)

        def read_memory(self, a, n):
            o = a - 0x80000000
            return bytes(self.m[o:o + n])

        def write_memory(self, a, d):
            o = a - 0x80000000
            self.m[o:o + len(d)] = d
    f = Fake()
    _wr(f, SAVE + 0x1C, b"ZELDAZ")
    check(f)
    assert f.m[SAVE - 0x80000000 + 0x1F] == ord("Z")                               # word-swapped storage
    assert give(f, "Hookshot", 1)["verified"]
    r = skip_deku_tree(f)
    assert r["verified"] and r["warp"] == "0x211" and r["state"]["c_buttons"].startswith("0a"), r
    assert "hookshot" in r["state"]["items"]
    g = goto(f, "end of the Shadow Temple")
    assert g["place"] == "bongo bongo" and g["warp"] == "0x413" and g["kit"] == "adult", g
    assert goto(f, "final battle")["warp"] == "0x41f"
    assert full_inventory(f)["verified"]
    print("oot ok")


if __name__ == "__main__":
    _selftest()
