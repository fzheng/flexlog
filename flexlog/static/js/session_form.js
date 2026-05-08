// Session form — link row management.
// Adds rows by cloning the first existing row; removes rows by clicking the
// per-row remove button. For pre-existing links (with data-link-id), the
// remove button POSTs to /session_links/<id>/delete instead of just hiding
// the row, so the deletion is persisted immediately.

(function () {
  "use strict";
  const rowsContainer = document.querySelector("[data-link-rows]");
  const addBtn = document.getElementById("add-link-row");
  if (!rowsContainer || !addBtn) return;

  function emptyRowFromTemplate() {
    const first = rowsContainer.querySelector(".link-row");
    if (!first) return null;
    const clone = first.cloneNode(true);
    clone.querySelectorAll("input").forEach((i) => (i.value = ""));
    // New rows are NOT existing-link removes — remove the data-link-id, swap
    // the button data attr.
    clone.querySelectorAll("[data-remove-existing-link]").forEach((b) => {
      b.removeAttribute("data-remove-existing-link");
      b.removeAttribute("data-link-id");
      b.setAttribute("data-remove-link", "");
    });
    return clone;
  }

  function ensureAtLeastOneRow() {
    if (rowsContainer.querySelectorAll(".link-row").length === 0) {
      const fresh = emptyRowFromTemplate();
      if (fresh) rowsContainer.appendChild(fresh);
    }
  }

  addBtn.addEventListener("click", () => {
    const fresh = emptyRowFromTemplate();
    if (fresh) rowsContainer.appendChild(fresh);
  });

  rowsContainer.addEventListener("click", (event) => {
    const removeBtn = event.target.closest("[data-remove-link]");
    if (removeBtn) {
      removeBtn.closest(".link-row").remove();
      ensureAtLeastOneRow();
      return;
    }
    const removeExisting = event.target.closest("[data-remove-existing-link]");
    if (removeExisting) {
      const linkId = removeExisting.getAttribute("data-link-id");
      if (!linkId) return;
      // POST to /session_links/<id>/delete using a hidden synthetic form so
      // the request carries the page's CSRF token.
      const form = document.createElement("form");
      form.method = "post";
      form.action = "/session_links/" + encodeURIComponent(linkId) + "/delete";
      const csrfInput = document.querySelector("input[name='csrf_token']");
      if (csrfInput) {
        const tok = document.createElement("input");
        tok.type = "hidden";
        tok.name = "csrf_token";
        tok.value = csrfInput.value;
        form.appendChild(tok);
      }
      document.body.appendChild(form);
      form.submit();
    }
  });
})();
