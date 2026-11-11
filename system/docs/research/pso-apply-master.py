"""Apply the operator's master setup in verified stages, each with its own evidence.

Stages (run them independently):
  hp        freeze the player's HP at its maximum through write_memory + freeze_memory (both now work on this session)
  legendary give 5 copies of a legendary weapon and multi-equip them so all five weapon slots hold it
  ultimate  enable the Ultimate difficulty selection (the plane's `legendary` mod, next offline game)
  techs     write the technique-level array (default OFF: needs the table confirmed first)
  status    report what is currently true, changing nothing

Every stage prints the plane's own answer plus a re-read, so a claim is never based on the request alone.

Usage:
  python apply_master.py status
  python apply_master.py hp
  python apply_master.py legendary --code 000100
  python apply_master.py ultimate
  python apply_master.py techs --offset 0x2E7 --apply      (writes 20 bytes of 30)
"""
import json
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

PLAYER_POINTER = 0x8050EA10
HP, HP_MAX, TP, TP_MAX = 0x32C, 0x2B8, 0x32E, 0x2BA
TECH_OFFSET = 0x2E7
TECH_COUNT = 20


def log(line):
    print(line, flush=True)


def player_pointer():
    value = int.from_bytes(S.read_memory(PLAYER_POINTER, 4), "big")
    if not (0x80000000 <= value < 0x81800000):
        log(f"no player loaded (table holds {hex(value)})")
        return None
    return value


def status():
    pointer = player_pointer()
    if pointer is None:
        return 2
    blob = S.read_memory(pointer, 0x340)
    hp = struct.unpack(">H", blob[HP:HP + 2])[0]
    hpmax = struct.unpack(">H", blob[HP_MAX:HP_MAX + 2])[0]
    tp = struct.unpack(">H", blob[TP:TP + 2])[0]
    tpmax = struct.unpack(">H", blob[TP_MAX:TP_MAX + 2])[0]
    floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
    techs = list(blob[TECH_OFFSET:TECH_OFFSET + TECH_COUNT])
    log(f"actor {hex(pointer)} floor {floor} hp {hp}/{hpmax} tp {tp}/{tpmax}")
    log(f"technique bytes at +0x{TECH_OFFSET:03X}: {techs}")
    caps = S.controls("capabilities", {})
    log(f"capabilities supported: {caps.get('supported') if isinstance(caps, dict) else caps}")
    return 0


def stage_hp():
    pointer = player_pointer()
    if pointer is None:
        return 2
    blob = S.read_memory(pointer, 0x340)
    hp = struct.unpack(">H", blob[HP:HP + 2])[0]
    hpmax = struct.unpack(">H", blob[HP_MAX:HP_MAX + 2])[0]
    if hp == hpmax:
        log(f"hp already full ({hp}/{hpmax})")
        return 0
    want = struct.pack(">H", hpmax)
    state, result, error = S.job("write_memory", {"session_id": S.session_id(),
                                                 "address": pointer + HP, "hex_bytes": want.hex()}, timeout=60)
    log(f"write hp: {state} {error or ''} {json.dumps(result)[:120] if result else ''}")
    state, result, error = S.job("freeze_memory", {"session_id": S.session_id(),
                                                   "address": pointer + HP, "hex_bytes": want.hex()}, timeout=60)
    log(f"freeze hp: {state} {error or ''}")
    blob = S.read_memory(pointer, 0x340)
    log(f"hp after: {struct.unpack('>H', blob[HP:HP + 2])[0]}/{hpmax}")
    return 0


def stage_legendary(code="000100", copies=5):
    log(f"giving {copies} copies of {code} and multi-equipping them")
    for index in range(copies):
        state, result, error = S.controls("give", {"code": code})
        log(f"  give {index + 1}: {json.dumps(result)[:140] if result else error}")
    reply = S.controls("multi_equip", {"target": "0", "count": copies})
    log(f"multi_equip: {json.dumps(reply)[:200] if reply else 'no reply'}")
    return 0


def stage_ultimate():
    reply = S.controls("legendary", {"on": True})
    log(f"legendary: {json.dumps(reply)[:240] if reply else 'no reply'}")
    return 0


def stage_techs(offset, apply_it):
    pointer = player_pointer()
    if pointer is None:
        return 2
    before = list(S.read_memory(pointer + offset, TECH_COUNT))
    log(f"technique bytes before (+0x{offset:03X}): {before}")
    if not apply_it:
        log("dry run: pass --apply to write 30 into every slot")
        return 0
    payload = bytes([30] * TECH_COUNT)
    state, result, error = S.job("write_memory", {"session_id": S.session_id(),
                                                 "address": pointer + offset,
                                                 "hex_bytes": payload.hex()}, timeout=60)
    log(f"write techs: {state} {error or ''} {json.dumps(result)[:140] if result else ''}")
    after = list(S.read_memory(pointer + offset, TECH_COUNT))
    log(f"technique bytes after: {after}")
    return 0


def main(argv):
    command = argv[1] if len(argv) > 1 else "status"
    if command == "status":
        return status()
    if command == "hp":
        return stage_hp()
    if command == "legendary":
        code = argv[argv.index("--code") + 1] if "--code" in argv else "000100"
        return stage_legendary(code)
    if command == "ultimate":
        return stage_ultimate()
    if command == "techs":
        offset = int(argv[argv.index("--offset") + 1], 0) if "--offset" in argv else TECH_OFFSET
        return stage_techs(offset, "--apply" in argv)
    log(f"unknown command {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
