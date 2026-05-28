'use client';

import { Popover } from '@base-ui/react/popover';
import { cn } from '@/lib/utils';
import { CitationCard } from '@/components/CitationCard';
import type { Citation } from '@/lib/types';

interface SourcesPopoverProps {
  citations: Citation[];
}

export function SourcesPopover({ citations }: SourcesPopoverProps) {
  const sorted = [...citations].sort((a, b) => b.similarity - a.similarity);

  return (
    <Popover.Root>
      <Popover.Trigger
        className={cn(
          'flex items-center gap-1.5 rounded-full border border-black/10 bg-black/5',
          'px-3 py-1.5 text-xs font-medium text-[#555555]',
          'transition-colors hover:bg-black/10 cursor-pointer select-none'
        )}
      >

        <span>{sorted.length} {sorted.length === 1 ? 'source' : 'sources'}</span>
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Positioner side="top" sideOffset={8} align="end" className="isolate z-50">
          <Popover.Popup
            className={cn(
              'w-80 max-h-[70vh] overflow-y-auto rounded-2xl bg-white shadow-xl',
              'ring-1 ring-black/5 p-3 space-y-2',
              'origin-(--transform-origin)',
              'data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95',
              'data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95',
              'data-[side=top]:slide-in-from-bottom-2 data-[side=bottom]:slide-in-from-top-2',
              'duration-100'
            )}
          >
            <p className="text-[10px] uppercase tracking-[0.2em] text-[#999999] font-semibold px-1 pb-1">
              Sources
            </p>
            {sorted.map((c, i) => (
              <CitationCard key={`${c.section}-${i}`} citation={c} rank={i + 1} />
            ))}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
