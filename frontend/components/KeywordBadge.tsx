import type { KeywordDef } from '@/lib/gameKeywords';

interface KeywordBadgeProps {
  def: KeywordDef;
}

export function KeywordBadge({ def }: KeywordBadgeProps) {
  if (!def.color) {
    return <>{def.label}</>;
  }
  return (
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
}
