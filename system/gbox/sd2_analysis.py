"""WWF SmackDown! 2 - Know Your Role (USA, SLUS-01234): loader pins and writer-format probe (#1332, analysis stage).

Exact build: boot SLUS_012.34 sha256 e23acb31...2a7f, text 0x80010000 + 0x7c800. The reused Ghidra input is a RAM image
taken during a match (``~/gBox_alt/gbox-cache/sdk_re/ghidra_ram.bin``, sha256 f0a9524c...c220, decompile ``sd2_ram.c``). Its
code is byte-identical to the EXE text over 0x80010000-0x8007ffff (``ram_matches``), so its function addresses hold
for this build. ``verify_exe`` re-derives every pin below from the owned EXE alone: jal call sites inside each
function's extent and the magic constants built by lui/ori pairs.

How the game reads a wrestler part (ED1H/ED1B/ED1L DPAC entry = "PAC "):
  * 80027aa4 binary-searches the u16 item ids, so a PAC's ids must ascend. Entries are 8 bytes: u16 id, 24-bit
    offset (from the end of the table), 24-bit size. 80027eec/80027f64 read them.
  * 8002806c unpacks an item: "BPE " -> 800612a0 (Gage byte-pair decoder, src+16, size at +0xc), else memcpy.
  * 8003e244 loads a part. It relocates every "EMD " item for the player slot (8003ab40 -> 8003aa94 with
    player*3 and player*0xc0), takes the model as item index 0, and fetches the texture PAC by id 10 (80027d38).
    Then 8003e0c4 builds the optional head attachment: id 2 (a small EMD) placed by id 3 (seven 4-character ASCII
    numbers). Both lookups are null-checked, so a head without ids 2/3 just has no attachment.
  * EXE.PAC overlays: 80013528 / 80013628 BPE-decode 0x801e0810 -> 0x801b8000 and 0x800a0010 -> 0x80130000.

``probe(files)`` checks what yukes_sd's writer must keep on the real ED1* files: ascending ids, the head
attachments it drops (ids 2/3, safe per 8003e0c4), and the TIMs it must keep byte-identical (4-bpp leg pages
on CLUT rows 253-255/257, CLUT-less 16-bpp pages).

    python -m gbox.sd2_analysis BIN [--exe SLUS_012.34] [--ram ghidra_ram.bin] [--out report.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path

from . import yukes_sd as y

EXE_SHA256 = "e23acb3165ed001b6d23558ef81624cea70b97d98e68a2a93546e6466a3c2a7f"
RAM_SHA256 = "f0a9524cf6d42cbf661911fc4554ab1bdfdb5cc1ccb68b5777ba5c402425c220"
TEXT, TEXT_SIZE, CODE_END = 0x80010000, 0x7C800, 0x80080000
BPE, EMD = 0x20455042, 0x20444D45
JR_RA = 0x03E00008

# start -> (end, name, role). end = the next function start in the RAM decompile.
FUNCS = {
    0x80027AA4: (0x80027B30, "pac_find_id", "binary search over the u16 item ids -> index or -1"),
    0x80027C00: (0x80027C3C, "pac_open", "PAC handle {ptr, 0x400000 | header size} for a loaded entry"),
    0x80027D38: (0x80027DC4, "pac_child_by_id", "unpack the item with a given id as a child PAC (texture PAC: id 10)"),
    0x80027EEC: (0x80027F64, "pac_item_ptr", "base + header + 24-bit offset at entry+2"),
    0x80027F64: (0x80027FC4, "pac_item_size", "24-bit size at entry+5"),
    0x80027FF8: (0x8002806C, "pac_item_unpacked_size", "'BPE ' -> u32 at +0xc, else the stored size"),
    0x8002806C: (0x80028114, "pac_item_unpack", "'BPE ' -> bpe_decode, else memcpy"),
    0x80028114: (0x80028168, "pac_item_alloc_unpack", "malloc + pac_item_unpack"),
    0x80028168: (0x800281F8, "pac_item_view", "in place, or a decoded copy when 'BPE '"),
    0x80028268: (0x800282C0, "pac_unpack_by_id", "pac_find_id + pac_item_unpack"),
    0x80028304: (0x80028348, "pac_size_by_id", "pac_find_id + pac_item_unpacked_size"),
    0x8002838C: (0x800283D0, "pac_item_ptr_by_id", "pac_find_id + pac_item_ptr; 0 when the id is absent"),
    0x800612A0: (0x80061434, "bpe_decode", "Gage byte-pair expansion (src, dst, dst_end)"),
    0x80061434: (0x800614A4, "memcpy", "(dst, src, n)"),
    0x80013528: (0x80013628, "overlay_unpack_a", "BPE 0x801e0810 -> 0x801b8000"),
    0x80013628: (0x80013770, "overlay_unpack_b", "BPE 0x800a0010 -> 0x80130000"),
    0x8003AA94: (0x8003AB40, "emd_relocate", "per-player EMD relocation (args player*3, player*0xc0)"),
    0x8003AB40: (0x8003ABDC, "pac_relocate_emds", "every 'EMD ' item of a PAC -> emd_relocate"),
    0x8003E0C4: (0x8003E244, "head_attachment", "optional ids 2 (EMD) + 3 (7 ASCII fields), null-checked"),
    0x8003E244: (0x8003E690, "wrestler_part_load", "relocate EMDs, model = item 0, textures = id 10, attachment"),
}
XREFS = {
    0x80027FF8: (0x80027EEC, 0x80027F64),
    0x8002806C: (0x80027EEC, 0x80027F64, 0x800612A0, 0x80061434),
    0x80028114: (0x80027FF8, 0x8002806C),
    0x80028168: (0x80027EEC, 0x80027FF8, 0x800612A0),
    0x80028268: (0x80027AA4, 0x8002806C),
    0x80028304: (0x80027AA4, 0x80027FF8),
    0x8002838C: (0x80027AA4, 0x80027EEC),
    0x80027D38: (0x80028268, 0x80028304),
    0x80013528: (0x800612A0,),
    0x80013628: (0x80013528, 0x800612A0),
    0x8003AB40: (0x80027EEC, 0x8003AA94),
    0x8003E0C4: (0x8002838C,),
    0x8003E244: (0x80027C00, 0x80027D38, 0x80028114, 0x8003AB40, 0x8003E0C4),
}
MAGIC = {0x80027FF8: BPE, 0x8002806C: BPE, 0x80028168: BPE, 0x8003AB40: EMD,
         0x80013528: 0x801E0810, 0x80013628: 0x800A0010}


def exe_text(exe: bytes) -> bytes:
    """The PS-X EXE's text segment (must load at 0x80010000)."""
    if exe[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    t_addr, t_size = struct.unpack_from("<II", exe, 0x18)
    if t_addr != TEXT:
        raise ValueError(f"text loads at {t_addr:#x}, not {TEXT:#x}")
    return exe[0x800:0x800 + t_size]


def scan(text: bytes, start: int, end: int, base: int = TEXT) -> tuple[set[int], set[int]]:
    """MIPS words in [start, end) -> (jal targets, 32-bit constants from lui + ori/addiu on the same register)."""
    calls, consts, hi = set(), set(), {}
    for pc in range(start, end, 4):
        w = struct.unpack_from("<I", text, pc - base)[0]
        op = w >> 26
        if op == 3:
            calls.add((pc & 0xF0000000) | (w & 0x3FFFFFF) << 2)
        elif op == 0x0F:
            hi[(w >> 16) & 31] = w & 0xFFFF
        elif op in (0x09, 0x0D) and (w >> 21) & 31 in hi:
            lo = w & 0xFFFF
            if op == 0x09 and lo & 0x8000:
                lo -= 0x10000
            consts.add(((hi[(w >> 21) & 31] << 16) + lo if op == 0x09 else hi[(w >> 21) & 31] << 16 | lo) & 0xFFFFFFFF)
    return calls, consts


def verify_exe(exe: bytes) -> dict:
    """Re-derive the pinned functions from the EXE: each extent ends in jr ra, has its xrefs and magic constants."""
    text = exe_text(exe)
    funcs, bad = {}, []
    for start, (end, name, role) in FUNCS.items():
        words = [struct.unpack_from("<I", text, a - TEXT)[0] for a in range(start, end, 4)]
        calls, consts = scan(text, start, end)
        want = set(XREFS.get(start, ()))
        # Ghidra splits some large functions (8003e244 -> 8003e690/8003e6e0/8003e91c), so look for the epilogue's
        # jr ra up to 0x1000 bytes past the listed extent.
        tail = [struct.unpack_from("<I", text, a - TEXT)[0] for a in range(end, min(end + 0x1000, TEXT + len(text)), 4)]
        ret = next((start + 4 * i for i, w in enumerate(words + tail) if w == JR_RA), None)
        ok = {"returns": ret is not None, "xrefs": want <= calls,
              "magic": start not in MAGIC or MAGIC[start] in consts}
        funcs[name] = {"addr": f"{start:#010x}", "end": f"{end:#010x}", "role": role, **ok,
                       "jr_ra": f"{ret:#010x}" if ret else None,
                       "calls": sorted(f"{c:#010x}" for c in calls & set(FUNCS))}
        bad += [f"{name}:{k}" for k, v in ok.items() if not v]
    return {"sha256": hashlib.sha256(exe).hexdigest(), "exact_build": hashlib.sha256(exe).hexdigest() == EXE_SHA256,
            "functions": funcs, "failed": bad}


def ram_matches(exe: bytes, ram: bytes) -> float:
    """Fraction of EXE code bytes (0x80010000-0x8007ffff) equal in a 2 MB RAM image."""
    text = exe_text(exe)[:CODE_END - TEXT]
    seg = ram[TEXT - 0x80000000:CODE_END - 0x80000000]
    return sum(a == b for a, b in zip(text, seg)) / len(text)


def pac_ids(b: bytes, o: int = 0) -> list[int]:
    n = struct.unpack_from("<I", b, o + 4)[0]
    return [struct.unpack_from("<H", b, o + 8 + 8 * i)[0] for i in range(n)]


def _raw_tim(d: bytes) -> bytes:
    return y.bpe_decode(d) if d[:4] == b"BPE " else d


def probe(files: dict[str, bytes]) -> dict:
    """Writer-format checks on ED1H/ED1B/ED1L -> per-file report (counts, problems)."""
    out = {}
    for f in y.PART_FILES:
        seqs, tims, kept, unsorted, mismatch, attach = Counter(), Counter(), Counter(), [], [], set()
        for eid, _units, o in y.dpac_entries(files[f]):
            ids = pac_ids(files[f], o)
            seqs[",".join(map(str, ids))] += 1
            if ids != sorted(ids):
                unsorted.append(f"{eid:#x}")
            if {2, 3} <= set(ids):
                attach.add(eid >> 4)
            for t, d in y.pac_parse(files[f], o):
                if t != 0x0A:
                    continue
                if pac_ids(d) != sorted(pac_ids(d)):
                    unsorted.append(f"{eid:#x}/tex")
                for _i, td in y.pac_parse(d):
                    raw = _raw_tim(td)
                    tim = y.tim_parse(raw)
                    c = tim.get("clut_xy")
                    key = f"bpp{tim['bpp']}/" + (f"row{c[1]}/{c[2] * c[3]}" if c else "noclut")
                    tims[key] += 1
                    if not y.repaintable(tim):          # the writer keeps these: they must rebuild byte-identically
                        kept[key] += 1
                        if y.tim_build(tim) != raw:
                            mismatch.append(f"{eid:#x}:{key}")
        out[f] = {"item_ids": dict(seqs), "unsorted": unsorted, "tims": dict(sorted(tims.items())),
                  "kept_tims": dict(sorted(kept.items())), "kept_mismatch": mismatch,
                  "attachment_groups": sorted(f"{g:#x}" for g in attach)}
    return out


def report(bin_path: Path, exe: bytes | None = None, ram: bytes | None = None) -> dict:
    files = y.read_files(Path(bin_path))
    if exe is None:
        exe = y.read_files(Path(bin_path), ("SLUS_012.34",))["SLUS_012.34"]
    rep: dict = {"exe": verify_exe(exe), "probe": probe(files)}
    if ram is not None:
        rep["ram"] = {"sha256": hashlib.sha256(ram).hexdigest(), "code_match": round(ram_matches(exe, ram), 6)}
    groups = set(rep["probe"]["ED1H.PAC"]["attachment_groups"])
    try:                                                    # roster naming is informative only
        rep["attachment_wrestlers"] = sorted(w["name"] for w in y.roster(Path(bin_path))
                                             if f"{y.bcd(w['id']):#x}" in groups)
    except Exception as e:
        rep["attachment_wrestlers_error"] = repr(e)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SmackDown! 2 USA loader pins and writer-format probe")
    ap.add_argument("bin")
    ap.add_argument("--exe")
    ap.add_argument("--ram")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rep = report(Path(a.bin), Path(a.exe).read_bytes() if a.exe else None, Path(a.ram).read_bytes() if a.ram else None)
    text = json.dumps(rep, indent=1)
    Path(a.out).write_text(text) if a.out else print(text)
    return 0 if not rep["exe"]["failed"] and not any(p["unsorted"] or p["kept_mismatch"] for p in rep["probe"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
