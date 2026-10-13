"""gbox.crazy_taxi display-list writer: every material pointer of a rewritten .shp must name whole GX primitives on the
stock list's vertex attribute table, with one sampled UV per material.

The cast build cast_crazy_taxi_usa_sonic_adventure_us_82d27070 (Sonic Adventure cast as the four drivers) hung on the
driver-select screen with Dolphin's "GFX FIFO: Unknown Opcode (0x18 @ ...a01)": MP_YH_plyrA_atama / sl_atama have a
fifth / fourth material whose list lies *before* the previous record's list (0x9e0 vs 0xa20), the ascending-order scan
skipped it, the writer zeroed and repacked the region and that record kept pointing at 0xa00/0x40 - one byte into a
vertex stream (index byte 0x18). Then the lists were written on VAT 0 (0x98/0x90) where the stock ones use VAT 2/3, so
the drivers drew at the wrong scale, and every corner's UV was (0, 0), a see-through texel on the head textures.

Synthetic parts reproduce each case; the owned-disc checks (GBOX_CT_ISO / GBOX_CT_BANK) run the whole bank.
"""
import hashlib
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import crazy_taxi as ct
from gbox import crazy_taxi_swap as cs

ISO = Path(os.environ.get("GBOX_CT_ISO", "/home/ehm_eckx/gbox-cache/modbase/bc02bb68790ce2e7/Crazy Taxi (USA).iso"))
BANK_FILE = os.environ.get("GBOX_CT_BANK", "")

BOX = [(x, y, z) for x in (0.0, 4.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]
QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
TRIS = [t for a, b, c, d in QUADS for t in ((a, b, c), (a, c, d))]
UVS = [(0, 0), (128, 64), (40, 200)]              # entry 0 stands for a see-through corner texel
VAT = 2


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def _list(tris, tex: int, vat: int = VAT) -> bytes:
    dl = bytearray(bytes([0x90 | vat]) + struct.pack(">H", 3 * len(tris)))
    for t in tris:
        for i in t:
            dl += struct.pack(">3H", i, i, tex)
    return bytes(dl + b"\0" * ((0x20 - len(dl) % 0x20) % 0x20))


def _head(order=(0, 2, 1), unreferenced: bool = False) -> bytes:
    """Axel's-head-style part: three material records whose lists sit in the DL region in `order` (record 2's list
    before record 1's, as 0x9e0 sits before 0xa20 on the disc), VAT 2 primitives, POS/NRM/TEX0 arrays (three UVs:
    material 0 draws with UV 1, material 1 with UV 2, material 2 with UV 1). unreferenced: one more list in the region
    that no record points at."""
    centre = (2.0, 0.0, 0.0)
    local = np.asarray(BOX, float) - centre
    radius = float(np.linalg.norm(local, axis=1).max())
    scale = radius * 256 / 32767
    first, mat = 0x120, 0x300
    dl_base, V = 0x380, len(BOX)
    chunks = [TRIS[0:4], TRIS[4:8], TRIS[8:12]]
    texs = [1, 2, 1]
    lists = {k: _list(chunks[k], texs[k]) for k in range(3)}
    region = bytearray()
    where = {}
    for k in order:
        where[k] = dl_base + len(region)
        region += lists[k]
    if unreferenced:
        region += _list(TRIS[:2], 1)
    tex_off = dl_base + len(region) + 0x100
    b = bytearray(tex_off + 0x40)
    struct.pack_into(">ff", b, 0, 1.0, radius)
    struct.pack_into(">3f", b, 0x20, *centre)
    struct.pack_into(">3f", b, 0x2C, scale, scale, scale)
    struct.pack_into(">II", b, 0x38, 1, VAT)
    pos_off, nrm_off, tex0 = first, first + 6 * V, first + 12 * V
    struct.pack_into(">I", b, 0xCC, pos_off)
    struct.pack_into(">I", b, 0xD0, nrm_off)
    struct.pack_into(">I", b, 0xDC, tex0)
    struct.pack_into(">4I", b, 0x110, mat, first, dl_base, tex_off)
    for i, p in enumerate(local):
        struct.pack_into(">3h", b, pos_off + 6 * i, *(int(round(c * 256 / scale)) for c in p))
        n = p / np.linalg.norm(p)
        struct.pack_into(">3h", b, nrm_off + 6 * i, *(int(round(c * 16384)) for c in n))
    for i, uv in enumerate(UVS):
        struct.pack_into(">2h", b, tex0 + 4 * i, *uv)
    struct.pack_into(">I", b, mat, 0x38)
    for k in range(3):
        rec = mat + 8 + 0x24 * k
        struct.pack_into(">5I", b, rec, k, 0x0C + k, 0x0D + k, 0x0E + k, 3)
        struct.pack_into(">II", b, rec + 0x1C, where[k], len(lists[k]))
    b[dl_base:dl_base + len(region)] = region
    b[tex_off:tex_off + 9] = b"white.tex"
    return bytes(b)


def _gx_parse(dl: bytes, stride: int) -> list[tuple[int, int]]:
    """Parse a list the way the GPU's command processor does: (command, vertex count) per primitive, NOPs skipped;
    raises on anything else (Dolphin's "Unknown Opcode")."""
    out, p = [], 0
    while p < len(dl):
        c = dl[p]
        if c == 0:
            p += 1
            continue
        if c & 0xF8 not in (0x90, 0x98, 0xA0):
            raise AssertionError(f"unknown opcode {c:#x} at +{p:#x}")
        n = struct.unpack_from(">H", dl, p + 1)[0]
        p += 3 + n * stride
        if p > len(dl):
            raise AssertionError("primitive runs past the list")
        out.append((c, n))
    return out


def _written(template=None):
    template = template or _head()
    rng = np.random.default_rng(1)
    pos = np.asarray(BOX, float) - (2.0, 0.0, 0.0) + rng.normal(0, 0.01, (len(BOX), 3))
    nrm = pos / np.linalg.norm(pos, axis=1, keepdims=True)
    blob = ct.encode_shape(template, pos, nrm, TRIS, "MP_YH_plyrA_atama.shp",
                           chunks=[TRIS[0:5], TRIS[5:9], TRIS[9:12]])
    return template, blob


# ------------------------------------------------------------------------------------------- the reader


def test_out_of_order_material_lists_are_all_found_in_record_order():
    b = _head()
    slots = ct._material_list_slots(b, _u32(b, 0x110), _u32(b, 0x118), _u32(b, 0x11C))
    assert [s for s, _o, _z in slots] == [0x300 + 8 + 0x24 * k + 0x1C for k in range(3)]
    offs = [o for _s, o, _z in slots]
    assert offs[2] < offs[1]                                   # record 2's list before record 1's, like 0x9e0/0xa20
    assert ct.dl_lists_tiled(b)
    assert len(ct.read_shape(b).tris) == 12                   # the out-of-order list is decoded too


def test_dl_whole_rejects_a_pointer_into_the_middle_of_a_list():
    dl = _list(TRIS[:4], 1)
    assert ct.dl_whole(dl, 6)
    assert not ct.dl_whole(dl[1:], 6)                          # starts on the count: 0x00 0x0c then an index
    assert not ct.dl_whole(dl[3 + 6 * 2 + 1:], 6)              # starts inside the vertex stream
    assert not ct.dl_whole(dl[:0x20 - 1], 6) or len(dl) <= 0x20 - 1
    cut = bytes([0x9A]) + struct.pack(">H", 11) + b"\x00\x18" * 9   # 11 vertices declared, 0x40-byte window
    assert not ct.dl_whole(cut, 6)


# ------------------------------------------------------------------------------------------- the writer


def test_written_part_keeps_every_material_pointer_on_whole_lists():
    template, blob = _written()
    assert len(blob) == len(template)
    ct.check_written(template, blob, "head")
    mat, dl_base, end = _u32(blob, 0x110), _u32(blob, 0x118), _u32(blob, 0x11C)
    for slot, _o, _z in ct._material_list_slots(template, mat, dl_base, end):
        off, size = _u32(blob, slot), _u32(blob, slot + 4)
        assert off % 0x20 == 0 and size % 0x20 == 0 and dl_base <= off and off + size <= end
        prims = _gx_parse(blob[off:off + size], 6)
        assert prims and all(c & 7 == VAT for c, _n in prims)  # the stock list's VAT, never VAT 0
    assert len(ct.read_shape(blob).tris) == 12


def test_written_lists_never_overlap_and_no_record_points_at_stale_bytes():
    template, blob = _written()
    mat, dl_base, end = _u32(blob, 0x110), _u32(blob, 0x118), _u32(blob, 0x11C)
    spans = sorted((_u32(blob, s), _u32(blob, s) + _u32(blob, s + 4))
                   for s, _o, _z in ct._material_list_slots(template, mat, dl_base, end))
    assert len(spans) == 3 and spans[0][0] == dl_base
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def test_each_material_samples_a_texel_its_stock_triangles_draw():
    template, blob = _written()
    assert ct.material_uvs(template) == [(128, 64), (40, 200), (128, 64)]
    tex = _u32(blob, 0xDC)
    got = [struct.unpack_from(">2h", blob, tex + 4 * k) for k in range(3)]
    assert got == [(128, 64), (40, 200), (128, 64)] and (0, 0) not in got
    s = ct.read_shape(blob)
    mat, dl_base, end = _u32(blob, 0x110), _u32(blob, 0x118), _u32(blob, 0x11C)
    for k, (_s, off, size) in enumerate(ct._material_list_slots(blob, mat, dl_base, end)):
        assert {c["tex"] for t in ct.decode_dl(blob[off:off + size], ["pos", "nrm", "tex"]) for c in t} == {k}
    assert {tuple(u) for u in s.uv[:3]} == {(0.5, 0.25), (40 / 256, 200 / 256)}


def test_check_written_catches_the_driver_select_freeze():
    """The shipped blob: the third record left at its stock offset after the region was repacked."""
    template, blob = _written()
    slot = 0x300 + 8 + 0x24 * 2 + 0x1C
    stale = bytearray(blob)
    struct.pack_into(">II", stale, slot, _u32(template, slot) + 1, 0x40)   # the ...a01 of the Dolphin warning
    with pytest.raises(ValueError, match="outside the lists|not whole GX|inside another"):
        ct.check_written(template, bytes(stale), "MP_YH_plyrA_sl_atama.shp")
    mid = bytearray(blob)
    off = _u32(blob, 0x300 + 8 + 0x1C)
    struct.pack_into(">II", mid, slot, off + 0x20, 0x20)                    # 32-aligned, but inside a list
    with pytest.raises(ValueError, match="not whole GX|inside another"):
        ct.check_written(template, bytes(mid), "MP_YH_plyrA_atama.shp")


def test_check_written_catches_a_list_on_the_wrong_vat():
    template, blob = _written()
    off = _u32(blob, 0x300 + 8 + 0x1C)
    bad = bytearray(blob)
    bad[off] = (bad[off] & 0xF8) | 0                                         # what the old writer emitted (0x98)
    with pytest.raises(ValueError, match="VAT 0"):
        ct.check_written(template, bytes(bad), "MP_YH_plyrA_mune.shp")


def test_encode_refuses_a_region_with_a_list_no_record_points_at():
    t = _head(unreferenced=True)
    assert not ct.dl_lists_tiled(t)
    with pytest.raises(ValueError, match="do not tile"):
        _written(t)


def test_hidden_blob_keeps_every_out_of_order_record_on_a_whole_list():
    t = _head()
    blob = cs.hidden_blob(t, "MP_YH_plyrA_atamaB.shp")
    ct.check_written(t, blob, "hidden")


# ------------------------------------------------------------------------------------------- the owned disc


def _exists(p) -> bool:
    try:
        return bool(p) and Path(p).is_file()
    except OSError:
        return False


OWNED = _exists(BANK_FILE) or _exists(ISO)


def _owned_bank() -> bytes:
    if _exists(BANK_FILE):
        bank = Path(BANK_FILE).read_bytes()
    else:
        from gbox.gcdisc import GCDisc
        disc = GCDisc(ISO)
        bank = disc.read(ct.BANK)
        disc.f.close()
    assert hashlib.sha256(bank).hexdigest() == ct.BANK_SHA256
    return bank


@pytest.mark.skipif(not OWNED, reason="owned Crazy Taxi GC disc not present")
def test_owned_disc_every_people_part_tiles_and_axels_head_has_its_out_of_order_list():
    bank = _owned_bank()
    shapes = [(n, bank[o:o + s]) for n, o, s in ct.read_bank(bank)
              if s >= 0x120 and struct.unpack_from(">f", bank, o)[0] == 1.0]
    assert sum(not ct.dl_lists_tiled(b) for _n, b in shapes) == 2          # grampus.shp, SetDownBox.shp
    assert all(ct.dl_lists_tiled(b) for n, b in shapes if n.startswith("MP_YH_"))
    by = dict(shapes)
    for n, want in (("MP_YH_plyrA_atama.shp", 5), ("MP_YH_plyrA_sl_atama.shp", 4)):
        b = by[n]
        slots = ct._material_list_slots(b, _u32(b, 0x110), _u32(b, 0x118), _u32(b, 0x11C))
        assert len(slots) == want, n
        assert any(x[1] > y[1] for x, y in zip(slots, slots[1:])), n     # not in address order
    vats = {b[off] & 7 for n, b in shapes if n.startswith("MP_YH_plyr")
            for _s, off, _z in ct._material_list_slots(b, _u32(b, 0x110), _u32(b, 0x118), _u32(b, 0x11C))}
    assert vats == {2, 3}


@pytest.mark.skipif(not OWNED, reason="owned Crazy Taxi GC disc not present")
def test_owned_disc_all_four_drivers_write_lists_the_gpu_can_parse():
    bank = _owned_bank()

    def sphere(r, c, n=8):
        pos = [(0.0, r, 0.0)] + [(r * np.sin(np.pi * i / n) * np.cos(np.pi * j / n), r * np.cos(np.pi * i / n),
                                  r * np.sin(np.pi * i / n) * np.sin(np.pi * j / n))
                                 for i in range(1, n) for j in range(2 * n)] + [(0.0, -r, 0.0)]
        ring = lambda i, j: 1 + (i - 1) * 2 * n + j % (2 * n)
        tris = [(0, ring(1, j + 1), ring(1, j)) for j in range(2 * n)]
        for i in range(1, n - 1):
            for j in range(2 * n):
                tris += [(ring(i, j), ring(i, j + 1), ring(i + 1, j + 1)), (ring(i, j), ring(i + 1, j + 1), ring(i + 1, j))]
        tris += [(len(pos) - 1, ring(n - 1, j), ring(n - 1, j + 1)) for j in range(2 * n)]
        P = np.asarray(pos) + c
        return P, (P - c) / r, tris

    segs = {p: sphere(0.5 + 0.05 * i, (i * 3.0, 10.0, 0.0)) for i, p in enumerate(ct.PARTS)}
    new, stats = cs.swap_people(bank, segs, ("plyrA", "plyrB", "plyrC", "plyrD"))
    assert len(stats) == 208
    for n, o, s in ct.read_bank(bank):
        if n in stats:
            ct.check_written(bank[o:o + s], new[o:o + s], n)                # raises on any bad pointer / VAT
