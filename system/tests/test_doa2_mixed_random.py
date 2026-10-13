"""DOA2 two-franchise cast with a random costume on every selection (gbox.doa2_mixed, gbox.doa2_random_select), on a
synthetic executable that carries the game's rand() at its address: the hook's machine code, its table, the patch
guards, read-back, and an interpreted run of hook + rand() + tail jump (registers preserved, picks uniform, slots
without a pool untouched); the pool planner's half-and-half and mixing guarantees; then the owned executable when
present."""
import collections
import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import doa2_mixed as M, doa2_random_select as R

RAND_CODE = [0xD41E, 0xD31F, 0x4F12, 0x6242, 0x9135, 0x0237, 0x9234, 0x031A, 0x331C, 0x6033, 0x4029, 0x2029,
             0x2432, 0x000B, 0x4F16]            # the game's LCG at 0x8c120cf0, literals at +0x76 .. +0x80


def synthetic_exe() -> bytes:
    exe = bytearray(R.RAND - R.BASE + 0x100)
    struct.pack_into("<I", exe, R.POOL_WORD - R.BASE, R.COMMIT)
    o = R.RAND - R.BASE
    struct.pack_into(f"<{len(RAND_CODE)}H", exe, o, *RAND_CODE)
    struct.pack_into("<H", exe, 0x8C120D66 - R.BASE, 0x3039)
    struct.pack_into("<H", exe, 0x8C120D68 - R.BASE, 0x7FFF)
    struct.pack_into("<2I", exe, 0x8C120D6C - R.BASE, 0x8C1E64E0, 0x41C64E6D)
    return bytes(exe)


def test_routine_layout_and_literals():
    code = R.routine()
    assert len(code) == R.ROUTINE_BYTES == 0x80
    words = struct.unpack_from("<56H", code)
    assert words[0] == 0x4F22 and words[0x6C // 2] == 0x402B          # sts.l pr ... jmp @r0
    assert words[0x1E // 2] == 0x8900 | ((0x60 - 0x22) // 2)           # bt skip
    assert struct.unpack_from("<4I", code, 0x70) == (R.TABLE, R.RAND, R.TCNT0, R.COMMIT)
    for at, lit in ((0x20, 0x70), (0x34, 0x74), (0x3A, 0x78), (0x6A, 0x7C)):   # every mov.l @(disp,pc) lands on its literal
        w = words[at // 2]
        assert w >> 12 == 0xD and ((R.HOOK + at) & ~3) + 4 + 4 * (w & 0xFF) == R.HOOK + lit


def test_table_bytes_and_errors():
    t = R.table_bytes({0: [0, 1, 2], 24: [5]})
    assert len(t) == 400 and t[0:4] == bytes([3, 0, 1, 2]) and t[24 * 16:24 * 16 + 2] == bytes([1, 5])
    for bad in ({25: [0]}, {0: []}, {0: list(range(16))}, {0: [40]}):
        with pytest.raises(ValueError):
            R.table_bytes(bad)


def test_patch_guards_and_read_back():
    exe = synthetic_exe()
    with pytest.raises(ValueError):
        R.patch(exe, {0: [0, 1]})                                     # not the pinned executable
    x = R.patch(exe, {0: [0, 1], 7: [3, 5, 9]}, pinned=False)
    rb = R.read_back(x)
    assert rb["installed"] and rb["pools"] == {0: [0, 1], 7: [3, 5, 9]} and rb["signature"] == "GBOXRND1"
    assert not R.read_back(exe)["installed"]
    changed = [i for i, (a, b) in enumerate(zip(exe, x)) if a != b]
    assert all(R.HOOK - R.BASE <= i < R.TABLE - R.BASE + 400 or R.POOL_WORD - R.BASE <= i < R.POOL_WORD - R.BASE + 4
               for i in changed)                                      # only the gap and the one pool word
    with pytest.raises(ValueError):
        R.patch(x, {0: [0]}, pinned=False)                            # gap no longer empty / word already moved
    other = bytearray(exe)
    struct.pack_into("<I", other, R.POOL_WORD - R.BASE, 0x8C000000)
    with pytest.raises(ValueError):
        R.patch(bytes(other), {0: [0]}, pinned=False)


def test_interpreted_hook_draws_from_the_pool_and_preserves_the_call():
    x = R.patch(synthetic_exe(), {0: [0, 1, 2, 3], 7: [6, 2]}, pinned=False)
    picks, seed = collections.Counter(), 0x2468ACE
    for k in range(800):
        r = R.simulate(x, slot=0, costume=9, player=k % 2, seed=seed, tcnt=k * 104729)
        seed = r["seed"]
        picks[r["costume"]] += 1
        assert r["jumped_to"] == R.COMMIT and r["slot"] == 0
        assert (r["r4"], r["r5"], r["r8"], r["r15"], r["pr"], r["macl"]) == \
               (0x8C300000, k % 2, 0x12345678, 0x8C2FF000, 0x8C026320, 0xCAFE)
    assert set(picks) == {0, 1, 2, 3} and min(picks.values()) > 150
    assert {R.simulate(x, slot=7, costume=0, seed=s * 7919 + 1)["costume"] for s in range(64)} == {6, 2}
    assert R.simulate(x, slot=3, costume=4)["costume"] == 4          # no pool: the player's own costume
    assert R.simulate(x, slot=30, costume=4)["costume"] == 4         # out of range slot: untouched
    lcg = (0x2468ACE * 0x41C64E6D + 12345) & 0xFFFFFFFF
    assert R.simulate(x, slot=0, costume=0, seed=0x2468ACE)["seed"] == lcg   # the game's own rand() advanced once


def test_unpatched_call_goes_straight_to_commit():
    r = R.simulate(synthetic_exe(), slot=0, costume=5)
    assert r["costume"] == 5 and r["jumped_to"] == R.COMMIT


def test_disassembly_matches_when_capstone_is_present():
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_SH, capstone.CS_MODE_SH4 | capstone.CS_MODE_LITTLE_ENDIAN)
    ins = [f"{i.mnemonic} {i.op_str}".strip() for i in md.disasm(R.routine()[:0x70], R.HOOK)]
    assert ins[:5] == ["sts.l pr, @-r15", "sts.l macl, @-r15", "mov.l r4, @-r15", "mov.l r5, @-r15",
                       "mov.l r8, @-r15"] or ins[0].startswith("sts.l")
    assert any(i.startswith("jsr") for i in ins) and any(i.startswith("jmp") for i in ins)
    assert sum(i.startswith("mul.l") for i in ins) == 1 and len(ins) == 56


# ---------------------------------------------------------------- pool planning

COSTUMES = {"KAS": ["00", "01", "02", "03", "04", "05", "06", "07", "09"], "AYA": [f"{i:02}" for i in range(7)],
            "LEI": [f"{i:02}" for i in range(6)], "TIN": [f"{i:02}" for i in range(7)], "BAS": ["00", "01", "02", "03"],
            "JAN": [f"{i:02}" for i in range(5)], "GEN": [f"{i:02}" for i in range(6)], "BAY": ["00", "01", "03", "04"],
            "RYU": [f"{i:02}" for i in range(5)], "ZAC": [f"{i:02}" for i in range(5)], "HIK": [f"{i:02}" for i in range(7)],
            "SAM": ["00", "01", "02"], "TNG": ["00", "01"], "KTE": [f"{i:02}" for i in range(5)]}


def test_plan_is_half_and_half_and_every_pool_mixes():
    plan = M.plan_pools(COSTUMES)
    chk = M.check_plan(plan)
    assert chk["ok"], chk["problems"]
    assert (chk["headline_sa2"], chk["headline_sm64ds"], chk["costumes"]) == (7, 7, 75)
    for family, pool in plan.items():
        assert [c for c, _s in pool] == COSTUMES[family]
        assert pool[0][1] == M.HEADLINE[family]
        fr = [M.franchise(s) for _c, s in pool]
        assert all(a != b for a, b in zip(fr, fr[1:2]))               # the second costume is the other franchise
        assert len({s for _c, s in pool}) == len(pool)               # no donor twice in one fighter's pool
    assert {M.franchise(s) for _c, s in plan["TNG"]} == {"SA2", "SM64DS"}
    assert set(chk["donors"]) <= set(M.SA2) | set(M.SM64DS)
    assert M.plan_pools(COSTUMES) == plan                             # deterministic
    assert M.plan_pools(COSTUMES, seed="other") != plan


def test_plan_errors():
    with pytest.raises(ValueError):
        M.plan_pools({"XXX": ["00"]})
    lopsided = {k: v for k, v in M.HEADLINE.items()} | {"KAS": "sonic", "TIN": "sonic", "BAS": "sonic"}
    with pytest.raises(ValueError):
        M.plan_pools(COSTUMES, headline=lopsided)
    single = M.check_plan({"KAS": [("00", "sonic"), ("01", "sa2_tails")]})
    assert not single["ok"] and "KAS can only be SA2" in single["problems"][0]


# ---------------------------------------------------------------- the owned executable

def _owned_exe() -> bytes | None:
    for c in (os.environ.get("GBOX_DOA2_EXE"), r"D:\gBox\research\doa2_mixed_1st_read.bin"):
        try:
            if c and Path(c).is_file():
                data = Path(c).read_bytes()
                if hashlib.sha256(data).hexdigest() == R.EXECUTABLE_SHA256:
                    return data
        except OSError:
            continue
    return None


@pytest.mark.skipif(_owned_exe() is None, reason="owned DOA2 LE 1ST_READ.BIN not on this node")
def test_owned_executable_sites_and_render_pools():
    exe = _owned_exe()
    R.check_executable(exe)
    code = exe[0x8C026318 - R.BASE:0x8C02631E - R.BASE + 2]
    assert struct.unpack("<4H", code) == (0xD21C, 0x6593, 0x420B, 0x64C3)   # mov.l @pool,r2; mov r9,r5; jsr @r2; mov r12,r4
    assert struct.unpack("<3H", exe[R.RAND - R.BASE:R.RAND - R.BASE + 6]) == tuple(RAND_CODE[:3])
    plan = M.plan_pools(COSTUMES)
    pools, where = M.render_pools(exe, plan)
    assert sum(len(v) for v in pools.values()) == 75 and len(pools) == 14
    assert where["KAS"]["09"] == (5, 8) and pools[8] == [0, 1, 3, 4]       # BAY has no costume 2 on the disc
    x = R.patch(exe, pools)
    seed, seen = 0x1357, set()
    for k in range(200):
        r = R.simulate(x, slot=5, costume=0, seed=seed, tcnt=k * 977)
        seed = r["seed"]
        seen.add(r["costume"])
    assert seen == set(pools[5])
