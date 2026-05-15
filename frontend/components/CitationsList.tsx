import type { Citation } from '@/lib/types';
import { CitationCard } from '@/components/CitationCard';

interface CitationsListProps {
  citations: Citation[];
}

export function CitationsList({ citations }: CitationsListProps) {
  if (citations.length === 0) return null;

  const sorted = [...citations].sort((a, b) => b.similarity - a.similarity);

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
        📚 Sources
      </h3>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {sorted.map((c, i) => (
          <CitationCard key={`${c.section}-${i}`} citation={c} rank={i + 1} />
        ))}
      </div>
    </div>
  );
}
