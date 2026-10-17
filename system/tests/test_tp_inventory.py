import hashlib,io,struct
from pathlib import Path
from types import SimpleNamespace
import pytest
from gbox import tp_inventory as I
from test_rarc import archive

def test_rarc_summary_uses_valid_members():
    b=archive();b[0xe9:0xee]=b'a.bmd'
    result=I.rarc_parse(b)
    assert result['valid'] and result['data_off']==0x160
    assert result['j3d_assets']=={'.bmd':1} and result['sample_names']==['A/a.bmd']
    struct.pack_into('>I',b,0xc,0x160)
    with pytest.raises(ValueError):I.rarc_parse(b)

def test_wrong_disc_closes_handle(monkeypatch):
    stream=io.BytesIO();monkeypatch.setattr(I,'GCDisc',lambda _:SimpleNamespace(game_id='OTHER',f=stream))
    with pytest.raises(ValueError,match='GZ2E01'):I.disc_identity('unused')
    assert stream.closed

def test_actual_identity_and_bounded_archive_census(tmp_path,monkeypatch):
    p=tmp_path/'source';p.write_bytes(b'actual source')
    b=archive();stream=io.BytesIO();reads=[]
    def read(off,size):
        reads.append((off,size));assert size<=4
        return bytes(b[:size])
    disc=SimpleNamespace(game_id=I.GAME_ID,title='fixture',f=stream,files={'actors/a.arc':(100,len(b))},dol=lambda:b'executable',read=lambda _:b,_r=read)
    monkeypatch.setattr(I,'GCDisc',lambda _:disc)
    result=I.inventory(str(p))
    assert reads==[(100,4)] and stream.closed
    assert result['source']['sha256']==hashlib.sha256(b'actual source').hexdigest()
    assert result['hashes']['main_dol']==hashlib.sha256(b'executable').hexdigest()
    assert result['layout']['top_dirs']['actors']['files']==1
    assert result['archives']['raw_rarc']==1

def test_owned_twilight_princess():
    p=Path(I.GCZ)
    if not p.exists():pytest.skip('Owned Twilight Princess source not mounted')
    result=I.inventory(str(p))
    assert result['source']['game_id']==I.GAME_ID
    assert result['hashes']['main_dol']==I.MAIN_DOL_SHA256
    assert result['source']['file_count']==3656
    assert result['archives']['total']==1843
    assert len(result['sample_archives'])==6
    assert all(x['valid'] and x['name_count']>0 for x in result['sample_archives'].values())
