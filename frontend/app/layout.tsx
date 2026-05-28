import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Riftbound Judge AI',
  description: 'AI-powered rules judge for Riftbound TCG',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
