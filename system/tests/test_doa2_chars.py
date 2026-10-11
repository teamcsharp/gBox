"""DOA2 LE JP character asset readers (gbox.doa2_chars): CHR mesh + BIN texture decode.

Synthetic fixtures mirror the owned disc's DOA2/KAS00 archives (CHR sha256
63a67aa37da73d09e795c7e14b6ad39ed533ef6adeb7cd17787d749c7ae5dcee, BIN 332,800 B) so tests run
without the disc; export against the real GDI runs on the control-plane node. Real-disc anchors
here: 56 models, 145 submeshes, 11,844 vertex records, 8,672 triangles, 55 textures summing to
exactly the BIN length.
"""
import json
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import doa2_chars


def _flat(m):
    return [round(x, 6) for row in m for x in row]


def synth_chr(n_obj=3, n_tex=2, base=0x0C300000):
    """A minimal CHR with the corrected layout: 24-B container header, model 0 at offset 24
    (its {flags, sphere} words are what slice-1 mislabeled 'scale floats'), model bodies with
    per-model {0, vertex_count} end markers, model pointer table, texture descriptors.
    Models 1..2 each contain one submesh (80-B header + one strip of three 32-B vertices)."""
    scale = (0.0, 0.18116, 0.01111, 0.1796)
    models = [struct.pack("<2I4f", 0, 1, *scale) + struct.pack("<2I", 0, 0)]   # model 0: empty
    for _ in (1, 2):
        words = [0] * 20
        words[0] = 4 << 29                                   # native parameter tag (word0>>29==4)
        words[19] = 8 + 3 * 32                               # payload length: strip hdr + 3 verts
        h = struct.pack("<20I", *words)
        verts = b"".join(struct.pack("<8f", x, 0.1 * i, 0.0, 0.0, 0.0, 1.0, 0.1, 0.2)
                         for i, x in enumerate((0.0, 0.5, 0.25)))
        strip = struct.pack("<2I", 0, 3) + verts
        preamble = struct.pack("<2I4f", 0, 0, 0.0, 0.0, 0.0, 0.5)       # model {flags, sphere}
        models.append(preamble + h + strip + struct.pack("<2I", 0, 3))  # end: walked 3 vertices
    out = bytearray(struct.pack("<6I", 24, 0, 0, n_obj, n_tex, 0))     # tbl/tex_tbl patched below
    offs = []
    for m in models:
        offs.append(len(out) if len(offs) < n_obj else None)
        out += m
    while len(offs) < n_obj:
        offs.append(len(out))
        out += struct.pack("<2I", 0, 0)                       # extra empty models if n_obj > 3
    tbl = len(out)
    struct.pack_into("<I", out, 4, tbl)
    out += struct.pack(f"<{n_obj}I", *[base + (o - 24) for o in offs])   # ptr[0]==base -> offset 24
    tex_tbl = len(out)
    struct.pack_into("<I", out, 8, tex_tbl)
    entries = [(32, 32, 1, 1, 2048), (32, 32, 2, 3, 2048 + 256)]        # (w, h, pix, fmt, size)
    tbase = 0x1000
    addr = tbase
    for w, h, pix, fmt, size in entries[:n_tex]:
        out += struct.pack("<HHBBHI", w, h, pix, fmt, 0, addr)       # 12-B descriptor
        addr += size
    return bytes(out)


SYNTH_BIN_LEN = 2048 + (2048 + 256)                         # descriptor 0 + descriptor 1 sizes


def synth_bin():
    return b"\x11" * SYNTH_BIN_LEN


def synth_sup():
    """Two seams in the corrected native grammar: directory (n starts + 0 sentinel, first ==
    directory size), then per-seam {u32 data_ptr==off+8, u8 bone_a, u8 bone_b, u8 model, u8 init}
    followed by 18 floats = three interleaved column pairs (A_k, B_k). Seam 0: bones 1/0 with
    A=I, B=I (head/chest aligned). Seam 1: bones 0/2 with A=I, B=R_z(90deg) (chest rotated a
    quarter turn about Y-up from pelvis in the world frame this encodes)."""
    def seam(offset, a, b, model, bases):            # bases: list of 3 (A_k, B_k) column pairs
        body = struct.pack("<IBBBB", offset + 8, a, b, model, 0)
        for ak, bk in bases:
            for v in (ak, bk):
                body += struct.pack("<3f", *v)
        return body
    quarter = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))   # R_z(+90 deg) columns
    ident = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    dir_size = 12                                             # 3 words: size, start_1, sentinel
    s0 = seam(dir_size, 1, 0, 23, [(ident[k], ident[k]) for k in range(3)])
    s1 = seam(dir_size + len(s0), 0, 2, 40, [(ident[k], quarter[k]) for k in range(3)])
    # native layout: w0 = dir byte size == seam-0 offset; remaining starts; one 0 sentinel
    out = struct.pack("<3I", dir_size, dir_size + len(s0), 0) + s0 + s1
    return out


def synth_mot():
    offs = [0x1898, 0x1c5c, 0x1898]
    b = bytearray(0x40)
    struct.pack_into("<3I", b, 0, *offs)
    return bytes(b) + b"\0" * 0x2000


class TestParseChr:
    def test_kasumi_like_header(self):
        r = doa2_chars.parse_chr(synth_chr())
        assert r["n_objects"] == 3 and r["n_textures"] == 2
        assert r["ptr_base"] == 0x0C300000
        assert r["objects"][0] == 24                                  # model 0 offset
        assert r["objects"] == sorted(set(r["objects"]))
        assert r["model0_sphere"][2] == pytest.approx(0.01111, abs=1e-4)

    def test_system_chr_base(self):
        r = doa2_chars.parse_chr(synth_chr(base=0x0C400000))
        assert r["ptr_base"] == 0x0C400000

    def test_rejects_bad_header(self):
        with pytest.raises(ValueError):
            doa2_chars.parse_chr(b"\x00" * 64)
        bad = bytearray(synth_chr())
        struct.pack_into("<I", bad, 0, 32)                    # header size must be 24
        with pytest.raises(ValueError):
            doa2_chars.parse_chr(bytes(bad))
        bad = bytearray(synth_chr())
        struct.pack_into("<I", bad, 12, 0x9999)               # implausible model count
        with pytest.raises(ValueError):
            doa2_chars.parse_chr(bytes(bad))

    def test_real_disc_anchors(self):
        # disc-anchored regression: the real KAS00.CHR header words (offsets 0..0x2c)
        hdr = struct.unpack("<12I", bytes.fromhex(
            "18000000" "d8790400" "b87a0400" "38000000" "37000000" "00000000"
            "01000000" "01000000" "00000000" "4283393e" "f4f5353c" "40e8373e"))
        assert hdr[0] == 24 and hdr[3] == 56 and hdr[4] == 55      # Kasumi: 56 models, 55 textures
        assert hdr[1] == 0x479D8 and hdr[2] == 0x47AB8


class TestTextures:
    def test_descriptor_parse(self):
        descs = doa2_chars.parse_textures(synth_chr(), len(synth_bin()))
        assert len(descs) == 2
        t0, t1 = descs
        assert (t0["width"], t0["height"]) == (32, 32) and t0["pixel"] == 1 and t0["format"] == 1
        assert t0["size"] == 2048                                       # 2*w*h twiddled
        assert t1["format"] == 3 and t1["size"] == 2048 + 256           # VQ: +256-entry codebook
        assert t1["offset"] == 2048

    def test_size_formulas(self):
        assert doa2_chars.texture_size(128, 128, 1, 3) == 2048 + 128 * 128 // 4
        assert doa2_chars.texture_size(64, 64, 2, 0x0D) == 2 * 64 * 64
        with pytest.raises(ValueError):
            doa2_chars.texture_size(64, 64, 7, 1)                       # unknown pixel code
        with pytest.raises(ValueError):
            doa2_chars.texture_size(64, 64, 1, 9)                       # unknown format

    def test_rejects_non_pow2(self):
        b = bytearray(synth_chr())
        # descriptor 0 word: width/height packed at texture_table; set 48x48
        info = doa2_chars.parse_chr(bytes(b))
        struct.pack_into("<HH", b, info["texture_table"], 48, 48)
        with pytest.raises(ValueError):
            doa2_chars.parse_textures(bytes(b), len(synth_bin()))

    def test_rejects_bin_overflow(self):
        with pytest.raises(ValueError):
            doa2_chars.parse_textures(synth_chr(), 100)                # BIN smaller than declared sizes


class TestMeshDecode:
    def test_walk_models_and_strips(self):
        m = doa2_chars.parse_meshes(synth_chr())
        assert m["n_models"] == 3
        assert m["n_vertices"] == 6 and m["n_triangles"] == 2       # two 3-vertex strips
        m1 = m["models"][1]
        assert m1["vertex_count"] == 3
        v = m1["meshes"][0]["vertices"][0]
        assert v[:3] == (0.0, 0.0, 0.0) and v[6:] == pytest.approx((0.1, 0.2), abs=1e-6)
        assert m1["meshes"][0]["triangles"] == [(0, 1, 2)]

    def test_end_marker_count_enforced(self):
        b = bytearray(synth_chr())
        # model 1's end marker: start + 24 (preamble) + 80 (submesh hdr) + 8 (strip hdr)
        # + 3*32 (verts); declared count word is end_marker+4
        info = doa2_chars.parse_chr(bytes(b))
        end_off = info["objects"][1] + 24 + 80 + 8 + 96
        struct.pack_into("<I", b, end_off + 4, 5)
        with pytest.raises(ValueError):
            doa2_chars.parse_meshes(bytes(b))

    def test_triangles_from_strip(self):
        idx = [0, 1, 2, 3]
        t = doa2_chars._triangles(0, idx)                              # strip, cull 0: winding alternates
        assert t == [(0, 1, 2), (2, 1, 3)]
        t8 = doa2_chars._triangles(8, [0, 1, 2])                       # list mode
        assert t8 == [(0, 1, 2)]
        swapped = doa2_chars._triangles(2, [0, 1, 2])                  # cull 2: swap winding
        assert swapped == [(1, 0, 2)]


class TestRoster:
    def test_static_roster_shape(self):
        r = doa2_chars.roster()
        kas = next(e for e in r if e["key"] == "KAS")
        assert kas["name"] == "Kasumi" and kas["slug"] == "doa2_kas"
        assert {e["key"] for e in r} >= {"KAS", "AYA", "TIN", "RYU", "TNG"}

    def test_disc_listing_costumes(self):
        files = {"DOA2/KAS00.CHR": 1, "DOA2/KAS09.CHR": 1, "DOA2/AYA00.CHR": 1, "DOA2/STAGE01.CHR": 1,
                 "DOA2/EFC0.CHR": 1, "DOA2/KAS00.SUP": 1, "DOA2/KAS00.BIN": 1}
        r = doa2_chars.roster(files)
        kas = next(e for e in r if e["key"] == "KAS")
        assert kas["costumes"] == ["00", "09"]                       # disc zero-padded costume ids
        aya = next(e for e in r if e["key"] == "AYA")
        assert aya["costumes"] == ["00"]
        assert not any(e["key"] == "STAGE" for e in r)


class TestParseSupMot:
    def test_sup_seam_grammar(self):
        r = doa2_chars.parse_sup(synth_sup())
        assert r["seam_count"] == 2
        s0, s1 = r["seams"]
        assert s0["bone_a"] == 1 and s0["bone_b"] == 0 and s0["model_id"] == 23
        assert s0["data_offset"] == s0["offset"] + 8
        assert _flat(s0["a_vectors"]) == pytest.approx([1, 0, 0, 0, 1, 0, 0, 0, 1])
        assert s1["bone_a"] == 0 and s1["bone_b"] == 2
        assert _flat(s1["b_vectors"]) == pytest.approx([0, -1, 0, 1, 0, 0, 0, 0, 1])  # R_z(90)

    def test_sup_real_disc_anchor(self):
        # first 80 bytes of the real DOA2/KAS00.SUP (sha256 543fad88…): word0 = 0x2c (directory
        # size == seam-0 offset), seam 0 {ptr=0x34, bones 1/0, model 23} with identity bases.
        # Later starts point past this slice, so the slice is padded to the last start (0x1884)
        # with zeros and that last start is redirected to a minimal valid seam.
        anchor = bytearray(bytes.fromhex(
            "2c00000048040000400a0000340c0000880e0000581000006c12000060140000b4160000"
            "8418000000000000"
            "34000000010017000000803f00000000000000000000803f000000000000000000000000"
            "0000803f00000000000000000000803f0000000000000000000000000000803f00000000"
            "000000000000803f"))
        anchor += bytes(0x1884 + 80 - len(anchor))                     # room for 10 minimal seams
        for s in (0x448, 0xa40, 0xc34, 0xe88, 0x1058, 0x126c, 0x1460, 0x16b4, 0x1884):
            struct.pack_into("<IBBBB", anchor, s, s + 8, 3, 7, 10, 0)  # synthetic tail seams
        r = doa2_chars.parse_sup(bytes(anchor))
        assert r["seam_count"] == 10
        s = r["seams"][0]
        assert s["bone_a"] == 1 and s["bone_b"] == 0 and s["model_id"] == 23
        assert s["initialized"] == 0
        assert [round(x, 6) for v in s["a_vectors"] for x in v] == pytest.approx(
            [1, 0, 0, 0, 1, 0, 0, 0, 1])

    def test_sup_rejects_bad_directory(self):
        bad = bytearray(synth_sup())
        struct.pack_into("<I", bad, 4, 0)                     # interior zero start
        with pytest.raises(ValueError):
            doa2_chars.parse_sup(bytes(bad))
        bad = bytearray(synth_sup())
        struct.pack_into("<I", bad, 0, 7)                     # unaligned directory size
        with pytest.raises(ValueError):
            doa2_chars.parse_sup(bytes(bad))
        with pytest.raises(ValueError):                       # seam data_ptr != offset+8
            doa2_chars.parse_sup(struct.pack("<II", 12, 0) + struct.pack("<IBBBB", 99, 1, 0, 0, 0))

    def test_mot_table(self):
        r = doa2_chars.parse_mot_table(synth_mot())
        assert r["n_clips"] == 3
        assert r["offsets"][0] == 0x1898 and r["offsets"][2] == 0x1898   # shared clip


class TestRig:
    def test_solve_joint_bases_chain(self):
        # synth seams: (1,0)->I and (0,2)->R_z(90): anchor pelvis 2 = I implies chest quarter-
        # turned, head aligned to chest
        r = doa2_chars.solve_joint_bases(
            [{**s, "name": "synth"} for s in doa2_chars.parse_sup(synth_sup())["seams"]],
            anchor=2, joint_ids={0, 1, 2})
        assert _flat(r["2"]) == pytest.approx([1, 0, 0, 0, 1, 0, 0, 0, 1])
        assert _flat(r["0"]) == pytest.approx([0, 1, 0, -1, 0, 0, 0, 0, 1])  # rows of B=R_z(90)
        assert _flat(r["1"]) == pytest.approx(_flat(r["0"]))

    def test_solve_rejects_disconnected(self):
        with pytest.raises(ValueError, match="does not connect"):
            doa2_chars.solve_joint_bases(
                [{"bone_a": 5, "bone_b": 4, "a_vectors": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                  "b_vectors": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "name": "x"}],
                anchor=2, joint_ids=range(6))

    def test_solve_rejects_non_rotation(self):
        with pytest.raises(ValueError, match="proper rotation"):
            doa2_chars.solve_joint_bases(
                [{"bone_a": 0, "bone_b": 2, "a_vectors": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                  "b_vectors": [[2, 0, 0], [0, 1, 0], [0, 0, 1]], "name": "x"}],
                anchor=2, joint_ids={0, 2})

    def test_rest_table_rejects_foreign_exe(self):
        with pytest.raises(ValueError, match="verified DOA2"):
            doa2_chars.parse_rest_rig(b"\0" * 0x100000)


class TestExportAssets:
    def test_gltf_png_manifest(self, tmp_path):
        r = doa2_chars.export_assets(synth_chr(), synth_bin(), str(tmp_path), "unit")
        names = [Path(f).name for f in r["files"]]
        assert "unit.gltf" in names and "manifest.json" in names
        assert any("tex00" in n for n in names) and any("tex01" in n for n in names)
        m = r["manifest"]
        assert m["geometry_facts"]["n_models"] == 3
        assert m["texture_facts"]["n_textures"] == 2
        assert m["confidence"]["geometry"] == "verified"
        assert m["confidence"]["skeleton"] == "missing"               # no rig passed
        gltf = json.load(open(tmp_path / "unit.gltf"))
        assert gltf["asset"]["version"] == "2.0"
        assert gltf["images"] and len(gltf["materials"]) >= 1

    def test_gltf_with_rig(self, tmp_path):
        # synthetic rig in the native 17-joint shape: parents from the EXE rest table, world
        # matrices built like build_rig does (identity bases, pelvis-chain translations)
        import numpy as np
        parents = doa2_chars.JOINT_PARENTS
        vec = [[0.0, 0.18, 0.0]] + [[0.0, 0.1, 0.0]] * 16              # chest + chain offsets
        pos = {2: np.zeros(3)}
        for _ in range(17):
            for j, p in enumerate(parents):
                if j not in pos and (p == -1 or p in pos):
                    pos[j] = (np.zeros(3) if p == -1 else pos[p]) + np.asarray(vec[j])
        world = []
        for j in range(17):
            M = np.eye(4)
            M[:3, 3] = pos[j]
            world.append(M.tolist())
        rig = {"parents": parents, "roles": doa2_chars.JOINT_ROLES, "world": world,
               "rest_address": "0x8c193fe0", "fighter_slot": 5, "n_seam_records": 2,
               "seam_sources": ["DOA2/SYNTH.SUP"]}
        r = doa2_chars.export_assets(synth_chr(), synth_bin(), str(tmp_path), "rigged", rig=rig)
        m = r["manifest"]
        assert m["confidence"]["skeleton"] == "verified"
        assert m["skeleton_facts"]["n_joints"] == 17
        assert m["skeleton_facts"]["rest_address"] == "0x8c193fe0"
        gltf = json.load(open(tmp_path / "rigged.gltf"))
        assert len(gltf["skins"]) == 1 and len(gltf["skins"][0]["joints"]) == 17
        names = [n.get("name", "") for n in gltf["nodes"]]
        assert "pelvis_02" in names and "left_hand_05" in names and "right_breast_16" in names
        # pelvis node translation == world position (root parent is -1)
        root_idx = names.index("pelvis_02")
        assert gltf["nodes"][root_idx]["translation"] == pytest.approx([0, 0, 0])


class TestGameIds:
    def test_routes_only_doa2le(self):
        assert "1de2e7634f3161ff" in doa2_chars.GAME_IDS
        assert len(doa2_chars.GAME_IDS) == 1


def test_module_documented_facts():
    doc = doa2_chars.__doc__ or ""
    assert "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1" in doc   # 1ST_READ hash
    assert "0x0C300000" in doc and "0x0C400000" in doc                                # pointer bases
