import { render, screen } from '@testing-library/react';
import { ConfidenceBadge } from '@/components/ConfidenceBadge';

describe('ConfidenceBadge', () => {
  it('renders nothing for empty citations', () => {
    const { container } = render(<ConfidenceBadge citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders High confidence for avg >= 0.75', () => {
    const citations = [{ similarity: 0.9 }, { similarity: 0.85 }] as any;
    render(<ConfidenceBadge citations={citations} />);
    expect(screen.getByText(/High confidence/i)).toBeInTheDocument();
  });

  it('renders Medium confidence for mid-range avg', () => {
    const citations = [{ similarity: 0.65 }] as any;
    render(<ConfidenceBadge citations={citations} />);
    expect(screen.getByText(/Medium confidence/i)).toBeInTheDocument();
  });
});
