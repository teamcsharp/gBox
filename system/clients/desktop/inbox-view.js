// Preserve edits, expanded threads and the reader's place when background inbox data changes (#2395: a refresh
// must never reset the view while the operator is looking at or scrolling through it).
const INBOX_READING = { down: 10000, moved: 30000, scrolled: 2000, keys: 5000 };   // ms a signal counts as "reading"

function inboxScroller(host) {
  // The element that actually scrolls the list: the nearest scrolling ancestor, else the document.
  for (let el = host; el && el !== document.body; el = el.parentElement) {
    const style = getComputedStyle(el);
    if (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight) return el;
  }
  return document.scrollingElement || document.documentElement;
}

function inboxWatch(host) {
  if (host._gboxReading) return host._gboxReading;
  const reading = host._gboxReading = { down: 0, moved: 0, scrolled: 0, keys: 0, hover: false };
  const stamp = key => () => { reading[key] = Date.now(); };
  host.addEventListener("pointerdown", stamp("down"), true);
  host.addEventListener("pointermove", stamp("moved"), true);
  host.addEventListener("wheel", stamp("scrolled"), { capture: true, passive: true });
  host.addEventListener("keydown", stamp("keys"), true);
  host.addEventListener("pointerenter", () => { reading.hover = true; });
  host.addEventListener("pointerleave", () => { reading.hover = false; });
  document.addEventListener("pointerup", () => { reading.down = 0; }, true);
  inboxScroller(host).addEventListener("scroll", stamp("scrolled"), { capture: true, passive: true });
  return reading;
}

// The reader is busy with the list: holding a button, scrolling, typing, selecting text, or hovering it while
// they moved the pointer recently. A refresh waits; the next poll catches up once they look away.
window.inboxReading = function (host, now = Date.now()) {
  const r = inboxWatch(host);
  if (r.down && now - r.down < INBOX_READING.down) return true;
  if (now - r.scrolled < INBOX_READING.scrolled) return true;
  if (now - r.keys < INBOX_READING.keys) return true;
  if (r.hover && now - r.moved < INBOX_READING.moved) return true;
  const sel = window.getSelection ? window.getSelection() : null;
  return !!(sel && !sel.isCollapsed && sel.rangeCount && host.contains(sel.getRangeAt(0).commonAncestorContainer));
};

window.updateInboxView = function (host, key, render, replyAttachments = {}) {
  inboxWatch(host);                                   // from the first render on, so later refreshes know the reader
  const active = document.activeElement;
  if (host.contains(active) && active.closest("input,textarea,select,[contenteditable]")) return false;
  if (host._gboxViewKey === key) return false;
  if (host._gboxViewKey !== undefined && window.inboxReading(host)) return false;
  const drafts = host._gboxDrafts ||= new Map();
  for (const card of host.querySelectorAll(".req[data-id]")) {
    const reply = card.querySelector(":scope > .thread .reply");
    if (reply) drafts.set(card.dataset.id, reply.value);
  }
  // A group's summary text changes with its count and newest ticket, so a group is remembered by its kind (#1788).
  const detailKey = detail => (detail.closest(".req[data-id]")?.dataset.id || "root") + ":" + (detail.dataset.groupKey ? "group:" + detail.dataset.groupKey : detail.querySelector(":scope > summary")?.textContent);
  const expanded = host._gboxExpanded ||= new Map();
  for (const detail of host.querySelectorAll("details")) expanded.set(detailKey(detail), detail.open);
  const scroller = inboxScroller(host), scroll = { top: scroller.scrollTop, left: scroller.scrollLeft, host: host.scrollTop };
  host.innerHTML = render();
  host._gboxViewKey = key;
  for (const card of host.querySelectorAll(".req[data-id]")) {
    const reply = card.querySelector(":scope > .thread .reply");
    if (reply) reply.value = drafts.get(card.dataset.id) || "";
    const preview = card.querySelector(":scope > .thread .reply-att");
    if (preview) for (const attachment of replyAttachments[card.dataset.id] || []) {
      const figure = document.createElement("figure"), image = document.createElement("img");
      image.src = `data:${attachment.type};base64,${attachment.b64}`; image.alt = attachment.name || "Attached image";
      figure.append(image); preview.append(figure);
    }
  }
  for (const detail of host.querySelectorAll("details")) if (expanded.has(detailKey(detail))) detail.open = expanded.get(detailKey(detail));
  host.scrollTop = scroll.host;
  scroller.scrollTop = scroll.top; scroller.scrollLeft = scroll.left;
  return true;
};
