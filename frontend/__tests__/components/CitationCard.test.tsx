import { render, screen } from '@testing-library/react';
import { CitationCard } from '@/components/CitationCard';

jest.mock('@/content/sections.json', () => ({ 'Game Concepts': 'game-concepts' }), { virtual: true });

const citation = {
  section: 'Game Concepts',
  source_type: 'rulebook',
  content_preview: 'Some rules text here.',
  similarity: 0.92,
};

describe('CitationCard', () => {
  it('renders section name', () => {
    render(<CitationCard citation={citation} rank={1} />);
    expect(screen.getByText(/Game Concepts/)).toBeInTheDocument();
  });

  it('renders source_type badge', () => {
    render(<CitationCard citation={citation} rank={1} />);
    expect(screen.getByText('rulebook')).toBeInTheDocument();
  });

  it('renders content_preview', () => {
    render(<CitationCard citation={citation} rank={1} />);
    expect(screen.getByText('Some rules text here.')).toBeInTheDocument();
  });

  it('link href points to rules section', () => {
    render(<CitationCard citation={citation} rank={1} />);
    const link = screen.getByRole('link', { name: /View/i });
    expect(link).toHaveAttribute('href', '/rules#game-concepts');
  });

  it('falls back to /rules when slug is null', () => {
    const unknown = { ...citation, section: 'Unknown Section' };
    render(<CitationCard citation={unknown} rank={1} />);
    const link = screen.getByRole('link', { name: /View/i });
    expect(link).toHaveAttribute('href', '/rules');
  });
});
