'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

export function Navbar() {
  const pathname = usePathname();
  const onRules = pathname === '/rules';

  return (
    <header className="sticky top-0 z-50 px-8 md:px-16 py-8 flex items-center justify-between bg-[#f6f3ee]">
      {/* Left: logo */}
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-2xl bg-[#111111] flex items-center justify-center shadow-sm p-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/Order.png"
            alt="Riftbound"
            className="w-full h-full object-contain"
            style={{ filter: 'brightness(0) invert(1)' }}
          />
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.35em] text-[#777777] font-bold">Riftbound Competitive</div>
          <div className="text-2xl font-black italic uppercase tracking-tight">Judge System</div>
        </div>
      </div>

      {/* Right: nav */}
      <nav className="hidden md:flex items-center gap-8 text-sm tracking-[0.18em] text-[#666666] font-semibold">
        <Link href="/" className="hover:text-[#d4620a] transition-colors">Chat</Link>
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
