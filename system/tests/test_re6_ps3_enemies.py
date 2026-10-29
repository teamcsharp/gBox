"""RE6 PS3 enemy-list reader (gbox.mercs.titles.re6_ps3_enemies) - fixture-backed regression tests.

The fixtures are RAM images built exactly from the static evidence pinned out of the decrypted EBOOT
(sha256 3720224a...; registration 0x15cdb8: node 0x183434C, name 0x1412510, list 0x17F36E0, size 0x810):
the reader must walk the whole chain, name kinds through the instance DTI, expose head/torso aim points
for the living, and refuse to answer anything when the chain is not exactly this EBOOT's.
"""
import struct

from gbox.mercs.titles import re6_ps3_enemies as E


class Ram:                                   # byte-addressed guest RAM fixture
    def __init__(self):
        self.b = bytearray(0x4000000)

    def w32(self, a, v):
        self.b[a:a + 4] = struct.pack(">I", v & 0xFFFFFFFF)

    def w16(self, a, v):
        self.b[a:a + 2] = struct.pack(">h", v)

    def wf(self, a, v):
        self.b[a:a + 4] = struct.pack(">f", v)

    def wr(self, a, data):
        self.b[a:a + len(data)] = data

    def rd(self, a, n):
        if a < 0 or a + n > len(self.b):
            raise OSError("unmapped")
        return bytes(self.b[a:a + n])


def fixture(names_at=None, count=2, hp=(600, 0), downed_bytes=False, alt_layout=False):
    """A RAM image with a valid sEnemy chain. names_at maps enemy ptr -> DTI name VA (live kind naming)."""
    r = Ram()
    r.wr(E.ENEMY_NAME_VA, b"sEnemy\x00")
    r.w32(E.ENEMY_DTI_NODE, E.ENEMY_NODE_CLASS)
    r.w32(E.ENEMY_DTI_NODE + E.NODE_NAME, E.ENEMY_NAME_VA)
    inst = 0x3000000
    r.w32(E.ENEMY_DTI_NODE + E.NODE_INSTANCE_CANDIDATE, inst)
    arr = 0x3100000
    r.w32(inst + E.MGR_COUNT, count)
    r.w32(inst + E.MGR_ARRAY, arr)
    e_pos, e_hp = (E.ALT_E_POS, E.ALT_E_HP) if alt_layout else (E.E_POS, E.E_HP)
    ptrs = []
    for i in range(count):
        e = 0x3200000 + i * 0x4000
        r.wf(e + e_pos, 100.0 + 50 * i)
        r.wf(e + e_pos + 4, 10.0)
        r.wf(e + e_pos + 8, -200.0 - 25 * i)
        r.w16(e + e_hp, hp[i % len(hp)])
        r.w16(e + e_hp + 2, 800)
        if names_at and e in names_at:
            vt = e + 0x100
            dti = e + 0x200
            r.w32(e, vt)
            r.w32(vt + 0x20, dti)                     # slot 5: getDTI
            r.w32(dti + E.NODE_NAME, names_at[e])
        ptrs.append(e)
    for i, p in enumerate(ptrs):
        r.w32(arr + 4 * i, p)
    return r


def test_reader_walks_the_pinned_chain_from_the_eboot():
    r = fixture()
    foes = E.enemies(r)
    assert foes is not None and len(foes) == 2
    assert foes[0]["ptr"] == 0x3200000 and foes[0]["pos"] == (100.0, 10.0, -200.0)
    assert foes[0]["hp"] == 600 and foes[0]["hp_max"] == 800 and foes[0]["alive"]
    assert foes[1]["hp"] == 0 and not foes[1]["alive"]


def test_kinds_are_named_through_the_instance_dti_table():
    r = fixture(names_at={0x3200000: 0x143E26C, 0x3200000 + 0x4000: 0x1430DAC})
    foes = E.enemies(r)
    assert foes[0]["kind"] == "uEmZombieBase" and foes[0]["family"] == "zombie"
    assert foes[1]["kind"] == "uEm6000" and foes[1]["family"] is None


def test_targets_carry_head_and_torso_points_and_skip_the_dead():
    r = fixture()
    ts = E.targets(r)
    assert ts is not None and len(ts) == 1                  # the hp==0 enemy is not a target
    x, y, z = ts[0]["pos"]
    assert ts[0]["head"] == (x, y + E.HEAD_H, z)
    assert ts[0]["torso"] == (x, y + E.TORSO_H, z)
    assert ts[0]["downed_known"] is False                   # honest: no downed byte measured yet


def test_x360_sibling_layout_is_the_fallback_not_a_guess():
    r = fixture(alt_layout=True)
    assert E.enemies(r) is not None                         # pos +0x50 / hp +0xF20 still reads


def test_wrong_revision_name_bytes_reject_the_whole_chain():
    r = fixture()
    r.wr(E.ENEMY_NAME_VA, b"sPlaye\x00")                    # a different revision's .rodata
    assert E.enemies(r) is None and E.targets(r) is None and E.enemy_node(r) is None


def test_garbage_instance_or_count_never_fabricates_enemies():
    r = fixture()
    r.w32(E.ENEMY_DTI_NODE + E.NODE_INSTANCE_CANDIDATE, 0)
    assert E.enemies(r) is None
    r = fixture()
    r.w32(0x3000000 + E.MGR_COUNT, 999)                     # over MAX_ENEMIES
    assert E.enemies(r) is None
    r = fixture()
    r.w32(0x3200000 + E.E_POS + 4, struct.unpack(">I", struct.pack(">f", 1e12))[0])  # insane y
    assert E.enemies(r) is None
    r = fixture()
    r.w16(0x3200000 + E.E_HP, 9999)                         # hp > hp_max bound
    assert E.enemies(r) is None


def test_unmapped_boot_ram_is_none_not_crash():
    class Empty:
        def rd(self, a, n):
            raise OSError("unmapped")

    assert E.enemies(Empty()) is None
    assert E.enemy_node(Empty()) is None
