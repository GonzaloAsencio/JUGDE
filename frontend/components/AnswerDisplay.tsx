import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AnswerSkeleton } from '@/components/AnswerSkeleton';
import { ErrorDisplay } from '@/components/ErrorDisplay';
import { KeywordBadge } from '@/components/KeywordBadge';
import { detectKeywords } from '@/lib/keywordDetection';
import type { ApiError } from '@/lib/types';
import type { Components } from 'react-markdown';

interface AnswerDisplayProps {
  answer: string | null;
  loading: boolean;
  error: ApiError | null;
  onRetry?: () => void;
}

function processText(children: React.ReactNode): React.ReactNode {
  const mapped = React.Children.map(children, (child) => {
    if (typeof child !== 'string') return child;
    const segments = detectKeywords(child);
    if (segments.length === 1 && !segments[0].keyword) return child;
    return segments.map((seg, i) =>
      seg.keyword
        ? <KeywordBadge key={i} def={seg.keyword} />
        : seg.text
    );
  });
  return mapped ?? children;
}

const markdownComponents: Components = {
  p: ({ children, ...props }) => <p {...props}>{processText(children)}</p>,
  li: ({ children, ...props }) => <li {...props}>{processText(children)}</li>,
};

export function AnswerDisplay({ answer, loading, error, onRetry }: AnswerDisplayProps) {
  if (loading) return <AnswerSkeleton />;

  if (error) {
    return <ErrorDisplay error={error} onRetry={onRetry ?? (() => {})} />;
  }

  if (answer) {
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        className="prose prose-neutral max-w-none"
        components={markdownComponents}
      >
        {answer}
      </ReactMarkdown>
    );
  }

  return null;
}
