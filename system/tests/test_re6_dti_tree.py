import json, pathlib
J = pathlib.Path(__file__).resolve().parents[1] / "docs/research/re6-weapon-dti-tree.json"


def test_launcher_tree():
    e = {x["name"]: x for x in json.loads(J.read_text())["entries"]}
    assert e["uWp1080"]["parent"] == "uWpLauncher" and e["uWp1080"]["weapon_item"] == "0x112"
    assert e["uWp1120"]["parent"] == "uWpLauncher" and e["uWp1120"]["weapon_item"] == "0x11b"
    assert e["uWp1091"]["parent"] == "uWpBomb" and e["uWp1091"]["id"] == "0x7011301"
    assert all(e[n]["parent"] == "uWpShellLauncher" for n in ("uWp1302", "uWp1303", "uWp1304"))
