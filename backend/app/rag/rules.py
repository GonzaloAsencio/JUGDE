"""Rule-code extraction for Riftbound rulebook chunks.

Riftbound rules are numbered with a 3-digit code, optionally followed by
dotted sub-levels and a terminal letter: ``103``, ``103.2``, ``103.2.b``,
``146.1``. This module pulls those codes out of free text so a chunk can
declare which rules it actually covers — independent of its (coarser-grained)
section header and without truncating to a preview window.
"""
import re

# 3-digit base code, optional ``.N`` sub-levels, optional terminal ``.letter``.
# The leading \b + exactly-3-digit base avoids matching 4-digit years/dims
# (2026, 1024) and 1-2 digit incidental numbers.
_RULE_CODE = re.compile(r"\b\d{3}(?:\.\d+)*(?:\.[a-z])?\b")


def extract_rule_codes(text: str) -> set[str]:
    """Return the set of distinct rule codes appearing in *text*."""
    if not text:
        return set()
    return set(_RULE_CODE.findall(text))
