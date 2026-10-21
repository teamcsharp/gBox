// A report acknowledgement can wait for bounded evidence preparation and durable queue writes.
// Keep unrelated desktop requests on their existing deadlines.
function timeoutMs(path, method) {
  return method === 'POST' && /^\/api\/sessions\/[^/?]+\/coach$/.test(path) ? 60000 : 0;
}
module.exports = { timeoutMs };
