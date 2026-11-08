"""`gbox.rea` must expose what `rea_tool` imports, or the module is silently missing from every node.

The failure this pins was in the service log: *"tool module rea_tool not loaded on this machine: AttributeError: module
'gbox.rea' has no attribute 'VERSION'"*. The registry skips a tool module that raises, so the REA tools were simply absent
while the integration itself worked - a missing constant, not a broken feature.
"""
import pathlib

from gbox import rea, rea_tool


def test_rea_exposes_the_version_rea_tool_stamps():
    assert isinstance(rea.VERSION, str) and rea.VERSION.count(".") >= 1
    assert rea_tool is not None


def test_unavailable_answers_a_reason_or_none_and_never_raises():
    reason = rea.unavailable()
    assert reason is None or (isinstance(reason, str) and reason), "a check must say why, or say nothing"


def test_unavailable_does_not_raise_when_the_check_itself_fails(monkeypatch):
    def boom():
        raise OSError("npm vanished")
    monkeypatch.setattr(rea, "available", boom)
    reason = rea.unavailable()
    assert isinstance(reason, str) and "could not be checked" in reason


def test_the_tool_module_declares_its_tool():
    source = pathlib.Path(rea_tool.__file__).read_text(encoding="utf-8")
    assert "check=rea.unavailable" in source, "the registry's check must be the function this module provides"
