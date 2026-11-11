# Live platform fixes proven on the i9 (2026-11-10, ~21:00-21:15)

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: 2

## What works now, with the evidence

**1. The operator's controller is Player 1 through gBox** - after `GBOX_DOLPHIN_VPAD=off` and a restart,
`_want_vpad` returns False, `_argv`'s fallback calls `pad_bind` (`probe_pads -> {1: (0,-74,-348,278,-1046,0,0)}`), and the written
`GCPadNew.ini` carries `# gBox: Player 1 bound to XInput slot 1 ...` / `Device = XInput/1/Gamepad`. The operator played in-game as
"Deb" Lv 1 (docked in the gBox window).

**2. Random high-level weapon + mag every five minutes** - `docs/research/pso-cycle-build.py` running as a background job:

```
{"at": "21:15:06", "codes": ["000f02","024000"], "state": "ok", "spawned": 2, "verified": true,
 "ids": [15728642,15728643], "ms": 797.0}
```

Codes come from the plane's own plans (`pso_loadout op=plan preset=atp` for weapons, explicit mag names for mags), so every item is
disc-validated; 12 weapon + 12 mag codes rotate without repeats until a pool is exhausted.

**3. The operator's play is learned** - `pso_record_operator.py` sampled their pad at 30 Hz for ~15 minutes: **1,549 input changes ->
imitate.learn -> 173 bursts, menu keys `start, x, a`**, and a mission (`D:\\gBox\\pso-ds\\learned-missions\\pso-learned-20261110-210547.json`).

## Two live-path bugs, both measured

**A. `pso_loadout op=drop` posts to the wrong host and an 8 s expiry.** The tool builds
`expires = time.time() + 8` and posts `pso_controls` to `ctx.server`; on this machine `ctx.server` is `127.0.0.1:18765`
(`desktop_local`) and the drop returned **422 "PSO command expired"** while the same command sent to the same port with a **fresh
`now + 5`** expiry returned **200 `{"spawned": 2, "verified": true}`**. The control layer's validation is
`now < expires <= now + 15` (`pso_live.validate`), so 8 s is legal but leaves no room for the plan request that precedes it under
load; a caller must compute the expiry *immediately before* the POST.

**B. `POST /api/sessions/<sid>/rpc` on the main API (8765) answers 504 "Session did not acknowledge"** for `read_memory` and
`pso_controls`, while the same reads succeed through the **job** route (`{"tool": "read_memory"}`) in ~1.1 s. So the session RPC is
unreliable while the job path is not; tooling should prefer jobs, and the drop path should use the `desktop_local` port.

**Consequence for the remaining work:** route learning needs ~1 Hz position samples; the job route delivers ~0.9 Hz, which is enough
for waypoints (8-unit tolerance) on foot, and `pso_route.py` must be switched from the raw `/rpc` reader to the job path before it can
capture a city walk.
