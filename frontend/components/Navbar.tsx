'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

export function Navbar() {
  const pathname = usePathname();
  const onRules = pathname === '/rules';

  return (
    <header
      className="sticky top-0 z-50"
      style={{
        borderBottom: '1px solid rgba(0,0,0,0.07)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        backgroundColor: 'rgba(246,243,238,0.96)',
        height: 52,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          height: '100%',
          padding: '0 28px',
        }}
      >
        {/* Left: logo → home */}
        <Link
          href="/"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            textDecoration: 'none',
          }}
        >
          {/* Icon badge */}
          <div
            style={{
              width: 30,
              height: 30,
              borderRadius: 8,
              backgroundColor: '#111111',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/ICON.png" alt="Riftbound" style={{ width: 20, height: 20, objectFit: 'contain' }} />
          </div>

          {/* Brand text */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <span
              style={{
                fontSize: 8.5,
                fontWeight: 700,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                color: '#999999',
                lineHeight: 1,
              }}
            >
              Riftbound Competitive
            </span>
            <span
              style={{
                fontSize: 13,
                fontWeight: 900,
                fontStyle: 'italic',
                color: '#111111',
                lineHeight: 1.15,
                letterSpacing: '0.01em',
              }}
            >
              Judge System
            </span>
          </div>
        </Link>

        {/* Right: page nav */}
        <nav style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          <Link
            href="/rules"
            style={{
              fontSize: 10.5,
              fontWeight: 700,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: onRules ? '#111111' : '#999999',
              textDecoration: 'none',
              transition: 'color 0.15s',
            }}
          >
            Rules
          </Link>
        </nav>
      </div>
    </header>
  );
}
