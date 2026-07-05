// Shown by Next's App Router while the (server-rendered) rules page streams in.
// Mirrors the real two-column layout so the swap-in doesn't shift, and echoes
// the hung-number clause rhythm so the wait reads as "rules loading".

function Bar({ w, className = '' }: { w: string; className?: string }) {
  return (
    <div
      className={`h-3 rounded bg-brand-ink/10 ${className}`}
      style={{ width: w }}
    />
  );
}

function ClauseRow({ indent = 0, lines = 1 }: { indent?: number; lines?: number }) {
  return (
    <div className="flex gap-3" style={{ marginLeft: indent }}>
      <div className="h-3 w-8 shrink-0 rounded bg-brand-ink/10" />
      <div className="flex-1 space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <Bar key={i} w={i === lines - 1 ? '70%' : '100%'} />
        ))}
      </div>
    </div>
  );
}

export default function RulesLoading() {
  return (
    <div className="flex min-h-[calc(100vh-52px)] animate-pulse" aria-hidden>
      {/* Sidebar */}
      <nav
        className="hidden shrink-0 border-r border-border lg:block"
        style={{ width: 260, padding: '32px 24px' }}
      >
        <Bar w="40%" className="mb-6 h-2.5" />
        <div className="space-y-3">
          {Array.from({ length: 9 }).map((_, i) => (
            <Bar key={i} w={`${85 - (i % 3) * 15}%`} />
          ))}
        </div>
      </nav>

      {/* Article */}
      <main className="flex-1 px-[clamp(20px,5vw,64px)] py-10">
        {/* Section title */}
        <div className="mb-8 border-b border-border pb-4">
          <div className="h-7 w-3/5 rounded bg-brand-accent/25" />
        </div>

        <div className="space-y-4">
          <ClauseRow lines={2} />
          <ClauseRow indent={15} lines={1} />
          <ClauseRow indent={15} lines={3} />
          <ClauseRow indent={30} lines={1} />
          <ClauseRow indent={30} lines={2} />
          <ClauseRow lines={2} />
          <ClauseRow indent={15} lines={2} />
          <ClauseRow indent={15} lines={1} />
        </div>
      </main>
    </div>
  );
}
