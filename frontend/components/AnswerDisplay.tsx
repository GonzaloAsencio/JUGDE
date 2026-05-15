import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AnswerSkeleton } from '@/components/AnswerSkeleton';

interface AnswerDisplayProps {
  answer: string | null;
  loading: boolean;
  error: string | null;
}

export function AnswerDisplay({ answer, loading, error }: AnswerDisplayProps) {
  if (loading) return <AnswerSkeleton />;

  if (error) {
    return (
      <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-destructive text-sm">
        {error}
      </div>
    );
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
