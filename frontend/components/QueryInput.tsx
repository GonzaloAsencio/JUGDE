import { useState, useRef, useEffect, useId } from 'react';
import { Loader2, ArrowUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { GAME_KEYWORDS, type KeywordDef } from '@/lib/gameKeywords';
import { KeywordBadge } from '@/components/KeywordBadge';
import { searchCards, toSlug, type CardIndexEntry } from '@/lib/cardLookup';

interface QueryInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  loading: boolean;
  placeholder?: string;
}

// #term -> game keyword, @entity -> card. The sigil picks the source.
type MentionItem =
  | { kind: 'keyword'; keyword: KeywordDef }
  | { kind: 'card'; card: CardIndexEntry };

const MENTION_RE = /([#@])([\w-]*)$/;

export function QueryInput({ value, onChange, onSubmit, loading, placeholder }: QueryInputProps) {
  const trimmed = value.trim();
  const isValid = trimmed.length >= 3 && trimmed.length <= 1000;
  const label = placeholder ?? 'Ask the judge a rules question';

  const [mentionActive, setMentionActive] = useState(false);
  const [mentionItems, setMentionItems] = useState<MentionItem[]>([]);
  const [mentionIndex, setMentionIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const activeItemRef = useRef<HTMLLIElement>(null);

  // Stable ids for the ARIA combobox wiring (input ↔ listbox ↔ active option).
  const inputId = useId();
  const listboxId = useId();
  const optionId = (i: number) => `${listboxId}-opt-${i}`;

  useEffect(() => {
    if (!mentionActive) return;
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setMentionActive(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [mentionActive]);

  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: 'nearest' });
  }, [mentionIndex]);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value;
    onChange(val);

    const cursor = e.target.selectionStart ?? val.length;
    const match = val.slice(0, cursor).match(MENTION_RE);

    if (match) {
      const sigil = match[1];
      const search = match[2];
      const items: MentionItem[] =
        sigil === '#'
          ? GAME_KEYWORDS
              .filter(k => k.name.toLowerCase().startsWith(search.toLowerCase()))
              .map(keyword => ({ kind: 'keyword' as const, keyword }))
          : searchCards(search).map(card => ({ kind: 'card' as const, card }));

      if (items.length > 0) {
        setMentionItems(items);
        setMentionActive(true);
        setMentionIndex(0);
        return;
      }
    }
    setMentionActive(false);
  }

  function selectMention(item: MentionItem) {
    const el = inputRef.current;
    const cursor = el?.selectionStart ?? value.length;
    const token =
      item.kind === 'keyword'
        ? `#${item.keyword.name} `
        : `@${toSlug(item.card.clean_name)} `;
    const before = value.slice(0, cursor).replace(MENTION_RE, token);
    const after = value.slice(cursor);
    onChange(before + after);
    setMentionActive(false);
    setTimeout(() => {
      el?.focus();
      el?.setSelectionRange(before.length, before.length);
    }, 0);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (mentionActive) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionIndex(i => Math.min(i + 1, mentionItems.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionIndex(i => Math.max(i - 1, 0));
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        selectMention(mentionItems[mentionIndex]);
        return;
      }
      if (e.key === 'Escape') {
        setMentionActive(false);
        return;
      }
    }

    if (e.key === 'Enter') {
      // Single-line field: always suppress the form's implicit submit so
      // Shift+Enter never sends. Plain Enter submits explicitly below.
      e.preventDefault();
      if (!e.shiftKey && !loading && isValid) onSubmit();
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!loading && isValid) onSubmit();
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <label htmlFor={inputId} className="sr-only">{label}</label>
      <form
        onSubmit={handleSubmit}
        className="relative flex items-center w-full rounded-full border border-brand-ink/10 bg-card shadow-md focus-within:border-brand-muted-ink/40 focus-within:shadow-lg transition-shadow"
      >
        <input
          ref={inputRef}
          id={inputId}
          type="text"
          role="combobox"
          aria-expanded={mentionActive}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={mentionActive ? optionId(mentionIndex) : undefined}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          disabled={loading}
          placeholder={placeholder}
          className="flex-1 bg-transparent py-4 pl-6 pr-14 text-sm text-brand-ink placeholder:text-brand-ink-faint outline-none disabled:opacity-50 min-w-0"
        />
        <button
          type="submit"
          aria-label="Send question"
          disabled={loading || !isValid}
          className={cn(
            'absolute right-2 w-10 h-10 rounded-full flex items-center justify-center transition-colors flex-shrink-0',
            loading || !isValid
              ? 'bg-brand-ink/10 text-brand-ink/30 cursor-not-allowed'
              : 'bg-brand-ink text-brand-surface hover:bg-brand-ink/80'
          )}
        >
          {loading
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <ArrowUp className="w-4 h-4" />
          }
        </button>
      </form>

      {mentionActive && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={`${label} — suggestions`}
          data-testid="mention-dropdown"
          className="absolute left-0 right-0 bottom-full mb-2 z-50 max-h-64 overflow-y-auto rounded-2xl border border-brand-ink/10 bg-card shadow-lg"
        >
          {mentionItems.map((item, i) => (
            <li
              key={item.kind === 'keyword' ? `k-${item.keyword.name}` : `c-${item.card.riftbound_id}`}
              id={optionId(i)}
              role="option"
              aria-selected={i === mentionIndex}
              ref={i === mentionIndex ? activeItemRef : null}
              className={cn(
                'cursor-pointer px-4 py-2 text-sm first:rounded-t-2xl last:rounded-b-2xl',
                i === mentionIndex ? 'bg-brand-ink/5' : 'hover:bg-brand-ink/[0.03]'
              )}
              onMouseDown={e => { e.preventDefault(); selectMention(item); }}
            >
              {item.kind === 'keyword' ? (
                item.keyword.color
                  ? <KeywordBadge def={item.keyword} />
                  : <><span className="text-brand-ink-faint">#</span>{item.keyword.name}</>
              ) : (
                <span className="flex items-center gap-2.5">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={item.card.image_url}
                    alt={item.card.clean_name}
                    loading="lazy"
                    className="h-9 w-auto rounded shrink-0 bg-brand-ink/5"
                  />
                  <span className="truncate capitalize">{item.card.clean_name}</span>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
