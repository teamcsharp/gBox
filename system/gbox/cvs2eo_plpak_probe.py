"""Structural probe for CvS2 EO (GameCube) gc/afs02.afs plNNpak.bin character packs.

Proven by parsing the owned pl00pak.bin (968,020 B) / pl01pak.bin; field meanings beyond layout
are hypotheses:
  * header: 4 x (u32 0, u32 offset) LE pairs -> section offsets 0x20, secB, secC, 0 (terminator)
  * section A (0x20..first target): u32 LE ascending offset table; the table ends exactly at the
    first target offset (0x30c0 for pl00), all targets < secB.
  * section B: u32 LE offset table (monotone prefix) of small records, then record data.
"""
import struct

HDR_PAIRS = 4


def parse_plpak(d: bytes) -> dict:
    if len(d) < 0x20:
        raise ValueError("too short")
    pairs = struct.unpack_from("<8I", d, 0)
    if any(pairs[0::2]):
        raise ValueError("header high words not zero")
    offs = list(pairs[1::2])
    sec_a, sec_b, sec_c = offs[0], offs[1], offs[2]
    if offs[3] != 0 or not (sec_a < sec_b < sec_c <= len(d)):
        raise ValueError(f"bad section offsets {offs}")
    first = struct.unpack_from("<I", d, sec_a)[0]
    n_a = (first - sec_a) // 4
    if sec_a + 4 * n_a != first:
        raise ValueError("section A table does not end at first target")
    ta = struct.unpack_from(f"<{n_a}I", d, sec_a)
    mono = all(b >= a for a, b in zip(ta, ta[1:]))
    n_b = 0
    tb = struct.unpack_from(f"<{(sec_c - sec_b) // 4}I", d, sec_b)
    for a, b in zip(tb, tb[1:]):
        if b < a:
            break
        n_b += 1
    return {"size": len(d), "sec_a": sec_a, "sec_b": sec_b, "sec_c": sec_c,
            "a_count": n_a, "a_first": ta[0], "a_last": ta[-1], "a_monotone": mono,
            "a_in_range": max(ta) < sec_b, "b_monotone_prefix": n_b + 1, "b_first": tb[0]}


def parse_frames(d: bytes) -> dict:
    """Parse secB as sprite-composition records (verified structure, field meaning hypothesis).

    secB = u32 offset table (relative to secB; count = first_offset/4) then records
    ``u16 n`` + n x 8-byte parts (4 x u16/s16: x, y, flags/size, sprite index).  On the
    owned pl00/pl01 packs every record tiles exactly up to the next offset / secC.
    Part field names and the sprite index -> secA chunk mapping are hypotheses.
    """
    import struct as _s
    if len(d) < 32:
        raise ValueError("pak too small")
    h = _s.unpack_from("<8I", d, 0)
    a, b, c = h[1], h[3], h[5]
    if not (0 < a < b < c <= len(d)) or b + 4 > len(d):
        raise ValueError("bad section offsets")
    n = _s.unpack_from("<I", d, b)[0] // 4
    if n == 0 or b + 4 * n > c:
        raise ValueError("bad frame table")
    tb = _s.unpack_from("<%dI" % n, d, b)
    frames, exact, max_idx = [], 0, -1
    for k, o in enumerate(tb):
        if b + o + 2 > c:
            raise ValueError("frame offset out of range")
        cnt = _s.unpack_from("<H", d, b + o)[0]
        end = b + o + 2 + 8 * cnt
        nxt = b + tb[k + 1] if k + 1 < n else c
        exact += end == nxt
        parts = [_s.unpack_from("<hhhH", d, b + o + 2 + 8 * j) for j in range(cnt) if end <= c]
        for p in parts:
            max_idx = max(max_idx, p[3])
        frames.append(parts)
    return {"frame_count": n, "exact_tiling": exact, "max_sprite_idx": max_idx,
            "parts": sum(len(f) for f in frames), "frames": frames}


# --- DOL file-table (verified on owned default.dol sha 455591ea...) ---------
# Loader fn 0x801764c0(idx, dest, flag) does: path = *(u32*)(0x802214d0 + 4*idx),
# then size/read helpers 0x801b0dbc / 0x801b0c78.  plNNpak.bin is idx 57+NN.
DOL_FILE_TABLE_VADDR = 0x802214D0
DOL_PLPAK_FIRST_IDX = 57


def _dol_sections(dol: bytes):
    import struct as _s
    off = _s.unpack_from(">18I", dol, 0)
    adr = _s.unpack_from(">18I", dol, 0x48)
    ln = _s.unpack_from(">18I", dol, 0x90)
    return [(off[i], adr[i], ln[i]) for i in range(18) if ln[i]]


def dol_vaddr_to_off(dol: bytes, va: int):
    for o, a, l in _dol_sections(dol):
        if a <= va < a + l:
            return o + va - a
    return None


def dol_file_table_path(dol: bytes, idx: int) -> str:
    """Resolve loader file-table entry `idx` to its path string."""
    import struct as _s
    p = _s.unpack_from(">I", dol, dol_vaddr_to_off(dol, DOL_FILE_TABLE_VADDR + 4 * idx))[0]
    o = dol_vaddr_to_off(dol, p)
    return dol[o:o + 64].split(b"\0")[0].decode("ascii")
