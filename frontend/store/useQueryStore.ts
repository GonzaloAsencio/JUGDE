import { create } from 'zustand';
import { ApiErrorInstance, pingHealth } from '@/lib/api';
import { postQueryStream } from '@/lib/streamQuery';
import { useUsageStore } from '@/store/useUsageStore';
import type { ApiError, Citation } from '@/lib/types';

const COLD_START_POLL_MS = 5_000;
const COLD_START_MAX_MS = 90_000;

// Pull every `@token` mention out of the raw question and resolve it to a card's
// clean_name (space-separated, e.g. "yasuo unforgiven"). The backend's tagged_lookup
// matches against the corpus section, which stores clean_name with spaces — so the
// hyphenated slug must be resolved back to the space form, not sent verbatim.
const MENTION = /@([a-z0-9-]+)/gi;
async function extractCardMentions(text: string): Promise<string[]> {
  const tokens = [...text.matchAll(MENTION)].map(([, token]) => token);
  if (tokens.length === 0) return [];
  // Lazy-load the ~196KB card index only when the question actually has
  // @mentions, keeping it out of the initial bundle (it's also code-split
  // behind the dynamically imported ChatView).
  const { lookupCard } = await import('@/lib/cardLookup');
  const names = new Set<string>();
  for (const token of tokens) {
    const card = lookupCard(token);
    if (card) names.add(card.clean_name);
  }
  return [...names].slice(0, 10); // backend validates max_length=10
}

export interface Message {
  id: string;
  question: string;
  answer: string | null;
  citations: Citation[];
  confidence: number | null;
  latencyMs: number | null;
  loading: boolean;
  error: ApiError | null;
}

interface QueryState {
  messages: Message[];
  currentQuestion: string;
  setCurrentQuestion: (q: string) => void;
  submit: () => Promise<void>;
  retry: (id: string) => Promise<void>;
  reset: () => void;
}

type SetState = (fn: (state: QueryState) => Partial<QueryState>) => void;

// Runs a query for an existing message and folds the result (or error) back into
// it. Shared by submit (first attempt) and retry (re-run after a system error),
// so both paths produce identical success/error handling.
async function runQuery(set: SetState, id: string, question: string): Promise<void> {
  // Keep any existing error set while loading, so a retry stays on the System
  // Notice ("Retrying…") instead of flashing the judge's thinking bubble. The
  // error clears only on success.
  set(state => ({
    messages: state.messages.map(m =>
      m.id === id ? { ...m, loading: true } : m
    ),
  }));

  const cardMentions = await extractCardMentions(question);
  const apiQuestion = question.replace(/@/g, '');

  const patch = (fields: Partial<Message>) => set(state => ({
    messages: state.messages.map(m => (m.id === id ? { ...m, ...fields } : m)),
  }));

  try {
    // Streaming: tokens append to the message as they arrive (the bubble
    // renders the partial answer while loading); `restart` drops the partial
    // text (empty-Answer retry / leak cut backend-side); the resolved value is
    // the canonical post-validated response and REPLACES whatever streamed.
    const data = await postQueryStream(apiQuestion, cardMentions, {
      onToken: (t) => set(state => ({
        messages: state.messages.map(m =>
          m.id === id ? { ...m, answer: (m.answer ?? '') + t } : m
        ),
      })),
      onRestart: () => patch({ answer: null }),
    });
    patch({
      answer: data.answer,
      citations: data.citations,
      confidence: data.confidence ?? null,
      latencyMs: data.latency_ms,
      loading: false,
      error: null,
    });
    // Refresh the token meter now that this answer spent quota. Fire-and-forget:
    // the badge is ambient, so a failed refresh never touches the chat flow.
    void useUsageStore.getState().refresh();
  } catch (err: unknown) {
    const error: ApiError = err instanceof ApiErrorInstance
      ? { type: err.type, message: err.message, retryAfter: err.retryAfter }
      : { type: 'unknown', message: 'Something went wrong.' };
    // answer resets to null: a partial streamed answer must not linger behind
    // the System Notice or leak into the retry's fresh stream.
    patch({ answer: null, error, loading: false });

    // timeout/network/server are exactly what a sleeping HF Space produces —
    // probe /health to tell a real cold start apart from a one-off blip.
    if (error.type === 'timeout' || error.type === 'network' || error.type === 'server') {
      void handlePossibleColdStart(set, id, question);
    }
  }
}

// Confirms a cold start via /health, switches the message to the cold-start
// notice, then polls until the Space is back and auto-retries the question —
// no manual "Try again" needed. Leaves the original error untouched if the
// health probe succeeds immediately (it wasn't a cold start).
async function handlePossibleColdStart(set: SetState, id: string, question: string): Promise<void> {
  if (await pingHealth()) return;

  set(state => ({
    messages: state.messages.map(m =>
      m.id === id
        ? { ...m, error: { type: 'cold_start', message: 'The service was asleep and is starting back up.' } }
        : m
    ),
  }));

  const deadline = Date.now() + COLD_START_MAX_MS;
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, COLD_START_POLL_MS));
    if (await pingHealth()) {
      await runQuery(set, id, question);
      return;
    }
  }
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

    const newMessage: Message = {
      id,
      question: displayQuestion,
      answer: null,
      citations: [],
      confidence: null,
      latencyMs: null,
      loading: true,
      error: null,
    };

    set(state => ({ messages: [...state.messages, newMessage], currentQuestion: '' }));
    await runQuery(set, id, displayQuestion);
  },

  // Re-run a message that failed with a system error. Uses the stored question
  // so the user doesn't have to retype it.
  retry: async (id: string) => {
    const msg = get().messages.find(m => m.id === id);
    if (!msg || msg.loading) return;
    await runQuery(set, id, msg.question);
  },

  reset: () => set({ messages: [], currentQuestion: '' }),
}));
