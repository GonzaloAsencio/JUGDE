"""Rule-code extraction for Riftbound rulebook chunks.

Riftbound rules are numbered with a 3-digit code followed by dotted levels
that alternate freely between numbers and letters: ``103``, ``103.2``,
``103.2.b``, ``383.3.d.1``. This module pulls those codes out of free text so
a chunk can declare which rules it actually covers — independent of its
(coarser-grained) section header and without truncating to a preview window.
"""
import re

# 3-digit base code, then any run of ``.N`` / ``.letter`` levels — numbering
# nests past the letter (383.3.d.1), so the letter must not be terminal.
# The leading \b + exactly-3-digit base avoids matching 4-digit years/dims
# (2026, 1024) and 1-2 digit incidental numbers.
_RULE_CODE = re.compile(r"\b\d{3}(?:\.(?:\d+|[a-z]))*\b")


def extract_rule_codes(text: str) -> set[str]:
    """Return the set of distinct rule codes appearing in *text*."""
    if not text:
        return set()
    return set(_RULE_CODE.findall(text))
