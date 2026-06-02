jest.mock('next/navigation', () => ({ usePathname: () => '/' }));
jest.mock('./ThemeToggle', () => ({ ThemeToggle: () => <button>theme</button> }));

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Navbar } from './Navbar';

describe('Navbar mobile menu', () => {
  it('renders a collapsed menu toggle button', () => {
    render(<Navbar />);
    const toggle = screen.getByRole('button', { name: /menu/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens a mobile panel with the nav links when toggled', async () => {
    const user = userEvent.setup();
    render(<Navbar />);
    const toggle = screen.getByRole('button', { name: /menu/i });

    await user.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const panel = screen.getByTestId('mobile-menu');
    expect(within(panel).getByRole('link', { name: /rules/i })).toBeInTheDocument();
  });

  it('collapses the panel when toggled again', async () => {
    const user = userEvent.setup();
    render(<Navbar />);
    const toggle = screen.getByRole('button', { name: /menu/i });

    await user.click(toggle);
    await user.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('mobile-menu')).toBeNull();
  });
});
