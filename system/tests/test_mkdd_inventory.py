import hashlib,os,struct
from pathlib import Path
import pytest
from gbox import mkdd_inventory as I

def test_dol_data_section_uses_own_size():
    b=bytearray(0x120)
    struct.pack_into('>I',b,0,0x100);struct.pack_into('>I',b,0x1c,0x110)
    struct.pack_into('>I',b,0x90,4);struct.pack_into('>I',b,0xac,12)
    sections=I._dol_info(b)['sections']
    assert [(x['kind'],x['offset'],x['size']) for x in sections]==[('text',0x100,4),('data',0x110,12)]
    struct.pack_into('>I',b,0xac,20)
    with pytest.raises(ValueError):I._dol_info(b)

def test_wrong_game_rejected_before_open(tmp_path):
    p=tmp_path/'disc';b=bytearray(0x100);b[:6]=b'GZ2E01';b[0x1c:0x20]=bytes.fromhex('c2339f3d');p.write_bytes(b)
    with pytest.raises(ValueError,match='GM4E01'):I.inventory(p)

def test_expected_source_hash_verified(tmp_path):
    p=tmp_path/'disc';b=bytearray(0x100);b[:6]=b'GM4E01';b[0x1c:0x20]=bytes.fromhex('c2339f3d');p.write_bytes(b)
    with pytest.raises(ValueError,match='SHA-256 mismatch'):I.inventory(p,source_sha256='0'*64)

def test_owned_disc():
    path=Path(os.environ.get('GBOX_MKDD_GCZ','/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Mario Kart - Double Dash!! (USA).gcz'))
    if not path.exists():pytest.skip('Owned MKDD source not mounted')
    result=I.inventory(path)
    assert result['game_id']=='GM4E01' and result['rarc']['parsed']==79
    assert set(result['characters'])==set(I.CHARACTERS)
    assert all(c['driver'] and c['kart'] for c in result['characters'].values())
    assert len(result['source_sha256'])==64
    assert all(r['size']>0 for r in result['assets']['model'])
