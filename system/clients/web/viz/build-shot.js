// Screenshot of a build (Mods gallery card "Screenshot after launch", Builds tab "Screenshot"): one rule for every card.
//   1. A running session already runs this exact build (game + build; a staged <mod>~<build> copy, collection_mod or a
//      hot-swapped live_mod count as that build): capture a frame from it now. Never relaunch, never swap.
//   2. A session runs the same game with ANOTHER build: nothing changes on its own. The card says so and offers
//      "Capture from the running build instead" (the frame goes to that build's card) or "Switch to this build"
//      (session_swap with keep_state: the moment is kept); either takes a second, explicit click.
//   3. Nothing of this game runs: launch the build (never as a swap of another session), wait, capture.
// The frame goes to the card's in-game shots (POST /api/mods/{card}/thumb?append=true); it becomes the card's thumbnail
// when the card has none. 2026-10-13: the gallery's button swapped the operator's running Twin Snakes to another build.
// The server's twin of sessionBuild: gbox/built_mods.py session_build.
(function (root) {
  "use strict";
  const STAGED_SEP = "~";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const enc = encodeURIComponent;

  function sessionBuild(s) { return String(s?.live_mod || s?.collection_mod || s?.mod || "").split(STAGED_SEP)[0]; }
  function runningOf(sessions, gid) {
    return (sessions || []).filter(s => s && s.state === "running" && !s.stopping && s.game_id === gid)
      .sort((a, b) => (b.started || 0) - (a.started || 0));
  }
  // build = { game_id, name, card_id } -> { kind: "exact" | "other" | "none", session?, build? }
  function plan(build, sessions) {
    const same = runningOf(sessions, build.game_id);
    const exact = same.find(s => sessionBuild(s) === build.name);
    if (exact) return { kind: "exact", session: exact };
    if (same.length) return { kind: "other", session: same[0], build: sessionBuild(same[0]) };
    return { kind: "none" };
  }
  const titleOf = (b, fallback) => (b && (b.label || b.mod_title || b.display_name || b.name)) || fallback;
  // what the card offers when another build of the game is running (items: the builds the view knows, for the card)
  function choiceFor(build, p, items) {
    const item = p.build ? (items || []).find(i => i.game_id === build.game_id && i.name === p.build) : null;
    const running = p.build ? titleOf(item, p.build) : "the original game";
    return { session_id: p.session.session_id, build: p.build, running, card_id: item?.card_id || "",
             title: p.session.title || build.title || build.game_title || build.game_id, target: titleOf(build, build.name) };
  }
  // the choice block under a card; attr = the view's action attribute (data-mg / data-bv)
  function choiceHTML(c, attr = "data-mg") {
    const capture = c.card_id
      ? `<button class="act" type="button" ${attr}="shot-running" title="Capture a frame of the game as it runs now and add it to the card of ${ESC(c.running)}">Capture from the running build instead (adds to that build's card)</button>`
      : `<button class="act" type="button" ${attr}="shot-running" disabled title="${ESC(c.running)} has no build card to add a picture to">Capture from the running build instead (no card for ${ESC(c.running)})</button>`;
    return `<div class="bs-choice" role="group" aria-label="Screenshot choices">
      <div class="bs-q">${ESC(c.title)} is running <b>${ESC(c.running)}</b>, not this build. Nothing was changed.</div>
      <div class="bs-btns">${capture}<button class="act" type="button" ${attr}="shot-switch" title="Swap the running game to ${ESC(c.target)} (your moment is kept), then capture">Switch to this build</button>
      <button class="act" type="button" ${attr}="shot-cancel" title="Leave everything as it is">Cancel</button></div></div>`;
  }
  const CSS = `.bs-choice{border:1px solid var(--warn,#c9a227);border-radius:6px;padding:6px 8px;margin-top:4px;font-size:12px;background:#c9a22714}
    .bs-q{margin-bottom:5px}.bs-btns{display:flex;gap:6px;flex-wrap:wrap}`;

  async function capture(env, cardId, sid) {
    if (!cardId) throw new Error("this build has no mod card yet: refresh");
    return env.api(`/api/mods/${enc(cardId)}/thumb?append=true&session_id=${enc(sid)}`, {});
  }
  async function sessions(env) { return env.api("/api/sessions?include_ended=false").catch(() => []); }
  async function job(env, j, what) {
    const wait = env.wait || (ms => new Promise(r => setTimeout(r, ms)));
    for (let i = 0; i < 1800 && j && ["queued", "running"].includes(j.state); i++) {
      await wait(1000); j = await env.api("/api/jobs/" + j.id);
      if (j?.progress?.msg) env.msg?.(j.progress.msg + "…");
    }
    if (!j || j.state !== "succeeded") throw new Error(`${what}: ${j?.error || j?.state || "no answer"}`);
    return j;
  }

  // env = { api(path, body?), wait?(ms), msg?(text), launch(build) -> Promise (no swap of another session), items?() }
  // opts = { choice: "" | "running" | "switch", expect: the session the choice was offered for, settle: ms }
  // -> { captured: true, session_id, card_id, into } | { choice: {...}, stale?: true }
  async function run(env, build, opts = {}) {
    const wait = env.wait || (ms => new Promise(r => setTimeout(r, ms))), say = env.msg || (() => {});
    const settle = opts.settle ?? 12000;
    let p = plan(build, await sessions(env));
    if (p.kind === "exact") {
      if (!build.card_id) throw new Error("this build has no mod card yet: refresh");
      say("Capturing a frame of the running game…");
      await capture(env, build.card_id, p.session.session_id);
      return { captured: true, session_id: p.session.session_id, card_id: build.card_id, into: titleOf(build, build.name) };
    }
    if (p.kind === "other") {
      const c = choiceFor(build, p, env.items ? env.items() : []);
      if (!opts.choice) return { choice: c };
      if (opts.expect && opts.expect !== c.session_id) return { choice: c, stale: true };   // the game changed meanwhile
      if (opts.choice === "running") {
        if (!c.card_id) throw new Error(`${c.running} has no build card to add a picture to`);
        say(`Capturing a frame of ${c.running}…`);
        await capture(env, c.card_id, c.session_id);
        return { captured: true, session_id: c.session_id, card_id: c.card_id, into: c.running };
      }
      if (opts.choice !== "switch") throw new Error("unknown choice " + opts.choice);
      if (!build.card_id) throw new Error("this build has no mod card yet: refresh");
      say(`Switching the running game to ${c.target} (your moment is kept)…`);
      const j = await job(env, await env.api(`/api/sessions/${enc(c.session_id)}/swap`, { mod: build.name, keep_state: true }), "switch");
      const sid = j.output?.session_id || c.session_id;
      say("Running: waiting for the picture to settle…");
      await wait(settle);
      await capture(env, build.card_id, sid);
      return { captured: true, session_id: sid, card_id: build.card_id, into: titleOf(build, build.name), switched: true };
    }
    if (!build.card_id) throw new Error("this build has no mod card yet: refresh");
    say("Launching the build…");
    await env.launch(build);
    let s = null;
    for (let i = 0; i < 90; i++) {
      p = plan(build, await sessions(env));
      if (p.kind === "exact") { s = p.session; break; }
      await wait(2000);
    }
    if (!s) throw new Error("the build did not start a game session");
    say("Running: waiting for the picture to settle…");
    await wait(settle);
    say("Capturing a frame…");
    await capture(env, build.card_id, s.session_id);
    return { captured: true, session_id: s.session_id, card_id: build.card_id, into: titleOf(build, build.name), launched: true };
  }

  const api = { sessionBuild, runningOf, plan, choiceFor, choiceHTML, capture, run, CSS, STAGED_SEP };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxBuildShot = api;
})(typeof window !== "undefined" ? window : globalThis);
