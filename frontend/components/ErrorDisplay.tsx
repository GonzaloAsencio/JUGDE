'use client';

import type { ApiError } from '@/lib/types';

interface ErrorDisplayProps {
  error: ApiError;
  onRetry: () => void;
}

export function ErrorDisplay({ error, onRetry }: ErrorDisplayProps) {
  let heading: string;
  let detail: string;

  switch (error.type) {
    case 'rate_limit':
      heading = 'Rate limit reached.';
      detail =
        error.retryAfter != null
          ? `Try again in ${error.retryAfter} seconds.`
          : 'Too many requests. Please wait before trying again.';
      break;
    case 'timeout':
      heading = 'This is taking too long.';
      detail = 'The judge did not respond in time. Try again.';
      break;
    case 'server':
      heading = 'Something went wrong on our end.';
      detail = 'The server encountered an error. Try again.';
      break;
    case 'network':
      heading = 'Connection error.';
      detail = 'Check your internet connection and try again.';
      break;
    case 'validation':
      heading = 'Invalid input.';
      detail = error.message;
      break;
    default:
      heading = 'Something went wrong.';
      detail = error.message;
  }

  return (
    <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-destructive text-sm space-y-2">
      <p className="font-semibold">{heading}</p>
      <p>{detail}</p>
      <button
        onClick={onRetry}
        className="mt-2 text-xs underline underline-offset-2 hover:no-underline"
        type="button"
      >
        Try again
      </button>
    </div>
  );
}
