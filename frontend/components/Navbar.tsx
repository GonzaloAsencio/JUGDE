'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ArrowUpRight, Menu, X } from 'lucide-react';
import { ThemeToggle } from './ThemeToggle';

interface NavbarProps {
  /** When provided, the home control is a button (e.g. reset chat) instead of a link. */
  onHomeClick?: () => void;
  /** Sticky at the top (default). Set false for in-flow headers (landing, empty chat). */
  sticky?: boolean;
  /** Transparent background — used over the landing hero. Default uses the page surface. */
  transparent?: boolean;
  /** Show the home/chat control on the left of the nav. Landing hides it (you're already home). */
  showHomeLink?: boolean;
}

export function Navbar({
  onHomeClick,
  sticky = true,
  transparent = false,
  showHomeLink = true,
}: NavbarProps) {
  const pathname = usePathname();
  const onRules = pathname === '/rules';
  const [open, setOpen] = useState(false);

  // z-50 (even in-flow) so the logo + toggle always float above the full-screen
  // mobile overlay (z-40), which otherwise sits in its own stacking context.
  const position = sticky ? 'sticky top-0 z-50' : 'relative z-50 flex-shrink-0';
  const bg = transparent ? '' : 'bg-brand-surface';

  // While the full-screen menu is open: lock body scroll and close on Escape.
  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener('keydown', onKey);
    };
  }, [open]);

  // Shared links so the desktop bar and the mobile panel never diverge.
  // `onNavigate` lets the mobile panel close itself on selection.
  const homeControl = (onNavigate?: () => void) =>
    onHomeClick ? (
      <button
        onClick={() => { onHomeClick(); onNavigate?.(); }}
        className="hover:text-brand-accent transition-colors"
      >
        Home
      </button>
    ) : showHomeLink ? (
      <Link href="/" onClick={onNavigate} className="hover:text-brand-accent transition-colors">
        Chat
      </Link>
    ) : null;

  const rulesLink = (onNavigate?: () => void) => (
    <Link
      href="/rules"
      onClick={onNavigate}
      className={`transition-colors ${onRules ? 'text-brand-ink' : 'hover:text-brand-accent'}`}
    >
      Rules
    </Link>
  );

  return (
    <header className={`${position} ${bg} px-8 md:px-16 py-8 flex items-center justify-between`}>
      {/* Left: logo */}
      <div className="flex items-center gap-4">
        <div>
          <div className="text-2xl font-display font-black uppercase tracking-tight">Riftward</div>
          <div className="text-[10px] uppercase tracking-[0.35em] text-brand-muted-ink font-bold">Competitive Rules Judge</div>
        </div>
      </div>

      {/* Right: desktop nav */}
      <nav
        aria-label="Primary"
        className="hidden md:flex items-center gap-8 text-sm tracking-[0.18em] text-brand-muted-ink font-semibold"
      >
        {homeControl()}
        {rulesLink()}
        <ThemeToggle />
      </nav>

      {/* Mobile: hamburger toggle (44px touch target) */}
      <button
        type="button"
        aria-label={open ? 'Close menu' : 'Open menu'}
        aria-expanded={open}
        aria-controls="mobile-menu"
        onClick={() => setOpen(o => !o)}
        className="md:hidden flex items-center justify-center size-11 -mr-2 rounded-md text-brand-muted-ink hover:text-brand-accent transition-colors"
      >
        {open ? <X className="size-6" /> : <Menu className="size-6" />}
      </button>

      {/* Mobile: full-screen overlay menu */}
      {open && (
        <nav
          id="mobile-menu"
          data-testid="mobile-menu"
          aria-label="Mobile"
          className="md:hidden fixed inset-0 z-40 flex flex-col overflow-y-auto bg-brand-surface px-8 pt-28 pb-10 animate-in fade-in duration-200 ease-out"
        >
          <div className="flex flex-col">
            {onHomeClick ? (
              <button
                onClick={() => { onHomeClick(); setOpen(false); }}
                style={{ animationDelay: '60ms' }}
                className="group flex items-center justify-between border-b border-brand-ink/10 py-6 text-left font-display text-3xl font-bold tracking-tight text-brand-ink transition-colors hover:text-brand-accent animate-in fade-in slide-in-from-right-6 fill-mode-both"
              >
                <span>Home</span>
                <ArrowUpRight className="size-6 -translate-x-2 opacity-0 transition-all duration-200 group-hover:translate-x-0 group-hover:opacity-100" />
              </button>
            ) : showHomeLink ? (
              <Link
                href="/"
                onClick={() => setOpen(false)}
                style={{ animationDelay: '60ms' }}
                className="group flex items-center justify-between border-b border-brand-ink/10 py-6 font-display text-3xl font-bold tracking-tight text-brand-ink transition-colors hover:text-brand-accent animate-in fade-in slide-in-from-right-6 fill-mode-both"
              >
                <span>Chat</span>
                <ArrowUpRight className="size-6 -translate-x-2 opacity-0 transition-all duration-200 group-hover:translate-x-0 group-hover:opacity-100" />
              </Link>
            ) : null}

            <Link
              href="/rules"
              onClick={() => setOpen(false)}
              aria-current={onRules ? 'page' : undefined}
              style={{ animationDelay: '120ms' }}
              className={`group flex items-center justify-between border-b border-brand-ink/10 py-6 font-display text-3xl font-bold tracking-tight transition-colors animate-in fade-in slide-in-from-right-6 fill-mode-both ${
                onRules ? 'text-brand-accent' : 'text-brand-ink hover:text-brand-accent'
              }`}
            >
              <span>Rules</span>
              {onRules ? (
                <span className="size-2.5 rounded-full bg-brand-accent" aria-hidden />
              ) : (
                <ArrowUpRight className="size-6 -translate-x-2 opacity-0 transition-all duration-200 group-hover:translate-x-0 group-hover:opacity-100" />
              )}
            </Link>
          </div>

          {/* Appearance — theme toggle anchored to the bottom of the sheet */}
          <div
            style={{ animationDelay: '180ms' }}
            className="mt-auto flex items-center justify-between pt-10 animate-in fade-in fill-mode-both"
          >
            <span className="text-[11px] font-bold uppercase tracking-[0.28em] text-brand-muted-ink">
              Appearance
            </span>
            <ThemeToggle />
          </div>
        </nav>
      )}
    </header>
  );
}
