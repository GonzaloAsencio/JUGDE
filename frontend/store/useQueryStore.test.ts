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
    postQuery: jest.fn(),
  };
});

import { useQueryStore } from './useQueryStore';
import { postQuery, ApiErrorInstance } from '@/lib/api';

const mockPostQuery = postQuery as jest.MockedFunction<typeof postQuery>;

beforeEach(() => {
  jest.clearAllMocks();
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
    expect(mockPostQuery).not.toHaveBeenCalled();
  });

  it('submit appends a message and clears the input', async () => {
    mockPostQuery.mockResolvedValueOnce({ answer: 'Yes.', citations: [], latency_ms: 50 });
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

  it('submit accumulates multiple messages over time', async () => {
    mockPostQuery.mockResolvedValue({ answer: 'ok', citations: [], latency_ms: 10 });
    useQueryStore.getState().setCurrentQuestion('First question?');
    await useQueryStore.getState().submit();
    useQueryStore.getState().setCurrentQuestion('Second question?');
    await useQueryStore.getState().submit();
    expect(useQueryStore.getState().messages).toHaveLength(2);
  });

  it('submit sets error on API failure', async () => {
    mockPostQuery.mockRejectedValueOnce(new (ApiErrorInstance as unknown as new (t: string, m: string) => InstanceType<typeof ApiErrorInstance>)('server', 'Server error'));
    useQueryStore.getState().setCurrentQuestion('What is the rule?');
    await useQueryStore.getState().submit();
    const msg = useQueryStore.getState().messages[0];
    expect(msg.error?.type).toBe('server');
    expect(msg.loading).toBe(false);
    expect(msg.answer).toBeNull();
  });

  it('submit sets unknown error for unexpected exceptions', async () => {
    mockPostQuery.mockRejectedValueOnce(new Error('network failure'));
    useQueryStore.getState().setCurrentQuestion('What is the rule?');
    await useQueryStore.getState().submit();
    const msg = useQueryStore.getState().messages[0];
    expect(msg.error?.type).toBe('unknown');
  });

  it('reset clears all messages and the input', async () => {
    mockPostQuery.mockResolvedValue({ answer: 'ok', citations: [], latency_ms: 10 });
    useQueryStore.getState().setCurrentQuestion('A question here?');
    await useQueryStore.getState().submit();
    useQueryStore.getState().reset();
    const { messages, currentQuestion } = useQueryStore.getState();
    expect(messages).toHaveLength(0);
    expect(currentQuestion).toBe('');
  });

  it('submit does not fire while another message is loading', async () => {
    // simulate stuck loading state
    useQueryStore.setState({
      messages: [{
        id: 'existing',
        question: 'old',
        answer: null,
        citations: [],
        latencyMs: null,
        loading: true,
        error: null,
      }],
    });
    useQueryStore.getState().setCurrentQuestion('New question?');
    await useQueryStore.getState().submit();
    expect(mockPostQuery).not.toHaveBeenCalled();
  });
});
