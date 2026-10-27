"""An official edition preference is explicit even before its native driver exists."""
import random

import pytest

from gbox import mercmode as M, re_switch
from tests.test_mercmode import rig


PREFERENCE={'re5':{'platform':'switch','mode':'no_mercy','title_id':re_switch.RE5_TITLE_ID}}
RE6_PREFERENCE={'re6':{'platform':'switch','mode':'no_mercy','title_id':re_switch.RE6_TITLE_ID}}


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
    {'re5':{'platform':'switch','mode':'mercenaries','title_id':re_switch.RE5_TITLE_ID}},
    {'re6':{'platform':'switch','mode':'no_mercy','title_id':re_switch.RE5_TITLE_ID}},     # RE5's id for RE6
    {'re6':{'platform':'xbox360','mode':'no_mercy','title_id':re_switch.RE6_TITLE_ID}},
    {'re6':{'platform':'switch','mode':'mercenaries','title_id':re_switch.RE6_TITLE_ID}}])
def test_edition_preference_rejects_ambiguous_or_unreviewed_values(preference):
    with pytest.raises(ValueError):M.normalize({'preferred_editions':preference})


def test_re6_switch_no_mercy_is_an_edition_too_alone_or_beside_re5():
    both={**PREFERENCE,**RE6_PREFERENCE}
    assert M.normalize({'preferred_editions':RE6_PREFERENCE})['preferred_editions']==RE6_PREFERENCE
    assert M.normalize({'preferred_editions':both})['preferred_editions']==both
    native=M.TITLES['re6']
    spec=re_switch.preferred_spec('re6',native,{'preferred_editions':both})
    assert spec['platform']=='switch' and spec['map_id']==re_switch.RE6_TITLE_ID=='01002A000CD48000'
    assert spec['game_ids']==(re_switch.RE6_GAME_ID,) and spec['driver']=='gbox.mercs.titles.re6_switch'
    assert spec['playable'] is True and 'reason' not in spec and spec['modes']==['no_mercy']
    assert re_switch.preferred_spec('re6',native,{'preferred_editions':PREFERENCE}) is native   # only RE5 chosen
    assert M.title_spec('re6',{'preferred_editions':both})==spec
    assert native['playable'] is False and native['map_id']=='BH6'          # the Xbox 360 entry is unchanged
    assert native['backends']['switch']['game_id']==re_switch.RE6_GAME_ID


def test_re6_switch_preference_is_per_host_and_never_falls_back_to_the_xbox_360_disc():
    store,w,*_=rig()
    cfg=M.configure(store,w['name'],{'titles':['re6'],'preferred_editions':RE6_PREFERENCE})
    re6=next(r for r in M.inventory(store,w,cfg) if r['title']=='re6')
    assert re6['platform']=='switch' and re6['map_id']==re_switch.RE6_TITLE_ID and re6['preferred_mode']=='no_mercy'
    assert not re6['playable'] and re6['reason']=='The verified game revision is absent from the catalog'
    assert re6['preparation']['strategy']=='native_menus_from_boot' and 're6_switch' in re6['preparation']['reason']
    assert M.choose(store,w,random.Random(0),cfg) is None
    assert M.settings(store,'another-host')['preferred_editions']=={}


def test_a_re6_switch_round_boundary_names_the_switch_title_id():
    import time
    from tests.test_mercmode import playing,boundary
    store,w,saver,calls,now,tick,run,job=playing()
    run=run|{'mercmode':{'title':'re6','map_id':re_switch.RE6_TITLE_ID,'rounds_per_title':1},
             'playing_since':time.time()-200}
    body=boundary(run,time.time(),screen='dead',playing_observed=True,player_verified=True,hp=0)
    receipt=M.accept_boundary(store,run,body,parent_job=job,now=time.time())
    assert receipt['map_id']==re_switch.RE6_TITLE_ID
    with pytest.raises(ValueError):
        M.accept_boundary(store,run,body|{'map_id':'BH6'},parent_job=job,now=time.time())


def test_the_prepare_receipt_names_re6_switch_by_its_title_id():
    from gbox.tools import _prepare_title
    assert _prepare_title({'game_id':re_switch.RE6_GAME_ID,'title':'Resident Evil 6'})==re_switch.RE6_TITLE_ID
    assert _prepare_title({'game_id':re_switch.RE5_GAME_ID})==re_switch.RE5_TITLE_ID
