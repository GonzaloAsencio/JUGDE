'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
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

  const position = sticky ? 'sticky top-0 z-50' : 'relative z-20 flex-shrink-0';
  const bg = transparent ? '' : 'bg-brand-surface';

  return (
    <header className={`${position} ${bg} px-8 md:px-16 py-8 flex items-center justify-between`}>
      {/* Left: logo */}
      <div className="flex items-center gap-4">
        <div>
          <div className="text-2xl font-display font-black uppercase tracking-tight">Riftward</div>
          <div className="text-[10px] uppercase tracking-[0.35em] text-brand-muted-ink font-bold">Competitive Rules Judge</div>
        </div>
      </div>

      {/* Right: nav */}
      <nav className="hidden md:flex items-center gap-8 text-sm tracking-[0.18em] text-brand-muted-ink font-semibold">
        {onHomeClick ? (
          <button onClick={onHomeClick} className="hover:text-brand-accent transition-colors">Home</button>
        ) : showHomeLink ? (
          <Link href="/" className="hover:text-brand-accent transition-colors">Chat</Link>
        ) : null}
        <Link
          href="/rules"
          className={`transition-colors ${onRules ? 'text-brand-ink' : 'hover:text-brand-accent'}`}
        >
          Rules
        </Link>
        <ThemeToggle />
      </nav>
    </header>
  );
}
