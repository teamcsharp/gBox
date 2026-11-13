"""Execute the isolated ARM64 shell probe, including clobbered native call registers."""
import struct

import pytest

from gbox.mercs.native.re6_061d2a06 import shell_probe as S


class Machine:
    def __init__(self, base, kind="shell1304"):
        U = pytest.importorskip("unicorn")
        from unicorn import arm64_const as A
        self.U, self.A, self.base = U, A, base
        self.u = U.Uc(U.UC_ARCH_ARM64, U.UC_MODE_ARM)
        self.u.mem_map(base, 0x3000000)
        self.unit, self.player = base + 0x3100000, base + 0x3200000
        self.packet, self.table = base + 0x3300000, base + 0x3400000
        self.action, self.stack = base + 0x3500000, base + 0x3600000
        self.stop = base + 0x1000
        for at in (self.unit, self.player, self.packet, self.table, self.action, self.stack):
            self.u.mem_map(at, 0x10000)
        self.shell = S.SHELLS[kind]
        self.born, self.player_born = 0xAABBCCDD, 0x11223344
        self.put(self.unit, "Q", base + self.shell.vtable)
        self.put(self.unit + 0x1300, "Q", self.player)
        self.put(self.unit + 0x1308, "I", self.born)
        self.put(self.unit + 0x14, "I", 0xA55AA55A)
        self.put(self.unit + 0xC, "I", 0x201)
        self.put(self.unit + 0x3954, "I", 0x10)
        self.put(self.player + 0x1308, "I", self.player_born)
        self.put(self.player + 0x1368, "h", 500)
        self.put(base + 0x28EA8E0, "Q", base + 0x4000)
        self.put(self.packet, "4f", 1250.0, 150.0, -760.0, 0.0)
        self.put(self.unit + 0x13A8, "Q", base + S.MANAGER_VT)
        self.put(self.unit + 0x13B0, "Q", self.unit)
        self.put(self.unit + 0x13C0, "I", 27)
        self.put(self.unit + 0x13D0, "Q", self.table)
        self.put(self.table + 19 * 8, "Q", self.action)
        self.put(self.action, "Q", base + S.SHELL_EXPLODE_VT)
        self.put(self.action + 0x10, "Q", self.unit)
        self.calls = []
        self.allocated = self.unit
        self.u.hook_add(U.UC_HOOK_CODE, self.native_call)

    def put(self, at, fmt, *values):
        self.u.mem_write(at, struct.pack("<" + fmt, *values))

    def get(self, at, fmt):
        return struct.unpack("<" + fmt, self.u.mem_read(at, struct.calcsize("<" + fmt)))[0]

    def reg(self, n):
        return getattr(self.A, "UC_ARM64_REG_X" + str(n))

    def native_call(self, u, at, _size, _data):
        if at not in (self.base + 0x3BCF90, self.base + 0xF3D5F0):
            return
        args = [u.reg_read(self.reg(n)) for n in range(5)]
        self.calls.append((at - self.base, args))
        for n in range(19):
            u.reg_write(self.reg(n), 0xDEAD0000 + n)
        if at == self.base + 0x3BCF90:
            u.reg_write(self.reg(0), self.allocated)
        u.reg_write(self.A.UC_ARM64_REG_PC, u.reg_read(self.A.UC_ARM64_REG_LR))

    def run(self, image, args):
        self.u.mem_write(self.base + image[0], S.image_bytes(image))
        for n, arg in enumerate(args):
            self.u.reg_write(self.reg(n), arg)
        for n in range(19, 30):
            self.u.reg_write(self.reg(n), 0xCA110000 + n)
        self.u.reg_write(self.A.UC_ARM64_REG_SP, self.stack + 0x8000)
        self.u.reg_write(self.A.UC_ARM64_REG_LR, self.stop)
        self.u.emu_start(self.base + image[0], self.stop, count=500)
        assert self.u.reg_read(self.A.UC_ARM64_REG_PC) == self.stop
        assert self.u.reg_read(self.A.UC_ARM64_REG_SP) == self.stack + 0x8000
        for n in range(19, 30):
            assert self.u.reg_read(self.reg(n)) == 0xCA110000 + n
        return self.u.reg_read(self.reg(0))

    def spawn(self, dti=None, generation=None):
        return self.run(S.SPAWN, (self.player, self.player_born if generation is None else generation,
                                  self.base + self.shell.dti if dti is None else dti, self.packet))

    def arm(self, vt=None):
        return self.run(S.ARM, (self.unit, self.player, self.born, self.player_born,
                                self.base + self.shell.vtable if vt is None else vt))


@pytest.mark.parametrize("base", [0x10000000, 0x3CA7C04000])
@pytest.mark.parametrize("kind", list(S.SHELLS))
def test_spawn_uses_shell_factory_mode_and_preserves_abi(base, kind):
    m = Machine(base, kind)
    player_before = bytes(m.u.mem_read(m.player, 0x6000))
    assert m.spawn() == m.unit
    assert m.calls[0] == (0x3BCF90, [base + 0x4000, base + m.shell.dti, 14, 0, 0])
    assert m.calls[1][0] == 0xF3D5F0
    assert m.calls[1][1][:3] == [m.unit, 0, 0xFFFFFFFF]
    assert m.get(m.packet + 16, "Q") == m.unit
    assert m.get(m.packet + 24, "I") == 2
    assert m.get(m.unit + 0x14, "I") == 0xA55AA55A & 0xFFFFD7FF
    assert m.get(m.unit + 0x1300, "Q") == m.player
    for offset in (0x60, 0x3890, 0x38D0):
        assert bytes(m.u.mem_read(m.unit + offset, 16)) == struct.pack("<4f", 1250., 150., -760., 0.)
    for offset in (0x3870, 0x3880):
        assert bytes(m.u.mem_read(m.unit + offset, 12)) == bytes(12)
    assert m.get(m.unit + 0x38A0, "B") == 1
    assert bytes(m.u.mem_read(m.player, 0x6000)) == player_before
    # Merely spawning neither forces collision nor requests a bomb action.
    assert m.get(m.unit + 0x3954, "I") == 0x10
    assert m.get(m.unit + 0x13D8, "I") == 0


@pytest.mark.parametrize("failure", ["wrong_dti", "stale_player", "dead_player", "negative_hp",
                                    "null_allocation", "wrong_class"])
def test_spawn_refuses_invalid_identity_without_unowned_writes(failure):
    m = Machine(0x10000000)
    kwargs = {}
    if failure == "wrong_dti": kwargs["dti"] = m.base + 0x2951500
    if failure == "stale_player": kwargs["generation"] = m.player_born + 1
    if failure == "dead_player": m.put(m.player + 0x1368, "h", 0)
    if failure == "negative_hp": m.put(m.player + 0x1368, "h", -1)
    if failure == "null_allocation": m.allocated = 0
    if failure == "wrong_class": m.put(m.unit, "Q", m.base + 0x284AEB8)
    unit_before = bytes(m.u.mem_read(m.unit, 0x4000))
    assert m.spawn(**kwargs) == 0
    assert bytes(m.u.mem_read(m.unit, 0x4000)) == unit_before
    assert len(m.calls) == int(failure in ("null_allocation", "wrong_class"))
    assert m.get(m.packet + 24, "I") == int(failure == "wrong_class")
    assert m.get(m.packet + 16, "Q") == (m.unit if failure == "wrong_class" else 0)


@pytest.mark.parametrize("base", [0x10000000, 0x3CA7C04000])
@pytest.mark.parametrize("kind", list(S.SHELLS))
def test_arm_only_sets_native_collision_request_bit(base, kind):
    m = Machine(base, kind)
    before = bytearray(m.u.mem_read(m.unit, 0x4000))
    assert m.arm() == 1
    struct.pack_into("<I", before, 0x3954, 0x14)
    assert bytes(m.u.mem_read(m.unit, 0x4000)) == before
    assert m.calls == []
    assert m.get(m.action + 0x28, "B") == 0  # Native effect processing has not happened.


@pytest.mark.parametrize("failure", ["wrong_vt_arg", "wrong_unit_vt", "wrong_owner", "stale_unit",
                                    "stale_player", "dead_player", "wrong_manager", "wrong_manager_owner",
                                    "short_table", "null_table", "null_action", "throw_action",
                                    "wrong_action_owner", "wrong_phase", "already_impacted"])
def test_arm_guards_leave_memory_untouched(failure):
    m = Machine(0x10000000)
    changes = {
        "wrong_unit_vt": (m.unit, "Q", m.base + 0x284AEB8),
        "wrong_owner": (m.unit + 0x1300, "Q", m.player + 16),
        "stale_unit": (m.unit + 0x1308, "I", m.born + 1),
        "stale_player": (m.player + 0x1308, "I", m.player_born + 1),
        "dead_player": (m.player + 0x1368, "h", 0),
        "wrong_manager": (m.unit + 0x13A8, "Q", 0),
        "wrong_manager_owner": (m.unit + 0x13B0, "Q", m.player),
        "short_table": (m.unit + 0x13C0, "I", 19),
        "null_table": (m.unit + 0x13D0, "Q", 0),
        "null_action": (m.table + 19 * 8, "Q", 0),
        "throw_action": (m.action, "Q", m.base + 0x288C6C8),
        "wrong_action_owner": (m.action + 0x10, "Q", m.player),
        "wrong_phase": (m.unit + 0xC, "I", 0x10201),
        "already_impacted": (m.unit + 0x2C18, "I", 1),
    }
    if failure in changes: m.put(*changes[failure])
    before = bytes(m.u.mem_read(m.unit, 0x4000))
    assert m.arm(vt=0 if failure == "wrong_vt_arg" else None) == 0
    assert bytes(m.u.mem_read(m.unit, 0x4000)) == before
    assert m.calls == []


def test_probe_ranges_remain_after_shipped_images_and_inside_text_padding():
    from gbox.mercs.native.re6_061d2a06 import classes as C
    assert C.DETONATE_CLASS[0] + C.DETONATE_CLASS[2] <= S.SPAWN[0]
    assert S.SPAWN[0] + len(S.image_bytes(S.SPAWN)) <= S.ARM[0]
    assert S.ARM[0] + len(S.image_bytes(S.ARM)) == 0x18F3000
