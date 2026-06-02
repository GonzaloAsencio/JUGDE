import { render, screen } from '@testing-library/react';
import { ConfidenceBadge } from '@/components/ConfidenceBadge';
import type { Citation } from '@/lib/types';

// Only `.similarity` drives the badge; build full citations to stay typed.
const cite = (similarity: number): Citation => ({
  section: '',
  source_type: '',
  content_preview: '',
  similarity,
});

describe('ConfidenceBadge', () => {
  it('renders nothing for empty citations', () => {
    const { container } = render(<ConfidenceBadge citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders High confidence for avg >= 0.75', () => {
    render(<ConfidenceBadge citations={[cite(0.9), cite(0.85)]} />);
    expect(screen.getByText(/High confidence/i)).toBeInTheDocument();
  });

  it('renders Medium confidence for mid-range avg', () => {
    render(<ConfidenceBadge citations={[cite(0.65)]} />);
    expect(screen.getByText(/Medium confidence/i)).toBeInTheDocument();
  });
});
