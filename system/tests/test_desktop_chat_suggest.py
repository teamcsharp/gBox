"""#71: the desktop chat box must not pop suggestions on focus when the current
conversation already has messages (or when its content isn't loaded yet).

The gate lives inline in clients/desktop/index.html, so the test extracts the
real chatFresh() function and executes it in Node against the states the
focus listener sees.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parents[1] / "clients" / "desktop" / "index.html"

CASES = [
    # (state, expected) -- mirrors CH fields read by chatFresh
    ({"cid": None, "n": 0, "busy": False, "seen": False}, True),   # no conversation yet: suggest
    ({"cid": "c1", "n": 5, "busy": False, "seen": True}, False),   # has messages: never suggest
    ({"cid": "c1", "n": 0, "busy": False, "seen": False}, False),  # persisted chat not loaded yet: don't guess
    ({"cid": "c1", "n": 0, "busy": False, "seen": True}, True),    # loaded empty conversation: suggest
    ({"cid": "c1", "n": 2, "busy": True, "seen": True}, False),    # reply streaming: don't cover it
]


def _chat_fresh_source() -> str:
    html = HTML.read_text(encoding="utf-8")
    m = re.search(r"function chatFresh\s*\(\)\s*\{(.*?)\n\}", html, re.S)
    assert m, "chatFresh() gate not found in clients/desktop/index.html"
    return f"function chatFresh() {{{m.group(1)}\n}}"


def test_focus_handler_uses_chat_fresh_not_raw_count():
    html = HTML.read_text(encoding="utf-8")
    assert "if (!CH.n) suggest()" not in html, (
        "focus handler still gates on the raw CH.n count; an unloaded "
        "conversation has CH.n == 0 and would show suggestions")
    assert re.search(r'addEventListener\("focus",\s*\(\)\s*=>\s*\{\s*loadHistory\(\);\s*if\s*\(chatFresh\(\)\)\s*suggest\(\);\s*\}\)', html), (
        "focus handler must call chatFresh() before suggest()")


def test_chat_fresh_gate_behavior():
    if shutil.which("node") is None:
        pytest.skip("node unavailable")
    script = _chat_fresh_source() + """
let CH = {};
const cases = %s;
const out = cases.map(([st, want]) => { CH = st; const got = chatFresh(); return {got, want, st}; });
console.log(JSON.stringify(out));
""" % json.dumps(CASES)
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    results = json.loads(r.stdout)
    for i, (res, (state, want)) in enumerate(zip(results, CASES)):
        assert res["got"] is want, (
            f"case {i}: chatFresh() = {res['got']!r}, want {want!r} for CH={state}")


def test_seen_flag_kept_in_sync_with_loads():
    html = HTML.read_text(encoding="utf-8")
    # full load completes -> content known
    assert "if (full) CH.seen = true;" in html
    # conversation switches reset the knowledge
    assert "CH.game = g; CH.n = 0; CH.seen = false;" in html
    assert "CH.cid = ci.dataset.c; CH.n = 0; CH.seen = false; chatSave();" in html
    # a freshly created conversation is known-empty
    assert "CH.n = 0; CH.seen = true;" in html
