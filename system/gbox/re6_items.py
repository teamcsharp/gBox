"""Resident Evil 6 (Xbox 360) item catalogue: every item id with its in-game name and icon.

Names: soft\\message\\mes_item_<lang> (GMD) in Msg_<lang>.arc, read from the operator's disc (the slot index is
the item id: 0-40 weapons, 101-114 ammo, 201-207 herbs, 300-311 skill points, 400-437 key items).
Icons: data\\id\\cockpit\\itemicon_BM_NOMIP (Gadget00.arc), a 1024x1024 10x10 atlas; ICON maps id -> cell.
Cells were matched by eye against the game's own item descriptions (ammo notes name the guns: e.g. ".500 S&W:
M500 only" -> the revolver cell is the Elephant Killer); "verified" marks the ones also checked in game.
Thumbnails are cut from the operator's own disc into gbox-data (never redistributed).
"""
from __future__ import annotations

import io
import json
import struct
from pathlib import Path

GADGET_ARC = "/nativeXenon/arc/X360/Gadget00.arc"
ATLAS = "data\\id\\cockpit\\itemicon_BM_NOMIP"
MSG_ARC = "/nativeXenon/arc/X360/Msg_{lang}.arc"
MSG = "soft\\message\\mes_item_{lang}"

# id -> atlas cell (row * 10 + col)
ICON = {
    0: 25, 1: 12, 2: 13, 3: 46, 4: 41, 5: 42, 6: 43, 7: 40, 8: 22, 9: 37, 10: 45, 11: 44, 12: 33, 13: 34, 14: 35,
    15: 32, 16: 36, 17: 14, 18: 23, 19: 27, 20: 29, 21: 28, 22: 47, 23: 26, 24: 38, 25: 39, 26: 24, 27: 15,
    31: 48, 32: 71, 40: 34,
    101: 0, 102: 1, 103: 2, 104: 3, 105: 4, 106: 5, 107: 6, 108: 7, 109: 8, 110: 9, 111: 19, 112: 16, 113: 17, 114: 18,
    201: 10, 202: 11, 203: 20, 204: 21, 205: 30, 206: 31, 207: 60,
    300: 50, 301: 51, 302: 52, 303: 53, 304: 54, 305: 55, 306: 56, 307: 57, 308: 58, 309: 61, 310: 62, 311: 63,
    # key items: best guesses from the pictures (not yet checked in game)
    400: 82, 401: 96, 402: 97, 403: 96, 404: 97, 405: 77, 406: 75, 407: 84, 408: 84, 409: 84, 410: 78, 411: 79,
    412: 89, 413: 83, 414: 90, 419: 92, 420: 91, 421: 88, 422: 88, 423: 88, 424: 94, 425: 95, 426: 86, 427: 93,
    428: 99, 429: 93, 430: 76, 431: 70, 432: 72, 433: 80, 434: 73, 435: 74, 436: 75, 437: 87,
}
KEY_GUESSED = {i for i in ICON if i >= 400}
# cells seen in the game's own UI next to the item (Mercenaries character select / weapon wheel / HUD), Oct 2026
VERIFIED = {3, 4, 22, 101, 102, 8, 107, 7, 27, 12, 21, 32, 111, 106}

# who carries what in the story (the "exclusive" note the loadout picker shows)
OWNER = {0: "Jake", 3: "Leon", 6: "Helena", 11: "Piers", 13: "Sherry", 23: "Ada", 25: "Chris", 26: "Sherry"}
# vehicle / turret / boss weapons: not carried items (hidden from the picker unless asked for)
SPECIAL = {28, 30, 33, 34, 35, 36, 37, 38, 39}
AMMO_FOR = {101: [1, 2, 3, 12, 13, 14], 102: [4, 5], 103: [9, 10], 104: [15, 16, 17], 105: [11], 106: [7], 107: [8],
            108: [18, 16], 109: [18], 110: [18], 111: [27], 112: [23], 113: [23], 114: [6]}


def kind(i: int) -> str:
    if i < 100:
        return "grenade" if 19 <= i <= 22 else "melee" if i in (0, 24, 25, 26) else "recovery" if i in (29, 32) else "weapon"
    return {1: "ammo", 2: "herb", 3: "skill_points", 4: "key_item"}.get(i // 100, "other")


def parse_gmd(d: bytes) -> dict[int, str]:
    """mes_item GMD: offset table at 0x18 (one u32 per id, 0xFFFFFFFF = none), strings right after it."""
    if d[:4] != b"\0DMG":
        raise ValueError("not an Xbox 360 GMD message file")
    # u32 count at 0x14, then count + 1 u32 offsets at 0x18 (one per id, 0xFFFFFFFF = none, last = end of strings)
    n = struct.unpack_from(">I", d, 0x14)[0]
    tab, base = 0x18, 0x18 + 4 * (n + 1)
    out = {}
    for i in range(n):
        o = struct.unpack_from(">I", d, tab + 4 * i)[0]
        if o == 0xFFFFFFFF or base + o >= len(d):
            continue
        e = d.find(b"\0", base + o)
        s = d[base + o:e if e >= 0 else len(d)].decode("utf-8", "replace").strip()
        if s and "E3ROM" not in s and s != "sample":
            out[i] = s
    return out


def catalog(names: dict[int, str]) -> list[dict]:
    """The item list for the API / loadout picker (ids with a name and a real item)."""
    out = []
    for i, nm in sorted(names.items()):
        if i in (440, 441) or i >= 500:                  # help texts
            continue
        out.append({"id": i, "hex": f"0x{i:03X}", "name": nm, "kind": kind(i), "icon_cell": ICON.get(i),
                    "icon_checked": "game" if i in VERIFIED else "picture" if i not in KEY_GUESSED else "guess",
                    "owner": OWNER.get(i), "special": i in SPECIAL,
                    "ammo_for": AMMO_FOR.get(i, []), "duplicate_of": 13 if i == 40 else None})
    return out


def icon_png(atlas_img, cell: int, size: int = 128) -> bytes:
    from PIL import Image
    c = atlas_img.width / 10
    r, col = divmod(cell, 10)
    im = atlas_img.crop((round(col * c), round(r * c), round((col + 1) * c), round((r + 1) * c)))
    im = im.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def build(iso: Path, out_dir: Path, lang: str = "eng") -> dict:
    """Read names + icon atlas from the disc image, write items.json and icons/<id>.png into out_dir."""
    from . import re6
    disc = re6.XDVD(iso)
    try:
        msg = re6.Arc(disc.read(MSG_ARC.format(lang=lang)))
        names = parse_gmd(msg.get(msg.find(MSG.format(lang=lang), "242bb29a")))
        gad = re6.Arc(disc.read(GADGET_ARC))
        atlas = re6.tex_to_image(gad.get(gad.find(ATLAS, "tex")))
    finally:
        disc.close()
    items = catalog(names)
    icons = Path(out_dir) / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    atlas.save(Path(out_dir) / "itemicon_atlas.png")
    for it in items:
        if it["icon_cell"] is not None:
            (icons / f"{it['id']}.png").write_bytes(icon_png(atlas, it["icon_cell"]))
            it["icon"] = f"/api/re6/icon/{it['id']}"
    (Path(out_dir) / "items.json").write_text(json.dumps(items, indent=0))
    return {"items": len(items), "icons": sum(1 for i in items if i.get("icon")), "dir": str(out_dir)}
