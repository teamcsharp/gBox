/* Launch-screen mods: what a modded launch changes, shown on the loading screen (the web shell's #loader; the desktop
   app shows that shell, so its launch screen is the same one).
   - top band: a marquee of replacement pairs moving left to right, [original] -> [replacement] "KAS ← Amy Rose"
     (character slots first, then changed files as text tiles)
   - around the logo: a slideshow of the character pairs flying by (each card scales in from the left and out to the
     right, one side after the other)
   - bottom left: a compact list of what is active: the build's name (the Builds rename wins), writer and kind, slots
     replaced, cheats / patches / unlocks, files changed, other session mods kept on (game_link, unlocks, …), the build
     age and its verification, and the recorded build call
   Data: GET /api/builds/{game_id}/{name}/details (gbox/builds.py: slot <- donor rows with the game's own character
   matched by slot, the fit preview, codes, changed files, build call, verification) and GET /api/mods/built (the
   index: display name, donor previews, changes), both inside one 1.5 s budget; past it (or on any failure) only the
   names show. Thumbnails are preloaded once; nothing polls. A stock launch shows nothing.
   Reduced motion: the marquee stands still and the slides swap without moving.
   Node tests load the factory (tests/test_launch_mods.cjs). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory;
  else root.GBoxLaunchMods = factory(root);
})(typeof window === "undefined" ? globalThis : window, function (env) {
  "use strict";
  const BUDGET_MS = 1500;
  const SLIDE_MS = 1700;                                   // a new card every 1.7 s, alternating sides (each lives 3.4 s)
  const STILL_MS = 5000;                                   // reduced motion: swap the card's content, never move it
  const MAX_FILES = 12, MAX_PAIRS = 48;
  const MIN_ITEMS = 12;                                    // one copy of the marquee holds at least this many tiles (wide screens)
  const KINDS = { cast: "cast swap", character: "character swap", file: "file mod", cheats: "cheats", romhack: "ROM hack",
                  compile: "decomp / compile", showcase: "showcase", test: "test" };
  const CODE_WORDS = { cheat: ["cheat", "cheats"], code: ["code", "codes"], patch: ["patch", "patches"],
                       code_patch: ["code patch", "code patches"], unlock: ["unlock", "unlocks"], ram_write: ["RAM write", "RAM writes"],
                       hack: ["hack", "hacks"], changeset: ["change set", "change sets"], live: ["live change", "live changes"] };
  const LIVE_KIND = { game_link: "game link", cheats: "cheats", re_mods: "code patch", write_memory: "RAM write", poke: "RAM write",
                      freeze_memory: "RAM write", mgs_vr: "unlock", pso_mods: "patch", pso_drops: "drop table" };
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const enc = encodeURIComponent;
  const IMG_RX = /\.(png|jpe?g|webp|gif|svg)(\?|$)|\/preview(\?|$)|\/api\/artifacts\//i;

  // ---------------------------------------------------------------- words
  const pretty = slug => String(slug || "").replace(/[_-]+/g, " ").trim().replace(/\b[a-z]/g, c => c.toUpperCase());
  function slotLabel(slot, slotName) {                     // "fighter:kasumi" -> "Kasumi"; "KAS" stays "KAS"
    const raw = String(slotName || slot || "").split(":").pop().trim();
    if (!raw) return "?";
    return /[a-z]/.test(raw) && !/[A-Z]/.test(raw) ? pretty(raw) : raw;
  }
  function fmtAge(ts, now) {
    if (!ts) return "";
    const s = Math.max(0, now - ts);
    return s < 90 ? "built just now" : s < 5400 ? `built ${Math.round(s / 60)} min ago` : s < 129600 ? `built ${Math.round(s / 3600)} h ago`
      : `built ${Math.round(s / 86400)} days ago`;
  }
  const plural = (n, [one, many]) => `${n} ${n === 1 ? one : many}`;
  const imgOf = u => typeof u === "string" && u && IMG_RX.test(u) ? u : "";
  const artifact = sha => typeof sha==='string'&&/^[a-f0-9]{64}$/.test(sha)?'/api/artifacts/'+sha:'';
  function selfieFrom(meta) {
    const a=meta?.photo_skin_approval,source=artifact(a?.source_photo||meta?.selfie_photo);
    if(!a||!source)return null;
    const maps=(a.images||[]).filter(r=>artifact(r.before)&&artifact(r.after)).slice(0,4);
    const story=a.story,frames=(story?.frames||[]).filter(f=>artifact(f.sha256)&&['texture_projection','geometry_snapshot'].includes(f.kind)).slice(0,16)
      .map(f=>({img:artifact(f.sha256),label:String(f.label||'Recorded face snapshot'),kind:f.kind}));
    if(!frames.length&&maps.length)frames.push({img:artifact(maps[0].before),label:'Original face texture map',kind:'texture_map'},
      {img:artifact(maps[0].after),label:'Photo projected onto the texture map',kind:'texture_map'});
    if(!frames.length)return null;
    const deformed=story?.geometry==='deformed'&&frames.some(f=>f.kind==='geometry_snapshot');
    return {name:String(meta.name||meta.slug||'Photo character'),source,frames,
      maps:maps.map(r=>({before:artifact(r.before),after:artifact(r.after)})),
      geometry:deformed?'deformed':'unchanged',
      notice:deformed?'Recorded face-shape snapshots':'Photo texture projection · mesh shape unchanged'};
  }
  function selfieHTML(story, index, {mapUrl=u=>u,reduced=false}={}) {
    const frames=story.frames,frame=frames[reduced?frames.length-1:index%frames.length],previous=frames[Math.max(0,(index%frames.length)-1)],map=story.maps[0];
    const img=(url,alt,cls='')=>`<img class="${cls}" src="${ESC(mapUrl(url))}" alt="${ESC(alt)}" decoding="async" onerror="this.style.visibility='hidden'">`;
    return `<div class="lm-selfie-card${reduced?' lm-selfie-still':''}"><b>${ESC(story.name)}</b><div class="lm-face-row"><figure>${img(story.source,'Source selfie')}<figcaption>Source photo</figcaption></figure>
      <figure class="lm-face-result"><div class="lm-face-wipe">${img(previous.img,'Previous recorded face snapshot')}${img(frame.img,frame.label,'lm-face-next')}</div><figcaption>${ESC(frame.label)}</figcaption></figure></div>
      ${map?`<div class="lm-uv-row"><span>Original texture → photo texture</span><div class="lm-uv-wipe">${img(map.before,'Original UV texture')}${img(map.after,'Photo UV texture','lm-uv-next')}</div></div>`:''}
      <small>${ESC(story.notice)}</small></div>`;
  }

  // ---------------------------------------------------------------- which launch carries a mod
  // launch_game / session_swap jobs carry the build name in input.mod; "" (back to the original) is no mod.
  function modOfJob(job) {
    if (!job || !["launch_game", "session_swap"].includes(job.tool)) return null;
    const i = job.input || {}, g = i.game && typeof i.game === "object" ? i.game : {};
    const mod = String(i.mod || "").trim();
    return mod ? { gameId: String(i.game_id || g.game_id || g.id || ""), mod } : null;
  }

  // ---------------------------------------------------------------- the model: details + index entry -> what to show
  function pairsFrom(details, built) {
    const previews = new Map(((built && built.donor_previews) || []).map(p => [p.slug, p.url]));
    const rows = details && Array.isArray(details.characters) && details.characters.length ? details.characters : null;
    if (rows) return rows.slice(0, MAX_PAIRS).map(r => {
      const slug = (r.donors && r.donors[0]) || (r.donor && r.donor.slug) || "";
      const d = r.donor || {}, o = r.original;
      return { slot: String(r.slot || ""), slotName: slotLabel(r.slot, r.slot_name),
               original: o ? { name: o.name || slotLabel(r.slot, r.slot_name), img: imgOf(o.preview_url) } : null,
               donor: { name: d.name || pretty(slug) || "?", img: imgOf(r.fit_preview) || previews.get(slug) || (d.missing ? "" : imgOf(d.preview_url)) },
               status: r.status || "" };
    });
    return ((built && built.changes) || []).slice(0, MAX_PAIRS).map(c => {
      const slug = String(c.donor || "").split(",")[0].trim();
      return { slot: String(c.slot || ""), slotName: slotLabel(c.slot), original: null,
               donor: { name: pretty(slug) || "?", img: previews.get(slug) || "" }, status: c.status || "" };
    });
  }
  function filesFrom(details) {
    const rows = (details && details.modifications && details.modifications.files) || [];
    return rows.filter(f => f && f.path && f.change !== "image").slice(0, MAX_FILES)
      .map(f => ({ path: String(f.path), name: String(f.path).split("/").pop(), change: String(f.change || "changed") }));
  }
  function codeCounts(codes) {
    const out = {};
    for (const c of codes || []) { const t = CODE_WORDS[c && c.type] ? c.type : "live"; out[t] = (out[t] || 0) + 1; }
    return out;
  }
  function modelFrom({ gameId = "", mod = "", details = null, built = null, session = null, now = Date.now() / 1000 } = {}) {
    const d = details && typeof details === "object" && !details.local_only ? details : null;
    const b = built && typeof built === "object" ? built : null;
    const kinds = (d && d.kinds) || (b && b.kinds) || [];
    const verification = d && d.verification;
    const call = d && d.build_call && typeof d.build_call === "object" ? d.build_call : null;
    const model = {
      gameId, mod, selfies:[],
      label: (d && d.display_name) || (b && b.display_name) || (b && b.mod_title) || (d && d.label) || mod,
      originalTitle: (d && d.original_title) || (b && b.original_title) || "",
      writer: (d && d.writer) || (b && b.writer) || "",
      kinds: kinds.filter(k => k !== "test").map(k => KINDS[k] || k),
      pairs: mod ? pairsFrom(d, b) : [],
      files: mod ? filesFrom(d) : [],
      filesCount: d && d.modifications ? (d.modifications.files || []).filter(f => f && f.change !== "image").length : 0,
      codes: codeCounts(d && d.codes),
      age: fmtAge((d && d.built) || (b && b.built) || 0, now),
      verified: verification ? !!verification.verified : b ? !!b.verified : null,
      verifiedText: verification ? verification.text || "" : b ? (b.verified ? "verified in game" : "not verified in game yet") : "",
      buildCall: call && call.tool ? `${call.tool}${call.input && call.input.op ? " " + call.input.op : ""}` : "",
      session: (session || []).filter(s => s && s.title).map(s => ({ title: String(s.title), kind: s.kind || "" })),
      namesOnly: !d && !b,
    };
    if (model.label === model.originalTitle) model.originalTitle = "";
    return model;
  }
  // The patch mods this game keeps on across loads (the web shell's gbox_modkeep_<game>): their cards' titles and kinds.
  function sessionModsFrom(cards, ids) {
    const want = new Set(ids || []);
    return (Array.isArray(cards) ? cards : []).filter(c => c && want.has(c.id)).map(c => {
      const tools = [...new Set((c.calls || []).map(x => x && x.tool).filter(t => t && t !== "@launch"))];
      return { title: String(c.title || c.id), kind: [...new Set(tools.map(t => LIVE_KIND[t] || t.replace(/_/g, " ")))].join(", ") };
    });
  }
  const hasContent = m => !!m && (!!m.mod || m.session.length > 0);
  const thumbsOf = m => [...new Set([...m.pairs.flatMap(p => [p.original && p.original.img, p.donor.img]),
    ...(m.selfies||[]).flatMap(s=>[s.source,...s.frames.map(f=>f.img),...s.maps.flatMap(m=>[m.before,m.after])])].filter(Boolean))];

  // ---------------------------------------------------------------- markup
  const thumb = (url, label, cls, mapUrl) => `<span class="lm-th ${cls}"><i>${ESC(label)}</i>${url
    ? `<img src="${ESC(mapUrl(url))}" alt="" loading="eager" decoding="async" onerror="this.style.display='none'">` : ""}</span>`;
  function pairHTML(p, mapUrl) {
    const orig = p.original ? p.original.name : p.slotName;
    return `<span class="lm-pair" title="${ESC(`${orig} (${p.slotName}) replaced by ${p.donor.name}`)}">`
      + thumb(p.original && p.original.img, orig, "lm-orig", mapUrl) + `<b class="lm-arrow" aria-hidden="true">→</b>`
      + thumb(p.donor.img, p.donor.name, "lm-new", mapUrl) + `<span class="lm-cap">${ESC(p.slotName)} ← ${ESC(p.donor.name)}</span></span>`;
  }
  const fileHTML = f => `<span class="lm-pair lm-file" title="${ESC(f.path)}: ${ESC(f.change)}"><span class="lm-th lm-orig lm-txt"><i>${ESC(f.name)}</i></span>`
    + `<b class="lm-arrow" aria-hidden="true">→</b><span class="lm-th lm-new lm-txt"><i>${ESC(f.change)}</i></span><span class="lm-cap">${ESC(f.name)}</span></span>`;
  // The track holds its tiles twice: it slides from -50% to 0 (left to right) and the second copy takes the first's
  // place, so the loop has no seam (every tile carries its own right margin: both halves are exactly the same width).
  // A short list repeats inside one copy so the band is full on a wide screen.
  function marqueeHTML(m, { mapUrl = u => u, reduced = false } = {}) {
    const photos=(m.selfies||[]).flatMap(s=>s.frames.map((f,i)=>`<span class="lm-pair">${thumb(i?s.frames[i-1].img:s.source,i?'Previous face snapshot':'Source photo','lm-orig',mapUrl)}<b class="lm-arrow">→</b>${thumb(f.img,f.label,'lm-new',mapUrl)}<span class="lm-cap">${ESC(f.label)}</span></span>`));
    const items = [...photos,...m.pairs.map(p => pairHTML(p, mapUrl)), ...m.files.map(fileHTML)];
    if (!items.length) return "";
    const reps = reduced ? 1 : Math.max(1, Math.ceil(MIN_ITEMS / items.length));
    const once = items.join("").repeat(reps);
    const secs = Math.max(18, items.length * reps * 4.5);
    return `<div class="lm-band${reduced ? " lm-still" : ""}" aria-label="Replaced in this build">`
      + `<div class="lm-track${reduced ? "" : " lm-ltr"}" style="--lm-secs:${secs}s">${once}${reduced ? "" : `<span class="lm-copy" aria-hidden="true">${once}</span>`}</div></div>`;
  }
  function slideHTML(p, { mapUrl = u => u, reduced = false } = {}) {
    const orig = p.original ? p.original.name : p.slotName;
    return `<div class="lm-card${reduced ? " lm-still" : " lm-fly"}">`
      + thumb(p.original && p.original.img, orig, "lm-orig", mapUrl) + `<b class="lm-arrow" aria-hidden="true">→</b>`
      + thumb(p.donor.img, p.donor.name, "lm-new", mapUrl)
      + `<div class="lm-ccap"><b>${ESC(p.donor.name)}</b><span>replaces ${ESC(orig)}${orig !== p.slotName ? ` · ${ESC(p.slotName)}` : ""}</span></div></div>`;
  }
  function infoLines(m) {
    const lines = [];
    if (m.mod) {
      const head = [m.writer && `by ${m.writer}`, m.kinds.join(", ")].filter(Boolean).join(" · ");
      lines.push({ cls: "lm-name", html: `<b>${ESC(m.label)}</b>${m.originalTitle ? ` <span class="lm-mut">(${ESC(m.originalTitle)})</span>` : ""}${head ? ` <span class="lm-mut">${ESC(head)}</span>` : ""}` });
      const parts = [];
      if (m.pairs.length) parts.push(plural(m.pairs.length, ["slot replaced", "slots replaced"]));
      for (const [t, n] of Object.entries(m.codes)) parts.push(plural(n, CODE_WORDS[t]) + " active");
      if (m.filesCount) parts.push(plural(m.filesCount, ["file changed", "files changed"]));
      if (parts.length) lines.push({ cls: "lm-counts", html: ESC(parts.join(" · ")) });
      const state = [m.age, m.verifiedText].filter(Boolean).join(" · ");
      if (state) lines.push({ cls: "lm-state" + (m.verified ? " lm-ok" : m.verified === false ? " lm-warn" : ""), html: ESC(state) });
      if (m.buildCall) lines.push({ cls: "lm-call", html: `built with <code>${ESC(m.buildCall)}</code>` });
    }
    if (m.session.length) lines.push({ cls: "lm-session", html: `${m.mod ? "Also on" : "Mods on"}: ` + m.session.map(s =>
      `${ESC(s.title)}${s.kind ? ` <span class="lm-mut">(${ESC(s.kind)})</span>` : ""}`).join(", ") });
    return lines;
  }
  function infoHTML(m) {
    const lines = infoLines(m);
    return lines.length ? `<div class="lm-info" aria-label="Active mods">${m.mod ? `<small>MODDED BUILD</small>` : `<small>ACTIVE MODS</small>`}`
      + lines.map(l => `<div class="${l.cls}">${l.html}</div>`).join("") + `</div>` : "";
  }

  const CSS = `
.lm-layer { position:absolute; inset:0; pointer-events:none; }
.lm-band { position:absolute; left:0; right:0; top:0; height:108px; overflow:hidden; display:flex; align-items:center;
  -webkit-mask:linear-gradient(90deg,transparent,#000 7%,#000 93%,transparent); mask:linear-gradient(90deg,transparent,#000 7%,#000 93%,transparent); }
.lm-track { display:flex; flex:none; will-change:transform; }
.lm-track.lm-ltr { animation:lm-ltr var(--lm-secs,24s) linear infinite; }
.lm-copy { display:contents; }
.lm-band.lm-still { justify-content:center; } .lm-band.lm-still .lm-track { will-change:auto; }
@keyframes lm-ltr { from { transform:translateX(-50%); } to { transform:translateX(0); } }
.lm-pair { display:inline-flex; align-items:center; gap:6px; flex:none; position:relative; margin-right:18px; padding:6px 8px 20px; border-radius:10px;
  background:#00000059; border:1px solid #ffffff1c; }
.lm-th { position:relative; width:58px; height:58px; border-radius:7px; overflow:hidden; flex:none; display:flex; align-items:center; justify-content:center;
  background:linear-gradient(160deg,#ffffff1a,#ffffff08); box-shadow:0 0 0 1px #ffffff22 inset; }
.lm-th i { font:600 10px/1.15 system-ui,sans-serif; font-style:normal; color:#e9d3c9; text-align:center; padding:3px; word-break:break-word; max-height:100%; overflow:hidden; }
.lm-th img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; background:#1a0e0f; }
.lm-th.lm-new { box-shadow:0 0 0 1px #7ee0ff66 inset, 0 0 14px #7ee0ff2e; }
.lm-th.lm-txt { width:auto; min-width:58px; max-width:150px; padding:0 4px; }
.lm-arrow { color:#ffd2b0; font:700 16px system-ui,sans-serif; text-shadow:0 0 10px #ffb38a99; }
.lm-cap { position:absolute; left:8px; right:8px; bottom:3px; font:11px/14px system-ui,sans-serif; color:#f3e3dc; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; text-align:center; }
.lm-stage { position:absolute; left:0; right:0; top:44%; height:0; }
.lm-slot { position:absolute; top:-84px; width:min(300px,30vw); height:168px; }
.lm-slot.lm-l { right:calc(50% + min(13vh,110px) + 28px); } .lm-slot.lm-r { left:calc(50% + min(13vh,110px) + 28px); }
.lm-card { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; gap:10px; flex-wrap:wrap; align-content:center;
  padding:10px; border-radius:14px; background:#0000006b; border:1px solid #ffffff24; box-shadow:0 12px 34px #0009; opacity:0; }
.lm-card .lm-th { width:min(96px,9vw); height:min(96px,9vw); }
.lm-card .lm-arrow { font-size:22px; }
.lm-ccap { flex-basis:100%; text-align:center; font:12px/1.35 system-ui,sans-serif; color:#cdb3aa; }
.lm-ccap b { display:block; color:#f3e3dc; font-size:14px; font-weight:600; }
.lm-card.lm-fly { animation:lm-fly 3.4s cubic-bezier(.2,.75,.3,1) forwards; }
.lm-card.lm-still { opacity:1; }
@keyframes lm-fly { 0% { opacity:0; transform:translateX(-90px) scale(.55); } 20% { opacity:1; transform:translateX(0) scale(1); }
  75% { opacity:1; transform:translateX(14px) scale(1.04); } 100% { opacity:0; transform:translateX(110px) scale(.7); } }
.lm-info { position:absolute; left:14px; bottom:80px; max-width:min(380px,34vw); padding:8px 11px; border-radius:9px; background:#0000007a;
  border:1px solid #ffffff1f; font:12px/1.45 system-ui,sans-serif; color:#e9d3c9; text-shadow:none; }
.lm-info small { display:block; font-size:10px; letter-spacing:.12em; color:#ffb38a; margin-bottom:2px; }
.lm-info .lm-name b { color:#fff3ea; font-weight:600; }
.lm-info .lm-mut { color:#b39a92; }
.lm-info .lm-ok { color:#9be7b0; } .lm-info .lm-warn { color:#ffcf8a; }
.lm-info code { font:11px ui-monospace,Consolas,monospace; color:#dfe8ff; }
@media (max-width:820px), (max-height:560px) { .lm-stage { display:none; } }
@media (max-width:1000px), (max-height:640px) { .lm-info { max-width:calc(100% - 28px); } .lm-info .lm-call, .lm-info .lm-state { display:none; } }
@media (prefers-reduced-motion: reduce) { .lm-track.lm-ltr, .lm-card.lm-fly { animation:none; } .lm-card.lm-fly { opacity:1; } }
.lm-selfie-stage {position:absolute;left:18px;top:125px;width:min(420px,38vw);max-height:calc(100% - 260px);overflow:hidden;color:#f4eeee;font:12px/1.35 system-ui,sans-serif}
.lm-selfie-card {padding:12px;border:1px solid #9ecbff66;border-radius:12px;background:#111626dc;box-shadow:0 8px 30px #0007}
.lm-selfie-card>b {display:block;margin-bottom:8px}.lm-face-row {display:flex;gap:12px;align-items:center}.lm-face-row figure{margin:0;min-width:0;flex:1}
.lm-face-row figure:first-child{flex:.65}.lm-face-row img{width:100%;height:160px;object-fit:contain}.lm-face-row figcaption{color:#bec9e1;text-align:center;font-size:11px;margin-top:4px}
.lm-face-result{flex:1.4!important}.lm-face-wipe,.lm-uv-wipe{position:relative;overflow:hidden}.lm-face-next,.lm-uv-next{position:absolute;inset:0;animation:lm-face-reveal 1.5s ease-in-out both}
.lm-uv-row{display:flex;align-items:center;gap:10px;margin-top:8px;color:#bec9e1;font-size:11px}.lm-uv-wipe{width:100px;height:60px;flex:none}.lm-uv-wipe img{width:100%;height:100%;object-fit:contain}
.lm-uv-wipe img:first-child{animation:lm-texture-out 1.5s ease-in-out both}.lm-uv-next{animation:lm-texture-in 1.5s ease-in-out both}
.lm-selfie-card small{display:block;margin-top:8px;color:#b1c3db;font-size:11px}.lm-selfie-still .lm-face-next,.lm-selfie-still .lm-uv-next,.lm-selfie-still .lm-uv-wipe img:first-child{animation:none}
@keyframes lm-face-reveal {from{clip-path:inset(0 100% 0 0);transform:translateX(12px)}to{clip-path:inset(0);transform:translateX(0)}}
@keyframes lm-texture-out{to{transform:translateX(-100%);opacity:0}}@keyframes lm-texture-in{from{transform:translateX(100%)}to{transform:translateX(0)}}
@media(max-height:650px){.lm-face-row img{height:110px}.lm-uv-row{display:none}.lm-selfie-stage{top:115px}}
@media(max-width:820px){.lm-selfie-stage{width:calc(100% - 36px);top:116px;max-height:calc(100% - 260px)}.lm-face-row img{height:110px}}
@media(prefers-reduced-motion:reduce){.lm-face-next,.lm-uv-next,.lm-uv-wipe img:first-child{animation:none}}
`;

  // ---------------------------------------------------------------- loading inside the budget
  // fetchJson(path, signal) -> Promise<json>; sessionMods(signal) -> Promise<[{title, kind}]>. Every answer that is not
  // in by the deadline is dropped (its request aborted); a failure is the same as no answer.
  async function load({ fetchJson, gameId, mod, sessionMods = null, budgetMs = BUDGET_MS, setTimeout: st = env.setTimeout || setTimeout,
                        clearTimeout: ct = env.clearTimeout || clearTimeout, now = () => Date.now() } = {}) {
    if (!gameId || (!mod && !sessionMods)) return null;
    const Ctl = env.AbortController || (typeof AbortController === "function" ? AbortController : null);
    const ctl = Ctl ? new Ctl() : null, signal = ctl ? ctl.signal : undefined;
    let timer = null;
    const deadline = new Promise(resolve => { timer = st(() => { resolve(null); try { ctl && ctl.abort(); } catch (e) { /* ignore */ } }, budgetMs); });
    const within = p => Promise.race([Promise.resolve().then(p).catch(() => null), deadline]);
    const detailsPromise=mod ? within(() => fetchJson(`/api/builds/${enc(gameId)}/${enc(mod)}/details`, signal)) : Promise.resolve(null);
    const photoPromise=detailsPromise.then(d=>{
      const donors=[...new Set((d?.characters||[]).flatMap(r=>r.donors||[r.donor?.slug]).filter(Boolean))];
      return Promise.all(donors.filter(s=>/_photo_|selfie/i.test(s)).slice(0,2).map(slug=>within(()=>fetchJson('/api/characters/'+enc(slug),signal))));
    });
    const [details, built, session, photoRows] = await Promise.all([
      detailsPromise,
      mod ? within(() => fetchJson(`/api/mods/built?game_id=${enc(gameId)}&q=${enc(mod)}&limit=20`, signal)) : null,
      sessionMods ? within(() => sessionMods(signal)) : null,
      photoPromise,
    ]);
    const item = built && Array.isArray(built.items) ? built.items.find(x => x && x.name === mod) || null : null;
    const model=modelFrom({ gameId, mod, details, built: item, session: Array.isArray(session) ? session : [], now: now() / 1000 });
    const donors=[...new Set([...(details?.characters||[]).flatMap(r=>r.donors||[r.donor?.slug]).filter(Boolean),
      ...(item?.changes||[]).map(c=>String(c.donor||'').split(',')[0]).filter(Boolean)])];
    const candidates=photoRows.length?[]:donors.filter(s=>/_photo_|selfie/i.test(s)).slice(0,2);
    const photos=photoRows.length?photoRows:await Promise.all(candidates.map(slug=>within(()=>fetchJson('/api/characters/'+enc(slug),signal))));
    model.selfies=photos.map(selfieFrom).filter(Boolean);ct(timer);return model;
  }

  // ---------------------------------------------------------------- the controller on the loading screen
  function mount(host, opts = {}) {
    const doc = opts.document || env.document;
    const st = opts.setTimeout || env.setTimeout || setTimeout, ct = opts.clearTimeout || env.clearTimeout || clearTimeout;
    const mapUrl = opts.url || (u => u);
    const reduced = () => { try { return !!(env.matchMedia && env.matchMedia("(prefers-reduced-motion: reduce)").matches); } catch (e) { return false; } };
    if (doc && !doc.getElementById("lm-style")) {
      const s = doc.createElement("style"); s.id = "lm-style"; s.textContent = CSS; (doc.head || doc.body).appendChild(s);
    }
    const layer = doc.createElement("div"); layer.className = "lm-layer"; layer.setAttribute("aria-live", "off");
    // just above the visualizer canvas, under the logo, title, buttons and progress (they stay on top and clickable)
    const canvas = host.querySelector ? host.querySelector("canvas") : null;
    if (canvas && canvas.parentNode === host) host.insertBefore(layer, canvas.nextSibling); else host.appendChild(layer);
    let token = 0, timer = null, model = null, held = [], slideN = 0;

    function clear() {
      token++; ct(timer); timer = null; model = null; held = []; slideN = 0;
      layer.innerHTML = ""; layer.hidden = true;
    }
    function preload(urls) {
      const Img = env.Image;
      held = Img ? urls.map(u => { const im = new Img(); im.decoding = "async"; im.src = mapUrl(u); return im; }) : [];
    }
    function slide() {
      const m = model; if (!m || (!m.pairs.length&&!m.selfies?.length)) return;
      const still = reduced();
      if(m.selfies?.length){const slot=layer.querySelector('.lm-selfie-stage');
        if(slot)slot.innerHTML=selfieHTML(m.selfies[Math.floor(slideN/8)%m.selfies.length],slideN,{mapUrl,reduced:still});
      } else {
      const slot = layer.querySelector ? layer.querySelector(still || slideN % 2 === 0 ? ".lm-l" : ".lm-r") : null;
      if (slot) slot.innerHTML = slideHTML(m.pairs[slideN % m.pairs.length], { mapUrl, reduced: still });
      }
      slideN++;
      const t = token;
      timer = st(() => { if (t === token) slide(); }, still ? STILL_MS : SLIDE_MS);
    }
    function render(m) {
      model = m; ct(timer); timer = null; slideN = 0;
      if (!hasContent(m)) { layer.innerHTML = ""; layer.hidden = true; return; }
      const still = reduced();
      preload(thumbsOf(m));
      layer.innerHTML = marqueeHTML(m, { mapUrl, reduced: still })
        + (m.selfies?.length?'<div class="lm-selfie-stage" aria-label="Photo character construction snapshots"></div>':m.pairs.length ? `<div class="lm-stage" aria-hidden="true"><div class="lm-slot lm-l"></div><div class="lm-slot lm-r"></div></div>` : "")
        + infoHTML(m);
      layer.hidden = false;
      layer.dataset && (layer.dataset.motion = still ? "reduced" : "full");
      if (m.pairs.length||m.selfies?.length) slide();
    }
    // start({gameId, mod, sessionMods}): a stock launch (no mod, no session mods) clears and fetches nothing.
    async function start({ gameId, mod = "", sessionMods = null, fetchJson = opts.fetchJson } = {}) {
      clear();
      if (!gameId || (!mod && !sessionMods) || !fetchJson) return null;
      const t = token;
      let m = null;
      try { m = await load({ fetchJson, gameId, mod, sessionMods, budgetMs: opts.budgetMs || BUDGET_MS, setTimeout: st, clearTimeout: ct, now: opts.now }); }
      catch (e) { m = mod ? modelFrom({ gameId, mod }) : null; }
      if (t !== token || !m) return null;                  // a newer launch, or the loader went away
      render(m);
      return m;
    }
    clear();
    return { start, clear, render, el: layer, get model() { return model; }, get preloaded() { return held; } };
  }

  return { BUDGET_MS, SLIDE_MS, KINDS, CSS, modOfJob, modelFrom, load, mount, marqueeHTML, slideHTML, infoHTML, infoLines,
           pairsFrom, slotLabel, thumbsOf, hasContent, sessionModsFrom, selfieFrom, selfieHTML };
});
