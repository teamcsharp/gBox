"""door-hook - patch the game's own player-update entry so every floor's doors unlock every frame.

Operator's request (2026-11-14, live): "The game should have a Ghidra hook and latch on it that anytime I play this
game, it automatically unlocks any door I walk up to in this game."

The Ghidra map (D:\\gBox\\ghidra-pso\\PSO, pso_v3.elf): the player constructor FUN_801bd424 sets player+0x18 to the
vtable at 0x804C3BBC whose slot +12 (0x804C3BC8) holds ORIGINAL_UPDATE = 0x801BB330. Replacing that slot at runtime
does not execute (the running actor's entry is already resolved), but patching the *function entry itself* runs through
the existing gBox cave tail-chain. So this tool:

  1. copies ORIGINAL_UPDATE's first 16 bytes (the prologue: stwu/mflr/stw/stw) into a trampoline in unused RAM,
  2. makes the trampoline save the update's volatile registers, saturate the current floor's stage-flag group
     (0x80515CC8 + floor*32 = 32 bytes of 0xFF, the same action that opened the Cave door for the operator), record a
     marker + the floor it read, restore the registers, replay the displaced prologue and continue at 0x801BB340,
  3. overwrites 0x801BB330 with an absolute jump into the trampoline (lis/ori/mtctr/bctr - 0x804FFC00 is 54 MB away,
     outside a plain branch's range),
  4. asks the *guest* to icbi the patched line through gBox's own FLUSH_CODE at 0x80004F00 (a guest icbi invalidates
     Dolphin's JIT block; a host-side write alone would leave the warm block running old code).

Verification is part of the install: the marker must change, the current floor's flag group must read 0xFF and the
guest must keep ticking. Anything else rolls the 16 bytes back and re-flushes.

    python pso-door-hook.py --install
    python pso-door-hook.py --status
    python pso-door-hook.py --revert
    python pso-door-hook.py --watch
"""
from __future__ import annotations

import argparse
import json
import pathlib
import struct
import time

import importlib.util

spec = importlib.util.spec_from_file_location(
    "pso_door_latch", r"C:\_tools\gBox\system\docs\research\pso-door-latch.py")
latch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(latch)

Session = latch.Session
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
RECORD = OUT / "door-hook.json"
UPDATE = 0x801BB330
UPDATE_CONTINUE = UPDATE + 16
VT_UPDATE = 0x804C3BC8
CAVE = 0x80004C00
FLUSH_FN = 0x80004F00
QUEUE = 0x80004400
QSZ = 40
STAGE_FLAG_BASE = latch.STAGE_FLAG_BASE
FLOOR = latch.FLOOR
CODE_BASE = 0x804FFC00
MARKER = 0x804FFD80
TRAMPOLINE_SIZE = 0x100


def u32(value):
    return struct.pack(">I", value & 0xFFFFFFFF)


def log(message):
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "door-hook.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "message": message}) + "\n")


def locate_space(session, size=0x400):
    """Find a page in the upper half of MEM1 that is all zero and stays zero - never trust a first glance."""
    for chunk in range(0x80400000, 0x80500000, 0x1000):
        blob = session.read(chunk, 0x1000)
        if len(blob) != 0x1000 or blob != b"\x00" * 0x1000:
            continue
        time.sleep(0.25)
        if session.read(chunk, 0x1000) != b"\x00" * 0x1000:
            continue
        return chunk
    raise RuntimeError("no stable zero page found in MEM1's upper half")


def locate_and_set(session):
    global CODE_BASE, MARKER
    base = locate_space(session)
    CODE_BASE = base
    MARKER = base + 0x180
    return base, MARKER


def build_min_trampoline(displaced, marker=None):
    """Phase A: only proves the relocation (save regs/CR-free, marker 0x5A, replay prologue, continue)."""
    marker = MARKER if marker is None else marker
    code = [
        0x9421FFA0, 0x7C0802A6, 0x90010004, 0x90610008, 0x9081000C, 0x90A10010,
        0x90C10014, 0x90E10018, 0x9101001C, 0x91210020, 0x91410024, 0x91610028, 0x9181002C,
        0x3D400000 | ((marker >> 16) & 0xFFFF),   # addis r10, r0, hi(marker)
        0x614A0000 | (marker & 0xFFFF),           # ori   r10, r10, lo(marker)
        0x3920005A,                               # li    r9, 0x5A
        0x992A0000,                               # stb   r9, 0(r10)
        0x816A0008,                               # lwz   r11, 8(r10)
        0x396B0001,                               # addi  r11, r11, 1
        0x916A0008,                               # stw   r11, 8(r10)
        0x80010004, 0x80610008, 0x8081000C, 0x80A10010, 0x80C10014, 0x80E10018,
        0x8101001C, 0x81210020, 0x81410024, 0x81610028, 0x8181002C,
        0x7C0803A6, 0x38210060,
    ]
    code.extend(displaced)
    code += [
        0x3D800000 | ((UPDATE_CONTINUE >> 16) & 0xFFFF),
        0x618C0000 | (UPDATE_CONTINUE & 0xFFFF),
        0x7D8903A6, 0x4E800420,
    ]
    payload = b"".join(u32(word) for word in code)
    if len(payload) > TRAMPOLINE_SIZE:
        raise RuntimeError("minimal trampoline does not fit")
    return payload + b"\x00" * (TRAMPOLINE_SIZE - len(payload))


def build_trampoline(base=CODE_BASE, marker=MARKER, displaced=(0x9421FFF0, 0x7C0802A6, 0x90010014, 0x93E1000C)):
    """Wrapper at `base`; runs the saturation, replays `displaced`, then continues at UPDATE_CONTINUE."""
    code = [
        0x9421FFA0,   # stwu  r1, -96(r1)
        0x7C0802A6,   # mflr  r0
        0x90010004,   # stw   r0, 4(r1)
        0x90610008,   # stw   r3, 8(r1)
        0x9081000C,   # stw   r4, 12(r1)
        0x90A10010,   # stw   r5, 16(r1)
        0x90C10014,   # stw   r6, 20(r1)
        0x90E10018,   # stw   r7, 24(r1)
        0x9101001C,   # stw   r8, 28(r1)
        0x91210020,   # stw   r9, 32(r1)
        0x91410024,   # stw   r10, 36(r1)
        0x91610028,   # stw   r11, 40(r1)
        0x9181002C,   # stw   r12, 44(r1)
        0x3C60805D,   # lis   r3, 0x805D
        0x60635FC0,   # ori   r3, r3, 0x5FC0
        0x80830000,   # lwz   r4, 0(r3)              floor
        0x2C040001,   # cmpwi r4, 1
        0x4180000D,   # blt   skip                  (Pioneer 2's group is left alone)
        0x2C040011,   # cmpwi r4, 17
        0x4181000B,   # bgt   skip
        0x3CA08051,   # lis   r5, 0x8051
        0x60A55CC8,   # ori   r5, r5, 0x5CC8
        0x54862834,   # slwi  r6, r4, 5
        0x7CA53214,   # add   r5, r5, r6
        0x390000FF,   # li    r8, 0xFF
        0x38E00000,   # li    r7, 0
        0x99050000,   # loop: stb r8, 0(r5)
        0x38A50001,   # addi  r5, r5, 1
        0x38E70001,   # addi  r7, r7, 1
        0x2C070020,   # cmpwi r7, 32
        0x4180FFFB,   # blt   loop
        0x3D400000 | ((marker >> 16) & 0xFFFF),   # skip: addis r10, r0, hi(marker)
        0x614A0000 | (marker & 0xFFFF),           # ori   r10, r10, lo(marker)
        0x392000A5,   # li    r9, 0xA5
        0x992A0000,   # stb   r9, 0(r10)            marker = 0xA5
        0x908A0004,   # stw   r4, 4(r10)            store the floor we read
        0x816A0008,   # lwz   r11, 8(r10)
        0x396B0001,   # addi  r11, r11, 1
        0x916A0008,   # stw   r11, 8(r10)            bump the call counter
        0x80010004,   # lwz   r0, 4(r1)
        0x80610008,   # lwz   r3, 8(r1)
        0x8081000C,   # lwz   r4, 12(r1)
        0x80A10010,   # lwz   r5, 16(r1)
        0x80C10014,   # lwz   r6, 20(r1)
        0x80E10018,   # lwz   r7, 24(r1)
        0x8101001C,   # lwz   r8, 28(r1)
        0x81210020,   # lwz   r9, 32(r1)
        0x81410024,   # lwz   r10, 36(r1)
        0x81610028,   # lwz   r11, 40(r1)
        0x8181002C,   # lwz   r12, 44(r1)
        0x7C0803A6,   # mtlr  r0
        0x38210060,   # addi  r1, r1, 96
    ]
    code.extend(displaced)                                        # replay the displaced prologue
    code += [
        0x3D800000 | ((UPDATE_CONTINUE >> 16) & 0xFFFF),          # addis r12, r0, hi(continue)
        0x618C0000 | (UPDATE_CONTINUE & 0xFFFF),                  # ori   r12, r12, lo(continue)
        0x7D8903A6,   # mtctr r12
        0x4E800420,   # bctr
    ]
    payload = b"".join(u32(word) for word in code)
    if len(payload) > TRAMPOLINE_SIZE:
        raise RuntimeError(f"trampoline is {len(payload)} bytes, does not fit {TRAMPOLINE_SIZE}")
    return payload + b"\x00" * (TRAMPOLINE_SIZE - len(payload))


def guest_flush(session, address):
    """Run gBox's FLUSH_CODE with r3=address: guest dcbi/sync/icbi/isync, which invalidates Dolphin's JIT block."""
    line = int(address) & ~31
    pending = session.read(QUEUE, QSZ * 20)
    if not pending or any(struct.unpack_from(">I", pending, i * QSZ)[0] for i in range(20)):
        raise RuntimeError("native queue is busy; refusing to publish a flush")
    session.write(QUEUE, struct.pack(">10I", 0, line, 0, 0, 0, 0, 0, 0, 0, 0))
    session.write(QUEUE, u32(FLUSH_FN))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        head = session.read(QUEUE, QSZ)
        if len(head) == QSZ and struct.unpack_from(">I", head, 0)[0] == 0:
            return {"flushed": line, "result": struct.unpack_from(">I", head, 36)[0]}
        time.sleep(0.005)
    raise RuntimeError("guest flush did not acknowledge")


def guest_call(session, fn, args=()):
    """Publish one native call into gBox's queue exactly like pso_gc_live.call: payload first, then the fn word."""
    payload = struct.pack(">10I", 0, *[int(v) & 0xFFFFFFFF for v in args], *([0] * (8 - len(args))), 0)
    if not session.write(QUEUE, payload):
        raise RuntimeError("queue payload write failed")
    if not session.write(QUEUE, u32(fn)):
        raise RuntimeError("queue publish failed")
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        head = session.read(QUEUE, QSZ)
        if len(head) == QSZ and struct.unpack_from(">I", head, 0)[0] == 0:
            return struct.unpack_from(">I", head, 36)[0]
        time.sleep(0.005)
    raise RuntimeError("native call was not acknowledged")


def find_low_zero_page(session):
    """A zero page between the gBox cave (ends 0x80005000) and the DOL text base (0x8000C000)."""
    for chunk in range(0x80005000, 0x8000C000, 0x1000):
        blob = session.read(chunk, 0x1000)
        if len(blob) == 0x1000 and blob == b"\x00" * 0x1000:
            return chunk
    raise RuntimeError("no zero page found in the low arena")


def build_probe(base):
    """Guest probe: save volatiles, write marker 0x11 + bump counter, restore, return. Validates encodings/frame."""
    marker = base + 0x180
    code = [
        0x9421FFA0, 0x7C0802A6, 0x90010004, 0x90610008, 0x9081000C, 0x90A10010,
        0x90C10014, 0x90E10018, 0x9101001C, 0x91210020, 0x91410024, 0x91610028, 0x9181002C,
        0x3D400000 | ((marker >> 16) & 0xFFFF),
        0x614A0000 | (marker & 0xFFFF),
        0x39200011,
        0x992A0000,
        0x816A0008,
        0x396B0001,
        0x916A0008,
        0x80010004, 0x80610008, 0x8081000C, 0x80A10010, 0x80C10014, 0x80E10018,
        0x8101001C, 0x81210020, 0x81410024, 0x81610028, 0x8181002C,
        0x7C0803A6, 0x38210060,
        0x4E800020,
    ]
    payload = b"".join(u32(word) for word in code)
    return payload, marker


def probe(session):
    base = find_low_zero_page(session)
    payload, marker = build_probe(base)
    session.write(base, b"\x00" * 0x200)
    session.write(base, payload)
    if session.read(base, len(payload)) != payload:
        raise RuntimeError("probe write failed")
    session.write(marker, b"\x00" * 12)
    before = int.from_bytes(session.read(marker + 8, 4), "big")
    result = guest_call(session, base)
    after = int.from_bytes(session.read(marker + 8, 4), "big")
    state = session.read(marker, 4)
    log(f"probe at {base:#x}: marker {state.hex()} counter {before}->{after} result {result:#x}")
    return {"base": base, "marker": state.hex(), "before": before, "after": after, "result": result}


def current_state(session):
    global CODE_BASE, MARKER
    if RECORD.exists():
        try:
            record = json.loads(RECORD.read_text(encoding="utf-8"))
            if record.get("marker"):
                MARKER = int(record["marker"])
            if record.get("trampoline"):
                CODE_BASE = int(record["trampoline"])
        except ValueError:
            pass
    floor_raw = session.read(FLOOR, 4)
    floor = int.from_bytes(floor_raw, "big") if len(floor_raw) == 4 else None
    marker = session.read(MARKER, 8)
    group = session.read(STAGE_FLAG_BASE + (floor or 0) * 32, 32) if floor is not None else b""
    pointer = session.read(VT_UPDATE, 4)
    return {"floor": floor, "marker": marker.hex(), "hook_running": marker[:1] == b"\xa5",
            "floor_group_saturated": group == b"\xff" * 32, "vt_update": int.from_bytes(pointer, "big")
            if len(pointer) == 4 else None, "patch": session.read(UPDATE, 16).hex()}


def in_install_state(session):
    state = current_state(session)
    return state["vt_update"] == CAVE


def install(session):
    if not in_install_state(session):
        raise RuntimeError(f"gBox dispatcher is not installed (VT_UPDATE={hex(current_state(session)['vt_update'] or 0)})")
    base, marker = locate_and_set(session)
    log(f"using zero page {base:#x} for the trampoline, marker {marker:#x}")
    original = session.read(UPDATE, 16)
    if len(original) != 16:
        raise RuntimeError("cannot read the update prologue")
    displaced = struct.unpack(">4I", original)
    if session.read(CODE_BASE, TRAMPOLINE_SIZE) != b"\x00" * TRAMPOLINE_SIZE:
        session.write(CODE_BASE, b"\x00" * TRAMPOLINE_SIZE)
    if session.read(MARKER, 8) != b"\x00" * 8:
        session.write(MARKER, b"\x00" * 8)
    patch = b"".join(u32(word) for word in [
        0x3D800000 | ((CODE_BASE >> 16) & 0xFFFF),   # addis r12, r0, hi(trampoline)
        0x618C0000 | (CODE_BASE & 0xFFFF),           # ori   r12, r12, lo(trampoline)
        0x7D8903A6,                                  # mtctr r12
        0x4E800420,                                  # bctr
    ])

    def restore():
        session.write(UPDATE, original)
        try:
            guest_flush(session, UPDATE)
        except Exception as error:                               # noqa: BLE001
            log(f"restore flush failed: {error}")

    # Phase A - relocation only: prove that the patched entry reaches the trampoline, the trampoline's frame is
    # harmless, the displaced prologue runs in the right order and execution continues at UPDATE_CONTINUE.
    minimal = build_min_trampoline(displaced)
    if not session.write(CODE_BASE, minimal) or session.read(CODE_BASE, TRAMPOLINE_SIZE) != minimal:
        raise RuntimeError("minimal trampoline write failed")
    if not session.write(UPDATE, patch) or session.read(UPDATE, 16) != patch:
        restore()
        raise RuntimeError("entry patch write failed")
    try:
        guest_flush(session, UPDATE)
    except Exception:
        restore()
        raise
    log(f"relocation test installed at {UPDATE:#x} -> {CODE_BASE:#x}")
    deadline = time.monotonic() + 2.5
    state = current_state(session)
    alive = 0
    while time.monotonic() < deadline:
        state = current_state(session)
        if state["marker"].startswith("5a"):
            first = int.from_bytes(session.read(MARKER + 8, 4), "big")
            time.sleep(0.5)
            second = int.from_bytes(session.read(MARKER + 8, 4), "big")
            alive = second - first
            if alive > 0:
                break
        time.sleep(0.05)
    if not state["marker"].startswith("5a") or alive <= 0:
        restore()
        raise RuntimeError(f"relocation test failed: {state} ticks={alive}; entry restored")
    log(f"relocation test passed: marker {state['marker']}, guest ticking ({alive} words/s)")

    # Phase B - replace the trampoline body with the saturation code. The trampoline block is warm now, so ask the
    # guest for an icbi on its own line; Dolphin then recompiles it from the new bytes.
    full = build_trampoline(displaced=displaced)
    if not session.write(CODE_BASE, full) or session.read(CODE_BASE, TRAMPOLINE_SIZE) != full:
        restore()
        raise RuntimeError("full trampoline write failed")
    try:
        guest_flush(session, CODE_BASE)
    except Exception:
        restore()
        raise
    deadline = time.monotonic() + 3.0
    alive = 0
    state = current_state(session)
    while time.monotonic() < deadline:
        state = current_state(session)
        if state["hook_running"] and state["floor_group_saturated"]:
            first = int.from_bytes(session.read(MARKER + 8, 4), "big")
            time.sleep(0.5)
            second = int.from_bytes(session.read(MARKER + 8, 4), "big")
            alive = second - first
            if alive > 0:
                break
        time.sleep(0.05)
    if not state["hook_running"] or not state["floor_group_saturated"] or alive <= 0:
        restore()
        raise RuntimeError(f"hook verification failed: {state} ticks={alive}; entry restored")
    RECORD.write_text(json.dumps({"update": UPDATE, "original": original.hex(),
                                  "trampoline": CODE_BASE, "marker": MARKER, "at": time.time()}, indent=1),
                      encoding="utf-8")
    log(f"door hook verified: marker {state['marker']}, floor {state['floor']} group saturated, guest ticking ({alive} words/s)")
    return {"installed": True, "trampoline": CODE_BASE, "floor": state["floor"],
            "marker": state["marker"], "ticks": alive}


def revert(session):
    record = json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}
    original = bytes.fromhex(record.get("original", ""))
    if len(original) != 16:
        raise RuntimeError("no install record; refusing to guess the original prologue")
    session.write(UPDATE, original)
    try:
        guest_flush(session, UPDATE)
    except Exception as error:                                   # noqa: BLE001
        log(f"revert flush failed (entry bytes are restored anyway): {error}")
    verified = session.read(UPDATE, 16) == original
    log(f"door hook reverted: entry restored {verified}")
    return {"reverted": verified}


def watch(period=3.0):
    log("door hook watchdog started")
    session = None
    while True:
        try:
            if session is None:
                session = Session()
            state = current_state(session)
            if not state["hook_running"]:
                log(f"hook not running ({state}) - reinstalling")
                session = None
                fresh = Session()
                install(fresh)
                session = fresh
        except Exception as error:                               # noqa: BLE001
            session = None
            log(f"watch pass failed: {type(error).__name__}: {error}")
        time.sleep(period)


def main(argv=None):
    parser = argparse.ArgumentParser(description="native door hook: saturate the floor's flags from inside the update")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args(argv)
    if args.watch:
        watch()
        return 0
    session = Session()
    if args.probe:
        print(json.dumps(probe(session)))
    elif args.install:
        print(json.dumps(install(session)))
    elif args.revert:
        print(json.dumps(revert(session)))
    else:
        print(json.dumps(current_state(session)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
