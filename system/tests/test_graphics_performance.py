from types import SimpleNamespace

import pytest

from gbox import adapters, graphics, rewind, tools, provision
from gbox.config import Config, EmulatorConfig
from gbox.registry import Ctx, REGISTRY


@pytest.fixture(autouse=True)
def local_executable(monkeypatch):
    monkeypatch.setattr(provision, 'retroarch_exe', lambda cfg: 'retroarch')


def test_performance_preset_is_applied_to_launch_and_disables_both_rewind_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, 'HOST_OS', 'linux')
    cfg = Config(data_dir=tmp_path)
    graphics.save(cfg, 'pso', graphics.performance_preset())
    for platform in ('dreamcast', 'psx'):
        adapter = adapters.RetroArchAdapter(EmulatorConfig(adapter='retroarch', executable='retroarch'), cfg, platform)
        adapter.game_id = 'pso'
        text = adapter._write_cfg().read_text()
        assert 'video_shader_enable = "false"' in text
        assert 'fps_show = "true"' in text and 'video_font_enable = "true"' in text
        assert 'rewind_enable = "false"' in text and not adapter.rewind_on
        assert adapter.cpu_priority == 'above_normal'
        sid = 'test-' + platform
        try:
            assert rewind.start(sid, adapter, cfg, threads=False)['rewind'] == 'off'
            assert rewind.ACTIVE[sid].ring is None
        finally:
            rewind.stop(sid)
    # Other games retain their own defaults.
    assert graphics.get(cfg, 'other')['rewind_mode'] == 'auto'


def test_core_options_are_isolated_between_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, 'HOST_OS', 'linux')
    cfg = Config(data_dir=tmp_path)
    shared = cfg.runtime / 'retroarch' / 'core-options.cfg'
    shared.parent.mkdir(parents=True)
    original = 'reicast_enable_rttb = "disabled"\ncustom_option = "keep"\n'
    shared.write_text(original)
    one = adapters.RetroArchAdapter(EmulatorConfig(adapter='retroarch'), cfg, 'dreamcast', port=12341)
    two = adapters.RetroArchAdapter(EmulatorConfig(adapter='retroarch'), cfg, 'psx', port=12342)
    first = one._write_cfg()
    co = shared.with_name('session-12341-core-options.cfg')
    before = co.read_text()
    second = two._write_cfg()
    assert first != second and co.read_text() == before
    assert 'custom_option = "keep"' in before and 'reicast_enable_rttb = "enabled"' in before
    assert shared.read_text() == original


def test_tool_presets_reset_and_validation(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    monkeypatch.setattr(graphics, 'gpu', lambda: {'name': 'GPU', 'vram_mb': 8192})
    monkeypatch.setitem(tools.SESSIONS, 'w-s', (SimpleNamespace(name='retroarch'), {'game_id': 'pso'}))
    run = REGISTRY['graphics'].fn
    def call(op, prefs=None):
        return run(tools.GraphicsIn(game_id='pso', session_id='w-s', op=op, prefs=prefs or {}), Ctx(cfg))['result']
    assert call('performance')['prefs']['rewind_mode'] == 'off'
    assert call('best')['prefs']['rewind_mode'] == 'auto'
    assert call('reset')['prefs']['rewind_mode'] == 'auto'
    assert not call('get')['restart_needed']
    with pytest.raises(ValueError):
        call('set', {'res_scale': 200})  # RetroArch cannot consume the RPCS3 scale control.
    with pytest.raises(ValueError):
        call('set', {'show_fps': 1})  # bool, not an integer or truthy string


def test_diagnostics_reports_cpu_pressure_without_claiming_fps(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, 'cpu_percent', lambda **kw: 100)
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(percent=75, available=1024**3))
    result = graphics.diagnose()
    assert result['cpu_pct'] == 100 and result['fps'] is None
    assert any('CPU is saturated' in warning for warning in result['warnings'])


def test_gpu_inventory_is_cached_but_refreshes(monkeypatch):
    calls, now = [], [10]
    monkeypatch.setattr(graphics, '_GPU_CACHE', None)
    monkeypatch.setattr(graphics, '_GPU_EXPIRES', 0)
    monkeypatch.setattr(graphics.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(graphics, '_read_gpu', lambda: calls.append(1) or {'name': 'GPU', 'vram_mb': 8192})
    result = graphics.gpu()
    result['name'] = 'caller changed it'
    assert graphics.gpu()['name'] == 'GPU' and len(calls) == 1
    now[0] = 71
    graphics.gpu()
    assert len(calls) == 2


def test_windows_launch_priority_is_bounded_and_preserves_creation_flags(monkeypatch):
    import subprocess
    seen = {}
    monkeypatch.setattr(adapters, 'HOST_OS', 'windows')
    monkeypatch.setattr(graphics, 'prefer_gpu', lambda exe: True)
    monkeypatch.setattr(adapters, 'hidden_start', lambda: None)
    monkeypatch.setattr(adapters, 'keep_offscreen', lambda pid: None)
    monkeypatch.setattr(subprocess, 'ABOVE_NORMAL_PRIORITY_CLASS', 0x8000, raising=False)
    monkeypatch.setattr(subprocess, 'Popen', lambda argv, **kw: seen.update(kw) or SimpleNamespace(pid=1))
    adapters._popen(SimpleNamespace(cpu_priority='above_normal'), ['retroarch'], creationflags=0x200)
    assert seen['creationflags'] == 0x8200
    adapters._popen(SimpleNamespace(cpu_priority='normal'), ['retroarch'], creationflags=0x200)
    assert seen['creationflags'] == 0x200
