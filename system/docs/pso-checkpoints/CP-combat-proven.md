# COMBAT WORKS: an enemy was killed, and the recipe is now in the loop

## The kill

```
enemy d 12.0  aim +2.8  hp 41        <- already damaged, so earlier swings HAD connected
press B, then A  x3
  attack 1: [TObjEneBeast 60, TObjEneBeast 20]
  attack 3: [TObjEneBeast 60]        <- one dead
```

**An enemy died.** After thirty rounds of "attacks do not land", this is the first verified kill, and the reason is now completely understood.

## The three things every earlier attempt was missing

**1. `b` before the swing - and my own bug caused the menu.** A previous diagnostic pressed **START** to "close" a menu. **START *toggles* PSO's pause menu** - so pressing it while the menu was closed *opened* it, and from then on the character could not move and `a` did menu things. The screen captures confirmed it (Item Pack / Customize / Technique / Chat / Status / Options / Quit Game). **`b` cancels it.** The loop now presses `b` immediately before `a`.

**2. The game's own envelope, read out of `pso_coop_combat.py`:**

```
# Owned PMT minimum positive horizontal range is 12; unarmed is 13.
FALLBACK = dict(horizontal=10., vertical=10., horizontal_half_angle=8., vertical_half_angle=20.)

def geometry(player, target, envelope):
    ...
    angle = (desired - player['heading_deg'] + 180) % 360 - 180
```

**~12 units and an 8 degree half-angle.** Every earlier attempt swung at **16 to 45 units** with **100+ degrees** of aim error - outside both bounds, so it could never connect. The loop now checks the aim against the cone and turns in small measured steps before swinging.

**3. A ranged weapon.** The character could not walk closer than **~16.7 units** because the enemy's body blocks it, and 17 > 12, so melee was structurally impossible here. `RED HANDGUN` (`004400`, ATA 46) reaches from that distance and is now part of the arming step.

## What the loop does now

```
[19:07:11] === cycle 1 ===
[19:07:11] arming: walk_through, best weapons, survival
[19:07:13]   walk_through : succeeded
[19:07:14]   give 009d00: succeeded      <- DARK FLOW
[19:07:16]   give 003200: succeeded      <- TSUMIKIRI J-SWORD
[19:07:17]   give 004400: succeeded      <- RED HANDGUN
[19:07:19]   survival : succeeded        <- permanent Scape Doll
[19:07:26] unstick: up freed it (51.4 units) ... (31.1) ... (9.6) ...
```

and its `play()` now attacks only inside the envelope, with `b` before `a`.

## Still rough

The character can still end up **boxed in** - the unstick distances shrank 51 -> 31 -> 9.6 -> 8.0 -> 1.7 units, i.e. each escape left less room, and a second enemy froze at 16.7 units with the aim pinned at -153 degrees (it could not turn, which means a menu was open again, since turning demonstrably works: a `left` press moved the heading 199 -> 226 at 30 fps).

**So the mechanism is proven and the remaining work is robustness**: clear menus *before* deciding the character is stuck, and back away from a body block rather than only turning.
