'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { GitBranch } from 'lucide-react';
import { cn } from '@/lib/utils';

export function Navbar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex max-w-3xl items-center justify-between px-4 sm:px-6 lg:px-8 h-14">
        <Link href="/" className="font-bold text-base tracking-tight">
          Riftbound Judge AI
        </Link>

        <nav className="flex items-center gap-4">
          <Link
            href="/"
            className={cn(
              'text-sm transition-colors hover:text-foreground',
              pathname === '/' ? 'font-semibold text-foreground' : 'text-muted-foreground'
            )}
          >
            Judge
          </Link>
          <Link
            href="/rules"
            className={cn(
              'text-sm transition-colors hover:text-foreground',
              pathname === '/rules' ? 'font-semibold text-foreground' : 'text-muted-foreground'
            )}
          >
            Rules
          </Link>
          <a
            href="https://github.com"
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground hover:text-foreground transition-colors"
            aria-label="GitHub"
          >
            <GitBranch size={18} />
          </a>
        </nav>
      </div>
    </header>
  );
}
