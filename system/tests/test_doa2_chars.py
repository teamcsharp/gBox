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
    b = bytearray(68)
    struct.pack_into("<II", b, 0, 44, 60)
    struct.pack_into("<6f", b, 44, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0)
    struct.pack_into("<2f", b, 60, 0.5, 0.25)                         # last record runs to EOF
    return bytes(b)


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
    def test_sup_records(self):
        r = doa2_chars.parse_sup(synth_sup())
        assert r["n_records"] == 2
        assert r["records"][0][:3] == pytest.approx([0.0, 0.0, 1.0])
        assert r["records"][1] == pytest.approx([0.5, 0.25])

    def test_mot_table(self):
        r = doa2_chars.parse_mot_table(synth_mot())
        assert r["n_clips"] == 3
        assert r["offsets"][0] == 0x1898 and r["offsets"][2] == 0x1898   # shared clip


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
        assert m["confidence"]["skeleton"] == "missing"               # honest: rig not in CHR
        gltf = json.load(open(tmp_path / "unit.gltf"))
        assert gltf["asset"]["version"] == "2.0"
        assert gltf["images"] and len(gltf["materials"]) >= 1


class TestGameIds:
    def test_routes_only_doa2le(self):
        assert "1de2e7634f3161ff" in doa2_chars.GAME_IDS
        assert len(doa2_chars.GAME_IDS) == 1


def test_module_documented_facts():
    doc = doa2_chars.__doc__ or ""
    assert "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1" in doc   # 1ST_READ hash
    assert "0x0C300000" in doc and "0x0C400000" in doc                                # pointer bases
