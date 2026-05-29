interface CardChipProps {
  name: string;
}

export function CardChip({ name }: CardChipProps) {
  return (
    <span
      className="relative inline-block text-xs font-bold italic tracking-wide"
      style={{
        padding: '2px 8px',
        margin: '0 3px 2px',
        color: 'white',
        fontSize: '0.85em',
        zIndex: 1,
      }}
    >
      <span
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundColor: '#1f2937',
          transform: 'skewX(-12deg)',
          borderRadius: '4px',
          zIndex: -1,
        }}
      />
      <span className="relative">{name.toUpperCase()}</span>
    </span>
  );
}
