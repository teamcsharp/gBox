import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('host,expected',[(None,'0.0.0.0'),('127.0.0.1','127.0.0.1')])
def test_mcp_http_can_bind_locally_without_changing_control_plane(monkeypatch,tmp_path,host,expected):
    pytest.importorskip('mcp')
    from gbox import __main__ as cli,mcp_server
    config=SimpleNamespace(data_dir=tmp_path,api_host='0.0.0.0',api_port=8765,public_url='',token=lambda:'fixture')
    monkeypatch.setenv('GBOX_TOKEN','fixture')
    monkeypatch.setattr(cli.cfgmod,'load',lambda _:config)
    calls=[]
    monkeypatch.setattr(mcp_server,'serve_http',lambda *a:calls.append(a))
    monkeypatch.setattr(sys,'argv',['gbox','mcp','--http','8766',*(['--host',host] if host else [])])
    cli.main()
    assert calls==[('http://127.0.0.1:8765','fixture',expected,8766)]
    assert config.api_host=='0.0.0.0'
