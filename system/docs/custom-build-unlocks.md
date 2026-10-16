# Unlock-all custom build requirement

Favorites also have a persisted default: their original title and custom builds
should boot with every unlockable character, hidden entry, level/stage, costume,
mode, item and extra available. Enabling the policy does not claim that any title
already supports this. Missing or partial coverage is displayed as pending.

`GET /api/custom-build-unlocks` includes original-title coverage under `favorites`,
idle admission, and the existing per-game tasks. `@original` identifies the
unmodified catalog title; it uses a catalog-version/executable identity manifest,
so checking this policy never hashes or copies an entire ROM on Play. Per-build
receipts still pin the complete custom payload. Current profile/build changes
invalidate acceptance.

The existing reconciler and Hermes queue share the work. Research waits for five
minutes of quiet, no running games/conversations/jobs/results or other Hermes
investigations, and fresh measured CPU/GPU/memory admission. At most one unlock
investigation starts per managed tick, with a default limit of two per hour.
Dispatch history survives restarts. Every request forbids automatic game launches
and ROM copying; unsupported titles stay pending. Existing analysis is reused.

`POST /api/custom-build-unlocks/policy` accepts partial updates for
`favorites_enabled`, `default_boot`, `idle_resolution`, `excluded_games`,
`quiet_seconds` (30–3600), and `dispatch_per_hour` (1–4), independently of the older
custom-build `enabled` switch. Default-on favorite scope can be disabled globally
or for exact game IDs. This changes no worker permission grants or schedules.

For original titles, an accepted profile must also publish `boot_apply` with
`kind: "live_control"`, the current published live-control `revision` and `action`,
exact declared `values`, complete `coverage` matching the profile's eight-category
inventory, and stored `runtime_artifacts` proving that full boot application. Only
an existing native `unlock_all` control is accepted; generic byte writes, partial
actions, disabled/revert actions and a bare verified flag are rejected. Publish
and verify the original target with the same profile/manifest/verify endpoints,
using `@original` as its name. Evidence must cover a fresh boot and all content.

`GET /api/custom-build-unlocks/{game_id}/boot-plan?name=MOD` returns a verified
recipe or a visible pending reason. The launch hook uses only that exact accepted
recipe, existing native revision/mode guards and current worker permissions.
It never performs analysis, launches another game or edits a ROM. A changed/staged
identity, unavailable scene or missing explicit native readback remains pending.
Applying a recipe never closes its investigation or invents runtime coverage.

`POST /api/custom-build-unlocks/policy {"enabled":true}` persists the operator's standing requirement for every existing and future custom build. It covers characters, hidden characters, levels (including hidden levels), stages, costumes, modes, items and extras such as galleries, music, movies and endings. The scope is unlockable content in the owned game. Policy activation does not itself patch ROMs or prove that content is unlocked.

The background scanner creates one persistent Ghidra investigation/application ticket per catalog game, including builds known only through Windows worker inventories. New versions update that ticket. Broken builds awaiting disposal use their separate investigation. Discovery must pin the exact executable, inventory hidden content, identify the lock checks with Ghidra, and implement a reusable step in the game's custom-build writer. Existing findings and profiles are reused. Analysis stays off the Play path.

`GET /api/custom-build-unlocks` exposes the policy, current build versions, verification status and tickets. Mods cards and Builds rows show **Unlock-all pending** until acceptance. Game-running verification remains separate. Nothing is automatically described as unlocked merely because a Ghidra task was queued.

The investigation ticket documents the profile and receipt API contracts:

- `GET/POST /api/custom-build-unlocks/{game_id}/profile`: a complete inventory, exact executable SHA256, reusable implementation, stored Ghidra artifacts and runtime evidence. Missing categories or evidence are rejected. The read endpoint also exposes existing game-specific unlock support.
- `GET /api/custom-build-unlocks/{game_id}/{name}/manifest`: current build identity and exact file hashes.
- `POST /api/custom-build-unlocks/{game_id}/{name}/verify`: matching build version, profile revision and complete manifest, stored runtime evidence and application/verification notes. Use only after applying and testing the full unlock inventory in this build.

Rebuilt markers, changed profiles and changed payload file signatures invalidate prior acceptance. Verification hashes the full payload; UI and launch paths do not. The ticket cannot be marked done while current builds lack verified receipts. The agent must test fresh boots and actual selection/gameplay on an idle test machine, preserve original personal saves/base ROMs, and account for unavailable content explicitly. No generic byte patches or guessed addresses are applied by enabling this policy.
