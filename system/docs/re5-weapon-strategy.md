# RE5 weapon strategy: implementation and remaining verification

The bot reads enemies and weapon slots from BLUS30491 RAM. A front-camera sector is a target candidate;
only the current laser first-hit overlap permits ordinary gunfire. A ray ending before an aligned enemy marks
cover, causing retargeting or movement. Weapon choice never substitutes for this visibility check.

`re5_weapons.py` covers every ID in the verified weapon table. It favors a loaded shotgun for close crowds,
a rifle at distance, a magnum for high-health enemies, and automatic guns for sustained fire. It uses actual
D-pad slots, not writes to invented equip fields. Its distances are conservative **bot tuning**, not exact
weapon limits. Shotguns may still fire a confirmed distant hit while no better weapon is available.

| Weapons | Operational policy |
|---|---|
| M92F, P8, P226, Samurai Edge, M93R, Px4 | Direct fire; retain a usable current gun unless a materially better quick-slot choice exists. |
| VZ61, SIG 556, MP5, Gatling, AK-74 | Automatic trigger. The Gatling ID is 0x15, correcting the old 0x25 entry. |
| Ithaca, M3, Jail Breaker, Hydra | Close crowd preference; avoid treating spread as permission to fire through cover. |
| S75, PSG-1, SVD | Distance preference; still require measured impact evidence. Scoped targeting needs live validation. |
| M29, Lightning Hawk, M500 | Strong preference against high-health targets and a usable close-range fallback from explosives. |
| Grenade launcher | Six round effects catalogued; autonomous use requires decoded round type, which the current RAM reader does not supply. |
| Rocket launcher | Confirmed enemy impact plus conservative 7 m self/partner clearance. This is a starting margin, not a measured blast radius. |
| Hand, incendiary, flash grenades; proximity mine | Trajectory/placement verification remains open. Prefer a direct-fire gun when reachable. |
| Longbow, flamethrower, knives, stun rod | Explicit separate policies; contact/projectile controllers remain open instead of pretending a laser is universal. |

All gun/grenade definition entries retain the existing unlimited-ammo and x80 firing-table package. That does
not demonstrate every animation, projectile, or scoped weapon firing at that speed. The new controller holds
the trigger only after it reads back the global rapid-fire timer and the current weapon's zero interval.
Ordinary automatic weapons also start with their correct hold behavior. Hardware/game frame rate limits remain.

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
crossing exclusions are keyed by mesh geometry. This is a mesh plus failed-crossing memory, not a verified record
of successful traversal everywhere.

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
health to 30,000, and verifies the write. It follows respawns and can restore its change. It does **not** prove
immunity to scripted death, grabs, or stagger. Ghidra reflection names containing `Muteki` are research anchors,
not usable offsets. Live acceptance requires actual kill progress, health readback, no repeated cover fire,
successful traversal and bonuses, and completed-round results; unit tests alone do not establish dominance.
