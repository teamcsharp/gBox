# Round 273: the weapon advisor - the bot now equips for the situation

The operator asked for the bot to be made capable of playing the game properly, with the weapon rules researched. The Ephinea reference gives the
intent behind each type, and the bot now acts on it.

## The rules, as researched

* **Sword / Partisan / Slicer** - wide arcs, for several enemies in front;
* **Saber / Dagger** - fast single-target, for one enemy close in;
* **Handgun / Rifle / Mechgun / Shot** - ranged, and the **only** answer to a flying enemy, which melee cannot reach;
* **Cane / Rod / Wand** - technique weapons, boosting the techniques the bot already casts with B;
* all weapon damage derives from **ATP** regardless of type; multi-target weapons pay for their reach with reduced specials (50%/33%).

## The advisor, unit-tested against six situations

```
three close enemies  -> Sword, Partisan, Slicer        (3 enemies in melee range -> wide weapon)
two close enemies    -> Sword, Partisan, Slicer        (two enemies in range -> wide weapon)
one close enemy      -> Saber, Dagger                  (single enemy -> fast single-target weapon)
one far enemy        -> Handgun, Rifle, Mechgun, Shot  (nearest 30 units away -> ranged weapon)
one flying enemy     -> Handgun, Rifle, Mechgun, Shot  (enemy well above -> ranged; melee cannot reach)
no enemies           -> -                              (nothing to fight)
```

Every case matches the reference, and the flying case is the one that explains a whole evening of failed fights: **melee was being used against
enemies that were out of reach vertically**.

## The arsenal it chooses from

The character holds **every weapon class** - Saber, Sword, Dagger, Partisan, Slicer, Handgun, Rifle, Mechgun, Shot, Rod, Wand - with the **Rifle**
currently equipped. `equip_class` picks the first matching weapon and unequips the previous one, through the plane's item operations, which are not
keyboard input and therefore work even while the game is unfocused.

## Wired into play

Self-play now consults the advisor **when it locks a target**: it reads the situation, logs the reason, and equips accordingly. The live log
confirms the bot running on floor 1 with the advisor in place:

```
17:27:13 === self-play v2 on floor 1, 11 rooms, visited [1, 3, 5, 8]
```

## What this fixes, concretely

1. **Flying and elevated enemies** now draw a ranged weapon instead of a futile melee approach.
2. **Groups** draw a wide weapon instead of a single-target one.
3. **Distant enemies** draw ranged instead of a chase.
4. The advisor is also the natural home for the **confusion** request: the researched tiers are Panic 28% / Riot 44% / Havoc 60% / Chaos 76%, so a
   weapon bearing one of those specials can be selected deliberately once such a weapon is in the inventory.

## State

| item | state |
|---|---|
| weapon rules | researched and encoded |
| advisor | unit-tested on six situations, all correct |
| arsenal | 11 weapon classes available |
| integration | consulted at every target lock |
| game focus | false - combat training waits for it |
