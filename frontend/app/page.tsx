'use client';

import { useState } from 'react';
import { useQueryStore } from '@/store/useQueryStore';
import { LandingHero } from '@/components/LandingHero';
import { JudgeIntroAnimation } from '@/components/JudgeIntroAnimation';
import { ChatView } from '@/components/ChatView';

type AppState = 'landing' | 'animating' | 'chat';

export default function JudgePage() {
  const [appState, setAppState] = useState<AppState>('landing');
  const { reset } = useQueryStore();

  const handleCallJudge = () => {
    setAppState('animating');
  };

  const handleAnimationComplete = () => {
    setAppState('chat');
  };

  const handleReset = () => {
    reset();
    setAppState('landing');
  };

  return (
    <>
      {(appState === 'landing' || appState === 'animating') && (
        <LandingHero onCallJudge={handleCallJudge} />
      )}
      {appState === 'animating' && (
        <JudgeIntroAnimation onComplete={handleAnimationComplete} />
      )}
      {appState === 'chat' && (
        <ChatView onReset={handleReset} />
      )}
    </>
  );
}
