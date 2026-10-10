const { test } = require('node:test');
const assert = require('node:assert/strict');
const { badge, benchmark } = require('../clients/desktop/request-solvers.js');
const solver = { service: 'ollama-cloud', model: 'kimi-k2.7-code', system: 'Hermes', verification: 'Focused tests and live screenshot verified', verified_by: 'Codex' };
const done = (extra = {}) => ({ status: 'done', solved_by: solver, metrics: {}, ...extra });

test('badge credits the implementation service and records the reviewer separately', () => {
  const html = badge(done());
  assert.match(html, /Ollama Cloud/); assert.match(html, /kimi-k2.7-code/);
  assert.match(html, /Verified by Codex/); assert.match(html, /data-solver-benchmark="ollama-cloud"/);
});

test('legacy usage, reopened issues and automated review check-ins do not gain wins', () => {
  const data = benchmark([done(), done({ status: 'in_progress' }), done({ automated: true }),
    { status: 'done', metrics: { provider: 'deepseek', model: 'deepseek-v4-pro' } }]);
  assert.equal(data.groups.length, 1); assert.equal(data.groups[0].count, 1); assert.equal(data.unrecorded, 1);
  assert.match(badge({ status: 'done', metrics: { model: 'legacy' } }), /Unrecorded/);
  assert.equal(badge(done({ status: 'open' })), '');
});

test('a verified auto report counts and service/model combinations remain separate', () => {
  const data = benchmark([done({ automated: true, context: { auto_report: true } }), done({ solved_by: { ...solver, model: 'glm-5.3' } })]);
  assert.equal(data.groups.length, 2); assert.equal(data.groups[0].count, 1);
});

test('comparison uses the credited model usage and excludes mixed ticket totals and queue duration', () => {
  const data = benchmark([done({ metrics: { tokens_in: 999999, tokens_out: 99999, duration_s: 900,
    usage_by_solver: [
      { provider: 'ollama-cloud', model: solver.model, system: 'Hermes', tokens_in: 100, tokens_out: 20, agent_seconds: 12, timed: true },
      { provider: 'codex', model: 'GPT-6', system: 'Codex', tokens_in: 800, tokens_out: 50, agent_seconds: 100, timed: true }
    ] } })]);
  assert.equal(data.groups[0].tokens, 120); assert.equal(data.groups[0].seconds, 12);
  assert.equal(benchmark([done({ metrics: { tokens_in: 100, tokens_out: 50, agent_seconds: 900 } })]).groups[0].metered, 0);
});

test('unavailable usage is never presented as a zero-token successful model', () => {
  const metrics = { usage_by_solver: [{ provider: 'ollama-cloud', model: solver.model, system: 'Hermes', tokens_in: 0, tokens_out: 0, token_count_unavailable: 1 }] };
  assert.equal(benchmark([done({ metrics })]).groups[0].metered, 0);
});

test('untrusted model and service text is escaped in badges', () => {
  const html = badge(done({ solved_by: { ...solver, model: '<script>alert(1)</script>', service: '" onclick="bad' } }));
  assert.doesNotMatch(html, /<script>/); assert.match(html, /&lt;script&gt;/);
});
