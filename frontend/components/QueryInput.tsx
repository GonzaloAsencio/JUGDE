import { useState, useRef, useEffect } from 'react';
import { Loader2, ArrowUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { GAME_KEYWORDS, type KeywordDef } from '@/lib/gameKeywords';
import { KeywordBadge } from '@/components/KeywordBadge';

interface QueryInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  loading: boolean;
  placeholder?: string;
}

export function QueryInput({ value, onChange, onSubmit, loading, placeholder }: QueryInputProps) {
  const trimmed = value.trim();
  const isValid = trimmed.length >= 3 && trimmed.length <= 1000;

  const [mentionActive, setMentionActive] = useState(false);
  const [filteredKeywords, setFilteredKeywords] = useState<KeywordDef[]>([]);
  const [mentionIndex, setMentionIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const activeItemRef = useRef<HTMLLIElement>(null);

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
    const beforeCursor = val.slice(0, cursor);
    const match = beforeCursor.match(/@([\w-]*)$/);

    if (match) {
      const search = match[1];
      const results = GAME_KEYWORDS.filter(k =>
        k.name.toLowerCase().startsWith(search.toLowerCase())
      );
      if (results.length > 0) {
        setFilteredKeywords(results);
        setMentionActive(true);
        setMentionIndex(0);
        return;
      }
    }
    setMentionActive(false);
  }

  function selectMention(keywordName: string) {
    const el = inputRef.current;
    const cursor = el?.selectionStart ?? value.length;
    const before = value.slice(0, cursor).replace(/@([\w-]*)$/, `@${keywordName} `);
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
        setMentionIndex(i => Math.min(i + 1, filteredKeywords.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionIndex(i => Math.max(i - 1, 0));
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        selectMention(filteredKeywords[mentionIndex].name);
        return;
      }
      if (e.key === 'Escape') {
        setMentionActive(false);
        return;
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!loading && isValid) onSubmit();
    }
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <div className="relative flex items-center w-full rounded-full border border-black/10 bg-white shadow-md focus-within:border-black/20 focus-within:shadow-lg transition-shadow">
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          disabled={loading}
          placeholder={placeholder}
          className="flex-1 bg-transparent py-4 pl-6 pr-14 text-sm text-[#111111] placeholder:text-[#aaaaaa] outline-none disabled:opacity-50 min-w-0"
        />
        <button
          onClick={onSubmit}
          disabled={loading || !isValid}
          className={cn(
            'absolute right-2 w-10 h-10 rounded-full flex items-center justify-center transition-colors flex-shrink-0',
            loading || !isValid
              ? 'bg-black/10 text-black/30 cursor-not-allowed'
              : 'bg-[#111111] text-white hover:bg-[#333333]'
          )}
        >
          {loading
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <ArrowUp className="w-4 h-4" />
          }
        </button>
      </div>

      {mentionActive && (
        <ul
          data-testid="mention-dropdown"
          className="absolute left-0 right-0 bottom-full mb-2 z-50 max-h-48 overflow-y-auto rounded-2xl border border-black/10 bg-white shadow-lg"
        >
          {filteredKeywords.map((kw, i) => (
            <li
              key={kw.name}
              ref={i === mentionIndex ? activeItemRef : null}
              className={cn(
                'cursor-pointer px-4 py-2.5 text-sm first:rounded-t-2xl last:rounded-b-2xl',
                i === mentionIndex
                  ? 'bg-black/5'
                  : 'hover:bg-black/[0.03]'
              )}
              onMouseDown={e => { e.preventDefault(); selectMention(kw.name); }}
            >
              {kw.color
                ? <KeywordBadge def={kw} />
                : <><span className="text-[#aaaaaa]">@</span>{kw.name}</>
              }
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
