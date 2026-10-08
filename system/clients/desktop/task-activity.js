window.TaskActivity = class {
  constructor(host) {
    this.host = host; this.local = new Map(); this.jobs = [];
    host.innerHTML = '<progress aria-label="Background task progress" style="width:60px;height:8px"></progress><b></b><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>';
    host.style.cssText = "display:none;align-items:center;gap:6px;min-width:0;overflow:hidden";
  }
  start(id, title) { this.local.set(id, { title, message: "Starting…" }); this.render(); }
  log(id, text) {
    const task = this.local.get(id); if (!task) return;
    const lines = String(text).replace(/\x1b\[[0-9;]*[A-Za-z]/g, "").trim().split(/[\r\n]+/).filter(Boolean);
    if (lines.length) task.message = lines.at(-1); this.render();
  }
  end(id) { this.local.delete(id); this.render(); }
  remote(jobs) { this.jobs = jobs.filter(job => ["queued", "running"].includes(job.state)); this.render(); }
  render() {
    const task = Array.from(this.local.values()).at(-1), job = this.jobs.find(job => job.state === "running") || this.jobs[0];
    const active = task || job;
    this.host.style.display = active ? "flex" : "none";
    const audit = document.getElementById("sb-audit"); if (audit) audit.style.display = active ? "none" : "";
    if (!active) return;
    const title = task?.title || job.title || job.tool;
    const message = task?.message || (typeof job.progress === "object" ? job.progress?.msg : job.progress) || job.state;
    const progress = this.host.querySelector("progress"), pct = task ? null : job.progress?.pct;
    progress.max = 100;
    if (typeof pct === "number" && Number.isFinite(pct)) progress.value = Math.max(0, Math.min(100, pct));
    else progress.removeAttribute("value");
    this.host.querySelector("b").textContent = title;
    this.host.querySelector("span").textContent = message;
    this.host.title = `${title}: ${message}`;
    this.host.setAttribute("aria-label", this.host.title);
  }
};
