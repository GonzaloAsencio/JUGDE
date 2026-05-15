'use client';

import { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSlug from 'rehype-slug';
import rehypeAutolinkHeadings from 'rehype-autolink-headings';
import { cn } from '@/lib/utils';

interface TocEntry {
  id: string;
  text: string;
  depth: number;
}

interface RulesContentProps {
  markdown: string;
  toc: TocEntry[];
}

export function RulesContent({ markdown, toc }: RulesContentProps) {
  useEffect(() => {
    const hash = window.location.hash;
    if (hash) {
      document.querySelector(hash)?.scrollIntoView({ behavior: 'smooth' });
    }
  }, []);

  const tocLinks = (
    <ul className="space-y-0.5">
      {toc.map((item) => (
        <li key={item.id}>
          <a
            href={`#${item.id}`}
            className={cn(
              'block text-sm py-0.5 hover:text-foreground transition-colors',
              item.depth === 1 && 'pl-0 font-medium',
              item.depth === 2 && 'pl-3 text-muted-foreground',
              item.depth === 3 && 'pl-6 text-muted-foreground text-xs'
            )}
          >
            {item.text}
          </a>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="lg:grid lg:grid-cols-[240px_1fr] lg:gap-8">
      {/* Mobile TOC */}
      <details className="lg:hidden mb-4 border rounded-md p-3">
        <summary className="font-semibold cursor-pointer">Table of Contents</summary>
        <div className="mt-3">{tocLinks}</div>
      </details>

      {/* Desktop TOC */}
      <nav className="hidden lg:block sticky top-20 self-start max-h-[calc(100vh-5rem)] overflow-y-auto">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
          Contents
        </p>
        {tocLinks}
      </nav>

      {/* Markdown content */}
      <article className="prose prose-neutral max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeSlug, [rehypeAutolinkHeadings, { behavior: 'wrap' }]]}
        >
          {markdown}
        </ReactMarkdown>
      </article>
    </div>
  );
}
