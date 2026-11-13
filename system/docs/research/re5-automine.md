# RE5 armed Automine and escape ring

Operator requirements (2026-11-13): Automine defaults on; drop native armed mines
every 20 feet of actual movement, plus hit/QTE reactions, without equipping a
mine or taking over the movement input. Manual Mine Ring means flash cover plus
five armed mines at a five-foot radius, followed by hazard-aware escape.

## Live acceptance of native placement

Pinned Switch RE5 EBFFDB22 build. Request
`9a326a4b-41ce-47c7-bea6-4871e7b3e97f`, session
`125c9f417ce3496f-9be9d5f015544d35`, round
`432738460bb24b26bfffc95ea488e467`, Unix time 1794567546.1556.
Five native units (generations 2161–2165) were configured, grounded, and
observed active with native trigger-volume enabled bytes equal to one and
arming timers zero. All five positions were 152.4 cm from the commit center.
Placement span 964.7 ms; full preparation/arming receipt 4222.8 ms.
Hydra item 25 remained equipped before and after; inventory was not consumed.
The native path has no equipment, input, health, or invulnerability writes.

Full receipt is retained on Spark at
`gbox-data/mercs/native-intervention-receipts/6c9cd7d6b8ed08aaecc778b73042d363d7172a415e9058d1a9b07b66ff9bf1ea.json`,
SHA-256 `9b18d2c5f086f8a0c6793acd81b4ab4ea3ce6e1511d6a5f43c6f0f3538bbc22d`.
Its API state was uncertain because the build's live-verification gate was
still false; the complete native receipt establishes armed placement.
Earlier single-drop request `e92217bf-7479-4c51-892b-8b541e94dd83` also observed
an active armed mine with Hydra preserved, in 850.8 ms.

HP fell 930 to 706 during the five-mine observation window while enemies were
active. No mine trigger was observed. This does not establish the source of
damage or successful escape; those remain separate round-analysis measures.

Manual completion requires every requested mine to have an observed native
armed volume or an already-observed native trigger. A factory return alone
cannot produce a success receipt. Partial/unknown results are retained and
never automatically replayed. Live placement is now available on this pinned
build. The combined flash/escape behavior and distance-based automatic cadence
still require post-deployment round observation.

The Automine preference is exposed in the RE5 modifiers and PineLive controls,
saved per game, and defaults true. It is independent of inventory mine supply.
Automatic gameplay no longer enters the legacy equip/plant routine. A native
job runs beside movement; only observed physical hazards may request a retreat.
Damage/grab edges are observed before the engine's prompt-only early returns.
Flash reactions bypass the old 60-second emergency cooldown for fresh events;
the native mailbox still admits only one operation at a time, with bounded
event freshness and no replay of uncertain placements.

Validation before activation: focused mine/manual/queue/control tests passed
102 with two skips; mods/parity/weapon-mastery passed 92; reactive flash/engine
tests passed 42; client request/modifier tests passed 86. Native class/ABI
checks also passed. These checks do not establish S rank or live escape success.

A follow-up receipt/census race fix retains the exact snapshot census consumed
with a fresh mine receipt: the same observation cannot retire the newly armed
mine just because the engine and bot use slightly different timestamps. A new
census may retire it, and new rounds clear the references. Its focused suite
passed 91 tests.

## Adjacent corrections

Ordinary gun animation scaling was silently capped at 5x despite higher
requests. The cap, round default and Switch sliders now agree at 20x; scale
restoration still occurs outside the verified shot motion. This measures
animation scaling, not an unmeasured claim of 20 actual shots per second.

The grenade identity check incorrectly accepted only the flash vtable even
when the factory was asked for hand/incendiary grenades. Native allocator
exports `9211b0.json`, `920f70.json`, `920b60.json` in Spark's
`analysis/merc-full/re5-shell-research-20261113` establish final unit tables
`1C5FA38`, `1C5F4C8`, `1C5EF58` (main-relative), respectively. Checks now match
the requested class as well as owner and allocation generation. Fake tests
now exercise those checks instead of disabling them. Hand/incendiary live
availability is unchanged until their own native effects are verified.
