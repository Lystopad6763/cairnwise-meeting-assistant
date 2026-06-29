import { useState } from 'react';
import {
  AlertTriangle,
  CalendarClock,
  CircleDot,
  Cloud,
  Cpu,
  Gauge,
  ListTodo,
  Loader2,
  Lock,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UserRound,
} from 'lucide-react';

import { cn } from '../lib/cn';
import { useRequestSummary, useSummary } from '../lib/queries';
import {
  GATE_META,
  engineLabel,
  gateFor,
  scrollToSegment,
} from '../lib/summary';
import type { SummaryEngine } from '../types';
import { Badge, Button, useToast } from './ui';

// ── inline citation chip [#N] -> прокрутка до сегмента ──
function CitationChip({ n }: { n: number }) {
  return (
    <button
      type="button"
      onClick={() => scrollToSegment(n)}
      className="ml-0.5 inline-flex items-center rounded-pill bg-brand/15 px-1 text-[10px] font-semibold leading-tight text-brand hover:bg-brand/25"
      title={`Перейти до репліки #${n}`}
    >
      #{n}
    </button>
  );
}

function Citations({ list }: { list?: number[] }) {
  if (!list || list.length === 0) return null;
  return (
    <>
      {list.map((n, i) => (
        <CitationChip key={`${n}-${i}`} n={n} />
      ))}
    </>
  );
}

function SectionLabel({ icon: Icon, children }: { icon: typeof Sparkles; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {children}
    </div>
  );
}

// ── engine selector (приватність -> рушій) ──
function EngineToggle({
  value,
  onChange,
  disabled,
}: {
  value: SummaryEngine;
  onChange: (e: SummaryEngine) => void;
  disabled?: boolean;
}) {
  const opt = (key: SummaryEngine, label: string, Icon: typeof Cpu) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(key)}
      className={cn(
        'flex flex-1 items-center justify-center gap-1.5 rounded-card px-2.5 py-1.5 text-xs font-medium transition-colors',
        value === key ? 'bg-brand text-brand-fg' : 'text-muted hover:bg-surface-2',
        disabled && 'cursor-not-allowed opacity-60',
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {label}
    </button>
  );
  return (
    <div className="flex gap-1 rounded-card border border-border bg-surface-2/40 p-1">
      {opt('local', 'Локальна', Cpu)}
      {opt('cloud', 'Хмара', Cloud)}
    </div>
  );
}

interface SummaryRailProps {
  meetingId: string;
}

/**
 * Правий рейл «AI-резюме» (Агент-2, Фаза 7): генерація на вибраному рушії (local/cloud),
 * polling статусу, grounded summary з цитатами [#N] (клік -> репліка), HITL-гейт за впевненістю.
 */
export function SummaryRail({ meetingId }: SummaryRailProps) {
  const { toast } = useToast();
  const [engine, setEngine] = useState<SummaryEngine>('local');

  const summary = useSummary(meetingId);
  const request = useRequestSummary(meetingId);

  const data = summary.isError && summary.error.status === 404 ? undefined : summary.data;
  const generating = request.isPending || data?.status === 'pending';

  const onGenerate = () => {
    request.mutate(engine, {
      onError: (err) =>
        toast({
          title: 'Не вдалося запустити резюме',
          description:
            err.status === 400
              ? 'Хмарний режим недоступний: не задано OPENAI_API_KEY.'
              : err.detail || 'Спробуйте ще раз.',
          tone: 'danger',
        }),
    });
  };

  const ready = data?.status === 'ready';
  const gate = ready ? GATE_META[gateFor(data.confidence)] : null;
  const pct = ready && data.confidence != null ? Math.round(data.confidence * 100) : null;

  return (
    <aside
      aria-label="AI-резюме зустрічі"
      className="overflow-hidden rounded-card border border-border bg-surface shadow-card"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-card bg-brand/15 text-brand">
            <Sparkles className="h-4.5 w-4.5" aria-hidden="true" />
          </span>
          <div className="leading-tight">
            <h2 className="text-sm font-semibold text-fg">AI-резюме</h2>
            <p className="text-[11px] text-muted">
              {ready ? engineLabel(data.engine) : 'grounded summary + HITL'}
            </p>
          </div>
        </div>
        {ready && (
          <Button
            variant="ghost"
            size="sm"
            icon={RefreshCw}
            loading={generating}
            onClick={onGenerate}
          >
            Онов.
          </Button>
        )}
      </div>

      <div className="space-y-4 px-4 py-4">
        {/* Engine selector */}
        <div className="space-y-1.5">
          <SectionLabel icon={Cpu}>Рушій (приватність)</SectionLabel>
          <EngineToggle value={engine} onChange={setEngine} disabled={generating} />
          <p className="text-[11px] text-muted">
            Локальна — приватно, нічого не покидає машину. Хмара (OpenAI) — для «непублічних»
            зустрічей, лише текст.
          </p>
        </div>

        {/* Body states */}
        {summary.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Завантаження…
          </div>
        ) : generating ? (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <Loader2 className="h-6 w-6 animate-spin text-brand" aria-hidden="true" />
            <p className="text-sm font-medium text-fg">Генеруємо резюме…</p>
            <p className="text-xs text-muted">
              {engineLabel(data?.engine ?? `${engine}:`)} · це може зайняти кілька хвилин
            </p>
          </div>
        ) : data?.status === 'failed' ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-start gap-2 rounded-card border border-status-failed/30 bg-status-failed/10 px-3 py-2 text-xs text-status-failed">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="break-words">{data.error || 'Помилка генерації резюме.'}</span>
            </div>
            <Button variant="secondary" size="sm" icon={RefreshCw} onClick={onGenerate}>
              Спробувати знову
            </Button>
          </div>
        ) : !ready ? (
          /* no summary yet (404) */
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-brand">
              <Sparkles className="h-6 w-6" aria-hidden="true" />
            </span>
            <p className="max-w-[16rem] text-sm text-muted">
              Згенеруйте структуроване резюме з рішеннями, діями та цитатами на репліки.
            </p>
            <Button variant="primary" size="md" icon={Sparkles} onClick={onGenerate}>
              Згенерувати резюме
            </Button>
          </div>
        ) : (
          /* ready */
          <div className="space-y-5">
            {/* HITL gate */}
            <div className="flex flex-col gap-2 rounded-card border border-border bg-surface-2/50 p-3">
              <SectionLabel icon={Gauge}>Впевненість · HITL</SectionLabel>
              <div className="flex items-center justify-between gap-2">
                <Badge tone={gate!.tone}>
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                  {gate!.label}
                </Badge>
                <span className="font-mono text-sm tabular-nums text-fg">
                  {pct != null ? `${pct}%` : '—'}
                </span>
              </div>
              {pct != null && (
                <div className="h-1.5 w-full overflow-hidden rounded-pill bg-surface-2" aria-hidden="true">
                  <div
                    className={cn(
                      'h-full rounded-pill',
                      gate!.tone === 'success' && 'bg-status-transcribed',
                      gate!.tone === 'warning' && 'bg-status-transcribing',
                      gate!.tone === 'danger' && 'bg-status-failed',
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              )}
              <p className="text-[11px] text-muted">{gate!.hint}</p>
            </div>

            {/* Summary text */}
            {data.summary && (
              <div className="space-y-1.5">
                <SectionLabel icon={Sparkles}>Короткий підсумок</SectionLabel>
                <p className="text-sm leading-relaxed text-fg">{data.summary}</p>
              </div>
            )}

            {/* Decisions */}
            {data.decisions.length > 0 && (
              <div className="space-y-1.5">
                <SectionLabel icon={CircleDot}>Рішення</SectionLabel>
                <ul className="space-y-1.5">
                  {data.decisions.map((d, i) => (
                    <li key={i} className="flex gap-2 text-sm text-fg">
                      <CircleDot className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" aria-hidden="true" />
                      <span className="leading-snug">
                        {d.decision || '—'}
                        <Citations list={d.citations} />
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Action items */}
            {data.action_items.length > 0 && (
              <div className="space-y-1.5">
                <SectionLabel icon={ListTodo}>Дії</SectionLabel>
                <ul className="space-y-2">
                  {data.action_items.map((a, i) => (
                    <li key={i} className="rounded-card border border-border bg-surface-2/50 p-2.5">
                      <span className="text-sm font-medium leading-snug text-fg">
                        {a.task || '—'}
                        <Citations list={a.citations} />
                      </span>
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                        {a.owner && (
                          <span className="inline-flex items-center gap-1">
                            <UserRound className="h-3.5 w-3.5" aria-hidden="true" />
                            {a.owner}
                          </span>
                        )}
                        {a.deadline && (
                          <span className="inline-flex items-center gap-1">
                            <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
                            {a.deadline}
                          </span>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Risks / blockers */}
            {data.risks.length > 0 && (
              <div className="space-y-1.5">
                <SectionLabel icon={AlertTriangle}>Ризики / блокери</SectionLabel>
                <ul className="space-y-1.5">
                  {data.risks.map((r, i) => (
                    <li key={i} className="flex gap-2 text-sm text-fg">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-status-failed" aria-hidden="true" />
                      <span className="leading-snug">
                        {r.item || '—'}
                        <Citations list={r.citations} />
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer — privacy */}
      <div className="flex items-center gap-2 border-t border-border bg-surface-2/40 px-4 py-2.5 text-xs text-muted">
        <Lock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        Резюме йде на людський апрув (HITL) перед будь-якою розсилкою.
      </div>
    </aside>
  );
}

export default SummaryRail;
