'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSlug from 'rehype-slug';

interface TocEntry {
  id: string;
  text: string;
  depth: number;
}

interface TocSection {
  header: TocEntry;
  children: TocEntry[];
}

interface RulesContentProps {
  markdown: string;
  toc: TocEntry[];
}

// Theme-aware tokens (defined in globals.css :root / .dark). Inline styles can't
// use Tailwind utilities, so we reference the CSS variables directly.
const ACCENT = 'var(--brand-accent)';
const SIDEBAR_BG = 'var(--brand-sidebar)';
const INK = 'var(--brand-ink)';        // emphasis (strong)
const INK_2 = 'var(--brand-ink-2)';    // body text
const INK_3 = 'var(--brand-ink-3)';    // h2 headings
const INK_4 = 'var(--brand-ink-4)';    // h3 subheadings
const INK_SOFT = 'var(--brand-ink-soft)';
const INK_FAINT = 'var(--brand-ink-faint)';
const HAIRLINE = 'var(--border)';

function groupToc(toc: TocEntry[]): TocSection[] {
  const sections: TocSection[] = [];
  let current: TocSection | null = null;
  for (const entry of toc) {
    if (entry.depth === 1) {
      current = { header: entry, children: [] };
      sections.push(current);
    } else if (current) {
      current.children.push(entry);
    }
  }
  return sections;
}

function TocSidebar({
  sections,
  activeId,
  onNavigate,
}: {
  sections: TocSection[];
  activeId: string;
  onNavigate?: () => void;
}) {
  const [openSections, setOpenSections] = useState<Set<string>>(
    () => new Set(sections.length > 0 ? [sections[0].header.id] : [])
  );

  // Auto-expand the section containing the active item
  useEffect(() => {
    if (!activeId) return;
    for (const section of sections) {
      const ownsActive =
        section.header.id === activeId ||
        section.children.some((c) => c.id === activeId);
      if (ownsActive) {
        setOpenSections((prev) => {
          if (prev.has(section.header.id)) return prev;
          const next = new Set(prev);
          next.add(section.header.id);
          return next;
        });
        break;
      }
    }
  }, [activeId, sections]);

  const toggle = (id: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {sections.map((section) => {
        const isOpen = openSections.has(section.header.id);
        const headerActive = section.header.id === activeId;
        const hasActiveChild = section.children.some((c) => c.id === activeId);
        const numMatch = section.header.text.match(/^(\d+\.)\s+(.+)$/);
        const hasChildren = section.children.length > 0;

        return (
          <li key={section.header.id} style={{ marginBottom: 2 }}>
            {/* Section header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <a
                href={`#${section.header.id}`}
                onClick={onNavigate}
                style={{
                  flex: 1,
                  display: 'block',
                  fontSize: 13,
                  fontWeight: headerActive || hasActiveChild ? 700 : 600,
                  color: headerActive ? ACCENT : hasActiveChild ? INK_2 : INK_3,
                  paddingTop: 5,
                  paddingBottom: 5,
                  paddingLeft: 10,
                  paddingRight: 4,
                  textDecoration: 'none',
                  lineHeight: 1.3,
                  transition: 'color 0.25s ease, transform 0.25s ease, border-left-color 0.25s ease',
                  borderLeftWidth: 2,
                  borderLeftStyle: 'solid',
                  borderLeftColor: headerActive ? ACCENT : 'transparent',
                  marginLeft: -12,
                  transform: headerActive ? 'translateX(3px)' : 'translateX(0)',
                }}
                onMouseEnter={(e) => {
                  if (!headerActive) {
                    const el = e.currentTarget as HTMLAnchorElement;
                    el.style.color = ACCENT;
                    el.style.transform = 'translateX(2px)';
                  }
                }}
                onMouseLeave={(e) => {
                  if (!headerActive) {
                    const el = e.currentTarget as HTMLAnchorElement;
                    el.style.color = hasActiveChild ? INK_2 : INK_3;
                    el.style.transform = 'translateX(0)';
                  }
                }}
              >
                {numMatch ? (
                  <>
                    <span style={{ color: headerActive ? ACCENT : INK_FAINT, fontWeight: 400, marginRight: 4 }}>
                      {numMatch[1]}
                    </span>
                    {numMatch[2]}
                  </>
                ) : (
                  section.header.text
                )}
              </a>
              {hasChildren && (
                <button
                  onClick={() => toggle(section.header.id)}
                  aria-label={isOpen ? 'Collapse' : 'Expand'}
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    padding: '4px 6px',
                    color: INK_FAINT,
                    fontSize: 9,
                    lineHeight: 1,
                    flexShrink: 0,
                    transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
                    transition: 'transform 0.2s ease',
                  }}
                >
                  ▶
                </button>
              )}
            </div>

            {/* Children with animated collapse */}
            {hasChildren && (
              <div
                style={{
                  overflow: 'hidden',
                  maxHeight: isOpen ? '3000px' : '0',
                  transition: isOpen ? 'max-height 0.3s ease-in' : 'max-height 0.2s ease-out',
                }}
              >
                <ul style={{ listStyle: 'none', margin: 0, padding: '2px 0 6px' }}>
                  {section.children.map((child) => {
                    const childActive = child.id === activeId;
                    const childNum = child.text.match(/^(\d+\.)\s+(.+)$/);
                    return (
                      <li key={child.id}>
                        <a
                          href={`#${child.id}`}
                          onClick={onNavigate}
                          style={{
                            display: 'block',
                            fontSize: 11.5,
                            fontWeight: childActive ? 700 : 400,
                            color: childActive ? ACCENT : INK_SOFT,
                            paddingTop: 3,
                            paddingBottom: 3,
                            paddingLeft: 22,
                            paddingRight: 8,
                            textDecoration: 'none',
                            lineHeight: 1.35,
                            transition: 'color 0.25s ease, transform 0.25s ease, border-left-color 0.25s ease',
                            borderLeftWidth: 2,
                            borderLeftStyle: 'solid',
                            borderLeftColor: childActive ? ACCENT : 'transparent',
                            marginLeft: -12,
                            transform: childActive ? 'translateX(3px)' : 'translateX(0)',
                          }}
                          onMouseEnter={(e) => {
                            if (!childActive) {
                              const el = e.currentTarget as HTMLAnchorElement;
                              el.style.color = ACCENT;
                              el.style.transform = 'translateX(2px)';
                            }
                          }}
                          onMouseLeave={(e) => {
                            if (!childActive) {
                              const el = e.currentTarget as HTMLAnchorElement;
                              el.style.color = INK_SOFT;
                              el.style.transform = 'translateX(0)';
                            }
                          }}
                        >
                          {childNum ? (
                            <>
                              <span style={{ color: childActive ? ACCENT : INK_FAINT, marginRight: 4, fontWeight: 400 }}>
                                {childNum[1]}
                              </span>
                              {childNum[2]}
                            </>
                          ) : (
                            child.text
                          )}
                        </a>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

const mdComponents = {
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

export function RulesContent({ markdown, toc }: RulesContentProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [activeId, setActiveId] = useState('');
  const articleRef = useRef<HTMLElement>(null);

  const sections = useMemo(() => groupToc(toc), [toc]);

  useEffect(() => {
    const hash = window.location.hash;
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    const headings = articleRef.current?.querySelectorAll('h1[id], h2[id], h3[id]');
    if (!headings?.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0) setActiveId(visible[0].target.id);
      },
      { rootMargin: '-56px 0px -60% 0px', threshold: 0 }
    );
    headings.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, [markdown]);

  const sidebarContent = (
    <TocSidebar sections={sections} activeId={activeId} onNavigate={() => setMobileOpen(false)} />
  );

  return (
    <div style={{ display: 'flex', minHeight: 'calc(100vh - 52px)' }}>

      {/* Desktop sidebar */}
      <nav
        className="rules-sidebar hidden lg:block"
        style={{
          width: 260,
          flexShrink: 0,
          position: 'sticky',
          top: 52,
          height: 'calc(100vh - 52px)',
          overflowY: 'auto',
          overflowX: 'hidden',
          scrollbarWidth: 'none',
          backgroundColor: SIDEBAR_BG,
          padding: '32px 12px 32px 24px',
        } as React.CSSProperties}
      >
        <p style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: INK_FAINT, marginBottom: 16, marginTop: 0 }}>
          Contents
        </p>
        {sidebarContent}
      </nav>

      {/* Content column */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>

        {/* Mobile TOC */}
        <div className="lg:hidden" style={{ borderBottom: `1px solid ${HAIRLINE}`, backgroundColor: SIDEBAR_BG, padding: '12px 20px' }}>
          <button
            onClick={() => setMobileOpen((o) => !o)}
            style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontSize: 12, fontWeight: 600, color: INK_SOFT, letterSpacing: '0.06em', textTransform: 'uppercase' }}
          >
            Contents
            <span style={{ transform: mobileOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s', display: 'inline-block' }}>▾</span>
          </button>
          {mobileOpen && <div style={{ marginTop: 12, paddingBottom: 4 }}>{sidebarContent}</div>}
        </div>

        {/* Article */}
        <article ref={articleRef} style={{ padding: '40px 72px 80px 64px', flex: 1, minWidth: 0 }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} components={mdComponents}>
            {markdown}
          </ReactMarkdown>
        </article>
      </div>
    </div>
  );
}
