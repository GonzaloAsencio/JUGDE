import type { Metadata } from 'next';
import { Cinzel, Cinzel_Decorative, Lustria } from 'next/font/google';
import { ThemeProvider } from '@/components/ThemeProvider';
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

// Hero title font (classic Cinzel, no decorative swashes) — used only for the
// big "NEED A JUDGE?" headline, not the RIFTWARD logo.
const cinzel = Cinzel({
  subsets: ['latin'],
  weight: ['700', '900'],
  display: 'swap',
  variable: '--font-hero',
});

export const metadata: Metadata = {
  title: 'Riftward',
  description: 'AI-powered rules judge for Riftbound TCG',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${cinzelDecorative.variable} ${lustria.variable} ${cinzel.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen font-sans antialiased">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-3 focus:left-3 focus:rounded-md focus:bg-brand-ink focus:px-4 focus:py-2 focus:text-brand-surface"
        >
          Skip to main content
        </a>
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
