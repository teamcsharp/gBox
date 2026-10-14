# Windows browser proliferation investigation — 2026-10-14

The reported proliferation was confirmed and repaired. The first Windows scan
found **275 `msedge.exe` processes**, aggregate working set **15,199,416,320 bytes**
(14.2 GiB), and **117,340 handles**. A subsequent process-tree inventory identified
**18 headless GBox test-browser roots**, aged about 10.7 hours, all with missing
parents or parent PIDs reused by newer processes. No healthy legacy test owner
remained. The ordinary Electron GBox application was a separate process tree.

The exact older roots were:

| PID | Legacy temporary profile | Parent PID (gone/reused) |
| --- | --- | --- |
| 15600 | gbox-tk-W1NCX1 | 57692 |
| 24412 | gbox-tk-nFuC84 | 41364 |
| 29860 | gbox-tk-JjhOxL | 41032 |
| 36964 | gbox-72-17UJ6Z | 23840 |
| 39072 | gbox-tk-zJpsoA | 45608 |
| 43060 | gbox-tk-QBorJ6 | 43080 |
| 43064 | gbox-tk-HHJt7A | 45380 |
| 44580 | gbox-tk-2ZOigq | 22352 |
| 45032 | gbox-tk-BXj4TC | 44704 |
| 46596 | gbox-tk-0cfvg3 | 43344 |
| 50668 | gbox-tk-KErXwN | 50252 |
| 54660 | gbox-tk-dLEX0z | 54840 |
| 55880 | gbox-tk-u4pkNy | 48976 |
| 55912 | gbox-tk-4pW3Ip | 58636 |
| 57088 | gbox-72-Ik9zdR | 60100 |
| 58800 | gbox-tk-JRhNhS | 58700 |
| 58884 | gbox-tk-VAM3e9 | 58740 |
| 62568 | gbox-tk-67JAbn | 49480 |

The private runtime reports retain root/child creation times, parent links,
executable/profile matches, per-tree resources and cleanup outcomes:
`system/gbox-data/browser-process-investigation/{before,legacy-preflight,cleanup,after}.json`.
They are diagnostics, not committed user/profile data.

The two original test harnesses independently spawned Edge with
`--headless --no-sandbox --disable-gpu --remote-debugging-port=0` and a new
`gbox-tk-*` or `gbox-72-*` profile on every invocation. Their `finally` block sent
Browser.close, waited briefly, then killed only the immediate subprocess. It
had no kernel process-tree owner, global admission limit or worker-death
protection. Websocket connection/RPC promises and the task callback could wait
indefinitely. A test-worker timeout/hard termination could skip finally entirely;
immediate-process termination could leave browser children behind. Later test
runs launched new browsers independently of those old sessions. Temporary-profile
removal was best-effort after that incomplete shutdown.

The same unsafe helper pattern was copied into the newer shared
`tests/build_report_browser.cjs`; this repair removes that copy too. The surviving
trees' profile names and command arguments directly identify the older test
launchers. The original event that terminated each old test worker is not known;
the defect is established by the missing owners, the code paths, and reproduced
worker/supervisor crash tests.

Launch-site audit of authoritative `system/` code:

| Path | Creation/reuse | Cleanup and disposition |
| --- | --- | --- |
| `tests/test_tasks_scroll.cjs` | Raw Edge/Chromium per browser test | Duplicated unsafe helper replaced with central import |
| `tests/test_chat_conversation_composer.cjs` | Raw Edge/Chromium per browser test | Same replacement |
| `tests/build_report_browser.cjs` | Shared helper used by new UI checks | Now a compatibility import of central manager |
| `scripts/ui_evidence.py` | One Playwright browser per screenshot batch; context/page per shot | Uses managed browser via CDP; explicit context and browser finally blocks |
| `scripts/ui-perf/probe.cjs` | One Electron test window plus embedded webview | Owned Electron app exits on success/error; does not create these Edge profiles |
| `clients/desktop/main.js` | Single-instance Electron app, main window, reused overlay/viz windows, replacement mini window, temporary PDF window | Parent-owned windows; PDF destroys in finally; app shutdown; outside headless test pool |
| `clients/desktop/overlay.js` | Reuses one parent-owned overlay window | Existing destroy/closed lifecycle; not an Edge automation launcher |
| Desktop `browser:send` | Opens external AutoBrowse, or OS browser fallback | User-facing external app; never adopted/terminated by automation manager. Configured AutoBrowse entry was absent here |

No GBox production worker/service directly launches the raw headless Edge test
pattern. No Puppeteer/Selenium startup was found in authoritative project code.
Ghidra's unrelated `--headless` option and vendor documentation mentioning browser
flags are not browser launchers. Browser creation now has one managed entry point
for all discovered headless Node and Playwright callers. Normal app windows and
user browser capabilities remain available.

The [lifecycle documentation](browser-lifecycle.md) describes configurable session
and queue limits, resource backpressure, Windows Job Object ownership, timeouts,
cancellation, cleanup/recovery, sandbox defaults and local debugging isolation.
The unconditional Windows sandbox-disable flag was unnecessary: sandboxed Edge
passed the real UI tests. Observed legacy debugging listeners were already on
127.0.0.1, not LAN interfaces; the repair makes that binding and target validation
explicit. No remote debugging exposure was inferred merely from `port=0`.

At **10:29:38 UTC**, a fresh cleanup inventory found 257 Edge processes using
**12,736,049,152 aggregate working-set bytes** (11.9 GiB) and **111,831 handles**.
Process counts changed between snapshots as Chromium children came and went.
After revalidation, only the 18 confirmed orphan roots and same-profile descendants
were closed. At **10:29:57 UTC**, Edge count, aggregate working set, handles and
legacy test sessions were all **zero**. All 18 legacy profile directories were
preserved. A later independent check at **10:35:21 UTC** again found zero Edge
processes, zero live old roots and zero managed browsers, with all 18 profiles present.
The inventory measured about 27.98 GB across matching legacy temporary directories;
this repair did not delete that historical profile data. New disposable profiles
are cleaned by the manager. Aggregate RSS includes shared pages and is not an exact
measurement of physical RAM reclaimed; other OS workloads continued throughout.

Validation passed: 11 Python checks; 27 Node checks covering the migrated UI
consumers and lifecycle tests; then an extended run with 20 startup/shutdown
cycles, a 30-second automation task, task failures, cancellation, RPC/callback
timeouts, queue serialization, worker hard kill and supervisor hard kill. The
extended run finished with zero live owned processes and zero disposable profiles.
The final six-case lifecycle suite also checks application process exit, a missing
browser executable and configured memory-limit failure.
Its maximum observed per-session aggregate working set was 757,448,704 bytes,
with 5,007 handles in the reported session samples. The real Playwright screenshot
pipeline passed both a normal screenshot and a deliberate selector timeout:
both leases closed and left no profiles. Resource limits are configurable rather
than inferred from the number of Chromium renderer processes alone.

Windows Application Error/Windows Error Reporting events show an Explorer crash
with exception `0xc0000409`, faulting module Explorer.EXE. That crash predates the
observed orphan browser trees. The initial scan also showed about 31 GB of free
physical memory, so total RAM exhaustion was not established. The browser waste
was real, but these facts do **not** establish the cause of Explorer/taskbar/Start
instability. No Explorer process, Windows session, active GBox job, operator game,
normal browser or project data was terminated, restarted or deleted by this repair.
