'use client';

import { useTheme } from 'next-themes';
import { Moon, Sun } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useMounted } from '@/lib/useMounted';

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  // Avoid hydration mismatch: the theme is only known on the client.
  const mounted = useMounted();

  const isDark = resolvedTheme === 'dark';

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={mounted ? (isDark ? 'Switch to light theme' : 'Switch to dark theme') : 'Toggle theme'}
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      className="text-[var(--brand-muted-ink)]"
    >
      {/* Render a stable placeholder until mounted to keep SSR/CSR markup aligned. */}
      {mounted ? (
        isDark ? <Moon className="size-5" /> : <Sun className="size-5" />
      ) : (
        <Sun className="size-5 opacity-0" />
      )}
    </Button>
  );
}
