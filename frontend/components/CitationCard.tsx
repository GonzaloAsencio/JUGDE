import Link from 'next/link';
import { ExternalLink } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { CardPreview } from '@/components/CardPreview';
import { sectionToSlug } from '@/lib/slug';
import type { Citation } from '@/lib/types';

interface CitationCardProps {
  citation: Citation;
  rank: number;
}

export function CitationCard({ citation }: CitationCardProps) {
  const isCard = citation.source_type === 'card';
  const slug = sectionToSlug(citation.section);
  const href = slug ? `/rules#${slug}` : '/rules';

  const header = (
    <span className="inline-flex items-center gap-2">
      <Badge variant={isCard ? 'default' : 'secondary'}>{citation.source_type}</Badge>
      <span className="text-sm font-medium">
        {isCard ? citation.section : `§ ${citation.section}`}
      </span>
    </span>
  );

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-2 flex-wrap">
        {isCard ? <CardPreview cardName={citation.section}>{header}</CardPreview> : header}
        <span className="text-xs text-muted-foreground ml-auto">
          {Math.round(citation.similarity * 100)}%
        </span>
      </div>

      <p className="text-sm text-muted-foreground line-clamp-2">{citation.content_preview}</p>

      {!isCard && (
        <Link
          href={href}
          className="flex items-center gap-1 text-xs text-primary hover:underline mt-auto"
        >
          View <ExternalLink size={12} />
        </Link>
      )}
    </Card>
  );
}
