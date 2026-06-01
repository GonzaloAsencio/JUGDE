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
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
