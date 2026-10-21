"""No native emulator: profile locks and failed-start cleanup regressions."""
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from gbox import adapters, provision, rpcs3_profile as P
from gbox.config import Config


def native(tmp_path):
    path = tmp_path / 'cache' / 'rpcs3' / 'RPCS3.buf'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'leave this inode and content intact')
    return path


def test_native_probe_leaves_persistent_file_and_missing_path_untouched(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(P, '_exclusive', lambda fd: seen.append(os.fstat(fd).st_ino))
    P.native_available(tmp_path / 'absent')
    assert not (tmp_path / 'absent').exists()
    path = native(tmp_path)
    before = path.stat()
    P.native_available(tmp_path / 'cache')
    assert seen == [before.st_ino]
    assert path.stat().st_ino == before.st_ino
    assert path.read_bytes() == b'leave this inode and content intact'


@pytest.mark.parametrize('error', [BlockingIOError('busy'), PermissionError('denied'), OSError('unknown lock failure')])
def test_native_probe_fails_closed_and_never_removes_file(tmp_path, monkeypatch, error):
    path = native(tmp_path)
    def reject(fd):
        raise error
    monkeypatch.setattr(P, '_exclusive', reject)
    with pytest.raises(P.ProfileBusy, match='cannot be verified'):
        P.native_available(tmp_path / 'cache')
    assert path.read_bytes() == b'leave this inode and content intact'


def test_native_open_permissions_are_not_misclassified_as_available(tmp_path, monkeypatch):
    path = native(tmp_path)
    def reject(*args, **kwargs):
        raise PermissionError('no write access')
    monkeypatch.setattr(P, '_open', reject)
    with pytest.raises(P.ProfileBusy, match='Cannot verify'):
        P.native_available(tmp_path / 'cache')
    assert path.exists()


def test_native_probe_refuses_a_replaced_inode(tmp_path, monkeypatch):
    path = native(tmp_path)
    original = P.Path.lstat
    replaced = [False]
    def replace(_):
        replaced[0] = True
    def changed(self):
        current = original(self)
        if self == path and replaced[0]:
            return SimpleNamespace(st_dev=current.st_dev, st_ino=current.st_ino + 1)
        return current
    monkeypatch.setattr(P, '_exclusive', replace)
    monkeypatch.setattr(P.Path, 'lstat', changed)
    with pytest.raises(P.ProfileBusy, match='stable regular file'):
        P.native_available(tmp_path / 'cache')
    assert path.read_bytes() == b'leave this inode and content intact'


def test_open_is_nonblocking_without_create_or_truncate(tmp_path, monkeypatch):
    path = native(tmp_path)
    opened = []
    real_open = P.os.open
    def capture(path, flags, mode):
        opened.append(flags)
        return real_open(path, flags, mode)
    monkeypatch.setattr(P.os, 'open', capture)
    monkeypatch.setattr(P, '_exclusive', lambda _: None)
    P.native_available(tmp_path / 'cache')
    assert not opened[0] & (os.O_CREAT | os.O_TRUNC)
    if hasattr(os, 'O_NONBLOCK'):
        assert opened[0] & os.O_NONBLOCK


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux special-file behavior')
def test_fifo_native_lock_is_refused_without_open_blocking(tmp_path):
    path = tmp_path / 'cache' / 'rpcs3' / 'RPCS3.buf'
    path.parent.mkdir(parents=True)
    os.mkfifo(path)
    with pytest.raises(P.ProfileBusy, match='Cannot verify'):
        P.native_available(tmp_path / 'cache')
    assert path.exists()


def test_profile_lease_closes_failed_handle_and_releases_explicitly(tmp_path, monkeypatch):
    held = []
    monkeypatch.setattr(P, '_exclusive', lambda fd: held.append(fd))
    lease = P.Lease(tmp_path / 'home', tmp_path / 'cache').acquire()
    fd = lease.fd
    assert held == [fd]
    with pytest.raises(P.ProfileBusy, match='already owns'):
        lease.acquire()
    lease.close()
    lease.close()
    with pytest.raises(OSError):
        os.fstat(fd)
    def fail(_):
        raise P.ProfileBusy('native owner')
    monkeypatch.setattr(P, 'native_available', fail)
    with pytest.raises(P.ProfileBusy, match='native owner'):
        lease.acquire()
    assert lease.fd is None


@pytest.mark.skipif(sys.platform != 'linux', reason='real Linux flock across processes')
def test_native_and_gbox_locks_exclude_other_processes_without_unlink(tmp_path):
    import fcntl
    path = native(tmp_path)
    with open(path, 'rb') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(P.ProfileBusy):
            P.native_available(tmp_path / 'cache')
    P.native_available(tmp_path / 'cache')
    lease = P.Lease(tmp_path / 'home', tmp_path / 'cache').acquire()
    code = ('import sys; from gbox.rpcs3_profile import Lease, ProfileBusy\n'
            'try: Lease(sys.argv[1],sys.argv[2]).acquire()\n'
            'except ProfileBusy: sys.exit(23)\n')
    try:
        child = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'home'), str(tmp_path / 'cache')],
                               capture_output=True, timeout=10)
        assert child.returncode == 23, child.stderr
    finally:
        lease.close()
    assert path.read_bytes() == b'leave this inode and content intact'


@pytest.fixture
def ad(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    instance = adapters.RPCS3LinuxAdapter(cfg)
    monkeypatch.setattr(adapters, 'HOST_OS', 'linux')
    monkeypatch.setattr(P, '_exclusive', lambda fd: None)
    return instance


def test_busy_profile_prevents_settings_display_and_spawn(ad, monkeypatch):
    def reject(_):
        raise P.ProfileBusy('native owner')
    monkeypatch.setattr(P, 'native_available', reject)
    monkeypatch.setattr(adapters.StandaloneAdapter, 'launch_game', lambda *a: pytest.fail('must not launch'))
    with pytest.raises(P.ProfileBusy, match='native owner'):
        ad.launch_game('/game/EBOOT.BIN')
    assert ad._profile_lease is None and ad.display is None
    assert not (ad.home / 'config.yml').exists()


def test_launcher_keeps_profile_until_verified_stop(ad, monkeypatch):
    calls = []
    proc = SimpleNamespace(pid=123, returncode=None, poll=lambda: proc.returncode)
    def spawn(self, rom):
        calls.append('spawn')
        self.proc = proc
        return {'pid': proc.pid}
    def stop(self):
        calls.append('stop')
        proc.returncode = 0
        return {'returncode': 0}
    monkeypatch.setattr(adapters.StandaloneAdapter, 'launch_game', spawn)
    monkeypatch.setattr(adapters.StandaloneAdapter, 'stop_game', stop)
    monkeypatch.setattr(ad, '_wait_guest_ready', lambda: calls.append('guest'))
    monkeypatch.setattr(ad, '_park_pointer', lambda: calls.append('pointer'))
    out = ad.launch_game('/game/EBOOT.BIN')
    assert out['ready'] == 'guest_memory' and ad._profile_lease.fd is not None
    with pytest.raises(P.ProfileBusy):
        ad.launch_game('/another/EBOOT.BIN')
    ad.stop_game()
    assert calls == ['spawn', 'guest', 'pointer', 'stop'] and ad._profile_lease is None


def test_failed_start_cleans_only_new_process_and_releases_after_exit(ad, monkeypatch):
    calls = []
    proc = SimpleNamespace(pid=123, returncode=None, poll=lambda: proc.returncode)
    def spawn(self, rom):
        self.proc = proc
        return {'pid': proc.pid}
    def fail():
        raise RuntimeError('fatal dialog, no guest')
    def stop(self):
        calls.append(self.proc.pid)
        proc.returncode = -15
        return {'returncode': -15}
    monkeypatch.setattr(adapters.StandaloneAdapter, 'launch_game', spawn)
    monkeypatch.setattr(adapters.StandaloneAdapter, 'stop_game', stop)
    monkeypatch.setattr(ad, '_wait_guest_ready', fail)
    with pytest.raises(RuntimeError, match='fatal dialog'):
        ad.launch_game('/game/EBOOT.BIN')
    assert calls == [123] and ad._profile_lease is None


def test_unconfirmed_stop_retains_profile(ad, monkeypatch):
    ad._profile_lease = P.Lease(provision.rpcs3_linux_home(ad.config), ad.env['XDG_CACHE_HOME']).acquire()
    ad.proc = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(adapters.StandaloneAdapter, 'stop_game', lambda self: {'returncode': None})
    with pytest.raises(RuntimeError, match='lease was retained'):
        ad.stop_game()
    assert ad._profile_lease.fd is not None
    ad._profile_lease.close()


def test_readiness_waits_for_guest_and_rejects_living_dialog(ad, monkeypatch):
    ad.proc = SimpleNamespace(poll=lambda: None)
    ad.boot_timeout_s = 1
    clock = [0.0]
    monkeypatch.setattr(adapters.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(adapters.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    probes = []
    def guest():
        probes.append(1)
        if len(probes) < 3:
            raise RuntimeError('not initialized')
        return 123, 0x300000000
    monkeypatch.setattr(ad, '_guest', guest)
    ad._wait_guest_ready()
    assert len(probes) == 3
    monkeypatch.setattr(ad, '_guest', lambda: (_ for _ in ()).throw(RuntimeError('error dialog')))
    with pytest.raises(RuntimeError, match='does not confirm a successful launch'):
        ad._wait_guest_ready()


def test_readiness_rejects_exited_process_without_guest_probe(ad, monkeypatch):
    ad.proc = SimpleNamespace(poll=lambda: 1)
    monkeypatch.setattr(ad, '_guest', lambda: pytest.fail('exited process cannot be ready'))
    with pytest.raises(RuntimeError, match='exited before'):
        ad._wait_guest_ready()


@pytest.mark.parametrize('fail_spawn', [False, True])
def test_state_reload_preserves_lease_and_cleans_a_failed_replacement(ad, tmp_path, monkeypatch, fail_spawn):
    state = ad.home / 'savestates' / 'game' / 'one.SAVESTAT'
    state.parent.mkdir(parents=True)
    state.write_bytes(b'state')
    ad._profile_lease = P.Lease(provision.rpcs3_linux_home(ad.config), ad.env['XDG_CACHE_HOME']).acquire()
    lease = ad._profile_lease
    old = SimpleNamespace(pid=1, returncode=None, poll=lambda: old.returncode)
    new = SimpleNamespace(pid=2, returncode=None, poll=lambda: new.returncode)
    ad.proc, ad.display, ad.log_path = old, SimpleNamespace(name=':99'), tmp_path / 'wrapper.log'
    calls = []
    def kill(proc):
        assert proc is old
        proc.returncode = 0
        calls.append('stop-old')
    def spawn(*args, **kwargs):
        assert old.poll() == 0 and lease.fd is not None
        calls.append('spawn')
        kwargs['stdout'].close()
        if fail_spawn:
            raise OSError('failed to spawn')
        return new
    def stop(self):
        calls.append('cleanup')
        self.proc.returncode = 0
        return {'returncode': 0}
    monkeypatch.setattr(adapters, '_kill_tree', kill)
    monkeypatch.setattr(adapters.subprocess, 'Popen', spawn)
    monkeypatch.setattr(adapters.StandaloneAdapter, 'stop_game', stop)
    monkeypatch.setattr(ad, '_wait_guest_ready', lambda: calls.append('guest'))
    monkeypatch.setattr(ad, '_park_pointer', lambda: None)
    if fail_spawn:
        with pytest.raises(OSError, match='failed to spawn'):
            ad.load_state()
        assert calls == ['stop-old', 'spawn', 'cleanup'] and ad._profile_lease is None
    else:
        assert ad.load_state()['pid'] == 2
        assert calls == ['stop-old', 'spawn', 'guest'] and ad._profile_lease is lease
        ad.stop_game()
