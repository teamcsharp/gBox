"""Resident Evil 6 on Nintendo Switch (title 01002A000CD48000, update v131072 = "1.0.2", main build
061D2A06CD700785E987C42CE2D72231): unlock-on-load for The Mercenaries and The Mercenaries No Mercy.

What gates them (found 2026-10-26 on the Spark: Citron NEO nightly 56dad8119, NCE, private home; main NSO dumped with
Citron's dump_nso, read with capstone; live RAM through /proc/<pid>/mem, docs/research/re6-switch-ram.md):

* A fresh save never reaches the main menu. After PRESS ANY BUTTON the title runs the brightness screen and starts the
  Prologue, and quitting the Prologue brings the title back to the Prologue again. The main menu (PLAY GAME > EXTRA
  CONTENT > THE MERCENARIES / THE MERCENARIES NO MERCY) opens only once the Prologue is cleared.
* The flag is bit 0 of cSystemInfo's mTempData.mHistory.mUnlockFlag (u32; the name is main's own MtProperty string,
  registered at cSystemInfo+0xB8 by cSystemInfo's createProperty, main+0x112A620). A fresh save holds 0x10.
  sInfoMan (instance pointer main+0x28E9BE0) keeps four cSystemInfo (0xAA28 bytes each) at +0x48, indexed by its
  +0x2C; each cSystemInfo is a vtable and two copies of its 0x5510-byte data (+0x8 and +0x5518), which the game copies
  into each other, so the flag lives at cSystemInfo+0xB8 and +0x55C8.
* uIdTitle00's update (main+0xAD5D40, check at main+0xAD5D6C) sets its +0x20A "main menu" byte every frame from that
  bit; cDemoTitle (main+0xFC2B90) branches on it too. The game sets the bit itself when the Prologue is cleared
  (main+0xFB5834, cDemoStartUp's flow, under sInfoMan's lock).
* Nothing else gates the modes: EXTRA CONTENT (uIdStartUp02, update main+0xA83450) enables mode 1 (THE MERCENARIES) and
  mode 2 (NO MERCY) unconditionally (jump table main+0x2176F88); modes 0 and 3-6 (Agent Hunt, Survivors, Onslaught,
  Predator, Siege) only test sBioStorage+0x88 / +0x8C. All ten stages and the four characters are open.

The unlock is a RAM-only write: once the title screen (uIdTitle00) is up, so the save has been created or loaded, read
mUnlockFlag (both copies), set bit 0, read it back, then wait for the title's own +0x20A byte to turn 1. The game's next
autosave records the bit in SAVEDATA (file offset 0xE8; checksum at 0x30 = the u32 sum of the file from 0x34), the
same state a cleared Prologue leaves; set_save_flag() can take it out of a save again (rollback).
"""
from __future__ import annotations

import struct
import threading
import time

TITLE_ID = "01002A000CD48000"
UPDATE_TITLE_ID = "01002A000CD48800"
UPDATE_VERSION = 131072                      # the update NSP's [v131072]; the game shows 1.0.2
GAME_ID = "115f9cdbba115432"                 # catalog: quickswap-switch:Resident Evil 6/Resident Evil 6 [01002A000CD48000].nsp
UPDATE_GAME_ID = "5d50031f5c8057b1"          # catalog: the [01002A000CD48800][v131072] update NSP
MAIN_BUILD_ID = "061D2A06CD700785E987C42CE2D72231"
MAIN_NSO_SHA256 = "e42734cc39901ac4dd3f8a18fe4298dede97510867ad55aab0581d81c5dc5d99"     # Citron dump_nso (header + image)
EXEFS_MAIN_SHA256 = "8b81f49fde9d57a1dc47d79c7baa0e3db42dbde2e7a1cee867d14ebc97248a3a"   # the update's ExeFS main (NSO)
PROFILE = "re6-switch-prologue-gate-ram-v1"

# main's image (ASLR may move it; four Citron boots kept 0x3CA7C04000): 64 bytes of read-only data unique in main and
# absent from rtld / sdk / subsdk0
SIG_OFF = 0x2151000
SIGNATURE = bytes.fromhex("f304353f08208038386c3bbd286b6ece8716993eb743ba51a0d80b3e00401c46"
                          "008097436666863facc5273700c0284520bcbe4b017ba13ddb0fc93f48e17a3f")
# the gate as this build compiles it: uIdTitle00's update reading sInfoMan -> cSystemInfo[+0x2C] -> mUnlockFlag bit 0
TITLE_GATE_OFF = 0xAD5D6C
TITLE_GATE_CODE = bytes.fromhex("b4f0009088f245f9092d80b90a45955228210a9b0801443968000036e8030032682a0839")
TITLE_UPDATE_FN, DEMO_TITLE_GATE, PROLOGUE_CLEAR_SETTER = 0xAD5D40, 0xFC2B90, 0xFB5834
EXTRA_LIST_ENABLE_FN, EXTRA_LIST_JUMP_TABLE, SYSTEM_INFO_PROPERTIES_FN = 0xA83450, 0x2176F88, 0x112A620

S_INFOMAN = 0x28E9BE0                        # sInfoMan::mpInstance
INFO_INDEX, INFO_ARRAY, INFO_STRIDE = 0x2C, 0x48, 0xAA28
COPY_A, COPY_B = 0x8, 0x5518                 # cSystemInfo: vtable, then two copies of 0x5510 bytes
UNLOCK_FLAG = 0xB8                           # mTempData.mHistory.mUnlockFlag in copy A (copy B: +0x5510)
PROLOGUE_CLEARED = 0x1
FLAG_ADDRS = (UNLOCK_FLAG, UNLOCK_FLAG + COPY_B - COPY_A)

S_UNIT = 0x2A60780                           # sUnit::mpInstance (an sBioUnit)
UNIT_LINES, LINE_STRIDE, UNIT_NEXT, N_LINES, LINE_MAX = 0x268, 0x30, 0x20, 32, 96
TITLE_MENU_OPEN = 0x20A                      # uIdTitle00: 1 = the title opens the main menu (else the Prologue)
UNIT_VTABLES = {                             # interface units of this build by their vtable (main + offset)
    0x269B390: "uIdTitle00", 0x2698958: "uIdStartUp00", 0x26988B0: "uIdStartUp01", 0x2698808: "uIdStartUp02",
    0x2699658: "uIdStartUp10", 0x2699070: "uIdStartUp1a", 0x26998C8: "uIdStartUp20", 0x2685650: "uIdMerceUI",
    0x2683608: "uIdGameover00", 0x2681440: "uIdAlert00", 0x2685A68: "uIdNowLoading00", 0x2686750: "uIdResult30",
    0x2686EF8: "uIdSignIn00", 0x2686968: "uIdSave00", 0x2686A38: "uIdSaving00", 0x269A080: "uIdStartUp30",
    0x2699F30: "uIdStartUp31", 0x2699E88: "uIdStartUp32",
}
MENU_UNITS = ("uIdStartUp00", "uIdStartUp01", "uIdStartUp02",       # main menu, PLAY GAME, EXTRA CONTENT
              "uIdStartUp30", "uIdStartUp31", "uIdStartUp32")      # the Mercenaries menu, STAGE, CHARACTER

# SAVEDATA (save:/SAVEDATA, 0x7050 bytes): u32 checksum at 0x30 over the u32 words from 0x34 to the end;
# cSystemInfo copy A from file offset 0x38 (file = cSystemInfo offset + 0x30)
SAVE_SIZE, SAVE_CHECKSUM, SAVE_SUM_FROM, SAVE_UNLOCK_FLAG = 0x7050, 0x30, 0x34, UNLOCK_FLAG + 0x30


def u64(m, a: int) -> int:
    return struct.unpack("<Q", m.rd(a, 8))[0]


def u32(m, a: int) -> int:
    return struct.unpack("<I", m.rd(a, 4))[0]


def ptr_ok(p) -> bool:
    return isinstance(p, int) and 0x1000000 <= p < (1 << 40)


class AdapterMemory:
    """gbox.adapters.SwitchLinuxAdapter (or anything with read_memory / write_memory) as rd / wr / rows."""

    def __init__(self, adapter):
        self.adapter = adapter
        self.module_base = None

    def rd(self, a: int, n: int) -> bytes:
        return bytes(self.adapter.read_memory(a, n))

    def wr(self, a: int, data: bytes):
        return self.adapter.write_memory(a, data)

    def rows(self) -> list:
        guest = getattr(self.adapter, "_guest", None)
        if not callable(guest):
            return []
        _pid, arena = guest()
        shift = 0 if getattr(self.adapter, "address_mode", "direct") == "direct" else arena.get("base", 0)
        return [(s - shift, e - shift, p) for s, e, p in arena.get("mapped", [])]


def _rows(m) -> list:
    rows = getattr(m, "rows", None)
    return list(rows() if callable(rows) else rows or [])


def module_base(m) -> int | None:
    """main's load address this boot (cached on m, checked again with one 64-byte read)."""
    base = getattr(m, "module_base", None)
    if isinstance(base, int):
        try:
            if m.rd(base + SIG_OFF, len(SIGNATURE)) == SIGNATURE:
                return base
        except (ValueError, OSError):
            pass
    for s, e, p in _rows(m):
        if not p.startswith("r") or "w" in p:
            continue
        step = 1 << 24
        for off in range(s, e, step):
            n = min(step + len(SIGNATURE), e - off)
            try:
                chunk = m.rd(off, n)
            except (ValueError, OSError):
                break
            i = chunk.find(SIGNATURE)
            if i >= 0:
                found = off + i - SIG_OFF
                try:
                    m.module_base = found
                except AttributeError:
                    pass
                return found
    return None


def build_ok(m, base: int) -> bool:
    """This exact build: the title's gate compiled as measured (the routine the unlock relies on)."""
    try:
        return m.rd(base + TITLE_GATE_OFF, len(TITLE_GATE_CODE)) == TITLE_GATE_CODE
    except (ValueError, OSError):
        return False


def system_info(m, base: int) -> int | None:
    """The current cSystemInfo (sInfoMan + 0x48 + index * 0xAA28), None before sInfoMan exists."""
    im = u64(m, base + S_INFOMAN)
    if not ptr_ok(im):
        return None
    idx = struct.unpack("<i", m.rd(im + INFO_INDEX, 4))[0]
    if not 0 <= idx < 4:
        return None
    return im + INFO_ARRAY + idx * INFO_STRIDE


def ui_units(m, base: int) -> dict:
    """The interface units up now, by vtable: class name -> first unit of that class."""
    out: dict = {}
    su = u64(m, base + S_UNIT)
    if not ptr_ok(su):
        return out
    for line in range(N_LINES):
        try:
            u = u64(m, su + UNIT_LINES + LINE_STRIDE * line)
        except (ValueError, OSError):
            continue
        n = 0
        while ptr_ok(u) and n < LINE_MAX:
            try:
                name = UNIT_VTABLES.get(u64(m, u) - base)
                if name and name not in out:
                    out[name] = u
                u = u64(m, u + UNIT_NEXT)
            except (ValueError, OSError):
                break
            n += 1
    return out


def status(m) -> dict:
    """Where the game is for the unlock: booting / refused (another build) / waiting (no title yet) / title / menu."""
    base = module_base(m)
    if base is None:
        return {"state": "booting"}
    if not build_ok(m, base):
        return {"state": "refused", "module_base": base,
                "reason": f"main+{TITLE_GATE_OFF:#x} is not the title gate of build {MAIN_BUILD_ID}"}
    out = {"module_base": base}
    info = system_info(m, base)
    ui = ui_units(m, base)
    out["ui"] = sorted(ui)
    if info is not None:
        out["system_info"] = info
        out["unlock_flags"] = [u32(m, info + a) for a in FLAG_ADDRS]
    if any(name in ui for name in MENU_UNITS):
        return out | {"state": "menu"}
    title = ui.get("uIdTitle00")
    if title is None or info is None:
        return out | {"state": "waiting"}
    out["title"] = title
    out["title_menu_open"] = m.rd(title + TITLE_MENU_OPEN, 1)[0]
    return out | {"state": "title"}


def _write_u32(m, a: int, value: int):
    data = struct.pack("<I", value)
    writer = getattr(m, "wr", None)
    if callable(writer):
        writer(a, data)
    elif hasattr(m, "write_memory"):
        m.write_memory(a, data)
    back = u32(m, a)
    if back != value:
        raise RuntimeError(f"unlock write at {a:#x} read back {back:#x}, not {value:#x}")


def apply(m) -> dict:
    """One step: at the title, set bit 0 of mUnlockFlag (both copies) where it is clear, original read first and
    every write read back. Returns the status with `writes` [{address, before, after}] (empty when already set)."""
    st = status(m)
    st["writes"] = []
    if st["state"] != "title":
        return st
    info = st["system_info"]
    for off in FLAG_ADDRS:
        before = u32(m, info + off)
        if before & PROLOGUE_CLEARED:
            continue
        after = before | PROLOGUE_CLEARED
        _write_u32(m, info + off, after)
        st["writes"].append({"address": info + off, "field": f"cSystemInfo+{off:#x}", "before": before,
                             "after": after})
    st["unlock_flags"] = [u32(m, info + a) for a in FLAG_ADDRS]
    return st


def watch(m, timeout_s: float = 1800.0, poll_s: float = 0.25, alive=lambda: True, clock=time.monotonic,
          sleep=time.sleep, log=None) -> dict:
    """apply() until the title confirms (+0x20A = 1, the main menu is what it opens now) or a menu unit is up. The
    title can come back with the flag cleared (the save loaded over it): it is set again. Gives up on another build,
    a session that ended, or the timeout."""
    deadline = clock() + timeout_s
    record: dict = {"profile": PROFILE, "writes": [], "states": []}
    while clock() < deadline:
        if not alive():
            return record | {"state": "session_ended"}
        try:
            st = apply(m)
        except RuntimeError as e:                             # a write that did not read back: try again next poll
            st = {"state": "write_unconfirmed", "error": str(e)[:160], "writes": []}
        except (ValueError, OSError) as e:                    # not booted yet / memory moving: try again
            st = {"state": "booting", "error": str(e)[:160], "writes": []}
        record["writes"] += st.get("writes", [])
        if not record["states"] or record["states"][-1] != st["state"]:
            record["states"].append(st["state"])
            if log:
                log(st)
        if st["state"] == "refused":
            return record | {"state": "refused", "reason": st.get("reason")}
        done = "applied" if record["writes"] else "already_unlocked"
        if st["state"] == "menu":
            flags = st.get("unlock_flags") or [0]
            return record | {"state": done if flags[0] & PROLOGUE_CLEARED else "menu", "verified": "main menu up",
                             "unlock_flags": flags}
        if st["state"] == "title" and st.get("title_menu_open") == 1 and not st["writes"]:
            return record | {"state": done, "verified": "uIdTitle00+0x20A = 1 (the title opens the main menu)",
                             "unlock_flags": st.get("unlock_flags"), "module_base": st.get("module_base")}
        sleep(poll_s)
    return record | {"state": "timeout"}


def start_watch(adapter, timeout_s: float = 1800.0, on_done=None) -> threading.Thread:
    """watch() on a session's adapter in a daemon thread (the launch returns at once); on_done(record) at the end."""
    m = AdapterMemory(adapter)

    def alive() -> bool:
        proc = getattr(adapter, "proc", None)
        return proc is None or proc.poll() is None

    def run():
        try:
            record = watch(m, timeout_s=timeout_s, alive=alive)
        except Exception as e:                                # noqa: BLE001 - never takes the session down
            record = {"profile": PROFILE, "state": "failed", "reason": str(e)[:240]}
        if on_done:
            on_done(record)

    t = threading.Thread(target=run, name="re6-switch-unlock", daemon=True)
    t.start()
    return t


# ---- the save file (rollback, or a save-side edit where RAM is not reachable)

def save_checksum(data: bytes) -> int:
    body = data[SAVE_SUM_FROM:]
    return sum(struct.unpack(f"<{len(body) // 4}I", body[:len(body) // 4 * 4])) & 0xFFFFFFFF


def save_unlock_flag(data: bytes) -> int:
    if len(data) != SAVE_SIZE or struct.unpack_from("<I", data, SAVE_CHECKSUM)[0] != save_checksum(data):
        raise ValueError("not an RE6 Switch SAVEDATA (size or checksum)")
    return struct.unpack_from("<I", data, SAVE_UNLOCK_FLAG)[0]


def set_save_flag(data: bytes, on: bool) -> bytes:
    """SAVEDATA with bit 0 of mUnlockFlag set or cleared and the checksum fixed (refuses anything else)."""
    flag = save_unlock_flag(data)
    out = bytearray(data)
    struct.pack_into("<I", out, SAVE_UNLOCK_FLAG, (flag | PROLOGUE_CLEARED) if on else (flag & ~PROLOGUE_CLEARED))
    struct.pack_into("<I", out, SAVE_CHECKSUM, save_checksum(bytes(out)))
    return bytes(out)


def profile() -> dict:
    """The verified profile's evidence chain (gbox.re_switch.unlock_profile)."""
    return {
        "profile": PROFILE,
        "scope": ["main menu without the forced Prologue", "PLAY GAME > EXTRA CONTENT > THE MERCENARIES",
                  "THE MERCENARIES NO MERCY (mode 2)", "all 10 Mercenaries stages and the 4 starting characters"],
        "exclusions": ["Agent Hunt, Survivors, Onslaught, Predator and Siege keep their online / player checks",
                       "unlockable Mercenaries characters and costumes (not measured)", "campaign chapters"],
        "evidence": {
            "title_id": TITLE_ID, "update": {"title_id": UPDATE_TITLE_ID, "version": UPDATE_VERSION},
            "catalog_game_ids": {"base": GAME_ID, "update": UPDATE_GAME_ID},
            "main_build_id": MAIN_BUILD_ID, "main_nso_sha256": MAIN_NSO_SHA256,
            "exefs_main_sha256": EXEFS_MAIN_SHA256,
            "module_signature": f"main+{SIG_OFF:#x} (64 bytes)",
            "flag": "cSystemInfo.mTempData.mHistory.mUnlockFlag bit 0 (sInfoMan main+0x28E9BE0, +0x48 + idx*0xAA28, "
                    "+0xB8 and +0x55C8)",
            "routines": {"title_gate": f"main+{TITLE_UPDATE_FN:#x} (uIdTitle00 update; check at "
                                       f"main+{TITLE_GATE_OFF:#x}, verified byte-for-byte before any write)",
                         "demo_title_gate": f"main+{DEMO_TITLE_GATE:#x}",
                         "native_setter": f"main+{PROLOGUE_CLEAR_SETTER:#x} (the Prologue cleared)",
                         "extra_content_enable": f"main+{EXTRA_LIST_ENABLE_FN:#x} (modes 1 and 2 always enabled, "
                                                 f"jump table main+{EXTRA_LIST_JUMP_TABLE:#x})",
                         "property_list": f"main+{SYSTEM_INFO_PROPERTIES_FN:#x} (cSystemInfo::createProperty)"},
            "live_acceptance": "2026-10-26 Citron NEO on the Spark: fresh save, flag 0x10 -> 0x11 at the title, main "
                               "menu, EXTRA CONTENT, THE MERCENARIES NO MERCY > SOLO > Urban Chaos > Leon, round "
                               "started; the post-round save holds 0x11 and the next boot opened the main menu with no "
                               "write; repeated from a fresh save through game_unlocks.session_start on a "
                               "SwitchLinuxAdapter bound to the emulator (docs/research/re6-switch-ram.md, "
                               "docs/evidence/re6-switch-unlock/)",
            "save": "SAVEDATA file offset 0xE8 = mUnlockFlag; checksum 0x30 = u32 sum from 0x34",
        },
        "apply": "post_launch_ram",
        "save_effect": ("RAM-only write at the title; the game's next autosave records bit 0 (Prologue cleared) in "
                        "SAVEDATA, as clearing the Prologue would. Rollback: gbox.re6_switch_unlock.set_save_flag(data, "
                        "False) on a backup copy of save:/SAVEDATA."),
    }
