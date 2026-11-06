
## What actually kills the RE5 Switch bot (measured), and where the fix goes

`GET /api/mercs/learning` ? `what_kills_him`, over 62 rounds in 24 h at 0.968 deaths per round:

```
14 deaths  swarmed (4+ within 2 m) with the gun lowered      195 episodes  33,520 HP
11 deaths  aimed away or threat behind while hit              210 episodes  43,408 HP
10 deaths  swarmed (4+ within 2 m) with the gun up             99 episodes  15,382 HP
10 deaths  low health with no tablet or heal                   55 episodes   3,962 HP
 4 deaths  low health with a heal in hand, not used            25 episodes   3,447 HP
 3 deaths  grabbed from the front / behind                     28 episodes   2,900 HP
```

The dominant pattern is clear and it is not the character select: **he is surrounded at close range and dies there** - 34 of the
deaths involve being within 2 m of several enemies - and the "gun down" variant of it is twice the "gun up" one, which says he is
often not even aimed when it happens.

The code already has a handler for *one* close enemy and not for a crowd:

```
BACKOFF_S, BACKOFF_GAP_S = 0.5, 1.5   # one too close in front with the gun down: back off this long, then fight
BACKOFF_CONE = radians(60)            # ... only from one in front (backing up walks into one behind)
```

Under a `reload` motion the bot deliberately does not aim (`self.aim_since = None`, "the gun comes back up by itself"), so the
reload state is one of the ways the gun is down while a crowd closes in.

**The change to make next**, in this order:

1. a **crowd rule**: 3+ live enemies within 2 m triggers a backoff with its own, longer duration, not the single-enemy 0.5 s, and
   it should not require the enemy to be inside the front cone (the cone existed because backing up walks into one behind - with a
   crowd that reasoning no longer holds, so the direction has to be chosen away from the crowd's centroid);
2. a **reload guard**: do not start a reload while 2+ enemies are within ~5 m - finish the crowd first, reload when it clears;
3. only then re-tune the `low health` clusters (HEAL_CRITICAL is already tuned at 0.3 per stage).

Each of these is measurable by the same gate, and the gate needs ~8 rounds (~3 h) per verdict.
## First survival change, shipped as a measured experiment

Implemented in `re5_switch`:

```python
CROWD_HOLD_N, CROWD_HOLD_R = 4, 200.0
...
swarmed = len(crowd) >= CROWD_HOLD_N and crowd and min(flat(e) for e in crowd) <= CROWD_HOLD_R
if CROWD_MOVES and ... and not swarmed:      # the crowd move-out, which drops the gun, is skipped for this crowd
```

The reasoning is in the constant's comment and it is the death data, not taste: the crowd move is what puts the gun down, and
"swarmed with the gun down" was the largest single death cluster (14 deaths, 33,520 HP) with "swarmed with the gun up" second
(10 deaths) - so walking out of a four-strong crowd at 2 m unarmed costs more than standing in it firing. With four on him inside
2 m the bot now keeps the gun up and fires instead of walking out.

Reversible two ways: `CROWD_HOLD_N` above any real crowd turns the rule off, and the learning gate judges the change on the next
8 rounds like any other. `tests/test_re5_switch_cycle.py`, `test_re_switch.py` and `test_re5_switch_brain.py`: 31 passed.

This is the honest status of it: **shipped, not yet proven**. The gate's verdict is ~3 h away, and if the deaths-per-round figure
does not fall, the next lever from the same table is the reload guard (do not start a reload with two enemies inside 5 m).
## The biggest score lever is not survival - it is 8.6 missed time bonuses a round

The learning payload's `round_faults` for RE5 Switch:

```
round:bonus_missed   "time bonus seen, not taken"
rounds 62   marked rounds 60   share_of_rounds 0.968   rate_per_round 8.581
```

In Mercenaries the clock is the score: every time bonus extends the round, so 8.6 missed statues a round dwarfs any survival
tuning. The bot HAS a first phase for exactly this (`BONUS = True`, statues scanned every second, knife swings, a jump-down
context action, a wall governor, and counters `bonuses_seen / bonuses_taken / time_gained / knife_swings / bonus_jumps`), and
the code carries earlier live diagnoses of the same failure - "8 statues seen, none taken: he spawned on the roof and walked at
one 1.6 m below for a minute", and "the damage cluster's 138-missed-per-round fault: locked on one unbreakable statue".

So this fault has been worked before and is still at 96.8% of rounds. What the next attempt needs that the previous ones did not
have is the live counters per round: `bonuses_seen` against `bonuses_taken` says whether the scan sees them and the walking
fails, or whether the phase never runs at all. I could not read those counters this round - the session row carries no stats and
the autoplay job for the running round was not in the job list when I asked - so the first thing to do next is find where a
finished round's counters are kept and read two or three rounds' worth before changing anything.

Also worth recording: deaths_per_round 0.968 is consistent - 58 deaths over 60 rounds.