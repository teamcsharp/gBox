"""Mapped-but-black restarts: render evidence, ownership and one bounded retry."""
from io import BytesIO
from types import SimpleNamespace
import threading

from PIL import Image, ImageDraw
import pytest

from gbox import adapters, switch_nsp


STALL = '[2.645] Service.NVDRV nvhost_gpu ChannelSetTimeout\n[2.645] Service.NVDRV <Warning>'


def png(menu=False):
    image = Image.new('RGB', (320, 180), 'black')
    if menu:
        ImageDraw.Draw(image).rectangle((90, 50, 230, 130), fill=(40, 90, 150))
    out = BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


@pytest.fixture
def boot(monkeypatch):
    ad = adapters.SwitchLinuxAdapter.__new__(adapters.SwitchLinuxAdapter)
    ad.proc = SimpleNamespace(pid=10, poll=lambda: None)
    ad.rom, ad.debug, ad.paused, ad._stopped = 're5.nsp', False, False, False
    ad.restart_error, ad.restarts, ad._mem = None, 0, None
    ad._restart_lock = threading.RLock()
    clock, stopped, spawned = [0.0], [], []
    monkeypatch.setattr(adapters.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(adapters.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    monkeypatch.setattr(switch_nsp, 'title_id', lambda rom: '010018100CD46000')
    monkeypatch.setattr(ad, '_guest', lambda: (ad.proc.pid, {'lo': ad.proc.pid, 'hi': ad.proc.pid+100}))
    monkeypatch.setattr(ad, '_p', lambda *a: None)
    monkeypatch.setattr(ad, 'log_tail', lambda *a: STALL)
    monkeypatch.setattr(ad, '_boot_log_fresh', lambda: True)
    monkeypatch.setattr(ad, '_argv', lambda rom: ['eden', rom])
    monkeypatch.setattr(ad, '_coop_started', lambda: None)
    monkeypatch.setattr(ad, '_park_pointer', lambda: None)
    monkeypatch.setattr(ad, 'get_frame', lambda: png())

    def stop(proc):
        stopped.append(proc.pid)
        ad.proc = adapters._EdenRestarting(proc.pid)

    def spawn(argv):
        spawned.append(argv)
        ad.proc = SimpleNamespace(pid=10+len(spawned), poll=lambda: None)

    monkeypatch.setattr(ad, '_stop_eden', stop)
    monkeypatch.setattr(ad, '_spawn', spawn)
    return ad, clock, stopped, spawned


def test_static_visible_menu_passes_without_restart_or_full_timeout(boot, monkeypatch):
    ad, clock, stopped, spawned = boot
    monkeypatch.setattr(ad, 'get_frame', lambda: png(menu=True))
    arena, watch = ad._finish_restart(ad.proc)
    assert arena['lo'] == 10 and watch['rendered']
    assert adapters.BOOT_WATCH_SETTLE_S <= clock[0] < 12
    assert stopped == spawned == []


def test_mapped_black_gpu_stall_retries_same_launch_once_then_reports_final_process(boot, monkeypatch):
    ad, clock, stopped, spawned = boot
    monkeypatch.setattr(ad, 'get_frame', lambda: png(menu=ad.proc.pid == 11))
    arena, watch = ad._finish_restart(ad.proc)
    assert arena['lo'] == 11 and watch['rendered'] and ad.restarts == 1
    assert stopped == [10] and spawned == [['eden', 're5.nsp']]
    assert ad.restart_error is None


def test_second_black_stall_reports_failure_without_a_third_process(boot):
    ad, clock, stopped, spawned = boot
    with pytest.raises(adapters.EdenGpuInitStalled):
        ad._finish_restart(ad.proc)
    assert stopped == [10] and len(spawned) == 1
    assert 'again after one retry' in ad.restart_error


@pytest.mark.parametrize('reason', ['unknown', 'stale', 'progress', 'undecodable', 'nvdec', 'gray'])
def test_uncertain_black_boots_never_trigger_automatic_restart(boot, monkeypatch, reason):
    ad, clock, stopped, spawned = boot
    if reason == 'unknown':
        monkeypatch.setattr(ad, 'log_tail', lambda *a: 'nvhost_gpu initialized')
    elif reason == 'stale':
        monkeypatch.setattr(ad, '_boot_log_fresh', lambda: False)
    elif reason == 'progress':
        monkeypatch.setattr(ad, 'log_tail', lambda *a: STALL + str(clock[0]))
    elif reason == 'undecodable':
        monkeypatch.setattr(ad, 'get_frame', lambda: b'not an image')
    elif reason == 'nvdec':
        monkeypatch.setattr(ad, 'log_tail', lambda *a: STALL + '\nNvdec started')
    else:
        image = Image.new('RGB', (64, 64), 'gray')
        out = BytesIO()
        image.save(out, format='PNG')
        monkeypatch.setattr(ad, 'get_frame', lambda: out.getvalue())
    with pytest.raises(adapters.BootHung) as exc:
        ad._finish_restart(ad.proc)
    assert not isinstance(exc.value, adapters.EdenGpuInitStalled)
    assert stopped == spawned == []


@pytest.mark.parametrize('state', ['stopped', 'superseded', 'paused'])
def test_timeout_rechecks_ownership_and_pause_before_recovery(boot, monkeypatch, state):
    ad, clock, stopped, spawned = boot
    original = ad.proc

    def sleep(seconds):
        clock[0] += seconds
        if clock[0] >= adapters.BOOT_WATCH_S:
            if state == 'stopped':
                ad._stopped = True
            elif state == 'superseded':
                ad.proc = SimpleNamespace(pid=99, poll=lambda: None)
            else:
                ad.paused = True

    monkeypatch.setattr(adapters.time, 'sleep', sleep)
    if state == 'paused':
        assert ad._finish_restart(original)[1] == {'watched': False, 'paused': True}
    else:
        with pytest.raises(RuntimeError, match='cancelled'):
            ad._finish_restart(original)
    assert stopped == spawned == [] and ad.restart_error is None


def test_delayed_async_waiter_cannot_adopt_a_superseding_process(boot, monkeypatch):
    ad, clock, stopped, spawned = boot
    original = ad.proc
    ad.proc = SimpleNamespace(pid=99, poll=lambda: None)
    monkeypatch.setattr(ad, '_wait_guest_ready', lambda: pytest.fail('stale waiter reached the new process'))
    ad._settle(original)
    assert stopped == spawned == [] and ad.restart_error is None


def test_async_path_has_same_one_retry_budget_and_records_failure(boot):
    ad, clock, stopped, spawned = boot
    ad._settle(ad.proc)
    assert stopped == [10] and len(spawned) == 1
    assert 'again after one retry' in ad.restart_error


def test_failed_async_retry_spawn_exposes_stopped_process_instead_of_running_sentinel(boot, monkeypatch):
    ad, clock, stopped, spawned = boot
    original = ad.proc

    def failed_spawn(argv):
        original.poll = lambda: 1
        raise OSError('spawn failed')

    monkeypatch.setattr(ad, '_spawn', failed_spawn)
    ad._settle(original)
    assert ad.proc is original and ad.proc.poll() == 1
    assert stopped == [10] and ad.restart_error == 'spawn failed'


def test_synchronous_restart_returns_the_recovery_pid_and_keeps_display(boot, monkeypatch):
    ad, clock, stopped, spawned = boot
    display = SimpleNamespace(name=':99')
    ad.display, ad.overlay_build, ad.overlay_state = display, 'sonic', {'enabled': 'sonic'}
    monkeypatch.setattr(ad, '_check_overlay', lambda overlay: None)
    monkeypatch.setattr(ad, '_ensure', lambda: None)
    monkeypatch.setattr(ad, 'get_frame', lambda: png(menu=ad.proc.pid == 12))
    result = ad.restart_title()
    assert result['pid'] == 12 and result['previous_pid'] == 10 and result['restarts'] == 2
    assert result['boot_watch']['rendered'] and result['guest_arena'] == ['0xc', '0x70']
    assert ad.display is display and ad.overlay_build == 'sonic'
    assert stopped == [10, 11] and len(spawned) == 2


def test_memory_mapping_wait_never_restarts_or_spawns_another_waiter(boot, monkeypatch):
    ad, clock, stopped, spawned = boot
    ad.boot_timeout_s = 100

    def unavailable():
        raise RuntimeError('not mapped')

    monkeypatch.setattr(ad, '_guest', unavailable)
    with pytest.raises(RuntimeError, match='did not map guest memory'):
        ad._wait_guest_ready()
    assert stopped == spawned == []


def test_freshness_requires_a_log_written_after_this_spawn(boot, tmp_path, monkeypatch):
    ad, *_ = boot
    path = tmp_path / 'eden_log.txt'
    path.write_text(STALL)
    monkeypatch.setattr(ad, 'eden_log', lambda: path)
    ad._boot_spawn_wall = path.stat().st_mtime + 1
    assert not adapters.SwitchLinuxAdapter._boot_log_fresh(ad)
    ad._boot_spawn_wall = path.stat().st_mtime
    assert adapters.SwitchLinuxAdapter._boot_log_fresh(ad)
