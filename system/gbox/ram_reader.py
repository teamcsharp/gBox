"""Live RAM readers: the quickest way to a session's memory that never holds the game, with a budget.

The RAM inspector (gbox/ram_inspector.py) and bots read through one of these:

  * ShmReader: Dolphin on Linux (the Spark's flatpak): the shared-memory MEM1 / MEM2 views of the session's own Dolphin,
    read-only through /proc/<pid>/mem (gbox.ram_dump.ShmRam): no halt, a whole table per read.
  * AdapterReader: the session's adapter in this process: Windows Dolphin's process memory (DolphinProcMem, no halt),
    RetroArch's network commands (~1 MiB/s), or a GDB stub that halts the emulated CPU while it answers (reads are
    batched under one halt, in small pieces with play in between).
  * RpcReader: a session on another PC: its worker answers read_ranges over the session channel (POST
    /api/sessions/{sid}/rpc, one round trip per batch); an older worker that does not know read_ranges is read with
    read_memory, one range per request.

Every reader has a Budget (bytes and calls per second, by how it reads: a GDB stub gets far less than shared memory);
a read that would overspend waits up to `wait` seconds and then raises Throttled, so the inspector serves its last
values instead of piling requests on the game. read_ranges (the worker side of RpcReader) is serve().
"""
from __future__ import annotations

import base64
import platform
import threading
import time

from . import ram_map

MAX_RANGES, MAX_RANGE, MAX_TOTAL = 512, 1 << 20, 2 << 20     # one read_ranges request
# per reader kind: bytes/s, calls/s, the most bytes per call (per CPU halt for "gdb"), the pause between halted pieces
KINDS = {"shm": {"rate": 256 << 20, "calls": 400, "piece": 32 << 20, "gap_s": 0.0, "coalesce": 4096},
         "procmem": {"rate": 64 << 20, "calls": 200, "piece": 4 << 20, "gap_s": 0.0, "coalesce": 4096},
         "adapter": {"rate": 1 << 20, "calls": 40, "piece": 256 << 10, "gap_s": 0.0, "coalesce": 512},
         "gdb": {"rate": 256 << 10, "calls": 20, "piece": 64 << 10, "gap_s": 0.03, "coalesce": 256},
         "rpc": {"rate": 2 << 20, "calls": 30, "piece": 1 << 20, "gap_s": 0.0, "coalesce": 256}}
# an RpcReader's budget by the way the worker reads (its answer says)
RPC_RATE = {"shm": 4 << 20, "procmem": 4 << 20, "adapter": 512 << 10, "gdb": 128 << 10}


class Throttled(RuntimeError):
    """The reader's budget is spent for now: serve what was read last."""


class Budget:
    """Token buckets for bytes and calls, refilled continuously, holding at most `burst_s` seconds' worth."""

    def __init__(self, rate: float, calls: float, burst_s: float = 1.0, clock=time.monotonic, sleep=time.sleep):
        self.rate, self.calls, self.burst_s, self.clock, self.sleep = float(rate), float(calls), burst_s, clock, sleep
        self.bytes_left, self.calls_left, self.at = self.rate * burst_s, self.calls * burst_s, clock()
        self.lock = threading.Lock()
        self.spent = self.throttled = 0

    def _refill(self):
        now = self.clock()
        dt, self.at = max(0.0, now - self.at), now
        self.bytes_left = min(self.rate * self.burst_s, self.bytes_left + dt * self.rate)
        self.calls_left = min(self.calls * self.burst_s, self.calls_left + dt * self.calls)

    def take(self, n: int, wait: float = 0.0) -> None:
        """Spend n bytes and one call, waiting up to `wait` s for them; Throttled when that is not enough."""
        n = min(int(n), int(self.rate * self.burst_s))      # a piece larger than the bucket waits for a full one
        deadline = self.clock() + max(0.0, wait)
        while True:
            with self.lock:
                self._refill()
                if self.bytes_left >= n and self.calls_left >= 1:
                    self.bytes_left -= n
                    self.calls_left -= 1
                    self.spent += n
                    return
                need = max((n - self.bytes_left) / self.rate if self.rate else 1.0,
                           (1 - self.calls_left) / self.calls if self.calls else 1.0)
            if self.clock() + need > deadline:
                self.throttled += 1
                raise Throttled(f"RAM read budget spent ({self.rate / 1024:.0f} KiB/s, {self.calls:.0f} reads/s)")
            self.sleep(min(need, 0.25))

    def describe(self) -> dict:
        return {"bytes_per_s": int(self.rate), "reads_per_s": self.calls, "spent": self.spent, "throttled": self.throttled}


class Reader:
    """read(addr, n) / read_many([(addr, n)]) -> [bytes | Exception] within the budget; snapshot() for big regions."""
    kind = "adapter"

    def __init__(self, kind: str | None = None, clock=time.monotonic, sleep=time.sleep):
        self.kind = kind or self.kind
        k = KINDS[self.kind]
        self.budget = Budget(k["rate"], k["calls"], clock=clock, sleep=sleep)
        self.piece, self.gap_s, self.coalesce_gap = k["piece"], k["gap_s"], k["coalesce"]
        self.max_block = min(self.piece, ram_map.MAX_BLOCK)
        self.sleep = sleep
        self.lock = threading.Lock()

    # subclasses: one batch of ranges, each within self.piece bytes in all -> [bytes | Exception]
    def _many(self, ranges: list[tuple[int, int]]) -> list:
        raise NotImplementedError

    def read_many(self, ranges, wait: float = 1.0) -> list:
        """Each (addr, n) -> bytes, or the exception that range raised. Batches of at most `piece` bytes (a longer
        range is read in pieces and joined), each taking its share of the budget (Throttled when the budget is not
        there within `wait`)."""
        ranges = [(int(a), int(n)) for a, n in ranges]
        pieces = [(i, a + o, min(self.piece, n - o)) for i, (a, n) in enumerate(ranges) for o in range(0, max(n, 1), self.piece)]
        got_p: list = [None] * len(pieces)
        batch, size = [], 0
        batches = []
        for j, (_, _, n) in enumerate(pieces):
            if batch and (size + n > self.piece or len(batch) >= MAX_RANGES):
                batches.append(batch)
                batch, size = [], 0
            batch.append(j)
            size += n
        if batch:
            batches.append(batch)
        for k, b in enumerate(batches):
            self.budget.take(sum(pieces[j][2] for j in b), wait)
            if k and self.gap_s:
                self.sleep(self.gap_s)                   # a halted CPU runs again between pieces
            with self.lock:
                got = self._many([(pieces[j][1], pieces[j][2]) for j in b])
            for j, d in zip(b, got):
                got_p[j] = d
        out: list = [b""] * len(ranges)
        for (i, _, _), d in zip(pieces, got_p):
            if isinstance(out[i], Exception):
                continue
            out[i] = d if isinstance(d, Exception) else out[i] + bytes(d)
        return out

    def read(self, addr: int, n: int, wait: float = 1.0) -> bytes:
        data = self.read_many([(addr, n)], wait)[0]
        if isinstance(data, Exception):
            raise data
        if len(data) < n:
            raise ValueError(f"short read at {addr:#x}: {len(data)} of {n} bytes")
        return data

    def snapshot(self, base: int, size: int, wait: float = 30.0, stop=None) -> tuple[bytes, str | None]:
        """A region in pieces (a background read may wait for its budget): (bytes read, error that stopped it)."""
        out = bytearray()
        while len(out) < size:
            if stop is not None and stop():
                return bytes(out), "stopped"
            n = min(self.piece, size - len(out))
            try:
                got = self.read_many([(base + len(out), n)], wait)[0]
            except Throttled as e:
                return bytes(out), str(e)
            if isinstance(got, Exception):
                return bytes(out), f"{type(got).__name__}: {got}"[:300]
            out += got[:n]
            if len(got) < n:
                return bytes(out), f"short read at {base + len(out):#x}"
        return bytes(out), None

    def describe(self) -> dict:
        return {"kind": self.kind, **self.budget.describe()}

    def close(self):
        pass


class ShmReader(Reader):
    """Dolphin's shared RAM views (Linux), read-only: gbox.ram_dump.ShmRam."""
    kind = "shm"

    def __init__(self, shm, **kw):
        super().__init__(**kw)
        self.shm = shm

    def _many(self, ranges):
        out = []
        for a, n in ranges:
            try:
                d = self.shm.read(a, n)
                out.append(d if len(d) == n else ValueError(f"short read at {a:#x}"))
            except (OSError, ValueError) as e:
                out.append(e)
        return out

    def describe(self) -> dict:
        return {**super().describe(), "pid": self.shm.pid, "how": f"Dolphin shared memory (/proc/{self.shm.pid}/mem, read-only, no halt)"}

    def close(self):
        self.shm.close()


def _adapter_kind(ad) -> str:
    if getattr(ad, "name", "") == "shadps4":
        return "procmem"
    dbg = type(getattr(ad, "dbg", None)).__name__
    if dbg == "GdbDebugger":
        return "gdb"
    if dbg in ("DolphinProcMem", "XeniaProcMem"):
        return "procmem"
    return "adapter"


class AdapterReader(Reader):
    """The session's adapter in this process. A GDB stub's batch is read under one halt (dbg.paused())."""

    def __init__(self, ad, **kw):
        super().__init__(_adapter_kind(ad), **kw)
        self.ad = ad

    def _many(self, ranges):
        import contextlib
        dbg = getattr(self.ad, "dbg", None)
        hold = dbg.paused() if self.kind == "gdb" and hasattr(dbg, "paused") else contextlib.nullcontext()
        out = []
        with hold:
            for a, n in ranges:
                try:
                    d = bytes(self.ad.read_memory(a, n))
                    out.append(d if len(d) >= n else ValueError(f"short read at {a:#x}"))
                except Exception as e:                   # noqa: BLE001 - unmapped / emulator busy: that range fails
                    out.append(e)
        return out

    def describe(self) -> dict:
        how = {"gdb": "the emulator's GDB stub (halts the CPU while it reads: small pieces)",
               "procmem": "the emulator's process memory (no halt)", "adapter": "the emulator's memory commands"}[self.kind]
        return {**super().describe(), "how": how, "emulator": getattr(self.ad, "name", "")}


class RpcReader(Reader):
    """A session on another PC, through its worker: read_ranges (one round trip per batch), else read_memory. A worker
    that does not answer in wait_s is left alone for QUIET_S (its reads fail at once: the last values are served)."""
    kind = "rpc"
    QUIET_S = 5.0

    def __init__(self, sid: str, rpc, wait_s: float = 4.0, clock=time.monotonic, **kw):
        super().__init__(clock=clock, **kw)
        self.sid, self.rpc, self.wait_s, self.clock = sid, rpc, wait_s, clock
        self.ranges_op = True                          # False once the worker says it does not know read_ranges
        self.source = None
        self.quiet_until = 0.0

    def _call(self, op: str, args: dict):
        if self.clock() < self.quiet_until:
            raise TimeoutError("the session's worker did not answer: trying again in a moment")
        try:
            return self.rpc(self.sid, op, args, self.wait_s)
        except TimeoutError:
            self.quiet_until = self.clock() + self.QUIET_S
            raise

    def _many(self, ranges):
        if self.ranges_op:
            try:
                res = self._call("read_ranges", {"ranges": [[a, n] for a, n in ranges]})
            except Exception as e:                       # noqa: BLE001 - an old worker: read_memory per range
                if "not allowed" not in str(e):
                    return [e] * len(ranges)
                self.ranges_op = False
            else:
                self._adapt(res.get("source"))
                return [base64.b64decode(d) if d is not None else
                        RuntimeError((res.get("errors") or [None] * len(ranges))[i] or "unreadable")
                        for i, d in enumerate(res.get("data") or [None] * len(ranges))]
        out = []
        for a, n in ranges:
            try:
                out.append(b"".join(bytes.fromhex(self._call("read_memory", {"address": a + o, "length": min(MAX_RANGE, n - o)}))
                                    for o in range(0, n, MAX_RANGE)))
            except Exception as e:                       # noqa: BLE001
                out.append(e)
        return out

    def _adapt(self, source):
        if source and source != self.source:
            self.source = source
            rate = RPC_RATE.get(source)
            if rate:
                self.budget.rate = float(rate)
                self.budget.bytes_left = min(self.budget.bytes_left, rate * self.budget.burst_s)

    def describe(self) -> dict:
        return {**super().describe(), "how": "the session's worker over its channel" +
                (f" ({self.source})" if self.source else "") + ("" if self.ranges_op else ", one read_memory per range (older worker)")}


# --- choosing a reader --------------------------------------------------------------------------------------------------
def shm_for_pid(pid: int):
    """Dolphin's shared RAM views under this pid (Linux), read-only, or None."""
    from .ram_dump import ShmRam
    try:
        return ShmRam.find_pid(int(pid))
    except (OSError, ValueError):
        return None


def for_adapter(ad, g: dict | None = None, **kw) -> Reader:
    """The quickest reader for an adapter in this process: Dolphin's shared views on Linux, else the adapter itself.
    Bots: ram_map.load(game).read(ram_reader.for_adapter(ad))."""
    from .ram_dump import ShmRam
    shm = ShmRam.find(ad)
    return ShmReader(shm, **kw) if shm is not None else AdapterReader(ad, **kw)


def for_session(sid: str, session: dict | None = None, rpc=None, **kw) -> Reader | None:
    """On the control plane: the session's adapter when its worker runs in this process (the Spark's serve --worker),
    Dolphin's shared views when it runs on this host, else its worker over the session channel (rpc), else None."""
    try:
        from .tools import SESSIONS
        hit = SESSIONS.get(sid)
    except Exception:                                    # noqa: BLE001 - a control plane without the worker tools
        hit = None
    if hit:
        return for_adapter(hit[0], hit[1], **kw)
    det = (session or {}).get("detail") or {}
    if det.get("pid") and det.get("worker_name") == platform.node() and str(session.get("adapter")) == "dolphin":
        shm = shm_for_pid(det["pid"])
        if shm is not None:
            return ShmReader(shm, **kw)
    return RpcReader(sid, rpc, **kw) if rpc is not None else None


# --- the worker side of read_ranges ---------------------------------------------------------------------------------------
_LOCAL: dict[str, tuple[object, Reader]] = {}
_LOCAL_LOCK = threading.Lock()


def local(sid: str, ad) -> Reader:
    """This worker's reader for a session (kept while the emulator process stays the same)."""
    key = getattr(getattr(ad, "proc", None), "pid", None) or id(ad)
    with _LOCAL_LOCK:
        try:                                             # readers of sessions that ended (an fd each) go
            from .tools import SESSIONS
            for other in [k for k in _LOCAL if k != sid and k not in SESSIONS]:
                _LOCAL.pop(other)[1].close()
        except ImportError:
            pass
        hit = _LOCAL.get(sid)
        if hit and hit[0] == key:
            return hit[1]
        if hit:
            hit[1].close()
        r = for_adapter(ad)
        _LOCAL[sid] = (key, r)
        return r


def forget(sid: str) -> None:
    with _LOCAL_LOCK:
        hit = _LOCAL.pop(sid, None)
    if hit:
        hit[1].close()


def serve(sid: str, ad, args: dict) -> dict:
    """rpc op read_ranges {ranges: [[addr, n], ...]} -> {data: [base64 | null], errors, source, read_s}: up to 512
    ranges and 2 MiB per request, read the quickest way this worker has (one CPU halt per batch on a GDB stub)."""
    ranges = [(int(a), int(n)) for a, n in (args.get("ranges") or [])]
    if not ranges or len(ranges) > MAX_RANGES:
        raise ValueError(f"read_ranges takes 1..{MAX_RANGES} ranges")
    if any(not 0 < n <= MAX_RANGE for _, n in ranges) or sum(n for _, n in ranges) > MAX_TOTAL:
        raise ValueError(f"read_ranges reads at most {MAX_RANGE >> 10} KiB per range, {MAX_TOTAL >> 20} MiB per request")
    r = local(sid, ad)
    t0 = time.monotonic()
    got = r.read_many(ranges, wait=2.0)
    return {"data": [base64.b64encode(d).decode() if isinstance(d, (bytes, bytearray)) else None for d in got],
            "errors": [None if isinstance(d, (bytes, bytearray)) else f"{type(d).__name__}: {d}"[:200] for d in got],
            "source": r.kind, "read_s": round(time.monotonic() - t0, 4)}
