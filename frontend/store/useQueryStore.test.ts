jest.mock('@/lib/api', () => {
  class MockApiErrorInstance extends Error {
    type: string;
    retryAfter?: number;
    constructor(type: string, message: string, retryAfter?: number) {
      super(message);
      this.type = type;
      this.retryAfter = retryAfter;
    }
  }
  return {
    ApiErrorInstance: MockApiErrorInstance,
    pingHealth: jest.fn().mockResolvedValue(true),
  };
});

jest.mock('@/lib/streamQuery', () => ({
  postQueryStream: jest.fn(),
}));

import { useQueryStore } from './useQueryStore';
import { ApiErrorInstance, pingHealth } from '@/lib/api';
import { postQueryStream } from '@/lib/streamQuery';

const mockPostQueryStream = postQueryStream as jest.MockedFunction<typeof postQueryStream>;
const mockPingHealth = pingHealth as jest.MockedFunction<typeof pingHealth>;

const makeApiError = (type: string, message: string) =>
  new (ApiErrorInstance as unknown as new (t: string, m: string) => InstanceType<typeof ApiErrorInstance>)(type, message);

beforeEach(() => {
  jest.clearAllMocks();
  mockPingHealth.mockResolvedValue(true);
  useQueryStore.setState({ messages: [], currentQuestion: '' });
});

describe('useQueryStore', () => {
  it('starts with empty messages and empty question', () => {
    const { messages, currentQuestion } = useQueryStore.getState();
    expect(messages).toEqual([]);
    expect(currentQuestion).toBe('');
  });

  it('setCurrentQuestion updates the input field', () => {
    useQueryStore.getState().setCurrentQuestion('What is priority?');
    expect(useQueryStore.getState().currentQuestion).toBe('What is priority?');
  });

  it('submit does nothing if question is too short', async () => {
    useQueryStore.getState().setCurrentQuestion('hi');
    await useQueryStore.getState().submit();
    expect(useQueryStore.getState().messages).toHaveLength(0);
    expect(mockPostQueryStream).not.toHaveBeenCalled();
  });

  it('submit appends a message and clears the input', async () => {
    mockPostQueryStream.mockResolvedValueOnce({ answer: 'Yes.', citations: [], latency_ms: 50 });
    useQueryStore.getState().setCurrentQuestion('Can I attack?');
    await useQueryStore.getState().submit();
    const { messages, currentQuestion } = useQueryStore.getState();
    expect(messages).toHaveLength(1);
    expect(messages[0].question).toBe('Can I attack?');
    expect(messages[0].answer).toBe('Yes.');
    expect(messages[0].loading).toBe(false);
    expect(messages[0].error).toBeNull();
    expect(currentQuestion).toBe('');
  });

  it('appends tokens to the message while streaming and replaces with the final answer', async () => {
    mockPostQueryStream.mockImplementationOnce(async (_q, _m, handlers) => {
      handlers.onToken('Reason');
      expect(useQueryStore.getState().messages[0].answer).toBe('Reason');
      expect(useQueryStore.getState().messages[0].loading).toBe(true);
      handlers.onToken('ing [#1]');
      expect(useQueryStore.getState().messages[0].answer).toBe('Reasoning [#1]');
      // The final canonical answer differs from the streamed text (citation
      // markers stripped backend-side) and must REPLACE it, not append.
      return { answer: 'Reasoning', citations: [], latency_ms: 5 };
    });
    useQueryStore.getState().setCurrentQuestion('Can I attack?');
    await useQueryStore.getState().submit();

    expect(useQueryStore.getState().messages[0].answer).toBe('Reasoning');
  });

  it('restart drops the partial answer', async () => {
    mockPostQueryStream.mockImplementationOnce(async (_q, _m, handlers) => {
      handlers.onToken('half an answ');
      handlers.onRestart();
      expect(useQueryStore.getState().messages[0].answer).toBeNull();
      handlers.onToken('Fresh');
      return { answer: 'Fresh.', citations: [], latency_ms: 5 };
    });
    useQueryStore.getState().setCurrentQuestion('Can I attack?');
    await useQueryStore.getState().submit();

    expect(useQueryStore.getState().messages[0].answer).toBe('Fresh.');
  });

  it('a stream error clears the partial answer so it cannot linger behind the notice', async () => {
    mockPostQueryStream.mockImplementationOnce(async (_q, _m, handlers) => {
      handlers.onToken('partial text');
      throw makeApiError('server', 'boom');
    });
    useQueryStore.getState().setCurrentQuestion('What is the rule?');
    await useQueryStore.getState().submit();

    const msg = useQueryStore.getState().messages[0];
    expect(msg.error?.type).toBe('server');
    expect(msg.answer).toBeNull();
  });

  it('submit strips @ from the API question but extracts card_mentions as clean_names', async () => {
    mockPostQueryStream.mockResolvedValueOnce({ answer: 'ok', citations: [], latency_ms: 10 });
    useQueryStore.getState().setCurrentQuestion('explain @yasuo-unforgiven please');
    await useQueryStore.getState().submit();
    expect(mockPostQueryStream).toHaveBeenCalledWith(
      'explain yasuo-unforgiven please', ['yasuo unforgiven'], expect.anything(),
    );
  });

  it('submit passes empty card_mentions when there are no @ mentions', async () => {
    mockPostQueryStream.mockResolvedValueOnce({ answer: 'ok', citations: [], latency_ms: 10 });
    useQueryStore.getState().setCurrentQuestion('what is priority?');
    await useQueryStore.getState().submit();
    expect(mockPostQueryStream).toHaveBeenCalledWith('what is priority?', [], expect.anything());
  });

  it('submit dedupes repeated mentions of the same card', async () => {
    mockPostQueryStream.mockResolvedValueOnce({ answer: 'ok', citations: [], latency_ms: 10 });
    useQueryStore.getState().setCurrentQuestion('@yasuo-unforgiven vs @yasuo-unforgiven?');
    await useQueryStore.getState().submit();
    expect(mockPostQueryStream).toHaveBeenCalledWith(
      'yasuo-unforgiven vs yasuo-unforgiven?', ['yasuo unforgiven'], expect.anything(),
    );
  });

  it('submit accumulates multiple messages over time', async () => {
    mockPostQueryStream.mockResolvedValue({ answer: 'ok', citations: [], latency_ms: 10 });
    useQueryStore.getState().setCurrentQuestion('First question?');
    await useQueryStore.getState().submit();
    useQueryStore.getState().setCurrentQuestion('Second question?');
    await useQueryStore.getState().submit();
    expect(useQueryStore.getState().messages).toHaveLength(2);
  });

  it('submit sets error on API failure', async () => {
    mockPostQueryStream.mockRejectedValueOnce(makeApiError('server', 'Server error'));
    useQueryStore.getState().setCurrentQuestion('What is the rule?');
    await useQueryStore.getState().submit();
    const msg = useQueryStore.getState().messages[0];
    expect(msg.error?.type).toBe('server');
    expect(msg.loading).toBe(false);
    expect(msg.answer).toBeNull();
  });

  it('submit sets unknown error for unexpected exceptions', async () => {
    mockPostQueryStream.mockRejectedValueOnce(new Error('network failure'));
    useQueryStore.getState().setCurrentQuestion('What is the rule?');
    await useQueryStore.getState().submit();
    const msg = useQueryStore.getState().messages[0];
    expect(msg.error?.type).toBe('unknown');
  });

  it('reset clears all messages and the input', async () => {
    mockPostQueryStream.mockResolvedValue({ answer: 'ok', citations: [], latency_ms: 10 });
    useQueryStore.getState().setCurrentQuestion('A question here?');
    await useQueryStore.getState().submit();
    useQueryStore.getState().reset();
    const { messages, currentQuestion } = useQueryStore.getState();
    expect(messages).toHaveLength(0);
    expect(currentQuestion).toBe('');
  });

  it('retry re-runs a failed message and clears its error on success', async () => {
    mockPostQueryStream.mockRejectedValueOnce(makeApiError('timeout', 'timed out'));
    useQueryStore.getState().setCurrentQuestion('Does @yasuo-unforgiven attack?');
    await useQueryStore.getState().submit();
    const id = useQueryStore.getState().messages[0].id;
    expect(useQueryStore.getState().messages[0].error?.type).toBe('timeout');

    mockPostQueryStream.mockResolvedValueOnce({ answer: 'Yes.', citations: [], latency_ms: 20 });
    await useQueryStore.getState().retry(id);

    const msg = useQueryStore.getState().messages[0];
    expect(msg.error).toBeNull();
    expect(msg.answer).toBe('Yes.');
    // reuses the stored question (with @ stripped for the API)
    expect(mockPostQueryStream).toHaveBeenLastCalledWith(
      'Does yasuo-unforgiven attack?', ['yasuo unforgiven'], expect.anything(),
    );
    // still a single message — retry mutates in place, never appends
    expect(useQueryStore.getState().messages).toHaveLength(1);
  });

  it('turns a system error into a cold-start notice, then auto-retries once /health confirms the Space is back', async () => {
    jest.useFakeTimers();
    try {
      mockPostQueryStream.mockRejectedValueOnce(makeApiError('server', 'down'));
      mockPingHealth.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
      mockPostQueryStream.mockResolvedValueOnce({ answer: 'Awake.', citations: [], latency_ms: 5 });

      useQueryStore.getState().setCurrentQuestion('Still there?');
      await useQueryStore.getState().submit();

      // flush the initial (non-timer) health probe fired after the failed request
      await Promise.resolve();
      await Promise.resolve();
      expect(useQueryStore.getState().messages[0].error?.type).toBe('cold_start');

      await jest.advanceTimersByTimeAsync(5_000);

      const msg = useQueryStore.getState().messages[0];
      expect(msg.error).toBeNull();
      expect(msg.answer).toBe('Awake.');
    } finally {
      jest.useRealTimers();
    }
  });

  it('leaves a transient error as-is when /health responds immediately (not a real cold start)', async () => {
    mockPostQueryStream.mockRejectedValueOnce(makeApiError('timeout', 'timed out'));
    mockPingHealth.mockResolvedValueOnce(true);

    useQueryStore.getState().setCurrentQuestion('One more thing?');
    await useQueryStore.getState().submit();
    await Promise.resolve();
    await Promise.resolve();

    expect(useQueryStore.getState().messages[0].error?.type).toBe('timeout');
  });

  it('submit does not fire while another message is loading', async () => {
    // simulate stuck loading state
    useQueryStore.setState({
      messages: [{
        id: 'existing',
        question: 'old',
        answer: null,
        citations: [],
        confidence: null,
        latencyMs: null,
        loading: true,
        error: null,
      }],
    });
    useQueryStore.getState().setCurrentQuestion('New question?');
    await useQueryStore.getState().submit();
    expect(mockPostQueryStream).not.toHaveBeenCalled();
  });
});
