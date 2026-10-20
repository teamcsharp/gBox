"""#1322: Windows N64 forces the angrylion RDP, which only draws with the LLE cxd4 RSP (HLE/auto = black 3D).

#1695: Linux/aarch64 N64 forces the cached interpreter CPU core; the Ari64 dynarec is x86-only and never boots.
"""
from gbox import adapters, gamepads, graphics, provision
from gbox.adapters import RetroArchAdapter
from gbox.config import Config, EmulatorConfig


def _write(tmp_path, monkeypatch, platform, host="windows", arch="x86_64"):
    monkeypatch.setattr(adapters, "HOST_OS", host)
    monkeypatch.setattr(provision, "ARCH", arch)
    monkeypatch.setattr(gamepads, "retroarch_driver", lambda exe: "sdl2")
    monkeypatch.setattr(provision, "retroarch_exe", lambda cfg: tmp_path / "retroarch.exe")
    monkeypatch.setattr(graphics, "get", lambda cfg, game_id: {})
    monkeypatch.setattr(graphics, "retroarch_opts", lambda prefs, exe_dir: {})
    adapter = RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="retroarch", core="core"),
                               config=Config(data_dir=tmp_path), platform=platform)
    adapter._write_cfg()
    return adapter.config.runtime / "retroarch" / "core-options.cfg"


def _co(tmp_path):
    co = Config(data_dir=tmp_path).runtime / "retroarch" / "core-options.cfg"
    co.parent.mkdir(parents=True, exist_ok=True)
    return co


def test_windows_n64_pairs_angrylion_with_lle_rsp(tmp_path, monkeypatch):
    lines = _write(tmp_path, monkeypatch, "n64").read_text().splitlines()
    assert lines.count('parallel-n64-gfxplugin = "angrylion"') == 1
    assert lines.count('parallel-n64-rspplugin = "cxd4"') == 1


def test_stale_hle_or_auto_rsp_is_replaced_and_other_options_kept(tmp_path, monkeypatch):
    co = _co(tmp_path)
    co.write_text('parallel-n64-rspplugin = "auto"\n  parallel-n64-rspplugin="hle"\nparallel-n64-gfxplugin = "glide64"\n'
                  'parallel-n64-cpucore = "dynamic_recompiler"\nreicast_enable_rttb = "enabled"\n')
    lines = _write(tmp_path, monkeypatch, "n64").read_text().splitlines()
    assert [l for l in lines if "rspplugin" in l] == ['parallel-n64-rspplugin = "cxd4"']
    assert [l for l in lines if "gfxplugin" in l] == ['parallel-n64-gfxplugin = "angrylion"']
    assert 'parallel-n64-cpucore = "dynamic_recompiler"' in lines
    assert 'reicast_enable_rttb = "enabled"' in lines


def test_linux_and_other_platforms_keep_their_rsp_choice(tmp_path, monkeypatch):
    co = _co(tmp_path)
    before = 'parallel-n64-gfxplugin = "gliden64"\nparallel-n64-rspplugin = "auto"\n'
    co.write_text(before)
    _write(tmp_path, monkeypatch, "n64", host="linux", arch="x86_64")
    assert [l for l in co.read_text().splitlines() if "plugin" in l] == before.splitlines()
    after_n64 = co.read_text()
    _write(tmp_path, monkeypatch, "psx")
    assert co.read_text() == after_n64


def test_linux_aarch64_n64_forces_cached_interpreter(tmp_path, monkeypatch):
    co = _co(tmp_path)
    co.write_text('parallel-n64-cpucore = "dynamic_recompiler"\nparallel-n64-gfxplugin = "gliden64"\n')
    lines = _write(tmp_path, monkeypatch, "n64", host="linux", arch="aarch64").read_text().splitlines()
    assert [l for l in lines if "cpucore" in l] == ['parallel-n64-cpucore = "cached_interpreter"']
    assert [l for l in lines if "gfxplugin" in l] == ['parallel-n64-gfxplugin = "gliden64"']  # gfx choice untouched


def test_linux_x86_64_n64_keeps_dynarec_default(tmp_path, monkeypatch):
    co = _co(tmp_path)
    before = 'parallel-n64-cpucore = "dynamic_recompiler"\n'
    co.write_text(before)
    _write(tmp_path, monkeypatch, "n64", host="linux", arch="x86_64")
    assert [l for l in co.read_text().splitlines() if "cpucore" in l] == before.splitlines()


def test_other_platforms_on_aarch64_keep_their_cpucore_choice(tmp_path, monkeypatch):
    co = _co(tmp_path)
    before = 'parallel-n64-cpucore = "dynamic_recompiler"\n'
    co.write_text(before)
    _write(tmp_path, monkeypatch, "psx", host="linux", arch="aarch64")
    assert co.read_text() == before


def test_every_n64_port_gets_a_memory_pak(tmp_path, monkeypatch):
    co = _co(tmp_path)
    co.write_text('parallel-n64-pak1 = "none"\nparallel-n64-pak2 = "rumble"\nreicast_enable_rttb = "enabled"\n')
    for host, arch in (("windows", "x86_64"), ("linux", "aarch64")):
        lines = _write(tmp_path, monkeypatch, "n64", host=host, arch=arch).read_text().splitlines()
        for i in range(1, 5):
            assert [l for l in lines if l.startswith(f"parallel-n64-pak{i} ")] == [f'parallel-n64-pak{i} = "memory"']
            assert f'mupen64plus-pak{i} = "memory"' in lines
        assert 'reicast_enable_rttb = "enabled"' in lines
