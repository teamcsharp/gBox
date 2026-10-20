import hashlib
import os
from pathlib import Path
import struct
import pytest
from gbox import pstone2_mdl as M, pstone2_inventory as I

def fixture():
    # Independently positioned header, two chunk records, 16-byte node area and payload.
    raw=bytearray(120)
    struct.pack_into('<8I',raw,0,0xffffffff,1,112,2,0,0x3f800000,0x40a00000,0)
    struct.pack_into('<8I',raw,32,0,0,3,0,0,0,0,0)
    struct.pack_into('<8I',raw,64,0,0,4,4,8,0,0,0xffffffff)
    raw[112:120]=b'ABCDabcd'
    return raw

def test_hand_positioned_payloads():
    raw=fixture(); result=M.parse_mdl(raw); records=M.chunk_records(raw)
    assert result['node_region']==(96,112)
    assert [M.chunk_bytes(raw,r,records,i) for i,r in enumerate(records)]==[b'ABCD',b'abcd']

@pytest.mark.parametrize('field,value',[(8,0),(8,121),(12,999),(44,20),(80,3),(80,9)])
def test_rejects_invalid_geometry_extents(field,value):
    raw=fixture(); struct.pack_into('<I',raw,field,value)
    with pytest.raises(ValueError): M.parse_mdl(raw)

def test_foreign_or_invalid_chunk_selection():
    raw=fixture(); rs=M.chunk_records(raw)
    with pytest.raises(ValueError): M.chunk_bytes(raw,rs[1],rs,0)
    with pytest.raises(ValueError): M.chunk_bytes(raw,rs[0],rs,-1)

@pytest.mark.parametrize('code',['','0','000','G0'])
def test_invalid_pl_code(code):
    with pytest.raises(ValueError): M.pl_character(code)

def test_table_position_is_not_character_index():
    exe=b'X\0\0\0'+b''.join(n.ljust(20,b'\0') for n in [b'PL00_CONNECT.BIN',b'PL10_CONNECT.BIN',b'PL12_CONNECT.BIN',b'PL20_CONNECT.BIN'])
    rows=M.pl_load_ids(exe,at=0)
    assert [(r['load_id'],r['char_index'],r['variant']) for r in rows]==[(1,0,0),(2,1,0),(3,1,2),(4,2,0)]

def test_owned_character_model_containers():
    from gbox.gdrom import GDRom
    path=Path(os.environ.get('GBOX_PSTONE2_GDI',str(Path.home()/'gBox_alt/gbox-cache/dc/690a402443c15668/disc.gdi')))
    if not path.exists(): pytest.skip('Owned Power Stone 2 GDI not mounted')
    disc=GDRom(path);exe=disc.read('1ST_READ.BIN')
    assert hashlib.sha256(exe).hexdigest()==I.FIRST_READ_SHA256
    rows=M.pl_load_ids(exe); assert len(rows)==18
    checked=0
    for row in rows:
        data=disc.read(row['name']);off,size=I.connect_table(data)[0];raw=data[off:off+size]
        parsed=M.parse_mdl(raw);rs=M.chunk_records(raw)
        assert parsed['chunks']
        for index,rec in enumerate(rs):
            assert len(M.chunk_bytes(raw,rec,rs,index))==parsed['chunks'][index]['end']-rec.offset
        checked+=1
    assert checked==18
