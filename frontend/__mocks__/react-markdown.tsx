import React from 'react';

interface Props {
  children?: React.ReactNode;
  className?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  components?: Record<string, React.ComponentType<any>>;
  [key: string]: unknown;
}

export default function ReactMarkdown({ children, className, components }: Props) {
  const content = typeof children === 'string' ? children : children;

  if (components?.p && typeof components.p === 'function') {
    const P = components.p as React.ComponentType<{ children: React.ReactNode }>;
    return <div className={className}><P>{content}</P></div>;
  }

  return <div className={className}>{content}</div>;
}
