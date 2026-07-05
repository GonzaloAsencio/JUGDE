import React from 'react';
import { ACCENT, INK, INK_2, INK_3, INK_4, INK_SOFT, INK_FAINT, HAIRLINE } from './theme';
import { parseClause } from './structureClauses';

const bodyText: React.CSSProperties = {
  lineHeight: 1.7,
  color: INK_2,
  fontSize: '0.95rem',
  margin: 0,
};

/**
 * Body paragraph renderer. A clause paragraph ("133.4.a. …") gets its rule
 * number hung in a fixed left column and indented by nesting depth; an
 * "Example:" note becomes a muted callout. Everything else is a plain paragraph.
 */
function Paragraph({ children }: React.ComponentPropsWithoutRef<'p'>) {
  const arr = React.Children.toArray(children);
  const first = arr[0];

  if (typeof first === 'string') {
    // Example callout
    const ex = first.match(/^Example:\s*/);
    if (ex) {
      const body = [first.slice(ex[0].length), ...arr.slice(1)];
      return (
        <div
          style={{
            borderLeft: `2px solid ${HAIRLINE}`,
            paddingLeft: '0.85rem',
            margin: '0.4rem 0 0.7rem',
            color: INK_SOFT,
            fontSize: '0.875rem',
            fontStyle: 'italic',
            lineHeight: 1.65,
          }}
        >
          <span style={{ fontStyle: 'normal', fontWeight: 700, fontSize: '0.7rem', letterSpacing: '0.08em', textTransform: 'uppercase', color: INK_FAINT, marginRight: 6 }}>
            Example
          </span>
          {body}
        </div>
      );
    }

    // Numbered clause: hang the number, indent by depth.
    const parsed = parseClause(first);
    if (parsed) {
      const { num, depth, rest } = parsed;
      const isTop = depth === 1;
      return (
        <div
          className="rules-clause"
          style={{
            // Indent step is applied in CSS (responsive) from this depth var.
            ['--rc-depth' as string]: Math.min(depth - 1, 4),
            display: 'flex',
            gap: 10,
            marginTop: isTop ? '1.1rem' : '0.35rem',
            marginBottom: '0.35rem',
          } as React.CSSProperties}
        >
          <span
            className="rules-clause__num"
            style={{
              flexShrink: 0,
              whiteSpace: 'nowrap',
              fontFamily: 'var(--font-mono, ui-monospace, monospace)',
              fontSize: '0.78rem',
              fontWeight: isTop ? 700 : 400,
              color: isTop ? INK_3 : INK_FAINT,
              lineHeight: 1.9,
            }}
          >
            {num}.
          </span>
          <p style={{ ...bodyText, flex: 1, minWidth: 0 }}>{rest ? [rest, ...arr.slice(1)] : arr.slice(1)}</p>
        </div>
      );
    }
  }

  return <p style={{ ...bodyText, marginBottom: '0.65rem' }}>{children}</p>;
}

/** Styled element overrides passed to <ReactMarkdown> for the rulebook. */
export const mdComponents = {
  h1: ({ children, ...props }: React.ComponentPropsWithoutRef<'h1'>) => (
    <h1
      {...props}
      style={{
        fontSize: 'clamp(1.6rem, 3vw, 2.2rem)',
        fontWeight: 900,
        fontStyle: 'italic',
        textTransform: 'uppercase' as const,
        letterSpacing: '0.04em',
        color: ACCENT,
        marginTop: '2.5rem',
        marginBottom: '0.5rem',
        paddingBottom: '0.5rem',
        borderBottom: `1px solid ${HAIRLINE}`,
        lineHeight: 1.15,
      }}
    >
      {children}
    </h1>
  ),
  h2: ({ children, ...props }: React.ComponentPropsWithoutRef<'h2'>) => (
    <h2
      {...props}
      style={{
        fontSize: '1.05rem',
        fontWeight: 700,
        textTransform: 'uppercase' as const,
        letterSpacing: '0.08em',
        color: INK_3,
        marginTop: '1.75rem',
        marginBottom: '0.4rem',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: '50%', backgroundColor: ACCENT, flexShrink: 0, display: 'inline-block' }} />
      {children}
    </h2>
  ),
  h3: ({ children, ...props }: React.ComponentPropsWithoutRef<'h3'>) => (
    <h3
      {...props}
      style={{
        fontSize: '0.9rem',
        fontWeight: 600,
        color: INK_4,
        marginTop: '1.25rem',
        marginBottom: '0.3rem',
        letterSpacing: '0.02em',
      }}
    >
      {children}
    </h3>
  ),
  p: Paragraph,
  ul: ({ children, ...props }: React.ComponentPropsWithoutRef<'ul'>) => (
    <ul {...props} style={{ paddingLeft: '1.4rem', color: INK_2, lineHeight: 1.7, marginBottom: '0.65rem', marginTop: 0 }}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }: React.ComponentPropsWithoutRef<'ol'>) => (
    <ol {...props} style={{ paddingLeft: '1.4rem', color: INK_2, lineHeight: 1.7, marginBottom: '0.65rem', marginTop: 0 }}>
      {children}
    </ol>
  ),
  li: ({ children, ...props }: React.ComponentPropsWithoutRef<'li'>) => (
    <li {...props} style={{ marginBottom: '0.3rem', fontSize: '0.95rem' }}>{children}</li>
  ),
  strong: ({ children, ...props }: React.ComponentPropsWithoutRef<'strong'>) => (
    <strong {...props} style={{ color: INK, fontWeight: 700 }}>{children}</strong>
  ),
  a: ({ children, ...props }: React.ComponentPropsWithoutRef<'a'>) => (
    <a {...props} style={{ color: ACCENT, textDecoration: 'underline', textDecorationColor: 'rgba(212,98,10,0.3)' }}>
      {children}
    </a>
  ),
  blockquote: ({ children, ...props }: React.ComponentPropsWithoutRef<'blockquote'>) => (
    <blockquote {...props} style={{ borderLeft: `3px solid ${ACCENT}`, paddingLeft: '1rem', marginLeft: 0, color: INK_SOFT, fontStyle: 'italic', marginBottom: '0.75rem' }}>
      {children}
    </blockquote>
  ),
};
