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
