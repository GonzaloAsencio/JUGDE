import type { Metadata } from 'next';
import { Cinzel_Decorative, Lustria } from 'next/font/google';
import './globals.css';

const cinzelDecorative = Cinzel_Decorative({
  subsets: ['latin'],
  weight: ['400', '700', '900'],
  display: 'swap',
  variable: '--font-display',
});

const lustria = Lustria({
  subsets: ['latin'],
  weight: ['400'],
  display: 'swap',
  variable: '--font-body',
});

export const metadata: Metadata = {
  title: 'Riftward',
  description: 'AI-powered rules judge for Riftbound TCG',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${cinzelDecorative.variable} ${lustria.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
