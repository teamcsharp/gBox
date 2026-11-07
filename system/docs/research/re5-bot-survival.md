
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
## Root cause of the missed bonuses: the knife needs 90 cm and the bot never gets there

Per-round counters, straight from `mercs/curriculum/010018100CD46000/rounds.sqlite`:

```
seen  taken  time_gained  bonus_runs  knife_swings  detours  prompts_seen_bonus
   8      0            0          12             0       27                   0
  11      0            0           3             0        8                   0
   8      1         59.6           6             0        8                   1     <- the one that worked
  10      0            0           2             0        6                   0
```

Three things fall out of it:

1. **`knife_swings` is zero in every round.** The swing is a 0.35 s toggle inside `if d <= KNIFE_R` - and `KNIFE_R = 90.0` cm. The bot runs to statues (`bonus_runs` 2-12) and detours around them (`detours` 6-27) but never enters that radius, so the swing code never executes once.
2. **The only take came from a prompt** (`prompts_seen_bonus: 1`, `time_gained: 59.6`), not from the knife. The prompt path works when it happens - it just happens once in four rounds.
3. `bonus_detours` rising with `bonus_runs` is the bot circling a statue it cannot get closer to, presumably because the statue is a solid actor and the walk presses into its collision at about a metre.

So the bonus phase is not idle or disabled - it is **arriving and stopping one step outside its own reach threshold**, then detouring until the block timer gives up.

## What to change, in order of confidence

1. **Raise the reach threshold** (`KNIFE_R`) to about 150-180 cm so the swing fires from where the bot actually stands. It is one number, the swing happens on a toggle, and a miss costs nothing but a swing; the current 90 cm is inside the statue's own footprint.
2. **Let the approach walk in for the prompt regardless of `prompt_read`** - today the "into it for its prompt" branch is gated on `snap.get("prompt_read")`, and with the prompt unread the bot never presses into the statue to make the prompt appear (the one success is exactly that prompt).
3. Only then look at level differences (the roof/ledge jump path) and the dead-statue block timer.

(1) is the smallest change that matches all four rounds' numbers, and it is measurable the same way: `knife_swings` should become non-zero and `bonuses_taken` should rise from 0.
## The rotation has completed no round in seven hours

While trying to verify the knife-reach change I read the Notebook directly instead of trusting the learning summary:

```
rounds in the last 1h : 0
rounds in the last 6h : 0
rounds in the last 24h: 99        <- so it did run earlier
newest round age      : 412 min   (~6.9 h)
live session          : started 3.9 min ago, eden, cast-inverted
frame                 : "NOW LOADING..." (a round is loading, mean 4.0)
```

So the MercMode rotation **is** launching games - a session is up right now and a round is loading - but no round has reached a terminal
state that the Notebook saves since about 10:40. Everything the learning gate reports (0.968 deaths/round, 62 rounds/24h, the bonus
faults) is therefore **seven hours stale**, and any change of mine - the crowd hold, the knife reach - has had no completed round to
affect. That also explains why the gate could never judge the 03:31 fix: there was nothing new to judge.

This is the first thing to establish before more bot work, and it is measurable: the scheduler's own logs, and the job state of the
autoplay that runs in each session, will say whether a round is being abandoned (relaunch before the clock ends), whether the bot
is stuck on a menu/prompt, or whether the Notebook writer stopped saving. The frame above at least rules out "the game is not
running".
## The rotation's rounds are not reaching the Notebook - and the same bot does record elsewhere

Every title's round database, with its last write:

```
010018100CD46000  RE5 Switch   rows 1480   last written 413.8 min ago   <- the rotation's title
01002A000CD48000  RE6 Switch   rows 1275   last written 1492.6 min ago
BLUS30491         RE5 PS3      rows  640   last written 474.8 min ago
G4BE08            RE4 GameCube rows  461   last written  43.2 min ago   <- recorded from a manual autoplay run today
```

So the Notebook writer works - RE4 GC wrote a round 43 minutes ago from my own `autoplay op=start` session - while the RE5 Switch
**MercMode rotation** has not written one since about 10:40 this morning, even though the scheduler is demonstrably cycling:

```
last 3 h by tool: launch_game 24, graphics 23, autoplay 22, session_op 21, re5_mods 15, bot_reload 8
a cycle every 5-8 min:  launch -> graphics -> autoplay -> re5_mods -> (session_op) -> launch
live run now: phase "playing", playing_since 2 min ago, mod cast-inverted, session 79aa9ea51f7c4ff5
```

That is the shape of the problem: the rotation relaunches every five to eight minutes, a Mercenaries round needs longer than that to
load and finish, and a round that is stopped mid-play is never a terminal round - so nothing is recorded. The stalemate cut (clock to
5 s after 15 s with no enemies) ends rounds rather than killing sessions, so it is not the suspect; the cycle time is.

The clean test, which is what I would do next: run **RE5 Switch with a plain `autoplay op=start`** (exactly what recorded the RE4 GC
round) and see whether rounds appear. If they do, the fault is in the MercMode cycle - its per-round time budget or its stop/relaunch
path - and not in the bot, the readers or the Notebook.
## The stock game boots in under a minute; the modded rotation hangs at a loading screen

Same title, same node, two runs:

```
mod cast-inverted : "History of RESIDENT EVIL ... NOW LOADING" still there at 9.6 minutes; the frames change (the history text
                    cycles), so the game is alive and stuck in its loader, not frozen
stock (no mod)    : "PRESS ANY BUTTON" within 60 seconds      (evidence/stock-re5-boots.jpg)
```

So the seven dead hours are not the bot, the readers, the Notebook or the scheduler: **a modded launch is not finishing its load**.
The rotation has been relaunching cast-inverted every five to eight minutes, each launch stuck in the loader, so no round could start
- which is exactly the cycle the job history shows.

What is NOT yet established is whether the mod is now bad or the emulator's cached state is: cast-inverted played rounds earlier today
(the modded matches in this session's own evidence), and what changed between then and 10:40 is a long series of launches and abrupt
stops on this PC - mine included. The next test is the same mod after clearing the emulator's shader/pipeline cache, and if it still
hangs, a second known-good mod on the same title.
## It is the build, not the emulator: cast-inverted hangs, majini-shrunk loads

The two modded launches, same title, same node, minutes apart:

```
cast-inverted   dark loader for 4.5 minutes; frames identical from +210 s to +270 s   (stuck)
majini-shrunk   "PRESS ANY BUTTON" by +30 s (mean 23.8 / std 48.9, the same signature as the stock capture), through +120 s
```

And the timing lines up exactly with the dead hours:

```
cast-inverted marker "built": 10:27      rounds stopped: ~10:40      no round since
overlay: 14 files, 322,769,736 bytes - uEm10.arc alone 97,227,287 (the stock arc is ~80 MB, my Sonic build 82 MB)
compare: cast-inverted-check (02:49) 4 files, 61,724,334 bytes
```

So `cast-inverted` was rebuilt at 10:27 into a much larger overlay (fourteen archives, uEm10 at 97 MB) and the game has not finished
loading it since. The emulator is fine - it ran the stock game and another mod in the same minutes.

What I did NOT do: switch the rotation to another build on my own. `cast-inverted-check` is the obvious candidate (smaller, older, built
02:49) but I have not watched it load, and switching the operator's rotation onto an untested build at the end of a round is how a
seven-hour gap turns into a longer one. The next round should launch `cast-inverted-check` once and watch it, then point the rotation at
whichever build loads.
## Rotation state and the Qwen provider

The build that hangs is **generated by the cast-swap feature**, not a stored one: configuring MercMode with `mod: cast-inverted-check`
was ignored and the scheduler rebuilt `cast-inverted` (mod cast-inverted, 322 MB overlay, rebuilt 10:27). `cast-inverted-check`
itself **loads** - it reached "PRESS ANY BUTTON" in 30 s - so the emulator and LayeredFS are fine and the generator produced a bad
build at 10:27.

Settings are now `cast_swap: off`, `skin_swap: off` so the next run is a stock RE5 with no overlay; the round currently playing
started before that change and still carries `mod: cast-inverted`. Newest recorded round: 459 minutes old.

## Qwen

The provider is registered (the GUI shows `qwen-token-plan` green, and `~/.dsh/.credentials.yaml` holds
`refs: QWEN_TOKEN_PLAN_API_KEY`), but this session refuses it:

```
list_subagent_models                     -> only "deepseek-account"
list_subagent_models(provider=qwen-token-plan) -> Error: LLM provider "qwen-token-plan" is not allowed for this Session
```

That is a session/preset provider allowlist, not a missing key or a bad model id. The provider was added while this session was
already running, and the allowlist is fixed for the session's life. To use it, either restart the session (a new one will see the
provider) or add `qwen-token-plan` to the agent preset's allowed providers. Once it is allowed I will put the parallel work on it -
the cast-swap build diagnosis and the RE4 VR archive being the two obvious candidates.
## Rounds are recording again - and the first one corrects me

Stopping the hung (bad-build) session let the scheduler relaunch on the stock baseline (`mod: None`), and the first round in about eight
hours arrived within five minutes:

```
outcome died | score 19,450 | bonuses_seen 11 | bonuses_taken 1 | knife_swings 0 | time_gained 59.8
```

Two things follow.

1. **The measurement pipeline is alive again.** Rounds write to the Notebook, so the learning gate, the death clusters and the bonus
   counters will start reflecting reality within a few rounds instead of describing 10:40.
2. **My knife-reach fix was incomplete.** `KNIFE_R` is 160 cm and `knife_swings` is still 0 with 11 statues seen: the bot is not
   entering the reach branch at all, so the radius was not the (only) gate. The reach branch is only reached when `d <= KNIFE_R`, and
   the one code path that walks *closer* to a statue ("into it for its prompt") is gated on `snap.get("prompt_read")` - a circular
   dependency: the prompt needs proximity, and proximity waits for the prompt. The detour path (every 1.5 s) resets `best_at`, so the
   approach never converges.

**The change to make next** is in the walk path, not the radius: when a statue is within `BONUS_WALK_R` and no prompt is read, face it
and press in (`lup` toward it) instead of detouring - the press is what makes the prompt appear, and the one round that took a bonus did
it through a prompt. That is a small, testable edit at the end of the bonus-approach block, and this time there are fresh rounds to
measure it against.