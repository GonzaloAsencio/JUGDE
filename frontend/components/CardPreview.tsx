'use client';

import { useRef, useState } from 'react';
import { lookupCard } from '@/lib/cardLookup';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { cn } from '@/lib/utils';

interface CardPreviewProps {
  cardName: string;
  children: React.ReactNode;
}

export function CardPreview({ cardName, children }: CardPreviewProps) {
  const card = lookupCard(cardName);
  const [loaded, setLoaded] = useState(false);
  const prefetched = useRef(false);

  if (!card) return <>{children}</>;

  // Warm the browser cache the moment the pointer (or focus) reaches the chip,
  // so by the time the hover-card opens the full art is already downloading —
  // instead of starting a cold ~2s fetch only once the popup mounts.
  const prefetch = () => {
    if (prefetched.current) return;
    prefetched.current = true;
    const img = new Image();
    img.src = card.image_url;
  };

  return (
    <HoverCard>
      <HoverCardTrigger render={<span onMouseEnter={prefetch} onFocus={prefetch} />}>{children}</HoverCardTrigger>
      <HoverCardContent className="w-60 p-1.5">
        {/* Reserve the card's aspect ratio and shimmer until the art paints, so
            the popup never opens onto an empty box. */}
        <div className="relative w-full overflow-hidden rounded" style={{ aspectRatio: '744 / 1039' }}>
          {!loaded && <span aria-hidden className="absolute inset-0 animate-pulse bg-brand-ink/10" />}
          <img
            src={card.image_url}
            alt={`Riftbound card: ${card.clean_name}`}
            width={744}
            height={1039}
            onLoad={() => setLoaded(true)}
            onError={() => setLoaded(true)}
            className={cn(
              'h-auto w-full rounded transition-opacity duration-200',
              loaded ? 'opacity-100' : 'opacity-0'
            )}
          />
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}
