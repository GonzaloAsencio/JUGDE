import { render, screen, waitFor } from '@testing-library/react';
import { AuthButton } from './AuthButton';

const createClient = jest.fn();
jest.mock('@/lib/supabase/client', () => ({ createClient: () => createClient() }));

function fakeSupabase(email: string | null) {
  return {
    auth: {
      getUser: jest.fn().mockResolvedValue({ data: { user: email ? { email } : null } }),
      onAuthStateChange: jest.fn().mockReturnValue({ data: { subscription: { unsubscribe: jest.fn() } } }),
      signInWithOAuth: jest.fn(),
    },
  };
}

afterEach(() => jest.resetAllMocks());

it('renders nothing when Supabase is not configured', () => {
  createClient.mockReturnValue(null);
  const { container } = render(<AuthButton />);
  expect(container).toBeEmptyDOMElement();
});

it('offers Google sign-in when logged out', async () => {
  createClient.mockReturnValue(fakeSupabase(null));
  render(<AuthButton />);
  expect(await screen.findByRole('button', { name: /sign in with google/i })).toBeInTheDocument();
});

it('shows the email and a sign-out control when logged in', async () => {
  createClient.mockReturnValue(fakeSupabase('judge@example.com'));
  render(<AuthButton />);
  expect(await screen.findByText('judge@example.com')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
});

it('posts to the signout route when signing out', async () => {
  createClient.mockReturnValue(fakeSupabase('judge@example.com'));
  render(<AuthButton />);
  const button = await screen.findByRole('button', { name: /sign out/i });
  const form = button.closest('form');
  await waitFor(() => expect(form).toHaveAttribute('action', '/auth/signout'));
  expect(form).toHaveAttribute('method', 'post');
});
