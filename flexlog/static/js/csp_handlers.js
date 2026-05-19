"use strict";

// Replaces the inline event-handler attributes that CSP script-src 'self'
// would otherwise block. Templates use data-* attributes to opt in:
//
//   data-auto-submit         on a <select>: parent form submits on change
//   data-nav-on-change="URL" on an <input type=checkbox>: navigate to URL
//                            on toggle. Use the literal token "{value}" in
//                            the URL where the checkbox's checked-state
//                            ("1" or "0") should be substituted.
//   data-confirm="MESSAGE"   on a <form>: window.confirm() before submit;
//                            cancel the submit if the user clicks No.

document.addEventListener("DOMContentLoaded", () => {
  // Auto-submit selects (e.g., dashboard sort dropdown)
  for (const sel of document.querySelectorAll("select[data-auto-submit]")) {
    sel.addEventListener("change", () => {
      if (sel.form) sel.form.submit();
    });
  }

  // Checkbox toggles that navigate
  for (const cb of document.querySelectorAll("input[type=checkbox][data-nav-on-change]")) {
    cb.addEventListener("change", () => {
      const tpl = cb.getAttribute("data-nav-on-change");
      window.location = tpl.replace("{value}", cb.checked ? "1" : "0");
    });
  }

  // Forms that confirm before submitting (delete actions)
  for (const form of document.querySelectorAll("form[data-confirm]")) {
    form.addEventListener("submit", (ev) => {
      const msg = form.getAttribute("data-confirm");
      if (!window.confirm(msg)) {
        ev.preventDefault();
      }
    });
  }
});
