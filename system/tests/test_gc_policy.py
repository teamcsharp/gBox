"""gbox serve's garbage-collection policy (gbox/gc_policy.py). It changes process-wide GC state, so every check runs in
a child interpreter, never in the pytest process."""
import json
import os
import subprocess
import sys
from pathlib import Path

SYSTEM = Path(__file__).resolve().parents[1]


def _child(code, **env):
    out = subprocess.run([sys.executable, "-c", code], cwd=SYSTEM, capture_output=True, text=True, timeout=120,
                         env={**os.environ, "PYTHONPATH": str(SYSTEM), **env})
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


PROBE = """
import gc, json
from gbox import gc_policy
logs = []
keep = [{"live": [i]} for i in range(1000)]
before = gc.get_freeze_count()      # an imported library may already have frozen a few objects
t = gc_policy.apply(freeze_after_s=0, log=logs.append)
if t is not None:
    t.join(30)
print(json.dumps({"threshold": gc.get_threshold(), "frozen": gc.get_freeze_count() - before, "logs": logs,
                  "thread": t is not None}))
"""


def test_serve_raises_the_young_threshold_and_freezes_the_warm_heap_once():
    got = _child(PROBE)
    assert got["thread"] and got["threshold"][0] == 20000 and got["threshold"][1:] == [10, 10]
    assert got["frozen"] > 1000, "the live heap (modules and the probe's objects) is in the permanent generation"
    assert len(got["logs"]) == 1 and "froze" in got["logs"][0]


def test_opt_out_keeps_cpython_defaults():
    got = _child(PROBE, GBOX_GC_POLICY="0")
    assert got == {"threshold": [700, 10, 10], "frozen": 0, "logs": [], "thread": False}


def test_a_disabled_or_higher_threshold_is_left_alone():
    got = _child("import gc, json\nfrom gbox import gc_policy\ngc.set_threshold(0)\nt = gc_policy.apply(freeze_after_s=3600)\n"
                 "print(json.dumps({'threshold': gc.get_threshold()}))")
    assert got["threshold"][0] == 0
    got = _child("import gc, json\nfrom gbox import gc_policy\ngc.set_threshold(50000, 10, 10)\n"
                 "t = gc_policy.apply(freeze_after_s=3600)\nprint(json.dumps({'threshold': gc.get_threshold()}))")
    assert got["threshold"][0] == 50000


def test_only_gbox_serve_applies_it():
    src = (SYSTEM / "gbox" / "__main__.py").read_text(encoding="utf-8")
    serve = src[src.index('if a.cmd == "serve":'):src.index('elif a.cmd == "worker":')]
    assert "gc_policy.apply()" in serve
    assert "gc_policy" not in (SYSTEM / "gbox" / "server.py").read_text(encoding="utf-8"), "never in create_app (tests)"
