'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSlug from 'rehype-slug';
import { groupToc, type TocEntry } from './toc';
import { TocSidebar } from './TocSidebar';
import { mdComponents } from './markdownComponents';
import { INK_SOFT, INK_FAINT, HAIRLINE } from './theme';

interface RulesContentProps {
  markdown: string;
  toc: TocEntry[];
}

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
          borderRight: `1px solid ${HAIRLINE}`,
          padding: '32px 12px 32px 24px',
        } as React.CSSProperties}
      >
        <p style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: INK_FAINT, marginBottom: 16, marginTop: 0 }}>
          Contents
        </p>
        {sidebarContent}
      </nav>

      {/* Content column */}
      <main id="main-content" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>

        {/* Mobile TOC */}
        <div className="lg:hidden" style={{ position: 'relative', borderBottom: `1px solid ${HAIRLINE}`, padding: '12px 20px' }}>
          <button
            onClick={() => setMobileOpen((o) => !o)}
            aria-expanded={mobileOpen}
            style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontSize: 12, fontWeight: 600, color: INK_SOFT, letterSpacing: '0.06em', textTransform: 'uppercase' }}
          >
            Contents
            <span style={{ transform: mobileOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s', display: 'inline-block' }}>▾</span>
          </button>
          {/* Float the open TOC above the article instead of pushing it down. */}
          {mobileOpen && (
            <div
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                top: '100%',
                zIndex: 30,
                maxHeight: '70vh',
                overflowY: 'auto',
                backgroundColor: 'var(--brand-surface)',
                borderBottom: `1px solid ${HAIRLINE}`,
                boxShadow: '0 14px 28px -14px rgba(0,0,0,0.3)',
                padding: '8px 20px 16px',
              }}
            >
              {sidebarContent}
            </div>
          )}
        </div>

        {/* Article */}
        <article ref={articleRef} style={{ padding: '40px clamp(20px, 6vw, 72px) 80px clamp(20px, 5vw, 64px)', flex: 1, minWidth: 0 }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} components={mdComponents}>
            {markdown}
          </ReactMarkdown>
        </article>
      </main>
    </div>
  );
}
