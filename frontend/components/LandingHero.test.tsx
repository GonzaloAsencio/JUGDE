import { render, screen, fireEvent } from '@testing-library/react';
import { LandingHero } from './LandingHero';

describe('LandingHero', () => {
  it('renders NEED A heading', () => {
    render(<LandingHero onCallJudge={jest.fn()} />);
    expect(screen.getByText('NEED A')).toBeInTheDocument();
  });

  it('renders JUDGE? heading', () => {
    render(<LandingHero onCallJudge={jest.fn()} />);
    expect(
      screen.getByText((_, el) => el?.textContent === 'JUDGE?' && el.children.length > 0)
    ).toBeInTheDocument();
  });

  it('renders the call button', () => {
    render(<LandingHero onCallJudge={jest.fn()} />);
    expect(screen.getByRole('button', { name: /call the judge/i })).toBeInTheDocument();
  });

  it('calls onCallJudge when button is clicked', () => {
    const onCallJudge = jest.fn();
    render(<LandingHero onCallJudge={onCallJudge} />);
    fireEvent.click(screen.getByRole('button', { name: /call the judge/i }));
    expect(onCallJudge).toHaveBeenCalledTimes(1);
  });

  it('renders branding header', () => {
    render(<LandingHero onCallJudge={jest.fn()} />);
    expect(screen.getByText('Riftward')).toBeInTheDocument();
  });
});
