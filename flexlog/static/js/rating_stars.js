"use strict";

document.addEventListener("DOMContentLoaded", () => {
  for (const row of document.querySelectorAll(".rating-input")) {
    bindStarRow(row);
  }
  bindOverallPreview();
});

function bindStarRow(row) {
  const stars = Array.from(row.querySelectorAll(".star"));
  const hidden = row.querySelector('input[type="hidden"]');
  const readout = row.querySelector("[data-value-readout]");

  const render = (value) => {
    for (const s of stars) {
      const n = parseInt(s.dataset.value, 10);
      const lit = n <= value;
      s.classList.toggle("lit", lit);
      s.setAttribute("aria-pressed", lit ? "true" : "false");
    }
    hidden.value = value;
    if (readout) readout.textContent = value + " / 5";
    updateOverallPreview();
  };

  const current = () => parseInt(hidden.value, 10) || 0;

  render(current());

  stars.forEach((star) => {
    const n = parseInt(star.dataset.value, 10);
    star.addEventListener("click", () => {
      // Click on already-lit star at the same value → decrement to N-1.
      // Allows clicking the lit star 1 to clear to 0.
      const cur = current();
      render(cur === n ? n - 1 : n);
    });
    star.addEventListener("mouseenter", () => previewFill(stars, n));
    star.addEventListener("mouseleave", () => previewFill(stars, current()));
    star.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        render(Math.max(0, current() - 1));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        render(Math.min(5, current() + 1));
      } else if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        const cur = current();
        render(cur === n ? n - 1 : n);
      }
    });
  });
}

function previewFill(stars, n) {
  for (const s of stars) {
    const sn = parseInt(s.dataset.value, 10);
    s.classList.toggle("hover", sn <= n);
  }
}

function bindOverallPreview() {
  // Recompute the preview now and on every star commit.
  updateOverallPreview();
}

function updateOverallPreview() {
  const out = document.querySelector("[data-overall-preview]");
  if (!out) return;
  let total = 0;
  for (const row of document.querySelectorAll(".rating-input")) {
    const weight = parseFloat(row.dataset.weight) || 0;
    const hidden = row.querySelector('input[type="hidden"]');
    const value = parseInt(hidden.value, 10) || 0;
    total += value * weight;
  }
  out.textContent = total.toFixed(1);
}
