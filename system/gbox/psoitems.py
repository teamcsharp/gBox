"""Phantasy Star Online items: the full catalog read from the game disc (ItemPMT + item name text) and the live
inventory in RAM (30 slots of 28 bytes: present u32, flags u32 (8 = equipped), item data 12 bytes, item id u32, data2 4).

Item codes are the first 3 data bytes: weapon 00 cc ii, frame 01 01 ii, barrier 01 02 ii, unit 01 03 ii, mag 02 ii 00,
tool 03 cc ii (stackable tools keep the count in data byte 5)."""
import struct

from . import psotext
from .ninja import prs_decompress

SLOT, SLOTS = 28, 30
CAT_NAMES = {0: "Weapons", 1: "Armor", 2: "Mags", 3: "Tools"}
CATALOG_SCHEMA = 3
CLASSES = {"HUmar": 0x49, "HUnewearl": 0xA1, "HUcast": 0x51, "RAmar": 0x4A,
           "RAcast": 0x52, "RAcaseal": 0x92, "FOmarl": 0x8C, "FOnewm": 0x64,
           "FOnewearl": 0xA4, "HUcaseal": 0x91, "RAmarl": 0x8A, "FOmar": 0x4C}


def rare_pool(items: list[dict], character_class: str, highest: bool = True) -> list[dict]:
    """Native base-star rarity and class flags, never capitalization. Requirements remain visible in the catalog.

    PSO weapons have grind/stat requirements, not an item level. 'Highest' means the highest star tier available
    for this class, with each weapon at its own PMT maximum grind when spawned.
    """
    if character_class not in CLASSES:
        raise ValueError("select a PSO character class")
    mask = CLASSES[character_class]
    pool = [i for i in items if i.get("cat") == "Weapons" and i.get("stars", 0) >= 9
            and i.get("usability_flags", 0) & mask == mask]
    if not pool:
        raise ValueError("no class-compatible rare weapons in this disc's item database")
    if highest:
        stars = max(i["stars"] for i in pool)
        pool = [i for i in pool if i["stars"] == stars]
    return pool


def catalog(pmt: bytes, text: bytes, endian: str = "<", root_skip: int = 1) -> list[dict]:
    """Item catalog from a decompressed ItemPMT + decoded TextEnglish. root_skip: DC v2's root table starts with one
    extra word (GC's doesn't). The item-name list is located from the first saber's name id."""
    p, t = pmt, text
    rp = lambda o: struct.unpack_from(f"{endian}I", p, o)[0]
    rt = lambda o: struct.unpack_from(f"{endian}I", t, o)[0]
    root = rp(len(p) - 16)                                         # REL footer -> root table
    weapons, armors, units, tools, mags = (rp(root + 4 * (i + root_skip)) for i in range(5))
    saber_str = t.find(b"Saber\0")
    ref = next(o for o in range(0, len(t) - 3, 4) if rt(o) == saber_str)
    names = ref - 4 * rp(rp(weapons + 12))                         # weapon class 1, entry 0 = Saber
    name = lambda i: (lambda o: t[o:t.find(b"\0", o)].decode("latin-1"))(rt(names + 4 * i)) if 0 <= names + 4 * i < len(t) - 3 else "?"
    out = []
    # Binary layouts independently decoded from the owned PMT. Schema references and field offsets:
    # docs/pso-controls.md (newserv ItemParameterTable, pinned revision).
    dc = root_skip == 1
    base_size = 4 if dc else 8
    star_start = rp(root + (0x30 if dc else 0x2C))
    star_base = 0x4E if dc else 0x94
    reloc, reloc_n = rp(len(p) - 32), rp(len(p) - 28)
    if reloc_n > len(p) // 2 or reloc + 2 * reloc_n > len(p):
        raise ValueError("invalid PSO REL relocations")
    roots = [root, reloc, len(p) - 32]
    field = 0
    for i in range(reloc_n):
        field += struct.unpack_from(f"{endian}H", p, reloc + 2 * i)[0] * 4
        if field > len(p) - 4:
            raise ValueError("invalid PSO REL pointer")
        roots.append(rp(field))
    def end_of(start):
        return min(v for v in roots + [root] if start < v <= len(p))
    star_end = end_of(star_start)
    u16 = lambda o: struct.unpack_from(f"{endian}H", p, o)[0]

    def add(code, cat, kind, n, o, st):
        if not 0 <= n <= 256 or not 0 <= o <= len(p) - st * n:
            raise ValueError("invalid PSO item table bounds")
        for k in range(n):
            at = o + st * k
            iid = rp(at)
            if iid == 0xFFFFFFFF:
                continue
            si = star_start + iid - star_base
            stars = p[si] if star_start <= si < star_end else 0
            if cat == "Mags":
                stars = 12 if k >= 0x28 else 0
            elif cat == "Tools":
                stars = 12 if rp(at + base_size + 8) & 0x80 else 0
            row = {"code": bytes(code(k)).hex(), "name": name(iid), "cat": cat, "kind": kind,
                   "stars": stars, "rare": stars >= 9, "schema": CATALOG_SCHEMA}
            if cat == "Weapons":
                row |= {"usability_flags": u16(at + base_size), "atp_min": u16(at + base_size + 2),
                        "atp_max": u16(at + base_size + 4), "atp_required": u16(at + base_size + 6),
                        "mst_required": u16(at + base_size + 8), "ata_required": u16(at + base_size + 10),
                        "max_grind": p[at + (0x10 if dc else 0x16)],
                        "ata": p[at + (0x13 if dc else 0x19)],
                        "special_id": p[at + (0x12 if dc else 0x18)]}
            elif kind in ("Frame", "Barrier"):
                row |= {"usability_flags": u16(at + base_size + 6), "level_required": p[at + base_size + 8] + 1}
            elif kind == "Mag":
                row["usability_flags"] = u16(at + base_size + 12)
            if "usability_flags" in row:
                row["classes"] = [c for c, mask in CLASSES.items() if row["usability_flags"] & mask == mask
                                  and (not dc or c in list(CLASSES)[:9])]
            out.append(row)

    for c in range(1, min(256, (end_of(weapons) - weapons) // 8)):    # all weapon classes, including late rares
        n, o = rp(weapons + 8 * c), rp(weapons + 8 * c + 4)
        if not n:
            continue
        add(lambda k, c=c: (0, c, k), "Weapons", f"class {c:02X}", n, o, 0x18 if dc else 0x28)
    for sub, kind in ((1, "Frame"), (2, "Barrier")):
        add(lambda k, s=sub: (1, s, k), "Armor", kind, rp(armors + 8 * (sub - 1)) + dc,
            rp(armors + 8 * (sub - 1) + 4), 0x18 if dc else 0x1C)
    add(lambda k: (1, 3, k), "Armor", "Unit", rp(units) + dc, rp(units + 4), 0x0C if dc else 0x10)
    add(lambda k: (2, k, 0), "Mags", "Mag", rp(mags) + dc, rp(mags + 4), 0x14 if dc else 0x18)
    for c in range(0, min(256, (end_of(tools) - tools) // 8)):
        n, o = rp(tools + 8 * c), rp(tools + 8 * c + 4)
        if not n or n > 300 or o >= len(p) or o == rp(weapons + 4):   # the tool table runs into the weapon table
            break
        if c == 2:                                                  # technique disks: 03 02 level tech
            continue
        add(lambda k, c=c: (3, c, k), "Tools", f"class {c:02X}", n, o, 0x10 if dc else 0x14)
    from .pso_loadouts import enrich
    return [enrich(i, 'dcv2' if dc else 'gc') for i in out if i["name"] not in ("", "?", "????")]


def catalog_dc_v2(read) -> list[dict]:
    """read(path) -> bytes from the PSO Ver. 2 (Dreamcast) disc."""
    return catalog(prs_decompress(read("PSO/ITEMPMT.PRS")), psotext.pr2_decode(read("PSO/TEXTENGLISH.PR2")), "<", 1)


def catalog_gc(read) -> list[dict]:
    """read(path) -> bytes from the PSO Episode I & II (GameCube) disc (big-endian)."""
    return catalog(prs_decompress(read("ItemPMT.prs")), psotext.pr2_decode(read("TextEnglish.pr2"), ">"), ">", 0)


def _slot_ok(b: bytes, endian: str) -> int:
    """1 = a real item, 0 = an empty slot, -1 = not an inventory slot."""
    present, flags = struct.unpack_from(f"{endian}II", b, 0)
    iid = struct.unpack_from(f"{endian}I", b, 20)[0]
    if present == 0 and flags == 0:
        return 0
    if present != 1 or flags not in (0, 8) or b[8] > 3 or not (0x10000 <= iid < 0x1000000):
        return -1
    if b[8] == 0 and b[9] == 0:                                    # weapon class 0 doesn't exist
        return -1
    return 1


def find_inventory(mem: bytes, base: int, endian: str = "<") -> int | None:
    """Address of the live inventory's slot 0. Candidates = an equipped weapon slot; each is scored by walking back to
    the first slot and counting consecutive slots that look like real items (sane flags, item type 0-3, real item id)."""
    one, eight = (struct.pack(f"{endian}I", v) for v in (1, 8))
    pat = one + eight + b"\x00"
    best, best_n = None, 2
    i = mem.find(pat)
    while i >= 0:
        if i % 4 == 0 and i + SLOT <= len(mem) and _slot_ok(mem[i:i + SLOT], endian) == 1:
            s = i
            while s - SLOT >= 0 and _slot_ok(mem[s - SLOT:s], endian) == 1 and i - s < SLOT * 29:
                s -= SLOT
            n, k = 0, s
            while k + SLOT <= len(mem) and (k - s) < SLOT * SLOTS and (v := _slot_ok(mem[k:k + SLOT], endian)) >= 0:
                n += v
                if v == 0:
                    break                                          # items are packed: the first empty slot ends the list
                k += SLOT
            if n > best_n:
                best, best_n = base + s, n
        i = mem.find(pat, i + 1)
    return best


def decode_slot(b: bytes, endian: str = "<") -> dict:
    present, flags = struct.unpack_from(f"{endian}II", b, 0)
    return {"present": bool(present), "equipped": bool(flags & 8), "code": b[8:11].hex(), "data": b[8:20].hex(),
            "id": struct.unpack_from(f"{endian}I", b, 20)[0], "count": b[13] if b[8] == 3 else None}


def _selftest():
    slot = struct.pack("<II", 1, 8) + bytes.fromhex("000100000000000000000000") + struct.pack("<I", 0x10000) + b"\0" * 4
    frame = struct.pack("<II", 1, 8) + bytes.fromhex("010100000000000000000000") + struct.pack("<I", 0x10001) + b"\0" * 4
    mate = struct.pack("<II", 1, 0) + bytes.fromhex("030000000005000000000000") + struct.pack("<I", 0x10002) + b"\0" * 4
    mem = b"\x03\x00\x00\x00" + slot + frame + mate + b"\0" * SLOT * 27
    assert find_inventory(mem, 0x8C000000) == 0x8C000004, hex(find_inventory(mem, 0x8C000000) or 0)
    d = decode_slot(slot)
    assert d["equipped"] and d["code"] == "000100" and d["id"] == 0x10000
    print("psoitems ok")


if __name__ == "__main__":
    _selftest()
