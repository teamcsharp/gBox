"""Local acceptance tests for the CVSE unlock profile gate and cast-swap planner.

These are pure-logic tests: no worker, no game launch, no save access, no
network.  They pin the safety gates demanded by request #2072 (77e268d9d6f24adc):

  * an unverified build (or a wrong game/platform/title) never reaches a
    native writer or a live launch job;
  * the CVSE profile is registered against the exact catalog game id, the
    pinned owned-source SHA256 and the GEOE08 disc identity;
  * the cast-swap plan targets only the agent workers (i9-NUC / Spark), never
    the operator play PC, keeps launch:false until operator acceptance, keeps
    the whole_cast replacement preference, covers every build-feedback
    required context, and records save-restore steps before any write.
"""
import hashlib
import json
from types import SimpleNamespace

import pytest

from gbox import game_unlocks as G
from gbox import cvs2eo_unlock as C
from gbox import cvs2eo_inventory as INV

CVSE = C.CVSE_ID
SOURCE_SHA = C.SOURCE_SHA256
OPERATOR_PC = "JAYBUILTFINALE"


def game(**over):
    g = {"game_id": CVSE, "platform": "gamecube",
         "title": "Capcom vs. SNK 2 EO - Millionaire Fighting 2001 (USA)"}
    g.update(over)
    return g


# --------------------------------------------------------------------------
# inventory integrity: the pinned evidence file must match the inventory code
# --------------------------------------------------------------------------

def test_pinned_inventory_matches_inventory_code():
    ev_path = C.evidence_path()
    assert ev_path.exists(), "pinned evidence file missing"
    ev = json.loads(ev_path.read_text())
    assert ev["source"]["sha256"] == SOURCE_SHA
    assert C.inventory_digest() == ev.get("_inventory_sha256"), (
        "cvs2eo_inventory.py changed without regenerating the pinned evidence")


def test_inventory_digest_is_content_addressed():
    src = (C.evidence_path().parents[2] / "gbox" / "cvs2eo_inventory.py").read_bytes()
    assert C.inventory_digest() == hashlib.sha256(src).hexdigest()


# --------------------------------------------------------------------------
# profile gate: verified only for the exact game/build
# --------------------------------------------------------------------------

def test_profile_verified_for_exact_game():
    p = G.profile_for(game())
    assert p["status"] == "verified_profile" and p["verified"] is True
    assert p["game_id"] == CVSE
    assert p["template_sha256"] == C.CVSE_EVIDENCE_SHA256
    assert "operator gameplay" in " ".join(p["exclusions"]).lower() or p["exclusions"]


@pytest.mark.parametrize("bad", [
    {"platform": "ps2"},
    {"game_id": "1" * 16},
    {"title": "Capcom vs SNK 2 (unverified title string)"},
])
def test_profile_rejects_wrong_build(bad):
    p = G.profile_for(game(**bad))
    assert p["verified"] is False and p["profile"] is None


def test_unverified_never_reaches_writer(monkeypatch):
    def boom(*a, **k):
        pytest.fail("native writer reached for unverified build")
    for mod_name, attr in (("re6_tool", "pre_launch"), ("cvs2eo_unlock", "apply")):
        import importlib
        mod = importlib.import_module(f"gbox.{mod_name}")
        monkeypatch.setattr(mod, attr, boom, raising=False)
    import gbox.game_unlocks as GU
    # wrong platform -> gated out before any hook
    assert GU.pre_launch({"game_id": CVSE, "platform": "ps2"}, SimpleNamespace())["applied"] is False
    monkeypatch.setattr(C, "load_evidence", lambda: None)
    r = GU.pre_launch(game(), SimpleNamespace())
    assert r["applied"] is False and r["state"] == "research_pending"


# --------------------------------------------------------------------------
# cast-swap planner gates
# --------------------------------------------------------------------------

def test_swap_plan_requires_verified_profile():
    w = {"id": "w" * 16, "name": "i9-nuc"}
    r = C.cast_swap_plan(game(title="wrong"), w)
    assert r["status"] == "unsupported_cast_swap" and r["jobs"] == [] and r["executed"] is False


def test_swap_plan_never_targets_operator_pc():
    w = {"id": "w" * 16, "name": OPERATOR_PC}
    with pytest.raises(ValueError):
        C.cast_swap_plan(game(), w)


def test_swap_plan_is_launch_false_whole_cast_and_save_safe():
    w = {"id": "a" * 16, "name": "i9-nuc"}
    r = C.cast_swap_plan(game(), w, mod="cvse-replacement", save_session_id="a" * 16 + "-sess")
    assert r["status"] == "planned" and r["executed"] is False
    assert r["replacement_preference"] == "whole_cast"
    assert set(r["required_contexts"]) == {
        "gameplay", "in_engine_cutscenes", "prerecorded_cinematics"}
    recipe = [j for j in r["jobs"] if j["tool"] == "mod"][0]
    assert recipe["input"]["launch"] is False
    assert recipe["input"]["request_id"] == C.REQUEST_ID
    assert r["audio_policy"] == "2% volume"
    assert w["id"] == recipe["require_worker"]
    # save protection precedes any asset write
    tools = [j["tool"] for j in r["jobs"]]
    assert tools.index("memory") < tools.index("mod") or "save" in str(r["jobs"][0])
    assert r["save_protection"]["restores_before_next_cast"] is True


def test_swap_plan_rejects_foreign_session():
    w = {"id": "a" * 16, "name": "spark"}
    with pytest.raises(ValueError):
        C.cast_swap_plan(game(), w, save_session_id="deadbeefdeadbeef-x")


def test_swap_plan_accepts_agent_workers_only():
    # a worker name that is neither agent nor operator is refused
    w = {"id": hashlib.sha1("otherpc".encode()).hexdigest()[:16], "name": "otherpc"}
    with pytest.raises(ValueError):
        C.cast_swap_plan(game(), w)


# --------------------------------------------------------------------------
# live acceptance verdict gate (operator/agent gameplay, never assumed)
# --------------------------------------------------------------------------

def test_live_acceptance_requires_operator_verdict():
    r = C.live_acceptance_report(required_contexts=C.REQUIRED_CONTEXTS, observations=[])
    assert r["accept"] is False and set(r["missing"]) == set(C.REQUIRED_CONTEXTS)

    obs = [
        {"context": "gameplay", "worker": "w1", "session_id": "w1-s", "state": "ended",
         "operator_verified": True, "save_restored": True, "evidence": "/e/1"},
        {"context": "in_engine_cutscenes", "worker": "w1", "session_id": "w1-s", "state": "ended",
         "operator_verified": True, "save_restored": True, "evidence": "/e/2"},
    ]
    r = C.live_acceptance_report(required_contexts=C.REQUIRED_CONTEXTS, observations=obs)
    assert r["accept"] is False and r["missing"] == ["prerecorded_cinematics"]

    obs.append({"context": "prerecorded_cinematics", "worker": "w2", "session_id": "w2-s",
                "state": "ended", "operator_verified": True, "save_restored": True,
                "evidence": "/e/3"})
    r = C.live_acceptance_report(required_contexts=C.REQUIRED_CONTEXTS, observations=obs)
    assert r["accept"] is True and r["missing"] == []


def test_live_acceptance_rejects_unended_or_unrestored():
    obs = [{"context": c, "worker": "w", "session_id": "w-s", "state": "running",
            "operator_verified": True, "save_restored": True, "evidence": "/e"}
           for c in C.REQUIRED_CONTEXTS]
    assert C.live_acceptance_report(C.REQUIRED_CONTEXTS, obs)["accept"] is False
    obs[0]["state"] = "ended"
    obs[0]["save_restored"] = False
    assert C.live_acceptance_report(C.REQUIRED_CONTEXTS, obs)["accept"] is False
    # agent (not operator) verification alone is never enough to close
    obs[0]["save_restored"] = True
    for o in obs:
        o["state"] = "ended"
        o["operator_verified"] = False
        o["agent_verified"] = True
    assert C.live_acceptance_report(C.REQUIRED_CONTEXTS, obs)["accept"] is False
    # ...but is enough for agent-side progress evidence
    assert C.live_acceptance_report(C.REQUIRED_CONTEXTS, obs, allow_agent_only=True)["accept"] is True


# --------------------------------------------------------------------------
# recipe integrity: published recipe must bind to this request + evidence
# --------------------------------------------------------------------------

def test_recipe_sha_binds_request_and_evidence():
    w = {"id": "f" * 16, "name": "i9-nuc"}
    a = C.cast_swap_plan(game(), w)
    b = C.cast_swap_plan(game(), w, save_session_id="f" * 16 + "-s")
    assert a["recipe_sha256"] != b["recipe_sha256"]
    assert len(a["recipe_sha256"]) == 64
    # publishing gate: recipe acks must be explicit, never defaulted
    with pytest.raises(ValueError):
        C.publish_guard(requests_ack=False, feedback_ack=True, recipe_sha256=a["recipe_sha256"],
                        change_id="c" * 16, worker_id=w["id"])
    with pytest.raises(ValueError):
        C.publish_guard(requests_ack=True, feedback_ack=True, recipe_sha256="0" * 64,
                        change_id="c" * 16, worker_id=w["id"])
    ok = C.publish_guard(requests_ack=True, feedback_ack=True,
                         recipe_sha256=a["recipe_sha256"], change_id="c" * 16, worker_id=w["id"])
    assert ok["publish_allowed"] is True
