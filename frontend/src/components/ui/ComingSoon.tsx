import { MessageSquare, Sparkles, CheckSquare, type LucideIcon } from 'lucide-react';
import { Badge } from './Badge';

interface ComingSoonProps {
  feature: 'summary' | 'approvals' | 'ask';
  title: string;
  description?: string;
}

const FEATURE_ICON: Record<ComingSoonProps['feature'], LucideIcon> = {
  summary: Sparkles,
  approvals: CheckSquare,
  ask: MessageSquare,
};

const FEATURE_DEFAULT_DESC: Record<ComingSoonProps['feature'], string> = {
  summary:
    'AI-резюме зустрічі з обґрунтованими цитатами [#N] та підтвердженням людиною за рівнем впевненості.',
  approvals:
    'Черга підтверджень для запропонованих дій Jira / Slack — кожна дія з обґрунтуванням і цитатами.',
  ask: 'RAG-чат по вашим зустрічам зі стрімінгом відповіді та цитатами на сегменти.',
};

export function ComingSoon({ feature, title, description }: ComingSoonProps) {
  const Icon = FEATURE_ICON[feature];
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-card border border-dashed border-border bg-surface/50 px-6 py-16 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-card bg-surface-2 text-brand">
        <Icon className="h-7 w-7" aria-hidden="true" />
      </span>
      <div className="flex items-center gap-2">
        <h3 className="text-base font-semibold text-fg">{title}</h3>
        <Badge tone="neutral">Скоро</Badge>
      </div>
      <p className="max-w-md text-sm text-muted">
        {description ?? FEATURE_DEFAULT_DESC[feature]}
      </p>
    </div>
  );
}
