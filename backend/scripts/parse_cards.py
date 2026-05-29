"""
Parsea cartas de Riftbound desde la Riftcodex API (https://api.riftcodex.com/cards).

Modos:
  - URL: pagina el API, cachea el payload crudo en data/raw/cards.json,
         y emite data/processed/cards.md
  - Path local: lee el JSON cacheado y emite el markdown

Cada carta se renderiza como un bloque H2 (## clean_name) con metadata
estructurada en el body. clean_name es el slug que usa el sistema de @tags
del judge, así `@yasuo` matchea section="yasuo" en tagged_lookup.
"""
import json
import sys
import time
from pathlib import Path

import requests

_API_BASE = "https://api.riftcodex.com/cards"
_HEADERS = {"User-Agent": "RiftboundJudgeBot/1.0 (+https://github.com/GonzaloAsencio/Judge)"}
_PAGE_SIZE = 100
_REQUEST_PAUSE_S = 0.5
_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------

def _extract_items(payload) -> list[dict]:
    """The Riftcodex API may wrap results in {items|data|results: [...]}.

    Accept any of those keys, or a bare list. Returns [] if the shape is
    unrecognised (caller decides whether to keep paginating).
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "cards"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _fetch_pages(url: str = _API_BASE) -> list[dict]:
    cards: list[dict] = []
    page = 1
    while True:
        params = {"page": page, "size": _PAGE_SIZE}
        for attempt in range(_MAX_RETRIES):
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** attempt
                print(f"  Rate limited on page {page}, sleeping {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            raise RuntimeError(f"Riftcodex API kept returning 429 on page {page}")

        items = _extract_items(resp.json())
        if not items:
            break
        cards.extend(items)
        print(f"  Page {page}: {len(items)} cards (total so far: {len(cards)})")
        if len(items) < _PAGE_SIZE:
            break
        page += 1
        time.sleep(_REQUEST_PAUSE_S)
    return cards


# ---------------------------------------------------------------------------
# Filter — alternate art + dedupe
# ---------------------------------------------------------------------------

def _filter_cards(cards: list[dict]) -> list[dict]:
    """Drop alternate-art versions and dedupe by riftbound_id (first wins)."""
    seen: set[str] = set()
    result: list[dict] = []
    for card in cards:
        metadata = card.get("metadata") or {}
        if metadata.get("alternate_art"):
            continue
        rb_id = card.get("riftbound_id")
        if not rb_id or rb_id in seen:
            continue
        seen.add(rb_id)
        result.append(card)
    return result


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _render_card(card: dict) -> str:
    """Render a single card to markdown. Returns "" if essential fields missing."""
    metadata = card.get("metadata") or {}
    clean_name = metadata.get("clean_name")
    name = card.get("name")
    classification = card.get("classification") or {}
    card_type = classification.get("type")
    if not clean_name or not name or not card_type:
        return ""

    lines: list[str] = [f"## {clean_name}", f"**Name**: {name}"]

    set_info = card.get("set") or {}
    set_label = set_info.get("label")
    riftbound_id = card.get("riftbound_id")
    set_parts: list[str] = []
    if set_label and riftbound_id:
        set_parts.append(f"**Set**: {set_label} ({riftbound_id})")
    elif set_label:
        set_parts.append(f"**Set**: {set_label}")

    rarity = classification.get("rarity")
    if rarity:
        set_parts.append(f"**Rarity**: {rarity}")

    domain = classification.get("domain") or []
    if domain:
        set_parts.append(f"**Domain**: {', '.join(domain)}")

    if set_parts:
        lines.append(" | ".join(set_parts))

    attributes = card.get("attributes") or {}
    stat_parts: list[str] = []
    for key, label in (("energy", "Energy"), ("might", "Might"), ("power", "Power")):
        value = attributes.get(key)
        if value is not None:
            stat_parts.append(f"**{label}**: {value}")
    stat_parts.append(f"**Type**: {card_type}")
    supertype = classification.get("supertype")
    if supertype:
        stat_parts.append(f"**Supertype**: {supertype}")
    lines.append(" | ".join(stat_parts))

    tags = card.get("tags") or []
    if tags:
        lines.append(f"**Tags**: {', '.join(tags)}")

    text = card.get("text") or {}
    plain = text.get("plain")
    if plain:
        lines.append("")
        lines.append("**Text**:")
        lines.append(plain)

    flavour = text.get("flavour")
    if flavour:
        lines.append("")
        lines.append(f'*Flavor*: "{flavour}"')

    return "\n".join(lines)


def _render_markdown(cards: list[dict]) -> str:
    """Filter + render every card. Output is one H2 block per card, separated by blank lines."""
    blocks = []
    for card in _filter_cards(cards):
        block = _render_card(card)
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Entry point — local JSON OR live API
# ---------------------------------------------------------------------------

def parse_cards(source: str | Path = _API_BASE) -> str:
    """Build cards.md content.

    - If source is an existing file path → read JSON from it.
    - Otherwise → treat as URL, paginate, return rendered markdown.
    """
    path = Path(str(source))
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        cards = _extract_items(payload) if not isinstance(payload, list) else payload
    else:
        cards = _fetch_pages(str(source))
    return _render_markdown(cards)


if __name__ == "__main__":
    raw_out = Path("data/raw/cards.json")
    md_out = Path("data/processed/cards.md")
    raw_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)

    source = sys.argv[1] if len(sys.argv) > 1 else _API_BASE
    print(f"Fetching cards from: {source}")
    if Path(source).exists():
        cards_payload = json.loads(Path(source).read_text(encoding="utf-8"))
        cards = _extract_items(cards_payload) if not isinstance(cards_payload, list) else cards_payload
    else:
        cards = _fetch_pages(source)
        raw_out.write_text(json.dumps(cards, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Cached raw payload: {raw_out} ({len(cards)} cards)")

    md = _render_markdown(cards)
    md_out.write_text(md, encoding="utf-8")
    chunk_count = md.count("## ")
    print(f"Generated: {md_out} ({len(md):,} chars, {chunk_count} cards)")
