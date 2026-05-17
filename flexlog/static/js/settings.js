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

// --- M7 additions: weight sum indicator + Distribute Evenly button ---

document.addEventListener("DOMContentLoaded", () => {
  bindWeightHandling();
});

function bindWeightHandling() {
  const tbody = document.querySelector("[data-ratings-tbody]");
  if (!tbody) return;

  const recompute = () => {
    let sum = 0;
    for (const row of tbody.querySelectorAll(".rating-row")) {
      const enabled = row.querySelector('[data-rating-enabled]');
      if (!enabled || !enabled.checked) {
        updatePct(row);
        continue;
      }
      const input = row.querySelector('[data-weight-input]');
      const w = parseFloat(input.value) || 0;
      sum += w;
      updatePct(row);
    }
    const indicator = document.querySelector("[data-weight-sum-indicator]");
    const sumEl = document.querySelector("[data-weight-sum]");
    if (sumEl) sumEl.textContent = sum.toFixed(2);
    if (indicator) {
      indicator.classList.toggle("valid", Math.abs(sum - 1.0) < 1e-6);
      indicator.classList.toggle("invalid", Math.abs(sum - 1.0) >= 1e-6);
    }
  };

  const updatePct = (row) => {
    const input = row.querySelector('[data-weight-input]');
    const pctEl = row.querySelector('[data-weight-pct]');
    if (!input || !pctEl) return;
    const w = parseFloat(input.value) || 0;
    pctEl.textContent = "(" + Math.round(w * 100) + "%)";
  };

  // Initial render
  recompute();

  // Recompute on any change inside the tbody (input or enabled checkbox).
  tbody.addEventListener("input", recompute);
  tbody.addEventListener("change", recompute);
  tbody.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-rating-delete]")) {
      // Allow the existing handler to remove the row first; recompute after.
      setTimeout(recompute, 0);
    }
  });

  const distributeBtn = document.querySelector("[data-distribute-evenly]");
  if (distributeBtn) {
    distributeBtn.addEventListener("click", () => {
      const enabledRows = Array.from(tbody.querySelectorAll(".rating-row"))
        .filter((row) => {
          const cb = row.querySelector('[data-rating-enabled]');
          return cb && cb.checked;
        });
      const n = enabledRows.length;
      if (n === 0) return;
      const per = Math.round((1.0 / n) * 100) / 100;
      for (let i = 0; i < n - 1; i++) {
        enabledRows[i].querySelector('[data-weight-input]').value = per.toFixed(2);
      }
      // Last enabled row absorbs the rounding remainder so sum is exactly 1.0.
      const last = +(1.0 - per * (n - 1)).toFixed(2);
      enabledRows[n - 1].querySelector('[data-weight-input]').value = last.toFixed(2);
      recompute();
    });
  }

  // When a new row is added via the existing Add button, the listener via
  // `tbody.addEventListener("input")` will pick it up automatically.
}
