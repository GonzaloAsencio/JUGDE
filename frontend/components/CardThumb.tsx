'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';

/**
 * Card thumbnail for the @mention list. Reserves its box via aspect-ratio and
 * shows a shimmer until the (lazily loaded, remote) art arrives, then fades it
 * in — so the dropdown never flashes empty grey squares while images stream.
 */
export function CardThumb({ src, alt }: { src: string; alt: string }) {
  const [loaded, setLoaded] = useState(false);

  return (
    <span
      className="relative block h-[3.25rem] shrink-0 overflow-hidden bg-brand-ink/5 ring-1 ring-brand-ink/10 shadow-sm"
      style={{ aspectRatio: '38 / 53' }}
    >
      {!loaded && <span aria-hidden className="absolute inset-0 animate-pulse bg-brand-ink/10" />}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        loading="lazy"
        width={38}
        height={53}
        onLoad={() => setLoaded(true)}
        onError={() => setLoaded(true)}
        className={cn(
          'h-full w-full object-cover transition-opacity duration-300',
          loaded ? 'opacity-100' : 'opacity-0'
        )}
      />
    </span>
  );
}
