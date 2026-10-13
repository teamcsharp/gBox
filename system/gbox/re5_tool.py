"""`re5`: Resident Evil 5 Gold Edition (PS3, RPCS3 on a Windows node) - unlock every secret / bonus feature (#1104).
Register with:  from . import re5_tool  # noqa: F401

RE5 keeps its unlocks in the save file (DATA0.DAT), not in code, so this is a save edit, done the way the published
Game Genie for PS3 codes do it (Apollo Save Tool's patch database, bucanero/apollo-patches PS3/BLUS30491.savepatch, the
same lines for BLES00816): fixed offsets in DATA0.DAT + the file's additive checksum. RPCS3 keeps PS3 saves decrypted
(<rpcs3>/dev_hdd0/home/<user>/savedata/<serial>*/DATA0.DAT), so no PFD re-signing is involved. Safety: the checksum
rule is first checked against the save as the game wrote it (a mismatch = unknown layout or an encrypted file:
refused); the original is kept as DATA0.DAT.gbox-backup and on=false / op=revert puts it back.

ops: status | unlock_all [groups=[...]] [on=false = revert] | revert | groups | addresses
     merc_time / combo_time / merc_time_bonus: refused with the reason (no published address for the PS3 build).
Live: the game reads DATA0.DAT when it loads the save, so the unlocks show after RE5 is restarted from gBox (or the
save is loaded again from the title). A running RE5 that saves before that writes its old flags back.
"""
from __future__ import annotations

import shutil
import struct
from pathlib import Path

from pydantic import BaseModel

from .models import Permission as P
from .registry import Unsupported, tool

SOURCE = ("Game Genie for PS3 codes as published in Apollo Save Tool's patch database "
          "(bucanero/apollo-patches, PS3/BLUS30491.savepatch and PS3/BLES00816.savepatch, identical code lines), "
          "file DATA0.DAT; Game Genie code types 0/1/2 = 8/16/32-bit big-endian write at the file offset")

# Each group: the published code lines verbatim. Offsets are DATA0.DAT file offsets (not RAM).
GG_CODES = {
    "bonus_features": ("Unlock All Bonus Features", ["200000A4 FFFFFFFF", "200000A8 FFFFFFFF", "200000AC FFFFFFFF"]),
    "files": ("Unlock All Files", ["10000082 0000FFFF"]),
    "cutscenes": ("Unlock All Cutscenes", ["2000008C FFFFFFFF", "20000091 FFFFFFFF"]),
    "figurines": ("Have All Main Game Figurines", ["20000084 FFFFFFFF", "1000008A 0000FFFF"]),
    "chapters": ("Unlock All Chapters and Professional Mode", ["0000010B 000000FF", "1000010E 0000FFFF",
                                                                 "10000116 0000FFFF"]),
    "emblems": ("Have All BSAA Emblems", ["20000118 FFFFFFFF"]),
    "item_management": ("All Items and Upgrades In Item Management", ["20000094 FFFFFFFF"]),
    "points": ("Max Points", ["200000E4 05F5E0FF"]),
    "money": ("Max Money", ["200000E0 05F5E0FF"]),
}
DEFAULT_GROUPS = ("bonus_features", "files", "cutscenes", "figurines", "chapters", "emblems", "item_management")
# [default:Update checksum (required)]  set [csum]:dwadd(10,4BBF) ; write at 0x8:[csum]
CHECKSUM = {"from": 0x10, "to": 0x4BBF, "at": 0x8, "rule": "sum of the big-endian u32 words 0x10..0x4BBF (inclusive), "
                                                             "mod 2^32, stored at 0x8"}

VERSIONS = {
    "BLUS30491": {"name": "Resident Evil 5 Gold Edition (USA, BLUS30491)", "groups": GG_CODES, "checksum": CHECKSUM,
                  "source": SOURCE, "live_checked": False},
    "BLES00816": {"name": "Resident Evil 5 Gold Edition (Europe, BLES00816)", "groups": GG_CODES, "checksum": CHECKSUM,
                  "source": SOURCE, "live_checked": False},
}
GAME_IDS = {"e7ca89bbeb67360d"}      # catalog: Resident Evil 5 - Gold Edition (USA) (v02.00), ps3

NO_MERC_ADDRESSES = (
    "Resident Evil 5 (PS3) has no published address for the Mercenaries clock, time bonus or combo timer: RPCS3's patch "
    "database has only an FPS unlock for BLUS30491 / BLES00816, and the Game Genie / Apollo list for this game edits "
    "the save file only. gBox will not guess addresses. Finding them needs a live memory search during a Mercenaries "
    "round (memory_snapshot, let the clock run, memory_filter dec; then a kill with a time bonus, filter inc).")

COVERAGE = {
    "unlocks": ["Bonus Features (every entry: Special Settings / infinite-ammo and costume entries, Library, ...)",
                "all Files", "all cutscenes", "all main-game figurines", "every chapter + Professional difficulty",
                "all BSAA emblems", "every item and upgrade in Item Management"],
    "not_confirmed": "Mercenaries characters / stages: RE5 unlocks them by rank; whether the Bonus Features words cover "
                     "them is not documented by the source. Check in game (live check in docs/mercenaries.md).",
}


def version(serial: str) -> dict:
    s = (serial or "").upper().replace("-", "")
    if s not in VERSIONS:
        raise Unsupported(f"re5: no verified save layout for {serial or 'an unknown serial'}; known: "
                          f"{', '.join(VERSIONS)} (Resident Evil 5 Gold Edition). Other releases (the original RE5 "
                          "BLUS30270, Japanese BLJM60199) are refused instead of guessed.")
    return VERSIONS[s]


def parse_code(line: str) -> tuple[int, int, int]:
    """Game Genie PS3 'TOOOOOOO VVVVVVVV' (types 0/1/2 only) -> (size, offset, value)."""
    a, v = line.split()
    t = int(a[0], 16)
    if t not in (0, 1, 2) or a[1] != "0":
        raise ValueError(f"unsupported Game Genie code {line!r}")
    return 1 << t, int(a[2:], 16), int(v, 16) & ((1 << (8 << t)) - 1)


def checksum(data: bytes, ck: dict = CHECKSUM) -> int:
    seg = data[ck["from"]:ck["to"] + 1]
    return sum(struct.unpack(f">{len(seg) // 4}I", seg[:len(seg) // 4 * 4])) & 0xFFFFFFFF


def checksum_ok(data: bytes, ck: dict = CHECKSUM) -> bool:
    return len(data) > ck["to"] and struct.unpack_from(">I", data, ck["at"])[0] == checksum(data, ck)


def patch(data: bytes, groups, ver: dict) -> bytes:
    out = bytearray(data)
    for gname in groups:
        for line in ver["groups"][gname][1]:
            size, off, val = parse_code(line)
            out[off:off + size] = val.to_bytes(size, "big")
    struct.pack_into(">I", out, ver["checksum"]["at"], checksum(out, ver["checksum"]))
    return bytes(out)


def group_state(data: bytes, ver: dict) -> dict:
    st = {}
    for gname, (_, lines) in ver["groups"].items():
        st[gname] = all(data[o:o + s] == v.to_bytes(s, "big") for s, o, v in map(parse_code, lines))
    return st


def save_files(home: Path, serial: str) -> list[Path]:
    root = Path(home) / "dev_hdd0" / "home"
    return sorted(p for p in root.glob(f"*/savedata/{serial.upper()}*/DATA0.DAT") if p.is_file())


def _backup(p: Path) -> Path:
    return p.with_name(p.name + ".gbox-backup")


def unlock_file(p: Path, ver: dict, groups) -> dict:
    data = p.read_bytes()
    if not checksum_ok(data, ver["checksum"]):
        raise RuntimeError(f"{p}: the checksum rule ({ver['checksum']['rule']}) does not match this save as the game "
                           "wrote it (encrypted copy from a real PS3, or another layout); not editing it")
    b = _backup(p)
    if not b.exists():
        shutil.copy2(p, b)
    new = patch(data, groups, ver)
    p.write_bytes(new)
    back = p.read_bytes()
    return {"file": str(p), "backup": str(b), "verified": back == new and checksum_ok(back, ver["checksum"]),
            "groups": {g: v for g, v in group_state(back, ver).items() if g in groups},
            "bytes_changed": sum(1 for x, y in zip(data, back) if x != y)}


def revert_file(p: Path) -> dict:
    b = _backup(p)
    if not b.exists():
        return {"file": str(p), "reverted": False, "note": "no gBox backup next to this save (never unlocked by gBox)"}
    shutil.copy2(b, p)
    return {"file": str(p), "reverted": True, "verified": p.read_bytes() == b.read_bytes()}


def run(home: Path, serial: str, op: str = "status", groups=None, on: bool = True, running: bool = False) -> dict:
    op = (op or "status").strip().lower().replace(" ", "_").replace("-", "_")
    op = {"unlock": "unlock_all", "unlock_everything": "unlock_all", "unlock_secrets": "unlock_all",
          "unlock_hidden": "unlock_all", "everything_unlocked": "unlock_all", "restore": "revert",
          "address_table": "addresses"}.get(op, op)
    if op in ("merc_time", "combo_time", "merc_time_bonus", "merc_timer_freeze", "combo_freeze"):
        raise Unsupported(f"re5 {op}: {NO_MERC_ADDRESSES}")
    ver = version(serial)
    res: dict = {"op": op, "game": ver["name"], "live_checked": ver["live_checked"]}
    if op in ("groups", "addresses"):
        res.update(groups={k: {"name": n, "codes": c, "offsets": [f"0x{o:X} ({s * 8}-bit)" for s, o, _ in
                                                                    map(parse_code, c)]}
                           for k, (n, c) in ver["groups"].items()},
                   default=list(DEFAULT_GROUPS), checksum=ver["checksum"]["rule"], source=ver["source"],
                   coverage=COVERAGE)
        return res
    files = save_files(home, serial)
    if not files:
        raise RuntimeError(f"no RE5 save (DATA0.DAT) for {serial} under {Path(home) / 'dev_hdd0' / 'home'}: start RE5 "
                           "once and let it create its save, then unlock")
    if op == "status":
        res["saves"] = []
        for p in files:
            d = p.read_bytes()
            res["saves"].append({"file": str(p), "checksum_ok": checksum_ok(d, ver["checksum"]),
                                 "unlocked": group_state(d, ver) if checksum_ok(d, ver["checksum"]) else None,
                                 "gbox_backup": _backup(p).exists()})
        return res
    if op == "revert" or (op == "unlock_all" and not on):
        res.update(op="revert", saves=[revert_file(p) for p in files])
        res["verified"] = all(s.get("verified", False) for s in res["saves"] if s["reverted"])
        return res
    if op != "unlock_all":
        raise ValueError("re5 op: status | unlock_all [groups] [on=false] | revert | groups | addresses")
    want = list(groups or DEFAULT_GROUPS)
    bad = [g for g in want if g not in ver["groups"]]
    if bad:
        raise ValueError(f"unknown group(s) {bad}; groups: {', '.join(ver['groups'])}")
    res.update(saves=[unlock_file(p, ver, want) for p in files], groups=want, coverage=COVERAGE, source=ver["source"])
    res["verified"] = all(s["verified"] for s in res["saves"])
    res["takes_effect"] = ("restart Resident Evil 5 from gBox (or reload the save from the title): the game reads "
                           "DATA0.DAT when it loads it. If the running game saves first, it writes its old flags back - "
                           "run unlock_all again then." if running else
                           "the next time Resident Evil 5 loads its save")
    return res


class Re5In(BaseModel):
    session_id: str = ""   # a running RE5 session (its RPCS3 folder + serial); empty = this node's RPCS3, serial below
    op: str = "status"     # status | unlock_all | revert | groups | addresses
    on: bool = True        # unlock_all on=false = revert to the original save
    groups: list[str] = [] # unlock_all: subset of the groups (default: every unlock, not points/money)
    serial: str = ""       # without a session: BLUS30491 (USA) | BLES00816 (Europe); default BLUS30491


class Re5Out(BaseModel):
    result: dict


@tool("re5", "1.0", Re5In, Re5Out, capabilities=["mod"], permissions=[P.FILE_MUTATION], timeout_s=120)
def re5_tool(inp: Re5In, ctx):
    """Resident Evil 5 Gold Edition (PS3, RPCS3): unlock all secret / hidden content in the save (bonus features,
    files, cutscenes, figurines, every chapter + Professional, emblems, item management) with the published Game Genie
    offsets + the save checksum; original kept, on=false / op=revert restores it. Mercenaries clock/combo: refused (no
    published address for the PS3 build)."""
    running = False
    if inp.session_id:
        from .tools import SESSIONS
        ad, g = SESSIONS[inp.session_id]
        if g.get("platform") != "ps3":
            raise Unsupported(f"re5: Resident Evil 5 on PS3 (RPCS3); this session is {g.get('title')} ({g.get('platform')})")
        home = getattr(ad, "home", None)
        serial = getattr(ad, "serial", None) or g.get("serial") or inp.serial
        running = True
    else:
        from . import provision
        home, serial = provision.rpcs3_home(ctx.config), inp.serial or "BLUS30491"
    if not home:
        raise RuntimeError("re5: this session has no RPCS3 folder (not an RPCS3 session)")
    return {"result": run(Path(home), serial or "", inp.op, inp.groups, inp.on, running)}
