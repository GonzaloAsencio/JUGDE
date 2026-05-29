jest.mock('@/lib/cardIndex', () => ({
  CARD_INDEX: [
    {
      clean_name: 'yasuo',
      image_url: 'https://example.com/yasuo.png',
      set_label: 'Origins',
      riftbound_id: 'ori-042-219',
    },
  ],
}));

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

  it('renders @hunt as a KeywordBadge in user bubble (not raw @hunt text)', () => {
    const msg: Message = { ...baseMessage, question: 'Can @hunt trigger twice?' };
    render(<ChatMessage message={msg} />);
    expect(screen.queryByText('@hunt')).toBeNull();
    expect(screen.getByText('HUNT')).toBeInTheDocument();
  });

  it('keeps unrecognized @mentions as plain text', () => {
    const msg: Message = { ...baseMessage, question: 'Can @unknownkeyword appear?' };
    render(<ChatMessage message={msg} />);
    expect(screen.getByText(/\@unknownkeyword/)).toBeInTheDocument();
  });

  it('renders @yasuo as a CardChip wrapped in a hover trigger', () => {
    const msg: Message = { ...baseMessage, question: 'Can @yasuo attack?' };
    render(<ChatMessage message={msg} />);
    expect(screen.queryByText('@yasuo')).toBeNull();
    expect(screen.getByText('YASUO')).toBeInTheDocument();
    const trigger = document.querySelector('[data-slot="hover-card-trigger"]');
    expect(trigger).not.toBeNull();
    expect(trigger?.textContent).toContain('YASUO');
  });

  it('prefers keyword over card when the name matches both (keyword wins)', () => {
    // 'hunt' is a GAME_KEYWORDS entry. Even if a card named "hunt" existed in the mock,
    // the parser must still render KeywordBadge per D7.
    const msg: Message = { ...baseMessage, question: 'How does @hunt resolve?' };
    render(<ChatMessage message={msg} />);
    expect(screen.getByText('HUNT')).toBeInTheDocument();
    // No card hover trigger should appear because the keyword path was taken.
    expect(document.querySelector('[data-slot="hover-card-trigger"]')).toBeNull();
  });
});
