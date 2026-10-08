// Preserve edits and expanded threads when background inbox data changes.
window.updateInboxView = function (host, key, render, replyAttachments = {}) {
  const active = document.activeElement;
  if (host.contains(active) && active.closest("input,textarea,select,[contenteditable]")) return false;
  if (host._gboxViewKey === key) return false;
  const drafts = host._gboxDrafts ||= new Map();
  for (const card of host.querySelectorAll(".req[data-id]")) {
    const reply = card.querySelector(":scope > .thread .reply");
    if (reply) drafts.set(card.dataset.id, reply.value);
  }
  const detailKey = detail => (detail.closest(".req[data-id]")?.dataset.id || "root") + ":" + detail.querySelector(":scope > summary")?.textContent;
  const expanded = host._gboxExpanded ||= new Map();
  for (const detail of host.querySelectorAll("details")) expanded.set(detailKey(detail), detail.open);
  const scroll = host.scrollTop;
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
  host.scrollTop = scroll;
  return true;
};
