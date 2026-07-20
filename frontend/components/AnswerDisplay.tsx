'use client';

import React from 'react';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AnswerSkeleton } from '@/components/AnswerSkeleton';
import { KeywordBadge } from '@/components/KeywordBadge';
import { CardChip } from '@/components/CardChip';
import { CardPreview } from '@/components/CardPreview';
import { RuneIcon } from '@/components/RuneIcon';
import { detectKeywords } from '@/lib/keywordDetection';
import { detectCards } from '@/lib/cardDetection';
import { detectRuneTokens } from '@/lib/runeTokens';
import { useRevealedText } from '@/lib/useRevealedText';
import ruleAnchors from '@/content/rule-anchors.json';
import type { Components } from 'react-markdown';

interface AnswerDisplayProps {
  answer: string | null;
  loading: boolean;
}

const CITATION_RE = /\[:?#[\d,\s]+\]/g;
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
      className="inline-code font-mono text-[0.8em] text-brand-ink-soft bg-brand-ink/5 border border-brand-ink/10 rounded px-1 py-0.5 hover:bg-brand-ink/10 hover:text-brand-ink transition-colors no-underline"
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
    return renderEntities(part, `${baseKey}-r${i}`);
  });
}

// Pipeline order: rune/symbol tokens first (they are delimited ":rb_*:" and
// unambiguous), then cards (multi-word names), then keywords inside the leftover
// plain text. Cards win over keywords so a keyword inside a card name is not split.
function renderEntities(text: string, baseKey: string): React.ReactNode {
  const runeSegments = detectRuneTokens(text);
  return runeSegments.map((rseg, ri) => {
    if (rseg.token) {
      return <RuneIcon key={`${baseKey}-t${ri}`} token={rseg.token} />;
    }
    const cardSegments = detectCards(rseg.text);
    return cardSegments.map((cseg, ci) => {
      if (cseg.card) {
        return (
          <CardPreview key={`${baseKey}-t${ri}-c${ci}`} cardName={cseg.card.clean_name}>
            <CardChip name={cseg.card.clean_name} />
          </CardPreview>
        );
      }
      const kwSegments = detectKeywords(cseg.text);
      if (kwSegments.length === 1 && !kwSegments[0].keyword) return cseg.text;
      return kwSegments.map((kseg, ki) => {
        if (kseg.keyword) {
          return <KeywordBadge key={`${baseKey}-t${ri}-c${ci}-k${ki}`} def={kseg.keyword} />;
        }
        // Card text wraps keywords in brackets ("[HIDDEN]"). Drop a bracket that
        // sits directly against a keyword we just rendered, so it reads "HIDDEN".
        let t = kseg.text;
        if (kwSegments[ki + 1]?.keyword) t = t.replace(/\[\s*$/, '');
        if (kwSegments[ki - 1]?.keyword) t = t.replace(/^\s*\]/, '');
        return t;
      });
    });
  });
}

function processText(children: React.ReactNode): React.ReactNode {
  const mapped = React.Children.map(children, (child) => {
    if (typeof child !== 'string') return child;

    const parts = child.split(CITATION_RE);

    return parts.map((part, i) => {
      if (CITATION_RE.test(part)) {
        CITATION_RE.lastIndex = 0;
        return null;
      }
      return splitWithRuleRefs(part, String(i));
    });
  });
  return mapped ?? children;
}

// Matches a leading "Reasoning:" / "Answer:" section heading, tolerating the
// markdown decoration the model sometimes adds ("**Answer:**", "### Answer :").
// Mirrors the backend's _ANSWER_HEADING_RE so we style exactly what it emits.
const SECTION_LABEL_RE = /^[\s*_#>-]*(reasoning|answer)[\s*_]*:\s*/i;

function SectionLabel({ label }: { label: 'reasoning' | 'answer' }) {
  const isAnswer = label === 'answer';
  return (
    <span
      className={`block text-[10px] uppercase tracking-[0.28em] font-bold mb-1.5 ${
        isAnswer ? 'text-brand-accent' : 'text-brand-muted-ink'
      }`}
    >
      {label}
    </span>
  );
}

// The model wraps entity names in backticks ("`Tideturner`"). react-markdown
// renders those as a bare <code> element by default, which skips processText
// entirely — so a backticked card name never reaches detectCards. Only card
// names get special handling here; everything else (rule refs, keywords)
// already renders correctly as plain inline code.
function CodeSpan({ children, ...props }: { children?: React.ReactNode }) {
  const text = React.Children.toArray(children).join('');
  const cardSegments = detectCards(text);
  if (cardSegments.length === 1 && cardSegments[0].card) {
    const card = cardSegments[0].card;
    return (
      <CardPreview cardName={card.clean_name}>
        <CardChip name={card.clean_name} />
      </CardPreview>
    );
  }
  return <code {...props}>{children}</code>;
}

function makeComponents(): Components {
  return {
    code: CodeSpan,
    p: ({ children, ...props }) => {
      // Promote a leading "Reasoning:"/"Answer:" into a section eyebrow so the
      // reader can scan reasoning vs. conclusion. Only the first text child can
      // carry the heading; anything else renders as a normal paragraph.
      const arr = React.Children.toArray(children);
      const first = arr[0];
      if (typeof first === 'string') {
        const match = first.match(SECTION_LABEL_RE);
        if (match) {
          const label = match[1].toLowerCase() as 'reasoning' | 'answer';
          const rest = first.slice(match[0].length);
          const restChildren = rest ? [rest, ...arr.slice(1)] : arr.slice(1);
          return (
            <p {...props}>
              <SectionLabel label={label} />
              {processText(restChildren)}
            </p>
          );
        }
      }
      return <p {...props}>{processText(children)}</p>;
    },
    li: ({ children, ...props }) => <li {...props}>{processText(children)}</li>,
  };
}

// Stable across renders — makeComponents closes over nothing component-scoped,
// so building it once avoids handing react-markdown a fresh components object
// (new closures) on every reveal tick (~30/sec while streaming), which forced a
// full re-parse each time.
const MARKDOWN_COMPONENTS = makeComponents();

export function AnswerDisplay({ answer, loading }: AnswerDisplayProps) {
  // Smooths delivery: streamed deltas AND at-once answers (cache hits, burst
  // providers) reveal at reading pace instead of flashing in. While streaming,
  // the partial answer renders; the skeleton only shows before the first text.
  const revealed = useRevealedText(answer);

  if (revealed) {
    const cleaned = revealed
      .replace(CITATION_RE, '')
      .replace(/\brelevant sections?\s*:\s*[,\s]*/gi, '')
      .replace(/\n{3,}/g, '\n\n')
      .trim();

    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        className="prose prose-neutral dark:prose-invert max-w-none"
        components={MARKDOWN_COMPONENTS}
      >
        {cleaned}
      </ReactMarkdown>
    );
  }

  if (loading) return <AnswerSkeleton />;

  return null;
}
