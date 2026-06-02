import { ACCENT, INK, INK_2, INK_3, INK_4, INK_SOFT, HAIRLINE } from './theme';

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
  p: ({ children, ...props }: React.ComponentPropsWithoutRef<'p'>) => (
    <p {...props} style={{ lineHeight: 1.75, color: INK_2, fontSize: '0.95rem', marginBottom: '0.65rem', marginTop: 0 }}>
      {children}
    </p>
  ),
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
