# The launch lock: why retrying never helps

## The mechanism

`gbox/tools.py` serialises launches deliberately:

```python
_LAUNCH_LOCK = threading.RLock()

def launch_game(inp: LaunchIn, ctx: Ctx):
    """Launch a cataloged game on this node ..."""
    with _LAUNCH_LOCK:
        diag: dict = {}
        _LAUNCH_DIAG.d = diag
        ...
```

Launches are serialised so two games cannot start at once - a sound decision. The consequence, though, is that **the lock is held for the entire launch**,
and a launch that **hangs** holds it **forever**. Every retry then waits on a lock that will never be released, which is exactly the behaviour observed:
the overlay shows the same step forever, pressing launch again changes nothing, and the state is identical whether or not the stale save files are
present.

That also explains why the failure system never fires (round 18): a launch blocked on a lock is **not failing**, it is **waiting**, and nothing in the
classifier counts "waiting forever" as a failure.

## What this means practically

The lock lives in the process running `launch_game` - a `gbox` server process. Two are running:

```
pid 54088  AppData\Local\gbox\venv\...\python.exe -m gbox --config C:\_tools\gBox\system\gbox.toml
pid 50880  AppData\Roaming\uv\python\...\python.exe -m gbox --config C:\_tools\gBox\system\gbox.toml
```

Both started at the same second (11:56:50), so they are a parent/child pair rather than duplicates - but **whichever one ran the stuck launch is holding
that lock**, and nothing else can start a launch through it.

The API ports are owned by other processes again (`18765` by `gbox.desktop_local`, `8765` by the server), so the picture is: an idle API, no active jobs,
and a launch that cannot proceed.

## The action

**Restart gBox.** A restart replaces the server process, and a fresh process has a fresh `_LAUNCH_LOCK`. It also reloads every client change built since
the 19:33 restart, and there is nothing running to lose - no session has existed for eleven rounds.

Then **launch PSO**. If it proceeds, the held lock was the cause and the fix for the future is a **launch timeout**: a launch that has not advanced in N
seconds should release the lock and file a ticket, rather than blocking every attempt after it.

## What is verified on the bot side, unchanged by any of this

33 checks passing that need no emulator - 11 perception, 10 movement, 12 decision - plus the plane's virtual pad verified working on this machine, input
routed through `send_input` instead of the dropped keyboard branch, `boot()` to get from the title into the game, and exits matched with `AREA CLEARED`
logged when the floor changes. One supervisor with a working lock is waiting.

## State

| item | state |
|---|---|
| launch block | **`_LAUNCH_LOCK` held by a stuck launch** |
| retries | **queue behind it forever** |
| stale save states | cleared (round 19) - not the cause |
| fix now | **restart gBox** |
| fix for the future | **a launch timeout that releases the lock and files a ticket** |
| bot | ready and verified |
