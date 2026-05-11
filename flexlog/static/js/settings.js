"use strict";

document.addEventListener("DOMContentLoaded", () => {
  bindRatingsTable();
});

function bindRatingsTable() {
  const tbody = document.querySelector("[data-ratings-tbody]");
  if (!tbody) return;
  const addBtn = document.querySelector("[data-rating-add]");
  const tmpl = document.getElementById("rating-row-template");

  const syncCheckboxValues = (row) => {
    const idInput = row.querySelector('input[name="rating_id"]');
    const enabled = row.querySelector('input[name="rating_enabled"]');
    const sortable = row.querySelector('input[name="rating_sortable"]');
    const sync = () => {
      enabled.value = idInput.value;
      sortable.value = idInput.value;
    };
    idInput.addEventListener("input", sync);
    sync();
  };
  tbody.querySelectorAll(".rating-row").forEach(syncCheckboxValues);

  addBtn?.addEventListener("click", () => {
    const clone = tmpl.content.cloneNode(true);
    const row = clone.querySelector(".rating-row");
    tbody.appendChild(clone);
    syncCheckboxValues(row);
    row.querySelector('input[name="rating_id"]').focus();
  });

  tbody.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-rating-delete]");
    if (btn) btn.closest(".rating-row").remove();
  });

  let dragged = null;
  tbody.addEventListener("dragstart", (e) => {
    const row = e.target.closest(".rating-row");
    if (!row) return;
    dragged = row;
    row.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  });
  tbody.addEventListener("dragend", () => {
    if (dragged) dragged.classList.remove("dragging");
    dragged = null;
  });
  tbody.addEventListener("dragover", (e) => {
    e.preventDefault();
    const target = e.target.closest(".rating-row");
    if (!target || target === dragged) return;
    const rect = target.getBoundingClientRect();
    const before = e.clientY < rect.top + rect.height / 2;
    tbody.insertBefore(dragged, before ? target : target.nextSibling);
  });
}
