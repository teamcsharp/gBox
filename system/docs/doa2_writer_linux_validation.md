# DOA2 LE JP writer — independent Linux validation of the native reintegration stack

Run: 2026-10-10 (Hermes cron fe4aa883825e, GLM-5.3 via Z.AI). This documents an
independent reproduction of the native writer stack introduced in PR #8
(`codex/request-1135-native-writer`, commits `139c314`/`ca59c10`/`712a706`) on
Linux/aarch64, using the operator's owned DOA2 LE JP disc assets already
extracted for the reader slice (see `docs/doa2_re_findings.md`).

## Environment

- Worktree branch under review: `712a706` (tip of PR #8 at validation time), via
  `git fetch origin codex/request-1135-native-writer`.
- Interpreter: canonical `.venv-linux-aarch64/bin/python` (3.12), `PYTHONPATH`
  pointing at the checked-out `system/`, `-P` enabled.
- Owned fixtures: `disc.gdi` + extracted `1ST_READ.BIN`
  (sha256 `27a014ae…c20c97e1`, matching `doa2_bindings.EXECUTABLE_SHA256`),
  `TNG_A00.ACS` re-extracted from the owned GDI for the ACS component test.
- Donor: `sa2_amy_rose` from the shared character library.

## Test results

`pytest -k doa2` with `GBOX_DOA2_EXE` + `GBOX_DOA2_FIXTURES` set:

```
203 passed, 46 subtests passed (0 skips)
```

Without fixtures the suite degrades to skips, not failures (12 executable-based
skips + 3 fixture skips), i.e. the suite is honest about its owned-asset
dependencies.

Notes:

- `GBOX_DOA2_EXE` must point at the unscrambled `1ST_READ.BIN`, **not** the
  wrapped ELF (`doa2le.elf`, sha256 `0d5e404e…`): `doa2_bindings` pins the
  executable hash and correctly refuses other binaries.
- Full non-DOA2 test run on this worktree shows 6 failures
  (`test_adapters`, `test_control_plane`, `test_rea`,
  `test_win_grab_visibility`×3). All 6 reproduce on the pre-DOA2 baseline
  `6c92106`, so they are pre-existing environment issues, not PR #8
  regressions.

## End-to-end writer build (Linux, CPU-only)

`doa2_swap.build()` for Kasumi costume 00 with the Amy Rose donor:

```
audit + profile: render_slot 5, costume 0, fighter KAS/00
build: 2.1 s total, status built_unverified
mod: doa2_kas00_sa2_amy_rose (GDI rebuilt in scratch)
```

Build report facts: 1,384 source triangles retained (matches the count
independently GPU-verified on JAYBUILTFINALE in attempt 7 of #1135), CHR
93,184 B within its 294,912 B sector budget, BIN exactly 332,800 B, supplements
APV/SUP/ACS neutralized via their native bindings (`kas_a00.acs` → slot 5
costume 0, native consumer `8c0332e4..8c033308`).

## Independent rebuilt-image verification

Reading the rebuilt GDI back with `GDRom` and comparing against the build
report:

- `DOA2/KAS00.CHR` 93,184 B, `KAS00.BIN` 332,800 B, `KAS00.APV` 491,008 B,
  `KAS00.SUP` 6,808 B, `KAS_A00.ACS` 6,798 B — all byte-exact round-trip PASS.
- `1ST_READ.BIN` sha256 unchanged vs the owned disc (no executable mutation in
  the single-costume path).
- `DOA2/KASUMI.MOT` sha256 unchanged — original fighter motion data preserved,
  as the ticket requires.

Rebuilt mod image sha256: `16b4ca0d642f93c93d4fa94789f5c3aabe0780865cf0d472c92bbd6e8f9f336b`.

## What this does and does not establish

Established: the PR #8 writer stack is reproducible outside the authoring
machine — tests green on Linux/aarch64 with the canonical venv, and the
retarget → encode → GDI rebuild pipeline produces a self-consistent, verified
mod image from the owned disc in seconds.

Not established here: gameplay. `built_unverified` is accurate; acceptance
still rests on the in-engine verification lane (native GPU proof, damage
registration, save-state reload on JAYBUILTFINALE) recorded on #1135/#1140,
plus the remaining work named there (public MCP deployment, cross-fighter
extent relocation, second donor/target gameplay test).
