"""Flycast's future snapshots must include render-to-texture results in VRAM."""
import pytest

from gbox import adapters
from gbox.adapters import RetroArchAdapter
from gbox.config import Config, EmulatorConfig


def _write(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    adapter = RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="retroarch", core="core"),
                               config=Config(data_dir=tmp_path), platform=platform)
    adapter._write_cfg()
    return adapter.config.runtime / "retroarch" / f"session-{adapter.addr[1]}-core-options.cfg"


@pytest.mark.parametrize("platform", sorted(adapters.FLYCAST_PLATFORMS))
def test_flycast_launch_keeps_rtt_and_serialization_stable(tmp_path, monkeypatch, platform):
    co = _write(tmp_path, monkeypatch, platform)
    text = co.read_text()
    assert 'reicast_enable_rttb = "enabled"' in text
    assert 'reicast_threaded_rendering = "disabled"' in text


def test_stale_values_and_whitespace_variants_are_replaced_without_touching_other_options(tmp_path, monkeypatch):
    co = Config(data_dir=tmp_path).runtime / "retroarch" / "core-options.cfg"
    co.parent.mkdir(parents=True, exist_ok=True)
    co.write_text('reicast_enable_rttb = "disabled"\n  reicast_enable_rttb="disabled"\n'
                  'reicast_threaded_rendering = "enabled"\n'
                  'reicast_internal_resolution = "1920x1440"\nmupen64plus-cpucore = "dynamic"\n'
                  '# reicast_enable_rttb is deliberately managed at launch\n')
    before = co.read_text()
    lines = _write(tmp_path, monkeypatch, "naomi").read_text().splitlines()
    assert co.read_text() == before  # launch settings never mutate the shared defaults
    assert lines.count('reicast_enable_rttb = "enabled"') == 1
    assert lines.count('reicast_threaded_rendering = "disabled"') == 1
    assert '  reicast_enable_rttb="disabled"' not in lines
    assert 'reicast_internal_resolution = "1920x1440"' in lines
    assert 'mupen64plus-cpucore = "dynamic"' in lines
    assert '# reicast_enable_rttb is deliberately managed at launch' in lines


def test_non_flycast_launch_preserves_existing_flycast_preferences(tmp_path, monkeypatch):
    co = Config(data_dir=tmp_path).runtime / "retroarch" / "core-options.cfg"
    co.parent.mkdir(parents=True, exist_ok=True)
    before = 'reicast_enable_rttb = "disabled"\nreicast_threaded_rendering = "enabled"\n'
    co.write_text(before)
    _write(tmp_path, monkeypatch, "psx")
    assert co.read_text() == before
