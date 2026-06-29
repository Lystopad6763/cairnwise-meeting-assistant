import {
  CalendarClock,
  CircleDot,
  Gauge,
  ListTodo,
  Lock,
  Quote,
  ShieldCheck,
  Sparkles,
  UserRound,
} from 'lucide-react';

import { cn } from '../lib/cn';
import { Badge } from '../components/ui';

/**
 * _SummaryPlaceholder — DISABLED right-rail preview of the future Phase 7
 * "AI Summary" output. Purely presentational: no data is fetched, the backend
 * summary endpoint is not shipped. It sketches the intended shape so reviewers
 * can see where AI-резюме, рішення, дії та цитати will live.
 *
 * The whole card is rendered with reduced contrast + a "Скоро" badge and is
 * marked aria-disabled so assistive tech announces it as inactive.
 */

// ── Mock content (illustrative only — never rendered as real data) ───────────

interface MockDecision {
  text: string;
  cite: number;
}

interface MockAction {
  owner: string;
  task: string;
  deadline: string;
  cite: number;
}

const MOCK_SUMMARY =
  'Команда узгодила обсяг релізу, винесла ризик з інтеграцією платежів в окрему задачу та домовилася про демо у п’ятницю.';

const MOCK_DECISIONS: MockDecision[] = [
  { text: 'Реліз переноситься на наступний спринт', cite: 1 },
  { text: 'Інтеграцію платежів робимо через стороннього провайдера', cite: 2 },
];

const MOCK_ACTIONS: MockAction[] = [
  { owner: 'Олег', task: 'Підготувати демо-середовище', deadline: 'пт, 03.07', cite: 1 },
  { owner: 'Марія', task: 'Оцінити обсяг інтеграції платежів', deadline: 'ср, 01.07', cite: 2 },
];

// ── HITL confidence gate ─────────────────────────────────────────────

type GateKind = 'auto' | 'review' | 'reject';

interface GateMeta {
  label: string;
  tone: 'success' | 'warning' | 'danger';
  hint: string;
}

const GATE_META: Record<GateKind, GateMeta> = {
  auto: { label: 'Авто-підтвердження', tone: 'success', hint: 'висока впевненість' },
  review: { label: 'Потрібен перегляд', tone: 'warning', hint: 'середня впевненість' },
  reject: { label: 'Відхилено', tone: 'danger', hint: 'низька впевненість' },
};

/** Demo confidence → HITL gate band (mirrors the planned server thresholds). */
function gateFor(confidence: number): GateKind {
  if (confidence >= 0.8) return 'auto';
  if (confidence >= 0.5) return 'review';
  return 'reject';
}

const MOCK_CONFIDENCE = 0.72; // → "review"

// ── Small inline citation chip [#N] ──────────────────────────────────

function CitationChip({ n }: { n: number }) {
  return (
    <sup
      className="ml-0.5 inline-flex items-center rounded-pill bg-brand/15 px-1 text-[10px] font-semibold leading-tight text-brand"
      title={`Цитата на сегмент #${n}`}
    >
      #{n}
    </sup>
  );
}

function SectionLabel({
  icon: Icon,
  children,
}: {
  icon: typeof Sparkles;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {children}
    </div>
  );
}

export function SummaryPlaceholder() {
  const gate = GATE_META[gateFor(MOCK_CONFIDENCE)];
  const pct = Math.round(MOCK_CONFIDENCE * 100);

  return (
    <aside
      aria-disabled="true"
      aria-label="AI-резюме — функція в розробці"
      className="relative overflow-hidden rounded-card border border-dashed border-border bg-surface/60 shadow-card"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-card bg-brand/15 text-brand">
            <Sparkles className="h-4.5 w-4.5" aria-hidden="true" />
          </span>
          <div className="leading-tight">
            <h2 className="text-sm font-semibold text-fg">AI-резюме</h2>
            <p className="text-[11px] text-muted">Фаза 7 · grounded summary</p>
          </div>
        </div>
        <Badge tone="neutral">Скоро</Badge>
      </div>

      {/* Faded preview body — non-interactive */}
      <div className="pointer-events-none select-none space-y-5 px-4 py-4 opacity-70">
        {/* HITL confidence gate */}
        <div className="flex flex-col gap-2 rounded-card border border-border bg-surface-2/50 p-3">
          <SectionLabel icon={Gauge}>Впевненість · HITL</SectionLabel>
          <div className="flex items-center justify-between gap-2">
            <Badge tone={gate.tone}>
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
              {gate.label}
            </Badge>
            <span className="font-mono text-sm tabular-nums text-fg">{pct}%</span>
          </div>
          <div
            className="h-1.5 w-full overflow-hidden rounded-pill bg-surface-2"
            aria-hidden="true"
          >
            <div
              className={cn(
                'h-full rounded-pill',
                gate.tone === 'success' && 'bg-status-transcribed',
                gate.tone === 'warning' && 'bg-status-transcribing',
                gate.tone === 'danger' && 'bg-status-failed',
              )}
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-[11px] text-muted">
            Поріг автопідтвердження — {gate.hint}. Нижче порогу резюме йде на
            перегляд людиною.
          </p>
        </div>

        {/* Summary text with inline citations */}
        <div className="space-y-1.5">
          <SectionLabel icon={Sparkles}>Короткий підсумок</SectionLabel>
          <p className="text-sm leading-relaxed text-fg">
            {MOCK_SUMMARY}
            <CitationChip n={1} />
            <CitationChip n={3} />
          </p>
        </div>

        {/* Decisions */}
        <div className="space-y-1.5">
          <SectionLabel icon={CircleDot}>Рішення</SectionLabel>
          <ul className="space-y-1.5">
            {MOCK_DECISIONS.map((d, i) => (
              <li key={i} className="flex gap-2 text-sm text-fg">
                <CircleDot
                  className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand"
                  aria-hidden="true"
                />
                <span className="leading-snug">
                  {d.text}
                  <CitationChip n={d.cite} />
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/* Action items (owner / task / deadline) */}
        <div className="space-y-1.5">
          <SectionLabel icon={ListTodo}>Дії</SectionLabel>
          <ul className="space-y-2">
            {MOCK_ACTIONS.map((a, i) => (
              <li
                key={i}
                className="rounded-card border border-border bg-surface-2/50 p-2.5"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium leading-snug text-fg">
                    {a.task}
                    <CitationChip n={a.cite} />
                  </span>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                  <span className="inline-flex items-center gap-1">
                    <UserRound className="h-3.5 w-3.5" aria-hidden="true" />
                    {a.owner}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
                    {a.deadline}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* Grounded citations footnote */}
        <div className="space-y-1.5">
          <SectionLabel icon={Quote}>Цитати</SectionLabel>
          <p className="text-[11px] leading-relaxed text-muted">
            Кожне твердження [#N] прив’язане до конкретного сегмента транскрипту —
            клік прокручуватиме до репліки-джерела.
          </p>
        </div>
      </div>

      {/* Lock ribbon */}
      <div className="flex items-center gap-2 border-t border-border bg-surface-2/40 px-4 py-2.5 text-xs text-muted">
        <Lock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        Зʼявиться, щойно увімкнемо генерацію резюме з людиною в контурі (HITL).
      </div>
    </aside>
  );
}

export default SummaryPlaceholder;
