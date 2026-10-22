"""RE6 (Xbox 360, Xenia) RAM map, request 3023: partial map from the documented memory map (docs/re6.md)."""
import struct
from pathlib import Path

from gbox import ram_map
from gbox.mercs import vocab

MAP_ID = "0871eee3b68cdea3"
# publish_task_changes only accepts gbox/ tests/ docs/ paths; the map ships here and is copied to
# profiles/gamedata/<id>-ram.json at merge (same bytes).
MAP_FILE = Path(__file__).resolve().parents[1] / "docs" / "re6-ram-map-0871eee3b68cdea3.json"
SPLAYER, SAVE = 0x83CA52FC, 0x83CA4F98


class Mem:
    def __init__(self):
        self.b = {}

    def put(self, a, fmt, *v):
        self.b[a] = struct.pack(fmt, *v)

    def rd(self, a, n):
        buf = bytearray(n)
        for base, d in self.b.items():
            lo, hi = max(a, base), min(a + n, base + len(d))
            if lo < hi:
                buf[lo - a:hi - a] = d[lo - base:hi - base]
        return bytes(buf)


def world(pos=(1.0, 2.0, 3.0), hp=900, hp_max=1000, stage_mask=0x7, char_mask=0x10101):
    m = Mem()
    sp, up, save = 0x40100000, 0x40200000, 0x40300000
    m.put(SPLAYER, ">I", sp)
    m.put(sp + 0x28, ">I", up)
    m.put(up + 0x50, ">3f", *pos)
    m.put(up + 0xF20, ">hh", hp, hp_max)
    m.put(up + 0x3EE8, ">I", 2)
    m.put(SAVE, ">I", save)
    m.put(save + 0x30 + 0x974, ">II", stage_mask, char_mask)
    return m


def test_map_loads_and_vocabulary_is_consistent():
    m = ram_map.find(str(MAP_FILE))
    assert m.platform == "xbox360" and m.id == MAP_ID
    assert [p for p in ram_map.check(str(MAP_FILE)) if "file name" not in p] == []
    # the only problems are the declared gaps: required names still unmapped (no live evidence yet)
    gaps = {"screen", "merc.timer", "player.facing", "player.state", "enemies"}
    assert {x.split(":")[0] for x in vocab.check(vocab.profile(m))} == gaps


def test_every_field_carries_evidence():
    for name, f in ram_map.find(str(MAP_FILE)).fields.items():
        assert f.spec.get("evidence"), name


def test_partial_map_is_not_marked_ready():
    prof = vocab.profile(ram_map.find(str(MAP_FILE)))
    assert not prof.mercs.get("ready")
    assert prof.names["merc.timer"] is None and prof.names["enemies"] is None   # unmapped until measured live


def test_reads_the_fixture_through_pointer_chains():
    v = ram_map.find(str(MAP_FILE)).read(world().rd)
    assert v["player.pos"] == [1.0, 2.0, 3.0] and v["player.hp"] == 900 and v["player.hp_max"] == 1000
    assert v["player.slot"] == 2
    assert v["merc.stage_mask"] == 7 and v["merc.character_mask"] == 0x10101


def test_null_player_pointer_is_reported_not_guessed():
    m = world()
    m.put(SPLAYER, ">I", 0)
    v = ram_map.find(str(MAP_FILE)).read(m.rd)
    assert v["player.pos"] is None and "player.pos" in v.errors
