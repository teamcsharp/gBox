"""GoldenEye 007 AI lists decoded from the owned ROM's level setup files (#2410, gBrain milestone 2).

A level's setup file (``Usetup<level>Z`` / ``Ump_setup<level>Z``, rarezip in the ROM, read through
gbox.goldeneye_files) starts with the decomp's ``stagesetup`` record: ten big-endian u32 file offsets (pathwaypoints,
waypointgroups, intro, propDefs, patrolpaths, ailists, pads, boundpads, padnames, boundpadnames). ``ailists`` is an
array of ``{u32 list offset, u32 id}`` records ending with a zero offset; ids 0x0401-0x04FF are character lists,
0x1000-0x10FF background (level logic) lists. Each list is the 1-byte-opcode bytecode of gbox/bond_ai/commands.json,
ending with EndList (0x04). Decoding every list of every level to its EndList with no unknown opcode is also the check
that the command table's parameter widths are right: one wrong width puts the decoder out of step.

    python -m gbox.bond_ai.ailists <GoldenEye ROM (.z64/.zip)> [--level UsetupdamZ] [--out lists.json]
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from . import commands as C

SETUP_FIELDS = ("pathwaypoints", "waypointgroups", "intro", "propDefs", "patrolpaths", "ailists", "pads",
                "boundpads", "padnames", "boundpadnames")
END_LIST = 0x04


class DecodeError(ValueError):
    pass


def decode_list(buf: bytes, off: int, table: dict[int, dict] | None = None, limit: int = 0x10000) -> list[dict]:
    """The commands of one AI list at `off`: [{at, op, name, args: {param: value}}], EndList included."""
    table = table or C.by_opcode()
    out, o = [], off
    while True:
        if o >= len(buf) or o - off > limit:
            raise DecodeError(f"list at 0x{off:x}: no EndList before 0x{o:x}")
        op = buf[o]
        cmd = table.get(op)
        if cmd is None:
            raise DecodeError(f"list at 0x{off:x}: unknown opcode 0x{op:02x} at 0x{o:x}")
        if cmd.get("variable") == "nul_terminated_text":       # PRINT: text up to and including a NUL
            end = buf.find(bytes(1), o + 1)
            if end < 0:
                raise DecodeError(f"list at 0x{off:x}: {cmd['name']} at 0x{o:x} has no NUL")
            out.append({"at": o, "op": op, "name": cmd["name"],
                        "args": {"TEXT": buf[o + 1:end].decode("latin-1")}})
            o = end + 1
            continue
        if o + cmd["length"] > len(buf):
            raise DecodeError(f"list at 0x{off:x}: {cmd['name']} at 0x{o:x} runs past the file")
        args, p = {}, o + 1
        for prm in cmd["params"]:
            args[prm["name"]] = int.from_bytes(buf[p:p + prm["bytes"]], "big")
            p += prm["bytes"]
        out.append({"at": o, "op": op, "name": cmd["name"], "args": args})
        o += cmd["length"]
        if op == END_LIST:
            return out


def setup_header(buf: bytes) -> dict[str, int]:
    if len(buf) < 40:
        raise DecodeError("setup file shorter than its header")
    return dict(zip(SETUP_FIELDS, struct.unpack_from(">10I", buf, 0)))


def ai_lists(setup: bytes, table: dict[int, dict] | None = None) -> list[dict]:
    """Every AI list of one level setup file: [{id, kind, offset, commands}] in the file's order."""
    table = table or C.by_opcode()
    o = setup_header(setup)["ailists"]
    if not o or o + 8 > len(setup):
        raise DecodeError(f"ailists offset 0x{o:x} outside the file")
    out = []
    while o + 8 <= len(setup):
        lst, lid = struct.unpack_from(">II", setup, o)
        if lst == 0:
            return out
        kind = "character" if 0x400 <= lid <= 0x4FF else "background" if 0x1000 <= lid <= 0x10FF else "global"
        out.append({"id": lid, "kind": kind, "offset": lst, "commands": decode_list(setup, lst, table)})
        o += 8
    raise DecodeError("ailists array has no terminator")


def text(lst: dict) -> str:
    """One list as readable lines: `0x0401  0010  SetChrAiList(CHR_NUM=1, AI_LIST_ID=0x405)`."""
    rows = [f"AI list 0x{lst['id']:04x} ({lst['kind']}), {len(lst['commands'])} commands"]
    for c in lst["commands"]:
        args = ", ".join(f"{k}={v!r}" if isinstance(v, str) else f"{k}={v:#x}" if v > 9 else f"{k}={v}"
                         for k, v in c["args"].items())
        rows.append(f"  {c['at'] - lst['offset']:04x}  {c['name']}({args})")
    return "\n".join(rows)


GLOBAL_NAMES = ("AIM_AT_BOND", "DEAD_AI", "STANDARD_GUARD", "PLAY_IDLE_ANIMATION", "BASH_KEYBOARD", "SIMPLE_GUARD_DEAF",
                "ATTACK_BOND", "SIMPLE_GUARD", "RUN_TO_BOND", "SIMPLE_GUARD_ALARM_RAISER", "STARTLE_AND_RUN_TO_BOND",
                "TRY_CLONE_SEND_OR_RUN_TO_BOND", "STANDARD_CLONE", "PERSISTENTLY_CHASE_AND_ATTACK_BOND",
                "WAIT_ONE_SECOND", "END_LEVEL", "DRAW_TT33_AND_ATTCK_BOND", "REMOVE_CHR")   # chraidata.c table order


def find_global_table(data: bytes, base_vram: int) -> int:
    """Offset of g_GlobalAILists in the game's data segment: {u32 list pointer, u32 id} records whose ids are
    0x00..0x11 in some order, every pointer inside the segment, then a {0, 0} terminator."""
    n = len(GLOBAL_NAMES)
    hi = base_vram + len(data)
    for o in range(0, len(data) - 8 * (n + 1) + 1, 4):
        recs = [struct.unpack_from(">II", data, o + 8 * k) for k in range(n + 1)]
        if recs[-1] != (0, 0) or sorted(r[1] for r in recs[:-1]) != list(range(n)):
            continue
        if all(base_vram <= r[0] < hi for r in recs[:-1]):
            return o
    raise DecodeError("g_GlobalAILists not found in the data segment")


def global_lists(ge, table: dict[int, dict] | None = None) -> list[dict]:
    """GoldenEye's shared AI lists (ids 0x00-0x11: patrol, combat, chase, flee ...) from the data segment."""
    from ..goldeneye_files import DATA_VRAM
    table = table or C.by_opcode()
    o = find_global_table(ge.data, DATA_VRAM)
    out = []
    for k in range(len(GLOBAL_NAMES)):
        ptr, lid = struct.unpack_from(">II", ge.data, o + 8 * k)
        out.append({"id": lid, "kind": "global", "name": GLOBAL_NAMES[lid] if lid < len(GLOBAL_NAMES) else "",
                    "offset": ptr - DATA_VRAM, "commands": decode_list(ge.data, ptr - DATA_VRAM, table)})
    return out


def rom_levels(rom_path) -> dict[str, list[dict]]:
    from ..goldeneye_files import GoldenEyeROM
    ge = GoldenEyeROM.load(rom_path)
    table = C.by_opcode()
    return {e.name: ai_lists(ge.read_file(e.name), table)
            for e in ge.file_table() if "setup" in e.name.lower()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rom")
    ap.add_argument("--level", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    levels = rom_levels(a.rom)
    if a.level:
        levels = {a.level: levels[a.level]}
    total = sum(len(v) for v in levels.values())
    cmds = sum(len(lst["commands"]) for v in levels.values() for lst in v)
    print(f"{len(levels)} setup files, {total} AI lists, {cmds} commands decoded")
    if a.out:
        Path(a.out).write_text(json.dumps(levels, indent=1), encoding="utf-8")
    elif a.level:
        for lst in levels[a.level]:
            print(text(lst))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
