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
            <div>
              <div className="text-2xl font-display font-black uppercase tracking-tight">Riftward</div>
              <div className="text-[10px] uppercase tracking-[0.35em] text-[#27484f] font-bold">Competitive Rules Judge</div>
            </div>
          </div>
          <nav className="hidden md:flex items-center gap-8 text-sm tracking-[0.18em] text-[#27484f] font-semibold">
            <button onClick={onReset} className="hover:text-[#d4620a] transition-colors">Home</button>
            <Link href="/rules" className="hover:text-[#d4620a] transition-colors">Rules</Link>
          </nav>
        </header>
        <div className="flex-1 flex flex-col justify-center px-4">
          <div className="max-w-2xl mx-auto w-full flex flex-col gap-6">
            <div className="flex justify-start pointer-events-none select-none judge-welcome-bubble">
              <div className="max-w-[85%] rounded-[28px] border border-[#27484f]/15 bg-[#27484f]/[0.05] backdrop-blur-xl px-6 py-5 shadow-sm">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-2 h-2 rounded-full bg-[#27484f]" />
                  <span className="text-[10px] uppercase tracking-[0.28em] text-[#27484f] font-bold">Judge</span>
                </div>
                <p className="text-[15px] leading-relaxed text-[#111111]">
                  Hey! What ruling can I help you sort out?
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
                  { label: 'Type @ to mention a card', value: '@' },
                  { label: 'Type # to tag a keyword', value: '#' },
                  { label: 'Try: "what does hidden do?"', value: 'What does hidden do?' },
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
