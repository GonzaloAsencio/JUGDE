import React from 'react';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AnswerSkeleton } from '@/components/AnswerSkeleton';
import { ErrorDisplay } from '@/components/ErrorDisplay';
import { KeywordBadge } from '@/components/KeywordBadge';
import { detectKeywords } from '@/lib/keywordDetection';
import ruleAnchors from '@/content/rule-anchors.json';
import type { ApiError, Citation } from '@/lib/types';
import type { Components } from 'react-markdown';

interface AnswerDisplayProps {
  answer: string | null;
  loading: boolean;
  error: ApiError | null;
  citations?: Citation[];
  onRetry?: () => void;
}

function CitationChip({ section }: { section: string }) {
  return (
    <span className="inline-flex items-center mx-0.5 px-1.5 py-0.5 text-[0.72em] font-medium rounded-md bg-black/5 text-[#555555] border border-black/8 align-middle leading-none">
      §&nbsp;{section}
    </span>
  );
}

const CITATION_RE = /(\[#\d+\])/g;
const RULE_REF_RE = /(\b\d{3,}\.\d[\d.a-z]*)/g;

const anchors = ruleAnchors as Record<string, string>;
const anchorKeys = Object.keys(anchors).map(Number).sort((a, b) => b - a);

function ruleRefToHref(ref: string): string {
  const num = parseInt(ref);
  const floor = anchorKeys.find(k => k <= num);
  if (floor === undefined) return '/rules';
  return `/rules#${anchors[String(floor)]}`;
}

function RuleLink({ children, href }: { children: string; href: string }) {
  return (
    <Link
      href={href}
      className="inline-code font-mono text-[0.8em] text-[#555555] bg-black/5 border border-black/8 rounded px-1 py-0.5 hover:bg-black/10 hover:text-black transition-colors no-underline"
    >
      {children}
    </Link>
  );
}

function splitWithRuleRefs(text: string, baseKey: string): React.ReactNode[] {
  const parts = text.split(RULE_REF_RE);
  return parts.map((part, i) => {
    if (RULE_REF_RE.test(part)) {
      RULE_REF_RE.lastIndex = 0;
      return <RuleLink key={`${baseKey}-r${i}`} href={ruleRefToHref(part)}>{part}</RuleLink>;
    }
    if (!part) return null;
    const segments = detectKeywords(part);
    if (segments.length === 1 && !segments[0].keyword) return part;
    return segments.map((seg, j) =>
      seg.keyword ? <KeywordBadge key={`${baseKey}-r${i}-k${j}`} def={seg.keyword} /> : seg.text
    );
  });
}

function processText(children: React.ReactNode, citations: Citation[]): React.ReactNode {
  const mapped = React.Children.map(children, (child) => {
    if (typeof child !== 'string') return child;

    const parts = child.split(CITATION_RE);

    return parts.map((part, i) => {
      const citMatch = part.match(/^\[#(\d+)\]$/);
      if (citMatch) {
        const idx = parseInt(citMatch[1]) - 1;
        const citation = citations[idx];
        return citation
          ? <CitationChip key={i} section={citation.section} />
          : <span key={i} className="text-[#aaaaaa] text-[0.75em]">{part}</span>;
      }
      return splitWithRuleRefs(part, String(i));
    });
  });
  return mapped ?? children;
}

function makeComponents(citations: Citation[]): Components {
  return {
    p: ({ children, ...props }) => <p {...props}>{processText(children, citations)}</p>,
    li: ({ children, ...props }) => <li {...props}>{processText(children, citations)}</li>,
  };
}

export function AnswerDisplay({ answer, loading, error, citations = [], onRetry }: AnswerDisplayProps) {
  if (loading) return <AnswerSkeleton />;

  if (error) {
    return <ErrorDisplay error={error} onRetry={onRetry ?? (() => {})} />;
  }

  if (answer) {
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        className="prose prose-neutral max-w-none"
        components={makeComponents(citations)}
      >
        {answer}
      </ReactMarkdown>
    );
  }

  return null;
}
