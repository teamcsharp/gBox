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
