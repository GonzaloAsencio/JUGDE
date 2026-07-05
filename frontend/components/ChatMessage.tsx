'use client';

import React from 'react';
import { useQueryStore, type Message } from '@/store/useQueryStore';
import { AnswerDisplay } from './AnswerDisplay';
import { SystemNotice } from './SystemNotice';
import { SourcesPopover } from './SourcesPopover';
import { ConfidenceBadge } from './ConfidenceBadge';
import { KeywordBadge } from './KeywordBadge';
import { CardChip } from './CardChip';
import { CardPreview } from './CardPreview';
import { GAME_KEYWORDS } from '@/lib/gameKeywords';
import { lookupCard } from '@/lib/cardLookup';

function parseQuestionWithTags(text: string): React.ReactNode[] {
  // Two sigils, no ambiguity: #term -> keyword, @entity -> card.
  const parts = text.split(/(#[\w-]+|@[\w-]+)/g);
  return parts.map((part, i) => {
    if (part.startsWith('#')) {
      const name = part.slice(1);
      const kw = GAME_KEYWORDS.find(k => k.name.toLowerCase() === name.toLowerCase());
      return kw ? <KeywordBadge key={i} def={kw} /> : part;
    }
    if (part.startsWith('@')) {
      const card = lookupCard(part.slice(1));
      if (card) {
        return (
          <CardPreview key={i} cardName={card.clean_name}>
            <CardChip name={card.clean_name} />
          </CardPreview>
        );
      }
    }
    return part;
  });
}

interface ChatMessageProps {
  message: Message;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const retry = useQueryStore((s) => s.retry);

  return (
    <div className="space-y-3">
      {/* User bubble */}
      <div className="flex justify-end">
        <div className="max-w-[70%] rounded-[24px] bg-brand-ink text-brand-surface px-5 py-3 text-sm leading-relaxed">
          {parseQuestionWithTags(message.question)}
        </div>
      </div>

      {/* A system fault is not a ruling — surface it as a notice, never as the
          judge answering. Otherwise render the judge bubble as usual. */}
      {message.error ? (
        <SystemNotice error={message.error} onRetry={() => retry(message.id)} retrying={message.loading} />
      ) : (
        <div className="flex justify-start">
          <div className="max-w-[85%] rounded-[28px] border border-brand-muted-ink/15 bg-brand-muted-ink/5 backdrop-blur-xl px-6 py-5 shadow-sm">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-2 h-2 rounded-full bg-brand-muted-ink" />
              <span className="text-[10px] uppercase tracking-[0.28em] text-brand-muted-ink font-bold">Judge</span>
              {message.answer && <ConfidenceBadge confidence={message.confidence} />}
            </div>
            <AnswerDisplay
              answer={message.answer}
              loading={message.loading}
            />
            {message.answer && message.citations.length > 0 && (
              <div className="flex justify-end mt-3">
                <SourcesPopover citations={message.citations} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
