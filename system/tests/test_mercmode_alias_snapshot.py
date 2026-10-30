"""Status polls must not do a database lookup for each historical worker hop."""
from gbox import mercmode as M, screensaver as S
from gbox.store import Store


def test_snapshot_retains_host_cycle_and_depth_boundaries(tmp_path):
    store = Store(tmp_path)
    try:
        worker = {'id': 'current', 'name': 'Spark'}
        store.put('worker_alias', 'old', {'to': 'current', 'name': 'Spark'})
        store.put('worker_alias', 'foreign', {'to': 'current', 'name': 'i9'})
        store.put('worker_alias', 'cycle-a', {'to': 'cycle-b', 'name': 'Spark'})
        store.put('worker_alias', 'cycle-b', {'to': 'cycle-a', 'name': 'Spark'})
        for i in range(9):
            store.put('worker_alias', f'chain{i}', {'to': f'chain{i+1}' if i < 8 else 'current', 'name': 'Spark'})
        snapshot = M.alias_snapshot(store)
        match = M._host_matcher(store, worker, snapshot)
        for source in ['current', 'old', 'foreign', 'cycle-a', 'absent', '', None, *[f'chain{i}' for i in range(9)]]:
            assert match(source) == M._same_host_worker(store, source, worker)
        assert match('old') and not match('foreign') and not match('cycle-a')
        assert not match('chain0') and match('chain8')
        # Each computation uses consistent evidence; the next one sees a new registration.
        store.put('worker_alias', 'old', {'to': 'current', 'name': 'i9'})
        assert match('old')
        assert not M._host_matcher(store, worker)('old')
    finally:
        store.close()


def test_status_reads_aliases_once_for_all_hosts_and_titles(tmp_path, monkeypatch):
    store = Store(tmp_path)
    try:
        hosts = [{'id': f'w{i}', 'name': f'pc{i}', 'os': 'linux', 'online': True,
                  'tools': ['launch_game', 'autoplay']} for i in range(3)]
        gids = [M.TITLES[t]['game_ids'][0] for t in ('re4', 're5')]
        for title in ('re4', 're5'):
            spec = M.TITLES[title]
            gid = spec['game_ids'][0]
            store.upsert_catalog([{'game_id': gid, 'title': spec['name'], 'platform': spec['platform'], 'library': 'test'}])
        for h in hosts:
            for i in range(30):
                source = f'{h["id"]}old{i}'
                # Foreign history is rejected before a late, verified prior launch.
                store.put('worker_alias', source, {'to': h['id'], 'name': 'another-pc' if i < 29 else h['name']})
                for n, gid in enumerate(gids):
                    sid = f'{source}-launch{n}'
                    store.put('session', sid, {'session_id': sid, 'game_id': gid, 'state': 'ended'})
        reads = []
        real_rows, real_get = store.rows, store.get
        def rows(kind):
            if kind == 'worker_alias': reads.append(kind)
            return real_rows(kind)
        def get(kind, key):
            assert kind != 'worker_alias', 'Status performed a per-hop database lookup'
            return real_get(kind, key)
        monkeypatch.setattr(store, 'rows', rows)
        monkeypatch.setattr(store, 'get', get)
        saver = S.Screensaver(store, None, None, lambda: hosts)
        result = saver.mercmode_status(fresh=True)
        assert len(reads) == 1
        for host in result['hosts']:
            titles = {r['title']: r for r in host['titles']}
            assert titles['re4']['rom_access']['session_id'] == f'{host["id"]}old29-launch0'
            assert titles['re5']['rom_access']['session_id'] == f'{host["id"]}old29-launch1'
    finally:
        store.close()
