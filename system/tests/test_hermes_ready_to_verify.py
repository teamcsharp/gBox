"""#1308: tickets whose published fix is on main must be pointed back at verification."""
import asyncio
import json

import httpx
import pytest

from gbox import hermes_merges


def _state(tmp_path, reported):
    (tmp_path / 'branches.json').write_text(json.dumps({'reported': reported, 'checked_at': 1.0}))
    return tmp_path


def test_on_main_requests_keeps_only_on_main_states(tmp_path):
    root = _state(tmp_path, {'a': 'on_main:' + 'a' * 40, 'b': 'review:33:' + 'b' * 40,
                             'c': 'closed:26:' + 'c' * 40, 'd': 'unchanged:' + 'd' * 40,
                             'e': 'stranded:' + 'e' * 40, 'f': None})
    assert hermes_merges.on_main_requests(root) == {'a': 'a' * 40}


@pytest.mark.parametrize('content', [None, '', '{not json', '[]', '{"reported": [1, 2]}'])
def test_on_main_requests_fails_open(tmp_path, content):
    if content is not None:
        (tmp_path / 'branches.json').write_text(content)
    assert hermes_merges.on_main_requests(tmp_path) == {}


def _rows():
    def row(rid, number, created):
        return {'id': rid, 'number': number, 'title': f'ticket {number}', 'body': 'x', 'status': 'in_progress',
                'source': 'chat', 'created': created, 'messages': [{'author': 'operator', 'ts': 1.0}]}
    return [row('new', 1308, 3), row('mid', 1300, 2), row('old', 1155, 1)]


def _serve(monkeypatch, tmp_path, reported):
    if reported is not None:
        _state(tmp_path, reported)
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))

    def handler(req):
        if req.url.path == '/api/registry':
            return httpx.Response(200, json={'tools': []})
        if req.url.path == '/api/requests':
            return httpx.Response(200, json=_rows())
        if req.url.path == '/api/tasks':
            return httpx.Response(200, json={'jobs': [], 'hermes': []})
        raise AssertionError(req.url.path)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda *a, **k: original(*a, **k, transport=httpx.MockTransport(handler)))


def _call(name, args):
    from mcp.client import Client
    from gbox.mcp_server import build

    async def go():
        async with Client(build('http://fixture', 'fixture')) as client:
            return json.loads((await client.call_tool(name, args)).content[0].text)
    return asyncio.run(go())


def test_list_requests_marks_on_main_tickets_and_lists_them_beyond_the_page(monkeypatch, tmp_path):
    pytest.importorskip('mcp')
    _serve(monkeypatch, tmp_path, {'old': 'on_main:' + '1' * 40, 'mid': 'review:33:' + '2' * 40,
                                   'gone': 'on_main:' + '3' * 40})
    out = _call('list_requests', {'limit': 1})
    assert [i['number'] for i in out['items']] == [1308]
    assert 'hermes_on_main' not in out['items'][0]
    # #1155 is off this one-item page, but the whole-inbox list still names it; a done ticket ('gone') is absent
    assert out['ready_to_verify'] == [{'id': 'old', 'number': 1155, 'title': 'ticket 1155',
                                       'status': 'in_progress', 'sha': '1' * 12}]
    page = {i['number']: i for i in _call('list_requests', {'limit': 20})['items']}
    assert page[1155]['hermes_on_main']['sha'] == '1' * 40
    assert 'verify the acceptance criteria live' in page[1155]['hermes_on_main']['note']
    assert '111111111111' in page[1155]['hermes_on_main']['note']
    assert 'hermes_on_main' not in page[1300] and 'hermes_on_main' not in page[1308]


def test_list_requests_without_branch_state_is_unchanged(monkeypatch, tmp_path):
    pytest.importorskip('mcp')
    _serve(monkeypatch, tmp_path, None)
    out = _call('list_requests', {'limit': 20})
    assert 'ready_to_verify' not in out
    assert [i['number'] for i in out['items']] == [1308, 1300, 1155]
    assert not any('hermes_on_main' in i for i in out['items'])


def test_tool_description_and_task_mode_prompt_point_at_verification():
    from pathlib import Path
    from gbox import mcp_server
    assert 'ready_to_verify' in mcp_server.CONVENIENCE['list_requests'][0]
    prompt = (Path(__file__).resolve().parents[1] / 'hermes/gbox/TASK_MODE.md').read_text()
    assert 'ready_to_verify' in prompt and 'hermes_on_main' in prompt
