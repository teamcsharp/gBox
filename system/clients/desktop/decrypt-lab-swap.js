/* Request validation shared by the archive swap form and its focused tests. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.GBoxArchiveSwap = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function optionalIndex(value, label) {
    const text = String(value ?? '').trim();
    if (!text) return undefined;
    const index = Number(text);
    if (!/^\d+$/.test(text) || !Number.isSafeInteger(index)) {
      throw new Error(`${label} index must be a nonnegative whole number (zero is the first entry)`);
    }
    return index;
  }

  function request(fields) {
    const body = {};
    for (const key of ['title', 'arc_path', 'entry', 'donor_arc', 'donor_entry']) {
      body[key] = String(fields[key] ?? '').trim();
      if (!body[key]) throw new Error('give the title, archive, its entry, and the donor archive and entry');
    }
    body.build = String(fields.build ?? '').trim() || 'gbox-lab';
    for (const [key, label] of [['entry_index', 'Target'], ['donor_index', 'Donor']]) {
      const index = optionalIndex(fields[key], label);
      if (index !== undefined) body[key] = index;
    }
    return body;
  }

  return { request };
});
