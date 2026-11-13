"""Reproduce and verify the RE4 dispatcher image (gbox/mercs/native/re4_82c2a04a/code.py).

    python -m gbox.mercs.native.re4_82c2a04a.build_dispatch [out-dir]

Assembles `dispatch.S` with keystone at the cave address, checks the bytes against the pinned image and its sha256,
and disassembles them with capstone for the report (the per-character callback load included). Keystone and capstone
are research/build dependencies: nothing in the gbox runtime imports them. A changed source must be rebuilt here and
re-pinned in `code.py` - the checked-in bytes are what the controller installs.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from . import code as C


def assemble(source: str | None = None) -> bytes:
    from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN
    text = source if source is not None else (Path(__file__).with_name("dispatch.S")).read_text(encoding="utf-8")
    encoder = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)
    encoded, _count = encoder.asm(text, addr=C.CAVE_AT)
    return bytes(encoded)


def assemble_first_aid() -> bytes:
    from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN
    source = Path(__file__).with_name("first_aid.S").read_text(encoding="utf-8")
    return bytes(Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN).asm(source, addr=C.FIRST_AID_AT)[0])


def assemble_weapon_rate() -> bytes:
    from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN
    source = Path(__file__).with_name('weapon_rate.S').read_text(encoding='utf-8')
    return bytes(Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN).asm(source, addr=C.WEAPON_RATE_AT)[0])


def assemble_mine_detonate() -> bytes:
    from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN
    source = Path(__file__).with_name('detonate_mine.S').read_text(encoding='utf-8')
    return bytes(Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN).asm(source, addr=C.MINE_DETONATE_AT)[0])


def check() -> dict:
    image = assemble()
    problems = []
    aid = assemble_first_aid()
    rate = assemble_weapon_rate()
    if rate != C.WEAPON_RATE[4] or hashlib.sha256(rate).hexdigest() != C.WEAPON_RATE[3]:
        problems.append('the firearm-rate guard differs from its pinned source/image')
    if not C.CAVE_AT + len(image) <= C.WEAPON_RATE_AT < C.WEAPON_RATE_AT + len(rate) <= C.FIRST_AID_AT:
        problems.append('the firearm-rate guard overlaps another executable image')
    mine = assemble_mine_detonate()
    if mine != C.MINE_DETONATE[4] or hashlib.sha256(mine).hexdigest() != C.MINE_DETONATE[3]:
        problems.append('the mine-detonation wrapper differs from its pinned source/image')
    if not C.FIRST_AID_AT + len(aid) <= C.MINE_DETONATE_AT < C.MINE_DETONATE_AT + len(mine) <= C.CAVE_END:
        problems.append('the mine-detonation wrapper overlaps another image or exceeds the cave')
    if aid != C.FIRST_AID[4] or hashlib.sha256(aid).hexdigest() != C.FIRST_AID[3]:
        problems.append("the first-aid wrapper differs from its pinned source/image")
    if not C.FIRST_AID_AT + len(aid) <= C.CAVE_END:
        problems.append("the first-aid wrapper exceeds the cave")
    if image != C.DISPATCH[4]:
        problems.append("the assembled bytes differ from the pinned image")
    if hashlib.sha256(image).hexdigest() != C.DISPATCH[3]:
        problems.append("the sha256 differs from the pinned digest")
    if len(image) != C.DISPATCH[2]:
        problems.append("the size differs from the pinned size")
    if len(image) > C.CAVE_SIZE:
        problems.append("the image does not fit the cave")
    tail = None
    try:
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
        decoder = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        decoder.detail = True
        insns = list(decoder.disasm(image, C.CAVE_AT))
        if len(insns) * 4 != len(image):
            problems.append("capstone cannot decode every word")
        for index, ins in enumerate(insns):
            if ins.mnemonic == "ldr" and ins.op_str == "x9, [x19]" and index + 1 < len(insns):
                nxt = insns[index + 1]
                if nxt.mnemonic == "ldr" and nxt.op_str == "x9, [x9, #0x108]":
                    tail = C.CLONE_ORIGINAL_OFF
    except ImportError:                                   # capstone is in the runtime requirements, but stay usable
        pass
    if tail != C.CLONE_ORIGINAL_OFF:
        problems.append("the tail call does not load the pinned per-character original from the clone")
    return {"image": image, "size": len(image), "sha256": hashlib.sha256(image).hexdigest(),
            "tail_call": tail, "problems": problems, "ok": not problems}


def main(argv) -> int:
    report = check()
    image = report["image"]
    if len(argv) > 1:
        out = Path(argv[1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "dispatch.bin").write_bytes(image)
        print(f"wrote {out / 'dispatch.bin'}")
    print(f"dispatch: {report['size']} bytes at {C.CAVE_AT:#x} sha256 {report['sha256']}")
    print(f"tail call: {report['tail_call'] if report['tail_call'] is None else hex(report['tail_call'])}")
    print("verdict:", "PASS - the pinned image reproduces from dispatch.S" if report["ok"]
          else "FAIL - " + "; ".join(report["problems"]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
