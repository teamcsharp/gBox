import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from gbox import tas


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    root=tmp_path_factory.mktemp('tas-native')
    try:
        proxy=tas.compile_proxy(root/'runtime')
        fake=root/'fake';(fake/'native').mkdir(parents=True)
        shutil.copyfile(Path(__file__).parent/'native/tas_test_core.c',fake/'native/tas_core.c')
        original=tas.__file__
        try:
            tas.__file__=str(fake/'tas.py')
            core=tas.compile_proxy(root/'runtime')
        finally:tas.__file__=original
    except (OSError, subprocess.SubprocessError) as error:
        pytest.skip('Native C compiler unavailable: '+str(error))
    return proxy,core,root


def drive(native,folder,mode,frames,**env):
    proxy,core,_=native
    result=subprocess.run([sys.executable,str(Path(__file__).parent/'tas_native_harness.py'),str(proxy),str(core),str(folder),mode,str(frames)],
                          env={**os.environ,**env},capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_native_preserves_rewind_branches_mod_writes_reset_and_every_input(native):
    folder=native[2]/'roundtrip'
    original=drive(native,folder,'record',1400)
    info=tas.index(folder/'input.gbt')
    assert info['frames']==1400 and info['state_restores']==10
    assert any(c['reason']==3 for c in info['checkpoints'])
    replay=drive(native,folder,'play',1401)
    assert replay['native']==dict(state='finished',reason='',frame=1400,loops=0,mismatches=0)
    assert replay['ram_sha256']==original['ram_sha256']


def test_native_desync_fails_and_never_consumes_random_input(native):
    folder=native[2]/'tamper';drive(native,folder,'record',400)
    data=bytearray((folder/'input.gbt').read_bytes())
    offset=next(o for o,t,p in tas.records(folder/'input.gbt') if t==b'F')
    data[offset+5+12]^=1;(folder/'input.gbt').write_bytes(data)
    replay=drive(native,folder,'play',500)
    assert replay['native']['state']=='failed' and replay['native']['mismatches']==1
    assert replay['native']['frame']==0


def test_native_budget_seals_prefix_but_human_game_keeps_running(native):
    folder=native[2]/'budget'
    stopped=drive(native,folder,'record',400,GBOX_TAS_MAX_BYTES='1024')
    assert stopped['native']['state']=='budget_stop'
    assert tas.index(folder/'input.gbt')['frames']==60
    normal=drive(native,native[2]/'normal','record',400)
    assert normal['ram_sha256']==stopped['ram_sha256']


def test_native_segment_preroll_and_loop_return_to_initial_checkpoint(native):
    source=native[2]/'source';drive(native,source,'record',1400)
    folder=native[2]/'loop';folder.mkdir()
    cut=tas.slice_tape(source/'input.gbt',folder/'input.gbt',655,875)
    replay=drive(native,folder,'play',800,GBOX_TAS_FROM=str(cut['start_frame']),GBOX_TAS_TO=str(cut['end_frame']),GBOX_TAS_LOOP='1')
    assert replay['native']['mismatches']==0 and replay['native']['loops']>=2
