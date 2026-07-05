'use client';

import { useRef, useEffect } from 'react';
import { cn } from '@/lib/utils';
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
      <div className="flex flex-col h-screen bg-brand-surface page-fade-in">
        <Navbar onHomeClick={onReset} sticky={false} />
        <main id="main-content" className="flex-1 flex flex-col justify-center px-4">
          <div className="max-w-2xl mx-auto w-full flex flex-col gap-6">
            <div className="flex justify-start pointer-events-none select-none judge-welcome-bubble">
              <div className="max-w-[85%] rounded-[28px] border border-brand-muted-ink/15 bg-brand-muted-ink/5 backdrop-blur-xl px-6 py-5 shadow-sm">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-2 h-2 rounded-full bg-brand-muted-ink" />
                  <span className="text-[10px] uppercase tracking-[0.28em] text-brand-muted-ink font-bold">Judge</span>
                </div>
                <p className="text-[15px] leading-relaxed text-brand-ink">
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
            {/* Suggestion chips: kept mounted (space reserved so the centered
                layout never jumps) and cross-faded as the input fills/empties. */}
            <div
              aria-hidden={currentQuestion !== ''}
              className={cn(
                'flex flex-wrap justify-center gap-2 transition-all duration-300 ease-out',
                currentQuestion === ''
                  ? 'translate-y-0 opacity-100'
                  : 'pointer-events-none -translate-y-1 opacity-0'
              )}
            >
              {[
                { label: 'Type @ to mention a card', value: '@' },
                { label: 'Type # to tag a keyword', value: '#' },
                { label: 'What does the Hidden keyword do?', value: 'What does the Hidden keyword do?' },
              ].map(tip => (
                <button
                  key={tip.label}
                  onClick={() => setCurrentQuestion(tip.value)}
                  tabIndex={currentQuestion === '' ? undefined : -1}
                  className="text-[11px] text-brand-ink-faint px-3 py-1.5 rounded-full border border-brand-ink/10 bg-brand-card hover:text-brand-ink hover:border-brand-ink/20 transition-colors"
                >
                  {tip.label}
                </button>
              ))}
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-brand-surface page-fade-in">
      <Navbar onHomeClick={onReset} />

      {/* Screen-reader status: announces when the judge is working. */}
      <div role="status" aria-live="polite" className="sr-only">
        {isAnyLoading ? 'The judge is consulting the rules…' : ''}
      </div>

      {/* Messages */}
      <main id="main-content" className="flex-1 overflow-y-auto px-4 md:px-8 py-6">
        <div className="space-y-8 max-w-3xl mx-auto">
          {messages.map(msg => <ChatMessage key={msg.id} message={msg} />)}
        </div>
        <div ref={messagesEndRef} />
      </main>

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
