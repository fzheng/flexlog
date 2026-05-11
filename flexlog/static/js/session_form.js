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
    try {
      const u = new URL(raw);
      if (!u.protocol || !u.host) throw new Error("missing host");
    } catch {
      errEl.textContent = "Invalid URL — include http:// or https://";
      errEl.hidden = false;
      return;
    }
    const li = document.createElement("li");
    li.className = "link-row";
    li.dataset.linkRow = "";
    const a = document.createElement("a");
    a.href = raw;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = raw;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn link-remove";
    btn.dataset.linkRemove = "";
    btn.textContent = "✕";
    const hid = document.createElement("input");
    hid.type = "hidden";
    hid.name = "link_urls";
    hid.value = raw;
    li.append(a, btn, hid);
    list.appendChild(li);
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
    const btn = ev.target.closest("[data-link-remove]");
    if (btn) btn.closest("[data-link-row]").remove();
  });
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
