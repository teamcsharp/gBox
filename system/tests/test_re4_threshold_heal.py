"""RE4: the threshold heal - a hurt player is restored, a healthy one is never touched.

The operator, 2026-11-12: "they have unlimited healing items, so they should always have the ability to use a first aid
spray and heal themselves if they need to in the game ... I don't want them bringing up the item screen." The hand swap
cannot do it: re4_switch_mods._hand_hold requires a row in the weapon table and a First Aid Spray has none, and RE4 has
no "hold a spray" state. So the heal is the player's own life field (re4_switch.PLAYER_LIFE) put back at its maximum
when - and only when - he is below heal_below. That is deliberately NOT unlimited life: full health writes nothing.
"""
import struct

from gbox.mercs.titles import re4_switch as D
from gbox.mercs.titles import re4_switch_mods as M

BASE = 0x10000000


class Ad:
    def __init__(self):
        self.at = {}
        self.writes = []

    def put(self, addr, data):
        self.at[addr] = bytearray(data)

    def read_memory(self, addr, n):
        for a, d in self.at.items():
            if a <= addr and addr + n <= a + len(d):
                return bytes(d[addr - a:addr - a + n])
        raise ValueError("unmapped")

    def write_memory(self, addr, data):
        for a, d in self.at.items():
            if a <= addr and addr + len(data) <= a + len(d):
                d[addr - a:addr - a + len(data)] = data
                self.writes.append((addr, bytes(data)))
                return
        raise ValueError("unmapped")


def world(hp, top=1000, heal_below=0.55):
    ad = Ad()
    ad.put(BASE + D.PLAYER_LIFE, struct.pack("<H", hp))
    st = M._state(ad)
    st.clear()
    st["heal_below"] = heal_below
    st["boot"] = M._boot(ad, BASE)
    snap = {"module_base": BASE, "player": {"hp": hp, "hp_max": top}}
    return ad, snap, st


def life(ad):
    return struct.unpack("<H", ad.read_memory(BASE + D.PLAYER_LIFE, 2))[0]


def test_the_setting_survives_the_saved_key_filter():
    """_load_saved keeps SAVED_KEYS only. heal_below was missing from it, so the setting written on the host was
    silently dropped and the heal never ran at all - live, hp 658/2400 with mods_heals absent."""
    assert "heal_below" in M.SAVED_KEYS


def test_a_hurt_player_is_healed_and_it_is_counted():
    ad, snap, st = world(400)
    out = M.maintain(ad, snap)
    assert out.get("heals") == 1 and life(ad) == 1000
    assert st["heals"] == 1


def test_a_healthy_player_is_never_written():
    ad, snap, st = world(900)                      # above heal_below 0.55
    out = M.maintain(ad, snap)
    assert not out.get("heals") and not ad.writes and life(ad) == 900


def test_full_health_is_never_written():
    ad, snap, st = world(1000)
    out = M.maintain(ad, snap)
    assert not out.get("heals") and not ad.writes


def test_the_threshold_is_what_decides():
    ad, snap, st = world(400, heal_below=0.2)      # 40% is above a 20% threshold
    out = M.maintain(ad, snap)
    assert not out.get("heals") and life(ad) == 400


def test_unlimited_health_still_wins_and_plain_healing_steps_aside():
    ad, snap, st = world(400)
    st["unlimited_health"] = True
    out = M.maintain(ad, snap)
    assert out.get("life_kept") == 1 and not out.get("heals")
    assert life(ad) == 1000
