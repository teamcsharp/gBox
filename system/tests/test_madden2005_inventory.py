import hashlib
import io
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from gbox import madden2005_inventory as I

@pytest.mark.parametrize('raw,kind',[(b'TERF','terf'),(b'QL01','qkl'),(b'DB','db'),(b'BNR1','bnr'),(b'BNR2','bnr'),(b'','other')])
def test_container_magic(raw,kind):
    assert I.classify_magic(raw)==kind

def test_archive_family_does_not_exclude_nested_model_formats():
    result=I.engine_finding({'terf':3,'bnr':1})
    assert result['engine']=='ea_terf_qkl' and result['refutes'] is None
    assert result['scope']=='outer containers only'
    assert I.engine_finding({'other':2})['unclassified_containers']==2

def test_reads_only_bounded_prefixes_and_hashes_actual_source(tmp_path,monkeypatch):
    source=tmp_path/'disc';source.write_bytes(b'owned fixture')
    stream=io.BytesIO();calls=[]
    def read(off,size):
        calls.append((off,size));assert size<=8
        return b'TERFdata'[:size]
    disc=SimpleNamespace(game_id=I.BUILD_ID,title='fixture',files={'PLADATA.DAT':(100,10**9)},_r=read,dol=lambda:b'executable',f=stream)
    monkeypatch.setattr(I,'_disc',lambda _:disc)
    result=I.inventory(str(source))
    assert calls==[(100,8)] and stream.closed
    assert result['source_sha256']==hashlib.sha256(b'owned fixture').hexdigest()

def test_wrong_build_is_rejected_and_closed(monkeypatch):
    stream=io.BytesIO();monkeypatch.setattr(I,'_disc',lambda _:SimpleNamespace(game_id='OTHER',f=stream))
    with pytest.raises(ValueError,match='Expected'):I.inventory('unused')
    assert stream.closed

def test_owned_disc_inventory():
    path=Path(os.environ.get('GBOX_MADDEN2005_GCZ','/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Madden NFL 2005 (USA).gcz'))
    if not path.exists():pytest.skip('Owned Madden 2005 GCZ not mounted')
    result=I.inventory(str(path))
    assert result['build_id']==I.BUILD_ID
    assert result['kinds'].get('terf',0)>0 and result['kinds'].get('qkl',0)>0
    assert 'PLADATA.DAT' in result['character_containers']
    assert len(result['source_sha256'])==64 and len(result['main_dol']['sha256'])==64
