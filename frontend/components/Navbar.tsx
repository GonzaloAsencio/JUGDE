'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

interface NavbarProps {
  onHomeClick?: () => void;
}

export function Navbar({ onHomeClick }: NavbarProps) {
  const pathname = usePathname();
  const onRules = pathname === '/rules';

  return (
    <header className="sticky top-0 z-50 px-8 md:px-16 py-8 flex items-center justify-between bg-[#f6f3ee]">
      {/* Left: logo */}
      <div className="flex items-center gap-4">
        <div>
          <div className="text-2xl font-display font-black uppercase tracking-tight">Riftward</div>
          <div className="text-[10px] uppercase tracking-[0.35em] text-[#777777] font-bold">Competitive Rules Judge</div>
        </div>
      </div>

      {/* Right: nav */}
      <nav className="hidden md:flex items-center gap-8 text-sm tracking-[0.18em] text-[#666666] font-semibold">
        {onHomeClick ? (
          <button onClick={onHomeClick} className="hover:text-[#d4620a] transition-colors">Home</button>
        ) : (
          <Link href="/" className="hover:text-[#d4620a] transition-colors">Chat</Link>
        )}
        <Link
          href="/rules"
          className={`transition-colors ${onRules ? 'text-black' : 'hover:text-[#d4620a]'}`}
        >
          Rules
        </Link>
      </nav>
    </header>
  );
}
