import { render, screen } from '@testing-library/react';
import { ChatMessage } from './ChatMessage';
import type { Message } from '@/store/useQueryStore';

const baseMessage: Message = {
  id: 'test-1',
  question: 'Can I attack with a tapped unit?',
  answer: null,
  citations: [],
  latencyMs: null,
  loading: false,
  error: null,
};

describe('ChatMessage', () => {
  it('renders the user question', () => {
    render(<ChatMessage message={baseMessage} />);
    expect(screen.getByText('Can I attack with a tapped unit?')).toBeInTheDocument();
  });

  it('renders judge answer when available', () => {
    const msg: Message = { ...baseMessage, answer: 'No, tapped units cannot attack.' };
    render(<ChatMessage message={msg} />);
    expect(screen.getByText(/tapped units cannot attack/)).toBeInTheDocument();
  });

  it('renders loading skeleton when loading is true', () => {
    const msg: Message = { ...baseMessage, loading: true };
    const { container } = render(<ChatMessage message={msg} />);
    expect(container.firstChild).toBeTruthy();
  });

  it('shows the Judge label', () => {
    render(<ChatMessage message={baseMessage} />);
    expect(screen.getByText('Judge')).toBeInTheDocument();
  });

  it('shows citations section when answer and citations exist', () => {
    const msg: Message = {
      ...baseMessage,
      answer: 'Yes.',
      citations: [{
        section: '4.1',
        source_type: 'rule',
        content_preview: 'Units may attack...',
        similarity: 0.9,
      }],
    };
    render(<ChatMessage message={msg} />);
    expect(screen.getByText(/Sources/i)).toBeInTheDocument();
  });

  it('does not show citations section when empty', () => {
    const msg: Message = { ...baseMessage, answer: 'Yes.', citations: [] };
    render(<ChatMessage message={msg} />);
    expect(screen.queryByText(/Sources/i)).toBeNull();
  });
});
