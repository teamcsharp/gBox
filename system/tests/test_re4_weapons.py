"""RE4 Switch weapons in RAM (gbox.mercs.titles.re4_weapons): the decoders on synthetic bytes, and the offsets' agreement
with what was measured live (the player's life, the firepower rows the live mods write)."""
import struct

from gbox.mercs.titles import re4_switch as D
from gbox.mercs.titles import re4_switch_mods as Mods
from gbox.mercs.titles import re4_weapons as W


def test_levels_pack_and_unpack():
    v = W.levels_pack(6, 2, 1, 5)
    assert W.levels_unpack(v) == {"firepower": 6, "firing_speed": 2, "reload": 1, "capacity": 5}


def test_max_levels_take_the_exclusive_column():
    m = W.max_levels(0x29)                                  # Broken Butterfly: (6, 1, 3, 4) counts
    assert m["firepower"] == W.EXCLUSIVE and m["firing_speed"] == 0 and m["reload"] == 2 and m["capacity"] == 3
    assert W.max_levels(0x37)["capacity"] == W.EXCLUSIVE    # the Handcannon's infinite exclusive capacity
    assert W.max_levels(0x9999) is None


def test_an_item_record_decodes():
    raw = struct.pack("<HHBBHHBBBB", 0x29, 1, 1, 0, W.levels_pack(6, 0, 2, 3), (6 << 3) | 0, 2, 3, 0, 1)
    it = W.decode_item(raw, 0x1000)
    assert it["id"] == 0x29 and it["name"] == "Broken Butterfly" and it["in_use"] and it["loaded"] == 6
    assert it["levels"]["firepower"] == 6 and not it["empty"]


def test_the_weapon_table_row_decodes():
    raw = struct.pack("<HBBBBH7H", 0x2D, 0, 0x08, 0, 0, 0x18, 7, 9, 12, 14, 17, 20, 100)
    w = W.decode_weapon_table(raw)
    assert w[0x2D]["class"] == 0x08 and w[0x2D]["capacity"][6] == 100


def test_rapid_fire_keeps_the_gate_visible():
    assert W.rapid_fire_value(14.0, 20) == W.RAPID_FIRE_FLOOR    # 0.7 frames would never cross the gate
    assert W.rapid_fire_value(30.0, 2) == 15.0
    assert W.gate_frame(W.RAPID_FIRE_FLOOR) == 1


def test_the_offsets_agree_with_the_live_measurements():
    """Static and live agree: the game object's life field is the one the live probe found, and the firepower table's
    class rows are the rows the live mods write (Handgun class 2, Handcannon 15, Riot Gun 33)."""
    assert W.GAME_OBJ + W.G_HP == D.PLAYER_LIFE
    for name, cls in (("handgun", 0x02), ("handcannon", 0x0F), ("riot_gun", 0x21), ("broken_butterfly", 0x05)):
        assert Mods.FIREPOWER_ROWS[name][0] == W.FIREPOWER_TBL + cls * 4 * W.FIREPOWER_COLS



def test_movz_encodes_and_decodes():
    word = W.movz_w(0, 0x27)
    assert word == 0x528004E0 and W.movz_imm(word) == (0, 0x27)
    assert W.movz_imm(0xD65F03C0) is None                    # ret is no movz


def test_the_loadout_sites_are_rewritten_only_on_this_builds_instructions():
    import random
    base = 0x3CA7C04000

    class Ad:
        def __init__(self):
            self.mem = {}
            for sites in W.LOADOUT_SITES.values():
                for site in sites["weapons"] + tuple(s for s in sites["levels"] if s):
                    off, rd, imm = site
                    self.mem[base + off] = struct.pack("<I", W.movz_w(rd, imm))

        def read_memory(self, a, n):
            return self.mem[a]

        def write_memory(self, a, data):
            self.mem[a] = bytes(data)

    ad = Ad()
    done = Mods._patch_loadout(ad, base, Mods._draw_loadouts(random.Random(1), fixed=0x29))
    assert set(done) == set(W.LOADOUT_SITES) and all(ids[0] == 0x29 for ids in done.values())
    leon_w = W.movz_imm(struct.unpack("<I", ad.mem[base + 0x2951D4])[0])
    leon_l = W.movz_imm(struct.unpack("<I", ad.mem[base + 0x295278])[0])
    assert leon_w == (0, 0x29) and leon_l == (8, W.max_levels(0x29)["packed"])
    ad.mem[base + 0x2951D4] = struct.pack("<I", 0xD65F03C0)     # not a movz: another build
    done = Mods._patch_loadout(ad, base, {0: [0x37, None]})
    assert ad.mem[base + 0x2951D4] == struct.pack("<I", 0xD65F03C0) and 0x37 not in done.get(0, [])
