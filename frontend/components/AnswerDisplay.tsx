import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AnswerSkeleton } from '@/components/AnswerSkeleton';
import { ErrorDisplay } from '@/components/ErrorDisplay';
import type { ApiError } from '@/lib/types';

interface AnswerDisplayProps {
  answer: string | null;
  loading: boolean;
  error: ApiError | null;
  onRetry?: () => void;
}

export function AnswerDisplay({ answer, loading, error, onRetry }: AnswerDisplayProps) {
  if (loading) return <AnswerSkeleton />;

  if (error) {
    return <ErrorDisplay error={error} onRetry={onRetry ?? (() => {})} />;
  }

  if (answer) {
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]} className="prose prose-neutral max-w-none">
        {answer}
      </ReactMarkdown>
    );
  }

  return null;
}
