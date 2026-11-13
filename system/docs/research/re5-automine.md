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

## Sprint cadence correction

The first activated Ship Deck round `0ab55576a450407c82db66ed7b2579cf`
retained native action 4 while holding B + forward and moving about three
metres between Unix times 1794569039.78 and 1794569040.92. The initial cadence
recognized walk (1) and backing (7), so it missed sprint distance. Observed
sprint motion 4 now contributes actual position deltas to the twenty-foot
cadence. Stationary movement input, teleports, stale intervals and non-travel
motions still contribute no distance. The evidence is retained in
`gbox-data/mercs/round_maps/010018100CD46000/Ship_Deck/20261113-052144-0ab55576.json`.
Focused scheduling regressions cover all three travel motions and native
submission from sprinting. This correction still needs another live round to
establish successful distance-triggered placement.

## Combined button acceptance after activation

Commit `0560aad9` activated between rounds at Unix time 1794568759.84.
New RE5 session `fff71e9405964236-be08dae348784be3`, round
`0ab55576a450407c82db66ed7b2579cf`, reports Automine true and configured gun
rate 20. Manual Mine Ring request `86491e97-228b-4b58-9957-9efe7c38e312`
was claimed at 1794569023.2869 and confirmed at 1794569027.1212.
Its full receipt confirms five flash detonations (zero observed self-damage),
five active armed mines, and Jail Breaker item 23 preserved with HP916 unchanged.
Native mine placement span was 341.4 ms; preparation/arming took 3533.3 ms.
Archive: `gbox-data/mercs/native-intervention-receipts/6d7fd37cad68c2faec5d418118f2054a58e028220164f4fcbeb5875ae00c4dcc.json`.
SHA-256: `507e14c9138890446dee218f3bd18c3416c123f52f67111777b4bf4d20afc8c5`.
Player position did not change during that receipt window; automatic escape
success is still being assessed separately, not inferred from arming.

## Primary trigger gate correction (user-reported non-detonating mines)

The earlier placement receipts are **not sufficient evidence of functional arming**.
They observed the secondary proximity volume only. Live read-only inspection of
RE5 PID4113346, main base0x3ca86aa000, found every active native drop with
secondary volume `unit+0x28C8` enabled but primary volume `unit+0x2710`
disabled. Enemy contacts within 19?44cm were present in Ship Deck round
0ab55576, with no recorded mine blasts. The raw live state is archived at
`gbox-data/analysis/merc-tuning-20261113/re5-mine-trigger-state.json`.

Native update0x81F700 explicitly clears the pending explosion bit when the
primary volume is absent or disabled. Configure0x60D6D0 disables that volume;
the custom drop path passed zero as its third argument, leaving unit+0x273F
clear. The native put action0x91E6D0 then permanently skipped primary enabling.
Placement now passes one, allowing the put action to enable the primary volume
and update native item flags through the normal lifecycle. Arming confirmation requires **both** volumes enabled,
or an actual native explosion latch already observed. No explosion latch,
enemy contact, inventory, equipment or health is written by this correction.
Independent execution of the real configure, put-action and mine-update
functions passes13 tests at two load bases. With the old argument, proximity
contact cannot latch an explosion; with the corrected argument it can. A late
flag correction does not repair an already-consumed put action. A real enemy
trigger and explosion after deployment remain required for live acceptance.

The adjacent escape correction passes its selected mesh waypoint to the wall
and room guards, preserves corners that cannot be cut safely, and moves toward
the waypoint while turning. Earlier manual-ring evidence showed initial motion
away followed by a return into the ring, so successful escape is not claimed.
The run now prioritizes remaining time bonuses over distant enemy hunting;
nearby emergency responses still take precedence.

## Validate the floor before activating a mine

Round `443f46cf24f54548a8078df81609c1ae` in Experimental Facility exposed a
separate placement defect. Receipt `711d15c82644400fbb2dd4cb99a446e8` requested
mine generation611 at Y=-474.883cm; native grounding placed it at
Y=-1929.005cm, 14.54m below that floor. After the same-floor mines triggered,
the lower mine remained a live hazard at263cm horizontal clearance. It prolonged
blocked escape; the earlier blocked escape began before this ring.

The former sequence activated/configured each mine before native ground
projection0x793AB0. The pinned function casts from100cm above the request to
a deep downward bound. It changes only Y on a collision hit, and native W0
retains that hit result through RET despite the export's inferred void type.
The complete264-byte function is checked with SHA-256
`9e9c111b224aa84d19a69bdaff46128beb6bf69ca50d6dfefb4cdfa246dab347`.
Its detached-object branch has no activation dependency. The actual reset
virtual0x60CC80 clears activation without changing either position.

Placement now resets and grounds every requested member while inactive, then
requires a real native hit, finite coordinates, unchanged horizontal position,
and at most61cm vertical difference from the requested floor. This is a
conservative placement policy matching the escape floor lookup tolerance,
not an assertion about blast height. No member is configured or armed unless
all requested points pass. The former unbounded post-activation raycast is
removed. Before each activation, the actor must still be inactive, detached,
owned by the same player and generation, with its validated position intact.
Both primary and proximity volumes still must be observed enabled for an
arming receipt; no contact or explosion flag is manufactured.

A rejected batch reports zero placed/armed mines and publishes no hazard.
Its inactive allocations are retained in a bounded pool of at most eight,
scoped to the exact player life, so repeated floor refusals do not allocate
more mines. Reuse checks allocation identity before and after reading state;
active, attached, recycled, foreign, or uncertain units are never reused.
Unknown partial activations remain uncertain and are not replayed.

Six offline Unicorn cases passed on Spark using the existing local ELF at
two load bases. Actual native instructions preserve hit/miss results, reproduce
the14.54m projection, and leave activation clear. Only quaternion accessors
and the collision service are stubbed, so these prove the call contract,
not live map collision accuracy. Focused controller, tactic, escape and
retirement regressions also pass, including the captured lower-floor defect,
whole-ring refusal, bounded reuse, generation races and round expiry.
The reordered placement has not yet been deployed or live-validated; existing
blast clearance remains unchanged. No S-rank or successful escape guarantee
is inferred from these offline checks. Game binaries and decompiler exports
remain in Spark's local library and are not bundled with these tests.
