# RE5 weapon strategy: implementation and remaining verification

The bot reads enemies and weapon slots from BLUS30491 RAM. A front-camera sector is a target candidate;
only the current laser first-hit overlap permits ordinary gunfire. A ray ending before an aligned enemy marks
cover, causing retargeting or movement. Weapon choice never substitutes for this visibility check.

`re5_weapons.py` covers every ID in the verified weapon table. It favors a loaded shotgun for close crowds,
a rifle at distance, a magnum for high-health enemies, and automatic guns for sustained fire. It uses actual
D-pad grid positions, decoded from each inventory record's `+0x1C`, not storage indices or writes to invented equip fields.
The live layout had a rocket in record 0/grid 3 and Hydra in record 1/grid 5; the old record-index assumption
selected the wrong item. A switch now waits for matching in-hand RAM evidence, and failed attempts back off
while combat continues. Its distances are conservative **bot tuning**, not exact
weapon limits. Shotguns may still fire a confirmed distant hit while no better weapon is available.

| Weapons | Operational policy |
|---|---|
| M92F, P8, P226, Samurai Edge, M93R, Px4 | Direct fire; retain a usable current gun unless a materially better quick-slot choice exists. |
| VZ61, SIG 556, MP5, Gatling, AK-74 | Automatic trigger. The Gatling ID is 0x15, correcting the old 0x25 entry. |
| Ithaca, M3, Jail Breaker, Hydra | Close crowd preference; avoid treating spread as permission to fire through cover. |
| S75, PSG-1, SVD | Distance preference; still require measured impact evidence. Scoped targeting needs live validation. |
| M29, Lightning Hawk, M500 | Strong preference against high-health targets and a usable close-range fallback from explosives. |
| Grenade launcher | Six round effects catalogued; autonomous use requires decoded round type, which the current RAM reader does not supply. |
| Rocket launcher | Random loadouts and spawn templates replace it with a random M29, Lightning Hawk or M500. Run5 confirmed an equipped M500 in the former rocket slot on the next spawn. Existing equipped objects are not relabelled; the legacy explosive policy retains its conservative clearance until that transition. |
| Hand, incendiary, flash grenades; proximity mine | Trajectory/placement verification remains open. Prefer a direct-fire gun when reachable. |
| Longbow, flamethrower, knives, stun rod | Explicit separate policies; contact/projectile controllers remain open instead of pretending a laser is universal. |

All gun/grenade definition entries retain the existing unlimited-ammo and x80 firing-table package. That does
not demonstrate every animation, projectile, or scoped weapon firing at that speed. The new controller holds
the trigger only after it reads back the global rapid-fire timer and the current weapon's zero interval.
Ordinary automatic weapons also start with their correct hold behavior. Hardware/game frame rate limits remain.
Each mod now starts from the current live weapon tables and changes only its own fields. Previously, ammunition
restored original firing intervals and damage could restore original firing speeds. Saved originals still govern
scaling and restoration; combined-mod regression tests cover repeated application and independent removal.

## Live longbow requests (2026-10-25)

The live longbow control is separate from **Next-round weapon**. It requests a
bow during the existing round, using the game's native pickup constructor and
ordinary inventory/equip controls. It requires this exact PS3 build, a current
solo bot, a free inventory grid, and a safely reachable ownerless ammo pickup.
It keeps existing carried weapons. It is not a general arbitrary-item grant or
an instantaneous replacement of every inventory slot.

The source conversion changes only the validated pickup's serialized item and
quantity. Native `9D417C/9D693C -> 9D6520 -> 151540` creates the item/weapon;
the longbow registry key is `0x07010F00`, with weapon vtable `0x016289F8`.
The controller then uses the real D-pad grid or inventory menu. It never
relabels a carried gun, replaces its owner pointer, or asserts that a saved
request is an equipped weapon. Completion needs fresh native bow class,
player-owner and in-hand readback. Rendered appearance and actual arrow cadence
still require live observation. Other live weapon IDs remain unsupported.

The separate next-round override now covers all three verified preset banks,
including original Mercenaries, and survives the randomizer's stock-loadout
choice. Death rotation waits for the actual input-ready Continue dialog and
reads its Yes/No selection; it confirms only observed No. Sending Right during
the death animation no longer counts as selecting No.

During the active-session investigation, the RE5 process remained alive but
its native round and HUD clocks stopped near 88.6 seconds. The bot reported a
lost/stalled round and stopped. No live bow source conversion was applied to
that stalled process. Static constructor signatures and synthetic tests do not
establish successful live equip or hyperspeed bow playback.

## Research checked 2026-10-21

[Berserker's Reunion guide](https://gamefaqs.gamespot.com/ps3/980166-resident-evil-5-gold-edition/faqs/59792)
distinguishes shotgun close-range damage from rifles' distant utility. It distinguishes launcher explosive/flame
area damage, acid armor damage, electric stun, flash effects against parasites, and nitrogen freeze/stagger.
These qualitative differences inform the policy; character-specific damage values are not assumed universal.

[Berserker's original Mercenaries guide](https://gamefaqs.gamespot.com/ps3/929198-resident-evil-5/faqs/56737)
describes inventory reloading during other animations and reload/gunshot cancellation into an available melee.
The bot preserves real melee and traversal prompts. Inventory cancellation is not yet implemented; with unlimited
ammo it offers less immediate benefit than keeping targets acquired. Ladder/vault invulnerability is contextual,
not evidence that standing, aiming, healing, or all animations are invulnerable.

The [speedrunning guide index](https://www.speedrun.com/re5steam/guides) and
[BlueRunsFast's boosting explanation](https://www.speedrun.com/re5steam/guides/r3oyo) were also checked.
The documented boost depends on online co-op latency, so it does not apply to this solo RPCS3 round. Campaign
boss skips and PC-version tricks require separate applicability checks. None are represented as verified PS3 hooks.

## Navigation and regression coverage

Routes use the game's RAM navigation mesh, including its directed crossings. Floor lookup now follows sloped
triangles at the player's position, and one-way drops remain reachable only in their recorded direction. A known
unreachable route is skipped; it does not become a straight run through a wall. Ladder, ledge, and vault actions
still require the game's actual traversal prompt. A crossing is learned as blocked only after a continuous,
aligned, stationary attempt; turning, movement, a prompt, or an interruption longer than 1 s clears that timeout. Saved
crossing exclusions are keyed by mesh geometry. Positive learning also records visited triangles, consecutive
plausible directed crossings and route arrivals/failures, with bounded storage and geometry invalidation. It
does not invent connections from skipped frames or treat unclassified ladder transitions as verified crossings.

Nearby threats and confirmed laser overlaps can interrupt travel, while distant unsighted candidates leave the
bonus route intact. A too-close attacker allows a 0.25 s retreat, then reserves 1 s for acquisition before another
automatic retreat. Bonus collection preserves close-range square presses and real traversal prompts.

`test_re5_nav.py` covers slopes, directed drops, and geometry-specific learning. `test_re5_mercs.py` covers traversal
prompts, crossing timeout resets, unreachable-route handling, bonus-route priority, bounded close-enemy retreat,
and death/restart accounting. `test_re5_combat.py` covers first-hit firing evidence, observation during prompts and
travel, and pending hits on the final death frame. `test_re5_health.py` covers opt-in refill, respawns, dead/invalid
players, pointer changes, wrong builds, failed readback, and restoring health limits. These tests establish the
controller's decisions and accounting; live traversal and combat outcomes still require observation.

## Health and evidence

The per-snapshot guard resolves the current player, validates the build and signed health values, raises living
health to 30,000, and verifies the write. It follows respawns and can restore its change. The first bounded live
run held 30,000 health with eight refills, but fired zero shots while the bad inventory mapping repeatedly tried
to change weapons. That run failed combat acceptance.

Ghidra analysis subsequently identified the persistent Muteki setter and incoming-hit collision helper; three
exact code signatures were matched against the running game. The opt-in health guard now sets only the verified
player flag bits and disables validated type-1 incoming-hit collision nodes. Every write rechecks the current
living player and list ownership; originals are restored conservatively. Signature/layout failures explicitly
fall back to health maintenance. This implementation still requires live evidence of protection from stagger;
it does not establish protection from every scripted death or grab. Live acceptance requires actual kill progress, health readback, no repeated cover fire,
successful traversal and bonuses, and completed-round results; unit tests alone do not establish dominance.

The third bounded run (16:30:40-16:33:14 UTC) confirmed Muteki readback with 13 current incoming-hit nodes.
All sampled HP values stayed at 30,000. It switched the actual in-hand rocket to Hydra, recorded 26 shot events
and 23 associated hits, reached 24 kills and collected two time bonuses. Navigation recorded 92 visited triangles
and 136 observed crossings. The last active telemetry score was 8,050; the later RAM tally reached 8,420 after
the clock expired. This remains D-rank territory, not the requested winning performance. Shot-event sampling
does not establish an 80-shots-per-second rate. Labelled real frames are in
[the run evidence](evidence/re5-2026-10-21/README.md).

The fifth bounded run completed two rounds with terminal RAM scores of 6,840 and 6,950, and 21 and 20 kills.
Observed shot/hit counts were 29/19 and 30/19. Health remained 30,000 after setup in both rounds, and the second
spawn confirmed an equipped M500 with unlimited ammo in the former rocket slot. These are still D-rank results.
The subsequent fine-aim fix separates the horizontal and vertical pulse counters: their shared toggle could
starve vertical corrections when both axes needed small adjustments. Four regressions reproduced that defect;
all 102 focused combat/Mercenaries/engine tests passed after the fix. Live improvement is not yet established.

## QTE input decoding

The previous decoder misread `sActionButton+0x34`, an active-array count, as prompt-visibility flags. The decoder
now validates the two selected first-player display units, their active button objects, immutable input-mask
table, code signatures and raw-controller routing. Modes 1/3/4/5 emit fast rising-edge face/shoulder chords;
mode 2 releases held inputs. Mode 6 alternates stick edges, mode 7 maintains an adjacent eight-way rotation
without neutral gaps, and modes 8/9 hold the verified Y/X axis. Every path retains the selected-request and
signature guards. The native parser explicitly remaps shoulder masks; PS3 bit order is not assumed.

Live Circle Resuscitate evidence is HP 1, a positive dying timer and the selected recovery button at player
`+0x22DC`. This request suppresses health refill until the game's recovery callback finishes. HP 0 and the
terminal death action do not imply a recoverable prompt. A bounded 21-press probe increased the recovery timer
but did not yet prove full revival. Recovery ownership and the running timer also suppress health writes while
the prompt is briefly hidden; only a displayed, validated request authorizes button presses. All verified
input-handler modes are implemented; complete live acceptance of each type remains outstanding. The focused
RE5/engine suite passed 163 tests after the hidden-recovery guards.

Ghidra firing analysis also confirmed that the x80 timer is not a throughput measurement. The fire action has
animation/update gates, and type-0 weapons (including magnums) follow a different branch from automatic guns.
The successful firing path accepts held input; only the dry-fire branch has the identified previous-input edge
check. No unverified weapon-type rewrite or animation flag patch is enabled.

Further Ghidra analysis identified the motion-layer playback rate at player `+0x324`, `+0x404` and `+0x4E4`.
The setter stores the rate and the update loop multiplies frame advance by it; magnum firing setup selects
motion IDs `0x51D`, `0x51E`, `0x51C` at rate1.0. This is a candidate for a narrowly guarded firing-only change,
not a demonstrated shot-rate improvement. The normal60fps animation samples do not establish animation
completion as the sole cadence limit: the outer controller can re-enter fire before completion.

The separate review branch implements that candidate with an 8x ceiling. It verifies exact code signatures,
current living player, FIRE action, inventory weapon, all three motion IDs and expected playback values before
individual four-byte writes. Process PID/start time/save-state generation are rechecked at the writer. Owned
values are restored only while the same observed animation context remains; observed resets discard ownership.
No animation generation counter is known, so an entire unobserved reuse between reads cannot be excluded.
The normal QTE path disables this maintenance and retains input priority.

Two bounded read-only observations, lasting60 and180seconds, matched all six code signatures but did not catch
magnum FIRE. Two rocket FIRE samples shared those motion IDs at rate1.0: the separate magnum inventory guard
is essential. No animation-rate writes or live throughput trial have occurred. This change remains separate
from the fine-aim fix in PR #795 and must not be presented as deployed or proven to increase kills.
