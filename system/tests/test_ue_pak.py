"""ue_pak / ue_asset: synthetic .pak archives (v1-v11 layouts) and cooked package headers built in the tests."""
import struct
import sys
from pathlib import Path

import pytest

import ue_synth as S
from gbox import ue_asset, ue_pak

FILES = {"Game/Content/A.uasset": b"A" * 300, "Game/Content/Sub/B.uexp": bytes(range(256)) * 9,
         "Game/Config/X.ini": b"[x]\n"}


def _write(tmp_path: Path, blob: bytes, name="t.pak") -> Path:
    p = tmp_path / name
    p.write_bytes(blob)
    return p


@pytest.mark.parametrize("version,footer", [(1, ""), (2, ""), (3, ""), (4, ""), (5, ""), (6, ""), (7, ""),
                                            (8, "4.22"), (8, ""), (9, ""), (10, ""), (11, "")])
@pytest.mark.parametrize("method", ["None", "Zlib", "Gzip"])
def test_every_pak_version_lists_and_reads(tmp_path, version, footer, method):
    if version < 3 and method != "None":
        pytest.skip("compression arrived in pak v3")
    p = _write(tmp_path, S.build_pak(FILES, version, method, footer=footer, block_size=0x800))
    with ue_pak.PakFile(p) as pf:
        assert pf.version == version
        assert pf.index_hash_ok
        assert sorted(pf.entries) == sorted(FILES)
        for name, data in FILES.items():
            assert pf.read(name) == data
            assert pf.entries[name].method == method
        s = pf.summary()
        assert s["entries"] == 3 and s["names_available"]


def test_v8_footer_sizes_are_told_apart(tmp_path):
    a = ue_pak.PakFile(_write(tmp_path, S.build_pak(FILES, 8, "Zlib", footer="4.22"), "a.pak"))
    b = ue_pak.PakFile(_write(tmp_path, S.build_pak(FILES, 8, "Zlib"), "b.pak"))
    assert a.info.footer_size == 189 and a.info.method_u8
    assert b.info.footer_size == 221 and not b.info.method_u8
    a.close(); b.close()


def test_multi_block_zlib_entry(tmp_path):
    big = bytes((i * 7) % 251 for i in range(50000))
    p = _write(tmp_path, S.build_pak({"Game/Big.uexp": big}, 11, "Zlib", block_size=0x1000))
    with ue_pak.PakFile(p) as pf:
        e = pf.entries["Game/Big.uexp"]
        assert len(e.blocks) == 13 and e.block_size == 0x1000
        assert pf.read(e) == big


def test_v11_non_encoded_entry_list(tmp_path):
    p = _write(tmp_path, S.build_pak(FILES, 11, "Zlib", listed=("Game/Config/X.ini",)))
    with ue_pak.PakFile(p) as pf:
        assert pf.read("Game/Config/X.ini") == b"[x]\n"
        assert pf.read("Game/Content/A.uasset") == b"A" * 300


def test_v11_without_full_directory_index_lists_by_hash(tmp_path):
    p = _write(tmp_path, S.build_pak(FILES, 11, full_dir=False))
    with ue_pak.PakFile(p) as pf:
        assert not pf.names_available
        assert len(pf.entries) == 3 and all(n.startswith("#hash/") for n in pf.entries)
        assert sorted(pf.read(e) for e in pf.entries.values()) == sorted(FILES.values())


def test_mount_point_is_applied(tmp_path):
    p = _write(tmp_path, S.build_pak({"Content/A.uasset": b"x"}, 11, mount="../../../MyGame/"))
    with ue_pak.PakFile(p) as pf:
        assert list(pf.entries) == ["MyGame/Content/A.uasset"]


@pytest.mark.parametrize("version", [4, 7, 11])
def test_encrypted_index_stops_with_key_needed(tmp_path, version):
    p = _write(tmp_path, S.build_pak(FILES, version, encrypt_index=True))
    with pytest.raises(ue_pak.PakEncrypted, match="AES"):
        ue_pak.PakFile(p)
    pf, s = ue_pak.open_pak(p)
    assert pf is None and s["status"] == "encrypted"


@pytest.mark.parametrize("version", [7, 11])
def test_encrypted_entry_is_listed_but_not_read(tmp_path, version):
    p = _write(tmp_path, S.build_pak(FILES, version, "Zlib", encrypted=("Game/Content/A.uasset",)))
    with ue_pak.PakFile(p) as pf:
        assert pf.entries["Game/Content/A.uasset"].encrypted
        assert pf.summary()["encrypted_entries"] == 1
        with pytest.raises(ue_pak.PakEncrypted):
            pf.read("Game/Content/A.uasset")
        assert pf.read("Game/Config/X.ini") == b"[x]\n"


@pytest.mark.parametrize("version", [5, 11])
def test_oodle_without_the_games_dll_is_reported_unsupported(tmp_path, version):
    gd = tmp_path / "game"
    gd.mkdir()
    p = _write(gd, S.build_pak(FILES, version, "Oodle"))
    pf, s = ue_pak.open_pak(p, gd)
    assert s["status"] == "ok" and s["compression_methods"] == ["Oodle"]
    assert s["oodle_dll"] is None and "no oo2core" in s["oodle_error"]
    with pytest.raises(ue_pak.PakUnsupported, match="Oodle"):
        pf.read("Game/Config/X.ini")
    pf.close()


def test_oodle_dll_is_only_taken_from_the_game_folder(tmp_path):
    gd = tmp_path / "game"
    (gd / "MyGame" / "Binaries" / "Win64").mkdir(parents=True)
    dll = gd / "MyGame" / "Binaries" / "Win64" / "oo2core_9_win64.dll"
    dll.write_bytes(b"MZ")
    assert ue_pak.Oodle.find(gd) == dll
    outside = tmp_path / "oo2core_9_win64.dll"
    outside.write_bytes(b"MZ")
    with pytest.raises(ue_pak.PakUnsupported):
        ue_pak.Oodle(outside, gd)
    with pytest.raises(ue_pak.PakUnsupported):
        ue_pak.Oodle(gd / "MyGame" / "evil.dll", gd)


def test_not_an_unreal_pak(tmp_path):
    p = _write(tmp_path, b"PK\x03\x04" + b"\0" * 400, "resources.pak")
    pf, s = ue_pak.open_pak(p)
    assert pf is None and s["status"] == "not_unreal"


def test_index_outside_the_file_is_refused(tmp_path):
    blob = bytearray(S.build_pak(FILES, 11))
    # Footer: guid(16) enc(1) magic(4) version(4) index_offset(8) ...
    off = len(blob) - 221 + 16 + 1 + 4 + 4
    struct.pack_into("<q", blob, off, len(blob) * 4)
    with pytest.raises(ue_pak.PakError, match="outside"):
        ue_pak.PakFile(_write(tmp_path, bytes(blob)))


def test_truncated_or_corrupt_index_is_bounds_checked(tmp_path):
    blob = bytearray(S.build_pak(FILES, 7))
    idx_off = struct.unpack_from("<q", blob, len(blob) - 61 + 25)[0]
    mount_len = struct.unpack_from("<i", blob, idx_off)[0]
    struct.pack_into("<i", blob, idx_off + 4 + mount_len, 0x7FFFFFF)     # absurd entry count
    with pytest.raises(ue_pak.PakError, match="implausible count"):
        ue_pak.PakFile(_write(tmp_path, bytes(blob)))
    r = ue_pak.Reader(b"\x10\x00\x00\x00ab")
    with pytest.raises(ue_pak.PakError):
        r.fstring()


def test_entry_header_disagreeing_with_index_is_refused(tmp_path):
    blob = bytearray(S.build_pak({"Game/A.uasset": b"x" * 64}, 7))
    struct.pack_into("<q", blob, 8, 63)                 # inline header size
    with ue_pak.PakFile(_write(tmp_path, bytes(blob))) as pf:
        with pytest.raises(ue_pak.PakError, match="disagrees"):
            pf.read("Game/A.uasset")


@pytest.mark.parametrize("bad", ["../evil.uasset", "/abs.uasset", "C:/x.uasset", "a/../../b", ""])
def test_safe_out_path_refuses_escapes(tmp_path, bad):
    with pytest.raises(ue_pak.PakError):
        ue_pak.safe_out_path(tmp_path, bad)


def test_safe_out_path_keeps_the_archive_layout(tmp_path):
    assert ue_pak.safe_out_path(tmp_path, "Game/Content/A.uasset") == (tmp_path / "Game/Content/A.uasset").resolve()


def test_patch_paks_mount_last():
    names = [Path("pakchunk0-WindowsNoEditor_P.pak"), Path("pakchunk0-WindowsNoEditor.pak"),
             Path("pakchunk0-WindowsNoEditor_0_P.pak"), Path("pakchunk0-WindowsNoEditor_2_P.pak")]
    order = [p.name for p in sorted(names, key=ue_pak.pak_priority)]
    assert order[0] == "pakchunk0-WindowsNoEditor.pak"
    assert order[-1] == "pakchunk0-WindowsNoEditor_2_P.pak"


def test_iostore_containers_are_listed(tmp_path):
    (tmp_path / "Paks").mkdir()
    (tmp_path / "Paks" / "global.utoc").write_bytes(S.build_utoc(7, flags=1 | 8))
    (tmp_path / "Paks" / "global.ucas").write_bytes(b"\0" * 100)
    (tmp_path / "Paks" / "enc.utoc").write_bytes(S.build_utoc(2, flags=2))
    (tmp_path / "Paks" / "bad.utoc").write_bytes(b"nope")
    rows = {r["path"]: r for r in ue_pak.list_iostore(tmp_path)}
    g = rows["Paks/global.utoc"]
    assert g["entries"] == 7 and g["flags"] == ["compressed", "indexed"] and g["ucas_size"] == 100
    assert "next stage" in g["status"]
    assert rows["Paks/enc.utoc"]["encrypted"]
    assert rows["Paks/bad.utoc"]["status"] == "error"


# ---------------------------------------------------------------------- packages

def test_unversioned_package_tables_and_classification():
    ua, ue, _ = S.mesh_package()
    pkg = ue_asset.parse_package(ua, (4, 27))
    assert pkg.summary["unversioned"] and pkg.ue4 == 522
    assert [e.name for e in pkg.exports] == ["SK_Test", "SK_Test_Skeleton"]
    assert [e.class_name for e in pkg.exports] == ["SkeletalMesh", "Skeleton"]
    assert pkg.summary["saved_by"].startswith("4.27.2")
    rows = ue_asset.classify(pkg)
    assert [(r["kind"], r["export"]) for r in rows] == [("skeletal_mesh", "SK_Test"), ("skeleton", "SK_Test_Skeleton")]
    body = ue_asset.export_body(pkg, pkg.exports[0], ua, ue)
    assert len(body) == pkg.exports[0].serial_size


def test_engine_version_drives_unversioned_object_version():
    ua, _ue, _ = S.mesh_package()
    assert ue_asset.parse_package(ua, (4, 19)).ue4 == 516
    assert ue_asset.parse_package(ua, None).ue4 == 522          # default 4.27
    assert ue_asset.object_versions((5, 1)) == (522, 1008)
    with pytest.raises(ue_asset.AssetError):
        ue_asset.object_versions((3, 0))


def test_inventory_relations_in_classify():
    pk = S.anim_actor_packages()
    seq = ue_asset.classify(ue_asset.parse_package(pk["Game/Content/Char/Run_Fwd"][0], (4, 27)))
    assert seq[0]["kind"] == "animation" and seq[0]["class"] == "AnimSequence"
    assert seq[0]["uses"]["skeleton"] == ["/Game/Char/SK_Test_Skeleton.SK_Test_Skeleton"]
    bp = ue_asset.classify(ue_asset.parse_package(pk["Game/Content/Char/BP_Hero"][0], (4, 27)))
    assert len(bp) == 1 and bp[0]["super"] == "Character" and bp[0]["super_path"] == "/Script/Engine.Character"
    assert bp[0]["uses"]["skeletal_mesh"] == ["/Game/Char/SK_Test.SK_Test"]
    assert bp[0]["uses"]["anim_blueprint"] == ["/Game/Char/ABP_Test.ABP_Test_C"]


def test_bad_package_headers_raise_asset_error():
    with pytest.raises(ue_asset.AssetError, match="tag"):
        ue_asset.parse_package(b"\0" * 64)
    ua, _ue, _ = S.mesh_package()
    bad = bytearray(ua)
    struct.pack_into("<i", bad, 4, -3)                            # UE3-era legacy version
    with pytest.raises(ue_asset.AssetError, match="legacy"):
        ue_asset.parse_package(bytes(bad))
    with pytest.raises(ue_pak.PakError):
        ue_asset.parse_package(ua[:120], (4, 27))


def test_package_inside_a_pak_round_trip(tmp_path):
    files = S.game_files()
    p = _write(tmp_path, S.build_pak(files, 11, "Zlib", block_size=0x400))
    with ue_pak.PakFile(p) as pf:
        pkg = ue_asset.parse_package(pf.read("Game/Content/Char/SK_Test.uasset"), (4, 27))
        assert pkg.exports[0].class_name == "SkeletalMesh"


@pytest.mark.skipif(sys.platform != "win32", reason="ctypes WinDLL only exists on Windows")
def test_oodle_refuses_non_dll_name_on_windows(tmp_path):
    gd = tmp_path / "g"
    gd.mkdir()
    f = gd / "oo2core_9_win64.dll"
    f.write_bytes(b"not a dll")
    with pytest.raises(OSError):
        ue_pak.Oodle(f, gd)
