'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Menu, X } from 'lucide-react';
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

  const position = sticky ? 'sticky top-0 z-50' : 'relative z-20 flex-shrink-0';
  const bg = transparent ? '' : 'bg-brand-surface';

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

      {/* Mobile: dropdown panel */}
      {open && (
        <nav
          id="mobile-menu"
          data-testid="mobile-menu"
          aria-label="Mobile"
          className="md:hidden absolute top-full left-0 right-0 z-50 flex flex-col gap-1 px-8 py-4 bg-brand-surface border-t border-brand-ink/10 shadow-lg text-sm tracking-[0.18em] text-brand-muted-ink font-semibold"
        >
          {homeControl(() => setOpen(false))}
          {rulesLink(() => setOpen(false))}
          <div className="pt-1">
            <ThemeToggle />
          </div>
        </nav>
      )}
    </header>
  );
}
