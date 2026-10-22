import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gbox.gcdisc import GCDisc
from gbox.re2gc_native import Model, part_bone_census

ROM = '/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Resident Evil 2 (USA).gcz'
EXPECTED_PLD = 40
EXPECTED_BIND = 23
EXPECTED_EXTRA = 17


@pytest.mark.skipif(not os.path.exists(ROM), reason='owned RE2 GameCube build not mounted')
def test_owned_build_part_bone_census():
    disc = GCDisc(ROM)
    try:
        names = [k for k in disc.files if k.lower().endswith('.pld')]
        rows = [part_bone_census(Model(disc.read(n))) for n in sorted(names)]
    finally:
        disc.f.close()
    extra = [r for r in rows if r['extra_parts']]
    bind = [r for r in rows if r['bind_pose_exportable']]
    assert len(rows) == EXPECTED_PLD, 'expected %d PLDs, got %d' % (EXPECTED_PLD, len(rows))
    assert len(bind) == EXPECTED_BIND, 'expected %d bind-pose PLDs, got %d' % (EXPECTED_BIND, len(bind))
    assert len(extra) == EXPECTED_EXTRA, 'expected %d extra-part PLDs, got %d' % (EXPECTED_EXTRA, len(extra))


def test_census_reports_extra_parts():
    class FakeModel:
        objects = (1, 2, 3)
        skeleton = {'bones': 2}

    census = part_bone_census(FakeModel())
    assert census == {'objects': 3, 'bones': 2, 'extra_parts': 1, 'bind_pose_exportable': False}
