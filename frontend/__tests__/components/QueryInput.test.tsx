import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryInput } from '@/components/QueryInput';

const noop = () => {};

describe('QueryInput', () => {
  it('renders with placeholder', () => {
    render(<QueryInput value="" onChange={noop} onSubmit={noop} loading={false} placeholder="Ask something" />);
    expect(screen.getByPlaceholderText('Ask something')).toBeInTheDocument();
  });

  it('calls onSubmit on Enter', async () => {
    const onSubmit = jest.fn();
    render(<QueryInput value="some question" onChange={noop} onSubmit={onSubmit} loading={false} />);
    await userEvent.type(screen.getByRole('textbox'), '{Enter}');
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('does NOT call onSubmit on Shift+Enter', async () => {
    const onSubmit = jest.fn();
    render(<QueryInput value="some question" onChange={noop} onSubmit={onSubmit} loading={false} />);
    await userEvent.type(screen.getByRole('textbox'), '{Shift>}{Enter}{/Shift}');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('disables input and button when loading', () => {
    render(<QueryInput value="q" onChange={noop} onSubmit={noop} loading={true} />);
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(screen.getByRole('button')).toBeDisabled();
  });

  it('calls onSubmit on button click', async () => {
    const onSubmit = jest.fn();
    render(<QueryInput value="valid question here" onChange={noop} onSubmit={onSubmit} loading={false} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
