import { confidenceLevel } from '@/lib/confidence';

interface ConfidenceBadgeProps {
  confidence: number | null;
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

export function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const level = confidenceLevel(confidence);
  if (!level) return null;

  const { className, label } = CONFIG[level];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${className}`}
      title={`Retrieval confidence: ${(confidence ?? 0).toFixed(2)}`}
    >
      {label}
    </span>
  );
}
