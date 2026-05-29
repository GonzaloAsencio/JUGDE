'use client';

import { lookupCard } from '@/lib/cardLookup';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';

interface CardPreviewProps {
  cardName: string;
  children: React.ReactNode;
}

export function CardPreview({ cardName, children }: CardPreviewProps) {
  const card = lookupCard(cardName);
  if (!card) return <>{children}</>;

  return (
    <HoverCard>
      <HoverCardTrigger render={<span />}>{children}</HoverCardTrigger>
      <HoverCardContent className="w-60 p-1.5">
        <img
          src={card.image_url}
          alt={`Riftbound card: ${card.clean_name}`}
          loading="lazy"
          width={744}
          height={1039}
          className="w-full h-auto rounded"
        />
      </HoverCardContent>
    </HoverCard>
  );
}
