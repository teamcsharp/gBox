"""A debug launch of an Xbox game writes Cxbx-Reloaded's full kernel log (JSRF black screen, #2412)."""
from pathlib import Path

from gbox import evidence_capture as E, xbox


def test_a_debug_launch_logs_every_module_and_a_normal_launch_writes_info_back(tmp_path):
    log = tmp_path / "gbox-kernel.log"
    debug = xbox.log_settings(True, log)
    assert debug == {"KrnlDebugMode": "0x2", "KrnlDebugLogFile": str(log), "LogLevel": "0", "LoggedModules": "0xFFFFFFFF"}
    normal = xbox.log_settings(False, log)
    assert normal["LogLevel"] == "1" and "LoggedModules" not in normal, "a previous debug run never slows the next game"


def test_the_settings_file_keeps_its_other_keys_and_takes_the_log_level(tmp_path):
    ini = tmp_path / "settings.ini"
    ini.write_text("[gui]\nDataStorageToggle = 0x1\n[core]\nAllowAdminPrivilege = false\nLogLevel = 1\n[video]\nFullScreen = false\n", encoding="utf8")
    xbox._set_ini(ini, {"core": xbox.log_settings(True, tmp_path / "k.log")})
    text = ini.read_text(encoding="utf8")
    assert "AllowAdminPrivilege = false" in text and "DataStorageToggle = 0x1" in text and "FullScreen = false" in text
    assert text.count("LogLevel = ") == 1 and "LogLevel = 0" in text and "LoggedModules = 0xFFFFFFFF" in text
    xbox._set_ini(ini, {"core": xbox.log_settings(False, tmp_path / "k.log")})
    text = ini.read_text(encoding="utf8")
    assert "LogLevel = 1" in text and text.count("LogLevel = ") == 1


def test_evidence_capture_passes_debug_to_its_launch():
    assert E.EvidenceIn(game_id="a" * 16).debug is False
    assert E.EvidenceIn(game_id="a" * 16, debug=True).debug is True
    src = Path(E.__file__).read_text(encoding="utf8")
    assert '"debug": bool(inp.debug)' in src, "the launch input carries the flag"
