"""Examine 3D capability matrix (#971): every emulator reports supported / relaunch_under_capture / unsupported."""
from types import SimpleNamespace

import pytest

from gbox import scene_capture as scene
from gbox import scene_support as ss
from gbox.registry import Unsupported


def test_matrix_is_exposed_from_scene_capture():
    assert scene.support is ss.support


@pytest.mark.parametrize('core', ['flycast', 'C:\\gbox\\cores\\flycast_libretro.dll', 'mednafen_psx_hw_libretro.so'])
def test_gl_session_of_vulkan_core_relaunches_under_vulkan(core):
    row = ss.support('retroarch', core, 'gl', host_os='windows')
    assert row['status'] == ss.RELAUNCH
    assert (row['driver'], row['attach'], row['relay']) == ('vulkan', 'layer', True)
    assert row['fallback'] == 'frame_2d'
    assert 'video_driver=vulkan' in row['reason'] and 'keeps running' in row['reason']


def test_n64_capture_session_uses_hle_on_glcore():
    row = ss.support('retroarch', 'mupen64plus_next', 'gl', host_os='windows')
    assert (row['status'], row['driver'], row['attach'], row['relay']) == (ss.RELAUNCH, 'glcore', 'inject', True)
    assert 'compute' in row['reason']


@pytest.mark.parametrize('driver', ['gl', 'vulkan'])
def test_parallel_n64_has_no_capturable_scene(driver):
    row = ss.support('retroarch', 'parallel_n64', driver, hooked=True, host_os='windows')
    assert (row['status'], row['fallback']) == (ss.UNSUPPORTED, 'frame_2d')
    assert 'no draw calls' in row['reason'] and 'compatibility context' in row['reason']


@pytest.mark.parametrize('driver', ['d3d11', 'd3d12', 'vulkan'])
def test_capturable_retroarch_driver_is_supported(driver):
    row = ss.support('retroarch', 'pcsx2_libretro.dll', driver, hooked=True, host_os='windows')
    assert row == row | {'status': ss.SUPPORTED, 'driver': None, 'fallback': None, 'core': 'pcsx2'}


def test_capturable_driver_without_renderdoc_relays_to_a_capture_session():
    row = ss.support('retroarch', 'pcsx2', 'd3d11', hooked=False, host_os='windows')
    assert (row['status'], row['driver'], row['attach'], row['relay']) == (ss.RELAUNCH, 'd3d11', 'inject', True)
    assert 'without RenderDoc inside' in row['reason']
    other = ss.support('retroarch', 'some_d3d_core', 'd3d11', hooked=False, host_os='windows')
    assert (other['driver'], other['attach']) == ('d3d11', 'inject')


def test_gl_only_core_uses_glcore_second_choice():
    row = ss.support('retroarch', 'kronos', 'gl', host_os='windows')
    assert (row['status'], row['driver'], row['attach'], row['relay']) == (ss.RELAUNCH, 'glcore', 'inject', True)
    assert row['verified'] is False


@pytest.mark.parametrize('core', ['snes9x', 'genesis_plus_gx_libretro.dll', 'mgba'])
def test_software_cores_are_2d_only(core):
    row = ss.support('retroarch', core, 'd3d11', hooked=True, host_os='windows')
    assert row['status'] == ss.UNSUPPORTED and row['fallback'] == 'frame_2d'
    assert '2D frame only' in row['reason']


@pytest.mark.parametrize('adapter,status', [('dolphin', ss.SUPPORTED), ('yuzu', ss.SUPPORTED),
                                            ('rpcs3', ss.SUPPORTED), ('xenia', ss.UNSUPPORTED),
                                            ('steam', ss.UNSUPPORTED), ('rocketlauncher', ss.UNSUPPORTED),
                                            ('something_new', ss.UNSUPPORTED)])
def test_standalone_emulators_have_a_row_with_reason(adapter, status):
    row = ss.support(adapter, host_os='windows')
    assert row['status'] == status and row['reason']


def test_yuzu_and_rpcs3_use_the_vulkan_layer():
    for adapter in ('yuzu', 'rpcs3'):
        row = ss.support(adapter, hooked=True, host_os='windows')
        assert (row['status'], row['attach']) == (ss.SUPPORTED, 'layer')
        late = ss.support(adapter, hooked=False, host_os='windows')
        assert (late['status'], late['relay']) == (ss.RELAUNCH, False)     # their states can't be carried
        assert "can't be carried" in late['reason']


def test_yuzu_on_opengl_names_the_vulkan_route():
    row = ss.support('yuzu', None, 'opengl', host_os='windows')
    assert (row['status'], row['driver']) == (ss.UNSUPPORTED, 'vulkan')
    assert 'Vulkan' in row['reason'] and 'opengl' in row['reason']


def test_dolphin_without_renderdoc_relays_on_vulkan():
    row = ss.support('dolphin', hooked=False, host_os='windows')
    assert (row['status'], row['driver'], row['attach'], row['relay']) == (ss.RELAUNCH, 'vulkan', 'layer', True)
    assert 'GFXBackend' in row['reason'] or 'Vulkan backend' in row['reason']


def test_layer_session_that_never_loaded_renderdoc_is_not_hooked():
    ad = SimpleNamespace(name='yuzu', cfg=None, video_driver='vulkan',
                         proc=SimpleNamespace(renderdoc={'attach': 'layer', 'loaded': False}))
    assert ss.session_support(ad, 'windows')['status'] == ss.RELAUNCH
    ad.proc.renderdoc['loaded'] = True
    assert ss.session_support(ad, 'windows')['status'] == ss.SUPPORTED


def test_linux_sessions_are_unsupported_with_reason():
    row = ss.support('retroarch', 'flycast', 'vulkan', host_os='linux')
    assert row['status'] == ss.UNSUPPORTED and 'Windows' in row['reason']


def test_video_driver_reads_retroarch_config(tmp_path):
    cfg = tmp_path / 'ra.cfg'
    cfg.write_text('audio_driver = "xaudio"\nvideo_driver = "glcore"\n')
    assert ss.video_driver(['retroarch.exe', '--config', str(cfg), '-L', 'x.dll', 'rom']) == 'glcore'
    assert ss.video_driver(['dolphin.exe']) is None


def test_session_support_from_live_adapter():
    ad = SimpleNamespace(name='retroarch', cfg=SimpleNamespace(core='flycast'), video_driver='gl',
                         proc=SimpleNamespace(renderdoc=None))
    row = ss.session_support(ad, 'windows')
    assert (row['status'], row['driver'], row['core']) == (ss.RELAUNCH, 'vulkan', 'flycast')


def test_capture_reports_matrix_reason_instead_of_generic_relaunch(monkeypatch, tmp_path):
    ad = SimpleNamespace(name='retroarch', cfg=SimpleNamespace(core='flycast'), video_driver='gl',
                         proc=SimpleNamespace(poll=lambda: None, pid=1, renderdoc=None),
                         query_runtime=lambda: {'state': 'PLAYING'}, pause=lambda: None, resume=lambda: None)
    with pytest.raises(Unsupported, match='video_driver=vulkan'):
        scene.capture_session(ad, tmp_path)


def test_launch_result_carries_scene_capture_row():
    from gbox import tools
    src = open(tools.__file__).read()
    assert 'detail["scene_capture"] = session_support(ad, HOST_OS)' in src
    assert 'caps["scene_capture"]' in src
