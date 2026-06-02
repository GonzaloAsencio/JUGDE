import { useState, useRef, useEffect } from 'react';
import { GAME_KEYWORDS, type KeywordDef } from '@/lib/gameKeywords';
import { searchCards, toSlug, type CardIndexEntry } from '@/lib/cardLookup';

// #term -> game keyword, @entity -> card. The sigil picks the source.
export type MentionItem =
  | { kind: 'keyword'; keyword: KeywordDef }
  | { kind: 'card'; card: CardIndexEntry };

const MENTION_RE = /([#@])([\w-]*)$/;

interface UseMentionsParams {
  value: string;
  onChange: (v: string) => void;
}

/**
 * Drives the @card / #keyword mention picker for a text field: detection while
 * typing, keyboard navigation, and token insertion. The owning component stays
 * presentational — it wires the returned refs/handlers and renders the list.
 */
export function useMentions({ value, onChange }: UseMentionsParams) {
  const [active, setActive] = useState(false);
  const [items, setItems] = useState<MentionItem[]>([]);
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const activeItemRef = useRef<HTMLLIElement>(null);

  // Close the picker when the user clicks outside the field/list.
  useEffect(() => {
    if (!active) return;
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setActive(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [active]);

  // Keep the highlighted option in view as the user arrows through.
  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: 'nearest' });
  }, [index]);

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value;
    onChange(val);

    const cursor = e.target.selectionStart ?? val.length;
    const match = val.slice(0, cursor).match(MENTION_RE);

    if (match) {
      const sigil = match[1];
      const search = match[2];
      const next: MentionItem[] =
        sigil === '#'
          ? GAME_KEYWORDS
              .filter(k => k.name.toLowerCase().startsWith(search.toLowerCase()))
              .map(keyword => ({ kind: 'keyword' as const, keyword }))
          : searchCards(search).map(card => ({ kind: 'card' as const, card }));

      if (next.length > 0) {
        setItems(next);
        setActive(true);
        setIndex(0);
        return;
      }
    }
    setActive(false);
  }

  function select(item: MentionItem) {
    const el = inputRef.current;
    const cursor = el?.selectionStart ?? value.length;
    const token =
      item.kind === 'keyword'
        ? `#${item.keyword.name} `
        : `@${toSlug(item.card.clean_name)} `;
    const before = value.slice(0, cursor).replace(MENTION_RE, token);
    const after = value.slice(cursor);
    onChange(before + after);
    setActive(false);
    setTimeout(() => {
      el?.focus();
      el?.setSelectionRange(before.length, before.length);
    }, 0);
  }

  /** Handles arrow/enter/escape while the picker is open. Returns `true` when
   * the keystroke was consumed, so the caller can fall through to submit. */
  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>): boolean {
    if (!active) return false;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setIndex(i => Math.min(i + 1, items.length - 1));
      return true;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setIndex(i => Math.max(i - 1, 0));
      return true;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      select(items[index]);
      return true;
    }
    if (e.key === 'Escape') {
      setActive(false);
      return true;
    }
    return false;
  }

  return {
    active,
    items,
    index,
    inputRef,
    containerRef,
    activeItemRef,
    handleInputChange,
    handleKeyDown,
    select,
  };
}
