"""RE6 Switch unlock-on-load (gbox.re6_switch_unlock) on a fake 64-bit little-endian guest laid out like the live
measurements of 2026-10-26 (Citron NEO on the Spark, main build 061D2A06...): main found by its read-only signature,
the build refused unless the title gate's code matches, sInfoMan -> cSystemInfo mUnlockFlag (two copies), sUnit's
interface units by vtable (uIdTitle00 with its +0x20A "main menu" byte, uIdStartUp00 the main menu)."""
import struct
from types import SimpleNamespace

import pytest

from gbox import re6_switch_unlock as U

BASE = 0x3CA7C04000                       # the live runs' main base
HEAP = 0x5D00000000


class Guest:
    """Two rows like the HostMemory ones (main's image read-only, a heap): rd / wr inside them only."""
    MAIN_SIZE, HEAP_SIZE = 0x2B00000, 0x200000

    def __init__(self, flag=0x10, gate=U.TITLE_GATE_CODE, signature=True):
        self.regions = {BASE: bytearray(self.MAIN_SIZE), HEAP: bytearray(self.HEAP_SIZE)}
        self.next_heap = HEAP + 0x1000
        self.writes = []
        self.ignore_writes = False
        if signature:
            self.put(BASE + U.SIG_OFF, U.SIGNATURE)
        self.put(BASE + U.TITLE_GATE_OFF, gate)
        self.infoman = self.alloc(U.INFO_ARRAY + 4 * U.INFO_STRIDE)
        self.q(BASE + U.S_INFOMAN, self.infoman)
        self.i32(self.infoman + U.INFO_INDEX, 1)                       # the second cSystemInfo is the current one
        self.info = self.infoman + U.INFO_ARRAY + U.INFO_STRIDE
        for off in U.FLAG_ADDRS:
            self.u32(self.info + off, flag)
        self.unit = self.alloc(U.UNIT_LINES + U.LINE_STRIDE * U.N_LINES)
        self.q(BASE + U.S_UNIT, self.unit)
        self.title = None

    # memory
    def _region(self, a, n):
        for s, buf in self.regions.items():
            if s <= a and a + n <= s + len(buf):
                return s, buf
        raise ValueError(f"unmapped {a:#x}")

    def put(self, a, data: bytes):
        s, buf = self._region(a, len(data))
        buf[a - s:a - s + len(data)] = data

    def rd(self, a, n):
        s, buf = self._region(a, n)
        return bytes(buf[a - s:a - s + n])

    def wr(self, a, data):
        self.writes.append((a, bytes(data)))
        if not self.ignore_writes:
            self.put(a, data)

    def rows(self):
        return [(s, s + len(buf), "r--s" if s == BASE else "rw-s") for s, buf in self.regions.items()]

    def q(self, a, v):
        self.put(a, struct.pack("<Q", v))

    def i32(self, a, v):
        self.put(a, struct.pack("<i", v))

    def u32(self, a, v):
        self.put(a, struct.pack("<I", v))

    def alloc(self, n):
        a = self.next_heap
        self.next_heap += (n + 0xFFF) & ~0xFFF
        return a

    # the game
    def show(self, line, *names):
        """Interface units on a move line, linked through +0x20, each a vtable at main + its offset."""
        by_name = {v: k for k, v in U.UNIT_VTABLES.items()}
        head = 0
        for name in reversed(names):
            u = self.alloc(0x400)
            self.q(u, BASE + by_name[name])
            self.q(u + U.UNIT_NEXT, head)
            head = u
            if name == "uIdTitle00":
                self.title = u
        self.q(self.unit + U.UNIT_LINES + U.LINE_STRIDE * line, head)

    def frame(self):
        """uIdTitle00's update: its +0x20A byte follows mUnlockFlag bit 0 every frame (main+0xAD5D6C)."""
        if self.title:
            flag = struct.unpack("<I", self.rd(self.info + U.UNLOCK_FLAG, 4))[0]
            self.put(self.title + U.TITLE_MENU_OPEN, bytes([flag & 1]))

    def flags(self):
        return [struct.unpack("<I", self.rd(self.info + off, 4))[0] for off in U.FLAG_ADDRS]


def test_module_base_is_found_by_the_signature_and_cached():
    g = Guest()
    assert U.module_base(g) == BASE and g.module_base == BASE
    assert U.module_base(g) == BASE                                    # the cached base is checked, not searched
    assert U.module_base(Guest(signature=False)) is None


def test_status_names_booting_waiting_title_and_menu():
    assert U.status(Guest(signature=False))["state"] == "booting"
    g = Guest()
    st = U.status(g)
    assert st["state"] == "waiting" and st["unlock_flags"] == [0x10, 0x10] and st["system_info"] == g.info
    g.show(0, "uIdAlert00", "uIdTitle00")
    g.frame()
    st = U.status(g)
    assert st["state"] == "title" and st["title"] == g.title and st["title_menu_open"] == 0
    assert st["ui"] == ["uIdAlert00", "uIdTitle00"]
    g.show(18, "uIdStartUp00")
    assert U.status(g)["state"] == "menu"


def test_another_build_is_refused_and_never_written():
    g = Guest(gate=bytes(len(U.TITLE_GATE_CODE)))
    g.show(0, "uIdTitle00")
    st = U.apply(g)
    assert st["state"] == "refused" and st["writes"] == [] and g.writes == []
    rec = U.watch(g, timeout_s=5, sleep=lambda s: None)
    assert rec["state"] == "refused" and g.writes == [] and g.flags() == [0x10, 0x10]


def test_apply_sets_bit_0_in_both_copies_with_the_original_kept_and_read_back():
    g = Guest(flag=0x10)
    assert U.apply(g)["writes"] == []                                  # no title yet: nothing written
    g.show(0, "uIdTitle00")
    st = U.apply(g)
    assert [(w["before"], w["after"]) for w in st["writes"]] == [(0x10, 0x11), (0x10, 0x11)]
    assert [w["address"] for w in st["writes"]] == [g.info + off for off in U.FLAG_ADDRS]
    assert g.flags() == [0x11, 0x11] and st["unlock_flags"] == [0x11, 0x11]
    assert U.apply(g)["writes"] == []                                  # set: never written again


def test_a_write_that_does_not_read_back_is_an_error():
    g = Guest()
    g.show(0, "uIdTitle00")
    g.ignore_writes = True
    with pytest.raises(RuntimeError, match="read back"):
        U.apply(g)


def test_watch_waits_for_the_title_then_confirms_the_main_menu_is_what_it_opens():
    g = Guest(flag=0x10)
    t = [0.0]
    polls = []

    def sleep(s):
        t[0] += s
        polls.append(t[0])
        if len(polls) == 3:                                            # the title comes up after the save dialogs
            g.show(0, "uIdAlert00", "uIdTitle00")
        g.frame()

    rec = U.watch(g, timeout_s=60, poll_s=0.25, clock=lambda: t[0], sleep=sleep)
    assert rec["state"] == "applied" and rec["profile"] == U.PROFILE
    assert rec["states"] == ["waiting", "title"] and len(rec["writes"]) == 2
    assert g.flags() == [0x11, 0x11] and g.rd(g.title + U.TITLE_MENU_OPEN, 1) == b"\x01"
    assert "0x20A" in rec["verified"]


def test_watch_on_a_save_that_has_it_writes_nothing():
    g = Guest(flag=0x11)
    g.show(0, "uIdTitle00")
    g.frame()
    rec = U.watch(g, timeout_s=5, sleep=lambda s: None)
    assert rec["state"] == "already_unlocked" and rec["writes"] == [] and g.writes == []


def test_watch_sets_it_again_when_a_save_load_clears_it():
    g = Guest(flag=0x10)
    g.show(0, "uIdTitle00")
    n = [0]

    def sleep(s):
        n[0] += 1
        if n[0] == 1:                                                  # the save loads over the first write
            for off in U.FLAG_ADDRS:
                g.u32(g.info + off, 0x10)
        g.frame()

    rec = U.watch(g, timeout_s=60, clock=lambda: n[0], sleep=sleep)
    assert rec["state"] == "applied" and len(rec["writes"]) == 4 and g.flags() == [0x11, 0x11]


def test_watch_stops_when_the_session_ends_or_times_out():
    g = Guest()
    assert U.watch(g, alive=lambda: False, sleep=lambda s: None)["state"] == "session_ended"
    t = [0.0]

    def sleep(s):
        t[0] += s
    rec = U.watch(g, timeout_s=2, poll_s=0.5, clock=lambda: t[0], sleep=sleep)
    assert rec["state"] == "timeout" and g.writes == []


def test_watch_reaching_the_menu_reports_the_flag():
    g = Guest(flag=0x11)
    g.show(18, "uIdStartUp00")
    rec = U.watch(g, timeout_s=5, sleep=lambda s: None)
    assert rec["state"] == "already_unlocked" and rec["verified"] == "main menu up"
    g = Guest(flag=0x11)
    g.show(18, "uIdStartUp31")                                         # STAGE select: past the title already
    assert U.watch(g, timeout_s=5, sleep=lambda s: None)["state"] == "already_unlocked"


def test_watch_keeps_retrying_a_write_that_does_not_stick_then_times_out():
    g = Guest(flag=0x10)
    g.show(0, "uIdTitle00")
    g.ignore_writes = True
    t = [0.0]

    def sleep(s):
        t[0] += s
    rec = U.watch(g, timeout_s=1, poll_s=0.25, clock=lambda: t[0], sleep=sleep)
    assert rec["state"] == "timeout" and rec["states"] == ["write_unconfirmed"] and rec["writes"] == []
    assert len(g.writes) == 4 and g.flags() == [0x10, 0x10]           # one attempt per poll, nothing recorded


def test_adapter_memory_reads_writes_and_rows_through_an_eden_adapter():
    store = {}
    arena = {"base": 0x1000000000, "mapped": [(0x1000000000, 0x1000010000, "r--s"), (0x1000010000, 0x1000020000, "rw-s")]}
    ad = SimpleNamespace(read_memory=lambda a, n: bytes(store.get(a + i, 0) for i in range(n)),
                         write_memory=lambda a, d: store.update({a + i: b for i, b in enumerate(d)}) or {"verified": True},
                         _guest=lambda: (7, arena), address_mode="direct")
    m = U.AdapterMemory(ad)
    m.wr(0x1000010000, b"\x11")
    assert m.rd(0x1000010000, 2) == b"\x11\x00"
    assert m.rows() == arena["mapped"]
    ad.address_mode = "offset"                                         # Dynarmic: guest = host - arena base
    assert m.rows()[0] == (0, 0x10000, "r--s")


def test_start_watch_runs_on_a_daemon_thread_and_reports(monkeypatch):
    seen = []
    monkeypatch.setattr(U, "watch", lambda m, timeout_s, alive: {"state": "applied", "alive": alive()})
    ad = SimpleNamespace(proc=SimpleNamespace(poll=lambda: None))
    t = U.start_watch(ad, on_done=seen.append)
    t.join(5)
    assert t.daemon and seen == [{"state": "applied", "alive": True}]
    monkeypatch.setattr(U, "watch", lambda m, timeout_s, alive: 1 / 0)
    U.start_watch(ad, on_done=seen.append).join(5)
    assert seen[-1]["state"] == "failed" and "division" in seen[-1]["reason"]


def savedata(flag=0x10) -> bytes:
    data = bytearray(U.SAVE_SIZE)
    data[0x38:0x40] = b"\x01\x00\x00\x00\x05\x00\x00\x00"
    struct.pack_into("<I", data, U.SAVE_UNLOCK_FLAG, flag)
    struct.pack_into("<I", data, U.SAVE_CHECKSUM, U.save_checksum(bytes(data)))
    return bytes(data)


def test_save_flag_round_trip_keeps_the_checksum_valid():
    fresh = savedata(0x10)
    assert U.save_unlock_flag(fresh) == 0x10
    on = U.set_save_flag(fresh, True)
    assert U.save_unlock_flag(on) == 0x11 and len(on) == U.SAVE_SIZE
    assert on[U.SAVE_CHECKSUM:U.SAVE_CHECKSUM + 4] != fresh[U.SAVE_CHECKSUM:U.SAVE_CHECKSUM + 4]
    off = U.set_save_flag(on, False)                                   # rollback
    assert off == fresh


@pytest.mark.parametrize("bad", [b"\0" * 16, savedata()[:-4], bytes([1]) + savedata()[1:-1] + bytes([1])],
                         ids=["short", "truncated", "edited"])
def test_anything_but_a_valid_savedata_is_refused(bad):
    corrupt = bytearray(savedata())
    corrupt[0x100] ^= 0xFF
    for data in (bad, bytes(corrupt)):
        with pytest.raises(ValueError):
            U.set_save_flag(data, True)


def test_profile_records_the_evidence_chain():
    p = U.profile()
    ev = p["evidence"]
    assert p["profile"] == U.PROFILE and p["apply"] == "post_launch_ram"
    assert ev["title_id"] == "01002A000CD48000" and ev["update"] == {"title_id": "01002A000CD48800", "version": 131072}
    assert ev["main_build_id"] == "061D2A06CD700785E987C42CE2D72231" and len(ev["main_nso_sha256"]) == 64
    assert "main+0xad5d40" in ev["routines"]["title_gate"] and "live_acceptance" in ev
    assert any("NO MERCY" in s for s in p["scope"])


def test_apply_uses_adapter_facade_when_wr_absent():
    """Regression: gbox.re6_switch_unlock._write_u32 must fall back to adapter.write_memory()
    when the memory object does not expose a .wr() method (the real SwitchLinuxAdapter facade
    exposes read_memory / write_memory but no .wr attribute — the previous code path raised
    AttributeError in the write-back check)."""
    g = Guest(flag=0x10)
    g.show(0, "uIdTitle00")

    # Simulate an adapter-like facade: only read_memory / write_memory, no .wr method
    class FacadeAdapter:
        def __init__(self, guest):
            self._g = guest
            self.writes = []
            self.module_base = None

        def rd(self, a, n):
            return self._g.rd(a, n)

        def write_memory(self, a, data):
            self.writes.append((a, bytes(data)))
            self._g.put(a, data)

        def rows(self):
            return self._g.rows()

    facade = FacadeAdapter(g)
    st = U.apply(facade)

    # The write must land on the guest via the facade's write_memory, not fail
    assert g.flags() == [0x11, 0x11], "bit 0 not set in both cSystemInfo copies"
    assert st["writes"], "no write record returned"
    # Both copies should have been written
    assert len(facade.writes) == 2, f"expected 2 adapter writes, got {len(facade.writes)}"
    # Addresses match the FLAG_ADDRS offsets from system_info
    info = st["system_info"]
    assert [w["address"] for w in st["writes"]] == [info + off for off in U.FLAG_ADDRS]
