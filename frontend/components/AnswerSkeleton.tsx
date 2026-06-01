export function AnswerSkeleton() {
  return (
    <div className="flex items-center gap-1.5 py-1">
      {[0, 0.15, 0.30].map((delay, i) => (
        <div
          key={i}
          className="w-2 h-2 rounded-full bg-brand-ink/40 animate-bounce"
          style={{ animationDelay: `${delay}s` }}
        />
      ))}
    </div>
  );
}
