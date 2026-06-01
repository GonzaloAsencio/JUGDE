'use client';

import { useEffect, useState } from 'react';
import { useTheme } from 'next-themes';
import { Moon, Sun } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Avoid hydration mismatch: the theme is only known on the client.
  useEffect(() => setMounted(true), []);

  const isDark = resolvedTheme === 'dark';

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
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
