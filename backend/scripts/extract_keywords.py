"""
Extracts keyword rules (805-826) from rulebook.md and writes keywords.md.
Each keyword gets its own H2 section for better RAG chunk isolation.
"""
import re
from pathlib import Path

_KW_TOP = re.compile(r"^(8(?:0[5-9]|1\d|2[0-6]))\. (.+)$")
_ANY_RULE_TOP = re.compile(r"^\d{3,}\. ")  # any NNN. line — stops collection when outside keyword range
_FIRST_KW = 805
_LAST_KW = 826

RULEBOOK = Path(__file__).parent.parent / "data" / "processed" / "rulebook.md"
OUTPUT = Path(__file__).parent.parent / "data" / "processed" / "keywords.md"


def extract_keywords(rulebook_text: str) -> str:
    """Parse rulebook_text and return keywords.md with each keyword as an H2 section."""
    lines = rulebook_text.splitlines()
    sections: dict[int, dict] = {}
    current_rule: int | None = None

    for line in lines:
        kw_m = _KW_TOP.match(line)
        if kw_m:
            rule_num = int(kw_m.group(1))
            current_rule = rule_num
            sections[rule_num] = {"name": kw_m.group(2).strip(), "lines": [line]}
        elif _ANY_RULE_TOP.match(line):
            current_rule = None
        elif current_rule is not None:
            sections[current_rule]["lines"].append(line)

    parts = ["# Riftbound Keywords Reference", ""]
    for rule_num in sorted(sections.keys()):
        sec = sections[rule_num]
        parts.append(f"## {sec['name']}")
        parts.append("")
        for line in sec["lines"]:
            parts.append(line)
        parts.append("")

    return "\n".join(parts)


if __name__ == "__main__":
    text = RULEBOOK.read_text(encoding="utf-8")
    output = extract_keywords(text)
    OUTPUT.write_text(output, encoding="utf-8")
    print(f"Written {output.count('## ')} keyword sections to {OUTPUT}")
