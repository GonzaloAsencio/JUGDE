'use client';

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
  return (
    <div className={`min-h-screen bg-[#f6f3ee] text-[#111111] overflow-hidden relative font-sans${leaving ? ' landing-fade-out' : ''}`}>
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
              opacity: 0.28,
            }}
          />
          {/* Icon — desaturated, sits on top of its glow */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={src}
            alt=""
            aria-hidden="true"
            className="w-full relative"
            style={{
              filter: 'grayscale(1)',
              mixBlendMode: 'multiply',
              opacity: 0.12,
            }}
          />
        </div>
      ))}

      {/* Header */}
      <header className="relative z-20 px-8 md:px-16 py-8 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div>
            <div className="text-2xl font-display font-black uppercase tracking-tight">
              Riftward
            </div>
            <div className="text-[10px] uppercase tracking-[0.35em] text-[#27484f] font-bold">
              Competitive Rules Judge
            </div>
          </div>
        </div>
        <nav className="hidden md:flex items-center gap-8 text-sm tracking-[0.18em] text-[#27484f] font-semibold">
          <a href="/rules" className="hover:text-[#d4620a] transition-colors">Rules</a>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative z-10 flex items-center justify-center px-8 md:px-16 pt-8 pb-20">
        <div className="max-w-5xl mx-auto w-full text-center flex flex-col items-center">
          <div className="mt-14 leading-none uppercase font-display font-black">
            <div className="text-6xl md:text-8xl text-[#111111]">NEED A</div>
            <div className="text-7xl md:text-[11rem] text-[#d4620a]">JUDGE<span className="text-[#111111]">?</span></div>
          </div>

          <p className="mt-10 max-w-2xl text-xl leading-relaxed text-[#555555]">
            Resolve complex rulings, look up competitive interactions, and get answers backed by citations from the official <strong className="font-bold text-[#111111]">Riftbound</strong> rulebook.
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
