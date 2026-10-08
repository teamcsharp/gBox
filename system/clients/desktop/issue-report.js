// Issue drafts are submitted only by Send report. Binary attachments retain their original bytes.
window.openIssueReport = function ({ diagnostics, submit, clipboardFiles, onSent }) {
  const current = document.getElementById("issue-modal");
  if (current) { current.querySelector("input").focus(); return; }
  const dialog = document.createElement("dialog");
  dialog.id = "issue-modal";
  dialog.style.cssText = "width:min(620px,85vw);max-height:85vh;overflow:auto;background:var(--bg,#16161a);color:var(--fg,#eee);border:1px solid var(--line,#444);border-radius:12px;padding:22px";
  dialog.innerHTML = `<form style="display:flex;flex-direction:column;height:100%;min-height:0">
    <h2 style="margin:0 0 16px;flex-shrink:0">Report issue</h2>
    <div id="issue-fields" style="flex:1;min-height:0;overflow:auto">
    <label for="issue-subject">Subject</label>
    <input id="issue-subject" required maxlength="140" placeholder="Briefly describe the problem" style="width:100%;box-sizing:border-box;margin:6px 0 14px">
    <label for="issue-body">Issue</label>
    <textarea id="issue-body" required rows="6" placeholder="What happened? What did you expect?" style="width:100%;box-sizing:border-box;margin:6px 0 12px"></textarea>
    <div id="issue-drop" tabindex="0" style="border:1px dashed var(--line,#666);padding:12px;border-radius:6px">
      Paste images or files here, or drop files of any format.
      <div style="margin-top:8px"><button type="button" class="act" id="issue-add">Add files…</button>
      <button type="button" class="act" id="issue-paste">Paste files</button></div>
      <input type="file" id="issue-files" multiple hidden>
      <div id="issue-attachments" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px"></div>
    </div>
    <p style="font-size:12px;color:var(--mut,#aaa)">A screenshot and available game diagnostics are attached when you send.</p>
    <p id="issue-status" role="status" style="font-size:13px;white-space:pre-wrap"></p>
    </div><div id="issue-actions" style="flex-shrink:0;padding-top:10px">
    <button type="submit" class="act pri" id="issue-send">Send report</button>
    <button type="button" class="act" id="issue-cancel">Cancel</button>
    </div>
  </form>`;
  document.body.append(dialog); dialog.showModal();
  window.floating?.(dialog, dialog.querySelector("h2"), "issue-report");
  const find = s => dialog.querySelector(s), attachments = [];
  let pending = Promise.resolve(), busy = false, attachmentError = null;
  const status = text => { find("#issue-status").textContent = text; };
  const context = Promise.resolve().then(diagnostics).then(value => ({ value }), error => ({ error }));
  const draw = () => {
    const host = find("#issue-attachments"); host.replaceChildren();
    attachments.forEach((attachment, index) => {
      const card = document.createElement("div"); card.style.cssText = "max-width:180px;overflow-wrap:anywhere;border:1px solid var(--line,#444);border-radius:5px;padding:6px";
      if (attachment.type.startsWith("image/")) {
        const image = document.createElement("img"); image.src = `data:${attachment.type};base64,${attachment.b64}`;
        image.alt = attachment.name; image.style.cssText = "max-width:160px;max-height:100px;display:block"; card.append(image);
      }
      const label = document.createElement("span"); label.textContent = attachment.name; card.append(label);
      const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×"; remove.title = `Remove ${attachment.name}`;
      remove.disabled = busy; remove.onclick = () => { attachments.splice(index, 1); draw(); }; card.append(remove); host.append(card);
    });
  };
  const enqueue = task => {
    if (busy) return;
    status("Adding attachments…");
    pending = pending.then(task).then(items => {
      // The server stores at most 20 attachments, including its console and emulator log.
      if (attachments.length + items.length > 18) throw new Error("Attach up to 18 files per report.");
      attachments.push(...items); attachmentError = null; draw(); status("");
    }).catch(error => { attachmentError = error; status("Could not attach files: " + error.message); });
  };
  const files = transfer => {
    const list = Array.from(transfer?.files || []);
    return list.length ? list : Array.from(transfer?.items || []).filter(item => item.kind === "file").map(item => item.getAsFile()).filter(Boolean);
  };
  const read = async list => Promise.all(list.map(async file => ({ name: file.name || "pasted-image.png", type: file.type || "application/octet-stream",
    b64: await new Promise((resolve, reject) => {
      const reader = new FileReader(); reader.onload = () => resolve(reader.result.slice(reader.result.indexOf(",") + 1));
      reader.onerror = () => reject(new Error(`Cannot read ${file.name}`)); reader.readAsDataURL(file);
    }) })));
  dialog.addEventListener("paste", event => {
    if (busy) return;
    const list = files(event.clipboardData);
    if (list.length) { event.preventDefault(); event.stopPropagation(); enqueue(() => read(list)); }
    else if (!event.clipboardData?.getData("text/plain")) {
      event.preventDefault(); event.stopPropagation(); enqueue(() => clipboardFiles());
    }
  });
  dialog.addEventListener("dragover", event => { event.preventDefault(); });
  dialog.addEventListener("drop", event => { event.preventDefault(); event.stopPropagation(); const list = files(event.dataTransfer); if (list.length) enqueue(() => read(list)); });
  find("#issue-add").onclick = () => find("#issue-files").click();
  find("#issue-files").onchange = event => { const list = Array.from(event.target.files); enqueue(() => read(list)); event.target.value = ""; };
  find("#issue-paste").onclick = () => enqueue(async () => {
    const items = await clipboardFiles(); if (!items.length) throw new Error("Copy files in File Explorer, then paste here."); return items;
  });
  const close = () => { if (!busy) { dialog.__floatingDestroy?.(); dialog.close(); dialog.remove(); } };
  find("#issue-cancel").onclick = close;
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  find("form").onsubmit = async event => {
    event.preventDefault(); if (busy) return;
    const title = find("#issue-subject").value.trim(), note = find("#issue-body").value.trim();
    if (!title || !note) return status("Enter a subject and describe the issue.");
    busy = true;
    for (const control of dialog.querySelectorAll("button,input,textarea")) control.disabled = true;
    try {
      await pending; status("Sending report…");
      if (attachmentError) throw attachmentError;
      const gathered = await context; if (gathered.error) throw gathered.error;
      const result = await submit({ ...gathered.value, title, note, attachments: [...attachments, ...(gathered.value.attachments || [])] });
      if (!result.ok) throw new Error(result.error || `Request failed (${result.status || "unknown error"})`);
      dialog.__floatingDestroy?.(); dialog.close(); dialog.remove(); onSent(result.data);
    } catch (error) {
      busy = false; for (const control of dialog.querySelectorAll("button,input,textarea")) control.disabled = false;
      draw(); status("Report not sent: " + error.message);
    }
  };
  find("#issue-subject").focus();
};
