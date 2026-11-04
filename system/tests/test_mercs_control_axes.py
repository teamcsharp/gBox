"""The universal behavior axes (gbox.mercs.core.control_axes): the schema's guards, each title's expansion onto its
own knobs, and the live-controls wiring the radial behavior graph will sit on."""
import asyncio
import copy
import json
import uuid

import pytest

from gbox import merc_live_controls as LC
from gbox.mercs import bot_logic, tuning
from gbox.mercs.core import control_axes as AX

# The operator's hard rules stay out of every axis's reach (gbox-bot-no-wall-shots-no-mine-standing): these knobs are
# safety, not style, and the axes must never write them.
HARD_RULES = {"WALL_GOV", "CAM_DOWN_GUARD", "SHOT_TAIL_S", "AIM_LOCK", "MINE_FOE_CLEAR_CM", "PROMPTS"}


def view_of(title):
    knobs = [{"name": k[0], "label": k[1], "group": k[2], "kind": k[3], "min": k[4], "max": k[5], "step": k[6],
              "help": k[7], "value": False if k[3] == "bool" else (k[4] if k[3] == "int" else float(k[4])),
              "set": False} for k in bot_logic.KNOBS[title]]
    return {"verified": True, "title": title, "knobs": knobs}


def status_of(title):
    st = {"capabilities": {op: {"available": True} for op, _l, _f, _b in LC.MODS[title]}}
    for _op, _label, field, bounds in LC.MODS[title]:
        node, keys = st, field.split(".")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = 1.0 if bounds else False
    return st


def rows_of(title, **status_over):
    status = status_of(title)
    status.update(status_over)
    return LC.control_inventory(title, view_of(title), status)


def test_every_axis_is_mapped_or_named_grey_and_each_knob_serves_one_axis():
    assert set(AX.AXES) == {"aggression", "aim_speed", "fire_rate", "magnum", "weapon_switching", "grenade_use",
                            "mine_place", "melee", "knife"}
    for title, axes in AX.MAPS.items():
        knobs = {k[0]: k for k in bot_logic.KNOBS[title]}
        mods = {op: bounds for op, _l, _f, bounds in LC.MODS[title]}
        used = []
        for name in AX.AXES:
            assert name in axes or (title, name) in AX.UNMAPPED, f"{title}: {name} neither mapped nor explained"
        for name, mapping in axes.items():
            for target in mapping:
                tid, spec = target[0], target[1:]
                kind, key = tid.split(".", 1)
                used.append(tid)
                if kind == "behavior":
                    knob = knobs[key]                               # KeyError = a target the title does not have
                    assert (knob[3] == "bool") == (spec[0] == "gate"), f"{title} {name}: {tid} kind mismatch"
                    if spec[0] == "lin":                            # the transfer stays inside the vetted bounds
                        assert min(spec[1], spec[2]) >= knob[4] and max(spec[1], spec[2]) <= knob[5], tid
                else:
                    assert kind == "mod" and key in mods, tid
                    assert mods[key] is not None and spec[0] in ("lin", "pass"), f"{title} {name}: {tid}"
        assert len(used) == len(set(used)), f"{title}: a knob serves two axes"


def test_tuner_constants_and_hard_rules_stay_out_of_reach():
    tuned = {name.rsplit(".", 1)[1] for params in tuning.PARAMS.values() for name in params}
    for title, axes in AX.MAPS.items():
        for name, mapping in axes.items():
            for target in mapping:
                kind, key = target[0].split(".", 1)
                if kind == "behavior":
                    assert key not in tuned, f"{title} {name} writes the tuner's {key}"
                    assert key not in HARD_RULES, f"{title} {name} writes the hard rule {key}"


def test_inventory_derives_axis_values_and_greys_what_a_title_lacks():
    rows = rows_of("re6", fire_rate_x=40.0)
    assert rows[0]["id"].startswith("axis.") and not rows[-1]["id"].startswith("axis.")
    fire = next(r for r in rows if r["id"] == "axis.fire_rate")
    assert fire["available"] and fire["value"] == 40.0 and (fire["min"], fire["max"]) == (1.0, 80.0)
    assert fire["group"] == AX.GROUP and fire["targets"] == ["mod.fire_rate"]
    knife = next(r for r in rows if r["id"] == "axis.knife")
    assert not knife["available"] and knife["value"] is None and "knife" in knife["reason"]
    magnum = next(r for r in rows_of("re5") if r["id"] == "axis.magnum")
    assert not magnum["available"] and "arsenal" in magnum["reason"]
    assert not next(r for r in rows_of("re5") if r["id"] == "axis.melee")["available"]
    assert LC.control_inventory(None, {}, {}) == []
    # a primary the worker has not verified greys the axis and carries the knob's own reason
    bare = LC.control_inventory("re5", view_of("re5"), {"fire_rate_x": 1.0})
    fire5 = next(r for r in bare if r["id"] == "axis.fire_rate")
    assert not fire5["available"] and fire5["reason"]


def test_expand_emits_exactly_the_job_shapes_the_knob_path_sends():
    rows = rows_of("re6")
    jobs, skipped = AX.expand("re6", "axis.grenade_use", 1.0, rows)
    assert skipped == []
    assert jobs[0] == ({"op": "throw_speed", "multiplier": 20.0, "on": True},
                       [{"control": "mod.throw_speed", "value": 20.0}])
    assert jobs[1][0] == {"op": "bot_logic", "values": {"NADES": True, "FLASH": True, "FLASH_N": 2}}
    assert {t["control"]: t["value"] for t in jobs[1][1]} == \
           {"behavior.NADES": True, "behavior.FLASH": True, "behavior.FLASH_N": 2}
    jobs, _ = AX.expand("re6", "axis.grenade_use", 0.5, rows)
    assert jobs[0][0]["multiplier"] == 10.5 and jobs[1][0]["values"]["FLASH_N"] == 5
    jobs, _ = AX.expand("re5", "axis.aim_speed", 4.0, rows_of("re5"))
    assert jobs[0][0] == {"op": "turn_speed", "multiplier": 4.0, "on": True}
    assert jobs[1][0] == {"op": "bot_logic", "values": {"HEADING_GOV_DEG_S": 200.0}}
    jobs, _ = AX.expand("re5", "axis.fire_rate", 1.0, rows_of("re5"))
    assert jobs == [({"op": "fire_rate", "multiplier": 1.0, "on": False},
                     [{"control": "mod.fire_rate", "value": 1.0}])]
    jobs, _ = AX.expand("re6", "axis.aggression", 1.0, rows)
    assert jobs[0][0]["values"] == {"FIRE_ZONE_R": 2000.0, "KITE_R": 400.0}
    jobs, _ = AX.expand("re6", "axis.aggression", 0.0, rows)
    assert jobs[0][0]["values"] == {"FIRE_ZONE_R": 300.0, "KITE_R": 1200.0}


def test_expand_refuses_what_change_input_would():
    rows = rows_of("re6")
    for axis, value in (("axis.fire_rate", 81), ("axis.aggression", True), ("axis.aggression", 1.2),
                        ("axis.knife", 0.5), ("axis.nope", 0.5)):
        with pytest.raises(ValueError):
            AX.expand("re6", axis, value, rows)
    with pytest.raises(ValueError, match="arsenal"):
        AX.expand("re5", "axis.magnum", 0.5, rows_of("re5"))
    with pytest.raises(ValueError):                    # an axis never passes as a single knob
        LC.change_input({"id": "axis.aggression", "available": True, "kind": "number", "min": 0, "max": 1}, 0.5)


SID = "pc-round"


class Plane:
    """The control plane the axis set rides: the re6 session, its jobs, and the knob state they move."""

    def __init__(self):
        self.session = {"session_id": SID, "state": "running", "game_id": "115f9cdbba115432", "adapter": "eden",
                        "title": "RE6"}
        self.run = {"session_id": SID, "game_id": self.session["game_id"], "phase": "playing"}
        self.posts, self.jobs = [], {}
        self.actual = None
        self.status = status_of("re6")
        self.view = view_of("re6")

    def answer(self, method, path, body=None):
        if path == "/api/sessions":
            return [self.session]
        if path == "/api/mercmode":
            return {"hosts": [{"id": "pc", "online": True, "current_run": self.run}]}
        if path == f"/api/sessions/{SID}/interventions":
            return {"available": False, "capabilities": [], "requests": []}
        if path == "/api/jobs" and method == "POST":
            self.posts.append(body)
            inp = body["input"]
            if inp["op"] == "bot_logic":
                for k in self.view["knobs"]:
                    if k["name"] in inp["values"]:
                        k["value"] = self.actual if self.actual is not None else inp["values"][k["name"]]
                result = copy.deepcopy(self.view)
            elif inp["op"] == "live_controls":
                result = {"verified": True, "view": copy.deepcopy(self.view), "status": copy.deepcopy(self.status)}
            else:
                self.status[inp["op"] + "_x"] = self.actual if self.actual is not None else inp.get("multiplier")
                result = {"verified": True, "status": copy.deepcopy(self.status)}
            jid = "job" + str(len(self.jobs))
            job = {**body, "id": jid, "state": "succeeded", "output": {"result": result}}
            self.jobs[jid] = job
            return copy.deepcopy(job)
        if path.startswith("/api/jobs/"):
            return copy.deepcopy(self.jobs[path.rsplit("/", 1)[1]])
        raise AssertionError((method, path, body))

    async def get(self, path, **kw):
        return self.answer("GET", path)

    async def post(self, path, body):
        return self.answer("POST", path, body)


async def no_delay(_):
    pass


def test_axis_set_drives_every_mapped_knob_and_the_dot_reads_back():
    async def check():
        p = Plane()
        c = LC.Controls(p.get, p.post, sleep=no_delay)
        out = await c.call({"session_id": SID})                       # the status read a front end opens with
        dot = next(r for r in out["controls"] if r["id"] == "axis.grenade_use")
        assert dot["available"] and dot["value"] == 0.0               # throw_speed_x 1.0 = the game's own pace
        out = await c.call({"session_id": SID, "op": "set", "control": "axis.grenade_use", "value": 1.0})
        assert out["action"]["state"] == "confirmed" and len(out["action"]["jobs"]) == 2
        sent = [b["input"] for b in p.posts if b["input"]["op"] != "live_controls"]
        assert sent == [{"session_id": SID, "op": "throw_speed", "multiplier": 20.0, "on": True},
                        {"session_id": SID, "op": "bot_logic", "values": {"NADES": True, "FLASH": True, "FLASH_N": 2}}]
        dot = next(r for r in out["controls"] if r["id"] == "axis.grenade_use")
        assert dot["value"] == 1.0
        for knob, value in (("behavior.NADES", True), ("behavior.FLASH_N", 2)):
            assert next(r for r in out["controls"] if r["id"] == knob)["value"] == value
        with pytest.raises(ValueError):                               # the grey dot refuses a drag
            await c.call({"session_id": SID, "op": "set", "control": "axis.knife", "value": 0.5})
        p.actual = 5                                                  # the worker answers with another value
        with pytest.raises(ValueError, match="did not confirm"):
            await c.call({"session_id": SID, "op": "set", "control": "axis.fire_rate", "value": 4})
    asyncio.run(check())
