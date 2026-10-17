import hashlib,struct
from pathlib import Path
import pytest
from gbox import burnout_inventory as I

def test_rw_payload_sizes_and_zero_length_extensions():
    raw=struct.pack('<III',1,3,0x1803ffff)+b'abc'+struct.pack('<III',3,0,0x1803ffff)
    rows=I.rw_chunks(raw)
    assert [(r['type'],r['size'],r['offset']) for r in rows]==[('Struct',3,0),('Extension',0,15)]
    with pytest.raises(ValueError):I.rw_chunks(raw[:-1])
    with pytest.raises(ValueError):I.rw_chunks(raw+b'x')

def test_rw_chunk_names_are_not_interchanged():
    rows=I.rw_chunks(b''.join(struct.pack('<III',i,0,1) for i in (0xe,0xf,0x14,0x15,0x1a)))
    assert [r['type'] for r in rows]==['FrameList','Geometry','Atomic','TextureNative','GeometryList']

def test_tpl_bounds():
    raw=bytearray(32);struct.pack_into('>III',raw,0,I.TPL_MAGIC,1,12)
    struct.pack_into('>I',raw,12,20);struct.pack_into('>HHII',raw,20,2,4,4,32)
    assert I.tpl_images(raw)==[{'w':4,'h':2,'fmt':'RGB565'}]
    struct.pack_into('>I',raw,8,4)
    with pytest.raises(ValueError):I.tpl_images(raw)

def test_pointer_prefix_and_sgd_are_explicit_hypotheses():
    bank=struct.pack('>3I',0x81000000,0x81000100,5)
    assert I.asset_bank(bank)['candidate_prefix_ends']==8
    sgd=bytearray(64);sgd[:8]=b'SGDVER 7'
    assert I.sgd_header(sgd)['layout_verified'] is False

def test_expected_source_hash_checked(tmp_path):
    p=tmp_path/'source';p.write_bytes(b'actual source')
    with pytest.raises(ValueError,match='SHA-256 mismatch'):I.inventory(p,source_sha256='0'*64)

def test_owned_burnout():
    path=Path('/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Burnout (USA).gcz')
    if not path.exists():pytest.skip('Owned Burnout GCZ not mounted')
    result=I.inventory(path)
    assert result['disc']['disc_id']=='GBOE51' and result['roster_size']==9
    assert len(result['source']['sha256'])==64
    assert all(c['files'] and c['bytes'] for c in result['roster'])
    assert result['format_probes']['frontend/frontend.dic']['chunks'][0]['type']=='TextureDictionary'
    assert result['format_probes']['misc/start.dff']['chunks'][0]['type']=='Clump'
