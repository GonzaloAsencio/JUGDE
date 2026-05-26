import { useState, useRef, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { GAME_KEYWORDS } from '@/lib/gameKeywords';

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
  const [filteredKeywords, setFilteredKeywords] = useState<string[]>([]);
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
        k.toLowerCase().startsWith(search.toLowerCase())
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

  function selectMention(keyword: string) {
    const el = inputRef.current;
    const cursor = el?.selectionStart ?? value.length;
    const before = value.slice(0, cursor).replace(/@([\w-]*)$/, `@${keyword} `);
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
        selectMention(filteredKeywords[mentionIndex]);
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
    <div className="flex gap-2 w-full">
      <div ref={containerRef} className="relative flex-1">
        <Input
          ref={inputRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          disabled={loading}
          placeholder={placeholder}
          className="w-full"
        />
        {mentionActive && (
          <ul className="absolute left-0 right-0 top-full z-50 mt-1 max-h-48 overflow-y-auto rounded-md border border-input bg-popover shadow-md">
            {filteredKeywords.map((kw, i) => (
              <li
                key={kw}
                ref={i === mentionIndex ? activeItemRef : null}
                className={cn(
                  'cursor-pointer px-3 py-2 text-sm',
                  i === mentionIndex
                    ? 'bg-accent text-accent-foreground'
                    : 'hover:bg-accent/50'
                )}
                onMouseDown={e => { e.preventDefault(); selectMention(kw); }}
              >
                <span className="text-muted-foreground">@</span>{kw}
              </li>
            ))}
          </ul>
        )}
      </div>
      <Button
        onClick={onSubmit}
        disabled={loading || !isValid}
      >
        {loading ? <Loader2 className="animate-spin" /> : 'Ask Judge'}
      </Button>
    </div>
  );
}
