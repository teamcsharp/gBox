"""door-latch - a resident native hook that unlocks every door of the floor the player is on.

Operator's standing request (2026-11-14, live): "The game should have a Ghidra hook and latch on it that anytime I play
this game, it automatically unlocks any door I walk up to in this game."

How it works. The game's own dispatcher (`VT_UPDATE` at 0x804C3BC8 points at gBox's cave at 0x80004C00) is called
every player update. This tool writes a small MIPS wrapper into genuinely unused RAM, and points the VT_UPDATE word at
it. The wrapper calls a resident routine that saturates the **current floor's stage-flag group** (0x80515CC8 +
floor*32, 32 bytes of 0xFF - the same action that made the operator walk straight through the Cave door in round 2),
then tail-calls whatever VT_UPDATE pointed at before (normally gBox's cave), so the normal player update is untouched.

It is a latch, not a one-shot: the wrapper runs on every player update, so doors of the floor stay unlocked however
the game rewrites its flags, and no Python polling is involved. A watchdog pass (`--watch`) re-arms the latch if the
worker re-hooks VT_UPDATE for its own pso_controls ops. `--revert` writes the original pointer back.

    python pso-door-latch.py --install
    python pso-door-latch.py --status
    python pso-door-latch.py --watch          # keep the latch armed for the whole session
    python pso-door-latch.py --revert
"""
from __future__ import annotations

import argparse
import json
import pathlib
import struct
import time
import urllib.request

BASE = "http://127.0.0.1:18765"
TOKEN = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token").read_text(encoding="utf-8").strip()
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
LATCH_FILE = OUT / "door-latch.json"
VT_UPDATE = 0x804C3BC8
STAGE_FLAG_BASE = 0x80515CC8
FLOOR = 0x805D5FC0
CODE_SEARCH = (0x804FFE00, 0x804FFD80, 0x804FFD00, 0x804FFC80)
FALLBACK_SEARCH = range(0x80002000, 0x80004000, 0x40)
ROUTINE_SIZE = 0x100


def call(path, payload=None, method="GET", timeout=60):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None, method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as error:                                   # noqa: BLE001
        return {"error": str(error)}


def log(message):
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "door-latch.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "message": message}) + "\n")


class Session:
    def __init__(self):
        rows = call("/api/sessions")
        rows = rows if isinstance(rows, list) else (rows.get("items") or [])
        live = [row for row in rows if row.get("state") in ("running", "starting")
                and row.get("adapter") == "dolphin"]
        if not live:
            raise RuntimeError("no live dolphin session")
        self.sid = live[0]["session_id"]
        self.worker = self.sid.split("-")[0]

    def rpc(self, op, **args):
        return call(f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args}, "POST")

    def read(self, address, length):
        raw = self.rpc("read_memory", address=int(address), length=int(length))
        return bytes.fromhex(raw) if isinstance(raw, str) else b""

    def write(self, address, data):
        job = call("/api/jobs", {"tool": "write_memory", "require_worker": self.worker,
                                 "input": {"session_id": self.sid, "address": int(address),
                                           "hex_bytes": data.hex()}}, "POST", 30)
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            return False
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            row = call("/api/jobs/" + job_id)
            if isinstance(row, dict) and row.get("state") == "succeeded":
                return True
            if isinstance(row, dict) and row.get("state") in ("failed", "cancelled"):
                return False
            time.sleep(0.05)
        return False


def u32(value):
    return struct.pack(">I", value & 0xFFFFFFFF)


def build_code(base, original=0x80004C00):
    """The wrapper at `base`, the saturating routine at `base + 0x80`."""
    routine = base + 0x80
    code = [
        0x7C0802A6,   # mflr  r0
        0x9421FFC0,   # stwu  r1, -64(r1)
        0x90010004,   # stw   r0, 4(r1)
        0x90610008,   # stw   r3, 8(r1)
        0x9081000C,   # stw   r4, 12(r1)
        0x90A10010,   # stw   r5, 16(r1)
        0x90C10014,   # stw   r6, 20(r1)
        0x90E10018,   # stw   r7, 24(r1)
        0x9101001C,   # stw   r8, 28(r1)
        0x91210020,   # stw   r9, 32(r1)
        0x91410024,   # stw   r10, 36(r1)
    ]
    bl_index = len(code)
    code.append(0x48000000)                        # bl saturate (patched below)
    code += [
        0x80010004,   # lwz   r0, 4(r1)
        0x80610008,   # lwz   r3, 8(r1)
        0x8081000C,   # lwz   r4, 12(r1)
        0x80A10010,   # lwz   r5, 16(r1)
        0x80C10014,   # lwz   r6, 20(r1)
        0x80E10018,   # lwz   r7, 24(r1)
        0x8101001C,   # lwz   r8, 28(r1)
        0x81210020,   # lwz   r9, 32(r1)
        0x81410024,   # lwz   r10, 36(r1)
        0x7C0803A6,   # mtlr  r0
        0x38210040,   # addi  r1, r1, 64
        # Tail-call the update this tool displaced. The value is an immediate, never re-read from VT_UPDATE: after the
        # hook that word holds the wrapper's own address, and reloading it made the wrapper call itself forever.
        0x3D800000 | ((original >> 16) & 0xFFFF),          # addis r12, r0, hi
        0x618C0000 | (original & 0xFFFF),                   # ori   r12, r12, lo
        0x7D8903A6,   # mtctr r12
        0x4E800420,   # bctr
    ]
    # bl offset = (routine - (base + bl_index*4 + 4)) >> 2; LK=1 so the routine's blr comes back here
    offset = (routine - (base + bl_index * 4 + 4)) >> 2
    code[bl_index] = 0x48000001 | (offset & 0x03FFFFFC)
    pad = 0x80 - len(code) * 4
    assert pad >= 0, "wrapper no longer fits before the routine"
    payload = b"".join(u32(word) for word in code) + b"\x00" * pad
    body = [
        0x3C60805D,   # lis   r3, 0x805D
        0x60635FC0,   # ori   r3, r3, 0x5FC0
        0x80830000,   # lwz   r4, 0(r3)          ; floor
        0x2C040001,   # cmpwi r4, 1
        0x4180000D,   # blt   skip               ; Pioneer 2's group is left alone
        0x2C040011,   # cmpwi r4, 17
        0x4181000B,   # bgt   skip
        0x3CA08051,   # lis   r5, 0x8051
        0x60A55CC8,   # ori   r5, r5, 0x5CC8
        0x54862834,   # slwi  r6, r4, 5
        0x7CA53214,   # add   r5, r5, r6
        0x390000FF,   # li    r8, 0xFF   (addi r8, r0, 0xFF)
        0x38E00000,   # li    r7, 0      (addi r7, r0, 0)
        0x99050000,   # loop: stb r8, 0(r5)
        0x38A50001,   # addi  r5, r5, 1
        0x38E70001,   # addi  r7, r7, 1
        0x2C070020,   # cmpwi r7, 32
        0x4180FFFB,   # blt   loop
        0x4E800020,   # skip: blr
    ]
    payload += b"".join(u32(word) for word in body)
    payload += b"\x00" * (ROUTINE_SIZE - len(payload))
    return payload


def find_code_space(session, size=ROUTINE_SIZE):
    """Prefer the unused tail of MEM1 below the 0x80500000 manager block; it stayed zero across a live second."""
    for candidates in (CODE_SEARCH, FALLBACK_SEARCH):
        for address in candidates:
            blob = session.read(address, size)
            if len(blob) == size and blob == b"\x00" * size:
                session.write(address, b"\x11" * size)
                stable = session.read(address, size) == b"\x11" * size
                session.write(address, b"\x00" * size)
                if stable:
                    return address
    raise RuntimeError("no zero-filled code space found")


def status(session):
    pointer = session.read(VT_UPDATE, 4)
    current = int.from_bytes(pointer, "big") if len(pointer) == 4 else None
    record = {}
    if LATCH_FILE.exists():
        try:
            record = json.loads(LATCH_FILE.read_text(encoding="utf-8"))
        except ValueError:
            record = {}
    floor_raw = session.read(FLOOR, 4)
    floor = int.from_bytes(floor_raw, "big") if len(floor_raw) == 4 else None
    group = session.read(STAGE_FLAG_BASE + (floor or 0) * 32, 32) if floor is not None else b""
    return {"vt_update": current, "wrapper": record.get("wrapper"),
            "latched": bool(record.get("wrapper")) and current == record.get("wrapper"),
            "floor": floor, "floor_group_saturated": group == b"\xff" * 32}


def install(session, force=False):
    record = {}
    if LATCH_FILE.exists():
        try:
            record = json.loads(LATCH_FILE.read_text(encoding="utf-8"))
        except ValueError:
            record = {}
    if record.get("wrapper") and record.get("session") == session.sid:
        base = int(record["wrapper"])
        blob = session.read(base, ROUTINE_SIZE)
        if blob == build_code(base, int(record.get("previous_vt_update") or 0x80004C00)):
            pointer = session.read(VT_UPDATE, 4)
            if int.from_bytes(pointer, "big") == base:
                return {"already": True, "wrapper": base}
            session.write(VT_UPDATE, u32(base))
            return {"rearmed": True, "wrapper": base}
        if not force:
            # another area's code (or the game reloaded) - rewrite it
            pass
    current = session.read(VT_UPDATE, 4)
    original = int.from_bytes(current, "big") if len(current) == 4 else None
    if original is None:
        raise RuntimeError("cannot read VT_UPDATE")
    base = find_code_space(session)
    code = build_code(base, original)
    if not session.write(base, code):
        raise RuntimeError("code write failed")
    if session.read(base, ROUTINE_SIZE) != code:
        raise RuntimeError("code readback mismatch")
    time.sleep(0.4)
    if session.read(base, ROUTINE_SIZE) != code:
        raise RuntimeError("code space is not stable")
    if not session.write(VT_UPDATE, u32(base)):
        raise RuntimeError("hook write failed")
    pointer = session.read(VT_UPDATE, 4)
    if int.from_bytes(pointer, "big") != base:
        raise RuntimeError("hook readback mismatch")
    # Prove the hook actually runs before trusting it: the resident routine saturates the current floor's group, so a
    # single saturated group means the game executed our code and the player update resumed. If it does not happen the
    # wrapper is broken (or the guest is spinning in it), so roll back at once - the same break-the-loop trick that
    # recovered the live game: the routine's loop branch becomes a return, then VT_UPDATE goes back to its old target.
    floor_raw = session.read(FLOOR, 4)
    floor = int.from_bytes(floor_raw, "big") if len(floor_raw) == 4 else 0
    group = STAGE_FLAG_BASE + floor * 32
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if session.read(group, 32) == b"\xff" * 32:
            break
        time.sleep(0.1)
    if session.read(group, 32) != b"\xff" * 32:
        session.write(base + 0x80 + 68, u32(0x4E800020))       # loop branch -> blr
        session.write(VT_UPDATE, u32(original))
        LATCH_FILE.unlink(missing_ok=True)
        raise RuntimeError("hook did not run: flags never saturated; rolled back")
    LATCH_FILE.write_text(json.dumps({"session": session.sid, "wrapper": base,
                                      "previous_vt_update": original, "at": time.time()},
                                     indent=1), encoding="utf-8")
    log(f"door latch installed: wrapper {base:#x}, saturating floor group every player update")
    return {"installed": True, "wrapper": base, "previous": original, "floor_group_saturated": True}


def revert(session):
    record = json.loads(LATCH_FILE.read_text(encoding="utf-8")) if LATCH_FILE.exists() else {}
    previous = record.get("previous_vt_update")
    if previous is None:
        return {"reverted": False, "reason": "no latch record"}
    session.write(VT_UPDATE, u32(int(previous)))
    now = session.read(VT_UPDATE, 4)
    ok = int.from_bytes(now, "big") == int(previous)
    log(f"door latch reverted to {previous:#x} (verified {ok})")
    return {"reverted": ok, "vt_update": int.from_bytes(now, "big")}


def main(argv=None):
    parser = argparse.ArgumentParser(description="resident native door latch")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--period", type=float, default=3.0)
    args = parser.parse_args(argv)
    if args.watch:
        log("door latch watchdog started")
        session = None
        while True:
            try:
                if session is None:
                    session = Session()
                state = status(session)
                if not state["latched"]:
                    log(f"latch not armed ({state}) - installing")
                    install(session, force=True)
                else:
                    session.write(VT_UPDATE, u32(state["wrapper"]))
            except Exception as error:                           # noqa: BLE001
                session = None
                log(f"watch pass failed: {type(error).__name__}: {error}")
            time.sleep(args.period)
    session = Session()
    if args.install:
        print(json.dumps(install(session)))
    elif args.revert:
        print(json.dumps(revert(session)))
    else:
        print(json.dumps(status(session)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
