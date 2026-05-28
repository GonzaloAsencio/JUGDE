'use client';

import { useEffect } from 'react';

interface JudgeIntroAnimationProps {
  onComplete: () => void;
}

export function JudgeIntroAnimation({ onComplete }: JudgeIntroAnimationProps) {
  useEffect(() => {
    const timer = setTimeout(onComplete, 1800);
    return () => clearTimeout(timer);
  }, [onComplete]);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#f6f3ee]/90 backdrop-blur-2xl">
      <div className="judge-intro-shadow">JUDGE!</div>
      <div className="judge-fullscreen-active">JUDGE!</div>
    </div>
  );
}
