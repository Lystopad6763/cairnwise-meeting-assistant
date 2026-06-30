import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Bot, Cloud, Cpu, Loader2, Sparkles } from 'lucide-react';

import { cn } from '../lib/cn';
import { useAgentRun, useRunAgent } from '../lib/queries';
import type { AskEngine } from '../types';
import { Badge, Button, Card, Input, useToast } from './ui';

const SUGGESTED = 'Запропонуй наступні кроки та задачі за останніми зустрічами проєкту';

interface AgentPanelProps {
  projectId: string;
}

/** Тригер агента (Phase 6): мета → ReAct по памʼяті → пропозиції дій у Чергу дій (HITL). */
export function AgentPanel({ projectId }: AgentPanelProps) {
  const { toast } = useToast();
  const run = useRunAgent(projectId);
  const [goal, setGoal] = useState(SUGGESTED);
  const [engine, setEngine] = useState<AskEngine>('local');
  const [runId, setRunId] = useState<string | null>(null);

  const result = useAgentRun(runId);
  const data = result.data;
  const pending = run.isPending || data?.status === 'pending';

  const start = useCallback(() => {
    const g = goal.trim();
    if (!g || pending) return;
    run.mutate(
      { goal: g, engine },
      {
        onSuccess: (r) => setRunId(r.id),
        onError: (err) =>
          toast({
            title: 'Не вдалося запустити агента',
            description:
              err.status === 400
                ? 'Хмарний режим недоступний: не задано OPENAI_API_KEY.'
                : err.detail || 'Спробуйте ще раз.',
            tone: 'danger',
          }),
      },
    );
  }, [goal, engine, pending, run, toast]);

  const engBtn = (key: AskEngine, label: string, Icon: typeof Cpu) => (
    <button
      type="button"
      disabled={pending}
      onClick={() => setEngine(key)}
      className={cn(
        'inline-flex items-center gap-1 rounded-card px-2 py-1 text-xs font-medium transition-colors',
        engine === key ? 'bg-brand text-brand-fg' : 'text-muted hover:bg-surface-2',
        pending && 'cursor-not-allowed opacity-60',
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {label}
    </button>
  );

  return (
    <Card className="p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Bot className="h-5 w-5 text-brand" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-fg">Агент: запропонувати дії</h2>
          <Badge tone="neutral">propose-then-commit</Badge>
        </div>
        <div className="flex gap-1 rounded-card border border-border bg-surface-2/40 p-0.5">
          {engBtn('local', 'Локальна', Cpu)}
          {engBtn('cloud', 'Хмара', Cloud)}
        </div>
      </div>

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="Мета для агента…"
            disabled={pending}
          />
        </div>
        <Button variant="primary" size="md" icon={Sparkles} loading={pending} disabled={!goal.trim() || pending} onClick={start}>
          Запустити
        </Button>
      </div>
      <p className="mt-1.5 text-[11px] text-muted">
        Агент шукає в памʼяті проєкту й <span className="font-medium text-fg">пропонує</span> дії
        (Jira/Slack/нотатки) — нічого не виконується без вашого підтвердження у Черзі дій.
      </p>

      {runId && (
        <div className="mt-4 border-t border-border pt-4">
          {pending ? (
            <div className="flex items-center gap-2 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Агент аналізує памʼять і формує пропозиції…
            </div>
          ) : data?.status === 'failed' ? (
            <p className="text-sm text-status-failed">{data.error || 'Помилка агента.'}</p>
          ) : data?.status === 'ready' ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-fg">
                Готово — <span className="font-semibold">{data.n_proposed}</span>{' '}
                {data.n_proposed === 1 ? 'пропозиція' : 'пропозицій'} на розгляд.
              </p>
              <Link
                to="/approvals"
                className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"
              >
                Відкрити Чергу дій
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}

export default AgentPanel;
