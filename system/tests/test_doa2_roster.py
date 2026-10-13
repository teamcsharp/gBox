"""DOA2 LE whole-roster replacement (#1385, #1361): several donors, every selectable fighter, one disc."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import doa2_swap as S


def test_plan_covers_every_selectable_fighter_once_and_is_deterministic():
    plan = S.plan_roster([("Kasumi", "sa2_amy_rose"), ("", "sonic"), ("", "sa2_tails"), ("", "sa2_knuckles")], seed="x")
    assert [f for f, _ in plan] == S.ROSTER and len(plan) == 14
    assert dict(plan)["KAS"] == "sa2_amy_rose"
    assert all(slug in {"sonic", "sa2_tails", "sa2_knuckles"} for f, slug in plan if f != "KAS")
    assert plan == S.plan_roster([("Kasumi", "sa2_amy_rose"), ("", "sonic"), ("", "sa2_tails"), ("", "sa2_knuckles")], seed="x")
    assert plan != S.plan_roster([("Kasumi", "sa2_amy_rose"), ("", "sonic"), ("", "sa2_tails"), ("", "sa2_knuckles")], seed="y")
    # one free donor: everyone else becomes that donor
    single = S.plan_roster([("", "sa2_shadow")])
    assert {slug for _, slug in single} == {"sa2_shadow"}


def test_plan_rejects_bad_entries():
    with pytest.raises(ValueError, match="costume"):
        S.plan_roster([("Kasumi:01", "sonic"), ("", "sa2_tails")])
    with pytest.raises(ValueError, match="assigned twice"):
        S.plan_roster([("Kasumi", "sonic"), ("kas", "sa2_tails"), ("", "sa2_amy_rose")])
    with pytest.raises(ValueError, match="No donors left"):
        S.plan_roster([("Kasumi", "sonic")])
    with pytest.raises(ValueError, match="boss variant"):
        S.plan_roster([("LOR", "sonic"), ("", "sa2_tails")])
    with pytest.raises(ValueError, match="needs a character"):
        S.plan_roster([("Kasumi", "")])


class FakeDisc:
    files = {}

    def read(self, key):
        assert key == "1ST_READ.BIN"
        return bytes(16)


def test_build_roster_merges_every_fighter_into_one_mod(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "GDRom", FakeDisc, raising=False)
    monkeypatch.setattr("gbox.gdrom.GDRom", lambda gdi: FakeDisc())
    monkeypatch.setattr("gbox.doa2_rig.collect_axes", lambda disc: {"axes": "audit"})
    seen = []

    def edits(disc, audit, gdi, character_dir, out_dir, family, costume="all", *, allow_downscale=False, progress=None):
        seen.append((family, Path(character_dir).name, costume))
        patch = bytearray(16)
        patch[S.ROSTER.index(family)] = 0xAA                   # each fighter edits its own executable byte
        return ({f"DOA2/{family}00.CHR": family.encode(), f"DOA2/{family}00.BIN": b"bin"},
                [{"fighter": family, "costume": "00"}], [bytes(patch)])
    monkeypatch.setattr(S, "fighter_edits", edits)
    written = {}

    def write_mod(gdi, out_dir, name, slug, changes, reports, progress):
        written.update(name=name, slug=slug, changes=changes, reports=reports)
        Path(out_dir, ".gbox-mod.json").write_text(json.dumps({"name": name, "character": slug}), encoding="utf-8")
        return {"mod": name, "image": "x.gdi", "status": "built_unverified"}
    monkeypatch.setattr(S, "write_mod", write_mod)
    donors = {}
    for slug in ("sonic", "sa2_tails"):
        d = tmp_path / slug
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"slug": slug}), encoding="utf-8")
        donors[slug] = d
    plan = S.plan_roster([("Kasumi", "sonic"), ("", "sa2_tails")], seed="t")
    out = tmp_path / "mod"
    out.mkdir()
    result = S.build_roster("disc.gdi", donors, out, plan)
    assert [f for f, _d, _c in seen] == S.ROSTER and all(c == "all" for _f, _d, c in seen)
    assert written["name"].startswith("doa2_roster_") and written["slug"] == "sa2_tails,sonic"
    assert len(written["changes"]) == 2 * 14 + 1
    merged = written["changes"]["1ST_READ.BIN"]
    assert all(merged[i] == 0xAA for i in range(14)) and merged[14:] == bytes(2)      # disjoint patches merged
    assert [r["donor"] for r in written["reports"]][:1] == ["sonic"] and len(written["reports"]) == 14
    record = json.loads((out / ".gbox-mod.json").read_text(encoding="utf-8"))
    assert record["roster"][0] == {"fighter": "KAS", "character": "sonic"} and len(record["roster"]) == 14
    assert result["roster"] == record["roster"]


def test_use_roster_resolves_donors_registers_targets_and_launches(tmp_path, monkeypatch):
    lib = tmp_path / "characters"
    for slug in ("sonic", "sa2_amy_rose"):
        (lib / slug).mkdir(parents=True)
        (lib / slug / "meta.json").write_text(json.dumps({"slug": slug}), encoding="utf-8")
    monkeypatch.setenv("GBOX_CHARACTERS", str(lib))
    calls = []
    import gbox.characters as C
    monkeypatch.setattr(C, "_dc_gdi", lambda ctx, game: "disc.gdi")
    monkeypatch.setattr(C, "_api", lambda ctx, method, path, **kw: calls.append((method, path, kw.get("json"))))
    monkeypatch.setattr(C, "_launch", lambda ctx, gid, mod, node: {"launched": mod, "node": node})
    import gbox.filemods as F
    monkeypatch.setattr(F, "mod_dir", lambda cfg, gid, name: (tmp_path / "mods" / name).mkdir(parents=True, exist_ok=True) or tmp_path / "mods" / name)
    monkeypatch.setattr(S, "build_roster", lambda gdi, donors, out, plan, progress=None: {"mod": "built", "roster": plan, "donors": sorted(donors)})
    ctx = SimpleNamespace(config=None, progress=lambda p, m: None)
    inp = SimpleNamespace(slot="roster", pairs=[{"character": "sonic", "slot": "Kasumi"}, {"character": "sa2_amy_rose"}],
                          rebuild=False, launch=True, title="")
    out = S.use(ctx, {"slug": "sonic"}, {"game_id": "1de2e7634f3161ff"}, inp)
    assert out["mod"].startswith("doa2_roster_") and out["launch"]["launched"] == out["mod"]
    assert out["roster"][0] == {"fighter": "KAS", "character": "sonic"} and len(out["roster"]) == 14
    assert out["build"]["donors"] == ["sa2_amy_rose", "sonic"]
    assert len(calls) == 14 and all(c[1].startswith("/api/characters/") and c[2]["slot"].endswith(":all") for c in calls)

    missing = SimpleNamespace(slot="roster", pairs=[{"character": "nobody"}], rebuild=False, launch=False, title="")
    with pytest.raises(ValueError, match="Not in the collection"):
        S.use(ctx, {"slug": "sonic"}, {"game_id": "1de2e7634f3161ff"}, missing)
