import { create } from 'zustand';
import { ApiErrorInstance, postQuery } from '@/lib/api';
import type { ApiError, Citation } from '@/lib/types';

export interface Message {
  id: string;
  question: string;
  answer: string | null;
  citations: Citation[];
  latencyMs: number | null;
  loading: boolean;
  error: ApiError | null;
}

interface QueryState {
  messages: Message[];
  currentQuestion: string;
  setCurrentQuestion: (q: string) => void;
  submit: () => Promise<void>;
  reset: () => void;
}

export const useQueryStore = create<QueryState>((set, get) => ({
  messages: [],
  currentQuestion: '',

  setCurrentQuestion: (q) => set({ currentQuestion: q }),

  submit: async () => {
    const { currentQuestion, messages } = get();
    const isAnyLoading = messages.some(m => m.loading);
    if (isAnyLoading || currentQuestion.trim().length < 3) return;

    const id = `msg-${Date.now()}-${Math.random()}`;
    const displayQuestion = currentQuestion.trim();
    const apiQuestion = displayQuestion.replace(/@/g, '');

    const newMessage: Message = {
      id,
      question: displayQuestion,
      answer: null,
      citations: [],
      latencyMs: null,
      loading: true,
      error: null,
    };

    set(state => ({ messages: [...state.messages, newMessage], currentQuestion: '' }));

    try {
      const data = await postQuery(apiQuestion);
      set(state => ({
        messages: state.messages.map(m =>
          m.id === id
            ? { ...m, answer: data.answer, citations: data.citations, latencyMs: data.latency_ms, loading: false }
            : m
        ),
      }));
    } catch (err: unknown) {
      const error: ApiError = err instanceof ApiErrorInstance
        ? { type: err.type, message: err.message, retryAfter: err.retryAfter }
        : { type: 'unknown', message: 'Something went wrong.' };
      set(state => ({
        messages: state.messages.map(m =>
          m.id === id ? { ...m, error, loading: false } : m
        ),
      }));
    }
  },

  reset: () => set({ messages: [], currentQuestion: '' }),
}));
