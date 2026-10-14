import base64
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from test_build_report_images import png
from gbox.server import create_app


@pytest.mark.parametrize('covered,source,expected', [
    (1, 'desktop-compositor', 409), (2, 'desktop-compositor', 409),
    (0, 'desktop-compositor', 200), (9, 'window-surface', 200),
    (0, 'chromium-gpu-surface', 200),
])
def test_report_never_accepts_a_known_partially_covered_desktop_frame(cfg, covered, source, expected):
    app=create_app(cfg);store=app.state.store
    sid='fixture-report'
    store.put('session',sid,{'session_id':sid,'game_id':'fixture','state':'running'})
    endpoint=next(r.endpoint for r in app.routes if getattr(r,'path','')=='/api/sessions/{sid}/report-frame')
    capture=dict(zip(endpoint.__code__.co_freevars,endpoint.__closure__))['_session_png'].cell_contents
    closure=dict(zip(capture.__code__.co_freevars,capture.__closure__))
    raw=png('blue')
    ref=store.put_artifact(raw,'game.png','image/png',{})
    def submit(*a,**kw):
        store.put('job','capture',{'id':'capture','state':'succeeded','output':{
            'sha256':ref.sha256,'mean_luma':60,'capture_source':source,'covered':covered}})
        return SimpleNamespace(id='capture')
    closure['submit'].cell_contents=submit
    client=TestClient(app,headers={'Authorization':'Bearer '+cfg.token()})
    response=client.post(f'/api/sessions/{sid}/report-frame')
    assert response.status_code==expected,response.text
    if expected==200:assert base64.b64decode(response.json()['image_b64'])==raw
    else:assert 'covers part of the game' in response.json()['detail']
    assert not store.all('request')
