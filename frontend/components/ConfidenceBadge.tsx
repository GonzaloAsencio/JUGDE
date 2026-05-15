import { deriveConfidence } from '@/lib/confidence';
import type { Citation } from '@/lib/types';

interface ConfidenceBadgeProps {
  citations: Citation[];
}

const CONFIG = {
  high: {
    className: 'bg-emerald-100 text-emerald-800',
    label: '●●● High confidence',
  },
  medium: {
    className: 'bg-amber-100 text-amber-800',
    label: '●●○ Medium confidence',
  },
  low: {
    className: 'bg-red-100 text-red-800',
    label: '●○○ Low confidence',
  },
} as const;

export function ConfidenceBadge({ citations }: ConfidenceBadgeProps) {
  const level = deriveConfidence(citations);
  if (!level) return null;

  const avg = citations.reduce((s, c) => s + c.similarity, 0) / citations.length;
  const { className, label } = CONFIG[level];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${className}`}
      title={`Avg similarity: ${avg.toFixed(2)}`}
    >
      {label}
    </span>
  );
}
