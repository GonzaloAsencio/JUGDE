import { Navbar } from '@/components/Navbar';

export default function RulesLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="min-h-screen text-foreground"
      style={{ backgroundColor: '#f6f3ee', ['--background' as string]: '#f6f3ee' } as React.CSSProperties}
    >
      <Navbar />
      {children}
    </div>
  );
}
