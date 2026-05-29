jest.mock('@/lib/cardIndex', () => ({
  CARD_INDEX: [
    {
      clean_name: 'yasuo',
      image_url: 'https://example.com/yasuo.png',
      set_label: 'Origins',
      riftbound_id: 'ori-042-219',
    },
    {
      clean_name: 'jhin virtuoso',
      image_url: 'https://example.com/jhin.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-181-219',
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
    // One citation -> the popover trigger reads "1 source" (singular).
    expect(screen.getByText(/source/i)).toBeInTheDocument();
  });

  it('does not show citations section when empty', () => {
    const msg: Message = { ...baseMessage, answer: 'Yes.', citations: [] };
    render(<ChatMessage message={msg} />);
    expect(screen.queryByText(/Sources/i)).toBeNull();
  });

  it('renders #hunt as a KeywordBadge in user bubble (not raw #hunt text)', () => {
    const msg: Message = { ...baseMessage, question: 'Can #hunt trigger twice?' };
    render(<ChatMessage message={msg} />);
    expect(screen.queryByText('#hunt')).toBeNull();
    expect(screen.getByText('HUNT')).toBeInTheDocument();
  });

  it('keeps unrecognized #mentions as plain text', () => {
    const msg: Message = { ...baseMessage, question: 'Can #unknownkeyword appear?' };
    render(<ChatMessage message={msg} />);
    expect(screen.getByText(/#unknownkeyword/)).toBeInTheDocument();
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

  it('renders a hyphenated slug @jhin-virtuoso showing the pretty card name', () => {
    const msg: Message = { ...baseMessage, question: 'Does @jhin-virtuoso work?' };
    render(<ChatMessage message={msg} />);
    expect(screen.queryByText('@jhin-virtuoso')).toBeNull();
    expect(screen.getByText('JHIN VIRTUOSO')).toBeInTheDocument();
  });

  it('resolves a bare prefix @jhin to the full card name (first-wins)', () => {
    const msg: Message = { ...baseMessage, question: 'Does @jhin work?' };
    render(<ChatMessage message={msg} />);
    expect(screen.getByText('JHIN VIRTUOSO')).toBeInTheDocument();
  });

  it('does not cross sigils: #yasuo (a card, not a keyword) stays plain text', () => {
    const msg: Message = { ...baseMessage, question: 'Is #yasuo strong?' };
    render(<ChatMessage message={msg} />);
    expect(screen.getByText(/#yasuo/)).toBeInTheDocument();
    expect(document.querySelector('[data-slot="hover-card-trigger"]')).toBeNull();
  });

  it('does not cross sigils: @hunt (a keyword, not a card) stays plain text', () => {
    const msg: Message = { ...baseMessage, question: 'Does @hunt resolve?' };
    render(<ChatMessage message={msg} />);
    expect(screen.getByText(/@hunt/)).toBeInTheDocument();
    expect(screen.queryByText('HUNT')).toBeNull();
  });
});
