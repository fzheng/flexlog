// Live tag-chip preview while the user types in the tags field.
// Mirrors the server-side normalization: comma-separated, dedup case-insensitive.

(function () {
  "use strict";
  const tagsInput = document.getElementById("tags");
  if (!tagsInput) return;

  const preview = document.createElement("div");
  preview.id = "tag-chip-preview";
  preview.setAttribute("aria-hidden", "true");
  tagsInput.parentNode.appendChild(preview);

  function render() {
    const seen = new Set();
    const chips = [];
    for (const raw of tagsInput.value.split(",")) {
      const display = raw.trim();
      if (!display) continue;
      const key = display.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      const span = document.createElement("span");
      span.className = "tag-chip";
      span.textContent = display;
      chips.push(span);
    }
    preview.innerHTML = "";
    for (const c of chips) preview.appendChild(c);
  }

  tagsInput.addEventListener("input", render);
  render();
})();
