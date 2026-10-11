# Bounded backend polling reads

`/api/jobs` previously read and decoded every job before filtering its state or
returning the newest requested rows. `/api/tasks` did the same, then decoded all
inbox reports to select at most twenty resolution threads. Slow overlapping
polls therefore repeated work on completed history while sharing the Store lock
with worker heartbeats and results.

The Store now filters job state and excludes inventory jobs in SQLite before
decoding results. Job state filters explicitly use the existing partial state
index: without the hint SQLite can choose a rowid scan for a multi-state poll.
A kind index supports rowid ordering without sorting the whole document kind.
A partial creation-time index selects resolution reports before decoding them.
Indexes are created when a fresh Store opens; this source change has not itself
reloaded a running backend.

The endpoint contract remains:

- Job ordering uses rowid, including the existing `INSERT OR REPLACE` behavior.
  State filters run before the limit. A positive limit returns the newest N,
  zero returns all matches, and a negative limit skips that many oldest matches
  before reversing them, preserving the previous Python slice semantics.
- Tasks contain all active non-inventory jobs, sorted by creation time, plus the
  newest ten completed non-inventory jobs in rowid order. Active and recent
  groups share a locked snapshot. Resolution reports retain creation-time order
  and ascending rowid order for ties.
- Sessions still return every session, including ended sessions, newest rowid
  first. Their stored fields and live frame ages remain available. One timestamp
  supplies frame ages for each response; no session cache or history truncation
  was added.
- The task reader reuses one worker snapshot. Retirement retains the existing
  stalled-frame and unavailable-worker rules, while reusing session and worker
  alias lookups within its locked queued-job snapshot. Inventory scheduling and
  its ten-second refresh interval remain unchanged.

## Verification

`tests/test_backend_polling.py` compares positive, zero and negative limits to
the old slice behavior; checks replacement ordering, active progress, inventory
exclusion, resolution ties, session fields and frame ages; and refuses to decode
obsolete documents. Its fixture also includes an unrelated malformed JSON
document. Retirement tests check repeated aliases and session lookups. Existing
active-job and inventory snapshot tests cover retirement and inventory results.

A read-only transaction copied 12,810 jobs (17,420,458 JSON bytes), 681 sessions
and 1,288 requests from the Spark to a new private SQLite snapshot. Three
same-host runs compared the old and new SQLite/JSON reader operations on the
same immutable rows. All five outputs had identical hashes and counts:

| Reader operation | Old median | New median | Result count |
| --- | ---: | ---: | ---: |
| Latest 100 jobs | 171.84 ms | 1.01 ms | 100 |
| Active jobs, limit 1000 | 223.41 ms | 0.05 ms | 8 |
| Task job groups | 190.71 ms | 0.48 ms | 2 active, 10 recent |
| Resolution reports, limit 20 | 22.07 ms | 0.12 ms | 4 |
| All sessions, newest first | 4.48 ms | 4.37 ms | 681 |

This is a private SQLite/JSON microbenchmark. It does not measure live HTTP
latency, concurrent-load behavior, retirement, inventory submission, Hermes
discovery, live-frame updates or response serialization, and it does not prove
runtime adoption. The canonical database was read only; all index creation and
timed operations ran against the private copy. The local evidence receipt is
`system/gbox-data/inbox-continuation-20261011/backend-polling-benchmark.json`
(SHA256 `a49488d893f33f52cdd7dda2fe91d1bfa168279965cb850c3faf9274370ea6b7`).
