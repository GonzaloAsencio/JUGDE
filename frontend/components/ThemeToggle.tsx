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
      className="text-[var(--brand-muted-ink)] hover:bg-transparent dark:hover:bg-transparent"
    >
      {/* Render a stable placeholder until mounted to keep SSR/CSR markup aligned. */}
      {/* transform + accent color ease together over 500ms so the sun lands on orange as it finishes rotating. */}
      {mounted ? (
        isDark ? (
          <Moon className="size-5 transition-all duration-500 ease-out group-hover/button:-rotate-12 group-hover/button:scale-110 group-hover/button:text-brand-accent" />
        ) : (
          <Sun className="size-5 transition-all duration-500 ease-out group-hover/button:rotate-90 group-hover/button:scale-110 group-hover/button:text-brand-accent" />
        )
      ) : (
        <Sun className="size-5 opacity-0" />
      )}
    </Button>
  );
}
