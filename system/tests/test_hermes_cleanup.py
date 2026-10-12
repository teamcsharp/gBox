import datetime as dt
import os
import signal
import sqlite3

import pytest

from gbox import hermes_cleanup, hermes_feedback

RID = 'cca882340c49410c'
BOOT = 1_791_000_000.0
TCK = os.sysconf('SC_CLK_TCK')
NOW = BOOT + 86_400


def _proc(tmp_path, procs, tcp_rows):
    """A fake /proc: procs = {pid: (cwd, cmdline list, started_epoch, [socket inodes])}."""
    proc = tmp_path / 'proc'
    (proc / 'net').mkdir(parents=True)
    (proc / 'stat').write_text(f'cpu 1 2 3\nbtime {int(BOOT)}\n')
    header = '  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n'
    lines = [f'   0: 00000000:{port:04X} 00000000:0000 {st} 00000000:00000000 00:00000000 00000000  1000        0 {inode}'
             for port, st, inode in tcp_rows]
    (proc / 'net/tcp').write_text(header + '\n'.join(lines) + '\n')
    for pid, (cwd, cmd, started, inodes) in procs.items():
        _add(proc, pid, cwd, cmd, started, inodes)
    return proc


def _add(proc, pid, cwd, cmd, started, inodes):
    d = proc / str(pid)
    (d / 'fd').mkdir(parents=True, exist_ok=True)
    if not (d / 'cwd').is_symlink():
        os.symlink(cwd, d / 'cwd')
    (d / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in cmd) + b'\0')
    ticks = int((started - BOOT) * TCK)
    rest = ' '.join(['0'] * 17)
    (d / 'stat').write_text(f'{pid} (python3 x) S 1 {rest} {ticks} 0 0\n')
    for n, inode in enumerate(inodes):
        os.symlink(f'socket:[{inode}]', d / 'fd' / str(n + 3))


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / 'gbox-hermes-tasks'
    (root / RID / 'system/clients/web').mkdir(parents=True)
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'state'))
    (tmp_path / 'state').mkdir()
    old = NOW - 23 * 3600
    proc = _proc(tmp_path, {
        # The #1301 case: cwd elsewhere, worktree only in the command line.
        238808: ('/home/u/.hermes/hermes-agent',
                 ['python3', '-m', 'http.server', '8124', '-d', f'{root}/{RID}/system/clients/web'], old, [111]),
        2387: ('/home/u/ComfyUI', ['python', 'main.py', '--port', '8188'], old, [222]),
        3759599: ('/home/u/gBox/system', ['python', '-m', 'gbox', 'serve'], old, [333]),
        4000: (f'{root}/{RID}/system', ['python', 'worker.py'], old, []),   # no listening socket
        4001: (f'{root}/{RID}/system', ['python', '-m', 'uvicorn', 'x'], old, [444]),   # established only
    }, [(8124, '0A', 111), (8188, '0A', 222), (8765, '0A', 333), (18771, '01', 444)])
    return root, proc


def test_owner_reads_cwd_command_line_and_option_values(tmp_path):
    root = '/h/gbox-hermes-tasks'
    assert hermes_cleanup.owner({'cwd': f'{root}/{RID}/system', 'cmdline': ['python']}, root) == RID
    assert hermes_cleanup.owner({'cwd': '/', 'cmdline': ['x', f'--directory={root}/{RID}/system']}, root) == RID
    assert hermes_cleanup.owner({'cwd': '/', 'cmdline': ['x', '-d', f'{root}/{RID}/../{RID}/a']}, root) == RID
    assert hermes_cleanup.owner({'cwd': f'{root}/scratch', 'cmdline': []}, root) == ''
    assert hermes_cleanup.owner({'cwd': '/h/gbox-hermes-tasks-old/x', 'cmdline': ['x']}, root) is None
    assert hermes_cleanup.owner({'cwd': '/h/gBox/system', 'cmdline': ['gbox', 'serve', 'rel/path']}, root) is None


def test_listeners_finds_only_listening_processes(world):
    _, proc = world
    found = {p['pid']: p for p in hermes_cleanup.listeners(proc)}
    assert sorted(found) == [2387, 238808, 3759599]
    assert found[238808]['ports'] == [8124]
    assert abs(found[238808]['started'] - (NOW - 23 * 3600)) < 1


def test_leftovers_keeps_young_servers_and_ones_a_running_run_may_own(world):
    root, proc = world
    procs = hermes_cleanup.listeners(proc)
    picked = hermes_cleanup.leftovers(procs, root, running_since=None, now=NOW)
    assert [(p['pid'], p['request_id']) for p in picked] == [(238808, RID)]
    # A run that started before the server could have started it: keep it.
    assert hermes_cleanup.leftovers(procs, root, running_since=NOW - 24 * 3600, now=NOW) == []
    # A run that started after the server could not have: stop it.
    assert len(hermes_cleanup.leftovers(procs, root, running_since=NOW - 60, now=NOW)) == 1
    # Too young to judge.
    assert hermes_cleanup.leftovers(procs, root, running_since=None, now=NOW - 23 * 3600 + 300) == []


def test_running_since_reads_running_cron_executions(tmp_path):
    (tmp_path / 'cron').mkdir()
    db = sqlite3.connect(tmp_path / 'cron/executions.db')
    db.execute('CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT, started_at TEXT)')
    iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()
    db.executemany('INSERT INTO executions VALUES (?,?,?,?)', [
        ('a', 'j', 'completed', iso(NOW - 900)), ('b', 'j', 'running', iso(NOW - 300)),
        ('c', 'k', 'claimed', iso(NOW - 120))])
    db.commit()
    db.close()
    assert hermes_cleanup.running_since(tmp_path) == pytest.approx(NOW - 300)
    assert hermes_cleanup.running_since(tmp_path / 'missing') is None


def test_stop_terminates_kills_or_refuses_a_reused_pid(world):
    _, proc = world
    p = next(x for x in hermes_cleanup.listeners(proc) if x['pid'] == 238808)
    sent = []

    def exits(pid, sig):
        sent.append(sig)
        (proc / str(pid) / 'stat').unlink()   # the process went away
    assert hermes_cleanup.stop(p, proc=proc, kill=exits, sleep=lambda s: None) == 'terminated'
    assert sent == [signal.SIGTERM]

    _add(proc, 238808, '/x', ['python3'], p['started'], [])
    sent.clear()
    assert hermes_cleanup.stop(p, proc=proc, kill=lambda pid, sig: sent.append(sig),
                               sleep=lambda s: None) == 'killed'
    assert sent == [signal.SIGTERM, signal.SIGKILL]

    sent.clear()
    reused = p | {'started': p['started'] - 5000}
    assert hermes_cleanup.stop(reused, proc=proc, kill=lambda pid, sig: sent.append(sig)) == 'gone'
    assert sent == []


def test_sweep_stops_reports_once_and_throttles(world, tmp_path):
    root, proc = world
    sent, posts = [], []

    def kill(pid, sig):
        sent.append((pid, sig))
        (proc / str(pid) / 'stat').unlink()

    api = lambda path, body=None: posts.append((path, body))
    dry = hermes_cleanup.sweep(api, home=tmp_path / 'nohome', root=root, now=NOW, dry_run=True, proc=proc, kill=kill)
    assert [p['pid'] for p in dry['leftovers']] == [238808] and sent == [] and posts == []

    out = hermes_cleanup.sweep(api, home=tmp_path / 'nohome', root=root, now=NOW, proc=proc, kill=kill,
                               sleep=lambda s: None)
    assert out['stopped'] == [{'pid': 238808, 'ports': [8124], 'request_id': RID, 'result': 'terminated'}]
    assert sent == [(238808, signal.SIGTERM)]
    assert len(posts) == 1 and posts[0][0] == f'/api/requests/{RID}/messages'
    text = posts[0][1]['text']
    assert text.startswith(hermes_cleanup.MARKER) and 'port 8124' in text and 'http.server 8124' in text
    assert posts[0][1]['task_step']['status'] == 'finished'

    again = hermes_cleanup.sweep(api, home=tmp_path / 'nohome', root=root, now=NOW + 60, proc=proc, kill=kill)
    assert again['status'] == 'skipped' and len(posts) == 1


def test_a_failed_report_does_not_undo_the_stop(world, tmp_path):
    root, proc = world

    def kill(pid, sig):
        (proc / str(pid) / 'stat').unlink()

    def api(path, body=None):
        raise OSError('inbox down')
    out = hermes_cleanup.sweep(api, home=tmp_path / 'nohome', root=root, now=NOW, proc=proc, kill=kill,
                               sleep=lambda s: None)
    assert out['stopped'][0]['result'] == 'terminated' and out['errors'] == [f'{RID}: OSError']


def test_missing_proc_finds_nothing(tmp_path):
    assert hermes_cleanup.listeners(tmp_path / 'noproc') == []


def test_finalize_cleanup_never_blocks_routing(monkeypatch):
    def fail(*a, **k):
        raise OSError('no proc')
    monkeypatch.setattr(hermes_cleanup, 'sweep', fail)
    assert hermes_feedback.finalize_cleanup() == {'status': 'deferred', 'error_type': 'OSError'}
