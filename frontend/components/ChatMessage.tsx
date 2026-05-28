'use client';

import React from 'react';
import type { Message } from '@/store/useQueryStore';
import { AnswerDisplay } from './AnswerDisplay';
import { CitationsList } from './CitationsList';
import { ConfidenceBadge } from './ConfidenceBadge';
import { KeywordBadge } from './KeywordBadge';
import { GAME_KEYWORDS } from '@/lib/gameKeywords';

function parseQuestionWithTags(text: string): React.ReactNode[] {
  const parts = text.split(/(@[\w-]+)/g);
  return parts.map((part, i) => {
    if (!part.startsWith('@')) return part;
    const name = part.slice(1);
    const kw = GAME_KEYWORDS.find(k => k.name.toLowerCase() === name.toLowerCase());
    return kw ? <KeywordBadge key={i} def={kw} /> : part;
  });
}

interface ChatMessageProps {
  message: Message;
}

export function ChatMessage({ message }: ChatMessageProps) {
  return (
    <div className="space-y-3">
      {/* User bubble */}
      <div className="flex justify-end">
        <div className="max-w-[70%] rounded-[24px] bg-[#111111] text-white px-5 py-3 text-sm leading-relaxed">
          {parseQuestionWithTags(message.question)}
        </div>
      </div>

      {/* Judge bubble */}
      <div className="flex justify-start">
        <div className="max-w-[85%] rounded-[28px] border border-black/5 bg-white/70 backdrop-blur-xl px-6 py-5 shadow-sm">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-2 h-2 rounded-full bg-[#111111]" />
            <span className="text-[10px] uppercase tracking-[0.28em] text-[#888888] font-bold">Judge</span>
            {message.answer && <ConfidenceBadge citations={message.citations} />}
          </div>
          <AnswerDisplay
            answer={message.answer}
            loading={message.loading}
            error={message.error}
          />
          {message.answer && message.citations.length > 0 && (
            <div className="mt-4 pt-4 border-t border-black/5">
              <CitationsList citations={message.citations} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
