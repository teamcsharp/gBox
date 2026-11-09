"""Opt-in: rebuild the accepted Sonic v15 archive from the owned inputs, whichever BLAS kernel rounds the bind tables.

Game data is never in the repository. Set ``GBOX_RE5_SONIC_ASSETS`` to a folder holding the original
``uPl00ChrisNormal.arc`` (SHA-256 8ab0dc18...) and ``sonic.glb`` (5dd7cc07...); without it every case skips.
Each case rebuilds all three stages in a fresh interpreter, about a minute apiece.

The reviewed bytes carry the rounding residue of OpenBLAS's SkylakeX kernels. Before ``re5_sonic_residue`` the
forced Haswell and Nehalem kernels produced stage-1 MODs ``44296edc...`` and ``26c7a135...`` on the authoring PC
and stopped at the v12 guard; they are the stand-ins available on x86 for a host with other kernels.
"""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import pytest

from gbox import re5_sonic_grip as grip, re5_sonic_hands as hands, re5_sonic_writer as writer

ASSETS = os.environ.get('GBOX_RE5_SONIC_ASSETS', '')
CHILD = r'''
import hashlib, json, sys, zlib
from pathlib import Path
from gbox import mt_arc, re5_sonic_residue as residue, re5_sonic_writer as writer
assets = Path(sys.argv[1])
archive, receipt = writer.build_grip_candidate((assets/'uPl00ChrisNormal.arc').read_bytes(), assets/'sonic.glb')
model = zlib.decompress(mt_arc.parse(archive).entries[97].data)
print(json.dumps({'models': [receipt['finger_rig']['base_mod_sha256'], receipt['finger_rig']['written_mod_sha256'],
                             receipt['grip_fit']['written_mod_sha256'], hashlib.sha256(model).hexdigest()],
                  'table': residue.record(model) == residue._TABLES[hashlib.sha256(model).hexdigest()],
                  'receipt': {k: receipt[k] for k in ('written_sha256', 'reviewed_sha256', 'reproduces_reviewed')},
                  'reproduction': writer.grip_reproduction(archive)}))
'''


@pytest.mark.skipif(not ASSETS, reason='set GBOX_RE5_SONIC_ASSETS to the owned Chris archive and Sonic GLB')
@pytest.mark.parametrize('kernel', ['', 'Haswell', 'Nehalem'])
def test_v15_rebuilds_byte_exactly_whichever_kernel_rounds_the_bind_tables(kernel):
    if kernel and platform.machine().lower() not in ('amd64', 'x86_64'):
        pytest.skip('forced OpenBLAS kernels are the x86-64 stand-ins')
    env = dict(os.environ, OPENBLAS_VERBOSE='2', PYTHONPATH=str(Path(writer.__file__).resolve().parents[1]))
    env.pop('OPENBLAS_CORETYPE', None)
    if kernel:
        env['OPENBLAS_CORETYPE'] = kernel
    result = subprocess.run([sys.executable, '-c', CHILD, ASSETS], env=env, capture_output=True, text=True)
    if kernel and f'Core: {kernel}' not in result.stderr:
        pytest.skip(f'this NumPy build or CPU does not run the {kernel} kernel')
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout)
    v15_model = writer.GRIP_PAYLOADS[0][2]
    assert report['models'] == [hands.BASE_MOD_SHA256, grip.V14_MOD_SHA256, v15_model, v15_model]
    assert report['table'] is True
    assert report['reproduction'] == {'reviewed_sha256': writer.GRIP_ARCHIVE_SHA256,
                                      'written_sha256': writer.GRIP_ARCHIVE_SHA256, 'exact': True}
    assert report['receipt'] == {'written_sha256': writer.GRIP_ARCHIVE_SHA256,
                                 'reviewed_sha256': writer.GRIP_ARCHIVE_SHA256, 'reproduces_reviewed': True}
