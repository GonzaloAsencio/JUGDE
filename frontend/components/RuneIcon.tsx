import type { RuneToken } from '@/lib/runeTokens';
import { Tooltip } from '@/components/ui/tooltip';

interface RuneIconProps {
  token: RuneToken;
}

export function RuneIcon({ token }: RuneIconProps) {
  const inner =
    token.kind === 'energy' ? (
      <span
        aria-label={token.alt}
        role="img"
        className="inline-flex items-center justify-center rounded-full font-bold tabular-nums align-middle"
        style={{
          width: '1.25em',
          height: '1.25em',
          margin: '0 1px',
          backgroundColor: '#ffffff',
          color: '#000000',
          fontSize: '0.9em',
          lineHeight: 1,
          border: '1px solid rgba(0,0,0,0.25)',
        }}
      >
        <span style={{ lineHeight: 1, transform: 'translateY(0.02em)' }}>{token.value}</span>
      </span>
    ) : (
      <img
        src={token.src}
        alt={token.alt}
        loading="lazy"
        // Monochrome (black) glyphs are invisible on dark bg — force them to pure
        // white in dark mode. Colored runes (mono unset) keep their color.
        className={`inline-block align-[-0.18em]${token.mono ? ' dark:brightness-0 dark:invert' : ''}`}
        style={{ height: token.emphasis ? '1.35em' : '1.1em', width: 'auto', margin: '0 1px' }}
      />
    );

  return <Tooltip content={token.desc}>{inner}</Tooltip>;
}
