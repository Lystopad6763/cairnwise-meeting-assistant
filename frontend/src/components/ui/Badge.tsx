import React from 'react';
import { cn } from '../../lib/cn';

export type BadgeTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'brand';

interface BadgeProps {
  tone?: BadgeTone;
  children: React.ReactNode;
  className?: string;
}

const TONE: Record<BadgeTone, string> = {
  neutral: 'bg-surface-2 text-muted border border-border',
  info: 'bg-sky-500/15 text-sky-300 border border-sky-500/25',
  success:
    'bg-status-transcribed/15 text-status-transcribed border border-status-transcribed/30',
  warning:
    'bg-status-transcribing/15 text-status-transcribing border border-status-transcribing/30',
  danger: 'bg-status-failed/15 text-status-failed border border-status-failed/30',
  brand: 'bg-brand/15 text-brand border border-brand/30',
};

export function Badge({ tone = 'neutral', children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-pill px-2.5 py-0.5',
        'text-xs font-medium whitespace-nowrap',
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
