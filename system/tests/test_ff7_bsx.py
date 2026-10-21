"""Focused tests for the FF7 special-scene cutscene writer (gbox.ff7_swap BSX support).

The synthetic tests build a minimal BSX (one Cloud model with the 22-bone party skeleton, 15 body parts + the
sword, one other actor, one animation) and verify the patch preserves everything it promises: the sword and the
other actor byte-for-byte, the donor geometry in every body part, consistent absolute pointers and a clean LZS
roundtrip. The disc-gated test runs against the operator's Disc 1 image when its cache is present and pins the
special-scene Cloud inventory (10 BSX files / 12 models on the USA build).
"""
import struct

import pytest

from gbox import ff7_swap as S

CLOUD_LENS = [0, 0, -53, -158, -53, -152, -70, -83, -140, -53, -152, -70, -83, -140, 0, -60, -161, -235, 0, -60,
              -161, -235]
CLOUD_PARS = [255, 0, 1, 2, 1, 4, 5, 6, 7, 1, 9, 10, 11, 12, 0, 14, 15, 16, 0, 18, 19, 20]
BODY = [(1, 14), (2, 32), (3, 90), (6, 16), (7, 16), (8, 8), (11, 16), (12, 16), (13, 8), (15, 10), (16, 21),
        (17, 10), (19, 10), (20, 21), (21, 10)]          # (bone, vertex count) of the original CLOUD.BCX parts


def _part_block(nv: int) -> bytes:
    return b"\0\0\0\0" + bytes(8 * nv)


def _part_table(part_id: int, bone: int, nv: int, ovx: int) -> bytes:
    return struct.pack("<12B2B5H2I", 1, bone, nv, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                       4 + 8 * nv, 4 + 8 * nv, 4 + 8 * nv, 4 + 8 * nv, 0, ovx | 0x80000000, 0)


def _anim_table(off_data: int) -> bytes:
    return struct.pack("<HBBBBHHHI", 1, 22, 0, 0, 0, 0, 0, 0, off_data | 0x80000000)


def _model_record(mid: int, off_skel: int, nb: int, np: int, na: int) -> bytes:
    return struct.pack("<HHI4B3h6B3h6B3h6B", mid, 512, off_skel,
                       0, 0, 0, 0,               # global light + unknown
                       0, 0, 0,                  # color1
                       0, 0, 0, 0, 0, nb,        # bone indices, rgb, bone count
                       0, 0, 0,                  # color2
                       0, 0, 0, 0, 0, np,        # part indices, rgb, part count
                       0, 0, 0,                  # color3
                       0, 0, 0, 0, 0, na)        # animation indices, rgb, animation count


def _synthetic_bsx() -> bytes:
    """One Cloud model (id 0, 22 bones, 15 body parts + sword, 1 animation), one other actor (id 17, 1 part)."""
    body_blocks = [_part_block(nv) for _bone, nv in BODY]
    sword_block = _part_block(43)
    other_block = _part_block(9)
    cloud_blocks = body_blocks + [sword_block]
    ovx, pos = [], 8
    for blk in cloud_blocks + [other_block]:
        ovx.append(pos)
        pos += len(blk)
    anim_off = pos
    anim_blob = bytes(4 + 22 * 8)                        # one frame, all-static channels
    off_models = anim_off + len(anim_blob)
    cloud_skel = off_models + 16 + 48 * 2
    cloud_bones = b"".join(struct.pack("<hBB", ln, par, 1 if par in (1, 2, 3, 6, 7, 8, 11, 12, 13, 15, 16, 17, 19,
                                                                      20, 21) else 0)
                           for ln, par in zip(CLOUD_LENS, CLOUD_PARS))
    cloud_tables = cloud_bones
    for i, (bone, nv) in enumerate(BODY):
        cloud_tables += _part_table(i, bone, nv, ovx[i])
    cloud_tables += _part_table(15, 13, 43, ovx[15])     # the sword, on the right hand
    cloud_tables += _anim_table(anim_off)
    other_skel = cloud_skel + len(cloud_tables)
    other_tables = _part_table(0, 1, 9, ovx[16])
    header = struct.pack("<II", 0, 0)
    body = bytearray(header)
    body += b"".join(cloud_blocks) + other_block + anim_blob
    models = struct.pack("<IIII", off_models | 0x80000000, 2, 0, 0)
    models += _model_record(0, cloud_skel - (off_models + 16 + 48 * 0), 22, 16, 1)
    models += _model_record(17, other_skel - (off_models + 16 + 48 * 1), 0, 1, 0)
    models += cloud_tables + other_tables
    models += bytes(20)                                  # empty texture section (the BSX tail)
    body += models
    struct.pack_into("<II", body, 0, len(body), off_models)
    return bytes(body)


def _synthetic_donor() -> dict:
    raw, parts, pos = bytearray(), [], 0
    for _bone, _nv in BODY:
        parts.append({"bone": _bone, "nv": 1, "ntc": 0, "counts": {k: 0 for k, *_ in S.BSX_POLYS},
                      "flags": 0, "controls": 0, "opoly": 12, "otc": 12, "ofl": 12, "octl": 12, "buffer": 0,
                      "ovx": pos})
        raw += _part_block(1)
        pos += 12
    return {"raw": bytes(raw), "parts": parts}


def test_bsx_cloud_patch_preserves_sword_and_other_models():
    u = _synthetic_bsx()
    orig_fm = {"parts": [{"bone": b, "nv": nv} for b, nv in BODY]}
    donor = _synthetic_donor()
    new_u, rep = S.patch_bsx_cloud(u, orig_fm, donor)
    assert rep["body_parts_replaced"] == 15
    assert rep["parts_kept"] == 2                       # the sword + the other actor's part
    models = S.bsx_models(new_u)
    assert len(models) == 2
    cloud, other = models[0], models[1]
    assert cloud["nb"] == 22 and cloud["np"] == 16 and cloud["na"] == 1
    # every body part now carries the donor block, the sword and the other actor are byte-identical
    for pi in range(15):
        q = cloud["skel"] + 4 * cloud["nb"] + 32 * pi
        f = struct.unpack_from("<12B2B5H2I", new_u, q)
        ovx = f[19] & 0x7FFFFFFF
        assert f[2] == 1, f"body part {pi} not replaced"
        assert new_u[ovx:ovx + 12] == _part_block(1)
    sq = cloud["skel"] + 4 * cloud["nb"] + 32 * 15
    f = struct.unpack_from("<12B2B5H2I", new_u, sq)
    assert f[2] == 43 and new_u[f[19] & 0x7FFFFFFF:(f[19] & 0x7FFFFFFF) + 4 + 8 * 43] == _part_block(43)
    oq = other["skel"] + 32 * 0
    f = struct.unpack_from("<12B2B5H2I", new_u, oq)
    assert f[2] == 9 and new_u[f[19] & 0x7FFFFFFF:(f[19] & 0x7FFFFFFF) + 4 + 8 * 9] == _part_block(9)
    # header / models-section pointers are consistent
    size, off_models = struct.unpack_from("<II", new_u, 0)
    assert size == len(new_u)
    assert struct.unpack_from("<I", new_u, off_models)[0] & 0x7FFFFFFF == off_models
    # the animation data offset was relocated and the animation still parses
    aq = cloud["skel"] + 4 * cloud["nb"] + 32 * cloud["np"]
    assert struct.unpack_from("<I", new_u, aq + 12)[0] & 0x7FFFFFFF < off_models


def test_bsx_cloud_patch_roundtrip_through_lzs():
    u = _synthetic_bsx()
    new_u, _rep = S.patch_bsx_cloud(u, {"parts": [{"bone": b, "nv": nv} for b, nv in BODY]}, _synthetic_donor())
    from gbox import ff7_models as F
    comp = S.lzs_encode(new_u, thorough=True)
    assert F.lzs(comp) == new_u
    comp0 = S.lzs_encode(new_u)
    assert F.lzs(comp0) == new_u


def test_bsx_cloud_patch_rejects_partial_variants():
    u = _synthetic_bsx()
    orig_fm = {"parts": [{"bone": b, "nv": nv} for b, nv in BODY[:14]]}      # one body part missing
    with pytest.raises(ValueError):
        S.patch_bsx_cloud(u, orig_fm, _synthetic_donor())


def test_bsx_cloud_patch_rejects_shared_actor_blocks():
    u = bytearray(_synthetic_bsx())
    # Make the other actor own Cloud's first body block (a shared scene actor): the part must not be replaced.
    off_models = struct.unpack_from("<I", u, 4)[0]
    models = S.bsx_models(u)
    cloud_q = models[0]["skel"] + 4 * 22 + 32 * 0
    ovx = struct.unpack_from("<12B2B5H2I", u, cloud_q)[19] & 0x7FFFFFFF
    other_q = models[1]["skel"] + 32 * 0
    struct.pack_into("<I", u, other_q + 24, ovx | 0x80000000)
    new_u, rep = S.patch_bsx_cloud(u, {"parts": [{"bone": b, "nv": nv} for b, nv in BODY]}, _synthetic_donor())
    assert rep["body_parts_replaced"] == 14                # all but the shared one
    cloud_q = S.bsx_models(new_u)[0]["skel"] + 4 * 22 + 32 * 0
    f = struct.unpack_from("<12B2B5H2I", new_u, cloud_q)
    assert f[2] == 14                                      # the shared part kept its own mesh


DISC = "/home/ehm_eckx/gBox_alt/gbox-cache/modbase/6703ee6f461a2ea5/Final Fantasy VII (USA) (Disc 1).bin"
MODDED = "/home/ehm_eckx/gBox_alt/gbox-cache/mods/6703ee6f461a2ea5/ff7_mario_v4_field_probe_2/FF7 Mario field detail.bin"


@pytest.mark.skipif(__import__("os").path.exists(DISC) is False or
                    __import__("os").path.exists(MODDED) is False,
                    reason="operator's Disc 1 cache not present")
def test_bsx_special_scene_inventory_on_the_usa_disc():
    """The USA Disc 1 carries Cloud's own mesh in 10 special-scene BSX files (12 models: BLACKBG4 has three).
    Every one of them must patch within its stored-file budget with the thorough LZS encoder."""
    from gbox import ff7_models as F
    from gbox import psxdisc
    base = psxdisc.RawBin(DISC, writable=False)
    mod = psxdisc.RawBin(MODDED, writable=False)
    orig_fm = F.read_field_model(base.read("FIELD/CLOUD.BCX"))
    donor_fm = F.read_field_model(mod.read("FIELD/CLOUD.BCX"))
    patched, models = 0, 0
    for name in sorted(base.files):
        if not name.upper().endswith(".BSX"):
            continue
        u = F.lzs(base.read(name))
        if not any(m["id"] == 0 and m["nb"] == 22 for m in S.bsx_models(u)):
            continue
        try:
            new_u, rep = S.patch_bsx_cloud(u, orig_fm, donor_fm)
        except ValueError:
            continue                                     # disguise/partial variants are left alone by design
        comp = S.lzs_encode(new_u, thorough=True)
        assert F.lzs(comp) == new_u
        assert len(comp) <= base.files[name][1], f"{name}: compressed {len(comp)} > budget {base.files[name][1]}"
        patched += 1
        models += rep["cloud_models"]
    assert patched == 10, f"expected the 10 special-scene BSX files, got {patched}"
    assert models == 13, f"expected 13 Cloud models, got {models}"
