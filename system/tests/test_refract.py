import json

import pytest

from gbox import refract


def lib(tmp_path, games):
    (tmp_path / "library.json").write_text(json.dumps({"games": games, "jobs": [], "settings": {}}))
    return tmp_path


RE4 = {"name": "Resident Evil 4", "package": "com.Armature.VR4", "binaryId": "123", "owned": True, "vrSdk": "vrapi",
       "nativeInstalled": True, "source": "meta",
       "files": [{"name": "base.apk", "path": "C:/dl/1/2/base.apk", "kind": "apk", "size": 10},
                 {"name": "main.obb", "path": "C:/dl/1/2/main.obb", "kind": "obb", "size": 90}]}


def test_scan(tmp_path):
    e, p = refract.scan_refract(lib(tmp_path, [RE4, {"name": "bad"}]))
    assert len(e) == 1 and len(p) == 1
    x = e[0]
    assert (x.game_id, x.platform, x.size) == ("quest-com.Armature.VR4", "quest", 100)
    assert x.launch["kind"] == "refract" and x.launch["owned"] and x.launch["obb_dir"] == str(
        refract.Path("C:/dl/1/2/main.obb").parent)


def test_scan_missing(tmp_path):
    assert refract.scan_refract(tmp_path)[0] == []


def test_commands(tmp_path):
    c = refract.native_commands(tmp_path, "com.Armature.VR4", "RE4", owned=True, obb_dir="/o", pictures="/p")
    assert "debug.refract.platform.owned.com.Armature.VR4=1" in c["game"]
    assert "/sdcard/Android/obb/com.Armature.VR4=/o" in c["game"]
    assert c["viewer"][5:7] == ["--shots", "/p"] and "--focus" in c["pose"]


def test_unowned_refused(tmp_path):
    with pytest.raises(PermissionError):
        refract.native_commands(tmp_path, "com.Armature.VR4", "RE4", owned=False)
    with pytest.raises(ValueError):
        refract.native_commands(tmp_path, "x;rm", "RE4", owned=True)


def test_control():
    assert refract.control_message("stick", "left", 0, 1, 0.5) == b"stick left 0 1 0.5\n"
    with pytest.raises(ValueError):
        refract.control_message("hold", "left")
