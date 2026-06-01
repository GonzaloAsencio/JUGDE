'use client';

import { useEffect, useState } from 'react';
import { useTheme } from 'next-themes';
import { Navbar } from './Navbar';

interface LandingHeroProps {
  onCallJudge: (x: number, y: number) => void;
  leaving?: boolean;
}

const FACTIONS = [
  {
    src: '/Body.png',
    wrapperClass: 'top-[6%]    left-[5%]   w-[190px]',
    rotate: '-14deg',
    blobColor: '#d4620a',
    blobSize: 340,
  },
  {
    src: '/Chaos.png',
    wrapperClass: 'top-[10%]   right-[7%]  w-[155px]',
    rotate: '12deg',
    blobColor: '#8b6fae',
    blobSize: 290,
  },
  {
    src: '/Fury.png',
    wrapperClass: 'top-[42%]   left-[6%]   w-[135px]',
    rotate: '-8deg',
    blobColor: '#c0392b',
    blobSize: 270,
  },
  {
    src: '/Mind.png',
    wrapperClass: 'top-[38%]   right-[6%]  w-[170px]',
    rotate: '10deg',
    blobColor: '#2e86ab',
    blobSize: 310,
  },
  {
    src: '/Calm.png',
    wrapperClass: 'bottom-[10%] left-[13%] w-[140px]',
    rotate: '7deg',
    blobColor: '#5a9e5a',
    blobSize: 270,
  },
  {
    src: '/Order.png',
    wrapperClass: 'bottom-[8%]  right-[12%] w-[158px]',
    rotate: '-11deg',
    blobColor: '#b8860b',
    blobSize: 290,
  },
];

export function LandingHero({ onCallJudge, leaving }: LandingHeroProps) {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const isDark = mounted && resolvedTheme === 'dark';

  // Dark bg needs the opposite treatment: 'multiply' + grayscale hides the icons,
  // so on dark we keep faction color, lighten via 'screen', and turn everything up.
  const glowOpacity = isDark ? 0.5 : 0.42;
  const iconStyle: React.CSSProperties = isDark
    ? { filter: 'grayscale(0) saturate(1.35) brightness(1.1)', mixBlendMode: 'screen', opacity: 0.55 }
    : { filter: 'grayscale(0.35) saturate(1.15)', mixBlendMode: 'multiply', opacity: 0.22 };

  return (
    <div className={`min-h-screen bg-brand-surface text-brand-ink overflow-hidden relative font-sans${leaving ? ' landing-fade-out' : ''}`}>
      {/* Faction icons — each with its own centered glow */}
      {FACTIONS.map(({ src, wrapperClass, rotate, blobColor, blobSize }) => (
        <div
          key={src}
          className={`absolute pointer-events-none select-none ${wrapperClass}`}
          style={{ transform: `rotate(${rotate})` }}
        >
          {/* Glow centered on this icon */}
          <div
            className="absolute rounded-full"
            style={{
              width: blobSize,
              height: blobSize,
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              background: blobColor,
              filter: 'blur(100px)',
              opacity: glowOpacity,
            }}
          />
          {/* Icon — desaturated, sits on top of its glow */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={src}
            alt=""
            aria-hidden="true"
            className="w-full relative"
            style={iconStyle}
          />
        </div>
      ))}

      {/* Header */}
      <Navbar sticky={false} transparent showHomeLink={false} />

      {/* Hero */}
      <section className="relative z-10 flex items-center justify-center px-8 md:px-16 pt-8 pb-20">
        <div className="max-w-5xl mx-auto w-full text-center flex flex-col items-center">
          <div className="mt-14 leading-none uppercase font-hero font-black">
            <div className="text-6xl md:text-8xl text-brand-ink">NEED A</div>
            <div className="text-7xl md:text-[11rem] text-brand-accent">JUDGE<span className="text-brand-ink">?</span></div>
          </div>

          <p className="mt-10 max-w-2xl text-xl leading-relaxed text-brand-ink-soft">
            Resolve complex rulings, look up competitive interactions, and get answers backed by citations from the official <strong className="font-bold text-brand-ink">Riftbound</strong> rulebook.
          </p>

          <button
            className="call-judge-btn mt-14"
            onClick={(e) => onCallJudge(e.clientX, e.clientY)}
            aria-label="Call the Judge"
          >
            <span className="cjb-content">
              <span className="cjb-text">
                <span className="cjb-label cjb-label-idle">CHAT WITH AN AI JUDGE</span>
                <span className="cjb-label cjb-label-hover">CALL THE JUDGE</span>
              </span>
            </span>
          </button>
        </div>
      </section>
    </div>
  );
}
