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


def test_the_settings_route_saves_and_clears_the_edition_preference(cfg):
    # 2026-10-26: POST /api/mercmode dropped preferred_editions (not in its model), so neither the mercmode tool nor MCP
    # could select RE5 Switch No Mercy
    import time
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    from tests.test_screensaver import worker
    app=create_app(cfg);store=app.state.store
    w=worker(time.time(),name='lilspark',os='linux')
    store.put('worker',w['id'],w|{'last_seen':time.time(),'tools':['mercmode','launch_game','autoplay']})
    with TestClient(app,headers={'Authorization':'Bearer '+cfg.token()}) as c:
        r=c.post('/api/mercmode',json={'host':'lilspark','preferred_editions':PREFERENCE})
        assert r.status_code==200,r.text
        assert M.settings(store,'lilspark')['preferred_editions']==PREFERENCE
        assert c.post('/api/mercmode',json={'host':'lilspark','preferred_editions':{'re5':{'platform':'ps3'}}}).status_code==422
        assert M.settings(store,'lilspark')['preferred_editions']==PREFERENCE        # a refused value changes nothing
        assert c.post('/api/mercmode',json={'host':'lilspark','preferred_editions':{}}).status_code==200
        assert M.settings(store,'lilspark')['preferred_editions']=={}


@pytest.mark.parametrize('preference',[None,[],{'re4':{}},{'re5':{'platform':'ps3'}},
    {'re5':{'platform':'switch','mode':'mercenaries','title_id':re_switch.RE5_TITLE_ID}}])
def test_edition_preference_rejects_ambiguous_or_unreviewed_values(preference):
    with pytest.raises(ValueError):M.normalize({'preferred_editions':preference})
