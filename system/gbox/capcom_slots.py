"""Capcom Generations (PS1) boot-file slot tables.

Each game EXE (P1942/P1943/P1943K) carries a pointer table of ISO9660 path
strings (``\\1943\\CHAR.DEE;1``); the table index is the loader's file slot.
Found by scanning for runs of word pointers into the EXE's own cstrings.
"""
import struct

PSX_HDR = 0x800


def _cstr(exe, taddr, ptr):
    off = ptr - taddr + PSX_HDR
    if not (PSX_HDR <= off < len(exe)):
        return None
    end = exe.find(b"\0", off, off + 64)
    if end < 0:
        return None
    s = exe[off:end]
    if len(s) < 5 or not all(32 <= c < 127 for c in s):
        return None
    return s.decode("ascii")


def find_slot_tables(exe, min_run=8):
    """Return [(table_vaddr, [path, ...])] runs of >=min_run path pointers."""
    if exe[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    taddr = struct.unpack_from("<I", exe, 0x18)[0]
    n = (len(exe) - PSX_HDR) // 4
    words = struct.unpack_from("<%dI" % n, exe, PSX_HDR)
    out, run, start = [], [], 0
    for i, w in enumerate(words + (0,)):
        s = _cstr(exe, taddr, w) if i < n and taddr <= w < taddr + n * 4 else None
        if s and s.endswith(";1") and "\\" in s:
            if not run:
                start = i
            run.append(s[:-2])
        else:
            if len(run) >= min_run:
                out.append((taddr + start * 4, run))
            run = []
    return out


def slot_table(exe):
    """Largest slot table as {slot_index: iso_path_without_version}."""
    t = find_slot_tables(exe)
    if not t:
        raise ValueError("no slot table")
    _, paths = max(t, key=lambda x: len(x[1]))
    return {i: p.lstrip("\\").replace("\\", "/") for i, p in enumerate(paths)}
