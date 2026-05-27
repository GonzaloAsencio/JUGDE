import { render, screen } from '@testing-library/react';
import { KeywordBadge } from './KeywordBadge';
import type { KeywordDef } from '@/lib/gameKeywords';

const accelerate: KeywordDef = { name: 'accelerate', label: 'ACCELERATE', color: '#26705f', textColor: 'white' };
const deflect: KeywordDef = { name: 'deflect', label: 'DEFLECT', color: '#93af34', textColor: 'black' };
const banish: KeywordDef = { name: 'banish', label: 'banish' };

describe('KeywordBadge', () => {
  it('renders a styled span for card keywords', () => {
    render(<KeywordBadge def={accelerate} />);
    const text = screen.getByText('ACCELERATE');
    expect(text.tagName).toBe('SPAN');
    const bg = text.previousElementSibling as HTMLElement;
    expect(bg).toHaveStyle({ backgroundColor: '#26705f' });
    expect(text.parentElement).toHaveStyle({ color: 'white' });
  });

  it('renders black text for yellow-green keywords', () => {
    render(<KeywordBadge def={deflect} />);
    const text = screen.getByText('DEFLECT');
    expect(text.parentElement).toHaveStyle({ color: 'black' });
  });

  it('renders plain text (no span) for general game keywords', () => {
    const { container } = render(<KeywordBadge def={banish} />);
    expect(container.querySelector('span')).toBeNull();
    expect(container.textContent).toBe('banish');
  });

  it('applies the correct label text', () => {
    render(<KeywordBadge def={accelerate} />);
    expect(screen.getByText('ACCELERATE')).toBeTruthy();
  });
});
