/* Background task visual: a running job opens this only after its actual model/image loads.
   Queued/nonvisual tasks and unavailable assets never substitute decorative geometry.
   Shared verbatim by the web shell (/viz/process-popup.js) and the desktop app (../web/viz/…).
   "R" (bottom-right of the 3D view, and on each fitting row): the Retarget editor's Goals view on that model's donor,
   target game and slot (mount({retarget(o)}): the shell's opener); follow(jobId) shows a rebuild the editor queued. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory;
  else root.GBoxProcessPopup = factory(root);
})(typeof window === "undefined" ? globalThis : window, function (env) {
  "use strict";
  const doc = env.document;

  // ---- which background jobs are 3D model work ------------------------------------------
  const MODEL_TOOLS = new Set(["characters", "session_swap", "asset_convert", "open_in_blender", "blender_copy",
    "export_asset", "extract_pso_model", "extract_pso_area", "bevy_scene", "oot_models", "rom_export", "file_mod"]);
  const CHEAP_OPS = new Set(["list", "get", "coverage", "environments", "unplace", "plan", "status", "search", "summary"]);
  const NEVER_TOOLS = new Set(["session_op", "graphics", "launch_game", "autoplay", "tasks", "scan_library", "hash_game",
    "poke", "read_memory", "write_memory", "freeze_memory", "memory_search", "cheats", "get_frame", "browse", "pick",
    "video", "llm_complete", "provision_node", "echo_artifact", "zelda", "zelda_oot", "re6", "re_mods", "pso_mods",
    "gta_mods", "ac_mods", "re_inventory", "pso_inventory", "pso_drops", "unreal_script", "script_patch", "game_link",
    "live_link", "state_transfer", "ghidra_script", "analyze_binary", "rea_tools", "rea_resources", "read_rea_result"]);
  const STAGE_WORDS = /decimat|simplif|retarget|blender|\bglb\b|\bgltf\b|\bmesh(es)?\b|triangl|\brig(ging)?\b|weight paint|atlas\b|uv unwrap/i;

  function classify(job) {
    if (!job || !["queued", "running"].includes(job.state)) return false;
    if (fittingRows(job).length) return true;                              // a writer is fitting models (gbox.fit_events)
    const tool = job.tool || "";
    if (MODEL_TOOLS.has(tool)) return !CHEAP_OPS.has((job.input || {}).op);
    if (NEVER_TOOLS.has(tool)) return false;
    const msgs = [(job.progress || {}).msg].concat((job.progress_log || []).slice(-5)).filter(Boolean);
    return msgs.some(m => STAGE_WORDS.test(String(m)));
  }

  // Activity mode also follows RE, compilation, testing and service jobs. Cheap
  // polling/control calls are not useful work to display as automation.
  function activityJob(job) {
    if (!job || !['queued', 'running'].includes(job.state)) return false;
    if (classify(job)) return true;
    if (CHEAP_OPS.has((job.input || {}).op)) return false;
    return !!(job.agent_use || job.low_priority || (job.origin || {}).inspection_run);
  }
  function onWorker(job, worker) {
    if (!worker) return false; // Unknown machine must never show another PC's work.
    const names = [worker.id, worker.name].filter(Boolean);
    return job.state === 'running' ? names.includes(job.worker_id) : names.includes(job.require_worker);
  }
  function detailHTML(job, now = Date.now() / 1000) {
    const p = job.progress || {}, stamp = p.ts || job.started || job.created;
    const age = typeof stamp === 'number' ? Math.max(0, Math.floor(now - stamp)) : null;
    const rows = fittingRows(job), cur = rows.find(r => r.key === job.fitting?.current);
    const data = cur ? job.fitting.models[cur.key].stages || {} : {};
    return `<div class="pp-origin">${ESC(job.worker_name || job.worker_id || job.require_worker || 'Worker not assigned')} · Job ${ESC(job.id)}${job.parent_request_id ? ' · Request ' + ESC(job.parent_request_id) : ''}</div>
      <div class="pp-flow"><span class="${job.state==='queued'?'now':''}">Queued</span> → <span class="${job.state==='running'?'now':''}">Executing</span> → <span>Result</span> → <span>Verification pending</span></div>
      <div>${ESC(job.admission_wait?.reason || (job.state==='queued' ? 'Waiting for worker admission; execution has not started.' : age==null ? 'No timestamped progress reported yet.' : `Last worker update ${age}s ago${age>=30 ? '; waiting for the next reported step' : ''}.`))}</div>
      ${cur ? `<details open><summary>${ESC(cur.label)} · reported measurements</summary>${Object.entries(data).map(([k,v])=>`<div><b>${ESC(k)}</b> ${ESC(v.state)}<pre>${ESC(JSON.stringify(v.data || {}, null, 2))}</pre></div>`).join('')}</details>` : ''}`;
  }

  // ---- which of several live 3D jobs the window follows ----------------------------------
  function pick(jobs) {
    const live = jobs.filter(classify);
    live.sort((a, b) => {
      const sa = a.state === "running" ? 1 : 0, sb = b.state === "running" ? 1 : 0;
      if (sa !== sb) return sb - sa;                                        // running beats queued
      const ta = (a.progress || {}).ts || a.started || a.created || 0;
      const tb = (b.progress || {}).ts || b.started || b.created || 0;
      return tb - ta;                                                       // most recent activity wins
    });
    return { job: live[0] || null, others: Math.max(0, live.length - 1) };
  }

  function title(job) {
    const i = job.input || {}, op = i.op ? " · " + i.op : "";
    const model = i.character || i.mod || i.model || "";
    return `${job.tool}${op}${model ? " · " + model : ""}`;
  }

  function modelPath(job) {                                                 // the GLB actually being processed, when known
    const snap = snapshotOf(job);                                           // the writer's own fitted-mesh snapshot first
    if (snap) return snap;
    const i = job.input || {};
    if (i.character && MODEL_TOOLS.has(job.tool)) return `/api/characters/${encodeURIComponent(i.character)}/model`;
    return null;
  }
  function activityModelPath(job) {
    const f = job.fitting || {}, m = (f.models || {})[f.current];
    if (!m) return modelPath(job);
    return m.snapshot || (m.donor ? `/api/characters/${encodeURIComponent(m.donor)}/model` : null);
  }
  function visualOf(job) {
    const image=previewOf(job),model=activityModelPath(job);
    return image ? {kind:'image',path:image} : model ? {kind:'model',path:model} : null;
  }

  // ---- the Fitting view: every model a writer fits, stage by stage (gbox/fit_events.py -> job.fitting) ----------
  const STAGES = ["scale", "retarget", "proportion", "weights", "decimate", "encode", "write"];
  const STAGE_NAMES = { scale: "scale", retarget: "retarget", proportion: "proportion", weights: "weights",
    decimate: "decimate", encode: "encode", write: "write" };
  const COLLECT_STAGES = ["extract", "preview"];                          // characters op=collect (a reader's roster)
  const isCollect = job => ((job && job.fitting) || {}).kind === "collect";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const isSnapshot = p => typeof p === "string" && p.includes("/fitting/files/");

  function fittingRows(job) {
    const f = job && job.fitting;
    if (!f || !f.models || !Array.isArray(f.order)) return [];
    return f.order.filter(k => f.models[k]).map(k => {
      const m = f.models[k], st = m.stages || {};
      const names = STAGES.filter(s => st[s]).concat(Object.keys(st).filter(s => !STAGES.includes(s)));
      return { key: k, label: m.label || k, state: m.state || "pending", current: m.current || null, snapshot: m.snapshot || null,
        comparison: m.comparison || null,
        snapshotStage: m.snapshot_stage || null, updated: m.updated || 0, preview: m.preview || null,
        previewStage: m.preview_stage || null, previewTs: m.preview_ts || 0, snapshotTs: m.snapshot_ts || 0,
        stages: names.map(s => ({ name: s, state: st[s].state || "running", text: stageNumbers(s, st[s].data) })) };
    });
  }
  function fittingSummary(job) {
    const rows = fittingRows(job), cur = (job.fitting || {}).current;
    return { total: rows.length, done: rows.filter(r => r.state === "done").length, failed: rows.filter(r => r.state === "failed").length,
      current: rows.find(r => r.key === cur) || null };
  }
  // the snapshot to show: the model being fitted now, else the most recent one that has a snapshot
  function snapshotOf(job) {
    const rows = fittingRows(job), cur = (job.fitting || {}).current;
    const now = rows.find(r => r.key === cur && r.snapshot);
    if (now) return now.snapshot;
    const any = rows.filter(r => r.snapshot).sort((a, b) => b.updated - a.updated)[0];
    return any ? any.snapshot : null;
  }
  // a preview image (a sprite writer's donor / fitted frames, a sprite reader's sheet): shown over the 3D view when the
  // model being fitted has no mesh snapshot of its own (a mesh snapshot always wins: the operator sees the 3D model)
  function previewOf(job) {
    const rows = fittingRows(job), cur = (job.fitting || {}).current;
    const r = rows.find(x => x.key === cur) || rows.filter(x => x.preview).sort((a, b) => b.updated - a.updated)[0];
    return r && r.preview && !r.snapshot ? r.preview : null;
  }
  const n2 = v => (typeof v === "number" ? (Math.abs(v) >= 100 ? Math.round(v).toLocaleString("en-US") : String(+v.toFixed(2))) : "");
  function stageNumbers(stage, d) {                                         // the stage's numbers, short
    d = d || {};
    if (d.error || d.reason) return String(d.error || d.reason).slice(0, 60);
    // the donor as loaded -> the fitted height (the writers' scale stage: donor_height / fitted_height, own units)
    const tall = d.donor_height != null && d.fitted_height != null ? ` · ${n2(d.donor_height)} → ${n2(d.fitted_height)} tall` : "";
    if (stage === "scale" && d.scale != null) return `×${n2(d.scale)}` + (d.head_scale != null ? ` · head ×${n2(d.head_scale)}` : "") + tall;
    if (stage === "scale" && d.donor_height != null) return `${n2(d.donor_height)} tall · ${n2(d.donor_triangles || 0)} tris`;
    if (stage === "retarget") return [d.mode || "", d.roles != null ? `${d.roles} roles` : "", d.vertices != null ? `${n2(d.vertices)} verts` : "",
      d.segments != null ? `${d.segments} parts` : ""].filter(Boolean).join(" · ");
    if (stage === "proportion") return d.applied ? ["height", "head", "torso_width"].filter(k => d[k] != null && d[k] !== 1)
      .map(k => `${k.replace("_", " ")} ×${n2(d[k])}`).concat((d.roles_adjusted || []).length ? [`${d.roles_adjusted.length} parts`] : [])
      .join(" · ") || "profile" : (d.profile === "none" ? "no profile" : String(d.profile || ""));
    const limbs = d.limbs != null ? d.limbs : d.nodes != null ? d.nodes : d.bones;   // per-limb vertex counts
    if (stage === "weights") return d.vertices_reduced != null ? `${n2(d.vertices_reduced)} verts → ${d.max_influences} bones`
      : limbs != null ? `${limbs} limbs · ${n2(d.vertices || 0)} verts` : (d.max_influences != null ? `max ${d.max_influences}` : "");
    if (stage === "decimate") return d.from != null && (d.triangles != null || d.to != null) ? `${n2(d.from)} → ${n2(d.triangles != null ? d.triangles : d.to)} tris` : "";
    const moved = d.relocates || (Array.isArray(d.relocated) ? d.relocated.length : d.relocated) ? " · moved" : "";
    if (stage === "encode") return (d.bytes != null ? `${n2(d.bytes / 1024)} KB` : d.chr_bytes != null ? `${n2((d.chr_bytes + (d.bin_bytes || 0)) / 1024)} KB`
      : d.triangles != null ? `${n2(d.triangles)} tris` : "") + (d.grew ? ` · +${n2(d.grew / 1024)} KB` : "") + moved;
    if (stage === "write") return (d.mod || d.image || "") + (d.vrom ? ` · ${d.vrom}` : "");
    if (stage === "extract") return d.kind === "sprites" ? "sprite sheet" : d.reason ? String(d.reason)
      : [d.triangles != null ? `${n2(d.triangles)} tris` : "", d.roles ? `${d.roles} roles` : ""].filter(Boolean).join(" · ");
    if (stage === "preview") return d.roles ? `${d.roles} roles` : (d.kind || "");
    return "";
  }
  // ---- the Retarget editor ("R"): a row's donor, target game and slot (fit events: donor / game / slot) ----------------
  const GID = /^[0-9a-f]{16}$/;
  function retargetOf(job, key) {
    const f = (job && job.fitting) || {}, k = key || f.current, m = k && (f.models || {})[k];
    if (!m || isCollect(job)) return null;
    const i = job.input || {};
    const slug = m.donor || (i.op === "use" && i.character) || "";
    const gid = m.game || [i.target_game, i.game_id].find(g => GID.test(String(g || ""))) || "";
    if (!slug || !gid) return null;
    const slot = m.slot || (k !== slug && !/ #\d+$/.test(k) ? k : "") || (i.op === "use" && i.slot) || "player";
    const name = String(m.label || "").split(/\s*(?:→|->)\s*/)[0] || slug;
    return { slug, gid, slot, name, view: "goals", key: k, job: job.id || null,
      recipe: ["cast_swap", "use"].includes(i.op) ? { tool: job.tool || "characters", input: i } : null };
  }
  // the row whose model the 3D view shows (snapshotOf's choice)
  function shownKey(job) {
    const rows = fittingRows(job), snap = snapshotOf(job), cur = ((job && job.fitting) || {}).current;
    const r = (snap && rows.find(x => x.snapshot === snap && x.key === cur)) || (snap && rows.find(x => x.snapshot === snap))
      || rows.find(x => x.key === cur);
    return r ? r.key : null;
  }
  // ---- calibration play-by-play (#1385): the current model's reported fit numbers as a "before -> fitted" tween ----
  // The writer's scale / proportion stages say how the donor was resized for the title (overall size, height or torso
  // stretch, torso width or shoulder widening, head). The viewer eases the fitted snapshot from those inverse factors
  // back to 1 on a loop, so the operator watches each character's proportions adjust while the build runs.
  const clampK = v => Math.min(1.6, Math.max(0.55, v));
  const pos = v => (typeof v === "number" && isFinite(v) && v > 0 ? v : null);
  function calibration(job) {
    const f = job && job.fitting;
    if (!f || !f.models || isCollect(job)) return null;
    let key = f.models[f.current] ? f.current : null;
    if (!key) { const r = fittingRows(job).filter(x => x.state !== "pending").sort((a, b) => b.updated - a.updated)[0]; key = r ? r.key : null; }
    const m = key && f.models[key];
    if (!m) return null;
    const st = m.stages || {}, sc = (st.scale || {}).data || {};
    const pr = (st.proportion || {}).state === "skipped" ? {} : ((st.proportion || {}).data || {});
    let s = pos(sc.scale);
    if (s == null && pos(sc.donor_height) && pos(sc.fitted_height)) s = sc.fitted_height / sc.donor_height;
    const torso = pos(sc.torso_up) && pos(sc.torso_down) ? (sc.torso_up + sc.torso_down) / 2 : pos(sc.torso_up) || pos(sc.torso_down);
    const h = pos(pr.height) || torso || 1, w = pos(pr.torso_width) || pos(sc.shoulder_widen) || 1;
    const head = pos(pr.head) || pos(sc.head_scale) || 1;
    s = s || 1;
    const parts = [];
    if (Math.abs(s - 1) >= 0.01) parts.push(`size ×${n2(s)}`);
    if (Math.abs(h - 1) >= 0.01) parts.push(`height ×${n2(h)}`);
    if (Math.abs(w - 1) >= 0.01) parts.push(`width ×${n2(w)}`);
    if (Math.abs(head - 1) >= 0.01) parts.push(`head ×${n2(head)}`);
    if (!parts.length) return null;
    const label = m.label || key;
    return { key, label, factors: { scale: s, height: h, width: w, head },
      from: { x: clampK(1 / (s * w)), y: clampK(1 / (s * h)), z: clampK(1 / (s * w)) },
      text: `Calibrating ${label}: ${parts.join(" · ")}` };
  }
  // 0 = donor proportions, 1 = fitted: hold, ease in-out, hold, repeat (2.8 s)
  function calibrationPhase(t) {
    const T = 2.8, u = ((t % T) + T) % T;
    if (u < 0.5) return 0;
    if (u >= 1.9) return 1;
    const x = (u - 0.5) / 1.4;
    return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
  }
  const nowS = () => ((env.performance && env.performance.now) ? env.performance.now() : Date.now()) / 1000;
  function fittingHTML(job, opts) {
    const rows = fittingRows(job);
    if (!rows.length) return "";
    const s = fittingSummary(job), collect = isCollect(job), chips = collect ? COLLECT_STAGES : STAGES;
    const withR = !opts || opts.retarget !== false;
    const count = (job.fitting?.reported_total || 0) > rows.length ? `${rows.length} shown of ${job.fitting.reported_total}` : `${s.done}/${s.total}`;
    const head = `<div class="pp-fh"><b>${collect ? "Collecting" : "Fitting"}</b> ${count} ${collect ? "characters" : "models"}${s.failed ? ` · <span class="bad">${s.failed} failed</span>` : ""}</div>`;
    return head + rows.map(r => `<div class="pp-fr ${ESC(r.state)}${s.current && s.current.key === r.key ? " cur" : ""}" title="${ESC(r.key)}">
      <span class="pp-fl">${ESC(r.label)}</span><span class="pp-fs">${chips.map(name => {
        const st = r.stages.find(x => x.name === name);
        return `<i class="${st ? ESC(st.state) : "todo"}" title="${ESC(STAGE_NAMES[name] || name)}${st && st.text ? ": " + ESC(st.text) : ""}">${ESC(name[0].toUpperCase())}</i>`;
      }).join("")}${withR && retargetOf(job, r.key) ? `<button type="button" class="pp-rr" data-pp-r="${ESC(r.key)}" title="Retarget goals: ${ESC(r.label)} - fix how its joints match the target">R</button>` : ""}</span><span class="pp-fn">${ESC((() => { const st = r.stages.find(x => x.name === r.current); return st ? `${st.name}${st.text ? " · " + st.text : ""}` : r.state; })())}</span>${opts?.review && (r.comparison || r.stages.some(s=>s.name==='decimate')) ? `<button type="button" class="pp-review" data-pp-review="${ESC(r.key)}">Compare / report mesh</button>` : ''}</div>`).join("");
  }

  // ---- what the current stage is doing to the mesh (drives the live mesh-change view) -----
  // Reads the worker's own progress lines, e.g. "Amy: decimating 12000 -> 8000 triangles",
  // "Too big (…): decimating to ~4000 triangles", "Retargeting Amy onto Leon's skeleton".
  // Writers word the same operations differently (oot/sm64/ninja "Decimating Amy -> 4000 triangles
  // (Blender)", sm64 "Simplifying the props 300 -> 200 triangles", pe/ff7/sa2/pso/re6/metal_arms
  // "Fitting Amy onto Cloud's field skeleton" / "Fitting Amy to Sonic's 22 nodes", aki/sm64
  // "Fitting 3 parts into the game's vertex/face budget"); tests scan gbox/*.py to keep this in step.
  function stageEffect(msg) {
    const m = String(msg || "");
    if (!m) return null;
    let r;
    const fitting = /\bfitting\b/i.test(m);
    const budgetFit = fitting && /\binto\b.*\b(budget|triangles?|faces?|data)\b/i.test(m);
    if (/decimat|simplif/i.test(m) || budgetFit) {
      const verb = budgetFit ? "fit to budget" : "decimate";
      // "12000 -> 8000 triangles", or gta_vc "12000 triangles: decimating to ~8000 (Blender)"
      if ((r = /([\d,]+)\s*(?:->|→|\bto)\s*~?([\d,]+)\s*tri/i.exec(m))
          || (r = /([\d,]+)\s*tri\w*\b.*?\b(?:decimat|simplif)\w*\s+(?:->|→|to)\s*~?([\d,]+)/i.exec(m))) {
        const from = +r[1].replace(/,/g, ""), to = +r[2].replace(/,/g, "");
        if (from > 0 && to > 0) return { kind: "decimate", from, to, ratio: Math.min(1, to / from),
          label: `${verb} ${from.toLocaleString("en-US")} → ${to.toLocaleString("en-US")} tris` };
      }
      if ((r = /(?:->|→|\bto)\s*~?([\d,]+)\s*tri/i.exec(m))) {                // target only: scaled to the mesh
        const to = +r[1].replace(/,/g, "");
        if (to > 0) return { kind: "decimate", to, ratio: null, label: `${verb} → ${to.toLocaleString("en-US")} tris` };
      }
      return { kind: "decimate", ratio: 0.5, label: verb };
    }
    if (/retarget/i.test(m) || (fitting && /\b(onto|to)\b/i.test(m))) {
      r = /\bonto\s+(.+?)(?:\s*\(|$)/i.exec(m) || (fitting ? /\bfitting\b.*?\bto\s+(.+?)(?:\s*\(|$)/i.exec(m) : null);
      return { kind: "retarget", label: "retarget" + (r ? " → " + r[1].trim() : "") };
    }
    if (/\b(re)?scal(e|es|ed|ing)\b|\bresiz/i.test(m)) return { kind: "rescale", label: "rescale" };
    return null;
  }

  function decimateRatio(effect, totalTris) {                               // fraction of triangles the stage keeps
    if (!effect || effect.kind !== "decimate") return 1;
    if (effect.ratio) return Math.max(0.02, Math.min(1, effect.ratio));
    if (effect.to && totalTris > 0) return Math.max(0.02, Math.min(1, effect.to / totalTris));
    return 0.5;
  }

  // Dispose resources from replaced or late GLTF results, including shared materials/textures.
  function disposeObject(object) {
    const resources = new Set();
    object.traverse(o => {
      if (o.geometry) resources.add(o.geometry);
      for (const material of (Array.isArray(o.material) ? o.material : [o.material])) {
        if (!material) continue;
        resources.add(material);
        for (const value of Object.values(material)) if (value && value.isTexture) resources.add(value);
      }
      if (o.skeleton && o.skeleton.boneTexture) resources.add(o.skeleton.boneTexture);
    });
    for (const resource of resources) if (resource.dispose) resource.dispose();
  }

  // ---- VCR close effect: tracking static, then the picture collapses to a line ------------
  const VCR_TRACKING_MS = 700, VCR_COLLAPSE_MS = 260, VCR_HOLD_MS = 60;
  function createVcr(now) {
    const clock = now || (() => Date.now());
    let t0 = null;
    return {
      start() { t0 = clock(); },
      step() {
        if (t0 === null) return { phase: "off", p: 0, done: false };
        const t = clock() - t0;
        if (t < VCR_TRACKING_MS) return { phase: "tracking", p: t / VCR_TRACKING_MS, done: false };
        if (t < VCR_TRACKING_MS + VCR_COLLAPSE_MS) return { phase: "collapse", p: (t - VCR_TRACKING_MS) / VCR_COLLAPSE_MS, done: false };
        if (t < VCR_TRACKING_MS + VCR_COLLAPSE_MS + VCR_HOLD_MS) return { phase: "hold", p: 1, done: false };
        return { phase: "done", p: 1, done: true };
      },
    };
  }

  // ---- one popup window -------------------------------------------------------------------
  function mount(opts) {
    opts = opts || {};
    const fetchJobs = opts.fetchJobs || null, pollMs = opts.pollMs || 4000;
    const assetUrl = opts.assetUrl || (p => p);
    const pathFor = activityModelPath;
    const failedVisuals=new Set();
    const visualKey=job=>{
      const visual=visualOf(job),rows=fittingRows(job),row=rows.find(r=>r.key===job.fitting?.current);
      return JSON.stringify([job.id,visual,visual?.kind==='image'?row?.previewTs:row?.snapshotTs]);
    };
    let pendingVisual=null;
    function visualReady(key) { if(root && current?.state==='running' && key===pendingVisual) {root.hidden=false;fitIn();} }
    function visualFailed(key) { if(key!==pendingVisual)return;failedVisuals.add(key);while(failedVisuals.size>128)failedVisuals.delete(failedVisuals.values().next().value);remove(); }
    // opts.fit(el): the shell keeps the window inside its viewport and below its header bar (toast-stack.js fit): after
    // each update (the fitting rows grow it upward from its bottom anchor), after a drag and on window resize
    const fitIn = () => { if (root && typeof opts.fit === "function") { try { opts.fit(root); } catch (e) { /* layout only */ } } };
    const view = doc && doc.defaultView;
    if (view && typeof view.addEventListener === "function" && typeof opts.fit === "function") view.addEventListener("resize", fitIn);
    const suppressed = new Set();
    let root = null, stage = null, overlay = null, ctx2d = null, titleEl = null, stateEl = null, moreEl = null,
      barEl = null, msgEl = null, logEl = null, opEl = null, footEl = null, fitEl = null, calEl = null, picEl = null, picSrc = null, rBtn = null,
      detailEl = null, jobsEl = null, consolePaused = false, logButton = null;
    let current = null, closing = false, vcr = createVcr(opts.now), three = null, timer = null, pollTimer = null,
      lastMsgs = [], dead = false, polling = null, preferred = null;
    // "R": the Retarget editor (opts.retarget(o), the shell's opener) on a row's donor / game / slot
    function openRetarget(key) {
      const o = current && retargetOf(current, key || shownKey(current));
      if (o && typeof opts.retarget === "function") opts.retarget(o);
      return o;
    }

    const style = doc.createElement("style");
    style.textContent = [
      ".gbox-pp{position:fixed;right:14px;bottom:46px;width:390px;max-width:calc(100vw - 28px);z-index:9999;",
      "background:#101318f2;border:1px solid #2c3340;border-radius:10px;box-shadow:0 12px 40px #000c;",
      "font:12px/1.45 system-ui,sans-serif;color:#dfe4ec;overflow:hidden}",
      ".gbox-pp .pp-h{display:flex;align-items:center;gap:8px;padding:7px 10px;background:#161a22;border-bottom:1px solid #232a36}",
      ".gbox-pp .pp-h b{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}",
      ".gbox-pp .pp-chip{flex:none;font-size:10px;padding:1px 7px;border-radius:9px;background:#233042;color:#9fc2ff}",
      ".gbox-pp .pp-chip.run{background:#1d3a26;color:#8fe6a8}.gbox-pp .pp-x{flex:none;border:0;background:none;color:#8b93a3;",
      "cursor:pointer;font-size:14px;padding:0 2px}.gbox-pp .pp-x:hover{color:#fff}",
      ".gbox-pp .pp-stage{position:relative;height:250px;background:#0b0d12}",
      ".gbox-pp .pp-stage canvas{position:absolute;inset:0;width:100%;height:100%}",
      ".gbox-pp .pp-meta{padding:7px 10px 2px}.gbox-pp .pp-bar{height:4px;border-radius:3px;background:#222936;overflow:hidden}",
      ".gbox-pp .pp-bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#4f8cff,#8fe6a8);transition:width .4s}",
      ".gbox-pp .pp-msg{margin-top:5px;color:#aeb7c6;min-height:16px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".gbox-pp .pp-log{padding:0 10px 4px;color:#6f7988;font:10px/1.5 ui-monospace,monospace;max-height:44px;overflow:hidden}",
      ".gbox-pp .pp-f{padding:4px 10px 7px;color:#5b6472;font-size:10px}",
      ".gbox-pp.pp-closing .pp-stage canvas:first-child{filter:saturate(.4)}",
      ".gbox-pp .pp-op{position:absolute;left:8px;top:7px;z-index:2;font:700 10px/1.4 ui-monospace,monospace;color:#ffb46b;",
      "background:#0b0d12cc;padding:1px 6px;border-radius:4px;pointer-events:none}.gbox-pp .pp-op:empty{display:none}",
      ".gbox-pp .pp-fit{padding:2px 10px 4px;max-height:132px;overflow:auto;font-size:11px}.gbox-pp .pp-fit:empty{display:none}",
      ".gbox-pp .pp-cal{position:absolute;left:8px;bottom:7px;right:8px;z-index:2;font:600 10px/1.4 ui-monospace,monospace;color:#8fe6a8;",
      "background:#0b0d12cc;padding:1px 6px;border-radius:4px;pointer-events:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gbox-pp .pp-cal:empty{display:none}",
      ".gbox-pp .pp-fh{color:#9fc2ff;margin:2px 0}.gbox-pp .pp-fh .bad{color:#ff8b8b}",
      ".gbox-pp .pp-fr{display:grid;grid-template-columns:1fr auto;gap:0 6px;padding:2px 4px;border-radius:4px}",
      ".gbox-pp .pp-review{grid-column:1/3;justify-self:start;margin:3px 0;background:#27354c;color:#c6dcff;border:1px solid #526680;border-radius:4px;font:11px system-ui;cursor:pointer}",
      ".gbox-pp .pp-fr.cur{background:#ffffff0d}.gbox-pp .pp-fr.failed .pp-fl{color:#ff8b8b}.gbox-pp .pp-fr.done .pp-fl{color:#8fe6a8}",
      ".gbox-pp .pp-fl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gbox-pp .pp-fs{display:flex;gap:2px}",
      ".gbox-pp .pp-fs i{font:700 9px/14px ui-monospace,monospace;width:14px;text-align:center;border-radius:3px;font-style:normal;",
      "background:#1a1f29;color:#4b5363}.gbox-pp .pp-fs i.running{background:#3a2c18;color:#ffb46b}",
      ".gbox-pp .pp-fs i.done{background:#1d3a26;color:#8fe6a8}.gbox-pp .pp-fs i.skipped{background:#1a1f29;color:#6f7988}",
      ".gbox-pp .pp-fs i.failed{background:#3a1d1d;color:#ff8b8b}",
      ".gbox-pp .pp-fn{grid-column:1/3;color:#6f7988;font:10px/1.4 ui-monospace,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".gbox-pp .pp-rr{font:700 9px/14px ui-monospace,monospace;width:16px;height:14px;padding:0;margin-left:3px;border:1px solid #4f8cff88;",
      "border-radius:3px;background:#16233a;color:#9fc2ff;cursor:pointer}.gbox-pp .pp-rr:hover,.gbox-pp .pp-rbtn:hover{background:#4f8cff;color:#fff}",
      ".gbox-pp .pp-rbtn{position:absolute;right:8px;bottom:8px;z-index:3;width:26px;height:26px;border-radius:50%;border:1px solid #4f8cff;",
      "background:#101318e6;color:#9fc2ff;font:700 13px/24px ui-monospace,monospace;text-align:center;padding:0;cursor:pointer}",
      ".gbox-pp.pp-activity{width:520px;max-height:calc(100vh - 160px);overflow:auto}.gbox-pp.pp-expanded{width:800px}",
      ".gbox-pp.pp-activity .pp-log{max-height:155px;overflow:auto;white-space:pre-wrap;color:#bdcee8;font:11px/1.5 ui-monospace,monospace;overflow-wrap:anywhere}",
      ".gbox-pp.pp-expanded .pp-log{max-height:300px}.gbox-pp .pp-detail{padding:6px 10px;color:#aebbd0;font-size:11px}",
      ".gbox-pp .pp-detail pre{white-space:pre-wrap;max-height:150px;overflow:auto;font:11px ui-monospace,monospace}",
      ".gbox-pp .pp-flow{display:flex;gap:5px;flex-wrap:wrap;margin:7px 0}.gbox-pp .pp-flow span{border:1px solid #34465d;padding:2px 4px;border-radius:4px}.gbox-pp .pp-flow .now{background:#2e5596}",
      ".gbox-pp .pp-controls{display:flex;gap:6px;padding:6px 10px}.gbox-pp .pp-controls select{min-width:0;flex:1}.gbox-pp .pp-controls button,.gbox-pp .pp-controls select{font:11px system-ui;background:#182437;color:#dfe4ec;border:1px solid #415673;border-radius:4px;padding:4px}",
    ].join("");
    doc.head.append(style);

    function build() {
      root = doc.createElement("div");
      root.hidden = true; // Nothing is shown until a relevant asset has actually loaded.
      root.className = "gbox-pp";
      if (opts.activity) root.classList.add('pp-activity');
      root.setAttribute("role", "dialog");
      root.setAttribute("aria-label", opts.activity ? 'This PC background operation' : "Background 3D task");
      const head = doc.createElement("div"); head.className = "pp-h";
      titleEl = doc.createElement("b");
      stateEl = doc.createElement("span"); stateEl.className = "pp-chip";
      moreEl = doc.createElement("span"); moreEl.className = "pp-chip"; moreEl.style.display = "none";
      const x = doc.createElement("button"); x.className = "pp-x"; x.textContent = "✕"; x.title = "Hide this task (it keeps running)";
      x.onclick = () => { if (current) suppressed.add(current.id); teardown(true); };
      head.append(titleEl, stateEl, moreEl, x);
      stage = doc.createElement("div"); stage.className = "pp-stage";
      overlay = doc.createElement("canvas"); overlay.width = 390; overlay.height = 250;
      opEl = doc.createElement("div"); opEl.className = "pp-op";
      picEl = doc.createElement("img"); picEl.className = "pp-pic"; picSrc = null;   // a sprite writer's preview image
      picEl.style.cssText = "position:absolute;inset:0;width:100%;height:100%;object-fit:contain;image-rendering:pixelated;"
        + "background:rgba(8,10,16,.92);display:none";
      rBtn = doc.createElement("button"); rBtn.className = "pp-rbtn"; rBtn.textContent = "R";      // the shown model's goals
      rBtn.title = "Retarget goals: is this model deformed wrongly? Adjust where its joints are and how they match the target";
      rBtn.style.display = "none";
      rBtn.onclick = e => { if (e && e.stopPropagation) e.stopPropagation(); openRetarget(null); };
      stage.append(overlay, picEl, opEl, rBtn);
      ctx2d = overlay.getContext && overlay.getContext("2d");
      const meta = doc.createElement("div"); meta.className = "pp-meta";
      barEl = doc.createElement("div"); barEl.className = "pp-bar";
      const fill = doc.createElement("i"); barEl.append(fill);
      msgEl = doc.createElement("div"); msgEl.className = "pp-msg";
      meta.append(barEl, msgEl);
      logEl = doc.createElement("div"); logEl.className = "pp-log";
      fitEl = doc.createElement("div"); fitEl.className = "pp-fit";                // per-model fitting stages
      fitEl.onclick = e => {                                                        // a row's own R
        const review = e?.target?.closest?.('[data-pp-review]');
        if(review && typeof opts.review==='function'){opts.review(current,review.dataset.ppReview);return;}
        const b = e && e.target && e.target.closest && e.target.closest("[data-pp-r]");
        if (b) openRetarget(b.dataset ? b.dataset.ppR : b.getAttribute("data-pp-r"));
      };
      calEl = doc.createElement("div"); calEl.className = "pp-cal";                // the calibration play-by-play caption
      stage.append(calEl);
      footEl = doc.createElement("div"); footEl.className = "pp-f";
      footEl.textContent = "Loading the task's reported visual";
      root.append(head, stage, meta, fitEl, logEl, footEl);
      if (opts.activity) {
        const controls = doc.createElement('div'); controls.className = 'pp-controls';
        jobsEl = doc.createElement('select'); jobsEl.setAttribute('aria-label', 'Operation to inspect');
        jobsEl.onchange = () => { preferred = jobsEl.value; const j = lastJobs.find(j=>j.id===preferred); if(j){setContent(j,lastJobs.length-1);update(j);} };
        const expand = doc.createElement('button'); expand.textContent = 'Expand';
        expand.onclick = () => { const on = !root.classList.contains('pp-expanded');root.classList[on?'add':'remove']('pp-expanded');expand.textContent=on?'Compact':'Expand';fitIn(); };
        logButton = doc.createElement('button'); logButton.textContent = 'Pause output';
        logButton.title = 'Freeze console and measurement text for inspection; the worker keeps running';
        logButton.onclick = () => { consolePaused=!consolePaused;logButton.textContent=consolePaused?'Resume output':'Pause output';if(!consolePaused&&current)update(current); };
        controls.append(jobsEl, expand, logButton);
        detailEl = doc.createElement('div'); detailEl.className='pp-detail';
        root.append(controls, detailEl);
      }
      doc.body.append(root);
      draggable(root);
    }

    // The popup can be moved by pressing on its header, meta or footer and dragging (#1415); the 3D stage, the log and
    // the hide button keep their own behaviour. A drag never counts as a click.
    function draggable(el) {
      if (typeof el.addEventListener !== "function") return;              // headless test documents
      el.addEventListener("pointerdown", e => {
        if (e.button !== 0 || e.target.closest("button, a, select, input, details, canvas, .pp-log, .pp-stage, .pp-fit, .pp-detail")) return;
        const r = el.getBoundingClientRect(), x0 = e.clientX, y0 = e.clientY, id = e.pointerId;
        let moving = false;
        const move = ev => {
          const dx = ev.clientX - x0, dy = ev.clientY - y0;
          if (!moving) {
            if (Math.abs(dx) + Math.abs(dy) < 4) return;
            moving = true;
            try { el.setPointerCapture(id); } catch (err) { /* capture is optional */ }
            el.style.right = "auto"; el.style.bottom = "auto";
          }
          el.style.left = Math.max(0, Math.min(el.ownerDocument.defaultView.innerWidth - 40, r.left + dx)) + "px";
          el.style.top = Math.max(0, Math.min(el.ownerDocument.defaultView.innerHeight - 24, r.top + dy)) + "px";
          ev.preventDefault();
        };
        const up = () => {
          el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up);
          if (moving) { try { el.releasePointerCapture(id); } catch (err) { /* already released */ } fitIn(); }
        };
        el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
      });
    }

    function teardown(instant) {
      if (!root) return;
      if (instant) { remove(); return; }
      closing = true; root.classList.add("pp-closing"); vcr.start(); loop();
    }

    function remove() {
      closing = false; current = null; pendingVisual=null;picSrc=null;
      if (timer) { (env.clearTimeout || clearTimeout)(timer); timer = null; }
      if (three) { try { three.dispose(); } catch (e) {} three = null; }
      if (root) { root.remove(); root = null; }
    }

    function setContent(job, others) {
      if (!root) build();
      if (current?.id !== job.id) { lastMsgs = []; logEl.textContent = ''; msgEl.textContent = ''; barEl.firstChild.style.width = '0%'; consolePaused=false;if(logButton)logButton.textContent='Pause output'; }
      current = job;
      const key=visualKey(job);
      if(key!==pendingVisual){if(three){three.dispose();three=null;}pendingVisual=key;root.hidden=true;picSrc=null;picEl.style.display='none';}
      titleEl.textContent = title(job);
      stateEl.textContent = job.state === "running" ? "processing" : "queued";
      const run = job.state === "running";
      if (stateEl.classList) stateEl.classList[run ? "add" : "remove"]("run");
      moreEl.textContent = `+${others} more`;
      moreEl.style.display = others ? "" : "none";
      const visible = !!visualOf(job);
      stage.style.display = visible ? '' : 'none';
      if (!visible && three) { three.dispose(); three=null; }
      if (visible && !previewOf(job) && !three) startViewer(job);
    }

    function update(job) {
      current = job;                                                        // pending module imports must use the newest model/stage
      const p = job.progress || {};
      if (typeof p.pct === "number") barEl.firstChild.style.width = Math.max(0, Math.min(100, p.pct)) + "%";
      if (p.msg && p.msg !== msgEl.textContent) msgEl.textContent = p.msg;
      const logs = (job.progress_log || job.stage_log || []).filter(Boolean).slice(opts.activity ? -50 : -3);
      const atTail = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 24;
      if (!consolePaused && logs.length) {
        const joined = logs.join("\n");
        if (joined !== logEl.textContent) logEl.textContent = joined;
      } else if (!consolePaused && p.msg && lastMsgs[lastMsgs.length - 1] !== p.msg) {
        lastMsgs = (lastMsgs.concat([p.msg])).slice(opts.activity ? -50 : -3);
        logEl.textContent = lastMsgs.join("\n");
      }
      if (atTail && !consolePaused) logEl.scrollTop = logEl.scrollHeight;
      if (detailEl && !consolePaused) {
        const html = detailHTML(job);
        if(detailEl.innerHTML !== html) detailEl.innerHTML=html;
      }
      if (jobsEl) jobsEl.value = job.id;
      const fitting = fittingSummary(job);
      if (fitEl) { const html = fittingHTML(job, { retarget: typeof opts.retarget === "function", review: typeof opts.review === "function" }); if (html !== fitEl.innerHTML) fitEl.innerHTML = html; }
      if (rBtn) {
        const o = typeof opts.retarget === "function" ? retargetOf(job, shownKey(job)) : null, show = o ? "" : "none";
        if (rBtn.style.display !== show) rBtn.style.display = show;
        if (o) rBtn.title = `Retarget goals for ${o.name} → ${o.slot}: adjust where its joints are and how they match the target`;
      }
      const pic = previewOf(job);
      if (picEl && pic !== picSrc) {
        picSrc = pic;
        picEl.style.display = 'none';
        if (pic) {
          const image=picEl,key=pendingVisual;
          image.onload=()=>{if(image!==picEl||key!==pendingVisual)return;if(!image.naturalWidth)return visualFailed(key);
            image.style.display='';footEl.textContent='Task sprite / image preview';visualReady(key);};
          image.onerror=()=>{if(image===picEl)visualFailed(key);};
          image.src = assetUrl(pic);
        }
      }
      if (opEl && fitting.current && fitting.current.current) {             // the model being fitted and its stage
        const lbl = opts.activity ? `${fitting.current.current} · ${fitting.current.label}` : `${fitting.current.current} · ${fitting.done + (fitting.current.state === "done" ? 0 : 1)}/${fitting.total}`;
        if (lbl !== opEl.textContent) opEl.textContent = lbl;
      } else if (opEl && p.msg) {                                           // which mesh operation is running now
        const fx = stageEffect(p.msg), lbl = fx ? fx.label : "";
        if (lbl !== opEl.textContent) opEl.textContent = lbl;
      }
      if (calEl) calEl.textContent = ''; // Show actual snapshots, not a simulated deformation.
      const t = title(job);
      if (titleEl && t !== titleEl.textContent) titleEl.textContent = t;   // the job may name its model mid-run
      if (three && three.setJob) three.setJob(job);
    }

    // ---- viewer: only the job's actual asset; no generic shape or renderer fallback -------
    async function startViewer(job) {
      if (!stage || three) return;
      const holder = { canvas: null, dispose() {} };
      const key=pendingVisual;
      three = holder;                                                       // loading token, never displayed
      let made = null;
      try {
        if (opts.loadModules || opts.now === undefined) {                   // injectable modules also exercise the real viewer offline
          const modules = opts.loadModules ? await opts.loadModules() : {
            THREE: await import("https://cdn.jsdelivr.net/npm/three@0.160.0/+esm"),
            GLTFLoader: (await import("https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js/+esm")).GLTFLoader,
          };
          if (!root || three !== holder || !current) return;
          made = makeThree(modules.THREE, modules.GLTFLoader, current);
        }
      } catch (e) { if (made) { try { made.dispose(); } catch (e2) {} made = null; } }
      if (!root || three !== holder) { if (made) made.dispose(); return; }
      if(!made){visualFailed(key);return;}
      three = made;
      if (current && three.setJob) three.setJob(current);
      if (root && stage.firstChild !== overlay) stage.insertBefore(overlay, stage.firstChild);
    }

    function makeThree(THREE, GLTFLoader, job) {
      const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
      renderer.setPixelRatio(Math.min(env.devicePixelRatio||1,2));renderer.setSize(390,250,false);
      const canvas=renderer.domElement;canvas.style.cssText="position:absolute;inset:0;width:100%;height:100%";
      stage.insertBefore(canvas,overlay);
      const scene=new THREE.Scene(),group=new THREE.Group();scene.add(group);
      scene.add(new THREE.HemisphereLight(0xffffff,0x30364a,2.1));
      const sun=new THREE.DirectionalLight(0xffffff,1.8);sun.position.set(3,5,4);scene.add(sun);
      const camera=new THREE.PerspectiveCamera(40,390/250,.01,100);camera.position.set(0,.7,3.1);camera.lookAt(0,0,0);
      let path=pathFor(job),model=null,generation=0,raf=0,stop=false,lastFrame=-Infinity;
      const tick=()=>{
        if(stop)return;
        raf=(env.requestAnimationFrame||(f=>env.setTimeout(f,33)))(tick);
        if(doc.hidden||nowS()-lastFrame<.05)return;
        lastFrame=nowS();group.rotation.y+=.012;
        renderer.render(scene,camera);
      };
      function load(p){
        const attempt=++generation,key=pendingVisual;
        const fail=()=>{if(!stop&&attempt===generation)visualFailed(key);};
        try{new GLTFLoader().load(assetUrl(p),gltf=>{
          if(stop||attempt!==generation||key!==pendingVisual){disposeObject(gltf.scene);return;}
          gltf.scene.updateMatrixWorld(true);
          const box=new THREE.Box3(),part=new THREE.Box3();let meshes=0;
          gltf.scene.traverse(o=>{if(o.isMesh&&o.geometry?.attributes?.position?.count>0){meshes++;
            if(!o.geometry.boundingBox)o.geometry.computeBoundingBox();
            box.union(part.copy(o.geometry.boundingBox).applyMatrix4(o.matrixWorld));}});
          if(!meshes){disposeObject(gltf.scene);fail();return;}
          if(box.isEmpty())box.setFromObject(gltf.scene);
          const center=box.getCenter(new THREE.Vector3()),size=Math.max(box.getSize(new THREE.Vector3()).length(),.1),scale=1.6/size;
          gltf.scene.scale.setScalar(scale);gltf.scene.position.copy(center).multiplyScalar(-scale);
          if(model){group.remove(model);disposeObject(model);}model=gltf.scene;group.add(model);group.userData.model=model;
          const row=fittingRows(current).find(r=>r.snapshot===p);
          footEl.textContent=isSnapshot(p)?`Task model snapshot${row?' · '+(row.snapshotStage||row.current||'')+' · '+row.label:''}`:'Source donor model · awaiting fitted stage snapshots';
          visualReady(key);if(!raf)tick();
        },undefined,fail);}catch(error){fail();}
      }
      if(path)load(path);
      return {canvas,
        setJob(j){const next=pathFor(j);if(next!==path){path=next;++generation;if(model){group.remove(model);disposeObject(model);model=null;}
          if(root)root.hidden=true;if(path)load(path);}},
        get state(){return {path,ready:!!model,fx:null,fxObjs:0,pulse:0,calib:null,lineVerts:0};},
        dispose(){stop=true;++generation;if(raf)(env.cancelAnimationFrame||(t=>env.clearTimeout(t)))(raf);
          if(model){disposeObject(model);model=null;}renderer.dispose();canvas.remove();}
      };
    }

    function drawOverlay() {                                                // VCR static + tracking band while closing
      if (!ctx2d || !closing) return;
      const v = vcr.step(), W = overlay.width, H = overlay.height;
      if (v.done) { remove(); return; }
      const rnd = env.Math ? env.Math.random : Math.random;
      ctx2d.clearRect(0, 0, W, H);
      if (v.phase === "tracking") {
        const n = Math.floor(40 + 260 * v.p);
        for (let i = 0; i < n; i++) {                                       // static snow
          const g = rnd() * 160 | 0;
          ctx2d.fillStyle = `rgba(${g},${g},${g},${0.25 + rnd() * 0.5})`;
          ctx2d.fillRect(rnd() * W, rnd() * H, 2 + rnd() * 26, 1.5);
        }
        const bandY = H - v.p * (H + 40);                                   // bright tracking bar sweeping upward
        ctx2d.fillStyle = "rgba(255,255,255,.16)"; ctx2d.fillRect(0, bandY, W, 22);
        ctx2d.fillStyle = "rgba(255,255,255,.5)"; ctx2d.fillRect(0, bandY + 9, W, 3);
        ctx2d.fillStyle = "#e8ecf3"; ctx2d.font = "700 11px ui-monospace,monospace";
        ctx2d.fillText("◼ STOP", 12, 20);
      } else if (v.phase === "collapse" || v.phase === "hold") {
        const k = v.phase === "hold" ? 1 : 1 - Math.pow(v.p, 2);
        ctx2d.fillStyle = `rgba(0,0,0,${0.35 + 0.6 * (1 - k)})`;
        ctx2d.fillRect(0, 0, W, H);
        const h = Math.max(1.5, 250 * k);
        ctx2d.fillStyle = "#dfe6f2";
        ctx2d.fillRect(0, (H - h) / 2, W, Math.min(h, 2));                  // picture collapsing to a scanline
        if (v.phase === "collapse" && v.p > .6) { ctx2d.fillStyle = "#fff"; ctx2d.fillRect(0, H / 2 - 1, W, 2); }
      }
    }

    function loop() {                                                       // keeps the VCR overlay animating while closing
      if (!closing || !root) return;
      drawOverlay();
      if (closing && root) timer = env.setTimeout(loop, 33);
    }

    let lastJobs = [];
    function sync(jobs) {
      if (dead || !Array.isArray(jobs)) return;
      const worker = typeof opts.worker === 'function' ? opts.worker() : opts.worker;
      const live = jobs.filter(j => j.state==='running' && visualOf(j) && (!opts.worker || onWorker(j, worker)) && !suppressed.has(j.id) && !failedVisuals.has(visualKey(j)));
      lastJobs = live;
      if (!live.length) { remove(); return; }
      let { job, others } = opts.activity ? {job:[...live].sort((a,b)=>(b.state==='running')-(a.state==='running') || ((b.progress||{}).ts||b.started||b.created||0)-((a.progress||{}).ts||a.started||a.created||0))[0],others:live.length-1} : pick(live);
      const wanted = preferred && live.find(j => j.id === preferred);         // a rebuild the editor queued: follow it
      if (wanted) job = wanted;
      if (closing && root) {
        if (job.id !== (current && current.id) && !vcr.step().done) return;  // a different 3D task took over mid-effect: let the effect finish first
        closing = false; root.classList.remove("pp-closing");
      }
      setContent(job, others);                                              // state and companion counts can change without a new job id
      if (jobsEl) {
        const html = live.map(j=>`<option value="${ESC(j.id)}">${ESC(title(j))} · ${ESC(j.state)}</option>`).join('');
        if(jobsEl.innerHTML !== html)jobsEl.innerHTML=html;
      }
      update(job);
      fitIn();
    }

    if (fetchJobs) {
      const poll = () => {
        if (dead || polling) return polling;
        polling = Promise.resolve().then(async () => {
          try { const jobs = await fetchJobs(); if (!dead) sync(jobs); }
          catch (e) { markStale(); }
          finally { polling = null; }
        });
        return polling;
      };
      poll();
      pollTimer = env.setInterval(poll, pollMs);
    }

    function markStale() { remove(); } // Processing is unconfirmed; don't keep a visual running as evidence.
    return {
      sync,
      stale: markStale,
      suspend() { remove(); }, // Idle operations iframe owns the single visible task window.
      follow(id) { preferred = id || null; if (id) suppressed.delete(id); },  // show this job once it is live
      openRetarget,
      viewer() { return three && three.state ? three.state : null; },      // live mesh-view state (diagnostics/tests)
      dispose() {
        dead = true;
        if (pollTimer) (env.clearInterval || (t => env.clearTimeout(t)))(pollTimer);
        if (view && typeof view.removeEventListener === "function") view.removeEventListener("resize", fitIn);
        remove(); style.remove();
      },
    };
  }

  return { mount, classify, activityJob, onWorker, detailHTML, pick, createVcr, title, modelPath, activityModelPath, stageEffect, decimateRatio, MODEL_TOOLS,
    fittingRows, fittingSummary, fittingHTML, snapshotOf, previewOf, visualOf, stageNumbers, calibration, calibrationPhase, STAGES, retargetOf, shownKey };
});
