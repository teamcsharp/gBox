import hashlib
import os
from pathlib import Path
import struct
import pytest
from gbox import doa2usa_bindings as B

def test_hand_positioned_table_ends_at_eof():
    raw = b'c:/doa2/kas00.chr\0'.ljust(32,b'\0') + struct.pack('<I',B.BASE)
    assert B.locate_file_names(raw) == 32
    assert B.read_names(raw,32) == [b'c:/doa2/kas00.chr']
    assert B.resource_names(raw) == [b'kas00.chr']

@pytest.mark.parametrize('raw',[b'',b'abc',bytes(32)])
def test_missing_table_is_explicit(raw):
    with pytest.raises(ValueError,match='No resource'): B.locate_file_names(raw)

@pytest.mark.parametrize('offset',[-4,1,32,100])
def test_invalid_table_offset(offset):
    with pytest.raises(ValueError): B.read_names(bytes(32),offset)

def test_stops_at_non_resource_text():
    raw=b'kas00.chr\0ordinary text\0'.ljust(32,b'\0')+struct.pack('<III',B.BASE,B.BASE+10,B.BASE)
    assert B.read_names(raw,32) == [b'kas00.chr']
    assert not B.is_resource_name(raw,-len(raw))

def test_partial_final_pointer_is_not_read():
    raw=b'kas00.chr\0'.ljust(32,b'\0')+struct.pack('<I',B.BASE)+b'xx'
    assert B.read_names(raw,32)==[b'kas00.chr']

def test_owned_usa_names_and_identity():
    from gbox.gdrom import GDRom
    path=Path(os.environ.get('GBOX_DOA2_USA_GDI',str(Path.home()/'gBox_alt/gbox-cache/dc/5f08ad9a86ebcc9a/disc.gdi')))
    if not path.exists(): pytest.skip('Owned USA GDI not mounted')
    exe=GDRom(path).read('1ST_READ.BIN')
    assert hashlib.sha256(exe).hexdigest()==B.USA_EXECUTABLE_SHA256
    assert B.locate_file_names(exe)==B.USA_FILE_NAMES_OFFSET
    names=B.resource_names(exe)
    assert len(names)==642
    assert set(B.USA_FIGHTERS)|set(B.USA_VARIANTS) <= set(B.fighter_families(names))
    with pytest.raises(NotImplementedError): B.parse_render_scripts(exe)


GDI = Path(os.environ.get("GBOX_DOA2_USA_GDI", str(Path.home() / "gBox_alt/gbox-cache/dc/5f08ad9a86ebcc9a/disc.gdi")))
if not GDI.exists():
    GDI = Path.home() / "gbox-cache/dc/5f08ad9a86ebcc9a/disc.gdi"


@pytest.fixture(scope="module")
def usa_exe():
    from gbox.gdrom import GDRom
    if not GDI.exists():
        pytest.skip("Owned USA GDI not mounted")
    return GDRom(GDI).read("1ST_READ.BIN")


def test_file_table_contiguous_after_names(usa_exe):
    assert B.USA_FILE_TABLE_OFFSET == 0x141C6C
    assert B.USA_FILE_TABLE_ADDRESS == 0x8C151C6C


def test_parse_file_table_108_records(usa_exe):
    t = B.parse_file_table(usa_exe)
    assert len(t) == 108
    for r in t:
        f = r["files"]
        assert f["motion"].endswith(".mot") and f["geometry"].endswith(".chr")
        assert f["skin"].endswith(".apv") and f["sup"].endswith(".sup")
        assert f["textures"].endswith(".bin") and f["control"][-4:] in (".bin", ".mdl")


def test_known_slots(usa_exe):
    f = B.fighter_files(usa_exe, 0, 0)["files"]
    assert (f["control"], f["motion"], f["geometry"]) == ("zack.bin", "zack.mot", "zac01.chr")
    f = B.fighter_files(usa_exe, 5, 0)["files"]      # KAS
    assert f["motion"] == "kasumi.mot" and f["geometry"].startswith("kas")
    assert B.fighter_files(usa_exe, 5, 5)["files"]["geometry"] == "kas04.chr"
    assert B.resolve_archive_binding(usa_exe, "c:/x/ZAC01.CHR")["code"] == "ZAC"


def test_accessory_table(usa_exe):
    a = B.accessory_table(usa_exe)
    assert len(a) == 108 and all(r["filename"].endswith(".acs") for r in a)
    assert a[0]["filename"] == "zac_a01.acs" and a[5]["filename"] == "kas_a00.acs"


def test_le_file_table_contiguity_cross_check():
    from gbox import doa2_bindings as le
    assert le.FILE_NAMES + 4 * B.LE_NAME_COUNT == le.FILE_TABLE


def test_script_table_still_unlocated(usa_exe):
    with pytest.raises(NotImplementedError):
        B.parse_render_scripts(usa_exe)
