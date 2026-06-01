import type { KeywordDef } from '@/lib/gameKeywords';
import { Tooltip } from '@/components/ui/tooltip';

interface KeywordBadgeProps {
  def: KeywordDef;
}

export function KeywordBadge({ def }: KeywordBadgeProps) {
  // Plain-text keyword (no colored badge): show the label, with a dotted
  // underline as a hover affordance when we have an explanation.
  if (!def.color) {
    if (!def.description) return <>{def.label}</>;
    return (
      <Tooltip content={def.description}>
        <span className="underline decoration-dotted decoration-from-font underline-offset-2">
          {def.label}
        </span>
      </Tooltip>
    );
  }

  const badge = (
    <span
      className="relative inline-block text-xs font-bold italic tracking-wide"
      style={{
        padding: '2px 8px',
        margin: '0 3px 2px',
        color: def.textColor ?? 'white',
        fontSize: '0.85em',
        zIndex: 1,
      }}
    >
      <span
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundColor: def.color,
          transform: 'skewX(-12deg)',
          borderRadius: '4px',
          zIndex: -1,
        }}
      />
      <span className="relative">{def.label}</span>
    </span>
  );

  if (!def.description) return badge;
  return <Tooltip content={def.description}>{badge}</Tooltip>;
}
