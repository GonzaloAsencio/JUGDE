jest.mock('@/store/useQueryStore', () => ({
  useQueryStore: jest.fn(),
}));

import { render, screen, fireEvent } from '@testing-library/react';
import { ChatView } from './ChatView';
import { useQueryStore } from '@/store/useQueryStore';
import type { Message } from '@/store/useQueryStore';

const mockUseQueryStore = useQueryStore as jest.Mock;

const defaultStore = {
  messages: [] as Message[],
  currentQuestion: '',
  setCurrentQuestion: jest.fn(),
  submit: jest.fn(),
  reset: jest.fn(),
};

beforeEach(() => {
  jest.clearAllMocks();
  mockUseQueryStore.mockReturnValue(defaultStore);
});

describe('ChatView', () => {
  it('renders JUDGE! watermark when there are no messages', () => {
    render(<ChatView onReset={jest.fn()} />);
    expect(screen.getByText('JUDGE!')).toBeInTheDocument();
  });

  it('does not render watermark when messages exist', () => {
    mockUseQueryStore.mockReturnValue({
      ...defaultStore,
      messages: [{
        id: '1',
        question: 'What is hunt?',
        answer: 'Hunt is a keyword.',
        citations: [],
        latencyMs: 50,
        loading: false,
        error: null,
      }] as Message[],
    });
    render(<ChatView onReset={jest.fn()} />);
    expect(screen.queryByText('JUDGE!')).toBeNull();
  });

  it('renders messages when present', () => {
    mockUseQueryStore.mockReturnValue({
      ...defaultStore,
      messages: [{
        id: '1',
        question: 'What is hunt?',
        answer: 'Hunt is a keyword.',
        citations: [],
        latencyMs: 50,
        loading: false,
        error: null,
      }] as Message[],
    });
    render(<ChatView onReset={jest.fn()} />);
    expect(screen.getByText('What is hunt?')).toBeInTheDocument();
  });

  it('calls onReset when nueva consulta is clicked', () => {
    const onReset = jest.fn();
    render(<ChatView onReset={onReset} />);
    fireEvent.click(screen.getByText(/new consultation/i));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it('renders the query input', () => {
    render(<ChatView onReset={jest.fn()} />);
    expect(screen.getByPlaceholderText(/describe the game/i)).toBeInTheDocument();
  });
});
