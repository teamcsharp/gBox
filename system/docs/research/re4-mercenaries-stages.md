# RE4 Mercenaries — stage layouts the bot needs, and the mesh gap that blocks them

Researched 2026-11-12 (the operator: "make sure to do online research for each and every one of these
levels and how they're supposed to be played ... so they can run around it, like instead of running
facing into walls like they're doing right now").

## Castle (r402) — why the bot runs facing walls

The stage is **multi-floor**:

* from the round's start you run **down the stairs to the left** and raise the cannon by knifing the
  hanging counterweight (the cannon then kills the Garradors)
* the **second floor** is where the catapults are, destroyed by shooting the explosive barrel beside
  each one (they otherwise steal kills and can kill you)
* the standing camp spots are the **Cannon area**, the **Castle Gate** and the starting area
* green orbs (time) are worth taking first; yellow orbs are a Mayhem charge better saved
* elites appear by kill count: 20 Zealot (staff), 50 Garrador, 70 two Zealots, 100 Armored Garrador,
  130 Garrador + Armored Garrador

Sources: <https://game8.co/games/Resident-Evil-4-Remake/archives/409535>,
<https://www.thegamer.com/resident-evil-4-remake-mercenaries-complete-guide-castle-map/>,
<https://gamewith.net/resident-evil-4-remake/article/show/38638>

**The gap, measured in our own data:**

| stage | points | tris | crossings | ladders | vertical extent |
|---|---|---|---|---|---|
| Village r400 | 7279 | 11520 | **176** | 1 | 9.0 m |
| Castle r402 | 2632 | 4093 | **0** | **0** | **11.2 m** |
| Base r403 | 6816 | 10590 | 18 | 10 | 16.7 m |
| Waterworld r404 | 4170 | 6765 | 16 | 8 | 12.0 m |

Castle is the tallest stage after Base and the **only one with no crossings and no ladders at all**,
while `re4_nav` measured it as a single connected floor piece. The bot therefore has no mapped route
between levels: it cannot take the stairs down to the cannon or reach the second floor's catapults, so
on a lost Castle round (`outcome=lost kills=0`) it circled the ground floor and never found the fight.

Every other stage carries ladders or crossings, which is why Village and Base allow real traversal.

**What a fix needs** — one of:

1. re-extract the Castle mesh with its stair/level crossings (the `crossings` rows `re4_nav.from_json`
   already reads), the way r403/r404 carry theirs; or
2. a learned link table: record the (floor -> floor) steps the bot actually walks and persist them per
   stage, so confidence grows run over run as the operator asked ("learning these levels so that each
   and every run they run through these levels with more confidence, knowing their way around").

Doors/gates need the same treatment: the Castle Gate is a named camp spot, and nothing in the mesh or
the room map marks a door the bot can open.
