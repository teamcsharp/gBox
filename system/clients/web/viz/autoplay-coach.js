// Coach the autoplay (operator 2026-10-20: "During cloud sessions put a text box here where I can type ... and tell it
// things like 'Stop walking into walls', 'that's not an enemy', 'go after the enemy', 'aim at the enemy'"). A one-line
// box in the Sessions header, right of the session id / save icon and left of the ★ ⏸ 🎮 ⌖ ↻ ■ buttons. Enter sends the
// note to POST /api/sessions/{sid}/coach (gbox/coaching.py): it is filed on the game's coaching ticket and its moment is
// captured on the PC running the game (a frame, a save state through gBox's own slot, the main RAM). The status beside
// the box follows those captures until they settle:
//   "Note #3 sent · frame ✓ · state … · RAM ✓"      ✓ attached · ✗ failed · – not taken here · … still capturing
// and a few seconds later folds to "Note #3 ✓" (or "Note #3 · RAM ✗"), so the box keeps its room in a full header; the
// tooltip keeps every detail (ticket, each capture, the RE4 summary). The shell's dictation adds its 🎤 to the box like
// to every text field. The desktop app shows this same header (its Play view embeds the web shell), so the box is there.
//   GBoxAutoplayCoach.html(sid)                  the box's markup for the header
//   GBoxAutoplayCoach.mount(root, {sid, api, onSent})  wires the box inside root; an unsent draft survives a re-render,
//                                                a note still capturing keeps its status when the header is drawn again;
//                                                onSent(answer) after each note is filed (the Sessions page gives a bot
//                                                demo on this PC the keyboard back then). The box shows on every running
//                                                session, so on a bot demo on any PC; each note reaches the agents at once
//                                                (scripts/agent_ledger.py: the inbox hook and `list`)
//   GBoxAutoplayCoach.create({sid, api, render}) the same without a DOM (tests)
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const KINDS = ["frame", "state", "ram"];
  const LABEL = { frame: "frame", state: "state", ram: "RAM" };
  const MARK = { done: "✓", failed: "✗", skipped: "–", pending: "…" };
  const PLACEHOLDER = "Coach the autoplay: stop walking into walls, aim at him…";
  const drafts = new Map();                     // sid -> unsent text
  const recent = new Map();                     // sid -> {out, at}: the latest note, to resume its status after a re-render
  const retries = new Map();                    // sid -> one failed/uncertain submission, retried with the same ID
  const RETRY_KEY = "gbox.coach.uncertain.v1", RETRY_AGE = 86400000;
  function storedRetries(storage, now) {
    try { return JSON.parse(storage?.getItem(RETRY_KEY) || "[]").filter(x =>
      typeof x.sid === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(x.sid) && typeof x.text === "string" && x.text.length <= 2000 &&
      typeof x.clientId === "string" && /^[A-Za-z0-9_-]{8,96}$/.test(x.clientId) && Number.isFinite(x.at) && now >= x.at && now - x.at <= RETRY_AGE).slice(-50); }
    catch { return []; }
  }
  // The outbox (operator 2026-11-10: a critique typed in the PiP never reached the ticket): a note that could not be
  // delivered - the request never left this PC (Wi-Fi / Spark unreachable, the app reconnecting), or its answer was lost
  // and the server's receipt says it never arrived - is retried with its own submission ID until it is filed, the status
  // saying so all along, instead of the words sitting back in a box the PiP hides. Only an idempotent box (the compact
  // window's) queues: the server files a submission ID once, so a retry can never make a second note.
  const OUTBOX_KEY = "gbox.coach.outbox.v1", OUTBOX_MAX_MS = 30 * 60000;
  const OUTBOX_BACKOFF_MS = [2000, 4000, 8000, 15000, 30000];
  const outbox = new Map();                     // clientId -> {sid, text, clientId, at, tries, checkFirst, reason, timer, ...}
  const painters = new Map();                   // sid -> Set of live controllers' outbox painters
  const apis = new Map();                       // sid -> the newest controller's api (the outbox outlives a re-mount)
  let outboxStorage = null, outboxLoaded = false;
  // The desktop marks a request that never left the PC (error.notSent: main.js apiRaw); older apps only say so in words.
  const NOT_SENT = /No request was sent|Your game was not changed|Remote gBox is offline|starting or reconnecting|Waiting for this connection|ERR_INTERNET_DISCONNECTED|ECONNREFUSED|ENOTFOUND|EHOSTUNREACH|ENETUNREACH|EAI_AGAIN/i;
  function notSent(e) { return e?.notSent === true || NOT_SENT.test(String(e?.message || e || "")); }
  function definitive(e) { return /^(400|401|403|404|422)\b/.test(String(e?.message || e || "")); }
  // Instant commands (operator 2026-10-24): the bot acts on these within a second (gbox/mercs/directives.py has the same ids).
  const COMMANDS = [
    ["fight", "Fight them!", "Stop standing there and fight the foes"],
    ["next_area", "Go to the next area", "Leave this goal for the next time bonus / area"],
    ["explore", "Navigate more of the level", "Reset the route and explore"],
    ["hunt", "Go after the enemies", "Seek, find and dispatch them"],
    ["score", "Go for score increases", "Build the combo"],
    ["repetitive", "You are doing a repetitive action", "Stop it and go forward"],
    ["mine", "Drop a mine and flee", "Plant a mine, then leave"],
    ["mine_trail", "Drop mines while leaving the area", "Plant, move on, repeat for 45 s (RE5, mines setting on)"],
    ["missing", "You are missing", "Adjust the aim for this weapon"],
  ];

  // Which live bot-logic knobs each command drives (request #5300): the sub-panel shows these with toggles / sliders.
  // Names match gbox/mercs/bot_logic.py KNOBS; the panel reads the current values from the running bot and writes back through it.
  const COMMAND_KNOBS = {
    re5: {
      fight:     ["CROWD_FIRE", "CROWD_FIRE_N", "RAMPAGE_R", "WINDUP"],
      next_area: ["RELOCATE", "PROMPTS", "WALL_GOV"],
      explore:   ["RELOCATE", "WALL_GOV", "QUICK_TURN"],
      hunt:      ["WINDUP", "WINDUP_R", "CROWD_FIRE", "BEHIND_R"],
      score:     ["CROWD_FIRE", "MINES", "MINE_EVERY_S", "RAMPAGE_R"],
      repetitive:["RELOCATE", "WALL_GOV", "QUICK_TURN"],
      mine:      ["MINES", "MINE_EVERY_S"],
      mine_trail:["MINES", "MINE_EVERY_S"],
      missing:   ["AIM_LOCK", "HEADING_GOV_DEG_S", "WINDUP"],
    },
    re6: {
      fight:     ["NADES", "FLASH", "FLASH_GAP_S", "CROWD_R", "FIRE_ZONE_R"],
      next_area: ["BONUS_RUN", "NAV_WALK", "PROMPTS"],
      explore:   ["NAV_WALK", "BONUS_RUN", "KITE_R"],
      hunt:      ["NADES", "FLASH", "CLOSE_R", "FIRE_ZONE_R"],
      score:     ["BONUS_RUN", "BONUS_SHOOT_R", "FIRE_ZONE_R", "AUTO_SWITCH"],
      repetitive:["NAV_WALK", "KITE_R", "KEEP_R"],
      mine:      ["BOMB_DROP"],
      mine_trail:["BOMB_DROP"],
      missing:   ["AIM_LOCK", "SPIN_DEG_S", "CLOSE_R"],
    },
  };
  const HOLD_MS = 4000;                         // the settled full status stays this long before it folds
  // the status gives way before the box: it shrinks first (ellipsis, full text in its tooltip)
  const CSS = `#session-head .coach{display:inline-flex;align-items:center;gap:6px;flex:1 1 240px;min-width:min(100%,200px);max-width:640px}
    #session-head .coach>input,#session-head .coach>.micwrap{flex:1 1 auto;min-width:min(100%,140px);width:auto}
    #session-head .coach .coach-st{flex:0 4 auto;min-width:0;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    #session-head .coach .coach-st:empty{display:none}
    #session-head .coach .coach-st[data-state=error]{color:var(--bad)}
    .coach .coach-st[data-state=queued],.coach .coach-st[data-state=draft]{color:#ffd166;cursor:pointer}
    .coach .coach-send{flex:0 0 auto;width:24px;height:23px;padding:0;border:1px solid #666;border-radius:3px;background:#18181d;color:#fff;cursor:pointer;-webkit-app-region:no-drag}
    .coach .coach-cmds{flex:0 0 auto;width:24px;height:23px;padding:0;border:1px solid #666;border-radius:3px;background:#18181d;color:#fff;cursor:pointer;-webkit-app-region:no-drag}
    .coach-menu{position:fixed;z-index:200;min-width:260px;background:#1d1d22;border:1px solid #555;border-radius:8px;padding:4px;box-shadow:0 8px 24px #0009;-webkit-app-region:no-drag}
    .coach-menu button{display:block;width:100%;text-align:left;background:none;border:0;color:#e8e8ee;padding:6px 10px;border-radius:5px;cursor:pointer;font-size:13px}
    .coach-menu button:hover,.coach-menu button:focus-visible{background:#ffffff1a}.coach-menu small{display:block;color:#aaa;font-size:11px}
    .coach-menu .coach-row{display:flex;align-items:center;gap:2px}
    .coach-menu .coach-row>button{flex:1;min-width:0}
    .coach-menu .coach-cog{flex:0 0 auto;width:28px;padding:6px 4px;text-align:center;color:#888}
    .coach-menu .coach-cog:hover{color:#fff;background:#ffffff22}
    .coach-sub{position:fixed;z-index:201;min-width:280px;max-width:360px;max-height:70vh;overflow:auto;background:#16161af2;border:1px solid #555;border-radius:8px;padding:10px 12px;box-shadow:0 10px 30px #000c;-webkit-app-region:no-drag;font-size:12px;color:#ddd}
    .coach-sub h4{margin:0 0 6px;font-size:12px;color:#9cf}
    .coach-sub .cs-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 6px;align-items:center;margin:4px 0}
    .coach-sub .cs-row small{grid-column:1/-1;color:#999;font-size:10px}
    .coach-sub .cs-row output{color:#ffd166;font-variant-numeric:tabular-nums}
    .coach-sub input[type=range]{grid-column:1/-1;width:100%;box-sizing:border-box;margin:0;accent-color:#7c96ff}
    .coach-sub .cs-msg{color:#ffadad;min-height:14px;margin:4px 0;font-size:11px}
    .coach-sub .cs-empty{color:#888;margin:6px 0;font-size:11px}
    .coach-sub fieldset{border:0;padding:0;margin:0}
    .coach-sub input:disabled,.coach-sub button:disabled{opacity:.5;cursor:default}`;

  function statusText(note, captures) {
    return [`Note #${note ?? "?"} sent`, ...KINDS.map(k => `${LABEL[k]} ${MARK[(captures && captures[k] || {}).state] || MARK.pending}`)]
      .join(" · ");
  }

  // the settled status folded: "Note #3 ✓", "Note #3 ✓ · state –" (not taken here), "Note #3 · RAM ✗" (failed)
  function compactText(note, captures) {
    const of = s => KINDS.filter(k => ((captures || {})[k] || {}).state === s).map(k => `${LABEL[k]} ${MARK[s]}`);
    const failed = of("failed");
    return failed.length ? [`Note #${note ?? "?"}`, ...failed].join(" · ") : [`Note #${note ?? "?"} ✓`, ...of("skipped")].join(" · ");
  }

  // the tooltip: the ticket, each capture's detail and (RE4) the decoded moment
  function detailText(st) {
    const rows = [`Coaching ticket #${st.number ?? "?"}, note ${st.note ?? "?"}`];
    if (st.task_dispatch_unavailable) rows.push("Note saved; automatic task dispatch requires the updated server. Do not resend it.");
    if (st.implementation_number) rows.push(`Implementation task #${st.implementation_number} queued; starts when admitted.`);
    else if (st.change_id) rows.push(`Change ${st.change_id}: ${st.dispatch_state || "open"}${st.dispatch_state === "uncertain" ? "; task creation needs review" : ""}`);
    for (const k of KINDS) {
      const c = (st.captures || {})[k] || {};
      rows.push(`${LABEL[k]}: ${c.state || "pending"}${c.detail ? " - " + c.detail : ""}`);
    }
    for (const [name, item] of Object.entries(st.evidence || {}))
      rows.push(`Report ${name}: ${item.state}${item.detail ? " - " + item.detail : ""}${item.age_s != null ? ` (age ${item.age_s}s)` : ""}`);
    if (st.summary) rows.push(st.summary);
    return rows.join("\n");
  }

  function settled(captures) {
    return KINDS.every(k => ((captures || {})[k] || {}).state !== "pending");
  }

  function noteView(st, compact = false) {
    const uncertain = st.change_id && ["creating", "uncertain"].includes(st.dispatch_state);
    let base = compact ? compactText(st.note, st.captures) : statusText(st.note, st.captures);
    if (st.evidence && Object.keys(st.evidence).length)
      base += ["stream", "map", "moment"].map(k => ` · ${k === "stream" ? "report image" : k} ${MARK[(st.evidence[k] || {}).state] || "?"}`).join("");
    const notQueued = st.dispatch_state === "failed";      // filed, but its implementation task could not be made
    return { text: st.task_dispatch_unavailable ? `Note #${st.note ?? "?"} saved; task dispatch needs server update`
      : uncertain ? `Note #${st.note ?? "?"} saved; task creation unconfirmed`
      : notQueued ? `Note #${st.note ?? "?"} saved; its task was not queued`
      : base + (st.implementation_number ? ` · task #${st.implementation_number} queued` : ""),
      title: detailText(st) + (notQueued && st.dispatch_error ? `\nTask not queued: ${st.dispatch_error}` : ""),
      state: st.task_dispatch_unavailable || uncertain || notQueued || Object.values(st.evidence || {}).some(x => x.state === "failed")
        ? "error" : settled(st.captures) ? "done" : "pending", compact };
  }

  // --- the outbox (OUTBOX_KEY above) ---------------------------------------------------------------------------------
  const outboxNow = () => Date.now();
  const stopTimer = t => { try { if (t != null) root.clearTimeout?.(t); } catch {} };
  function outboxSave() {
    try {
      outboxStorage?.setItem(OUTBOX_KEY, JSON.stringify([...outbox.values()].slice(-50).map(x =>
        ({ sid: x.sid, text: x.text, clientId: x.clientId, at: x.at, tries: x.tries, checkFirst: !!x.checkFirst, reason: x.reason || "" }))));
    } catch {}                                  // the in-memory outbox still retries in this view
  }
  function outboxLoad(storage) {
    if (outboxLoaded) return;
    outboxLoaded = true; outboxStorage = storage;
    const now = outboxNow();
    try {
      for (const x of JSON.parse(storage?.getItem(OUTBOX_KEY) || "[]"))
        if (typeof x.sid === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(x.sid) && typeof x.text === "string" && x.text.length <= 2000
            && typeof x.clientId === "string" && /^[A-Za-z0-9_-]{8,96}$/.test(x.clientId) && Number.isFinite(x.at)
            && now - x.at <= OUTBOX_MAX_MS)
          // after a reload each asks the server's receipt before it posts again: the last POST may have landed
          outbox.set(x.clientId, { ...x, tries: x.tries | 0, checkFirst: true, due: now });
    } catch {}
    for (const entry of outbox.values()) outboxSchedule(entry, 1000);
  }
  function queued(sid) { return [...outbox.values()].filter(x => x.sid === sid); }
  function outboxView(sid) {
    const rows = queued(sid);
    if (!rows.length) return null;
    const wait = Math.max(0, Math.round((Math.min(...rows.map(x => x.due || 0)) - outboxNow()) / 1000));
    return { state: "queued", text: `⟳ ${rows.length === 1 ? "Note" : rows.length + " notes"} not sent yet - retrying${wait ? ` in ${wait} s` : " now"}`,
      title: rows.map(x => `Waiting to send: "${x.text}"` + (x.reason ? ` (${x.reason})` : "")).join("\n")
        + "\nEach is filed once, with its own submission ID. Click to retry now." };
  }
  function outboxPaint(sid, kind, ...args) {
    for (const p of [...(painters.get(sid) || [])]) { try { p[kind](...args); } catch {} }
  }
  function outboxSchedule(entry, delay) {
    stopTimer(entry.timer);
    entry.due = outboxNow() + delay;
    if (typeof root.setTimeout === "function") {
      entry.timer = root.setTimeout(() => { entry.timer = null; outboxRun(entry); }, delay);
      entry.timer?.unref?.();                   // (node: a waiting retry never keeps a test process alive)
    }
    outboxSave();
    outboxPaint(entry.sid, "queued", outboxView(entry.sid));
  }
  function outboxRetry(entry, reason) {
    entry.tries = (entry.tries | 0) + 1;
    entry.reason = String(reason || "").slice(0, 200);
    if (outboxNow() - entry.at > OUTBOX_MAX_MS) return outboxGiveUp(entry, `not delivered in ${OUTBOX_MAX_MS / 60000} min: ${entry.reason}`);
    outboxSchedule(entry, OUTBOX_BACKOFF_MS[Math.min(entry.tries - 1, OUTBOX_BACKOFF_MS.length - 1)]);
  }
  function outboxGiveUp(entry, why) {
    stopTimer(entry.timer);
    outbox.delete(entry.clientId); outboxSave();
    outboxPaint(entry.sid, "failed", entry, why);
    return null;
  }
  function outboxDelivered(entry, out) {
    stopTimer(entry.timer);
    outbox.delete(entry.clientId); outboxSave();
    outboxPaint(entry.sid, "delivered", entry, out);
    return out;
  }
  // one attempt now: the receipt first when the last answer was lost, then the POST with the note's own ID
  function outboxRun(entry) {
    if (entry.running) return entry.running;
    if (!outbox.has(entry.clientId)) return Promise.resolve(null);
    stopTimer(entry.timer);
    const api = apis.get(entry.sid), at = encodeURIComponent(entry.sid);
    if (!api) { outboxRetry(entry, "waiting for the app"); return Promise.resolve(null); }
    entry.running = (async () => {
      let phase = "receipt";
      try {
        if (entry.checkFirst) {
          let r;
          try { r = await api(`/api/sessions/${at}/coach/submissions/${encodeURIComponent(entry.clientId)}`); }
          catch (e) {
            if (/^404\b/.test(String(e?.message))) return outboxGiveUp(entry, "Delivery unconfirmed: this server keeps no receipts; check the coaching ticket before sending it again");
            throw e;
          }
          if (r?.session_id !== entry.sid || r?.client_id !== entry.clientId)
            return outboxGiveUp(entry, "Delivery unconfirmed: check the coaching ticket before sending it again");
          if (r.state === "saved" && r.result?.message_id) return outboxDelivered(entry, r.result);
          if (r.state !== "missing") { outboxRetry(entry, "the server is still filing it"); return null; }
          entry.checkFirst = false;               // the server never got it: post it again, same ID
        }
        phase = "post";
        return outboxDelivered(entry, await api(`/api/sessions/${at}/coach`, { text: entry.text, client_id: entry.clientId }));
      } catch (e) {
        const msg = String(e?.message || e);
        if (phase === "post" && definitive(e)) return outboxGiveUp(entry, msg.slice(0, 200));
        if (phase === "post" && !notSent(e)) entry.checkFirst = true;   // an answer lost on the way: the receipt first
        outboxRetry(entry, notSent(e) ? "not reachable: " + msg.slice(0, 120) : msg.slice(0, 160));
        return null;
      } finally { entry.running = null; }
    })();
    return entry.running;
  }
  function outboxAdd(sid, text, clientId, at, checkFirst, reason) {
    const entry = outbox.get(clientId) || { sid, text, clientId, at, tries: 0 };
    entry.checkFirst = !!checkFirst;
    outbox.set(clientId, entry);
    outboxRetry(entry, reason);
    return entry;
  }
  // run every waiting note of a session (or all) now: "click to retry now", and the tests
  function outboxFlush(sid) {
    return Promise.all([...outbox.values()].filter(x => !sid || x.sid === sid).map(outboxRun));
  }

  function create({ sid, api, render, interval = 1500, timeout = 180000, hold = HOLD_MS, now = () => Date.now(),
                    sleep = ms => new Promise(r => setTimeout(r, ms)), idempotent = false,
                    makeId = () => root.crypto?.randomUUID?.() || `coach-${Date.now()}-${Math.random().toString(36).slice(2)}`,
                    delivered = () => {}, undelivered = () => {} }) {
    // delivered(text, out): a note the outbox filed after it had waited; undelivered(text, why): one it gave up on
    let generation = 0, disposed = false;
    let storage;
    try { storage = root.sessionStorage; } catch {} // sandboxed documents can deny storage
    function keepAttempt(value) {
      if (value) retries.set(sid, value); else retries.delete(sid);
      try {
        const rows = storedRetries(storage, now()).filter(x => x.sid !== sid);
        if (value) rows.push({sid, text: value.text, clientId: value.clientId, at: value.at,
          uncertain: !!value.uncertain, lookupSupported: !!value.lookupSupported, replayBlocked: !!value.replayBlocked});
        storage?.setItem(RETRY_KEY, JSON.stringify(rows.slice(-50)));
      } catch {} // the in-memory identity still protects retries in this view
    }
    const sending = new Map();
    const paint = (gen, view) => { if (!disposed && gen === generation) render(view); };
    const folded = st => noteView(st, true);

    // poll the note's status until every capture settled (or timeout), then fold it; only the newest note paints
    async function follow(out, gen, since = now()) {
      let st = { ...out, summary: out.summary || null };
      while (!settled(st.captures) && !disposed && gen === generation && now() - since < timeout) {
        await sleep(interval);
        if (disposed || gen !== generation) return st;
        try { st = { ...out, ...await api(`/api/sessions/${encodeURIComponent(sid)}/coach/${encodeURIComponent(out.message_id)}`) }; }
        catch (e) {                             // a Wi-Fi blip / Spark restart: the next poll catches up
          if (/^404\b/.test(String(e && e.message))) {
            paint(gen, { text: "Coaching note no longer available", title: String(e.message), state: "error", compact: true });
            return st;
          }
          continue;
        }
        paint(gen, noteView(st));
      }
      if (settled(st.captures) && !disposed && gen === generation) {
        await sleep(hold);
        paint(gen, folded(st));
      } else if (!disposed && gen === generation && now() - since >= timeout) {
        paint(gen, { text: `Note #${st.note ?? "?"} sent · captures still pending`, title: detailText(st), state: "error", compact: true });
      }
      return st;
    }

    // {receipt, unsupported}: unsupported when the server keeps no receipts (an old server) or answers for another
    // submission - a replay is never safe then; no receipt and not unsupported: the lookup did not get through (yet)
    async function recover(clientId) {
      let receipt = null;
      for (let i = 0; i < 3 && !disposed; i++) {
        if (i) await sleep(500);
        try { receipt = await api(`/api/sessions/${encodeURIComponent(sid)}/coach/submissions/${encodeURIComponent(clientId)}`); }
        catch (e) { if (/^404\b/.test(String(e?.message))) return { receipt: null, unsupported: true }; continue; }
        if (receipt?.session_id !== sid || receipt?.client_id !== clientId) return { receipt: null, unsupported: true };
        if (receipt.state === "saved" && receipt.result?.message_id) return { receipt, unsupported: false };
        if (!["missing", "pending"].includes(receipt.state)) return { receipt: null, unsupported: true };
      }
      return { receipt, unsupported: false };
    }

    async function submit(text) {
      const gen = ++generation;
      paint(gen, { text: "Sending note…", title: "", state: "sending" });
      let out;
      const previous = retries.get(sid) || storedRetries(storage, now()).find(x => x.sid === sid);
      const clientId = idempotent ? previous?.text === text ? previous.clientId : makeId() : null;
      const attempt = { ...(previous?.text === text ? previous : {}), text, clientId, at: previous?.text === text ? previous.at : now() };
      if (clientId) keepAttempt(attempt);
      try {
        // An old server ignored retry IDs. After an ambiguous response, never replay a POST to it.
        if (previous?.text === text && previous.uncertain && (previous.replayBlocked || !previous.lookupSupported)) {
          const { receipt } = await recover(clientId);
          attempt.lookupSupported = !!receipt;
          if (receipt?.state === "saved") out = receipt.result;
          else if (previous.replayBlocked || receipt?.state !== "missing") throw Object.assign(Error("Delivery unconfirmed; check the coaching ticket before resending."), { receiptChecked: true });
        }
        if (!out) {
          // F5 during this POST is also an ambiguous delivery, even before its timeout handler executes.
          if (clientId) keepAttempt({ ...attempt, uncertain: true, replayBlocked: true });
          out = await api(`/api/sessions/${encodeURIComponent(sid)}/coach`, { text, ...(clientId ? { client_id: clientId } : {}) });
        }
      }
      catch (e) {
        const msg = String(e?.message || e);
        const fenced = previous?.text === text && previous.uncertain && previous.replayBlocked;
        if (clientId && !e.receiptChecked && !fenced && notSent(e)) {
          // the request never left this PC (2026-11-10: "Remote gBox is offline" was taken for a lost answer and the
          // note stayed blocked for a day): nothing reached the server, so the outbox sends the same ID again
          keepAttempt({ ...attempt, uncertain: false, replayBlocked: false });
          outboxAdd(sid, text, clientId, attempt.at, false, "not reachable: " + msg.slice(0, 120));
          throw Object.assign(e, { queued: true });
        }
        const uncertain = !!clientId && !definitive(e);
        if (uncertain) {
          const r = e.receiptChecked ? { receipt: null, unsupported: true } : await recover(clientId);
          attempt.uncertain = true; attempt.lookupSupported ||= !!r.receipt;
          attempt.replayBlocked = !!previous?.replayBlocked || r.unsupported;
          keepAttempt(attempt);
          if (r.receipt?.state === "saved") out = r.receipt.result;
          else if (!attempt.replayBlocked) {
            // the server never got it ("missing": the same ID goes again) or its receipt did not get through yet (asked
            // again before any POST): either way the outbox keeps it until it is filed
            outboxAdd(sid, text, clientId, attempt.at, r.receipt?.state !== "missing", msg.slice(0, 160));
            throw Object.assign(e, { queued: true });
          } else paint(gen, { text: "Delivery unconfirmed; checking the saved note is safe. Do not resend as a new note.",
            title: msg, state: "error" });
        } else {
          if (clientId) keepAttempt(null);
          paint(gen, { text: "✗ Note not sent: " + msg.slice(0, 160), title: msg, state: "error" });
        }
        if (!out) throw e;
      }
      return shown(out, gen, clientId);
    }

    // a filed note on screen: its status, then its captures followed
    function shown(out, gen, clientId) {
      if (idempotent && !out.change_id && out.dispatch_state !== "failed") out = { ...out, task_dispatch_unavailable: true };
      if (retries.get(sid)?.clientId === clientId) keepAttempt(null);
      paint(gen, noteView(out));
      track(out, gen, now());                   // not awaited: the box is free for the next note at once
      return out;
    }

    function send(raw) {
      const text = String(raw ?? "").trim();
      if (!text || disposed) return Promise.resolve(null);
      if (sending.has(text)) return sending.get(text);
      const waiting = queued(sid).find(x => x.text === text);
      // the same words again while they wait in the outbox: retried now, with their own ID (never a second note)
      const task = (waiting ? outboxRun(waiting) : submit(text)).finally(() => sending.delete(text));
      sending.set(text, task);
      return task;
    }

    // the outbox reports here while this view shows the session (a remounted view takes over)
    const painter = {
      queued: view => { if (view && !disposed) paint(++generation, view); },
      delivered: (entry, out) => {
        if (disposed) return;
        if (retries.get(sid)?.clientId === entry.clientId) keepAttempt(null);
        shown(out, ++generation, entry.clientId);
        delivered(entry.text, out);
      },
      failed: (entry, why) => {
        if (disposed) return;
        if (retries.get(sid)?.clientId === entry.clientId) keepAttempt(null);
        paint(++generation, { text: "✗ Note not sent: " + why, title: `"${entry.text}"\n${why}`, state: "error" });
        undelivered(entry.text, why);
      },
    };
    if (!painters.has(sid)) painters.set(sid, new Set());
    painters.get(sid).add(painter);
    if (api) apis.set(sid, api);
    outboxLoad(storage);
    {
      const view = outboxView(sid);                // a remounted view shows what still waits
      if (view) paint(++generation, view);
    }

    function track(out, gen, at) {
      recent.set(sid, { out, at });
      return follow(out, gen, at).then(st => {
        const r = recent.get(sid);
        if (r && r.out.message_id === out.message_id && st && st.captures)
          recent.set(sid, { out: { ...out, ...st }, at });
        return st;
      });
    }

    // a header drawn again (another view of the same game, the app reloading it): the newest note's status comes back
    // and, while it still captures, keeps updating
    function resume() {
      const r = recent.get(sid);
      if (!r || now() - r.at > timeout) return false;
      const gen = ++generation;
      if (settled(r.out.captures)) { paint(gen, folded(r.out)); return true; }   // settled: its folded line, nothing to poll
      paint(gen, noteView(r.out));
      track(r.out, gen, r.at);
      return true;
    }

    return { send, resume, retryNow: () => outboxFlush(sid), waiting: () => queued(sid).length,
             dispose() { disposed = true; painters.get(sid)?.delete(painter); } };
  }

  function html(sid) {
    return `<span class="coach" data-coach data-sid="${ESC(sid)}">` +
      `<button type="button" class="coach-cmds" data-coach-cmds aria-haspopup="menu" aria-expanded="false" ` +
      `aria-label="Instant commands for the bot" title="Instant commands: the bot does it at once">▾</button>` +
      `<input type="text" class="coach-in" maxlength="2000" autocomplete="off" placeholder="${ESC(PLACEHOLDER)}" ` +
      `aria-label="Coach the autoplay (Enter sends the note)" title="Tell the autoplay what to do better. Each note goes to this ` +
      `game's coaching ticket with a frame, a save state (gBox's own slot, never yours) and the game's RAM.">` +
      // a visible send for dictation and the mouse (2026-11-10: a dictated critique sat unsent in the hidden PiP bar)
      `<button type="button" class="coach-send" data-coach-send aria-label="Send this critique (Enter)" ` +
      `title="Send this critique to the bot's coaching ticket (Enter)">➤</button>` +
      `<span class="coach-st mut" data-coach-status role="status" aria-live="polite"></span></span>`;
  }

  // the styles go in when the script loads: the shell's dictation wraps the input (🎤) from the box's computed style
  function style(doc) {
    if (doc && doc.head && doc.getElementById && !doc.getElementById("autoplay-coach-css")) {
      const st = doc.createElement("style"); st.id = "autoplay-coach-css"; st.textContent = CSS; doc.head.append(st);
    }
  }

  function mount(host, { sid, api, onSent, onState, delivered: onDelivered, undelivered: onUndelivered, ...opts }) {
    style(host && host.ownerDocument);
    const box = host && (host.matches && host.matches("[data-coach]") ? host : host.querySelector("[data-coach]"));
    const input = box && box.querySelector("input"), status = box && box.querySelector("[data-coach-status]");
    if (!input || !status) return null;
    const render = v => {
      status.textContent = v.text || ""; status.title = v.title || ""; status.dataset.state = v.state || "";
      input.readOnly = v.state === "sending";
      if (onState) onState(v);
    };
    // a note the outbox gave up on comes back into the box (never lost); one it filed later leaves the box if still there
    const giveBack = text => { if (!input.value) { input.value = text; drafts.set(sid, text); } };
    const hooks = { delivered: (text, out) => { if (String(input.value || "").trim() === text) { input.value = ""; drafts.delete(sid); }
                                               if (onSent) { try { onSent(out); } catch {} }
                                               if (onDelivered) { try { onDelivered(text, out); } catch {} } },
                    undelivered: (text, why) => { giveBack(text); if (onUndelivered) { try { onUndelivered(text, why); } catch {} } } };
    const ctl = create({ sid, api, render, ...hooks, ...opts });
    // an unsent critique carried from the previous game of the PiP (MercMode moved on): sent to the game it was for
    let carried = null;
    const others = new Map();
    const ctlFor = target => target === sid ? ctl : others.get(target) ||
      (others.set(target, create({ sid: target, api, render, ...hooks, ...opts })), others.get(target));
    const cmdButton = box.querySelector("[data-coach-cmds]");
    let menu = null, subPanel = null, unlisten = null;
    const closeMenu = () => {
      if (unlisten) { unlisten(); unlisten = null; }
      if (menu) { menu.remove(); menu = null; cmdButton?.setAttribute("aria-expanded", "false"); }
      closeSub();
    };
    const closeSub = () => { if (subPanel) { subPanel.remove(); subPanel = null; } };

    // read the live bot-logic state for the session's title; null when the game has none
    async function readBotLogic() {
      try {
        let j = await api("/api/jobs", { tool: "re5_mods", agent_use: false,
          input: { session_id: sid, op: "bot_logic" } }, "POST");
        for (let i = 0; i < 120 && j && ["queued", "running"].includes(j.state); i++) {
          await new Promise(r => setTimeout(r, 500));
          j = await api(`/api/jobs/${encodeURIComponent(j.id)}`, undefined, "GET");
        }
        if (j?.state !== "succeeded") return null;
        const out = j.output?.result;
        return out && out.verified === true && Array.isArray(out.knobs) ? out : null;
      } catch { return null; }
    }

    // write one knob back through bot_logic and return the refreshed view
    async function writeBotLogic(name, value) {
      let j = await api("/api/jobs", { tool: "re5_mods", agent_use: false,
        input: { session_id: sid, op: "bot_logic", values: { [name]: value } } }, "POST");
      for (let i = 0; i < 120 && j && ["queued", "running"].includes(j.state); i++) {
        await new Promise(r => setTimeout(r, 500));
        j = await api(`/api/jobs/${encodeURIComponent(j.id)}`, undefined, "GET");
      }
      if (j?.state !== "succeeded") throw new Error(j?.error?.message || j?.error || "The control job did not succeed.");
      const out = j.output?.result;
      if (!out || out.verified !== true || !Array.isArray(out.knobs)) throw new Error("The server returned no settings.");
      return out;
    }

    function subHtml(view, cmdId, message = "") {
      const title = view?.title;
      const wanted = COMMAND_KNOBS[title]?.[cmdId] || [];
      const knobs = view?.knobs || [];
      const mapped = knobs.filter(k => wanted.includes(k.name));
      if (!title || !mapped.length)
        return `<h4>${ESC(cmdId)}</h4><p class="cs-empty">No live bot-logic mapping for this command${title ? ` on ${ESC(title.toUpperCase())}` : ""} yet.</p>`;
      const rows = mapped.map(k => {
        const tip = ESC(k.help || "");
        if (k.kind === "bool")
          return `<label class="cs-row" title="${tip}"><span>${ESC(k.label)}</span><input type="checkbox" data-cs="${ESC(k.name)}"${k.value ? " checked" : ""}></label>`;
        return `<div class="cs-row" title="${tip}"><span>${ESC(k.label)}</span><output data-cs-out="${ESC(k.name)}">${ESC(k.value)}</output>`
          + `<input type="range" data-cs="${ESC(k.name)}" min="${k.min}" max="${k.max}" step="${k.step}" value="${ESC(k.value)}" aria-label="${ESC(k.label)}">`
          + (k.help ? `<small>${tip}</small>` : "") + `</div>`;
      }).join("");
      return `<h4>${ESC((COMMANDS.find(c => c[0] === cmdId) || [])[1] || cmdId)} · ${ESC(title.toUpperCase())}</h4>`
        + `<p class="cs-msg" role="status">${ESC(message)}</p><fieldset>${rows}</fieldset>`;
    }

    async function openSub(cmdId, anchorRect) {
      closeSub();
      const doc = box.ownerDocument;
      subPanel = doc.createElement("div"); subPanel.className = "coach-sub";
      subPanel.innerHTML = `<h4>Loading…</h4>`;
      Object.assign(subPanel.style, { left: Math.max(4, anchorRect.right + 4) + "px", top: Math.max(4, anchorRect.top) + "px" });
      doc.body.append(subPanel);
      const view = await readBotLogic();
      if (!subPanel) return;                                     // closed while reading
      if (!view) { subPanel.innerHTML = `<h4>Live controls</h4><p class="cs-empty">This game has no live bot-logic on its PC (RE5 / RE6 Switch only for now).</p>`; return; }
      subPanel.innerHTML = subHtml(view, cmdId);
      subPanel.addEventListener("change", async e => {
        const el = e.target, name = el?.dataset?.cs;
        if (!name || !subPanel) return;
        const value = el.type === "checkbox" ? el.checked : Number(el.value);
        const row = subPanel.querySelector(`[data-cs-out="${name}"]`);
        if (row) row.textContent = value;
        const msg = subPanel.querySelector(".cs-msg");
        if (msg) msg.textContent = "Applying…";
        try {
          const next = await writeBotLogic(name, value);
          if (!subPanel) return;
          const actual = next.knobs.find(k => k.name === name)?.value;
          if (typeof actual !== typeof value || (typeof value === "number" ? !Number.isFinite(actual) || Math.abs(actual - value) > 0.0001 : actual !== value))
            throw new Error("The bot did not confirm the new value.");
          if (msg) msg.textContent = "";
        } catch (err) {
          if (msg) msg.textContent = err.message || String(err);
        }
      });
      subPanel.addEventListener("input", e => {
        const n = e.target?.dataset?.cs, o = n && subPanel?.querySelector(`[data-cs-out="${n}"]`);
        if (o) o.textContent = e.target.value;
      });
    }

    async function command(id) {
      closeMenu();
      const label = (COMMANDS.find(c => c[0] === id) || [])[1] || id;
      render({ state: "sending", text: `${label}…` });
      try {
        const out = await api(`/api/sessions/${encodeURIComponent(sid)}/directive`, { command: id });
        render({ state: "done", text: `${label} · sent`, title: out?.directive?.label || "" });
        if (Number.isFinite(out?.directive?.seq)) confirm(label, out.directive);   // not awaited
      } catch (error) { render({ state: "error", text: error.message || "Command not sent", title: error.message || "" }); }
    }
    // what the bot made of a command (operator 2026-11-10: "make sure that when I use one of the quick commands ... it's
    // able to take those commands into consideration"): its telemetry (every 5 s) carries directive_seq and the bot's own
    // directive_status ("acting: fight", "mine due now ...", "... switched off"), shown beside the box
    let confirming = 0;
    async function confirm(label, row) {
      const mine = ++confirming, wait = ms => new Promise(r => { const t = root.setTimeout?.(r, ms); t?.unref?.(); if (t == null) r(); });
      for (let i = 0; i < 9 && mine === confirming; i++) {
        await wait(1000);
        let tel;
        try { tel = await api(`/api/autoplay/telemetry/${encodeURIComponent(sid)}`); } catch { continue; }
        const st = tel?.stats || {};
        if (mine !== confirming) return;
        if (st.directive_seq === row.seq) {
          const said = st.directive_status || (st.directive_active ? "acting: " + st.directive_active : "received");
          render({ state: "done", text: `${label} · bot: ${String(said).slice(0, 80)}`, title: `${row.label}\nThe bot: ${said}` });
          return;
        }
      }
      if (mine === confirming)
        render({ state: "error", text: `${label} · sent, but the bot has not reported it`,
                 title: `${row.label}\nNo live bot telemetry has acknowledged command #${row.seq} yet.` });
    }
    if (cmdButton) {
      cmdButton.addEventListener("click", e => {
        e.preventDefault(); e.stopPropagation();
        if (menu) { closeMenu(); return; }
        const doc = box.ownerDocument, r = cmdButton.getBoundingClientRect();
        // a menu left by an earlier mount (the PiP re-mounts the box on a stream reconnect) never stays on screen
        if (doc.querySelectorAll) doc.querySelectorAll(".coach-menu").forEach(old => old.remove());
        menu = doc.createElement("div"); menu.className = "coach-menu"; menu.setAttribute("role", "menu");
        menu.innerHTML = COMMANDS.map(([id, label, hint]) =>
          `<div class="coach-row"><button type="button" role="menuitem" data-cmd="${ESC(id)}">${ESC(label)}<small>${ESC(hint)}</small></button>`
          + `<button type="button" class="coach-cog" data-cog="${ESC(id)}" title="Tune what this command drives" aria-label="Tune ${ESC(label)}">⚙</button></div>`).join("");
        Object.assign(menu.style, { left: Math.max(4, r.left) + "px", top: r.bottom + 4 + "px" });
        menu.addEventListener("click", ev => {
          const b = ev.target.closest("[data-cmd]");
          if (b) { ev.stopPropagation(); command(b.dataset.cmd); return; }
          const g = ev.target.closest("[data-cog]");
          if (g) { ev.stopPropagation(); openSub(g.dataset.cog, g.getBoundingClientRect()); }
        });
        menu.addEventListener("keydown", ev => { ev.stopPropagation(); if (ev.key === "Escape") { closeMenu(); cmdButton.focus(); } });
        doc.body.append(menu); cmdButton.setAttribute("aria-expanded", "true"); menu.querySelector("button")?.focus();
        // closes on a click anywhere else, on the pointer going to the native game surface (the document loses focus:
        // no DOM click ever arrives from it - operator 2026-10-26: "close dropdowns when i click away. I cant close this
        // now"), on the view being hidden, and on Escape; every path removes its listeners
        const away = ev => { if (menu && !menu.contains(ev.target) && ev.target !== cmdButton) closeMenu(); };
        const win = doc.defaultView;
        doc.addEventListener("mousedown", away, true); doc.addEventListener("pointerdown", away, true);
        if (win && win.addEventListener) win.addEventListener("blur", closeMenu);
        doc.addEventListener("visibilitychange", closeMenu);
        unlisten = () => {
          doc.removeEventListener("mousedown", away, true); doc.removeEventListener("pointerdown", away, true);
          if (win && win.removeEventListener) win.removeEventListener("blur", closeMenu);
          doc.removeEventListener("visibilitychange", closeMenu);
        };
      });
    }
    if (drafts.has(sid)) input.value = drafts.get(sid);
    input.addEventListener("input", () => {
      if (input.value) drafts.set(sid, input.value); else drafts.delete(sid);
      if (carried && String(input.value).trim() !== carried.text) carried = null;   // edited: it is for this game now
      if (status.dataset.state === "draft" && !String(input.value).trim()) render({ state: "", text: "" });
    });
    function sendBox() {
      const text = input.value;
      if (!String(text || "").trim()) return;
      const target = carried && text.trim() === carried.text ? carried.sid : sid;
      carried = null;
      input.value = ""; drafts.delete(sid); drafts.delete(target);
      ctlFor(target).send(text).then(out => { if (out && onSent) { try { onSent(out); } catch {} } },   // e.g. the game gets the keys back
        e => { if (!e?.queued) giveBack(text); });   // not sent: keep the words (a queued note is retried instead)
    }
    input.addEventListener("keydown", e => {
      e.stopPropagation();                      // the operator's words: never a page shortcut or game input
      if (e.key === "Escape") { input.blur(); return; }
      if (e.key !== "Enter" || e.isComposing || e.shiftKey) return;
      e.preventDefault();
      sendBox();
    });
    for (const ev of ["keyup", "keypress"]) input.addEventListener(ev, e => e.stopPropagation());
    // a critique left in the box (typed or dictated, never sent) says so instead of looking filed
    input.addEventListener("blur", () => {
      if (String(input.value || "").trim() && !["sending", "pending", "queued", "error"].includes(status.dataset.state))
        render({ state: "draft", text: "✎ Not sent - Enter or ➤", title: "This critique is still in the box: Enter or ➤ files it on this game's coaching ticket." });
    });
    const sendButton = box.querySelector("[data-coach-send]");
    sendButton?.addEventListener?.("mousedown", e => e.preventDefault());   // the caret stays in the box
    sendButton?.addEventListener?.("click", e => { e.preventDefault?.(); e.stopPropagation?.(); sendBox(); });
    status.addEventListener?.("click", () => {                              // a waiting note: retried now
      if (status.dataset.state === "queued") { ctl.retryNow(); for (const o of others.values()) o.retryNow(); }
      else if (status.dataset.state === "draft") { input.focus?.(); }
    });
    ctl.resume();
    return { send: ctl.send, input, status, command,
             // the compact window's ⚠ Flawed report: the same filing, retry and status as typed words
             report: text => ctl.send(text),
             // MercMode moved the PiP to another game with words still in the box: they stay, for the game they were for
             carry(fromSid, text) {
               const t = String(text || "").trim();
               if (!t || fromSid === sid || String(input.value || "").trim()) return false;
               input.value = t; carried = { sid: fromSid, text: t };
               render({ state: "draft", text: "✎ Unsent, for the previous game - Enter or ➤ sends it there",
                        title: `"${t}" was typed while the previous game played; Enter or ➤ files it on that game's ticket. Edit it to send it to this game instead.` });
               return true;
             },
             dispose() { closeMenu(); closeSub(); ctl.dispose(); for (const o of others.values()) o.dispose(); } };
  }

  const api = { html, mount, create, COMMANDS, COMMAND_KNOBS, statusText, compactText, detailText, settled, PLACEHOLDER, HOLD_MS,
                notSent, outboxFlush, _drafts: drafts, _recent: recent, _outbox: outbox };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxAutoplayCoach = api;
  if (root.document) style(root.document);
})(typeof globalThis !== "undefined" ? globalThis : this);
