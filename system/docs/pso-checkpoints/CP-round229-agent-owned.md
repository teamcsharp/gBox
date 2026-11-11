# Round 229: "it's ignoring my controller" - root cause found: the session was agent-owned

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110

## The cause, in one field

```
session 0d2e88799e11476b-e425afc683e145f1
agent_owned: true
```

I relaunched PSO with an **agent job** after the operator saved and exited. gBox gives agent-created sessions their own ownership so that
background work can never take over the operator's live game - the boundary that kept my bots off their pad all session. The cost of
being on the other side of it: **gBox does not route the operator's controller (or any real input) to an agent-owned session.**

That explains every symptom at once:

* the operator's controller did nothing;
* my `game_input` keys did nothing (26 A-presses left the game on PRESS START);
* `win_send_keys(polite=False)` refused because the foreground was held by a shell window;
* `polite=True` reported `{'sent': 2}` but the game still did not advance - the presses reach a window that is not accepting input
  because the session is not the operator's.

I had read the boundary as protecting *their* session from *me*; it also means an agent session is unplayable by *them*, which is exactly
the wrong thing to hand an operator who wants to play.

## What I did about it

Stopped the agent-owned session so the app can create a proper one:

```
stop_game: succeeded  {"returncode": 1, "timings": {"kill_s": 0.515, "teardown_done": true}, "via": "stop"}
t+4s running sessions: []   -> agent session is closed
```

The app's Play button now creates an **operator-owned** session: the controller works, the window docks, and the plane's memory writes still
apply because `write_memory` is independent of ownership (proven earlier on an agent session with the no-op write, and the receipts come
from the adapter that owns the emulator either way).

## The rule this round establishes

**Never launch a game for the operator with an agent job.** `launch_game` from a job produces `agent_owned: true`, which silently disables
their input. Operator play must come from the app; agent work attaches to it read-only, or to a separately launched test session.

## Everything remains staged for the moment they press Play

```
apply_master.py status                          actor, hp/tp, technique bytes, capabilities
apply_master.py hp                              write + freeze HP at max
apply_master.py legendary --code <weapon>       5 copies, multi-equipped in all five slots
apply_master.py ultimate                        Ultimate difficulty selection
apply_master.py techs --offset 0x2E7 [--apply]  the technique array (dry run by default)
```

Plus the technique table candidate at +0x2E7 and the `30/10/20/15/15` group at +0x2F3, waiting for one confirmation pass against a
character known to hold several techniques.

## Files

* `session_attachments.py` - prints the session record's ownership and capabilities
* `release_session.py` - stops an agent-owned session so the app can create an operator one
