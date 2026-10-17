import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from gbox import fzgx_inventory as I

def test_roster_includes_compressed_models_without_duplicates():
    assert I.roster(SimpleNamespace(files=['chara/hero_500.gma.lz','chara/hero_face.gma','chara/other_100.gma','bg/fake_500.gma']))==['hero','other']

def test_owned_disc_inventory():
    source=Path(os.environ.get('GBOX_FZGX_GCZ','/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/F-Zero GX (USA).gcz'))
    if not source.exists():pytest.skip('Owned F-Zero GX GCZ not mounted')
    report=I.build_manifest(str(source))
    assert report['disc_id']=='GFZE01' and report['region']=='NTSC-U'
    assert report['roster_count']>=30
    assert report['samples']['chara/arc/arrow_sel.arc.lz']['head'].startswith('55aa382d')
    assert report['samples']['bg/bg_big.gma.lz']['size']==837472
    assert len(report['source_sha256'])==64 and len(report['dol']['sha256'])==64
