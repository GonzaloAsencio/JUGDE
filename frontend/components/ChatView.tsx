'use client';

import { useRef, useEffect } from 'react';
import Link from 'next/link';
import { useQueryStore } from '@/store/useQueryStore';
import { Navbar } from './Navbar';
import { QueryInput } from './QueryInput';
import { ChatMessage } from './ChatMessage';

interface ChatViewProps {
  onReset: () => void;
}

export function ChatView({ onReset }: ChatViewProps) {
  const { messages, currentQuestion, setCurrentQuestion, submit } = useQueryStore();
  const isAnyLoading = messages.some(m => m.loading);
  const hasMessages = messages.length > 0;
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (!hasMessages) {
    return (
      <div className="flex flex-col h-screen bg-[#f6f3ee] page-fade-in">
        <header className="flex-shrink-0 px-8 md:px-16 py-8 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-[#111111] flex items-center justify-center shadow-sm p-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/Order.png" alt="Riftbound" className="w-full h-full object-contain" style={{ filter: 'brightness(0) invert(1)' }} />
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.35em] text-[#777777] font-bold">Riftbound Competitive</div>
              <div className="text-2xl font-black italic uppercase tracking-tight">Judge System</div>
            </div>
          </div>
          <nav className="hidden md:flex items-center gap-8 text-sm tracking-[0.18em] text-[#666666] font-semibold">
            <button onClick={onReset} className="hover:text-[#d4620a] transition-colors">Home</button>
            <Link href="/rules" className="hover:text-[#d4620a] transition-colors">Rules</Link>
          </nav>
        </header>
        <div className="flex-1 flex flex-col justify-center px-4">
          <div className="max-w-2xl mx-auto w-full flex flex-col gap-6">
            <div className="flex justify-start pointer-events-none select-none judge-welcome-bubble">
              <div className="max-w-[85%] rounded-[28px] border border-black/5 bg-white/70 backdrop-blur-xl px-6 py-5 shadow-sm">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-2 h-2 rounded-full bg-[#111111]" />
                  <span className="text-[10px] uppercase tracking-[0.28em] text-[#888888] font-bold">Judge</span>
                </div>
                <p className="text-[15px] leading-relaxed text-[#111111]">
                  What&apos;s your ruling question?
                </p>
              </div>
            </div>
            <div data-testid="centered-input">
              <QueryInput
                value={currentQuestion}
                onChange={setCurrentQuestion}
                onSubmit={submit}
                loading={isAnyLoading}
                placeholder="Describe the game situation..."
              />
            </div>
            {currentQuestion === '' && (
              <div className="flex flex-wrap gap-2 justify-center">
                {[
                  { label: 'Use @ to tag keywords', value: '@' },
                  { label: 'Can I chain two Quick effects?', value: 'Can I chain two Quick effects?' },
                  { label: 'What if both players trigger simultaneously?', value: 'What if both players trigger simultaneously?' },
                ].map(tip => (
                  <button
                    key={tip.label}
                    onClick={() => setCurrentQuestion(tip.value)}
                    className="text-[11px] text-[#888888] px-3 py-1.5 rounded-full border border-black/8 bg-white/50 hover:bg-white hover:text-[#111111] hover:border-black/15 transition-all"
                  >
                    {tip.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-[#f6f3ee] page-fade-in">
      <Navbar onHomeClick={onReset} />

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6">
        <div className="space-y-8 max-w-3xl mx-auto">
          {messages.map(msg => <ChatMessage key={msg.id} message={msg} />)}
        </div>
        <div ref={messagesEndRef} />
      </div>

      {/* Input footer */}
      <div className="flex-shrink-0 px-4 md:px-8 py-4">
        <div data-testid="footer-input" className="max-w-3xl mx-auto">
          <QueryInput
            value={currentQuestion}
            onChange={setCurrentQuestion}
            onSubmit={submit}
            loading={isAnyLoading}
            placeholder="Describe the game situation..."
          />
        </div>
      </div>
    </div>
  );
}
