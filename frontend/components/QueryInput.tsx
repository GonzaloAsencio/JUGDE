import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface QueryInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  loading: boolean;
  placeholder?: string;
}

export function QueryInput({ value, onChange, onSubmit, loading, placeholder }: QueryInputProps) {
  const trimmed = value.trim();
  const isValid = trimmed.length >= 3 && trimmed.length <= 1000;

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!loading && isValid) onSubmit();
    }
  }

  return (
    <div className="flex gap-2 w-full">
      <Input
        value={value}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={loading}
        placeholder={placeholder}
        className="flex-1"
      />
      <Button
        onClick={onSubmit}
        disabled={loading || !isValid}
      >
        {loading ? <Loader2 className="animate-spin" /> : 'Ask Judge'}
      </Button>
    </div>
  );
}
