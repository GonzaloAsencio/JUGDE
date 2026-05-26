import { create } from 'zustand';
import { ApiErrorInstance, postQuery } from '@/lib/api';
import type { ApiError, Citation } from '@/lib/types';

interface QueryState {
  question: string;
  answer: string | null;
  citations: Citation[];
  latencyMs: number | null;
  loading: boolean;
  error: ApiError | null;
  setQuestion: (q: string) => void;
  submit: () => Promise<void>;
  reset: () => void;
}

export const useQueryStore = create<QueryState>((set, get) => ({
  question: '',
  answer: null,
  citations: [],
  latencyMs: null,
  loading: false,
  error: null,

  setQuestion: (q) => set({ question: q }),

  submit: async () => {
    const { question, loading } = get();
    if (loading || question.trim().length < 3) return;
    set({ loading: true, answer: null, citations: [], error: null, latencyMs: null });
    try {
      const data = await postQuery(question.trim().replace(/@/g, ''));
      set({ answer: data.answer, citations: data.citations, latencyMs: data.latency_ms, loading: false });
    } catch (err: unknown) {
      if (err instanceof ApiErrorInstance) {
        set({
          error: { type: err.type, message: err.message, retryAfter: err.retryAfter },
          loading: false,
        });
      } else {
        set({ error: { type: 'unknown', message: 'Something went wrong.' }, loading: false });
      }
    }
  },

  reset: () => set({ question: '', answer: null, citations: [], latencyMs: null, loading: false, error: null }),
}));
