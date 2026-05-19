"use strict";

// Read CSRF token once.
const CSRF =
  document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

let formSubmitting = false;

document.addEventListener("DOMContentLoaded", () => {
  bindMediaFieldsets();
  bindLinkSection();
  bindBeforeUnload();
  bindFormSubmit();
});

function bindMediaFieldsets() {
  for (const fs of document.querySelectorAll("fieldset[data-kind]")) {
    const kind = fs.dataset.kind;
    const fileInput = fs.querySelector("[data-upload-input]");
    const addBtn = fs.querySelector("[data-upload-add]");
    const list = fs.querySelector("[data-pending-list]");

    addBtn.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
      for (const file of fileInput.files) {
        uploadOne(kind, file, list);
      }
      fileInput.value = "";
    });

    list.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-remove]");
      if (btn) removeRow(btn.closest(".upload-row"), kind);
    });
  }
}

function uploadOne(kind, file, listEl) {
  const row = document.createElement("li");
  row.className = "upload-row";
  row.dataset.status = "uploading";
  row.innerHTML = `
    <span class="upload-name"></span>
    <span class="upload-status">
      <progress max="100" value="0" data-progress></progress>
    </span>
    <button type="button" class="btn upload-remove" data-remove>✕</button>
  `;
  row.querySelector(".upload-name").textContent = file.name;
  listEl.appendChild(row);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/sessions/upload");
  xhr.setRequestHeader("X-CSRFToken", CSRF);
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = (e.loaded / e.total) * 100;
    row.querySelector("[data-progress]").value = pct;
  };
  xhr.onload = () => {
    if (xhr.status !== 200) {
      markFailed(row, parseError(xhr));
      return;
    }
    const j = JSON.parse(xhr.responseText);
    markUploaded(row, kind, j);
  };
  xhr.onerror = () => markFailed(row, "network error");
  xhr.onabort = () => markFailed(row, "aborted");

  const fd = new FormData();
  fd.append("kind", kind);
  fd.append("file", file);
  xhr.send(fd);
}

function markUploaded(row, kind, payload) {
  row.dataset.status = "uploaded";
  row.dataset.fileKey = payload.file_key;
  row.querySelector(".upload-status").textContent = "✓";
  const hidden = document.createElement("input");
  hidden.type = "hidden";
  hidden.name = `${kind}_keys`;
  hidden.value = payload.file_key;
  row.appendChild(hidden);
}

function markFailed(row, msg) {
  row.dataset.status = "failed";
  row.querySelector(".upload-status").textContent = "✗ " + msg;
}

function parseError(xhr) {
  try {
    return JSON.parse(xhr.responseText).error || `HTTP ${xhr.status}`;
  } catch {
    return `HTTP ${xhr.status}`;
  }
}

function removeRow(row, kind) {
  const fileKey = row.dataset.fileKey;
  const existing = row.dataset.existing === "true";

  if (existing && fileKey) {
    // Don't delete server-side. Transfer the key to unlinked_keys[] so the
    // Save handler unlinks it from the session at form submit.
    const container = document.querySelector("[data-unlinked-keys-container]");
    const hid = document.createElement("input");
    hid.type = "hidden";
    hid.name = "unlinked_keys";
    hid.value = fileKey;
    container.appendChild(hid);
    row.remove();
    return;
  }

  if (fileKey) {
    // Best-effort server-side delete; UI removes regardless of result.
    fetch(`/sessions/upload/${encodeURIComponent(fileKey)}`, {
      method: "DELETE",
      headers: { "X-CSRFToken": CSRF },
    }).catch(() => {});
  }
  row.remove();
}

function bindLinkSection() {
  const list = document.querySelector("[data-link-list]");
  const input = document.querySelector("[data-link-input]");
  const addBtn = document.querySelector("[data-link-add]");
  const errEl = document.querySelector("[data-link-error]");
  if (!list || !input || !addBtn) return;

  const addLink = () => {
    const raw = input.value.trim();
    errEl.hidden = true;
    if (!raw) return;
    let parsed;
    try {
      parsed = new URL(raw);
    } catch {
      errEl.textContent = "Invalid URL — include http:// or https://";
      errEl.hidden = false;
      return;
    }
    // Allowlist only http(s). Reject javascript:, data:, file:, etc. —
    // the server also drops these (services.sessions.is_safe_link_url),
    // but rejecting here gives an immediate error instead of the URL
    // silently disappearing on save.
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      errEl.textContent = "Only http:// and https:// URLs are allowed";
      errEl.hidden = false;
      return;
    }
    if (!parsed.host) {
      errEl.textContent = "Invalid URL — missing host";
      errEl.hidden = false;
      return;
    }
    list.appendChild(buildLinkRow(raw, "", ""));
    input.value = "";
  };

  addBtn.addEventListener("click", addLink);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addLink();
    }
  });

  list.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-link-remove]")) {
      ev.target.closest("[data-link-row]").remove();
      return;
    }
    if (ev.target.closest("[data-thumb-clear]")) {
      const row = ev.target.closest("[data-link-row]");
      clearRowThumb(row);
      return;
    }
    // Click anywhere else on the row → focus it so paste lands here.
    const row = ev.target.closest("[data-link-row]");
    if (row) row.focus();
  });

  // Paste anywhere within the list — but only handle when the focused
  // row contains the paste target (otherwise let normal text paste run).
  list.addEventListener("paste", (ev) => {
    const row = ev.target.closest("[data-link-row]");
    if (!row) return;
    const file = imageFileFromDataTransfer(ev.clipboardData);
    if (!file) return;
    ev.preventDefault();
    uploadThumbForRow(row, file);
  });

  // Drag-and-drop image onto a row → same handler.
  list.addEventListener("dragover", (ev) => {
    const row = ev.target.closest("[data-link-row]");
    if (!row) return;
    if (!ev.dataTransfer.types.includes("Files")) return;
    ev.preventDefault();
    row.classList.add("link-row-drop-target");
  });
  list.addEventListener("dragleave", (ev) => {
    const row = ev.target.closest("[data-link-row]");
    if (row) row.classList.remove("link-row-drop-target");
  });
  list.addEventListener("drop", (ev) => {
    const row = ev.target.closest("[data-link-row]");
    if (!row) return;
    const file = imageFileFromDataTransfer(ev.dataTransfer);
    row.classList.remove("link-row-drop-target");
    if (!file) return;
    ev.preventDefault();
    uploadThumbForRow(row, file);
  });

  // Pre-existing rows from the server: nothing to do — they already
  // have their hidden inputs wired by the template.
}

function imageFileFromDataTransfer(dt) {
  if (!dt) return null;
  if (dt.files && dt.files.length) {
    for (const f of dt.files) {
      if (f.type && f.type.startsWith("image/")) return f;
    }
  }
  if (dt.items && dt.items.length) {
    for (const item of dt.items) {
      if (item.kind === "file" && item.type && item.type.startsWith("image/")) {
        return item.getAsFile();
      }
    }
  }
  return null;
}

function buildLinkRow(url, thumbKey, thumbUrl) {
  const li = document.createElement("li");
  li.className = "link-form-row";
  li.dataset.linkRow = "";
  li.tabIndex = 0;

  const slot = document.createElement("div");
  slot.className = "link-thumb-slot";
  slot.dataset.thumbSlot = "";
  renderThumbSlot(slot, thumbUrl);

  const meta = document.createElement("div");
  meta.className = "link-row-meta";
  const a = document.createElement("a");
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = url;
  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "btn link-remove";
  removeBtn.dataset.linkRemove = "";
  removeBtn.title = "Remove link";
  removeBtn.textContent = "✕";
  meta.append(a, removeBtn);

  const urlHid = document.createElement("input");
  urlHid.type = "hidden";
  urlHid.name = "link_urls";
  urlHid.value = url;

  const thumbHid = document.createElement("input");
  thumbHid.type = "hidden";
  thumbHid.name = "link_thumb_keys";
  thumbHid.value = thumbKey || "";
  thumbHid.dataset.thumbKey = "";

  li.append(slot, meta, urlHid, thumbHid);
  return li;
}

function renderThumbSlot(slot, thumbUrl) {
  slot.innerHTML = "";
  if (thumbUrl) {
    const img = document.createElement("img");
    img.className = "link-thumb-image";
    img.dataset.thumbImage = "";
    img.alt = "";
    img.src = thumbUrl;
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "btn link-thumb-clear";
    clear.dataset.thumbClear = "";
    clear.title = "Remove thumbnail";
    clear.textContent = "✕";
    slot.append(img, clear);
  } else {
    const ph = document.createElement("span");
    ph.className = "link-thumb-placeholder";
    ph.dataset.thumbPlaceholder = "";
    ph.textContent = "Paste screenshot";
    slot.appendChild(ph);
  }
}

function uploadThumbForRow(row, file) {
  const slot = row.querySelector("[data-thumb-slot]");
  const hid = row.querySelector("[data-thumb-key]");
  slot.classList.add("link-thumb-uploading");

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/sessions/upload");
  xhr.setRequestHeader("X-CSRFToken", CSRF);
  xhr.onload = () => {
    slot.classList.remove("link-thumb-uploading");
    if (xhr.status !== 200) {
      flashRowError(row, parseError(xhr));
      return;
    }
    let payload;
    try { payload = JSON.parse(xhr.responseText); }
    catch { flashRowError(row, "bad response"); return; }
    hid.value = payload.file_key;
    renderThumbSlot(slot, `/media/${encodeURIComponent(payload.file_key)}`);
  };
  xhr.onerror = () => {
    slot.classList.remove("link-thumb-uploading");
    flashRowError(row, "network error");
  };

  const fd = new FormData();
  fd.append("kind", "photo");
  // Give it a name so the server's filename-based extension logic has
  // something to work with — pasted images otherwise come through as
  // `image.png` with no name.
  fd.append("file", file, file.name || "pasted-screenshot.png");
  xhr.send(fd);
}

function clearRowThumb(row) {
  const slot = row.querySelector("[data-thumb-slot]");
  const hid = row.querySelector("[data-thumb-key]");
  hid.value = "";
  renderThumbSlot(slot, "");
}

function flashRowError(row, msg) {
  const slot = row.querySelector("[data-thumb-slot]");
  slot.innerHTML = "";
  const err = document.createElement("span");
  err.className = "link-thumb-error";
  err.textContent = "✗ " + msg;
  slot.appendChild(err);
  // After 3s, fall back to the placeholder so the user can retry.
  setTimeout(() => renderThumbSlot(slot, ""), 3000);
}

function hasUnsavedUploads() {
  for (const row of document.querySelectorAll(
    ".upload-row:not([data-existing='true'])"
  )) {
    if (row.dataset.status === "uploaded" || row.dataset.status === "uploading") {
      return true;
    }
  }
  return false;
}

function hasUploadingRows() {
  return !!document.querySelector(".upload-row[data-status='uploading']");
}

function bindBeforeUnload() {
  window.addEventListener("beforeunload", (e) => {
    if (formSubmitting) return;
    if (hasUnsavedUploads()) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

function bindFormSubmit() {
  const form = document.querySelector("form.session-form");
  if (!form) return;
  form.addEventListener("submit", (e) => {
    if (hasUploadingRows()) {
      e.preventDefault();
      alert("Wait for uploads to finish before saving.");
      return;
    }
    formSubmitting = true;
  });
}
