# Unlock-all custom build requirement

`POST /api/custom-build-unlocks/policy {"enabled":true}` persists the operator's standing requirement for every existing and future custom build. It covers characters, hidden characters, levels (including hidden levels), stages, costumes, modes, items and extras such as galleries, music, movies and endings. The scope is unlockable content in the owned game. Policy activation does not itself patch ROMs or prove that content is unlocked.

The background scanner creates one persistent Ghidra investigation/application ticket per catalog game, including builds known only through Windows worker inventories. New versions update that ticket. Broken builds awaiting disposal use their separate investigation. Discovery must pin the exact executable, inventory hidden content, identify the lock checks with Ghidra, and implement a reusable step in the game's custom-build writer. Existing findings and profiles are reused. Analysis stays off the Play path.

`GET /api/custom-build-unlocks` exposes the policy, current build versions, verification status and tickets. Mods cards and Builds rows show **Unlock-all pending** until acceptance. Game-running verification remains separate. Nothing is automatically described as unlocked merely because a Ghidra task was queued.

The investigation ticket documents the profile and receipt API contracts:

- `GET/POST /api/custom-build-unlocks/{game_id}/profile`: a complete inventory, exact executable SHA256, reusable implementation, stored Ghidra artifacts and runtime evidence. Missing categories or evidence are rejected. The read endpoint also exposes existing game-specific unlock support.
- `GET /api/custom-build-unlocks/{game_id}/{name}/manifest`: current build identity and exact file hashes.
- `POST /api/custom-build-unlocks/{game_id}/{name}/verify`: matching build version, profile revision and complete manifest, stored runtime evidence and application/verification notes. Use only after applying and testing the full unlock inventory in this build.

Rebuilt markers, changed profiles and changed payload file signatures invalidate prior acceptance. Verification hashes the full payload; UI and launch paths do not. The ticket cannot be marked done while current builds lack verified receipts. The agent must test fresh boots and actual selection/gameplay on an idle test machine, preserve original personal saves/base ROMs, and account for unavailable content explicitly. No generic byte patches or guessed addresses are applied by enabling this policy.
