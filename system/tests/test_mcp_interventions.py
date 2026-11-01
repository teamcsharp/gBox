import asyncio
import json
import uuid

import httpx
import pytest


@pytest.mark.parametrize('op,fields,args', [('equip_primary', {'item': 25}, {'item': 25}),
    ('set_infinite_ammo', {'enabled': True}, {'enabled': True})])
def test_mcp_weapon_selection_preserves_click_identity_and_native_item(monkeypatch, op, fields, args):
    pytest.importorskip('mcp')
    from mcp.client import Client
    from gbox.mcp_server import build
    seen = []
    rid = str(uuid.uuid4())

    def handler(request):
        if request.url.path == '/api/registry':
            return httpx.Response(200, json={'tools': []})
        assert request.headers['x-gbox-actor'] == 'mcp'
        assert request.url.path == '/api/sessions/worker-game/interventions'
        if request.method == 'GET':
            return httpx.Response(200, json={'capabilities': ['equip_primary'],
                'options': {'weapons': [{'item': 25, 'weapon': 'Hydra'}]}})
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={'request': dict(body, state='queued')})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw:
        original(*a, **kw, transport=httpx.MockTransport(handler)))

    async def check():
        async with Client(build('http://fixture', 'fixture')) as client:
            status = await client.call_tool('game_intervention', {'session_id': 'worker-game', 'op': 'status'})
            assert json.loads(status.content[0].text)['options']['weapons'][0]['item'] == 25
            result = await client.call_tool('game_intervention', {'session_id': 'worker-game',
                'op': op, **fields, 'request_id': rid})
            assert json.loads(result.content[0].text)['request']['state'] == 'queued'

    asyncio.run(check())
    assert seen == [{'op': op, 'request_id': rid, 'args': args}]
