"""A reviewer and operator must not overwrite each other's checkpoint."""
from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi.testclient import TestClient
from gbox.server import create_app


def test_concurrent_messages_preserve_both_authors(cfg, monkeypatch):
    app = create_app(cfg)
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    rid = client.post('/api/requests', json={'title': 'Review', 'body': 'Task'}).json()['id']
    store = app.state.store
    original = store.get
    first_read, second_done = threading.Event(), threading.Event()
    guard = threading.Lock()
    reads = 0

    def get(kind, key):
        nonlocal reads
        value = original(kind, key)
        if kind == 'request' and key == rid:
            with guard:
                reads += 1
                first = reads == 1
            if first:
                first_read.set()
                # Without the transaction lock the second writer commits here,
                # then gets overwritten by the first writer's stale JSON copy.
                second_done.wait(.3)
        return value

    monkeypatch.setattr(store, 'get', get)
    def post(author, text):
        r = client.post(f'/api/requests/{rid}/messages', json={'author': author, 'text': text})
        assert r.status_code == 200
        if author == 'operator':
            second_done.set()

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(post, 'agent', 'Cloud review checkpoint')
        assert first_read.wait(2)
        second = pool.submit(post, 'operator', 'Operator guidance')
        first.result(5); second.result(5)
    messages = original('request', rid)['messages']
    assert {'Cloud review checkpoint', 'Operator guidance'} <= {m['text'] for m in messages}
