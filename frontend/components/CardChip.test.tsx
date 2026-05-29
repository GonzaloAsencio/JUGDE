import { render, screen } from '@testing-library/react';
import { CardChip } from './CardChip';

describe('CardChip', () => {
  it('renders the card name uppercased', () => {
    render(<CardChip name="Yasuo" />);
    expect(screen.getByText('YASUO')).toBeInTheDocument();
  });

  it('does not render the @ prefix', () => {
    render(<CardChip name="Atakhan" />);
    expect(screen.queryByText(/@/)).toBeNull();
  });

  it('renders a span (inline-safe for chat bubble context)', () => {
    const { container } = render(<CardChip name="Shen" />);
    expect(container.firstChild?.nodeName).toBe('SPAN');
  });
});
