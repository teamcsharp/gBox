// Select once per app session. Never move a running game between control planes.
function createConnection({ configured, probe, startLocal, standalone = false }) {
  let pending;
  return function connect() {
    if (!pending) pending = (async () => {
      const s = configured();
      if (standalone || await probe(s.apiUrl)) return { mode: "remote" };
      return { mode: "local", ...await startLocal(s) };
    })().catch(error => { pending = null; throw error; });
    return pending;
  };
}
module.exports = { createConnection };
