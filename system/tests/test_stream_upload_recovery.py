"""A stalled/rejected upload reconnects to the newest frame without restarting the game."""
from types import SimpleNamespace

import httpx
import pytest

from gbox import tools


@pytest.mark.parametrize('failure', ['write_timeout', 'rejected', 'early_response'])
def test_upload_recovers_with_bounded_writes_and_backoff(monkeypatch, failure):
    sid = 'worker-session'
    sessions = {sid: object()}
    monkeypatch.setattr(tools, 'SESSIONS', sessions)
    delays, packets, timeouts = [], [], []
    monkeypatch.setattr(tools.time, 'sleep', delays.append)
    stream = SimpleNamespace(seq=1, latest=b'old', wait=lambda seen, timeout: True)
    ad = SimpleNamespace(proc=SimpleNamespace(poll=lambda: None))

    class Client:
        def __init__(self, **kwargs):
            timeouts.append(kwargs['timeout'])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, *, content, headers):
            assert url == f'/api/sessions/{sid}/stream'
            packets.append(next(content))
            content.close()
            request = httpx.Request('POST', 'http://test' + url)
            if len(packets) == 1:
                stream.seq, stream.latest = 20, b'newest'
                if failure == 'write_timeout':
                    raise httpx.WriteTimeout('receiver stopped reading', request=request)
                return httpx.Response(503 if failure == 'rejected' else 200, request=request)
            sessions.pop(sid)
            return httpx.Response(200, request=request)

    monkeypatch.setattr(tools.httpx, 'Client', Client)
    tools._upload_stream_frames(sid, ad, stream, 'http://test', {})
    assert packets == [b'\0\0\0\x03old', b'\0\0\0\x06newest']
    assert delays == [1]
    assert len(timeouts) == 2
    assert all(timeout.read is None and 0 < timeout.write <= 10 for timeout in timeouts)
