// Tasks window Providers view (2026-10-13): which Hermes provider did the work and which is out of credit.
// The renderers in clients/desktop/hermes-providers.js run on plain data from GET /api/hermes/providers;
// the desktop wiring (containers, 5 s poll, window toggle, provider on run nodes and details) is checked as text.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/hermes-providers.js'), 'utf8');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');

function load() {
  const ctx = { Math, JSON, Date, Object, Array, Number, String, Set, Map };
  ctx.window = ctx; vm.createContext(ctx); vm.runInContext(source, ctx);
  return ctx.GBoxProviders;
}
const NOW = 1_760_400_000;
const OPUS = 'anthropic/claude-opus-5.5';
const data = {
  window: 'today', window_label: 'Today', generated_at: NOW,
  recommendation: 'openrouter did the most completed work per dollar (today): 1 run for $2.50, $2.50 a run. Exhausted: nous (out of credit), ollama-cloud (usage limit).',
  routes: [
    { key: `openrouter/${OPUS}`, provider: 'openrouter', model: OPUS, current: true, in_routes: true, local: false,
      status: { state: 'working', label: 'Working' }, runs_completed: 12, runs_failed: 1, calls_ok: 140, calls_failed: 2,
      tokens: 4_250_000, wall_s: 7260, last_error: null,
      balance: { available: true, remaining_usd: 0.12, total_credits: 125, key_limit: 150, usage_daily: 24.85, usage_weekly: 80 } },
    { key: `nous/${OPUS}`, provider: 'nous', model: OPUS, current: false, in_routes: true, local: false,
      status: { state: 'out_of_credit', label: 'Out of credit · cooling until 13:05' }, cooldown: { until: NOW + 3600, category: 'quota' },
      runs_completed: 0, runs_failed: 0, calls_ok: 0, calls_failed: 3, tokens: 0, wall_s: 0,
      last_error: { ts: NOW - 600, text: 'HTTP 402: Insufficient available credits <script>', code: 402, kind: 'out_of_credit' },
      balance: { available: false, note: 'Balance not available (Nous has no balance API); status is read from its latest errors' } },
    { key: 'llamacpp/Qwen3.6-35B-A3B-UD-Q4_K_M', provider: 'llamacpp', model: 'Qwen3.6-35B-A3B-UD-Q4_K_M', current: false,
      in_routes: false, local: true, status: { state: 'working', label: 'Working' }, runs_completed: 2, runs_failed: 0,
      calls_ok: 29, calls_failed: 0, tokens: 52_000, wall_s: 95, last_error: null, balance: { available: false, note: 'Local model: no credit needed' } },
  ],
  providers: [
    { provider: 'openrouter', local: false, status: { state: 'working', label: 'Working' }, runs_completed: 12, calls_ok: 140, calls_failed: 2,
      tokens: 4_250_000, wall_s: 7260, spend_usd: 24.85, spend_source: 'OpenRouter account', per_run_usd: 2.071 },
    { provider: 'nous', local: false, status: { state: 'out_of_credit', label: 'Out of credit' }, runs_completed: 0, calls_ok: 0, calls_failed: 3,
      tokens: 0, wall_s: 0, spend_usd: null, spend_source: null, per_run_usd: null },
  ],
  runs: [{ session_id: 'cron_a_20261013_090000', job_id: 'a', name: 'gBox inbox task mode', start: NOW - 3600, status: 'completed',
    provider: 'openrouter', model: OPUS, tokens: 3600, wall_s: 125, tried: [`nous/${OPUS}`, 'ollama-cloud/kimi-k2.6'] }],
  runs_total: 14, runs_unattributed: 1,
};

test('Visual cards: one per route with status, window numbers, credit and the last error', () => {
  const P = load(), html = P.cards(data, { window: 'today', now: NOW });
  assert.equal((html.match(/<article class="tkp-card/g) || []).length, 3);
  assert.match(html, /<b>Providers · Today<\/b>/);
  assert.match(html, /data-tkp-window="today" aria-pressed="true">Today/);
  assert.match(html, /data-tkp-window="7d" aria-pressed="false">7 days/);
  assert.match(html, /openrouter did the most completed work per dollar/);
  const card = key => html.slice(html.indexOf(`data-tkp-route="${key}"`), html.indexOf('</article>', html.indexOf(`data-tkp-route="${key}"`)));
  const or = card(`openrouter/${OPUS}`);
  assert.match(html, /<article class="tkp-card working current" data-tkp-route="openrouter/);
  assert.match(or, /tkp-tag current">current/);
  assert.match(or, /<dt>Runs done<\/dt><dd>12 <small>· 1 failed<\/small>/);
  assert.match(or, /<dt>Model calls<\/dt><dd>140 <small>· 2 failed<\/small>/);
  assert.match(or, /<dt>Tokens<\/dt><dd>4\.3M/);
  assert.match(or, /<dt>Wall time<\/dt><dd>2h 01m/);
  assert.match(or, /\$0\.12 left · \$24\.85 today · of \$125 credit · key limit \$150/);
  const nous = card(`nous/${OPUS}`);
  assert.match(html, /<article class="tkp-card out_of_credit" data-tkp-route="nous/);
  assert.match(nous, /Out of credit · cooling until 13:05/);
  assert.match(nous, /Balance not available \(Nous has no balance API\)/);
  assert.match(nous, /HTTP 402: Insufficient available credits &lt;script&gt; · 10m ago/);
  assert.doesNotMatch(html, /<script>/, 'error text is escaped');
  const local = card('llamacpp/Qwen3.6-35B-A3B-UD-Q4_K_M');
  assert.match(local, /tkp-tag local">local model/);
  assert.match(local, /tkp-tag">not in routes/);
  assert.match(local, /Local model: no credit needed/);
  assert.match(P.cards(data, { window: '7d', now: NOW }), /\$80\.00 this week/);
});

test('Technical table: per route, per provider spend and recent run attribution', () => {
  const P = load(), html = P.table(data, { window: 'today', now: NOW });
  assert.match(html, /<b>Hermes providers · Today<\/b>/);
  assert.match(html, /<th>Route<\/th><th>Status now<\/th><th>Runs done<\/th><th>Runs failed<\/th><th>Calls ok \/ failed<\/th><th>Tokens<\/th><th>Wall time<\/th><th>Credit<\/th><th>Last error<\/th>/);
  assert.equal((html.match(/<tr class="tkp-row/g) || []).length, 3);
  assert.match(html, /<tr class="tkp-row out_of_credit"><td><b>nous<\/b>/);
  assert.match(html, /<span class="mut" title="Balance not available \(Nous has no balance API\)[^"]*">not available<\/span>/);
  assert.match(html, /<td>\$0\.12 left · \$24\.85 today · of \$125 credit · key limit \$150<\/td>/);
  assert.match(html, /<td><span class="mut">local<\/span><\/td>/);
  assert.match(html, /<td>\$24\.85 <span class="mut">OpenRouter account<\/span><\/td>\s*<td>\$2\.07<\/td>/);
  assert.match(html, /<details data-tk-key="tkp-runs"><summary>Recent runs and who served them \(14 in window, 1 without a successful call\)/);
  assert.match(html, /<td>openrouter · anthropic\/claude-opus-5\.5<\/td><td>completed<\/td>/);
  assert.match(html, /nous\/anthropic\/claude-opus-5\.5 → ollama-cloud\/kimi-k2\.6/);
});

test('loading, errors and an empty server render without throwing', () => {
  const P = load();
  assert.match(P.cards(null), /Loading providers…/);
  assert.match(P.cards({ error: 'HTTP 503 <b>' }), /Providers unavailable: HTTP 503 &lt;b&gt;/);
  assert.match(P.table({ error: 'down' }), /Providers unavailable: down/);
  assert.match(P.cards({ window: '7d', routes: [], providers: [], runs: [] }), /No Hermes routes or model calls found/);
  assert.match(P.table({ window: '7d', routes: [], providers: [], runs: [] }), /No Hermes routes or model calls found/);
});

test('run label and number formats', () => {
  const P = load();
  assert.equal(P.runLabel({ provider: 'llamacpp', model: 'Qwen3.6-35B-A3B-UD-Q4_K_M' }), 'llamacpp · Qwen3.6-35B-A3B-UD-Q4_K_M');
  assert.equal(P.runLabel({ model: 'glm-5.3' }), 'glm-5.3');
  assert.equal(P.runLabel({}), '');
  assert.deepEqual([P.tokens(950), P.tokens(12_400), P.tokens(3_400_000), P.tokens(45_000_000)], ['950', '12k', '3.4M', '45M']);
  assert.deepEqual([P.duration(42), P.duration(600), P.duration(3725)], ['42s', '10m', '1h 02m']);
  assert.equal(P.balance({ available: false }), 'Balance not available');
  assert.equal(P.balance(null), 'Balance not available');
});

test('desktop wiring: containers, the 5 s poll, window toggle and provider on run nodes and details', () => {
  assert.match(desktop, /<script src="task-activity\.js"><\/script>\r?\n<script src="hermes-providers\.js"><\/script>/);
  assert.match(desktop, /<div class="tkv-stats" id="tkv-stats"><\/div>\r?\n\s*<div class="tkp" id="tkv-providers"><\/div>/);
  assert.match(desktop, /hidden><div id="tk-providers"><\/div><div id="tk-local"><\/div>/);
  assert.match(desktop, /gbox\.api\(`\/api\/hermes\/providers\?window=\$\{encodeURIComponent\(want\)\}`\)/);
  const load = desktop.slice(desktop.indexOf('async function tasksLoad()'), desktop.indexOf('async function tkHermesRefresh'));
  assert.match(load, /tkVisualUpdate\(d\);\r?\n\s*tkProvidersLoad\(\);/);
  assert.match(load, /<div class="meta">\$\{esc\(window\.GBoxProviders\?\.runLabel\(run\) \|\| "Hermes"\)\}/);
  assert.match(desktop, /kind:"hermes", name:run\.name \|\| "Hermes run", state:run\.state,\r?\n\s*provider:run\.provider \|\| ""/);
  assert.match(desktop, /<small>\$\{task\.kind\.replace\("_", " "\)\} · \$\{task\.state\}\$\{task\.provider \? ` · \$\{task\.provider/);
  assert.match(desktop, /Started \$\{tkAge\(started\)\} ago` : "Live process"\}\$\{item\.kind === "hermes" && d\.provider \? ` · \$\{esc\(d\.provider\)\}` : ""\}\$\{d\.model/);
  assert.match(desktop, /\$\("#tkv-providers"\)\.onclick = tkProvidersWindow;/);
  assert.match(desktop, /\$\("#tk-providers"\)\.onclick = tkProvidersWindow;/);
  assert.match(desktop, /localStorage\.setItem\("gbox\.tasks\.providersWindow"/);
  // The technical table keeps the reader's place like the rest of the list.
  assert.match(desktop, /tkRender\(\$\("#tk-providers"\), P\.table\(TK\.providers, \{ window: TK\.providersWindow \}\), \$\("#tk-technical"\)\)/);
});

test('local mode banner and the Spark helper card (docs/hermes-local-fallback.md)', () => {
  const P = load();
  const local = { enabled: true, provider: 'spark-local', model: 'gpt-oss:20b', active: true,
    reason: 'Every paid route is cooling down or out of credit', next_paid_at: null,
    calls_ok: 42, tokens: 1_250_000, runs_completed: 3, refused_while_playing: 2, trimmed_calls: 1 };
  const grunt = { enabled: true, running: 'draft_pr_tests', doing: 'testing a Hermes draft PR', label: 'Spark helper: testing a Hermes draft PR',
    chores: [{ name: 'triage_inbox', title: 'Inbox triage', last_run: NOW - 120, last_status: 'ok', last_result: { triaged: 2 } },
             { name: 'fingerprints', title: 'Assimilate fingerprints', last_run: NOW - 900, last_status: 'error', last_result: { error: 'x' } }] };
  const html = P.cards({ ...data, local, grunt }, { window: 'today', now: NOW });
  assert.match(html, /<div class="tkp-local active" data-tkp-local="active">/);
  assert.match(html, /<b>Hermes is on the local model<\/b><span class="tkp-tag local">spark-local · gpt-oss:20b<\/span>/);
  assert.match(html, /42 calls · 1\.3M tokens · 3 runs · 2 held while you played · 1 trimmed to fit/);
  assert.match(html, /<article class="tkp-card tkp-grunt working" data-tkp-grunt>/);
  assert.match(html, /Spark helper: testing a Hermes draft PR/);
  assert.match(html, /Last: Inbox triage · 2m ago/);
  assert.match(html, /1 chore failed last time/);
  assert.equal((html.match(/<article class="tkp-card/g) || []).length, 4);
  const standby = P.cards({ ...data, local: { ...local, active: false },
    grunt: { ...grunt, running: null, doing: null, label: '', waiting: 'a build is running (characters use)' } }, { now: NOW });
  assert.match(standby, /Local fallback ready/);
  assert.match(standby, /Standby: used only when every paid route is out of credit/);
  assert.match(standby, /tkp-grunt cooling/);
  assert.match(standby, /Spark helper waiting: a build is running/);
  const table = P.table({ ...data, local, grunt }, { now: NOW });
  assert.match(table, /Hermes is on the local model/);
  assert.match(table, /<details data-tk-key="tkp-grunt"><summary>Spark helper: testing a Hermes draft PR<\/summary>/);
  assert.match(table, /<td><b>Inbox triage<\/b><\/td>\s*<td>2m ago<\/td><td>ok<\/td>/);
  assert.equal(P.localBanner({ enabled: false }), '');
  assert.equal(P.gruntCard(null), '');
});
