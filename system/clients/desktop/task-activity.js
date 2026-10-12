// Status-bar strip for background work: local tasks and the Spark's queued/running jobs.
// × cancels the shown task; clicking the strip lists every task with its own cancel and "Cancel all".
window.TaskActivity = class {
  constructor(host) {
    this.host = host; this.local = new Map(); this.jobs = []; this.dismissed = new Set(); this.note = "";
    host.innerHTML = '<progress aria-label="Background task progress" style="width:60px;height:8px;flex:none"></progress><b style="white-space:nowrap"></b><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span><i style="flex:none;font-style:normal;opacity:.75"></i><button type="button" aria-label="Cancel and close task" title="Cancel and close this task" style="flex:none;background:none;border:0;color:inherit;cursor:pointer;padding:0 5px;font-size:16px">×</button>';
    host.style.cssText = "display:none;align-items:center;gap:6px;min-width:0;overflow:hidden;cursor:pointer";
    this.list = document.createElement("div");
    this.list.style.cssText = "display:none;position:fixed;left:8px;bottom:30px;z-index:9999;min-width:320px;max-width:560px;max-height:50vh;overflow:auto;background:var(--panel,#1d1d22);color:inherit;border:1px solid var(--line,#333);border-radius:8px;padding:6px;box-shadow:0 6px 24px #0008;font-size:12px";
    this.list.style.display = "none"; document.body.appendChild(this.list);
    host.querySelector("button").onclick = e => { e.stopPropagation(); if (this.active) this.cancel(this.active); };
    host.onclick = () => { this.list.style.display = this.list.style.display === "none" ? "block" : "none"; this.render(); };
    this.list.onclick = async e => {
      const one = e.target.closest("[data-cancel]"), all = e.target.closest("[data-cancel-all]");
      if (one) await this.cancel({ id: one.dataset.cancel, local: one.dataset.local === "1" });
      if (all) for (const t of this.tasks()) await this.cancel(t);
    };
    document.addEventListener("click", e => { if (!host.contains(e.target) && !this.list.contains(e.target)) this.list.style.display = "none"; });
  }
  tasks() {
    return [...[...this.local.entries()].reverse().map(([id, t]) => ({ id, local: true, title: t.title, message: t.message })),
            ...this.jobs.map(j => ({ id: j.id, local: false, title: j.title || j.tool, state: j.state, pct: j.progress?.pct,
                                     message: (typeof j.progress === "object" ? j.progress?.msg : j.progress) || j.state }))];
  }
  async cancel({ id, local }) {
    const result = local ? await gbox.cancel(id) : await gbox.api(`/api/jobs/${id}/cancel`, {});
    // A local task that already ended, or a job the Spark no longer has, is gone either way: close it.
    const gone = local ? true : (result.ok || /404|not found/i.test(result.error || ""));
    if (!gone) { this.note = `Couldn't cancel: ${result?.error || "unknown error"}`; setTimeout(() => { this.note = ""; this.render(); }, 6000); }
    else { this.dismissed.add(`${local ? "local" : "job"}:${id}`); this.local.delete(id); this.jobs = this.jobs.filter(job => job.id !== id); }
    this.render();
  }
  start(id, title) { this.dismissed.delete(`local:${id}`); this.local.set(id, { title, message: "Starting…" }); this.render(); }
  log(id, text) {
    const task = this.local.get(id); if (!task) return;
    const lines = String(text).replace(/\x1b\[[0-9;]*[A-Za-z]/g, "").trim().split(/[\r\n]+/).filter(Boolean);
    if (lines.length) task.message = lines.at(-1); this.render();
  }
  end(id) { this.local.delete(id); this.render(); }
  remote(jobs) { this.jobs = jobs.filter(job => ["queued", "running"].includes(job.state) && !this.dismissed.has(`job:${job.id}`)); this.render(); }
  render() {
    const task = Array.from(this.local.values()).at(-1), job = this.jobs.find(job => job.state === "running") || this.jobs[0];
    const active = task || job, all = this.tasks();
    this.active = active ? { id: task ? [...this.local.keys()].at(-1) : job.id, local: !!task } : null;
    this.host.style.display = active ? "flex" : "none";
    const audit = document.getElementById("sb-audit"); if (audit) audit.style.display = active ? "none" : "";
    if (!active) { this.list.style.display = "none"; return; }
    const title = task?.title || job.title || job.tool;
    const message = this.note || task?.message || (typeof job.progress === "object" ? job.progress?.msg : job.progress) || job.state;
    const progress = this.host.querySelector("progress"), pct = task ? null : job.progress?.pct;
    progress.max = 100;
    if (typeof pct === "number" && Number.isFinite(pct)) progress.value = Math.max(0, Math.min(100, pct));
    else progress.removeAttribute("value");
    this.host.querySelector("b").textContent = title;
    this.host.querySelector("span").textContent = message;
    this.host.querySelector("i").textContent = all.length > 1 ? `+${all.length - 1} more` : "";
    this.host.title = `${title}: ${message}${all.length > 1 ? ` (${all.length} tasks; click to see all)` : " (click for details)"}`;
    this.host.setAttribute("aria-label", this.host.title);
    if (this.list.style.display === "none") return;
    const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    this.list.innerHTML = `<div style="display:flex;align-items:center;gap:8px;padding:2px 4px 6px"><b style="flex:1">Background tasks (${all.length})</b>`
      + `<button type="button" data-cancel-all="1" style="cursor:pointer">Cancel all</button></div>`
      + all.map(t => `<div style="display:flex;align-items:center;gap:8px;padding:4px;border-top:1px solid var(--line,#333)">`
        + `<div style="flex:1;min-width:0"><b>${esc(t.title)}</b> <span style="opacity:.7">${esc(t.local ? "this PC" : t.state)}${typeof t.pct === "number" ? ` · ${Math.round(t.pct)}%` : ""}</span>`
        + `<div style="opacity:.75;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.message)}</div></div>`
        + `<button type="button" data-cancel="${esc(t.id)}" data-local="${t.local ? 1 : 0}" title="Cancel this task" style="cursor:pointer">Cancel</button></div>`).join("");
  }
};
