'use client';

import { useRef, useEffect } from 'react';
import { useQueryStore } from '@/store/useQueryStore';
import { QueryInput } from './QueryInput';
import { ChatMessage } from './ChatMessage';

interface ChatViewProps {
  onReset: () => void;
}

export function ChatView({ onReset }: ChatViewProps) {
  const { messages, currentQuestion, setCurrentQuestion, submit } = useQueryStore();
  const isAnyLoading = messages.some(m => m.loading);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="flex flex-col h-screen bg-[#f6f3ee]">
      {/* Top bar */}
      <header className="flex-shrink-0 px-6 py-4 border-b border-black/5 bg-white/60 backdrop-blur-xl flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-[#111111] flex items-center justify-center p-1.5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/Order.png"
              alt="Riftbound"
              className="w-full h-full object-contain"
              style={{ filter: 'brightness(0) invert(1)' }}
            />
          </div>
          <div>
            <div className="text-[9px] uppercase tracking-[0.35em] text-[#777777] font-bold">Riftbound</div>
            <div className="text-sm font-black italic uppercase tracking-tight">Judge</div>
          </div>
        </div>
        <button
          onClick={onReset}
          className="text-[11px] uppercase tracking-[0.22em] text-[#666666] font-bold hover:text-black transition-colors px-4 py-2 rounded-full border border-black/10 hover:border-black/20"
        >
          New consultation
        </button>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full pointer-events-none">
            <div className="text-[100px] md:text-[180px] font-black italic uppercase text-[#111111] opacity-[0.04] select-none leading-none">
              JUDGE!
            </div>
          </div>
        ) : (
          <div className="space-y-8 max-w-3xl mx-auto">
            {messages.map(msg => <ChatMessage key={msg.id} message={msg} />)}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input bar */}
      <div className="flex-shrink-0 border-t border-black/5 bg-white/60 backdrop-blur-xl px-4 md:px-8 py-4">
        <div className="max-w-3xl mx-auto">
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
