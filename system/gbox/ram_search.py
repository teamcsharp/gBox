"""RAM search for the inspector: Cheat Engine style filters plus label correlation, vectorized and bounded in memory.

A Search covers one region (GameCube MEM1: 24 MiB) at one width (u8 / u16 / u32, s8 / s16 / s32, f32; aligned to the
width, as compilers place them). Every sample is the region's bytes now (or, once few candidates are left, just the
ranges around them: candidate_ranges()), and each sample can:

  * filter against the previous sample (Cheat Engine): changed / unchanged / increased / decreased, or test the value:
    equals / not_equals / range;
  * carry a label, "on" or "off" (the event is happening / is not: a prompt on screen, a door opening, a QTE): a
    candidate survives only while the values it had in "on" samples never equal a value it had in "off" samples. The
    labels come from the operator's buttons or a labeler (the screen-prompt watcher, a RAM-map field). Each candidate
    keeps the values it took per label, so value tables fall out: 0x80F3A2C1 on {3, 5} off {0} is "3 = TAKE,
    5 = JUMP OVER" once the prompts are named.
  * tolerance: a labeler is sometimes wrong at the edges (the stream's frame lags the RAM a little; a prompt the bot
    answers at once is gone before the sample). With tolerance t a candidate survives while its values could be made
    disjoint by relabeling at most t samples: cost = sum over the values seen in both labels of min(on count, off
    count). Candidates list the cleanest first (lowest cost, fewest values).

Memory: while many candidates are left (dense) the candidates are a bool mask over the region and the labeled samples
are kept whole (each region-sized) so the correlation stays exact; once at most SPARSE_AT are left (one "on" and one
"off" sample usually leave a few hundred thousand of 24 million: the rest of RAM does not change with the event) the
search keeps only their indexes, last values and up to K distinct values per label (a state takes few values; an
address that takes more than K in one label is a counter or a timer, not the event, and is dropped). max_bytes bounds
it all: past it the oldest labeled sample of the busier label is folded away (the correlation then stays exact only
for the samples kept; later samples still narrow it).
"""
from __future__ import annotations

import time

import numpy as np

TYPES = {"u8": "u1", "u16": "u2", "u32": "u4", "s8": "i1", "s16": "i2", "s32": "i4", "f32": "f4"}
OPS = ("changed", "unchanged", "increased", "decreased", "equals", "not_equals", "range")
SPARSE_AT = 1 << 20                  # candidates left when the search stops keeping whole samples
K = 8                                # distinct values kept per label per candidate
MAX_BYTES = 320 << 20                # one search's arrays
FEW = 20000                          # this few candidates: read only the ranges around them
MAX_REGION = 96 << 20


class SearchError(ValueError):
    pass


class Search:
    def __init__(self, base: int, size: int, type: str = "u8", big_endian: bool = True, max_bytes: int = MAX_BYTES,
                 k: int = K, sparse_at: int = SPARSE_AT, tolerance: int = 0, clock=time.time):
        if type not in TYPES:
            raise SearchError(f"type is one of {', '.join(TYPES)}")
        if not 0 < size <= MAX_REGION:
            raise SearchError(f"a region of 1 byte .. {MAX_REGION >> 20} MiB")
        self.base, self.type, self.big = int(base), type, bool(big_endian)
        self.dt = np.dtype(("<>"[self.big]) + TYPES[type])
        self.w = self.dt.itemsize
        self.size = size - size % self.w
        self.n = self.size // self.w
        self.max_bytes, self.k, self.sparse_at, self.clock = max_bytes, k, sparse_at, clock
        self.tolerance = max(0, int(tolerance))
        self.native = self.dt.newbyteorder("=")
        self.mask = None                 # dense: bool[n] (None = every address still a candidate)
        self.idx = None                  # sparse: int64[m] element indexes
        self.prev = None                 # dense: values[n]; sparse: values[m]
        self.cur = None                  # the sample being applied
        self.labeled: list[tuple[str, np.ndarray]] = []    # dense: whole labeled samples kept for exact correlation
        self.sets = None                 # sparse: {"on": (vals[m, k], n[m], counts[m, k]), "off": ...}
        self.cost = None                 # sparse: int32[m] samples that would need another label (see tolerance)
        self.counts = {"on": 0, "off": 0, "plain": 0}
        self.dropped = {"overlap": 0, "too_many_values": 0, "filtered": 0}
        self.folded = 0
        self.history: list[dict] = []
        self.started = clock()

    # -- reading what a sample needs --
    @property
    def dense(self) -> bool:
        return self.idx is None

    def count(self) -> int:
        if not self.dense:
            return int(self.idx.size)
        return self.n if self.mask is None else int(self.mask.sum())

    def candidate_ranges(self, gap: int = 64) -> list[tuple[int, int]] | None:
        """(addr, n) ranges covering every candidate once few are left; None = read the whole region."""
        if self.dense or self.idx.size > FEW:
            return None
        if not self.idx.size:
            return []
        a = self.base + self.idx * self.w
        breaks = np.nonzero(np.diff(a) > gap)[0]
        starts = np.concatenate(([0], breaks + 1))
        ends = np.concatenate((breaks, [a.size - 1]))
        return [(int(a[s]), int(a[e] - a[s]) + self.w) for s, e in zip(starts, ends)]

    def _values(self, data) -> np.ndarray:
        """This sample's values: [n] for the whole region (bytes), or [m] at the candidates (bytes, or [(addr, bytes)])."""
        if isinstance(data, (bytes, bytearray, memoryview)):
            if len(data) < self.size:
                raise SearchError(f"the sample has {len(data)} of the region's {self.size} bytes")
            v = np.frombuffer(data, dtype=self.dt, count=self.n).astype(self.native)
            return v if self.dense else v[self.idx]
        if self.dense:
            raise SearchError("a partial sample needs a sparse search (read the whole region)")
        out = np.zeros(self.idx.size, dtype=self.native)
        seen = np.zeros(self.idx.size, dtype=bool)
        addrs = self.base + self.idx * self.w
        for a, blob in data:
            lo, hi = np.searchsorted(addrs, a), np.searchsorted(addrs, a + len(blob) - self.w, side="right")
            if hi <= lo:
                continue
            offs = (addrs[lo:hi] - a).astype(np.int64)
            raw = np.frombuffer(bytes(blob), dtype=np.uint8)
            items = np.stack([raw[offs + j] for j in range(self.w)], axis=1).copy()
            out[lo:hi] = items.view(self.dt).reshape(-1).astype(self.native)
            seen[lo:hi] = True
        if not seen.all():
            raise SearchError(f"{int((~seen).sum())} candidates were not in the sample")
        return out

    # -- the steps --
    def sample(self, data, label: str | None = None, op: str | None = None, value=None, lo=None, hi=None,
               note: str = "") -> dict:
        """One sample: an optional filter op (against the previous sample / a value), then an optional label."""
        if label not in (None, "on", "off"):
            raise SearchError("label is on, off or none")
        if op is not None and op not in OPS:
            raise SearchError(f"op is one of {', '.join(OPS)}")
        before = self.count()
        self.cur = self._values(data)              # trimmed with the candidates while this sample narrows them
        try:
            if op is not None:
                self._filter(op, value, lo, hi)
            if label is not None:
                self._label(label)
            else:
                self.counts["plain"] += 1
            self.prev = self.cur
        finally:
            self.cur = None
        self._maybe_sparse()
        self._bound()
        step = {"t": round(self.clock(), 3), "op": op, "label": label, "value": value, "lo": lo, "hi": hi,
                "before": before, "after": self.count(), "note": note}
        self.history.append({k: x for k, x in step.items() if x is not None and x != ""})
        del self.history[:-200]
        return step

    def _keep(self, keep: np.ndarray, why: str | None):
        """Narrow to the candidates where keep (aligned with the current candidates) is True (why: what dropped them,
        counted here for sparse searches; None when the caller counted already)."""
        if self.dense:
            if self.mask is None:
                self.mask = keep.copy()
            else:
                self.mask &= keep
            return
        gone = int((~keep).sum())
        if why:
            self.dropped[why] += gone
        if not gone:
            return
        self.idx = self.idx[keep]
        self.prev = self.prev[keep] if self.prev is not None else None
        self.cur = self.cur[keep] if self.cur is not None else None
        self.cost = self.cost[keep] if self.cost is not None else None
        if self.sets:
            self.sets = {k: (vals[keep], n[keep], c[keep]) for k, (vals, n, c) in self.sets.items()}

    def _filter(self, op: str, value, lo, hi):
        v = self.cur
        num = (lambda x: float(x)) if self.type == "f32" else (lambda x: int(x, 0) if isinstance(x, str) else int(x))
        if op in ("changed", "unchanged", "increased", "decreased"):
            if self.prev is None:
                raise SearchError(f"{op} compares with the previous sample: take one first")
            p = self.prev
            keep = {"changed": v != p, "unchanged": v == p, "increased": v > p, "decreased": v < p}[op]
        elif op in ("equals", "not_equals"):
            if value is None:
                raise SearchError(f"{op} needs a value")
            keep = (v == num(value)) if op == "equals" else (v != num(value))
        else:
            if lo is None or hi is None:
                raise SearchError("range needs lo and hi")
            keep = (v >= num(lo)) & (v <= num(hi))
        if self.dense and self.mask is not None:
            self.dropped["filtered"] += int((self.mask & ~keep).sum())
        elif self.dense:
            self.dropped["filtered"] += int((~keep).sum())
        self._keep(keep, "filtered")

    def _drop_dense(self, keep: np.ndarray, why: str):
        self.dropped[why] += int(((self.mask if self.mask is not None else True) & ~keep).sum())
        self._keep(keep, why)

    def _dense_cost(self) -> np.ndarray | None:
        """Per address, the fewest kept samples that would need the other label for its on and off values to be
        disjoint: sum over the on samples i of min(a_i, b_i) / a_i, a_i = on samples equal to on_i, b_i = off samples
        equal to it (each value v contributes min(on count, off count))."""
        on = [s for lab, s in self.labeled if lab == "on"]
        off = [s for lab, s in self.labeled if lab == "off"]
        if not on or not off:
            return None
        cost = np.zeros(self.n, dtype=np.float32)
        for s in on:
            a = np.zeros(self.n, dtype=np.float32)
            b = np.zeros(self.n, dtype=np.float32)
            for t in on:
                a += s == t
            for t in off:
                b += s == t
            cost += np.minimum(a, b) / a
        return np.rint(cost).astype(np.int32)

    def _label(self, label: str):
        other = "off" if label == "on" else "on"
        self.counts[label] += 1
        v = self.cur
        if self.dense:
            if self.tolerance == 0:                    # exact: one equal on / off pair rules an address out
                for lab, s in self.labeled:
                    if lab == other:
                        self._drop_dense(v != s, "overlap")
                self.labeled.append((label, v))
                return
            self.labeled.append((label, v))
            cost = self._dense_cost()
            if cost is not None:
                self._drop_dense(cost <= self.tolerance, "overlap")
            return
        self._add(label, self.cur)

    def _add(self, label: str, v: np.ndarray):
        """v (one value per candidate) into each candidate's set of `label` values, its count and the candidate's
        cost; a candidate past K values in one label, or past the tolerance, goes."""
        other = "off" if label == "on" else "on"
        vals, n, cnt = self.sets[label]
        cols = np.arange(self.k)[None, :] < n[:, None]
        hit = (vals == v[:, None]) & cols
        have = hit.any(axis=1)
        rows_hit = np.nonzero(have)[0]
        slot = hit[rows_hit].argmax(axis=1)
        cnt[rows_hit, slot] += 1
        new = np.nonzero(~have)[0]
        full = new[n[new] >= self.k]
        room = new[n[new] < self.k]
        vals[room, n[room]] = v[room]
        cnt[room, n[room]] = 1
        n[room] += 1
        own = np.zeros(n.size, dtype=np.int32)          # how often this candidate has had v in `label`, now
        own[rows_hit] = cnt[rows_hit, slot]
        own[room] = 1
        ovals, on_, ocnt = self.sets[other]             # min(own, other) grows by one when own is still <= other
        ohit = (ovals == v[:, None]) & (np.arange(self.k)[None, :] < on_[:, None])
        theirs = (ocnt * ohit).sum(axis=1)
        self.cost += ((theirs > 0) & (own <= theirs)).astype(np.int32)
        keep = np.ones(n.size, dtype=bool)
        keep[full] = False
        self.dropped["too_many_values"] += int(full.size)
        over = self.cost > self.tolerance
        over[full] = False
        self.dropped["overlap"] += int(over.sum())
        keep &= ~over
        if not keep.all():
            self._keep(keep, None)

    def _maybe_sparse(self, force: bool = False):
        if not self.dense or (self.count() > self.sparse_at and not force):
            return
        idx = np.arange(self.n, dtype=np.int64) if self.mask is None else np.nonzero(self.mask)[0].astype(np.int64)
        labeled, prev = self.labeled, self.prev
        self.idx, self.mask, self.labeled = idx, None, []
        self.prev = prev[idx] if prev is not None else None
        m = idx.size
        self.sets = {lab: (np.zeros((m, self.k), dtype=self.native), np.zeros(m, dtype=np.int32),
                           np.zeros((m, self.k), dtype=np.int32)) for lab in ("on", "off")}
        self.cost = np.zeros(m, dtype=np.int32)
        for lab, s in labeled:                       # the kept samples, in order, give each candidate its value sets
            self._add(lab, s[self.idx])

    def memory(self) -> int:
        if self.dense:
            return ((self.mask.nbytes if self.mask is not None else 0) + (self.prev.nbytes if self.prev is not None else 0)
                    + sum(s.nbytes for _, s in self.labeled))
        return (self.idx.nbytes + (self.prev.nbytes if self.prev is not None else 0)
                + (self.cost.nbytes if self.cost is not None else 0)
                + sum(a.nbytes + b.nbytes + c.nbytes for a, b, c in (self.sets or {}).values()))

    def _bound(self):
        while self.dense and self.memory() > self.max_bytes and self.labeled:
            if self.count() <= 8 * self.sparse_at:
                self._maybe_sparse(force=True)        # sparse sets are smaller than whole samples
                return
            busier = "on" if sum(lab == "on" for lab, _ in self.labeled) >= sum(lab == "off" for lab, _ in self.labeled) else "off"
            i = next(i for i, (lab, _) in enumerate(self.labeled) if lab == busier)
            self.labeled.pop(i)                       # its overlap with the other label's samples was applied already
            self.folded += 1

    # -- what is left --
    def candidates(self, limit: int = 100, current=None) -> list[dict]:
        """The candidates (at most limit): address, value now, and per label the values seen (with how often)."""
        out = []
        if self.dense:
            if self.count() > limit * 50:
                return []                             # too many to list: keep narrowing
            idx = np.arange(self.n) if self.mask is None else np.nonzero(self.mask)[0]
            idx = idx[:limit]
            for i in idx:
                out.append({"address": self.base + int(i) * self.w,
                            "value": self._py(self.prev[i]) if self.prev is not None else None})
            if self.labeled:
                for row, i in zip(out, idx):
                    for lab in ("on", "off"):
                        seen = {}
                        for l2, s in self.labeled:
                            if l2 == lab:
                                x = self._py(s[i])
                                seen[x] = seen.get(x, 0) + 1
                        row[lab] = [{"value": x, "n": c} for x, c in sorted(seen.items(), key=lambda kv: -kv[1])]
            return out
        order = np.arange(self.idx.size)
        if self.sets and (self.counts["on"] or self.counts["off"]):
            nvals = self.sets["on"][1] + self.sets["off"][1]
            order = np.lexsort((self.idx, nvals, self.cost))   # cleanest first: fewest mislabels, then fewest values
        for j in order[:limit]:
            row = {"address": self.base + int(self.idx[j]) * self.w,
                   "value": self._py(self.prev[j]) if self.prev is not None else None}
            if self.cost is not None and self.tolerance:
                row["mislabeled"] = int(self.cost[j])
            if self.sets:
                for lab in ("on", "off"):
                    vals, n, cnt = self.sets[lab]
                    row[lab] = sorted(({"value": self._py(vals[j, c]), "n": int(cnt[j, c])} for c in range(int(n[j]))),
                                      key=lambda e: -e["n"])
            out.append(row)
        return out

    def _py(self, x):
        return float(x) if self.type == "f32" else int(x)

    def status(self) -> dict:
        return {"base": self.base, "size": self.size, "type": self.type, "width": self.w, "big_endian": self.big,
                "candidates": self.count(), "mode": "dense" if self.dense else "sparse", "samples": dict(self.counts),
                "tolerance": self.tolerance,
                "dropped": dict(self.dropped), "folded": self.folded, "memory": self.memory(),
                "partial_reads": self.candidate_ranges() is not None, "history": self.history[-20:],
                "started": self.started}
