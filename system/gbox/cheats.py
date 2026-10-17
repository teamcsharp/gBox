"""Cheat codes for every title: find, install, enable/disable live.

Sources
* libretro-database `cht/` (27,9xx files, 51 systems): GameShark / Action Replay / Game Genie / CodeBreaker codes in
  RetroArch .cht format, either as core codes (`cheatN_code`, decoded by the emulator core) or as RetroArch-native
  memory entries (address/value/size, applied by RetroArch's cheat engine).
* GameCube / Wii: Gecko + Action Replay code lists from the server Dolphin's own "Download Codes" uses, plus raw codes
  pasted by the operator / found by the agent.

Delivery
* RetroArch sessions: the game's .cht goes to `<cheat_database_path>/<core library name>/<content>.cht` before launch
  (RetroArch loads and applies it on content load); live toggles use the CHEAT_INDEX_PLUS/MINUS + CHEAT_TOGGLE network
  commands (RetroArch re-applies after each toggle).
* Any session with memory writes (Dolphin GDB, RetroArch): gBox applies decoded constant-write codes itself
  (Gecko 00/02/04, AR raw writes, plain address=value) and keeps them frozen until disabled.
"""
import ctypes
import difflib
import json
import re
import struct
from pathlib import Path

import httpx

# gBox platform -> libretro-database cht folder
DB_FOLDER = {
    "nes": "Nintendo - Nintendo Entertainment System", "fds": "Nintendo - Family Computer Disk System",
    "snes": "Nintendo - Super Nintendo Entertainment System", "satellaview": "Nintendo - Satellaview",
    "n64": "Nintendo - Nintendo 64", "gb": "Nintendo - Game Boy", "gbc": "Nintendo - Game Boy Color",
    "gba": "Nintendo - Game Boy Advance", "nds": "Nintendo - Nintendo DS", "virtualboy": "Nintendo - Virtual Boy",
    "genesis": "Sega - Mega Drive - Genesis", "megadrive": "Sega - Mega Drive - Genesis", "sms": "Sega - Master System - Mark III",
    "gamegear": "Sega - Game Gear", "segacd": "Sega - Mega-CD - Sega CD", "sega32x": "Sega - 32X", "saturn": "Sega - Saturn",
    "dreamcast": "Sega - Dreamcast", "sg1000": "Sega - SG-1000", "psx": "Sony - PlayStation", "psp": "Sony - PlayStation Portable",
    "pce": "NEC - PC Engine - TurboGrafx 16", "pcecd": "NEC - PC Engine CD - TurboGrafx-CD", "supergrafx": "NEC - PC Engine SuperGrafx",
    "pcfx": "NEC - PC-FX", "atari2600": "Atari - 2600", "atari5200": "Atari - 5200", "atari7800": "Atari - 7800",
    "atari8": "Atari - 8-bit Family", "jaguar": "Atari - Jaguar", "lynx": "Atari - Lynx", "wonderswan": "Bandai - WonderSwan",
    "wonderswancolor": "Bandai - WonderSwan Color", "coleco": "Coleco - ColecoVision", "intellivision": "Mattel - Intellivision",
    "msx": "Microsoft - MSX", "msx2": "Microsoft - MSX2", "ngp": "SNK - Neo Geo Pocket", "ngpc": "SNK - Neo Geo Pocket Color",
    "arcade_fbneo": "FBNeo - Arcade Games", "dos": "DOS", "zxspectrum": "Sinclair - ZX Spectrum +3",
}
GECKO_URL = "https://codes.rc24.xyz/txt.php?txt={gid}"        # what Dolphin's "Download Codes" fetches


def _norm(t: str) -> str:
    t = re.sub(r"\s*[\(\[].*?[\)\]]", "", t.lower())
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def find(db_root: Path, platform: str, title: str, limit: int = 5) -> list[Path]:
    """Best-matching .cht files for a title (region tags ignored; 'v2'/'2' kept)."""
    folder = db_root / DB_FOLDER.get(platform, "")
    if not platform in DB_FOLDER or not folder.is_dir():
        return []
    files = list(folder.glob("*.cht"))
    want, region = _norm(title), title.lower()
    foreign = ("japan", "europe", "german", "french", "spanish", "ital", "korea")

    def score(f):
        s = difflib.SequenceMatcher(None, want, _norm(f.stem)).ratio()
        stem = f.stem.lower()
        if any(w in stem for w in foreign) and not any(w in region for w in foreign):
            s -= 0.25                                       # a USA/World title should not pick a regional code list
        return s
    scored = sorted(files, key=lambda f: -score(f))
    return [f for f in scored[:limit] if score(f) > 0.6]


def parse_cht(text: str) -> list[dict]:
    """RetroArch .cht -> [{index, desc, enable, code?, address?, value?, ...all raw keys}]."""
    kv = dict(re.findall(r'^\s*(\w+)\s*=\s*"?(.*?)"?\s*$', text, re.M))
    n = int(kv.get("cheats", 0)) or 1 + max([int(m) for m in re.findall(r"cheat(\d+)_", text)] or [-1])
    out = []
    for i in range(n):
        e = {k[len(f"cheat{i}_"):]: v for k, v in kv.items() if k.startswith(f"cheat{i}_")}
        if not e:
            continue
        e["index"] = i
        e["enable"] = str(e.get("enable", "false")).lower() == "true"
        out.append(e)
    return out


def write_cht(entries: list[dict]) -> str:
    lines = [f"cheats = {len(entries)}", ""]
    for i, e in enumerate(entries):
        for k, v in e.items():
            if k == "index":
                continue
            if k == "enable":
                v = "true" if v else "false"
            lines.append(f'cheat{i}_{k} = "{v}"')
        lines.append("")
    return "\n".join(lines)


def core_library_name(core_path: str) -> str | None:
    """RetroArch keys cheat folders by the core's library_name (retro_get_system_info)."""
    class Info(ctypes.Structure):
        _fields_ = [("library_name", ctypes.c_char_p), ("library_version", ctypes.c_char_p),
                    ("valid_extensions", ctypes.c_char_p), ("need_fullpath", ctypes.c_bool), ("block_extract", ctypes.c_bool)]
    try:
        lib = ctypes.CDLL(core_path)
        info = Info()
        lib.retro_get_system_info(ctypes.byref(info))
        return info.library_name.decode()
    except Exception:
        return None


# ------------------------------------------------------------- GameCube / Wii: Gecko + Action Replay
def gecko_codes(game_id: str, cache: Path) -> list[dict]:
    """Code list for a disc id (e.g. GPOE8P): [{desc, lines:[...], kind}] parsed from Dolphin's txt format."""
    f = cache / f"{game_id}.txt"
    if not f.exists():
        r = httpx.get(GECKO_URL.format(gid=game_id), timeout=30, follow_redirects=True)
        if r.status_code == 404:                            # no codes on file for this disc
            return []
        r.raise_for_status()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(r.text, encoding="utf-8")
    return parse_gecko_txt(f.read_text(encoding="utf-8", errors="replace"))


def parse_gecko_txt(text: str) -> list[dict]:
    codes, cur = [], None
    for ln in text.splitlines()[2:]:                      # header: game id, game name
        s = ln.strip()
        if not s:
            cur = None
            continue
        if re.fullmatch(r"[0-9A-Fa-f]{8} [0-9A-Fa-f]{8}", s):
            if cur is not None:
                cur["lines"].append(s.upper())
        elif cur is None or cur["lines"]:
            cur = {"desc": s, "lines": [], "kind": "gecko"}
            codes.append(cur)
        else:
            cur["note"] = (cur.get("note", "") + " " + s).strip()
    return [c for c in codes if c["lines"]]


def decode_writes(lines: list[str], kind: str = "gecko") -> tuple[list[tuple[int, bytes]], list[str]]:
    """Constant-write subset that gBox can apply/freeze itself: Gecko 00/02/04 (and AR raw 00/02/04 equivalents),
    'ADDRESS VALUE' pairs. Returns (writes, unsupported lines) -- unsupported codes need the emulator's own engine."""
    writes, bad = [], []
    for ln in lines:
        a, v = (int(x, 16) for x in ln.split())
        t, base = (a >> 24) & 0xFE, 0x80000000 | (a & 0x01FFFFFF)
        if t == 0x00:                                       # 8-bit write, repeated (v >> 16) + 1 times
            n = ((v >> 16) & 0xFFFF) + 1
            writes += [(base + i, bytes([v & 0xFF])) for i in range(n)]
        elif t == 0x02:                                     # 16-bit write, repeated
            n = ((v >> 16) & 0xFFFF) + 1
            writes += [(base + 2 * i, struct.pack(">H", v & 0xFFFF)) for i in range(n)]
        elif t == 0x04:                                     # 32-bit write
            writes.append((base, struct.pack(">I", v)))
        else:
            bad.append(ln)
    return writes, bad


def decode(platform: str, code: str) -> tuple[list[tuple], list[str]]:
    """A database/user code -> gBox ops [(kind, addr, bytes)] with kind 'w' (write) or 'if' (the next op runs only if
    memory at addr equals bytes). Returns (ops, unsupported parts). Multi-line codes use ';' or '+' or newlines."""
    parts = [p.strip() for p in re.split(r"[;+\n]", code) if p.strip()]
    ops, bad = [], []
    for p in parts:
        m = re.fullmatch(r"([0-9A-Fa-f]{8})[ :]?([0-9A-Fa-f]{4,8})", p.replace("-", ""))
        if not m:
            bad.append(p)
            continue
        a, v = int(m[1], 16), int(m[2], 16)
        t = a >> 24
        if platform in ("n64", "n64dd"):                     # GameShark / Action Replay N64
            addr = 0x80000000 | (a & 0x00FFFFFF)             # libretro N64 cores hold RDRAM as host-endian 32-bit words:
            b8, b16 = addr ^ 3, addr ^ 2                      # byte a lives at a^3, halfword a at a^2 (byte-reversed)
            if t in (0x80, 0xA0):
                ops.append(("w", b8, bytes([v & 0xFF])))
            elif t in (0x81, 0xA1):
                ops.append(("w", b16, struct.pack("<H", v & 0xFFFF)))
            elif t == 0xD0:
                ops.append(("if", b8, bytes([v & 0xFF])))
            elif t == 0xD1:
                ops.append(("if", b16, struct.pack("<H", v & 0xFFFF)))
            else:
                bad.append(p)
        elif platform == "psx":                              # GameShark PS1
            addr = 0x80000000 | (a & 0x001FFFFF)
            if t == 0x30:
                ops.append(("w", addr, bytes([v & 0xFF])))
            elif t == 0x80:
                ops.append(("w", addr, struct.pack("<H", v & 0xFFFF)))
            elif t == 0xD0:
                ops.append(("if", addr, struct.pack("<H", v & 0xFFFF)))
            elif t == 0xE0:
                ops.append(("if", addr, bytes([v & 0xFF])))
            else:
                bad.append(p)
        elif platform in ("dreamcast", "naomi"):             # CodeBreaker / Xploder raw (decrypted): 0=8, 1=16, 2=32-bit
            addr = 0x8C000000 | (a & 0x00FFFFFF)
            # published lists put the type in the second nibble ("0TAAAAAA": SA2 USA "Max Score" 020DB294 05F5E0FF is a
            # 32-bit write, "Unlimited Lives" 010DB26C 00000004 a 16-bit one); a code with a non-zero first nibble keeps it there
            kind = t & 0xF if t < 0x10 else (a >> 28) & 0xF
            if kind in (0, 1, 2):
                ops.append(("w", addr, v.to_bytes(4, "little")[:(1, 2, 4)[kind]]))
            else:
                bad.append(p)
        elif platform in ("gamecube", "wii"):
            w, b = decode_writes([f"{m[1]} {m[2].rjust(8, '0')}"])
            ops += [("w", aa, dd) for aa, dd in w]
            bad += b
        else:                                                # plain ADDRESS VALUE (value width = its digits)
            ops.append(("w", a, v.to_bytes(len(m[2]) // 2, "big")))
    return ops, bad


def match_query(query: str, desc: str, code: str) -> int:
    """Rank meaningful whole-word overlap, retaining the database's stable indexes."""
    def tokens(text):
        return {t[:-1] if t == "characters" else t for t in re.findall(r"[a-z0-9]+", text.lower())}
    wanted = tokens(query or "") - {"all", "every", "the", "a", "an", "please", "and", "for"}
    if not wanted:
        return 1
    return len(wanted & tokens(f"{desc} {code}"))


def _native_uint(entry, key, default=None):
    """Strict unsigned .cht integer (RetroArch uses strtoul with base zero)."""
    value = entry.get(key, default)
    if type(value) is int:
        number = value
    elif isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)", value):
            raise ValueError(f"{key} is not an unsigned integer")
        base = 16 if value.lower().startswith("0x") else 8 if len(value) > 1 and value[0] == "0" else 10
        number = int(value, base)
    else:
        raise ValueError(f"{key} is not an unsigned integer")
    if not 0 <= number <= 0xffffffff:
        raise ValueError(f"{key} exceeds the unsigned 32-bit field")
    return number


def decode_native(platform: str, entry: dict) -> tuple[list[tuple], list[str]]:
    """Decode one independent RetroArch native constant write for Dreamcast RAM.

    memory_search_size is log2(bits), not a byte count: 3/4/5 mean 1/2/4 bytes.
    Source: libretro/RetroArch cheat_manager.h, item_cheat; cheat_manager.c,
    cheat_manager_setup_search_meta. Native conditional sequences and other
    operations remain owned by the emulator as a complete table (tools.py).
    Only Dreamcast's verified 16 MiB RAM translation is supported here; other
    platforms, sub-byte masks, repeat programs and rumble use the emulator.
    This validates encoding, not the game's meaning or correctness of an address.
    """
    if platform != "dreamcast":
        return [], [f"native RAM mapping for {platform!r} requires the emulator"]
    try:
        if _native_uint(entry, "handler", 0) != 1:
            raise ValueError("entry is not a RetroArch-native memory cheat")
        if _native_uint(entry, "cheat_type", 1) != 1:
            raise ValueError("native nonconstant operations require the emulator table")
        enum = _native_uint(entry, "memory_search_size", 3)
        if enum not in (3, 4, 5):
            raise ValueError("native sub-byte masks or unsupported widths require the emulator")
        width = 1 << (enum - 3)
        addr = _native_uint(entry, "address")
        value = _native_uint(entry, "value")
        if addr + width > 0x1000000:
            raise ValueError("native write is outside Dreamcast's 16 MiB RAM; no address wrapping")
        if _native_uint(entry, "repeat_count", 1) != 1:
            raise ValueError("native repeat programs require the emulator")
        # Parse all numeric fields even when a single iteration makes its increments inert.
        _native_uint(entry, "repeat_add_to_address", 1)
        _native_uint(entry, "repeat_add_to_value", 0)
        if _native_uint(entry, "rumble_type", 0) != 0:
            raise ValueError("native rumble operations require the emulator")
        endian = entry.get("big_endian", False)
        if type(endian) is bool:
            big_endian = endian
        elif isinstance(endian, str) and endian.strip().lower() in ("true", "false"):
            big_endian = endian.strip().lower() == "true"
        else:
            raise ValueError("big_endian must be true or false")
    except ValueError as exc:
        return [], [str(exc)]
    data = (value & ((1 << (8 * width)) - 1)).to_bytes(width, "big" if big_endian else "little")
    return [("w", 0x8c000000 + addr, data)], []


def _selftest():
    txt = 'cheats = 2\n\ncheat0_desc = "Inf HP"\ncheat0_code = "80309457 0001"\ncheat0_enable = false\n\ncheat1_desc = "B"\ncheat1_code = "1+2"\ncheat1_enable = true\n'
    e = parse_cht(txt)
    assert [x["desc"] for x in e] == ["Inf HP", "B"] and e[1]["enable"] and not e[0]["enable"]
    assert parse_cht(write_cht(e))[0]["code"] == "80309457 0001"
    w, bad = decode_writes(["0250EA10 00000028", "0450EA14 12345678", "C2000000 00000001"])
    assert w[0] == (0x8050EA10, b"\x00\x28") and w[1] == (0x8050EA14, bytes.fromhex("12345678")) and bad == ["C2000000 00000001"]
    g = parse_gecko_txt("GPOE8P\nPSO\n\nInfinite HP [someone]\n0250EA10 00000028\n\nMoon jump\nC2000000 00000001\n")
    assert len(g) == 2 and g[0]["desc"].startswith("Infinite HP") and g[0]["lines"] == ["0250EA10 00000028"]
    ops, bad = decode("n64", "803094DD 0064;D0309261 0020;8130947C 4220;ZZZ")
    assert ops[0] == ("w", 0x803094DE, bytes([0x64])) and ops[1] == ("if", 0x80309262, bytes([0x20]))   # word-swapped RDRAM
    assert ops[2] == ("w", 0x8030947E, bytes([0x20, 0x42])) and bad == ["ZZZ"]
    print("cheats selftest ok")


if __name__ == "__main__":
    _selftest()
