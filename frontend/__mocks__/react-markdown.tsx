import React from 'react';

interface Props {
  children?: React.ReactNode;
  className?: string;
  [key: string]: unknown;
}

export default function ReactMarkdown({ children, className }: Props) {
  return <div className={className}>{children}</div>;
}
