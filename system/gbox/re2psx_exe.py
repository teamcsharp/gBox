"""Resident Evil 2 Dual Shock (PSX, Claire disc) executable probe.

Analysis-stage companion to :mod:`gbox.re2psx_inventory`. It reads the boot
executable ``SLUS_007.56`` (PS-X EXE, MIPS R3000 little-endian, loaded at
``t_addr`` 0x80010000) and recovers the structures the game uses to load
player models, without a Ghidra dependency so the evidence can be re-derived
in tests:

* :func:`parse_psx_exe` - PS-X EXE header (pc0, gp0, t_addr, t_size, ...).
* :func:`find_file_table` - the game does not open files by name (the EXE
  holds no ``PLxx.PLD`` strings); it keeps a **sector table** with one 8-byte
  record per ISO9660 file in LBA order: ``u32 size_bytes, u32 pos`` where
  ``pos & 0xFFFFFF`` is the absolute LBA and the top byte is a per-file tag.
  The function locates the table by matching the disc's own directory.
* :func:`find_hilo_refs` / :func:`find_jal_callers` - small MIPS scanners
  (lui + addiu/ori/load/store pairs, jal targets) used to tie the table and the
  per-player index table to their loader functions.
* :func:`player_file_index` - resolves a player id to its PLD record via the
  executable's per-player file-number table (see ``probe``).

Run ``python -m gbox.re2psx_exe SLUS_007.56 --bin disc.bin`` for the JSON
probe report (requires the extracted disc for the directory match).
"""

from __future__ import annotations

import json
import struct
import sys

EXE_HEADER = 0x800
RAW_FORM2_SECTOR = 2336

# SLUS_007.56 (sha256 1664e7c6...fbee) addresses, proven by Ghidra project
# ~/gBox_alt/gbox-cache/2d8ef2bdbd4a58fd/ghidra/re2c_slus00756 and by tests.
EXE_SHA256 = "1664e7c634f8cfd03e421f10a6d7e8e8e9fa9bc7982f7c649cc86d28a983fbee"
FILE_TABLE_VA = 0x8009885C     # = $gp; 858 x {u32 size, u16 lba_lo, u8 lba_hi, u8 tag}
CD_LOAD_FILE_VA = 0x80012FB8   # load_file(file_no, dest, mode, name): whole-file CdRead
PLD_FILE_NO_VA = 0x800A3FA0    # u16[16]: player id -> sector-table file number
PLAYER_LOADER_VA = 0x8003BB0C  # loads G.pl's PLD, uploads TIM, keeps EDD/EMR/MD1 resident
PLAYER_LOADER_ALT_VA = 0x80069210  # second consumer (loads to 0x80198000; MD1+TIM only)
ROOM_PLAYER_SETUP_VA = 0x80049E20  # syncs requested id 0x800d47e4 -> G.pl.id, costume rules
MEMCPY_VA = 0x800769B8         # forward byte copy (dst, src, n)
PLAYER_WORK_VA = 0x800CFBB0    # G.pl; +8 = u8 player id (0x800cfbb8)
PL_ID_REQUEST_VA = 0x800D47E4  # requested player id (u16)
PLD_LOAD_BUF = 0x801BFA14      # whole PLD is read here
PLD_RESIDENT = 0x801CD414      # dir[3] bytes (EDD+EMR+MD1) are copied here, offsets rebased
# memcpy(PLD_RESIDENT, PLD_LOAD_BUF, dir[3]) copies forward over an overlapping range, so
# it is only correct while the pre-TIM part fits in the gap between the two buffers.
PLD_RESIDENT_MAX = PLD_RESIDENT - PLD_LOAD_BUF  # 0xDA00 = 55808 bytes


def parse_psx_exe(data: bytes) -> dict:
    """Parse a PS-X EXE header. Raises ValueError on a bad magic."""
    if data[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    if len(data) < EXE_HEADER:
        raise ValueError("PS-X EXE header truncated")
    (pc0, gp0, t_addr, t_size, d_addr, d_size, b_addr, b_size, s_addr,
     s_size) = struct.unpack_from("<10I", data, 0x10)
    if t_size > len(data) - EXE_HEADER:
        raise ValueError("t_size exceeds file")
    region = data[0x4C:0x800].split(b"\0", 1)[0].decode("latin-1")
    return {"pc0": pc0, "gp0": gp0, "t_addr": t_addr, "t_size": t_size,
            "b_addr": b_addr, "b_size": b_size, "s_addr": s_addr,
            "s_size": s_size, "region": region}


class Exe:
    """Text image of a PS-X EXE addressed by virtual address."""

    def __init__(self, data: bytes):
        self.hdr = parse_psx_exe(data)
        self.base = self.hdr["t_addr"]
        self.text = data[EXE_HEADER:EXE_HEADER + self.hdr["t_size"]]
        self.end = self.base + len(self.text)

    def _off(self, va: int, n: int) -> int:
        off = va - self.base
        if off < 0 or off + n > len(self.text):
            raise ValueError(f"VA {va:#x} outside the text image {self.base:#x}..{self.end:#x}")
        return off

    def u32(self, va: int) -> int:
        return struct.unpack_from("<I", self.text, self._off(va, 4))[0]

    def u16(self, va: int) -> int:
        return struct.unpack_from("<H", self.text, self._off(va, 2))[0]

    def words(self):
        for off in range(0, len(self.text) - 3, 4):
            yield self.base + off, struct.unpack_from("<I", self.text, off)[0]


# --- MIPS helpers -----------------------------------------------------------

_LOADSTORE = {0x08: "addiu", 0x09: "addiu", 0x0D: "ori", 0x20: "lb", 0x21: "lh",
              0x23: "lw", 0x24: "lbu", 0x25: "lhu", 0x28: "sb", 0x29: "sh",
              0x2B: "sw"}


def _simm(w: int) -> int:
    v = w & 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def find_hilo_refs(exe: Exe, lo: int, hi: int, window: int = 24) -> list[dict]:
    """Return lui/low16 pairs that form an address in ``[lo, hi)``.

    Each hit gives the lui address, the consumer instruction address, the
    consumer mnemonic and the formed address. ``window`` bounds how many
    instructions after the lui are searched (the register must not be
    redefined in between by another lui).
    """
    text, base = exe.text, exe.base
    n = len(text) // 4
    ws = struct.unpack_from("<%dI" % n, text)
    out = []
    for i, w in enumerate(ws):
        if w >> 26 != 0x0F:  # lui
            continue
        rt = (w >> 16) & 31
        upper = (w & 0xFFFF) << 16
        for j in range(i + 1, min(n, i + 1 + window)):
            x = ws[j]
            op = x >> 26
            if op == 0x0F and ((x >> 16) & 31) == rt:
                break
            if op in _LOADSTORE and ((x >> 21) & 31) == rt:
                addr = (upper | (x & 0xFFFF)) if op == 0x0D else (upper + _simm(x)) & 0xFFFFFFFF
                if lo <= addr < hi:
                    out.append({"lui": base + 4 * i, "use": base + 4 * j,
                                "op": _LOADSTORE[op], "addr": addr})
                if op in (0x08, 0x09, 0x0D, 0x20, 0x21, 0x23, 0x24, 0x25) and ((x >> 16) & 31) == rt:
                    break  # register overwritten by the consumer
    return out


def find_jal_callers(exe: Exe, target: int) -> list[int]:
    """Addresses of ``jal target`` instructions."""
    want = (0x03 << 26) | ((target >> 2) & 0x3FFFFFF)
    return [va for va, w in exe.words() if w == want]


def function_start(exe: Exe, va: int, limit: int = 0x4000) -> int | None:
    """Nearest preceding ``addiu sp, sp, -N`` (PsyQ prologue) at or before va."""
    a = va & ~3
    stop = max(exe.base, a - limit)
    while a >= stop:
        w = exe.u32(a)
        if w >> 16 == 0x27BD and w & 0x8000:
            return a
        a -= 4
    return None


# --- file table -------------------------------------------------------------

def _size_matches(table_size: int, entry: dict) -> bool:
    """Table sizes are bytes; XA/STR (Mode 2 Form 2) records count 2336-byte sectors."""
    if table_size == entry["size"]:
        return True
    return table_size == -(-entry["size"] // 2048) * RAW_FORM2_SECTOR


def find_file_table(exe: Exe, entries: list[dict]) -> dict:
    """Locate the sector table matching the disc directory.

    ``entries`` is the ISO9660 listing ({name, lba, size}); the table is in
    LBA order with records ``u32 size, u32 pos`` (pos & 0xFFFFFF == lba).
    Returns ``{"base", "count", "matched", "unmatched", "index": {name: i}}``
    where ``count`` is the table length (records matching the directory).
    """
    ordered = sorted(entries, key=lambda e: e["lba"])
    if not ordered:
        raise ValueError("no directory entries to match")
    first = ordered[0]
    key = struct.pack("<I", first["size"])
    text = exe.text
    start = 0
    while True:
        off = text.find(key, start)
        if off < 0:
            raise ValueError("file table not found")
        start = off + 1
        if off % 4 or off + 8 > len(text):
            continue
        pos = struct.unpack_from("<I", text, off + 4)[0]
        if pos & 0xFFFFFF != first["lba"]:
            continue
        matched = 0
        for i, e in enumerate(ordered):
            o = off + 8 * i
            if o + 8 > len(text):
                break
            size, pos = struct.unpack_from("<II", text, o)
            if not _size_matches(size, e) or pos & 0xFFFFFF != e["lba"]:
                break
            matched += 1
        if matched >= min(len(ordered), 16):
            # The table ends after the last game file; SYSTEM.CNF, the boot EXE
            # and the ZNULL.DAT pad sit after it on the disc but have no record.
            return {"base": exe.base + off, "count": matched,
                    "matched": matched,
                    "unmatched": [e["name"] for e in ordered[matched:]],
                    "index": {e["name"]: i for i, e in enumerate(ordered[:matched])}}


def table_record(exe: Exe, table_base: int, index: int) -> dict:
    size, pos = exe.u32(table_base + 8 * index), exe.u32(table_base + 8 * index + 4)
    return {"index": index, "size": size, "lba": pos & 0xFFFFFF, "tag": pos >> 24}


def find_u16_index_tables(exe: Exe, wanted: list[int], max_gap: int = 2) -> list[int]:
    """Find u16 arrays whose consecutive elements start with ``wanted``.

    Used to locate the per-player file-number table (player id -> PLD file
    number in the sector table). Elements may be separated by ``max_gap - 1``
    halfwords of other data (stride search 1..max_gap halfwords).
    """
    hits = []
    text = exe.text
    first = struct.pack("<H", wanted[0])
    start = 0
    while True:
        off = text.find(first, start)
        if off < 0:
            return hits
        start = off + 1
        if off % 2:
            continue
        for stride in range(1, max_gap + 1):
            ok = True
            for k, v in enumerate(wanted):
                o = off + 2 * stride * k
                if o + 2 > len(text) or struct.unpack_from("<H", text, o)[0] != v:
                    ok = False
                    break
            if ok:
                hits.append(exe.base + off)


def forward_copy_safe(n: int, delta: int = PLD_RESIDENT_MAX) -> bool:
    """True if a forward byte copy of n bytes to src+delta never reads clobbered data."""
    return 0 <= n <= delta


def _reg_const(exe: Exe, start: int, stop: int, reg: int) -> int | None:
    """Value of ``reg`` built by lui/ori/addiu between start and stop (exclusive)."""
    val = None
    for va in range(start, stop, 4):
        w = exe.u32(va)
        op, rs, rt = w >> 26, (w >> 21) & 31, (w >> 16) & 31
        if op == 0x0F and rt == reg:
            val = (w & 0xFFFF) << 16
        elif op == 0x0D and rt == reg and rs == reg and val is not None:
            val |= w & 0xFFFF
        elif op == 0x09 and rt == reg and rs == reg and val is not None:
            val = (val + _simm(w)) & 0xFFFFFFFF
    return val


def player_loader_sites(exe: Exe) -> list[dict]:
    """Every read of the per-player PLD table and the load call it feeds.

    Returns one record per site: the function entry, the ``lhu a0`` address,
    the following ``jal`` target and the destination buffer passed in ``a1``.
    """
    sites = []
    for r in find_hilo_refs(exe, PLD_FILE_NO_VA, PLD_FILE_NO_VA + 0x20):
        w = exe.u32(r["use"])
        if r["op"] != "lhu" or (w >> 16) & 31 != 4:  # lhu a0, lo(base)
            continue
        jal = None
        for va in range(r["use"] + 4, r["use"] + 0x20, 4):
            x = exe.u32(va)
            if x >> 26 == 0x03:
                jal = (va, (x & 0x3FFFFFF) << 2 | (va & 0xF0000000))
                break
        fn = function_start(exe, r["use"])
        sites.append({"function": fn, "lhu": r["use"],
                      "call": jal[0] if jal else None,
                      "target": jal[1] if jal else None,
                      "dest": _reg_const(exe, fn, jal[0], 5) if (fn and jal) else None})
    return sites


def pld_slots(exe: Exe, tab: dict, table_base: int | None = None) -> list[dict]:
    """Player id -> PLD record via PLD_FILE_NO_VA, with sector capacity to the next file."""
    base = table_base or tab["base"]
    by_index = {i: n for n, i in tab["index"].items()}
    out = []
    for pl_id in range(16):
        file_no = exe.u16(PLD_FILE_NO_VA + 2 * pl_id)
        rec = table_record(exe, base, file_no)
        nxt = table_record(exe, base, file_no + 1)
        out.append({"pl_id": pl_id, "file_no": file_no, "name": by_index.get(file_no),
                    "size": rec["size"], "lba": rec["lba"], "tag": rec["tag"],
                    "capacity": (nxt["lba"] - rec["lba"]) * 2048})
    return out


def probe(exe_bytes: bytes, entries: list[dict]) -> dict:
    """Analysis report: header, sector table, PLD records and code xrefs."""
    exe = Exe(exe_bytes)
    tab = find_file_table(exe, entries)
    base = tab["base"]
    end = base + 8 * tab["count"]
    plds = sorted(n for n in tab["index"] if n.upper().endswith(".PLD"))
    pld_records = {n: table_record(exe, base, tab["index"][n]) for n in plds}
    refs = find_hilo_refs(exe, base - 8, end)
    funcs = sorted({function_start(exe, r["use"]) or 0 for r in refs})
    return {
        "header": {k: (hex(v) if isinstance(v, int) else v) for k, v in exe.hdr.items()},
        "file_table": {"base": hex(base), "count": tab["count"],
                       "matched": tab["matched"], "record": "u32 size, u32 pos(lba|tag<<24)"},
        "pld_records": pld_records,
        "table_refs": [{k: (hex(v) if isinstance(v, int) else v) for k, v in r.items()} for r in refs],
        "table_ref_functions": [hex(f) for f in funcs if f],
        "pld_file_no_table": hex(PLD_FILE_NO_VA),
        "pld_slots": pld_slots(exe, tab),
        "player_loader_sites": [{k: (hex(v) if isinstance(v, int) else v) for k, v in s.items()}
                                for s in player_loader_sites(exe)],
        "writer_constraints": {
            "load_buffer": hex(PLD_LOAD_BUF), "resident": hex(PLD_RESIDENT),
            "resident_max_bytes": PLD_RESIDENT_MAX,
            "rules": [
                "PLD section order EDD, EMR, MD1, TIM; dir[3] (TIM offset) <= 0xDA00",
                "patch u32 size (and LBA if relocated) in SLUS_007.56 table at 0x8009885c + 8*file_no",
                "keep the record tag byte; size must fit the sector capacity or relocate",
                "avoid pl_id 0x0A/0x0E first: extra-part loaders 0x80019440/0x80019024",
            ]},
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0] if __doc__ else None)
    ap.add_argument("exe")
    ap.add_argument("--bin", required=True, help="extracted disc .bin (ISO directory)")
    a = ap.parse_args(argv)
    from gbox.psxdisc import RawBin

    rb = RawBin(a.bin, writable=False)
    entries = [{"name": k, "lba": v[0], "size": v[1]} for k, v in rb.files.items()]
    print(json.dumps(probe(open(a.exe, "rb").read(), entries), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
