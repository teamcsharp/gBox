import os,struct
from pathlib import Path
import pytest
from gbox import prime_inventory as I

def pak():
    # One named world, but three distinct resources, two without names.
    b=bytearray(0x100)
    struct.pack_into('>3I',b,0,I.PAK_VERSION,0,1)
    struct.pack_into('>4sII',b,12,b'MLVL',1,1);b[24]=ord('x')
    struct.pack_into('>I',b,25,3)
    for i,typ in enumerate((b'MLVL',b'CMDL',b'TXTR')):
        struct.pack_into('>I4sIII',b,29+i*20,0,typ,i+1,32,0xa0+32*i)
    return b

def test_inventory_counts_resources_not_exported_names():
    b=pak();assert I.parse_pak_toc(b)[2]==[('MLVL',1,'x',12)]
    assert I.section_types(b)=={'MLVL':1,'CMDL':1,'TXTR':1}
    struct.pack_into('>I',b,25,0xffffffff)
    with pytest.raises(ValueError):I.section_types(b)

def test_expected_hash_must_match(tmp_path):
    p=tmp_path/'source';p.write_bytes(b'actual')
    with pytest.raises(ValueError,match='SHA-256 mismatch'):I.inventory(p,source_sha256='0'*64)

def test_owned_prime2():
    path=Path(os.environ.get('GBOX_PRIME2_ISO','/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Metroid Prime 2 - Echoes (USA).gcz'))
    if not path.exists():pytest.skip('Owned Prime 2 source not mounted')
    result=I.inventory(path)
    assert result['disc']['disc_id']==I.DISC_ID and result['files']==215
    assert len(result['source']['sha256'])==64 and result['paks']
    assert result['section_types']['CMDL']>100 and result['section_types']['TXTR']>100
    assert sum(p['sections'] for p in result['paks'])>sum(p['exported_names'] for p in result['paks'])
    assert result['levels'] and result['actor_rels']>0
