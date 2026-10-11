// #1296: the desktop app says why this PC's worker is offline and the ↻ icon reconnects it.
// Extracts the real functions from clients/desktop/main.js and index.html (no Electron needed).
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const mainJs = fs.readFileSync(path.join(root, "clients/desktop/main.js"), "utf8");
const page = fs.readFileSync(path.join(root, "clients/desktop/index.html"), "utf8");

function grab(src, name) {
  const start = src.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  let i = src.indexOf("{", start), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) break;
  }
  return src.slice(start, i + 1);
}

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const ago = t => `${Math.round(Date.now() / 1000 - t)} s ago`;
const ctx = vm.createContext({ esc, ago });
vm.runInContext(grab(mainJs, "workerExitReason") + "\n" + grab(page, "workerReconnectNote"), ctx);

// The exact console the operator attached to #1296 (i9-NUC worker crash loop).
const tail = `20:22:04.201 [win-worker] Traceback (most recent call last):\r
  File "C:\\_tools\\gBox\\system\\gbox\\worker.py", line 210, in run\r
    raise RuntimeError('Worker activation held: finished results still await verified delivery')\r
RuntimeError: Worker activation held: finished results still await verified delivery\r
20:22:04.909 [win-worker] \n`;

test("exit reason is the final exception line, not the traceback frame", () => {
  assert.strictEqual(ctx.workerExitReason(tail),
    "RuntimeError: Worker activation held: finished results still await verified delivery");
  assert.strictEqual(ctx.workerExitReason("connecting\nplain last line\n"), "plain last line");
  assert.strictEqual(ctx.workerExitReason(""), "");
});

test("offline own worker: panel names the cause and offers reconnect", () => {
  const html = ctx.workerReconnectNote({ name: "i9-NUC", online: false },
    { running: false, lastExit: { code: 1, at: Date.now() - 5000, reason: ctx.workerExitReason(tail) } });
  assert.match(html, /This PC's worker isn't running\./);
  assert.match(html, /↻ reconnects it/);
  assert.match(html, /Last worker exit \(code 1, \d+ s ago\): RuntimeError: Worker activation held/);
  assert.match(html, /data-reconnect-worker="1"/);
});

test("running but not checked in, and online, read differently", () => {
  assert.match(ctx.workerReconnectNote({ name: "i9-NUC", online: false }, { running: true }),
    /running but hasn't checked in/);
  const ok = ctx.workerReconnectNote({ name: "i9-NUC", online: true }, { running: true, lastExit: null });
  assert.match(ok, /connected\. ↻ refreshes this panel/);
  assert.doesNotMatch(ok, /Last worker exit/);
});

test("reason text is escaped", () => {
  const html = ctx.workerReconnectNote({ online: false }, { lastExit: { code: 1, at: Date.now(), reason: "Error: <img src=x>" } });
  assert.doesNotMatch(html, /<img/);
});

test("refresh icon reconnects only this PC's offline worker; main has a restart op", () => {
  const refresh = page.slice(page.indexOf('$("#svc-refresh").onclick'), page.indexOf('floating($("#svcpanel")'));
  assert.match(refresh, /SVC_KEY\.startsWith\("worker:"\) && S\.workerName && \$\("#svc-sub"\)\.textContent === "offline"/);
  assert.match(refresh, /return svcReconnect\(SVC_KEY\)/);
  assert.match(mainJs, /if \(op === "restart"\) return restartWorker\(\);/);
  assert.match(mainJs, /return \{ running: !!worker, lastExit: workerLastExit \};/);
  assert.match(mainJs, /workerLastExit = \{ code, at: Date\.now\(\), reason: workerExitReason\(workerTail\) \};/);
});
