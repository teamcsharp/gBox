# Refract x gBox: feasibility report (Meta Quest / Resident Evil 4 VR, headset-free)

Research date: 2026-10-26. Nothing was downloaded, installed, run or signed into. Every claim is marked
**[V]** verified against a primary source (Refract's repository, release notes, issues, Meta's legal pages) or
**[I]** inferred by me from those sources. Links are in "Sources" at the end.

## 1. Identity

- **Refract** is `MIXIDtheSilly/Refract` on GitHub, tagline "Quest Translation Tool". README: "Refract runs Meta Quest
  (Android OpenXR) games on a Windows or Linux PC, in a PC VR headset or in a window on the screen." **[V]**
- Author: one person, MIXIDtheSilly, "a student", building it "in my spare time". It "started as a fork of AXRB by
  Feline Reintgen" (Android XR Bridge). **[V]**
- Repository created **2026-09-27**, last push 2026-10-21, 140 stars, 9 forks, 15 open issues. It is four weeks old. **[V]**
- Releases: test-1 (30 Sep) ... test-7 (2 Oct), **1.0.0 (15 Oct)**, 1.0.1 (15 Oct), **1.0.2 (19 Oct)**, 1.0.3 (21 Oct,
  Linux-only emergency fix). Assets: `Refract-1.0.x-win64.zip`, `Refract-1.0.x-linux-x86_64.tar.gz`. **[V]**
- License: GPL-3.0-or-later plus an extra NOTICE term: projects "built on Refract" must stay GPL-3.0-or-later and credit
  Refract with a visible link; code still from AXRB is MIT; the bundled Digitalis ARM64 translator is Apache-2.0. **[V]**
- Platforms: Windows 10/11 **x64** (two runtimes: "Android Emulator", most compatible; **"Refract Native"**, recommended and
  the default for new installs, "runs the game's ARM64 code directly on the PC" with no emulator) and Linux **x86_64**
  (glibc 2.39+, WebKitGTK 4.1, Python 3, adb, Waydroid 1.6.3+). "Refract Native is Windows-only for now." No ARM64 host
  build exists, so **the Spark (aarch64) cannot host it**; only the Windows workers can. **[V]**
- Requirements: "a recent graphics card (tested on NVIDIA)", 12 GB RAM, ~10 GB disk plus games; virtualization in
  BIOS (needed by the Android-emulator path; Native has no VM **[I]**). JAYBUILTFINALE has an RTX 3070 (gBox docs) **[V]**;
  the i9-NUC's GPU is not recorded anywhere I could find **[unverified]**.
- Status: "experimental. Not every game works yet." **[V]** No independent press coverage exists (UploadVR, Road to VR,
  Android Authority, Mixed: nothing; UploadVR covered the ancestor AXRB on 22 Sep 2026). Reddit and The Verge are not
  crawlable from here. Everything below therefore rests on the project's own pages and its issue tracker. **[V]**
- Namesakes/forks (not the target): `Omni-NexusAI/Refract` (a separate experimental project needing the Android SDK
  emulator + SteamVR), `Hustlenix/Refract`, `ytsodacan/Refract`, `VertofChest/R3fract`, `DeliciousMeatPop/Refracture-XR`
  (adds "Unknown sources" and an "ownership switch"), `MaxNiftyNine/Reflect` (macOS fork without launcher/Meta login). **[V]**

Verdict on identity: a real, open-source, very young hobby project with fast releases; not vaporware, not a closed beta,
but also not a mature emulator with a compatibility database.

## 2. Capabilities as of 1.0.2/1.0.3

### 2.1 Meta sign-in, library, downloads (the "Connect Meta" flow) **[V, from `launcher/core/meta.mjs`]**
- Sign-in is Meta's **native SSO** flow, code "adapted from RiftLift `meta_auth.py` (GPL-3.0-or-later)": POST
  `https://meta.graph.meta.com/webview_tokens_query` with a first-party client string (`FRL|512466987071624|...`), open
  `https://auth.meta.com/native_sso/confirm?...utm_source=refract` in a WebView, intercept the `oculus://` /
  `oculus-client://` callback, POST `webview_blobs_decrypt`, then GraphQL doc `24112177345042346` (app id
  `1582076955407037`) yields the Quest profile access token. 2FA happens inside Meta's web page. **It impersonates Meta's
  own client ids; it is not a registered third-party OAuth app.**
- Library: `https://graph.oculus.com/graphql` doc `4850747515044496`, `viewer.user.active_entitlements`, Quest apps
  only, each marked `owned: true`. Builds: doc `2885322071572384`; file plan: doc `4734929166632773` (`base.apk` from
  `binary.uri`, OBB from `obb_binary`, required `asset_files`). Downloads: `https://securecdn.oculus.com/binaries/download/
  ?id=...&access_token=...` (app-scoped token from `authenticate_application`, app id `1481000308606657`), resumable with
  `Range`/`If-Range`, SHA-256 verified, hosts whitelisted to oculus/meta/facebook CDNs. DLC: doc `3853229151363174`.
- Token storage: Windows DPAPI, current user, no entropy, raw blob in `%APPDATA%\Refract\meta-session.dpapi`
  (`launcher/src-tauri/src/secret.rs`). On Linux nothing is persisted.
- Known problems: issue #12 "Login Meta Account Failed" (library empty, error 500) is **still open**; maintainer said
  "Should be fixed", a user replied "Still happening" (15 Oct) and asked about 2FA (16 Oct). Issue #30: Meta's CDN answered
  **HTTP 416** for RE4 ("library ownership and file-delivery access are separate"), fixed by deleting files and retrying;
  issue #8: RE4 install failed "APK does not contain a launchable Android application", fixed in test-4. **[V]**

### 2.2 Install flow **[V]**
- Native: `python native/tools/install_apk.py <apk> --sdk <sdk>` unpacks the APK into
  `%LOCALAPPDATA%\Refract\native\apps\<package>\{lib\arm64\, classes.jar, app.properties}`, adds Refract's ARM64 OpenXR
  runtime (`libopenxr_runtime.so`, `librefract_driver.so`, `libvrapiimpl.so`) and the Platform SDK stand-in
  (`librefract_ovrplatform.so`), converts dex with dex2jar and rewrites `loadLibrary` calls (ShimBuilder). It needs
  **Python 3 on PATH** (the zip ships Node and a JDK but no Python) and Android build-tools `aapt2` (Setup downloads
  them since 1.0.2). OBB files stay where downloaded; the launcher passes their folder as `-ObbDir`, mounted in the guest
  at `/sdcard/Android/obb/<package>`.
- "Mixed-reality games that need a room scan won't start"; 32-bit (armeabi-v7a) games are not translated; "Refract Native
  can't play in-game videos yet; games skip them."

### 2.3 DRM / entitlement **[V, `platform-sdk/README.md`, `tools/run_native_game.ps1`, `backend/server.mjs`]**
- Refract ships a **Meta Platform SDK stand-in**: a `com.oculus.horizon` package whose `EntryPoint` loads
  `librefract_ovrplatform.so`, which implements init, message queue, users, access token, **entitlement**, app version and
  launch details; everything else is a logging stub. The game is unmodified ("no longer need OVRPort patching").
- The entitlement check succeeds **only** when the property `debug.refract.platform.owned.<package>=1` is set. The launcher
  sets `-Owned` iff `game.owned`, which is set only by the Meta library sync (`active_entitlements`) and reset to false for
  Meta-sourced records on every sync; imported APKs never get `owned`. `play()` itself does not check `owned`; an
  unowned title simply fails its own check. "In-app purchases and DLC are never granted." Games see a per-install random
  user id, user name "Refract".
- So the runtime check that RE4 VR performs is answered by Refract's stand-in, gated to titles in the signed-in account.

### 2.4 Desktop ("Play on PC") mode **[V, `scripts/pose_input_server.py`, `viewer/viewer.cpp`, `tools/run_native_game.ps1`]**
- Three processes: `python scripts\pose_input_server.py --eye-width N --eye-height N --refresh-rate 250` (TCP
  `0.0.0.0:38490` pose stream, UDP `127.0.0.1:38495` control), `viewer\build\refract_viewer.exe --title "<game>" --stats 0
  --shots "<Pictures>\Refract" --native refract_native.exe`, and `build-native\refract_native.exe --sysroot <sysroot> --app
  %LOCALAPPDATA%\Refract\native\apps\<pkg> --prop debug.refract.platform.owned.<pkg>=1 [--prop ...user_id=] [--mount
  "/sdcard/Android/obb/<pkg>=<ObbDir>"]`. Env: `REFRACT_CPU=digitalis` (or `dynarmic`), `REFRACT_JAVA_HOME`.
- Viewer window: Win32 class `RefractViewer`, D3D11 flip-model, title `"<game> – Refract Viewer"` (FPS appended each
  second), initial 1000x1040 resizable; **F11 toggles borderless fullscreen** (Esc leaves it; Alt+Enter disabled); no CLI
  flag for size/fullscreen/monitor. F1 stats, F2 screenshot, Home recenter. `--sensitivity 0.25`.
- Mouse: **right button held + drag = look** (yaw wraps, pitch clamped +-80 deg), left button = right trigger, middle
  button = right grip, wheel = hand reach 0.1-1.0 m. The cursor is not hidden or put in relative mode (SetCapture only),
  so it is not a native-FPS mouse feel. Viewer -> pose server: `view <yaw> <pitch> <trigger> <grip> <reach>` over UDP, on
  change and again every second.
- Keyboard (read with `GetAsyncKeyState`, but **only while the foreground window title matches `--focus`, default
  `Refract Viewer|Android Emulator|Emulator`**): Space/Enter=A, Backspace=B, Z=X, X=Y, Tab/M=left menu, E=right trigger,
  Q=left trigger, R=right grip, F=left grip, **arrows = right thumbstick**, **WASD walks the tracking origin (head and
  hands), it does not move a thumbstick**, Shift x2 speed, Home reset, T (hold) T-pose, C (hold) centre right controller.
  There is **no keyboard binding for the left thumbstick**, no height setting (head fixed at 1.65 m) and no sensitivity.
- Xbox/XInput pad (slots 0-3, read directly via `xinput1_4`): A/B -> right primary/secondary, X/Y -> left
  primary/secondary, Start -> left menu, stick clicks, LB/RB -> grips, LT/RT -> analog triggers, both sticks -> both
  thumbsticks (dead zone 0.24). This is the complete "Quest controller" model the operator asked for; it already exists.
- Tracking model: head looks along yaw/pitch; both hands are **fixed in the camera frame** at x = +-0.22 m, y = -0.28 m,
  z = -reach, aiming along the view. There is no gesture emulation (no reach-to-holster, no two-handed grip, no hand
  tracking: "Hand tracking, body tracking and keyboard overlays aren't supported"). Whether RE4 VR's body-slot weapon
  holsters are usable with fixed hands is **unverified** and is the single most important thing the Stage 0 test must
  answer.
- Scripting: the pose server accepts UDP text commands without any focus requirement: `hold <left|right>
  <a|x|b|y|menu|stick|trigger|grip> <s>`, `stick <left|right> <x> <y> <s>`, `view <yaw> <pitch> <trig> <grip> [reach]`,
  `keys <vk names>`, `tpose <s>`, `center <s>`. This is the injection surface for gBox bots. Caveat: the viewer re-sends
  its own `view` every second, so injected `view` values fight the viewer unless gBox controls that. **[V + I]**

### 2.5 Resident Evil 4 VR specifically
- Facts: Armature Studio / Oculus Studios, released 21 Oct 2021 as a Quest 2 exclusive, Unreal Engine 4 (4.25.3 per
  issue #38), built on the **older VrApi** SDK, package `com.Armature.VR4` (single source: issue #38), Meta store id
  `2637179839719680`. Meta acquired Armature in Oct 2022. **[V]**
- Refract timeline: 1.0.0 (15 Oct): "VrApi games aren't supported." 1.0.2 (19 Oct): "adds experimental support for older
  VrApi games", "**Resident Evil 4 plays on Refract Native**" (UE4 games start on Native, GPU reset/lost device fixes,
  ETC2 -> PC formats so lightmaps are no longer black, level texture load 20.7 s -> 5.8 s; on the emulator RE4 went
  49 -> 69 fps). The VrApi doc lists only QuakeQuest as a tested VrApi game and says Vulkan is "implemented but
  untested" and video surface swapchains are unsupported. **[V]**
- Field reports after 1.0.2: issue #30's reporter (20 Oct): RE4 "now launches but crashes at the intro video and after
  New Game" on the emulator, plus "ADB timed out" at the intro; the maintainer: hit the startup crash "early on and fixed
  it on their machine, but 'Maybe it needs more tweaks'". Issue #38 (20 Oct, **open**, no maintainer reply): on 1.0.2
  Native RE4 VR dies with SIGSEGV at `dlopen` because `libUE4.so`'s libc++ preempts `libovrplatformloader.so`'s private
  libc++; with the reporter's 21-stub PLT patch "the engine boots, OVRPlatform resolves ... frame 1 submitted" and the
  reporter "verified the game booting and controls working", then a SIGABRT in `libovraudio64.so` about 90 s into a
  headless (no viewer) run. **[V]**
- Honest reading: RE4 VR boots on Refract Native for the maintainer and for one user with an unmerged patch; nobody in
  the public record reports playing past the intro and New Game on the Native path, the intro video will be skipped
  (videos unsupported), and the UE4/platform-loader crash is unresolved upstream as of 1.0.3. **Not known-working.** **[V+I]**

## 3. Automation surface **[V unless marked]**

| Need | What Refract offers today |
|---|---|
| Programmatic launcher control | `node launcher\backend\server.mjs --data %APPDATA%\Refract` speaks **JSON lines over stdin/stdout**: `{id, method, args}` -> `{id, ok, value|error}`; events `changed` (full public state, <=10/s), `launch-error`, `secret`. Startup token: `{"type":"secret","value":"<token>"}` on stdin. No auth, no parent check: "Any process that can write to that pipe can send requests." Methods: `authBegin`, `authComplete(callbackUrl)`, `logout`, `state`, `sync`, `builds(id)`, `dlc(id)`, `checkSdk(id)`, `download(id, binaryId)`, `downloadDlc`, `cancel`, `retry`, `import(file)`, `importAssets`, `install(id)`, **`play(id, 'pc'|'vr')`**, `stop`, `headset`, `setup`, `fixSetup`, `settings({...})`, `emulatorStatus/Info/Storage/Action`, `logcat*`, `logFiles`, `logFile`, `adbShell`, `pidOf`, `exportDiagnostics`. |
| Where the library is | `%APPDATA%\Refract\library.json` = `{games[], jobs[], settings{}}`; game fields: `id, name, package, activity, apk, vrSdk, vrSdkBuild, binaryId, version, files[{name,path,kind,size,sha256}], downloaded, source ('meta'|import), owned, installed, nativeInstalled, lastPlayed` (+ artwork keys). Written atomically (`.tmp` + rename). `publicState()` hides `nativeInstalled`, `sha256` and the token. |
| Where games/data live | Downloads `~/Downloads/Refract/<app-id>/<build-id>/`; Native installs `%LOCALAPPDATA%\Refract\native\apps\<pkg>`; emulator saves inside the AVD (`%USERPROFILE%\.android\avd`). **Native save location is undocumented** (install_apk creates no data dir; `refract_native` has its own VFS) and must be found empirically **[unverified]**. No save states, no cloud saves. |
| Launch a specific title windowed without the GUI | `powershell -NoProfile -ExecutionPolicy Bypass -File tools\run_native_game.ps1 -Package <pkg> -GameName "<name>" -Sysroot <root>\build-native\sysroot -PcViewer -Owned [-ObbDir <dir>] [-UserId <id>] [-EyeSize 1600]` (or the three processes above directly). The script first **force-stops any leftover `refract_viewer.exe`, `refract-host-bridge.exe`, `refract_native.exe` and `pose_input_server.py`** (single session per PC), waits for TCP 38490, starts the viewer, starts the game, polls every 500 ms and ends when either exits; shutdown = `CloseMainWindow()` on the viewer, then kill. Logs: `<root>\build-windows-game\{input,viewer,native}.{log,err}`. |
| Headless | Not for play: the viewer is the only PC output. Issue #38 ran `refract_native` with no viewer ("xrEndFrame failed: -2" repeated). |
| Inject input | (a) UDP text commands to `127.0.0.1:38495` (no focus needed); (b) real keyboard/XInput, read globally but gated on the **foreground window title**; (c) mouse only through the viewer window. No virtual-gamepad API. |
| Capture | The viewer is an ordinary top-level D3D11 window: gBox's `win_grab(pid)` / desktop GPU-surface capture should apply as it does for Yuzu and xemu **[I]**. Frames also arrive in the viewer as named shared textures `Local\REFRACT_GPU_<session>_<eye>` (an alternative zero-copy tap, **[I]**). |
| Config | `library.json` `settings`: `backend ('emulator'|'native'), sdk, avd, port, memoryMB, downloadDir, cores, showWindow, audio, hostMic, keepEmulator, userId, pcEyeSize (512-4096, /8), vrRenderScale (25-200), setupDone`. Game-side props: `debug.refract.platform.owned.<pkg>`, `debug.refract.platform.user_id`, `debug.refract.texture_mip_limit`, `debug.refract.uncapped`, `debug.refract.vrapi_egl_compat`. |

## 4. Legal / ToS notes (not legal advice)
- Refract's own policy: "meant for apps you own and open samples"; do not use it "to bypass DRM, anti-cheat, platform
  security, store restrictions or license terms"; the repo "contains no game APKs, Meta SDKs or Horizon OS files: bring
  the games you own." Game files come **only** from the user's own Meta account (store download) or their own APKs. **[V]**
- Meta Quest Terms of Service (last updated 29 Apr 2025): content is licensed "on MPT Products devices you own or
  control, solely for personal non-commercial purposes" and "only licensed, not sold"; s.2.1: you "may not reverse
  engineer any of the MPT Products" and, except as Meta permits, may not "hack, emulate, or otherwise exploit any part of
  our services and software"; s.1.1.c forbids sharing passwords or transferring the account. Horizon Store Terms of Sale
  (1 Apr 2025) s.6: licence "on devices you own or control ... (as permitted by the functionality of your device)";
  "Any unauthorized use ... will cause the license ... to terminate automatically"; s.18: products "may require the use
  of an active Meta account". **[V]**
- Consequences for the operator: using only their own entitlements avoids piracy, but Refract (1) talks to Meta's
  undocumented Graph endpoints with Meta's own client ids, (2) answers the game's entitlement check with a stand-in, and
  (3) runs the title off-device, each of which sits outside the plain reading of s.2.1 "emulate". I found no record of
  Meta acting against Refract or AXRB users, and no statement from Meta either way. The realistic risk is to the Meta
  account (token revocation, account action), which gBox would be holding on a Windows worker. **[I]**
- gBox-side licence hygiene: driving Refract as separate processes over stdio/CLI is arm's length; vendoring or patching
  Refract code (viewer, pose server, the #38 patch) makes that code GPL-3.0-or-later with the NOTICE credit. **[V]**
- Keep the DPAPI token and `library.json` out of the repo and off the share; the same rules as `gbox-data/*.env`. **[I]**

## 5. Gap analysis

| Operator step | Refract today | gBox work | Possible now? |
|---|---|---|---|
| Meta sign-in | Native SSO in a Tauri WebView; `authBegin`/`authComplete` are rejected from the UI `call` and need the shell's `oculus://` interception; token DPAPI per Windows user | Option A (recommended first): operator signs in once in Refract's launcher on the worker; gBox reuses `meta-session.dpapi` via `CryptUnprotectData` (same user). Option B: gBox-desktop opens the `authBegin` URL in an Electron window with a `will-navigate` interceptor for `oculus://` and calls `authComplete`. | A: yes. B: yes, more work. 2FA stays in Meta's page. |
| Library (owned Quest games) | `sync` -> `library.json` games with `owned`, `vrSdk`, `installed/nativeInstalled` | `catalog.scan_refract()` modelled on `scan_steam()`: read `library.json`, emit `CatalogEntry(platform="quest", launch={"kind":"refract","package":..}, runtimes={"quest":"refract"})`; new `kind="refract"` library in `gbox.toml` | Yes (open issue #12 may leave the library empty for some accounts). |
| Download + install RE4 VR (APK + OBB) | `builds`, `download`, `install` over stdio; SHA-256; resume; `checkSdk` flags VrApi | gBox spawns the backend (never while the Refract GUI is open: both write `library.json`), drives the job, surfaces `changed` progress | Yes, if Meta's CDN cooperates (HTTP 416 episode). |
| Launch via Refract, windowed/fullscreen | `play(id,'pc')` or `run_native_game.ps1 -PcViewer`; F11 fullscreen; no size flag | `gbox/refract.py` `RefractAdapter` (Windows-only, like `YuzuAdapter`/`XboxAdapter`): launch, psutil-owned process tracking, `get_frame` via `win_grab(viewer pid)`, `stop_game` = WM_CLOSE viewer then kill, `query_runtime`; place/size/F11 the viewer like other docked windows | Yes mechanically. **Whether RE4 VR survives boot is the open question (s.2.5).** |
| Headset-free kb/m + gamepad | Built in: RMB-look, WASD/arrows/keys, full XInput -> Touch mapping, fixed hands aiming along view | None for the operator's own pad/keyboard. For gBox bots/autoplay: a UDP client for `hold/stick/view/keys` in `send_input` | Operator play: yes, with Refract's quirks (hold RMB to look, WASD moves the head, no left-stick on keyboard, no gestures). Bots: yes, except mouse-look conflicts with the viewer's 1 Hz `view` resend. |
| Translating VR gestures (holster, reload, two-hand) | Not modelled; hands are fixed in the camera frame | Would require forking the pose server (GPL) to add scripted hand motions | Not today; unknown whether RE4 VR is completable without it. |
| Saves | Native save path undocumented; no states | Locate the per-app data dir empirically, then add to `memory_card_sessions`/backup | Unknown until Stage 0. |
| Streaming to Pine Box / gBox app | Viewer = ordinary window | Reuse existing Windows capture path | Yes **[I]**. |

Hard constraints found in gBox: ViGEmBus must not be installed (`gbox/doa3_pad.py`), so no virtual gamepad; use
Refract's UDP control instead. gBox docks emulator windows as children of its own window (`winembed`), which changes the
foreground title and would **silence Refract's keyboard gating**; run the pose server with `--focus "gBox|Refract
Viewer"` or keep the viewer undocked/fullscreen. gBox has no mouse injection today (no `SendInput` mouse path), only keys.

## 6. Staged plan with effort

**Stage 0 - go/no-go, manual, on JAYBUILTFINALE (RTX 3070), 2-4 h operator time, no code.** Install Python 3 on PATH,
unzip Refract 1.0.3 (1.0.2 Windows bits), run Settings > Setup, Connect Meta, download RE4 VR, install on Native, Play
on PC with an Xbox pad. Record: does it get past the (skipped) intro and New Game; does the entitlement pass; fps; can
weapons be drawn from body slots with the fixed-hand model; where saves land (`procmon` on `refract_native.exe`). If it
crashes as in #38, choose: wait for upstream, or carry the #38 install-time patch in a fork (GPL). Nothing in gBox is
worth building before this passes.

**Stage 1 - launch adapter, 2-3 days.** `gbox/refract.py`: `RefractAdapter` (Windows-only; `supported = {launch_game,
stop_game, query_runtime, get_frame}`), config `[emulators.quest] adapter="refract" executable="<root>\Refract.exe"`
(`EmulatorConfig.adapter` comment in `gbox/config.py`), dispatch in `adapters.for_game()` for `plat == "quest"` (next to
the `ps4`/`switch` branches), a `quest` row in `gbox/systems.py`, `refract` in `launch_failures.ADAPTERS` and
`PLATFORM_ADAPTER`, catalog `scan_refract()` plus a `kind="refract"` library. Launch = the three processes (own the pose
server so `--focus` can include gBox's title), F11 or window placement, session ownership via psutil like
`XboxAdapter._live`. Deliverable: Play RE4 VR from gBox on a Windows worker, operator's pad/kb+m through Refract.

**Stage 2 - library and downloads through Refract's backend, 2-4 days.** `gbox/refract_backend.py`: spawn
`node\node.exe launcher\backend\server.mjs --data %APPDATA%\Refract --no-scan`, JSON-lines client, token from
`meta-session.dpapi` via `CryptUnprotectData`, `sync`/`builds`/`download`/`install`, progress to gBox jobs, mutual
exclusion with the Refract GUI. Sign-in option B (Electron interceptor in gbox-desktop) +1-2 days if the operator wants
it inside gBox.

**Stage 3 - bot/autoplay input, 2-3 days.** UDP control client in `send_input` (RetroPad -> `stick`/`hold`), `view` for
look with a solution to the viewer's 1 Hz resend (run the viewer with gBox's own pose server variant, GPL fork), and
`polite_input` semantics. Gesture macros (`center`, timed `hold`s) for RE4 VR interactions only if Stage 0 shows they
are needed and sufficient.

**Stage 4 - saves, backups, broadcast polish, 1-2 days** once the save path is known.

Total if Stage 0 passes: roughly 8-12 engineering days, plus upstream churn (Refract has shipped seven releases in four
weeks; pin a version and re-verify on upgrade).

## 7. Alternatives if Refract cannot do it
- **AXRB (Android-XR-Bridge/AXRB)**: the ancestor; MIT (launcher GPL), 288 stars, "Meta Quest library and storefront
  integration for owned Quest applications", Android x86_64 emulator + ARM translation + desktop OpenXR; Early Access
  delayed past 21 Sep 2026 (UploadVR); headset-centric with only a preview window; no documented desktop input model.
  Refract's Native runner and PC viewer are the parts that matter for headset-free play, so AXRB is a step back here. **[V]**
- **Refracture-XR fork**: same engine plus "Unknown sources" APK import and an ownership switch; irrelevant for an owned
  store title, and the switch is the DRM-adjacent part to stay away from. **[V]**
- **Meta XR Simulator (official)**: a desktop OpenXR runtime with keyboard/mouse/Xbox-driven headset and hands, but it
  "ships no operating system image and no Android layer": it runs developers' PC builds, never a Quest APK. **[V]**
- **PC OpenXR runtimes with virtual headsets** (SteamVR null driver, Monado, ALVR/Virtual Desktop) only run PC OpenXR
  apps; RE4 VR exists only as an Android/Quest build, so none of them can run it without Refract/AXRB-style translation. **[V]**
- **Linux path**: Refract on Waydroid x86_64 with Digitalis plus Monado/WiVRn works for OpenXR games (Batman at ~90 fps
  through SteamVR), but Native is Windows-only and VrApi on Linux is untested; no aarch64 build, so not the Spark. **[V]**
- **Not alternatives**: Resident Evil 4 (2023 PC remake) with the REFramework VR mod is a different game; "PortalVR 2.0"
  still needs the headset as a base station; casting the real Quest to a PC is not headset-free.
- **Wait**: the maintainer committed to RE4 in issue #30 ("work on that title next") and is shipping every few days; the
  #38 crash with a ready-made patch is the obvious next fix. Re-check the releases page before each stage.

## 8. Sources
- Repo and README: https://github.com/MIXIDtheSilly/Refract ; metadata: https://api.github.com/repos/MIXIDtheSilly/Refract
- Releases: https://github.com/MIXIDtheSilly/Refract/releases ; test-1: .../releases/tag/test-1 ; 1.0.0: .../releases/tag/v1.0.0 ; 1.0.2: .../releases/tag/v1.0.2
- PR #31 Refract Native: https://github.com/MIXIDtheSilly/Refract/pull/31 ; PR #33 Linux/PC viewer: https://github.com/MIXIDtheSilly/Refract/pull/33 ; PR #4 Electron->Tauri: https://github.com/MIXIDtheSilly/Refract/pull/4 ; PR #22 Meta resilience: https://github.com/MIXIDtheSilly/Refract/pull/22
- Issues: #8 https://github.com/MIXIDtheSilly/Refract/issues/8 ; #12 https://github.com/MIXIDtheSilly/Refract/issues/12 ; #30 https://github.com/MIXIDtheSilly/Refract/issues/30 ; #38 https://github.com/MIXIDtheSilly/Refract/issues/38
- Source files read (raw.githubusercontent.com/MIXIDtheSilly/Refract/main/...): `launcher/core/meta.mjs`, `launcher/core/download.mjs`, `launcher/core/runtime.mjs`, `launcher/core/state.mjs`, `launcher/backend/server.mjs`, `launcher/src-tauri/src/{backend.rs,secret.rs,main.rs}`, `launcher/README.md`, `scripts/pose_input_server.py`, `viewer/viewer.cpp`, `tools/run_native_game.ps1`, `tools/package_release.ps1`, `native/tools/install_apk.py`, `platform-sdk/README.md`, `docs/{overview,vrapi,windows_controller_hands,game_save_persistence,windows_unreal_memory}.md`; file tree: https://api.github.com/repos/MIXIDtheSilly/Refract/git/trees/main?recursive=1
- Forks/namesakes: https://github.com/DeliciousMeatPop/Refracture-XR ; https://github.com/Omni-NexusAI/Refract ; https://github.com/Hustlenix/Refract ; https://github.com/MaxNiftyNine/Reflect ; https://github.com/VertofChest/R3fract
- AXRB: https://github.com/Android-XR-Bridge/AXRB ; UploadVR 22 Sep 2026: https://www.uploadvr.com/android-xr-bridge-tool-brings-quest-exclusives-to-pc-vr/
- Meta XR Simulator: https://developers.meta.com/horizon/documentation/unity/xrsim-intro/
- Meta Quest ToS: https://www.meta.com/legal/quest/terms-of-service/ ; Horizon Store Terms of Sale: https://www.meta.com/legal/quest/store-terms-of-sale/
- RE4 VR: store https://www.meta.com/en-gb/experiences/2637179839719680/ ; launch post https://www.meta.com/blog/survival-horror-classic-resident-evil-4-launches-for-vr-october-21-exclusively-for-oculus-quest-2/ ; Armature acquisition https://www.shacknews.com/article/132636/armature-studio-meta-resident-evil-4-vr-re4
- gBox files inspected: `gbox/adapters.py` (`Adapter`, `CommandAdapter`, `StandaloneAdapter`, `YuzuAdapter`, `SteamAdapter`, `for_game`, `win_grab`, `win_send_keys`, `keep_offscreen`), `gbox/xbox.py` (`XboxAdapter._live/_boot`), `gbox/catalog.py` (`scan_steam`), `gbox/systems.py`, `gbox/launch_failures.py`, `gbox/config.py` (`EmulatorConfig`, `Library`, `[emulators.ps4]` example), `gbox/tools.py` (`_launch_game` around line 940), `gbox/doa3_pad.py` (ViGEm rule), `gbox/gamepads.py`

## 9. Ticket text (for gBox's request queue)
```
Quest via Refract, Stage 0 + 1: RE4 VR headset-free on a Windows worker
1. Stage 0 (manual, JAYBUILTFINALE/RTX 3070, no gBox code): install Python 3 + Refract 1.0.3 win64, Setup, Connect Meta,
   download + Native-install RE4 VR (com.Armature.VR4, store 2637179839719680), Play on PC with an Xbox pad.
2. Record go/no-go evidence: boots past (skipped) intro and New Game? entitlement passes? fps? weapons reachable with
   Refract's fixed hands? save path (procmon refract_native.exe)? If it dies at dlopen, it is upstream #38 (unmerged patch).
3. Stage 1 only after a GO: gbox/refract.py RefractAdapter (Windows-only; launch/stop/query_runtime/get_frame), spawning
   pose_input_server.py --focus "gBox|Refract Viewer", refract_viewer.exe, refract_native.exe (argv per tools/run_native_game.ps1).
4. Catalog: scan_refract() over %APPDATA%\Refract\library.json -> platform "quest", launch {"kind":"refract","package"}.
5. Wiring: for_game() branch, systems.py row, launch_failures ADAPTERS/PLATFORM_ADAPTER, [emulators.quest] docs in config.py.
6. Rules: operator's own Meta account only; no APK/token/library.json in repo or share; no ViGEm; Refract code stays separate (GPL).
7. Evidence: in-game screenshots from the gBox session (real frames), fps, and the input path used (pad vs kb/m).
8. Out of scope here: sign-in inside gBox, downloads via the stdio backend, bot UDP input (Stages 2-3, separate tickets).
```
