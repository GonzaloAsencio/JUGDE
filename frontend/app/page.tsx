'use client';

import { useQueryStore } from '@/store/useQueryStore';
import { QueryInput } from '@/components/QueryInput';
import { AnswerDisplay } from '@/components/AnswerDisplay';
import { CitationsList } from '@/components/CitationsList';
import { ConfidenceBadge } from '@/components/ConfidenceBadge';
import { ExampleQueries } from '@/components/ExampleQueries';

const EXAMPLES = [
  'Can I attack with a unit the same turn it entered play?',
  'How does Hunt resolve if the defending unit is destroyed before it deals damage?',
  'What happens if both players try to activate effects at the same time?',
];

export default function JudgePage() {
  const { question, answer, citations, loading, error, setQuestion, submit, reset } = useQueryStore();

  const handleSelect = (q: string) => {
    setQuestion(q);
    // trigger submit after state settles
    setTimeout(() => useQueryStore.getState().submit(), 0);
  };

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Ask the Judge</h1>
        <p className="text-sm text-muted-foreground">
          Rules questions answered with citations from the official corpus.
        </p>
      </div>

      <QueryInput
        value={question}
        onChange={setQuestion}
        onSubmit={submit}
        loading={loading}
        placeholder="E.g. Can I block with a tapped unit?"
      />

      <ExampleQueries examples={EXAMPLES} onSelect={handleSelect} disabled={!!answer || loading} />

      {(loading || answer || error) && (
        <div className="space-y-4">
          <AnswerDisplay answer={answer} loading={loading} error={error} onRetry={submit} />
          {answer && <ConfidenceBadge citations={citations} />}
          {answer && <CitationsList citations={citations} />}
        </div>
      )}
    </div>
  );
}
