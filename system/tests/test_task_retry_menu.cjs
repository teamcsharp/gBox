// #2398: a failed task in the Technical list can be retried from a right-click menu (POST /api/jobs/{id}/retry).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
function between(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing desktop source boundary: ${start}`);
  return html.slice(a, b);
}

test('recent task cards carry their state and failed ones say they can be retried', () => {
  const load = between('async function tasksLoad()', 'async function tkHermesRefresh');
  assert.match(load, /data-detail-job="\$\{j\.id\}" data-job-state="\$\{esc\(j\.state\)\}"/);
  assert.match(load, /\["failed", "rejected", "invalid"\]\.includes\(j\.state\) \? ' <span class="mut" title="Right-click: retry this task">/);
});

test('a right-click on a failed card offers Retry and posts the retry', () => {
  const menu = between('function taskRetryMenu(x, y, id, label)', '$("#tk-body").addEventListener("toggle"');
  assert.match(menu, /gbox\.api\(`\/api\/jobs\/\$\{id\}\/retry`, \{\}\)/);
  assert.match(menu, /Retry this task/);
  assert.match(menu, /\$\("#tk-technical"\)\.addEventListener\("contextmenu"/);
  assert.match(menu, /\["failed", "rejected", "invalid"\]\.includes\(d\.dataset\.jobState\)/, 'only ended-in-failure cards get the menu');
  assert.match(menu, /tasksLoad\(\);/, 'the list refreshes after the retry');
});
