'use client';

import { useState } from 'react';
import type { TocSection } from './toc';
import { ACCENT, INK_2, INK_3, INK_SOFT, INK_FAINT } from './theme';

export function TocSidebar({
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

  // Auto-expand the section containing the active item. Done during render
  // (guarded by the previous activeId) rather than in an effect, which is the
  // React-recommended way to adjust state when a prop changes.
  const [prevActiveId, setPrevActiveId] = useState<string | null>(null);
  if (activeId && activeId !== prevActiveId) {
    setPrevActiveId(activeId);
    const active = sections.find(
      (section) =>
        section.header.id === activeId ||
        section.children.some((c) => c.id === activeId)
    );
    if (active && !openSections.has(active.header.id)) {
      setOpenSections((prev) => new Set(prev).add(active.header.id));
    }
  }

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
