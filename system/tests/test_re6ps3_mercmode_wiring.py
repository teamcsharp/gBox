"""Request 3114: RE6 PS3 (BLUS30855) MercMode wiring - the shared engine's map template,
the revision gate, and the honest-unmeasured behavior of the interface-complete driver
gbox/mercs/titles/re6_ps3.py. No measured address is asserted: every live reader is owed
to a live RPCS3 session (docs/RE6-MERCMODE-HANDOFF.md steps 2-6)."""
import json
import os
import random

import pytest

from gbox import re6_ps3_unlock as U
from gbox import mercmode
from gbox.mercs.titles import re6_ps3 as D

MAP = os.path.join(os.path.dirname(__file__), "..", "profiles", "gamedata", "BLUS30855-ram.json")


class Mem:
    """Sparse big-endian guest memory: word bytes + contiguous name blobs; rd() raises when unmapped."""

    def __init__(self, words=None, blobs=None):
        self.words = dict(words or {})
        self.blobs = dict(blobs or {})

    def rd(self, addr, n):
        out = bytearray()
        for i in range(n):
            a = addr + i
            if a in self.words:
                out.append(self.words[a] & 0xFF)
            else:
                hit = None
                for start, blob in self.blobs.items():
                    if start <= a < start + len(blob):
                        hit = blob[a - start]
                        break
                if hit is None:
                    raise KeyError(hex(a))
                out.append(hit)
        return bytes(out)

    @staticmethod
    def w(addr, v):
        import struct
        return {addr + i: b for i, b in enumerate(struct.pack(">I", v))}


def node_mem(good_name=True):
    m = Mem()
    m.words.update(Mem.w(D.SPLAYER_DTI_NODE, D.SPLAYER_NODE_CLASS))
    m.words.update(Mem.w(D.SPLAYER_DTI_NODE + D.NODE_NAME, D.SPLAYER_NAME_VA))
    m.words.update(Mem.w(D.SPLAYER_DTI_NODE + D.NODE_INSTANCE_CANDIDATE, 0x2000000))
    m.blobs[D.SPLAYER_NAME_VA] = b"sPlayer\x00" if good_name else b"sPlay3r\x00"
    return m


def test_eboot_hash_consistent_across_sources():
    assert len(U.EBOOT_SHA256) == 64
    b = mercmode.TITLES["re6"]["backends"]["ps3"]
    assert b["eboot_sha256"] == U.EBOOT_SHA256
    t = json.load(open(MAP))
    assert t["match"]["eboot_sha256"] == U.EBOOT_SHA256
    assert t["match"]["game_ids"] == [b["game_id"]]
    assert b["title_id"] == t["id"] == "BLUS30855"
    assert b["app_ver"] == t["match"]["app_ver"] == "01.00"


def test_map_template_honest_gating():
    t = json.load(open(MAP))
    m = t["mercs"]
    assert m["ready"] is False
    assert m["driver"] == m["menus"] == "gbox.mercs.titles.re6_ps3"
    assert m["jump_at"] is None
    assert isinstance(t["fields"], dict)
    assert t["fields"], "pending reader table must not be empty"
    for name, spec in t["fields"].items():
        assert spec["addr"] is None, name
        assert spec["status"] in ("pending_measurement", "partial"), name


def test_screen_unknown_and_step_none_when_unmeasured():
    assert D.screen(Mem())["where"] == "unknown"
    assert D.step({"where": "unknown"}) is None
    assert D.wandered({"where": "unknown"}) is None
    assert D.screen(Mem())["cursor"] is None


def test_splayer_node_accepts_pinned_revision():
    n = D.splayer_node(node_mem(good_name=True))
    assert n is not None
    assert n["node"] == D.SPLAYER_DTI_NODE
    assert n["name"] == "sPlayer"
    assert n["instance"] == 0x2000000


def test_splayer_node_rejects_wrong_revision_or_garbage():
    assert D.splayer_node(node_mem(good_name=False)) is None
    assert D.splayer_node(Mem()) is None


def test_roster_never_picks_last_and_stage_pick_terminates():
    r = D.Roster(rng=random.Random(7))
    first = r.started()
    want = r.want()
    assert D.CHARACTERS[want] != first
    sp = D.StagePick(rng=random.Random(3))
    scr = {"where": "select_stage"}
    presses = 0
    while True:
        k = sp.key(scr)
        sp.pressed(scr, k)
        presses += 1
        assert k in ("a", "dright", "dleft")
        if k == "a":
            break
        assert presses < 20


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
