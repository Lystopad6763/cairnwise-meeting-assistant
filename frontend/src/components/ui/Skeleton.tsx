import { cn } from '../../lib/cn';

interface SkeletonProps {
  className?: string;
}

/** Shimmer block. Compose multiple for list/placeholder layouts. */
export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'relative overflow-hidden rounded-card bg-surface-2',
        'before:absolute before:inset-0 before:-translate-x-full',
        'before:bg-gradient-to-r before:from-transparent before:via-white/5 before:to-transparent',
        'before:animate-shimmer',
        className,
      )}
    />
  );
}
