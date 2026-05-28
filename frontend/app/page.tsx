'use client';

import { useState } from 'react';
import { useQueryStore } from '@/store/useQueryStore';
import { LandingHero } from '@/components/LandingHero';
import { ChatView } from '@/components/ChatView';

type AppState = 'landing' | 'leaving' | 'chat';
interface PopupPos { x: number; y: number; rotation: number; }

export default function JudgePage() {
  const [appState, setAppState] = useState<AppState>('landing');
  const [popup, setPopup] = useState<PopupPos | null>(null);
  const { reset } = useQueryStore();

  const handleCallJudge = (clientX: number, clientY: number) => {
    const offsetX = (Math.random() - 0.5) * 180;
    const offsetY = -30 + (Math.random() - 0.5) * 70;
    const rotation = (Math.random() - 0.5) * 18;
    setPopup({ x: clientX + offsetX, y: clientY + offsetY, rotation });
    setAppState('leaving');
    setTimeout(() => {
      setPopup(null);
      setAppState('chat');
    }, 700);
  };

  const handleReset = () => {
    reset();
    setAppState('landing');
  };

  return (
    <>
      {(appState === 'landing' || appState === 'leaving') && (
        <LandingHero onCallJudge={handleCallJudge} leaving={appState === 'leaving'} />
      )}
      {popup && (
        <div
          className="judge-called-popup"
          style={{
            left: popup.x,
            top: popup.y,
            '--r': `${popup.rotation}deg`,
            background: '#d4620a',
            color: '#ffffff',
          } as React.CSSProperties}
        >
          JUDGE!
        </div>
      )}
      {appState === 'chat' && (
        <ChatView onReset={handleReset} />
      )}
    </>
  );
}
