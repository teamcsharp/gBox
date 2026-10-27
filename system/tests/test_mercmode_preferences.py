"""An official edition preference is explicit even before its native driver exists."""
import random

import pytest

from gbox import mercmode as M, re_switch
from tests.test_mercmode import rig


PREFERENCE={'re5':{'platform':'switch','mode':'no_mercy','title_id':re_switch.RE5_TITLE_ID}}


def test_switch_no_mercy_preference_is_per_host_and_never_selects_ps3_as_its_substitute():
    store,w,*_=rig()
    cfg=M.configure(store,w['name'],{'titles':['re5'],'preferred_editions':PREFERENCE})
    rows=M.inventory(store,w,cfg)
    re5=next(r for r in rows if r['title']=='re5')
    assert re5['platform']=='switch' and re5['preferred_mode']=='no_mercy'
    assert re5['map_id']==re_switch.RE5_TITLE_ID
    assert not re5['playable'] and not re5['backend_playable']      # the rig's catalog has no Switch RE5
    assert re5['reason']=='The verified game revision is absent from the catalog'
    assert re5['preparation']['strategy']=='native_menus_from_boot'
    assert M.choose(store,w,random.Random(0),cfg) is None
    assert M.settings(store,'another-host')['preferred_editions']=={}
    assert not cfg['enabled']  # saving the desired edition does not start rotation


@pytest.mark.parametrize('preference',[None,[],{'re4':{}},{'re5':{'platform':'ps3'}},
    {'re5':{'platform':'switch','mode':'mercenaries','title_id':re_switch.RE5_TITLE_ID}}])
def test_edition_preference_rejects_ambiguous_or_unreviewed_values(preference):
    with pytest.raises(ValueError):M.normalize({'preferred_editions':preference})
