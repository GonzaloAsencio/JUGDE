import { Skeleton } from '@/components/ui/skeleton';

export function AnswerSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="w-full h-4" />
      <Skeleton className="w-[85%] h-4" />
      <Skeleton className="w-[65%] h-4" />
    </div>
  );
}
