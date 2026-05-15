import { ExternalLink } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { sectionToSlug } from '@/lib/slug';
import type { Citation } from '@/lib/types';

interface CitationCardProps {
  citation: Citation;
  rank: number;
}

export function CitationCard({ citation }: CitationCardProps) {
  const slug = sectionToSlug(citation.section);
  const href = slug ? `/rules#${slug}` : '/rules';

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="secondary">{citation.source_type}</Badge>
        <span className="text-sm font-medium">§ {citation.section}</span>
        <span className="text-xs text-muted-foreground ml-auto">
          {Math.round(citation.similarity * 100)}%
        </span>
      </div>

      <p className="text-sm text-muted-foreground line-clamp-2">{citation.content_preview}</p>

      <a
        href={href}
        className="flex items-center gap-1 text-xs text-primary hover:underline mt-auto"
      >
        View <ExternalLink size={12} />
      </a>
    </Card>
  );
}
