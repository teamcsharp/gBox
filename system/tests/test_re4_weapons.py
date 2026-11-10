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


BASE = 0x3CA7C04000


class CodeAd:
    """The loadout function's patchable words at their build values (what main.bin holds), nothing else."""
    def __init__(self, fail_at=None):
        self.mem = {BASE + off: struct.pack("<I", orig) for slots in W.LOADOUT_SLOTS.values() for s in slots
                    for off, _, orig in s["code"]}
        self.fail_at = fail_at

    def read_memory(self, a, n):
        return self.mem[a]

    def write_memory(self, a, data):
        if a == self.fail_at:
            raise ValueError("not writable")
        self.mem[a] = bytes(data)

    def word(self, off):
        return struct.unpack("<I", self.mem[BASE + off])[0]


def test_the_encodings_match_the_builds_own_instructions():
    """The table's words are the build's; the encoders reproduce the ones they stand for (read from main.bin and
    decoded with capstone, 2026-11-10): mov w0, #0x27 / cmp w10, #0x27 / mov w8, #0x2114 / and w8, w22, #0x7ffff."""
    assert W.movz_w(0, 0x27) == 0x528004E0 and W.cmp_w(10, 0x27) == 0x71009D5F
    assert W.movz_w(8, 0x2114) == 0x52842288 and W.and_full_mask(8, 22) == 0x12004AC8
    assert W.mov_full_mask(8) == 0x32004BE8                              # orr w8, wzr, #0x7ffff
    assert W.cmp_w(10, 0x3E) == 0x7100F95F                               # HUNK's search for his Custom TMP


def test_a_patched_slot_changes_every_use_of_its_weapon():
    """The give, both inventory searches (the level block's and the equip's), the levels, the first magazine and the
    mask: a give whose searches still name the old id is a null item at the round's start."""
    import random
    ad = CodeAd()
    done = Mods._patch_loadout(ad, BASE, Mods._draw_loadouts(random.Random(1), fixed=0x37))
    assert set(done) == set(W.LOADOUT_SLOTS) and all(ids[0] == 0x37 for ids in done.values())
    lv = W.max_levels(0x37)
    assert W.movz_imm(ad.word(0x2951D4)) == (0, 0x37)                    # Leon's give
    assert ad.word(0x295254) == W.cmp_w(10, 0x37) == ad.word(0x295354)   # the level search and the equip search
    assert W.movz_imm(ad.word(0x295278)) == (8, lv["packed"])
    assert W.movz_imm(ad.word(0x295280)) == (1, lv["capacity"] + 1)      # the first magazine at his capacity level
    assert ad.word(0x295294) == W.mov_full_mask(8)                       # the levels are not ANDed with 0x2114
    assert W.movz_imm(ad.word(0x29581C)) == (0, 0x37)                    # HUNK's ORR give became a MOVZ
    assert ad.word(0x2955BC) == W.and_full_mask(8, 21)                   # Ada's AND form
    # back to the game's own: every word is the build's again
    Mods._patch_loadout(ad, BASE, {ch: [None] * len(s) for ch, s in W.LOADOUT_SLOTS.items()})
    assert ad.mem == CodeAd().mem


def test_a_slot_with_foreign_code_is_never_touched():
    ad = CodeAd()
    ad.mem[BASE + 0x295354] = struct.pack("<I", 0xD65F03C0)             # ret: not this build's search
    done = Mods._patch_loadout(ad, BASE, {0: [0x37, 0x29]})
    assert done == {0: [0x29]}                                           # the Riot Gun slot is still fine
    assert ad.word(0x2951D4) == 0x528004E0 and ad.word(0x295254) == 0x71009D5F   # Blacktail slot untouched


def test_a_write_failing_part_way_puts_the_slot_back():
    ad = CodeAd(fail_at=BASE + 0x295354)                                 # the equip search cannot be written
    done = Mods._patch_loadout(ad, BASE, {0: [0x37, None]})
    assert 0x37 not in done.get(0, [])
    assert ad.word(0x2951D4) == 0x528004E0 and ad.word(0x295254) == 0x71009D5F, "no give without its searches"


def test_only_slots_with_a_level_block_and_no_attachment_are_patched():
    """Ada's and Wesker's semi-auto rifles (the scope / the rifle code) and Krauser's bow (no level block) stay stock."""
    ids = {ch: [s["id"] for s in slots] for ch, slots in W.LOADOUT_SLOTS.items()}
    assert ids == {0: [0x27, 0x94], 2: [0x21, 0x30], 3: [0x3E], 5: [0x23, 0x2A]}
    for slots in W.LOADOUT_SLOTS.values():
        assert sum(bool(s.get("equipped")) for s in slots) == 1 and slots[0].get("equipped")
        for s in slots:
            roles = [r for _, r, _ in s["code"]]
            assert roles.count("give") == 1 and roles.count("find") >= 1 and roles.count("levels") == 1
