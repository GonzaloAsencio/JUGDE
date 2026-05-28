'use client';

import { useEffect } from 'react';

interface JudgeIntroAnimationProps {
  onComplete: () => void;
}

export function JudgeIntroAnimation({ onComplete }: JudgeIntroAnimationProps) {
  useEffect(() => {
    const timer = setTimeout(onComplete, 1100);
    return () => clearTimeout(timer);
  }, [onComplete]);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center judge-overlay">
      <span className="judge-word">JUDGE!</span>
    </div>
  );
}
