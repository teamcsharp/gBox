import asyncio
import json

import httpx
import pytest


def test_mcp_discovers_broadcast_without_switching_program(monkeypatch):
    pytest.importorskip('mcp')
    from mcp.client import Client
    from gbox.mcp_server import build
    seen = []

    def handler(req):
        seen.append((req.method,req.url.path))
        assert req.method == 'GET'
        if req.url.path == '/api/registry':
            return httpx.Response(200,json={'tools':[]})
        assert req.headers['x-gbox-actor'] == 'mcp'
        return httpx.Response(200,json={'program':{'session_id':'test'},'feeds':[]})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw: original(*a,**kw,transport=httpx.MockTransport(handler)))

    async def check():
        async with Client(build('http://fixture','fixture')) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert {'get_broadcast_feeds','get_broadcast_status'} <= names
            for name in ['get_broadcast_feeds','get_broadcast_status']:
                result = await client.call_tool(name,{})
                assert json.loads(result.content[0].text)['program']['session_id'] == 'test'

    asyncio.run(check())
    assert ('GET','/api/broadcast/feeds') in seen and ('GET','/api/broadcast') in seen
