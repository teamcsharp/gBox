"""One owner of the pad at a time: suspend the bot while the operator presses, resume when they stop.

The "operator is playing - bot standing down" check happens **once per loop iteration**, and an iteration contains a `hold(pad, "up", 0.7)` - 0.7 seconds of pressing. So if the operator presses during
that window, **both sources are injecting at once**, and the same cancellation that made two relays do nothing applies: one side's release wipes the other's press. From the operator's side the
controller "ignored them", intermittently, which is exactly the symptom reported.

Iteration-level cooperation cannot fix that. **Process-level suspension can**: `NtSuspendProcess` freezes the bot where it stands - no further input from it, nothing to cancel - and
`NtResumeProcess` lets it carry on afterwards. No relaunch, no boot, no lost session.

So the relay now:

* on the **first** event of a burst, **suspends the bot** (and logs it);
* on **idle** (`IDLE_RELEASE` seconds with no input), **resumes it**.

That gives exactly one writer to the virtual pad at any moment - the operator while they are playing, the bot the rest of the time - which is the invariant the whole thing needed.
"""
import pathlib
import py_compile

RELAY = pathlib.Path(r"C:\_tools\gBox\.tmp\controller_relay.py")
text = RELAY.read_text(encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("controller_relay compiles BEFORE")

HELPER = '''
PROCESS_SUSPEND_RESUME = 0x0800


def _bot_pids():
    """PIDs of every running `endless.py` - the only processes the relay may suspend."""
    import subprocess

    pids = []
    try:
        out = subprocess.run(["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:                                          # noqa: BLE001
        return pids
    for line in out.splitlines():
        if "endless.py" in line:
            tail = line.strip().rsplit(None, 1)
            if tail and tail[-1].isdigit():
                pids.append(int(tail[-1]))
    return pids


def suspend_bots() -> list:
    """Freeze the bot processes so only the operator is writing to the pad."""
    import ctypes

    ntdll = ctypes.windll.ntdll
    frozen = []
    for pid in _bot_pids():
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SUSPEND_RESUME | 0x0400, False, pid)
        if handle:
            if ntdll.NtSuspendProcess(handle) == 0:
                frozen.append((pid, handle))
            else:
                ctypes.windll.kernel32.CloseHandle(handle)
    return frozen


def resume_bots(frozen) -> None:
    import ctypes

    ntdll = ctypes.windll.ntdll
    for pid, handle in frozen:
        ntdll.NtResumeProcess(handle)
        ctypes.windll.kernel32.CloseHandle(handle)


'''

if "def suspend_bots(" not in text:
    anchor = "def send(pad, events):"
    if text.count(anchor) != 1:
        raise SystemExit("send anchor count: %d" % text.count(anchor))
    text = text.replace(anchor, HELPER.lstrip("\n") + anchor, 1)
    print("suspend/resume helpers added")

# hold the frozen list and use it
old_state = "    held, last_stick, last_activity, last_rebind = set(), (0.0, 0.0), 0.0, 0.0"
new_state = ("    held, last_stick, last_activity, last_rebind = set(), (0.0, 0.0), 0.0, 0.0\n"
             "    frozen = []")
if text.count(old_state) == 1:
    text = text.replace(old_state, new_state, 1)
    print("frozen list declared")

old_send = """        if events:
            last_activity = time.time()"""
new_send = """        if events:
            if not frozen:
                frozen.extend(suspend_bots())          # the operator is playing: freeze the bot so only one writes
                if frozen:
                    print(f"  suspended the bot ({len(frozen)} process(es)) - operator has the pad", flush=True)
            last_activity = time.time()"""
if text.count(old_send) == 1:
    text = text.replace(old_send, new_send, 1)
    print("bot suspension on operator input")

old_idle = """        elif time.time() - last_activity > IDLE_RELEASE:
            if PAUSE_FILE.exists():"""
new_idle = """        elif time.time() - last_activity > IDLE_RELEASE:
            if frozen:
                resume_bots(frozen)
                frozen = []
                print("  operator idle - bot resumed", flush=True)
            if PAUSE_FILE.exists():"""
if text.count(old_idle) == 1:
    text = text.replace(old_idle, new_idle, 1)
    print("bot resumes when the operator stops")

RELAY.write_text(text, encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("controller_relay compiles AFTER")
