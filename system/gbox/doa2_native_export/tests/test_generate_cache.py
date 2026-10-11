"""Synthetic independent cache verifier regressions; no owned archive fixture."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from .. import generate_cache as K
from .test_cloth_cache import make_cache


def generated_cache(tmp_path):
    original,acs,_,_,row=make_cache(tmp_path)
    prefix=Path(row['seed']);prefix.with_suffix('.CHR').write_bytes(original)
    target=K.V.decode_grids(acs,original)[0]
    row.update({k:target[k] for k in ('parent','columns','rows','flags')})
    path=Path(row['output'])
    path.write_bytes(bytes(8192))
    native=Path(str(path)+'.component.CHR').read_bytes()
    Path(str(path)+'.CHR').write_bytes(native)
    Path(str(path)+'.input.CHR').write_bytes(original)
    cells=np.zeros((1,3,12),dtype='<f4')
    cells[0,:,:3]=np.array([[0,0,0],[1,2,3],[4,5,6]],float)+[0,2,0]
    Path(str(path)+'.cells').write_bytes(cells.tobytes()+bytes(32768-cells.nbytes))
    (tmp_path/'inventory.json').write_text(json.dumps([row]))
    return original,acs,row


@pytest.mark.parametrize('foreign_prefix',('/another/private/computer/',r'C:\another\private\computer\\'))
def test_independent_native_alias_cache_verification_and_relocation(tmp_path,foreign_prefix):
    original,acs,row=generated_cache(tmp_path)
    seed_name,output_name=Path(row['seed']).name,Path(row['output']).name
    row['seed']=foreign_prefix+seed_name
    row['output']=foreign_prefix+output_name
    (tmp_path/'inventory.json').write_text(json.dumps([row]))
    result=K.verify(tmp_path)
    assert result['errors']==[] and result['aliases_verified']==3
    verification=json.loads((tmp_path/'verification.json').read_text())
    assert verification['grids'][0]['cached_chr_sha256']==hashlib.sha256(Path(str(tmp_path/output_name)+'.component.CHR').read_bytes()).hexdigest()


@pytest.mark.parametrize('corruption',('source','inventory','outside_vertex','native_alias','nonfinite_cells','allocation'))
def test_corrupt_native_artifacts_fail_before_acceptance(tmp_path,corruption):
    original,acs,row=generated_cache(tmp_path);path=Path(row['output'])
    if corruption=='source':
        seed=Path(row['seed']).with_suffix('.CHR');data=bytearray(seed.read_bytes());data[-1]^=1;seed.write_bytes(data)
    elif corruption=='inventory':
        row['columns']=2;(tmp_path/'inventory.json').write_text(json.dumps([row]))
    elif corruption in ('outside_vertex','native_alias'):
        target=Path(str(path)+'.CHR');data=bytearray(target.read_bytes())
        offset=0 if corruption=='outside_vertex' else K.E.G.decode_chr(original)['models'][0]['meshes'][0]['records'][0]['offset']+2
        data[offset]^=128;target.write_bytes(data)
    elif corruption=='nonfinite_cells':
        target=Path(str(path)+'.cells');data=bytearray(target.read_bytes());data[:4]=np.asarray([np.nan],dtype='<f4').tobytes();target.write_bytes(data)
    else:
        path.write_bytes(bytes(8191))
    result=K.verify(tmp_path)
    assert len(result['errors'])==1 and result['full_native_generators_verified']==0


def test_headless_rejects_invalid_hidden_project_directory_before_starting(tmp_path):
    with pytest.raises(ValueError,match='hidden directory'):
        K.run_native(tmp_path,'nonexistent-headless',tmp_path/'.hermes'/'projects','owned','1ST_READ.BIN')
