"""CSP script-src 'self' silently blocks inline onclick/onchange/onsubmit
handlers. Keeping templates clear of them prevents the silent break
mode where a destructive action's confirm dialog gets dropped and the
form submits unguarded."""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "flexlog" / "templates"

# Any `onfoo="..."` attribute on an HTML element. Excludes attributes
# starting with "data-" or attributes named on*event from inside Jinja
# comments. Conservative: matches the literal attribute pattern in
# files; humans can grep for false positives.
_INLINE_HANDLER_RE = re.compile(
    r'\bon[a-z]+\s*=\s*["\']',
    re.IGNORECASE,
)


def test_no_inline_event_handlers_in_templates():
    offenders = []
    for path in TEMPLATES_DIR.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            # Skip Jinja comment lines
            if line.strip().startswith("{#") or "{# " in line:
                continue
            if _INLINE_HANDLER_RE.search(line):
                offenders.append(f"{path.relative_to(TEMPLATES_DIR.parent.parent)}:{line_no}: {line.strip()}")
    assert not offenders, (
        "Inline event-handler attributes found in templates. "
        "CSP script-src 'self' silently blocks them — migrate to "
        "data-* attributes consumed by static/js/csp_handlers.js. "
        "Offenders:\n  " + "\n  ".join(offenders)
    )
