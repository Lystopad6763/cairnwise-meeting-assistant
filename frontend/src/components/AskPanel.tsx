import { useCallback, useState, type KeyboardEvent } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  Cloud,
  Cpu,
  ExternalLink,
  Loader2,
  Quote,
  Search,
  Sparkles,
} from 'lucide-react';

import { cn } from '../lib/cn';
import { useAsk, useAskResult } from '../lib/queries';
import { formatTimestamp } from '../lib/format';
import type { AskCitation, AskEngine } from '../types';
import { Badge, Button, Card, Input, useToast } from './ui';

// Рендер відповіді: [#N] -> чип, що скролить до картки-джерела ask-cite-N.
function renderAnswer(text: string) {
  const parts = text.split(/(\[#\d+\])/g);
  return parts.map((p, i) => {
    const m = p.match(/^\[#(\d+)\]$/);
    if (!m) return <span key={i}>{p}</span>;
    const n = m[1];
    return (
      <button
        key={i}
        type="button"
        onClick={() => document.getElementById(`ask-cite-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
        className="mx-0.5 inline-flex items-center rounded-pill bg-brand/15 px-1 text-[10px] font-semibold text-brand hover:bg-brand/25"
        title={`Джерело #${n}`}
      >
        #{n}
      </button>
    );
  });
}

function CitationCard({ c }: { c: AskCitation }) {
  return (
    <li
      id={`ask-cite-${c.n}`}
      className="rounded-card border border-border bg-surface-2/40 p-2.5 text-xs"
    >
      <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-muted">
        <span className="inline-flex items-center rounded-pill bg-brand/15 px-1.5 font-semibold text-brand">
          #{c.n}
        </span>
        <span className="font-medium text-fg">{c.title || 'Зустріч'}</span>
        {c.date && <span>· {c.date}</span>}
        {c.speaker && <span>· {c.speaker}</span>}
        <span title="relevance score (reranker)">· {c.score.toFixed(2)}</span>
        {c.meeting_id && (
          <Link
            to={`/meetings/${c.meeting_id}`}
            className="ml-auto inline-flex items-center gap-1 text-brand hover:underline"
          >
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
            {typeof c.start === 'number' ? formatTimestamp(c.start) : 'відкрити'}
          </Link>
        )}
      </div>
      <p className="line-clamp-3 whitespace-pre-wrap text-fg/90">{c.text}</p>
    </li>
  );
}

interface AskPanelProps {
  projectId: string;
}

/** Памʼять проєкту: запит → hybrid+rerank → grounded відповідь із цитатами та abstention. */
export function AskPanel({ projectId }: AskPanelProps) {
  const { toast } = useToast();
  const ask = useAsk(projectId);
  const [question, setQuestion] = useState('');
  const [engine, setEngine] = useState<AskEngine>('local');
  const [askId, setAskId] = useState<string | null>(null);

  const result = useAskResult(askId);
  const data = result.data;
  const pending = ask.isPending || data?.status === 'pending';

  const submit = useCallback(() => {
    const q = question.trim();
    if (!q || pending) return;
    ask.mutate(
      { question: q, engine },
      {
        onSuccess: (row) => setAskId(row.id),
        onError: (err) =>
          toast({
            title: 'Не вдалося запитати',
            description:
              err.status === 400
                ? 'Хмарний режим недоступний: не задано OPENAI_API_KEY.'
                : err.detail || 'Спробуйте ще раз.',
            tone: 'danger',
          }),
      },
    );
  }, [question, engine, pending, ask, toast]);

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submit();
    }
  };

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
          <Sparkles className="h-5 w-5 text-brand" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-fg">Запитати памʼять проєкту</h2>
        </div>
        <div className="flex gap-1 rounded-card border border-border bg-surface-2/40 p-0.5">
          {engBtn('local', 'Локальна', Cpu)}
          {engBtn('cloud', 'Хмара', Cloud)}
        </div>
      </div>

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Input
            placeholder="Напр., що вирішили щодо релізу? які ризики називали?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKey}
            disabled={pending}
          />
        </div>
        <Button
          variant="primary"
          size="md"
          icon={Search}
          loading={pending}
          disabled={!question.trim() || pending}
          onClick={submit}
        >
          Запитати
        </Button>
      </div>
      <p className="mt-1.5 text-[11px] text-muted">
        Відповідь будується ВИКЛЮЧНО з памʼяті проєкту (гібридний пошук → reranker → grounded LLM);
        якщо інформації немає — чесно скаже, що не зафіксовано.
      </p>

      {/* Result */}
      {askId && (
        <div className="mt-4 border-t border-border pt-4">
          {pending ? (
            <div className="flex items-center gap-2 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Шукаю в памʼяті проєкту…
            </div>
          ) : data?.status === 'failed' ? (
            <div className="flex items-start gap-2 rounded-card border border-status-failed/30 bg-status-failed/10 px-3 py-2 text-xs text-status-failed">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="break-words">{data.error || 'Помилка запиту.'}</span>
            </div>
          ) : data?.status === 'ready' ? (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-muted">
                <span className="font-medium text-fg">Питання:</span> {data.question}
              </p>

              {data.abstained ? (
                <div className="rounded-card border border-border bg-surface-2/50 px-3 py-2.5 text-sm text-muted">
                  {data.answer}
                </div>
              ) : (
                <>
                  <p className="text-sm leading-relaxed text-fg">{renderAnswer(data.answer)}</p>
                  {data.citations.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
                        <Quote className="h-3.5 w-3.5" aria-hidden="true" />
                        Джерела ({data.citations.length})
                      </div>
                      <ul className="space-y-1.5">
                        {data.citations.map((c) => (
                          <CitationCard key={c.n} c={c} />
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}

              {data.engine && (
                <Badge tone="neutral" className="w-fit">
                  {data.engine.startsWith('cloud') ? 'Хмара' : 'Локальна'} · {data.engine.split(':')[1]}
                </Badge>
              )}
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}

export default AskPanel;
