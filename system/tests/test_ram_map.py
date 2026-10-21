"""RAM maps (gbox/ram_map.py, docs/ram_maps.md): the format, pointer chains, types, arrays and struct arrays, batched
reads through any reader, events, map lookup and the overlay that "add to map" writes. The RE4 GameCube map
(profiles/gamedata/G4BE08-ram.json) must read exactly what gbox/re4_merc_bot.py reads with its hard-coded offsets."""
import json
import math
import struct

import pytest

from gbox import ram_map, re4_merc_bot as R

MEM1 = 0x80000000


class FakeRam:
    """Memory from an image; counts every read (and every batch, when used as a read_many reader)."""

    def __init__(self, size=0x1800000, base=MEM1):
        self.ram, self.base, self.reads, self.batches = bytearray(size), base, [], []

    def put(self, addr, fmt, *v):
        struct.pack_into(fmt, self.ram, addr - self.base, *v)

    def read(self, addr, n):
        self.reads.append((addr, n))
        off = addr - self.base
        if off < 0 or off + n > len(self.ram):
            raise ValueError(f"{addr:#x} unmapped")
        return bytes(self.ram[off:off + n])


class Batched(FakeRam):
    def read_many(self, ranges):
        self.batches.append(list(ranges))
        out = []
        for a, n in ranges:
            try:
                out.append(self.read(a, n))
            except ValueError as e:
                out.append(e)
        return out


def re4_ram(cls=FakeRam, room=0x400, timer_s=87.3, combo=12, leon=(1000.0, 0.0, 2000.0), rot=0.5, hp=1860,
            ganados=((1000.0, 0.0, 4000.0, 1000, 1000), (5000.0, 0.0, 2000.0, 300, 1800)), dead=(7000.0, 0.0, 0.0),
            stride=0xDE0, pad=0x0120, prompt=0):
    """RE4's structures where the bot and the map read them: Leon is EmMgr slot 0, two live Ganados, one dead slot;
    the room's area events (AevMgr: a door, an area) and items (a Time Bonus hourglass, one taken); the prompt kind."""
    m = cls()
    m.ram[:6] = b"G4BE08"
    pg, psys, em = 0x8027F7D0, 0x80287E58, 0x810D3000
    m.put(R.P_GLOBAL, ">I", pg)
    m.put(0x802B2284, ">I", psys)
    m.put(psys + 4, ">I", 0x0F000000)
    m.put(pg + R.G_ROOM, ">H", room)
    m.put(pg + 0x4FA4, ">I", 4500)
    m.put(pg + 0x4FB0, ">h", hp)
    m.put(R.P_PLAYER, ">I", em)
    m.put(em + 0x94, ">3f", *leon)
    m.put(em + 0xA4, ">f", rot)
    m.put(R.AIM_PITCH, ">f", -0.25)                   # the aim's vertical blend (a global, kept between aims)
    slots = len(ganados) + 2
    m.put(R.EMMGR, ">III", em, slots, stride)
    m.put(em, ">I", 0x601)
    for k, (x, y, z, h, hmax) in enumerate(ganados, start=1):
        o = em + k * stride
        m.put(o, ">I", 0x401)
        m.put(o + 0x94, ">3f", x, y, z)
        m.put(o + 0x320, ">hh", h, hmax)
        m.ram[o + 0x398 - MEM1] = k
    o = em + (len(ganados) + 1) * stride                   # a dead slot: flags set, no ESL entry
    m.put(o, ">I", 0x401)
    m.put(o + 0x94, ">3f", *dead)
    m.ram[o + 0x398 - MEM1] = 0xFF
    m.put(R.MERC_TIMER, ">I", round(timer_s * 30))
    m.put(R.MERC + 0x28, ">II", combo, 150)
    m.put(0x80287EA2, ">H", pad)                         # this frame's buttons (pad.held)
    m.put(0x80287E9E, ">H", 0)                           # the frame before (pad.held_prev)
    m.ram[0x80279320 - MEM1] = prompt                   # prompt.kind: the button of the prompt drawn this frame
    mgr, aev, ita = 0x80289B3C, 0x80700000, 0x80701000      # AevMgr: +0 / +8 table headers (+6 count), +4 / +C entries
    m.put(0x802B3178, ">I", mgr)
    m.put(mgr, ">IIII", aev, aev + 0x100, ita, ita + 0x100)
    m.put(aev + 6, ">H", 2)
    for i, (kind, label) in enumerate(((1, 0x10), (4, 0x5))):         # a door (OPEN), an area (JUMP OVER)
        o = aev + 0x100 + i * 0x9C
        m.ram[o + 0x34 - MEM1], m.ram[o + 0x35 - MEM1], m.ram[o + 0x36 - MEM1], m.ram[o + 0x4A - MEM1] = 1, kind, i, label
    m.put(ita + 6, ">H", 2)
    for i, (on, item) in enumerate(((1, 0x73), (0, 0x75))):          # a Time Bonus still there, a Combo Bonus taken
        o = ita + 0x100 + i * 0x9C
        m.ram[o + 0x34 - MEM1], m.ram[o + 0x36 - MEM1] = on, 0x80 + i
        m.put(o + 0x5C, ">3f", 19401.0, 0.0, -6857.0)
        m.put(o + 0x78, ">H", item)
    return m


class Rd:
    """The bot's memory interface (ShmMem / AdMem: rd)."""

    def __init__(self, fake):
        self.rd = fake.read


def round_errors(v) -> dict:
    """The fields that failed to read in a round. The "menu" group reads the title task's work area through task 0's
    stack (docs/re4-menus.md): it exists only while the title runs, so in a round its fields fail by design
    (tests/test_re4_menus.py reads them at the title)."""
    return {k: e for k, e in v.errors.items() if not k.startswith("menu.")}


def test_the_re4_map_reads_what_the_mercenaries_bot_reads():
    fake = re4_ram()
    m = ram_map.load("G4BE08")
    v = m.read(fake)
    snap = R.snapshot(Rd(fake))
    assert v["game.room"] == snap["room"] == 0x400 and v.label("game.room") == "Mercenaries: Pueblo (village)"
    assert v["game.stage"] == 4 and v.label("game.stage") == "The Mercenaries"
    assert v["merc.timer"] == pytest.approx(snap["timer"], abs=0.05) and v["merc.combo"] == snap["combo"] == 12
    assert v["merc.combo_timer"] == pytest.approx(5.0)
    assert v["player.ptr"] == snap["player"]["ptr"]
    assert v["player.pos"] == pytest.approx(list(snap["player"]["pos"]))
    assert v["player.facing"] == pytest.approx(snap["player"]["rot"])
    assert v["player.aim_pitch"] == pytest.approx(-0.25) == snap["player"]["pitch"] / R.PITCH_SCALE
    assert v["player.hp"] == 1860
    assert v["game.money"] == 4500 and v["game.disc_id"] == "G4BE08"
    assert v["pad.held"] == 0x120 and v.label("pad.held") == "R, A" and v.label("pad.held_prev") == "none"
    assert v.label("save.extras") == "Mercenaries: Ada, Mercenaries: HUNK, Mercenaries: Krauser, Mercenaries: Wesker"
    rows = v["enemies"]
    assert [r["index"] for r in rows] == [e["slot"] for e in snap["enemies"]] == [1, 2]    # the dead slot is left out
    for r, e in zip(rows, snap["enemies"]):
        assert r["pos"] == pytest.approx(list(e["pos"]))
        if "hp" in e:                                    # the bot reads health too (re4_merc_bot v2)
            assert (r["hp"], r["hp_max"]) == (e["hp"], e["hp_max"])
    assert (rows[1]["hp"], rows[1]["hp_max"]) == (300, 1800) and v.counts["enemies"] == 4
    assert not round_errors(v)
    # the prompt and area-event fields (#724): read through two-level chains and counts from other fields
    assert v["prompt.kind"] == 0 and v.label("prompt.kind") == "none"
    assert [(e["type"], e["label"]) for e in v["aev.entries"]] == [(1, 0x10), (4, 0x5)]
    assert [(i["item_id"], i["enabled"]) for i in v["aev.items"]] == [(0x73, 1), (0x75, 0)]
    taking = ram_map.load("G4BE08").read(re4_ram(prompt=1), names=["prompt.kind"])
    assert taking.label("prompt.kind") == "A"


def test_the_enemy_table_follows_the_stride_the_game_reports():
    v = ram_map.load("G4BE08").read(re4_ram(stride=0x400))
    assert [r["index"] for r in v["enemies"]] == [1, 2] and v["enemies"][0]["pos"] == pytest.approx([1000.0, 0.0, 4000.0])
    fake = re4_ram()
    fake.put(0x8027DF28, ">I", 0)                         # a stride of 0: never read as a table
    v = ram_map.load("G4BE08").read(fake)
    assert v["enemies"] is None and "not a plausible element size" in v.errors["enemies"]


def test_reads_are_batched_per_pointer_level():
    fake = re4_ram(Batched)
    m = ram_map.load("G4BE08")
    v = m.read(fake)
    # static fields + pointer bases, then each pointer level, then the counted tables: a batch per level, not per field
    assert len(fake.batches) <= 5 < len(m.fields) and not round_errors(v)
    assert v.reads == sum(len(b) for b in fake.batches) and v.bytes == sum(n for b in fake.batches for _, n in b)
    big = max(n for b in fake.batches for _, n in b)
    assert big < 4 * 0xDE0                                 # live-slot spans, never the whole 80-slot table at once


def spec(fields, **kw):
    return {"format": ram_map.FORMAT, "id": "TEST01", "platform": "gamecube", "fields": fields, **kw}


def test_pointer_chains_are_cheat_engine_style_and_stop_at_null():
    fake = FakeRam()
    fake.put(0x80001000, ">I", 0x80002000)
    fake.put(0x80002010, ">I", 0x80003000)
    fake.put(0x80003008, ">H", 0xBEEF)
    m = ram_map.RamMap(spec({"a.deep": {"pointer": {"base": "0x80001000", "offsets": ["0x10", "0x8"]}, "type": "u16"},
                             "a.list": {"pointer": ["0x80001000", "0x10", "0x8"], "type": "u16", "format": "hex"},
                             "a.null": {"pointer": {"base": "0x80001100", "offsets": [4]}, "type": "u32"}}))
    v = m.read(fake)
    assert v["a.deep"] == v["a.list"] == 0xBEEF and v.address["a.deep"] == 0x80003008
    assert v.display("a.list") == "0xBEEF"
    assert v["a.null"] is None and v.errors["a.null"] == "null pointer: 0x80001100 holds 0x00000000"
    row = next(r for r in v.rows() if r["name"] == "a.null")
    assert row["value"] is None and "null pointer" in row["error"]


def test_types_endianness_bit_fields_scale_enum_and_flags():
    fake = FakeRam()
    fake.put(0x80000100, "<H", 0x1234)
    fake.put(0x80000104, ">h", -5)
    fake.put(0x80000108, ">f", 2.5)
    fake.put(0x8000010C, ">I", 0xA5)
    fake.put(0x80000110, ">I", 900)
    fake.ram[0x120:0x126] = b"AB\0CDE"
    fake.put(0x80000130, ">Q", 2 ** 40)
    fake.put(0x80000140, ">d", float("nan"))
    m = ram_map.RamMap(spec({
        "t.le": {"address": "0x80000100", "type": "u16", "endian": "little"},
        "t.s16": {"address": "0x80000104", "type": "i16", "valid": [0, 100]},
        "t.f32": {"address": "0x80000108", "type": "f32", "units": "m"},
        "t.hi": {"address": "0x8000010C", "type": "u32", "mask": "0xF0", "shift": 4, "enum": {"10": "ten"}},
        "t.bits": {"address": "0x8000010C", "type": "u32", "flags": {"0x1": "one", "0x4": "four", "0x8": "eight"}},
        "t.clock": {"address": "0x80000110", "type": "u32", "scale": 1 / 30, "bias": 1, "units": "s"},
        "t.str": {"address": "0x80000120", "type": "str", "length": 6},
        "t.raw": {"address": "0x80000120", "type": "bytes", "length": 3},
        "t.u64": {"address": "0x80000130", "type": "u64"},
        "t.flag": {"address": "0x80000121", "type": "bool"},
        "t.ptr": {"address": "0x8000010C", "type": "ptr"},
        "t.nan": {"address": "0x80000140", "type": "f64"}}))
    v = m.read(fake)
    assert v["t.le"] == 0x1234 and v["t.s16"] == -5 and v["t.f32"] == 2.5
    assert v["t.hi"] == 10 and v.label("t.hi") == "ten" and v.display("t.hi") == "ten (10)"
    assert v["t.bits"] == 0xA5 and v.label("t.bits") == "one, four, 0xA0"
    assert v["t.clock"] == pytest.approx(31.0) and v.display("t.clock") == "31 s"
    assert (v["t.str"], v["t.raw"], v["t.u64"], v["t.flag"], v["t.ptr"]) == ("AB", "414200", 2 ** 40, True, 0xA5)
    assert v.display("t.ptr") == "0x000000A5" and v.display("t.f32") == "2.5 m"
    assert v.suspect("t.s16") and not v.suspect("t.f32")
    assert math.isnan(v["t.nan"])
    rows = {r["name"]: r for r in v.rows()}
    assert rows["t.nan"]["value"] is None and rows["t.s16"]["suspect"] is True and rows["t.hi"]["label"] == "ten"
    json.dumps(v.rows(), allow_nan=False)                  # the API answers with these


def test_arrays_counts_from_fields_and_struct_live_conditions():
    fake = FakeRam()
    fake.put(0x80000200, ">I", 4)                          # count
    fake.put(0x80000204, ">I", 0x20)                       # stride
    fake.put(0x80000300, ">4H", 7, 8, 9, 10)
    for i, (flags, hp, kind) in enumerate([(1, 10, 2), (0, 0, 0), (3, 30, 5), (1, 40, 0xFF)]):
        o = 0x80000400 + i * 0x20
        fake.put(o, ">I", flags)
        fake.put(o + 4, ">h", hp)
        fake.ram[o + 8 - MEM1] = kind
        fake.put(o + 0xC, ">2f", i, -i)
    m = ram_map.RamMap(spec({
        "arr.count": {"address": "0x80000200", "type": "u32"},
        "arr.stride": {"address": "0x80000204", "type": "u32"},
        "arr.vals": {"address": "0x80000300", "type": "u16", "count": "@arr.count"},
        "arr.tail": {"address": "0x80000300", "type": "u16", "count": 4, "first": 2},
        "things": {"address": "0x80000400", "type": "struct", "stride": "@arr.stride", "count": "@arr.count",
                   "live": {"all": [{"field": "flags", "mask": 1, "ne": 0}, {"not": {"field": "kind", "eq": "0xFF"}}]},
                   "fields": {"flags": {"offset": 0, "type": "u32"}, "hp": {"offset": 4, "type": "s16"},
                              "kind": {"offset": 8, "type": "u8", "enum": {"2": "zombie", "5": "boss"}},
                              "xy": {"offset": "0xC", "type": "f32", "count": 2}}}}))
    v = m.read(fake)
    assert v["arr.vals"] == [7, 8, 9, 10] and v["arr.tail"] == [9, 10]
    assert [(r["index"], r["hp"], r["kind"]) for r in v["things"]] == [(0, 10, 2), (2, 30, 5)]
    assert v["things"][1]["xy"] == [2.0, -2.0] and v["things"][1]["address"] == 0x80000440
    row = next(r for r in v.rows() if r["name"] == "things")
    assert row["display"] == "2 live of 4" and row["rows"][1]["address"] == "0x80000440"
    sub = ram_map.RamMap(spec({"n": {"address": "0x80000200", "type": "u32"},
                               "only": {"address": "0x80000300", "type": "u16", "count": "@n"}})).read(fake, names=["only"])
    assert list(sub) == ["only"] and sub["only"] == [7, 8, 9, 10]          # its count was read, not reported


def test_changes_are_the_watched_fields_and_struct_elements():
    fake = FakeRam()
    fields = {"s.state": {"address": "0x80000500", "type": "u8", "enum": {"0": "idle", "3": "TAKE"}},
              "s.plain": {"address": "0x80000501", "type": "u8"},
              "s.watched": {"address": "0x80000502", "type": "u8", "watch": True},
              "s.pad": {"address": "0x80000504", "type": "u16", "flags": {"0x100": "A"}},
              "rows": {"address": "0x80000600", "type": "struct", "stride": 16, "count": 3, "watch": True,
                       "live": {"field": "alive", "ne": 0},
                       "fields": {"alive": {"offset": 0, "type": "u8"},
                                  "mode": {"offset": 1, "type": "u8", "enum": {"1": "walk", "2": "grab"}}}}}
    m = ram_map.RamMap(spec(fields))
    fake.ram[0x600] = fake.ram[0x610] = 1
    fake.ram[0x601] = 1
    a = m.read(fake)
    assert ram_map.changes(None, a) == []
    fake.ram[0x500], fake.ram[0x501], fake.ram[0x502] = 3, 9, 1
    fake.put(0x80000504, ">H", 0x100)
    fake.ram[0x601], fake.ram[0x610], fake.ram[0x620] = 2, 0, 1
    b = m.read(fake)
    ev = {e["field"]: e for e in ram_map.changes(a, b)}
    assert set(ev) == {"s.state", "s.watched", "s.pad", "rows[0].mode", "rows[1]", "rows[2]"}     # s.plain: not watched
    assert (ev["s.state"]["old_label"], ev["s.state"]["new_label"]) == ("idle", "TAKE")
    assert (ev["s.pad"]["old_label"], ev["s.pad"]["new_label"]) == ("none", "A")
    assert (ev["rows[0].mode"]["old_label"], ev["rows[0].mode"]["new_label"]) == ("walk", "grab")
    assert (ev["rows[1]"]["old"], ev["rows[1]"]["new"], ev["rows[2]"]["new"]) == ("live", None, "live")


@pytest.mark.parametrize("fields, msg", [
    ({"a.b": {"address": 1, "type": "u12"}}, "unknown type"),
    ({"a.b": {"type": "u8"}}, "give an address or a pointer"),
    ({"a.b": {"address": 1, "pointer": [1, 2], "type": "u8"}}, "give an address or a pointer"),
    ({"a.b": {"pointer": {"base": 1, "offsets": []}, "type": "u8"}}, "at least one offset"),
    ({"A.B": {"address": 1, "type": "u8"}}, "lowercase"),
    ({"a.b": {"address": 1, "type": "u8", "source": "guess"}}, "source is one of"),
    ({"a.b": {"address": 1, "type": "u8", "colour": "red"}}, "unknown key(s) colour"),
    ({"a.b": {"address": 1, "type": "u8", "count": "@nope"}}, "@nope is not a field"),
    ({"a.b": {"address": 1, "type": "u8", "live": {"field": "x", "eq": 1}}}, "live is for struct arrays"),
    ({"a.b": {"address": 1, "type": "struct", "stride": 4, "fields": {"x": {"address": 1, "type": "u8"}}}}, "has an offset"),
    ({"a.b": {"address": 1, "type": "struct", "stride": 4, "fields": {"x": {"offset": 0, "type": "u8"}},
              "live": {"field": "y", "eq": 1}}}, "not a sub-field"),
    ({"a.b": {"address": 1, "type": "str"}}, "needs a length"),
    ({"a.b": {"address": "0xZZ", "type": "u8"}}, "is not a number"),
])
def test_a_map_that_breaks_the_format_is_refused_with_the_field_named(fields, msg):
    with pytest.raises(ram_map.MapError, match="a.b|A.B") as e:
        ram_map.RamMap(spec(fields))
    assert msg in str(e.value)


def test_any_reader_shape_reads():
    fake = re4_ram()
    m = ram_map.load("G4BE08")
    for reader in (fake.read, Rd(fake), type("Ad", (), {"read_memory": lambda self, a, n: fake.read(a, n)})()):
        assert m.read(reader, names=["merc.combo"])["merc.combo"] == 12
    with pytest.raises(TypeError):
        m.read(object())


def test_maps_are_found_by_map_id_disc_id_game_id_or_session_and_from_memory():
    assert ram_map.find("G4BE08").id == "G4BE08"
    assert ram_map.find("78ab9efa2e310db4").id == "G4BE08"                    # the catalog's RE4 GC disc 1
    assert ram_map.find({"game_id": "e42c9b780c07c437", "title": "RE4 disc 2"}).id == "G4BE08"
    assert ram_map.find({"gecko_id": "G4BE08"}).id == "G4BE08"
    assert ram_map.find("0000000000000000") is None and ram_map.find({}) is None
    with pytest.raises(LookupError, match="no RAM map"):
        ram_map.load("nope")
    assert ram_map.detect(re4_ram(), "gamecube") == "G4BE08"
    assert ram_map.detect(FakeRam(), "gamecube") is None
    assert any(s["id"] == "G4BE08" and s["fields"] >= 20 for s in ram_map.summaries())


def test_promoted_fields_go_to_the_overlay_and_load_over_the_repo_map(tmp_path, monkeypatch):
    monkeypatch.setattr(ram_map, "OVERLAY_DIRS", [tmp_path / "ram_maps"])
    m = ram_map.promote("G4BE08", "prompt.action", {"address": "0x80400000", "type": "u8",
                                                    "enum": {"3": "TAKE", "5": "JUMP OVER"}, "source": "scan"})
    assert "prompt.action" in m.fields and m.overlay_fields == ["prompt.action"] and len(m.fields) > 20
    written = json.loads((tmp_path / "ram_maps" / "G4BE08-ram.json").read_text())
    assert list(written["fields"]) == ["prompt.action"]                       # only the promoted field, not the repo's
    fake = re4_ram()
    fake.ram[0x400000] = 5
    v = ram_map.load("78ab9efa2e310db4").read(fake)
    assert v.label("prompt.action") == "JUMP OVER" and v["merc.combo"] == 12
    with pytest.raises(ram_map.MapError, match="unknown type"):
        ram_map.promote("G4BE08", "prompt.bad", {"address": 1, "type": "u9"})
    assert list(json.loads((tmp_path / "ram_maps" / "G4BE08-ram.json").read_text())["fields"]) == ["prompt.action"]
    assert ram_map.unpromote("G4BE08", "prompt.action") and not ram_map.unpromote("G4BE08", "merc.combo")
    assert "prompt.action" not in ram_map.load("G4BE08").fields
    # a game without a map in the repo: the overlay is its map
    new = ram_map.promote("aaaa000011112222", "hud.lives", {"address": "0x80001000", "type": "u8", "source": "scan"},
                          base={"title": "Some game", "platform": "n64", "match": {"game_ids": ["aaaa000011112222"]}})
    assert new.title == "Some game" and new.platform == "n64" and list(new.fields) == ["hud.lives"]
    assert ram_map.find({"game_id": "aaaa000011112222"}).id == "aaaa000011112222"


def test_signatures_tag_enum_values_with_their_evidence():
    m = ram_map.RamMap(spec({"enemy.act": {"address": "0x80001000", "type": "u8", "enum": {"0x26": "swing"},
                                           "signatures": {"0x26": {"attack": "melee", "lead_s": 0.5,
                                                                   "source": "ghidra", "confidence": "static"}}}}))
    f = m.fields["enemy.act"]
    assert f.signatures[0x26]["attack"] == "melee" and f.describe()["signatures"]["0x26"]["lead_s"] == 0.5
    with pytest.raises(ram_map.MapError, match="confidence"):
        ram_map.RamMap(spec({"a.b": {"address": 1, "type": "u8", "signatures": {"1": {"confidence": "sure"}}}}))
    g = ram_map.load("G4BE08")                                      # the RE4 map: its Mercenaries block and attacks
    assert g.spec["mercs"]["vocab"]["projectiles"] == "thrown"
    assert g.fields["enemies"].fields["act"].signatures[0x26]["attack"] == "melee"


def test_check_cli(tmp_path, capsys):
    assert ram_map.main(["check", str(ram_map.GAMEDATA / "G4BE08-ram.json")]) == 0
    bad = tmp_path / "X-ram.json"
    bad.write_text(json.dumps(spec({"a.b": {"address": 1, "type": "u8"}}, id="X")))
    assert ram_map.main(["check", str(bad)]) == 1
    assert "no source" in capsys.readouterr().out
