import { AlertTriangle, CheckCircle2, Clock, Loader2, type LucideIcon } from 'lucide-react';
import { cn } from '../../lib/cn';
import type { MeetingStatus } from '../../types';
import { Badge, type BadgeTone } from './Badge';

interface StatusBadgeProps {
  status: MeetingStatus;
  className?: string;
}

/** Single source of truth: MeetingStatus → label + tone + dot + icon. */
export const STATUS_META: Record<
  MeetingStatus,
  { label: string; tone: BadgeTone; dotClass: string; icon: LucideIcon }
> = {
  uploaded: {
    label: 'У черзі',
    tone: 'neutral',
    dotClass: 'bg-status-uploaded',
    icon: Clock,
  },
  transcribing: {
    label: 'Транскрибуємо…',
    tone: 'warning',
    dotClass: 'bg-status-transcribing animate-pulseDot',
    icon: Loader2,
  },
  transcribed: {
    label: 'Готово',
    tone: 'success',
    dotClass: 'bg-status-transcribed',
    icon: CheckCircle2,
  },
  failed: {
    label: 'Помилка',
    tone: 'danger',
    dotClass: 'bg-status-failed',
    icon: AlertTriangle,
  },
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const meta = STATUS_META[status];
  return (
    <Badge tone={meta.tone} className={className}>
      <span
        aria-hidden="true"
        className={cn('h-2 w-2 shrink-0 rounded-full', meta.dotClass)}
      />
      {meta.label}
    </Badge>
  );
}
