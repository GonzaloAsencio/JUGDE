import { create } from 'zustand';
import { postQuery } from '@/lib/api';
import type { Citation } from '@/lib/types';

interface QueryState {
  question: string;
  answer: string | null;
  citations: Citation[];
  latencyMs: number | null;
  loading: boolean;
  error: string | null;
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
      const data = await postQuery(question.trim());
      set({ answer: data.answer, citations: data.citations, latencyMs: data.latency_ms, loading: false });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Something went wrong.';
      set({ error: msg, loading: false });
    }
  },

  reset: () => set({ question: '', answer: null, citations: [], latencyMs: null, loading: false, error: null }),
}));
