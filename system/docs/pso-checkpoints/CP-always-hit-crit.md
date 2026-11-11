# Always-hit is on, crit-always is not: measured on the running PSO (2026-11-10 ~21:33)

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: 2

The operator asked: *"make sure that the attacks always land. Make sure that every attack is always a critical attack and that it always
lands no matter what."*

Both features exist as **verified patches** in gBox, and their live state can be read without writing anything:

| patch | module | site | live state |
|---|---|---|---|
| **always hit** | `pso_accuracy` (`SITES` + `PATCHES`, cave `0x80006800`) | `0x80015f00`, `0x80016384` | **PATCH (active) on both sites** |
| **crit always** | `pso_crit` (`SITE 0x8001468c`, `PATCH 4bff0974`, `ORIGINAL 40820030`, header `0x800050e0`) | `0x8001468c` | **original - not installed** |

So attacks already always land (the two accuracy sites carry the verified branch), and every hit is **not** yet a critical.

## Why crit is not simply switched on

`pso_crit.GameCube.set_enabled(True)` does three writes (`CODE` at the cave, `METADATA` at the header, `PATCH` at the site) **and then
flushes the guest instruction cache** through a guest call (`self.call([(FLUSH, address)])`). `pso_live.OPS` has no `crit` op, and
the session RPC exposes `read_memory`/`write_memory` but not a guest call, so a write-only install would leave the memory patched
while Dolphin's JIT may keep running the old block - a false "crit_always: true" that the game does not honour. The module's own
`status()` would then lie.

**The honest requirement:** a `crit` op in `pso_live` (handler calling `pso_crit.set_enabled(ad, inp.on)`), which needs the running
gBox server to be restarted to pick it up - and a restart closes the operator's in-progress game.

**Verified reader for both states:** `docs/research/check-pso-hooks.py` - reads the sites and metadata through the 18765 byte RPC and
prints PATCH/original per site, so after any change the state can be re-measured instead of assumed.
