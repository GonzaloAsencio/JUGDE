import { useId } from 'react';
import { Loader2, ArrowUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { KeywordBadge } from '@/components/KeywordBadge';
import { CardThumb } from '@/components/CardThumb';
import { useMentions } from '@/components/useMentions';

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
  const label = placeholder ?? 'Ask the judge a rules question';

  const {
    active,
    items,
    index,
    inputRef,
    containerRef,
    activeItemRef,
    handleInputChange,
    handleKeyDown: onMentionKeyDown,
    select,
  } = useMentions({ value, onChange });

  // Stable ids for the ARIA combobox wiring (input ↔ listbox ↔ active option).
  const inputId = useId();
  const listboxId = useId();
  const optionId = (i: number) => `${listboxId}-opt-${i}`;

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (onMentionKeyDown(e)) return;

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
          aria-expanded={active}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={active ? optionId(index) : undefined}
          value={value}
          onChange={handleInputChange}
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

      {active && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={`${label} — suggestions`}
          data-testid="mention-dropdown"
          className="mention-scroll absolute left-0 right-0 bottom-full mb-2 z-50 max-h-80 overflow-y-auto rounded-2xl border border-brand-ink/10 bg-card shadow-lg"
        >
          {items.map((item, i) => (
            <li
              key={item.kind === 'keyword' ? `k-${item.keyword.name}` : `c-${item.card.riftbound_id}`}
              id={optionId(i)}
              role="option"
              aria-selected={i === index}
              ref={i === index ? activeItemRef : null}
              className={cn(
                'cursor-pointer px-4 py-2.5 text-sm first:rounded-t-2xl last:rounded-b-2xl',
                i === index ? 'bg-brand-ink/5' : 'hover:bg-brand-ink/[0.03]'
              )}
              onMouseDown={e => { e.preventDefault(); select(item); }}
            >
              {item.kind === 'keyword' ? (
                item.keyword.color
                  ? <KeywordBadge def={item.keyword} />
                  : <><span className="text-brand-ink-faint">#</span>{item.keyword.name}</>
              ) : (
                <span className="flex items-center gap-3.5">
                  <CardThumb src={item.card.image_url} alt={item.card.clean_name} />
                  <span className="truncate capitalize text-[0.95rem]">{item.card.clean_name}</span>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
