"""#1216: Flycast sessions must keep render-to-texture results in emulated VRAM so save states replay correctly."""
from gbox import adapters
from gbox.adapters import RetroArchAdapter
from gbox.config import Config, EmulatorConfig


def _write(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    adapter = RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="retroarch", core="core"),
                               config=Config(data_dir=tmp_path), platform=platform)
    adapter._write_cfg()
    return adapter.config.runtime / "retroarch" / "core-options.cfg"


def test_dreamcast_forces_rtt_copy_and_unthreaded_rendering(tmp_path, monkeypatch):
    co = _write(tmp_path, monkeypatch, "dreamcast")
    text = co.read_text()
    assert 'reicast_enable_rttb = "enabled"' in text
    assert 'reicast_threaded_rendering = "disabled"' in text


def test_stale_flycast_values_are_replaced_and_other_options_kept(tmp_path, monkeypatch):
    co = Config(data_dir=tmp_path).runtime / "retroarch" / "core-options.cfg"
    co.parent.mkdir(parents=True, exist_ok=True)
    co.write_text('reicast_enable_rttb = "disabled"\nreicast_threaded_rendering = "enabled"\n'
                  'reicast_internal_resolution = "1920x1440"\nmupen64plus-cpucore = "dynamic"\n')
    _write(tmp_path, monkeypatch, "naomi")
    lines = co.read_text().splitlines()
    assert lines.count('reicast_enable_rttb = "enabled"') == 1
    assert lines.count('reicast_threaded_rendering = "disabled"') == 1
    assert not any(l.endswith('"disabled"') and l.startswith("reicast_enable_rttb") for l in lines)
    assert 'reicast_internal_resolution = "1920x1440"' in lines
    assert 'mupen64plus-cpucore = "dynamic"' in lines


def test_non_flycast_platform_leaves_flycast_options_alone(tmp_path, monkeypatch):
    co = _write(tmp_path, monkeypatch, "psx")
    assert not co.exists() or "reicast_" not in co.read_text()
