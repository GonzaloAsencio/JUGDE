import { Button } from '@/components/ui/button';

interface ExampleQueriesProps {
  examples: string[];
  onSelect: (q: string) => void;
  disabled: boolean;
}

export function ExampleQueries({ examples, onSelect, disabled }: ExampleQueriesProps) {
  if (disabled) return null;

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">💡 Try these:</p>
      <div className="flex flex-wrap gap-2">
        {examples.map((q) => (
          <Button
            key={q}
            variant="outline"
            size="sm"
            onClick={() => onSelect(q)}
          >
            {q}
          </Button>
        ))}
      </div>
    </div>
  );
}
