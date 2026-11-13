"""Death lessons: learn from the first attributed death, bounded and decaying, without duplicate lessons."""
import json

from gbox.mercs.core import combat, death_lessons as dl

NOW = 1_800_000_000.0


def _dl(tmp_path, clock=lambda: NOW):
    return dl.DeathLessons("T", paths=[tmp_path / "u.jsonl", tmp_path / "t.jsonl"], clock=clock)


def _die(d, cls, t0=0.0):
    d.new_round()
    player = {"hp": 100, "pos": (0, 0, 0)}
    en = [{"class": cls, "hp": 50, "pos": (0, 0, 200)}, {"class": "x", "hp": 50, "pos": (0, 0, 900)}]
    d.observe(t0, player, en, doing="shoot x", why="cheapest")
    d.observe(t0 + 1, {"hp": 40, "pos": (0, 0, 0)}, en, hit={"class": cls, "damage": 60})
    return d.observe(t0 + 2, {"hp": 0, "pos": (0, 0, 0)}, en, hit={"class": cls, "damage": 40})


def test_death_is_recorded_everywhere(tmp_path):
    d = _dl(tmp_path)
    les = _die(d, "chainsaw")
    assert les["killer"] == "chainsaw" and les["killer_basis"] == "last_hit" and les["hits"] == 2
    assert les["nearest_cm"]["chainsaw"] == 200 and les["crowd_n"] == 2 and les["doing"] == "shoot x"
    for f in ("u.jsonl", "t.jsonl"):
        assert len((tmp_path / f).read_text().splitlines()) == 1
    assert d.observe(5, {"hp": 0, "pos": (0, 0, 0)}, []) is None     # staying dead does not record twice


def test_no_adjustment_before_evidence_then_bounded(tmp_path):
    d = _dl(tmp_path)
    assert d.weight("chainsaw") == 1.0
    _die(d, "chainsaw")
    assert d.weight("chainsaw") > 1.0
    assert d.doctrine(["chainsaw"])["flash_x"] < 1.0
    _die(d, "chainsaw", 10)
    d._adj = None
    assert d.weight("chainsaw") > 1.0 and d.keep_cm("chainsaw") > 0 and d.answer("chainsaw")
    assert d.weight("x") == 1.0                              # a class that never killed him is untouched
    for i in range(30):
        _die(d, "chainsaw", 20 + 10 * i)
    d._adj = None
    a = d.get("chainsaw")
    assert a["weight"] <= dl.CAPS["weight"] and a["keep_cm"] <= dl.CAPS["keep_cm"]
    assert a["retreat_x"] <= 1 + dl.CAPS["retreat_x"] and a["mine_x"] >= 1 - dl.CAPS["mine_x"]


def test_lessons_decay(tmp_path):
    d = _dl(tmp_path)
    _die(d, "g")
    _die(d, "g", 10)
    les = dl.load([tmp_path / "u.jsonl"])
    assert dl.learn(les, "T", NOW + 60)["g"]["weight"] > 1.0
    assert dl.learn(les, "T", NOW + 10 * dl.HALF_LIFE_S) == {}


def test_scorer_takes_the_killer_class_seriously(tmp_path):
    prof = combat.TitleProfile(title="t", title_id="T", engage_cm=3000)
    th = combat.Threats(prof, path=tmp_path / "threat.json")
    th.lessons = _dl(tmp_path)
    for t0 in (0, 10):
        _die(th.lessons, "boss_like", t0)
    th.lessons._adj = None
    player = {"hp": 100, "pos": (0, 0, 0), "rot": 0.0}
    near = {"class": "plain", "hp": 10, "pos": (0, 0, 300), "ptr": 1}
    far = {"class": "boss_like", "hp": 10, "pos": (0, 0, 900), "ptr": 2}
    got = th.priority(player, [near, far])
    assert got is not None and got[0] is far and got[1] == "dangerous"
    th.lessons = None
    assert th.priority(player, [near, far]) is None          # without the lesson the cheapest stands


def test_replay_is_causal_and_honest():
    ls = [{"killer": "g", "ts": NOW, "title_id": "T"}, {"killer": "g", "ts": NOW + 1, "title_id": "T"},
          {"killer": "g", "ts": NOW + 2, "title_id": "T"}, {"killer": None, "ts": NOW + 3, "title_id": "T"},
          {"killer": "h", "ts": NOW + 4, "title_id": "T"}]
    r = dl.replay(ls)
    assert r["first_adjustment_at_death"] == 1 and r["deaths_before"] == 1 and r["deaths_after"] == 4
    assert r["after_deaths_by_class_already_learned"] == 2 and r["killer_not_determined"] == 1
    assert r["after_deaths_by_unlearned_class"] == 1
    json.dumps(r)


def test_hp_and_terminal_events_record_one_lesson_until_new_round(tmp_path):
    d = _dl(tmp_path)
    _die(d, "chainsaw")
    assert d.died(3) is None
    d.observe(4, {"hp": 100}, [])  # a stale/loading HP read must not rearm a death
    assert d.observe(5, {"hp": 0}, []) is None
    assert len(dl.load([tmp_path / "u.jsonl"])) == 1
    # A fresh instance learns the persisted killer immediately.
    assert _dl(tmp_path).weight("chainsaw") > 1.0
    _die(d, "chainsaw", 10)
    assert len(dl.load([tmp_path / "u.jsonl"])) == 2


def test_unattributed_death_does_not_blame_nearest_enemy(tmp_path):
    d = _dl(tmp_path)
    enemies = [{"class": "near", "hp": 50, "pos": (0, 0, 10)}]
    d.observe(1, {"hp": 100, "pos": (0, 0, 0)}, enemies)
    lesson = d.observe(2, {"hp": 0, "pos": (0, 0, 0)}, enemies)
    assert lesson["killer"] is None
    assert d.weight("near") == 1.0
