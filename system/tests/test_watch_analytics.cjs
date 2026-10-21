// clients/web/viz/watch-analytics.js: the rows beside a watched game (bot telemetry, Ghidra/analysis, jobs, results).
const assert = require("assert");
const W = require("../clients/web/viz/watch-analytics.js");

const m = W.model(
  { running: true, mission: "playbook: doa2_bot", stats: { fights_s: 312.5, jumps: 14, p1_hp: 240 }, age_s: 2.2 },
  { active: [{ tool: "ghidra_analyze", progress: { msg: "decompiling hold check" } }, { tool: "stream_frames", state: "running" }],
    coordinator: { runs: [{ name: "rea_assimilate DOA2", state: "running", progress: "3/9" }, { name: "inbox triage", state: "running" }] },
    recent_results: [{ tool: "cheats", state: "done" }] });
assert.deepStrictEqual(m.bot[0], ["Autoplay", "playing"]);
assert(m.bot.some(([k, v]) => k === "Time in fights (s)" && v === "312.50"));
assert(m.bot.some(([k, v]) => k === "Updated" && v === "2 s ago"));
assert.deepStrictEqual(m.analysis.map(r => r.tool), ["ghidra_analyze", "rea_assimilate DOA2"]);
assert.deepStrictEqual(m.jobs.map(r => r.tool), ["stream_frames"]);
assert.deepStrictEqual(m.runs.map(r => r.tool), ["inbox triage"]);
assert.deepStrictEqual(m.results, [{ tool: "cheats", what: "done" }]);

const empty = W.model({}, null);
assert.deepStrictEqual(empty, { bot: [], analysis: [], jobs: [], runs: [], results: [] });
const h = W.html(empty, "Watching <x>");
assert(h.includes("No autoplay on this game.") && h.includes("Watching &#60;x&#62;"));
assert(W.html(W.model({ running: true, mission: "<img onerror=1>" }, null), "t").includes("&#60;img"));   // escaped
console.log("watch-analytics ok");
