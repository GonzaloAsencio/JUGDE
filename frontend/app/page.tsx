'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import { useQueryStore } from '@/store/useQueryStore';
import { LandingHero } from '@/components/LandingHero';

// Chat (and its heavy deps: the card index, markdown, card detection) only
// mount after "Call Judge", so code-split it out of the initial landing bundle.
const ChatView = dynamic(() => import('@/components/ChatView').then(m => m.ChatView));

type AppState = 'landing' | 'chat';
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
    setTimeout(() => {
      setPopup(null);
      setAppState('chat');
    }, 850);
  };

  const handleReset = () => {
    reset();
    setAppState('landing');
  };

  return (
    <>
      {appState === 'landing' && (
        <LandingHero onCallJudge={handleCallJudge} />
      )}
      {popup && (
        <div
          className="judge-called-popup"
          style={{
            left: popup.x,
            top: popup.y,
            '--r': `${popup.rotation}deg`,
            background: 'var(--brand-accent)',
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
