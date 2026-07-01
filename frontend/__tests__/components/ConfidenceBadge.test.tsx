import { render, screen } from '@testing-library/react';
import { ConfidenceBadge } from '@/components/ConfidenceBadge';

describe('ConfidenceBadge', () => {
  it('renders nothing when confidence is null', () => {
    const { container } = render(<ConfidenceBadge confidence={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders High confidence for score >= 0.75', () => {
    render(<ConfidenceBadge confidence={0.9} />);
    expect(screen.getByText(/High confidence/i)).toBeInTheDocument();
  });

  it('renders Medium confidence for mid-range score', () => {
    render(<ConfidenceBadge confidence={0.65} />);
    expect(screen.getByText(/Medium confidence/i)).toBeInTheDocument();
  });

  it('renders High confidence for an exact card match (backend score 1.0)', () => {
    render(<ConfidenceBadge confidence={1.0} />);
    expect(screen.getByText(/High confidence/i)).toBeInTheDocument();
  });
});
