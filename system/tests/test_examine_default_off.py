"""RenderDoc (Examine 3D) must not be injected into normal gameplay launches by default.

Injecting renderdoc.dll into every Windows launch hung Dolphin's D3D12 renderer: Soul
Calibur II froze ~70 s into attract mode with 0% GPU / 0.1% CPU and renderdoc.dll loaded
(#1973). Examine 3D instead relaunches a dedicated Vulkan-layer capture session on demand
(scene_support.relay), so normal gameplay launches stay injection-free unless the operator
(or an agent capture session) opts in explicitly.
"""
from gbox import decant
from gbox.config import Config
from gbox.tools import _examine_for_launch


def test_examine_ready_defaults_off():
    assert Config().examine_ready is False


def test_standalone_toml_defaults_examine_off():
    assert "examine_ready = false" in decant.STANDALONE_TOML
    assert "examine_ready = true" not in decant.STANDALONE_TOML


def test_normal_launch_does_not_inject_renderdoc():
    # examine=None (operator launch), default config examine_ready=False
    assert _examine_for_launch(None, False, "windows") is False


def test_explicit_config_opt_in_still_injects():
    # an operator who sets examine_ready=true in gbox.toml keeps instant Examine 3D
    assert _examine_for_launch(None, True, "windows") is True


def test_explicit_examine_flag_is_respected():
    assert _examine_for_launch(True, False, "windows") is True
    # an explicit off beats a config opt-in
    assert _examine_for_launch(False, True, "windows") is False


def test_non_windows_never_injects():
    assert _examine_for_launch(True, True, "linux") is False
    assert _examine_for_launch(None, True, "linux") is False
