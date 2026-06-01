import { Navbar } from '@/components/Navbar';

export default function RulesLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen text-foreground bg-brand-surface">
      <Navbar />
      {children}
    </div>
  );
}
