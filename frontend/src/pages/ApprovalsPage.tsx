import { useMemo } from 'react';
import {
  ArrowUpRight,
  CalendarClock,
  Check,
  CheckSquare,
  Clock3,
  Hash,
  Info,
  Lock,
  MessageSquare,
  Quote,
  ShieldCheck,
  Tag,
  Ticket,
  UserRound,
  X,
  type LucideIcon,
} from 'lucide-react';

import { cn } from '../lib/cn';
import { Badge, Button, Card } from '../components/ui';
import type { BadgeTone } from '../components/ui';
import type { ApprovalKind, Citation, ProposedAction } from '../types';

// ---------------------------------------------------------------------------
// ApprovalsPage — POLISHED PLACEHOLDER for the Phase 9 HITL approval queue.
//
// The "propose-then-commit" loop is the project's safety contract: the agent
// only ever *proposes* Jira / Slack actions; a human approves or rejects before
// anything is executed. This page sketches that queue with illustrative mock
// data so reviewers can see the intended shape. NOTHING here is fetched and the
// approve / reject controls are intentionally disabled — the backend endpoints
// are not shipped yet.
// ---------------------------------------------------------------------------

// ── Per-kind presentation (icon + label + accent) ───────────────────────────

interface KindMeta {
  label: string;
  icon: LucideIcon;
  tone: BadgeTone;
  /** Accent classes for the leading icon tile. */
  tile: string;
}

const KIND_META: Record<ApprovalKind, KindMeta> = {
  jira: {
    label: 'Jira',
    icon: Ticket,
    tone: 'info',
    tile: 'bg-sky-500/15 text-sky-300',
  },
  slack: {
    label: 'Slack',
    icon: MessageSquare,
    tone: 'brand',
    tile: 'bg-brand/15 text-brand',
  },
};

// ── Mock proposals (illustrative only — never real data) ─────────────────────

interface MockProposal extends ProposedAction {
  /** Extra UI-only field: when the proposal would expire if left unattended. */
  expiresIn: string;
}

const MOCK_PROPOSALS: MockProposal[] = [
  {
    id: 'prop-1',
    project_id: 'demo',
    meeting_id: 'mtg-1',
    kind: 'jira',
    title: 'Створити задачу: інтеграція платежів через стороннього провайдера',
    payload: {
      project: 'PAY',
      issue_type: 'Story',
      assignee: 'Марія Коваль',
      priority: 'High',
      labels: ['payments', 'integration', 'spike'],
      description:
        'Команда винесла ризик інтеграції платежів в окрему задачу. Оцінити обсяг роботи через стороннього провайдера, підготувати технічне рішення та оцінку строків.',
    },
    rationale:
      'На зустрічі узгоджено, що платежі робимо через зовнішнього провайдера, а ризик інтеграції виноситься в окрему задачу.',
    citations: [
      { n: 1, segment_index: 12, start: 312, end: 348 },
      { n: 2, segment_index: 27, start: 690, end: 731 },
    ],
    status: 'proposed',
    result: null,
    created_at: '2026-06-29T09:14:00Z',
    expiresIn: 'за 22 год',
  },
  {
    id: 'prop-2',
    project_id: 'demo',
    kind: 'slack',
    meeting_id: 'mtg-1',
    title: 'Надіслати підсумок зустрічі у #team-alpha',
    payload: {
      channel: '#team-alpha',
      text:
        'Підсумок синку: реліз переноситься на наступний спринт, платежі — через стороннього провайдера, демо у п’ятницю. Деталі та дії — у треді.',
      mentions: ['@oleh', '@maria'],
    },
    rationale:
      'Учасники просили закинути короткий підсумок у канал команди одразу після зустрічі.',
    citations: [{ n: 1, segment_index: 4, start: 88, end: 121 }],
    status: 'proposed',
    result: null,
    created_at: '2026-06-29T09:15:00Z',
    expiresIn: 'за 22 год',
  },
  {
    id: 'prop-3',
    project_id: 'demo',
    meeting_id: 'mtg-1',
    kind: 'jira',
    title: 'Створити задачу: підготувати демо-середовище до п’ятниці',
    payload: {
      project: 'ALPHA',
      issue_type: 'Task',
      assignee: 'Олег Гнатюк',
      priority: 'Medium',
      labels: ['demo', 'infra'],
      due: '2026-07-03',
      description:
        'Розгорнути демо-середовище зі свіжою збіркою, перевірити сценарій показу та підготувати тестові дані для демо у п’ятницю.',
    },
    rationale:
      'Домовилися про демо у п’ятницю; Олег бере на себе підготовку демо-середовища.',
    citations: [{ n: 1, segment_index: 41, start: 1024, end: 1067 }],
    status: 'proposed',
    result: null,
    created_at: '2026-06-29T09:16:00Z',
    expiresIn: 'за 22 год',
  },
];

// ── Small building blocks ────────────────────────────────────────────────────

/** Inline citation chip [#N] — anchors a claim to a transcript segment. */
function CitationChip({ citation }: { citation: Citation }) {
  return (
    <span
      title={`Цитата на сегмент #${citation.segment_index}`}
      className="inline-flex items-center gap-0.5 rounded-pill bg-brand/15 px-1.5 py-0.5 text-[11px] font-semibold leading-none text-brand"
    >
      <Quote className="h-2.5 w-2.5" aria-hidden="true" />#{citation.n}
    </span>
  );
}

/** A single key→value row inside the payload preview. */
function PayloadRow({
  icon: Icon,
  label,
  children,
}: {
  icon: LucideIcon;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-2.5 text-sm">
      <span className="mt-0.5 flex w-28 shrink-0 items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted">
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        {label}
      </span>
      <span className="min-w-0 flex-1 text-fg">{children}</span>
    </div>
  );
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'string');
}

/** Render the kind-specific payload preview from the (typed-as-unknown) record. */
function PayloadPreview({ kind, payload }: { kind: ApprovalKind; payload: Record<string, unknown> }) {
  const get = (k: string): string =>
    payload[k] != null ? String(payload[k]) : '—';

  if (kind === 'jira') {
    const labels = isStringArray(payload.labels) ? payload.labels : [];
    return (
      <div className="flex flex-col gap-2.5">
        <PayloadRow icon={Hash} label="Проєкт">
          <span className="font-mono text-[13px]">{get('project')}</span>
          <span className="mx-1 text-muted">·</span>
          <span className="text-muted">{get('issue_type')}</span>
        </PayloadRow>
        <PayloadRow icon={UserRound} label="Виконавець">
          {get('assignee')}
        </PayloadRow>
        <PayloadRow icon={ShieldCheck} label="Пріоритет">
          <Badge tone={get('priority') === 'High' ? 'warning' : 'neutral'}>
            {get('priority')}
          </Badge>
        </PayloadRow>
        {payload.due != null && (
          <PayloadRow icon={CalendarClock} label="Дедлайн">
            <span className="font-mono text-[13px]">{get('due')}</span>
          </PayloadRow>
        )}
        {labels.length > 0 && (
          <PayloadRow icon={Tag} label="Мітки">
            <span className="flex flex-wrap gap-1.5">
              {labels.map((l) => (
                <Badge key={l} tone="neutral" className="font-mono">
                  {l}
                </Badge>
              ))}
            </span>
          </PayloadRow>
        )}
        <PayloadRow icon={Info} label="Опис">
          <span className="leading-snug text-muted">{get('description')}</span>
        </PayloadRow>
      </div>
    );
  }

  // Slack
  const mentions = isStringArray(payload.mentions) ? payload.mentions : [];
  return (
    <div className="flex flex-col gap-2.5">
      <PayloadRow icon={Hash} label="Канал">
        <span className="font-mono text-[13px]">{get('channel')}</span>
      </PayloadRow>
      <PayloadRow icon={MessageSquare} label="Повідомлення">
        <span className="leading-snug">{get('text')}</span>
      </PayloadRow>
      {mentions.length > 0 && (
        <PayloadRow icon={UserRound} label="Згадки">
          <span className="flex flex-wrap gap-1.5">
            {mentions.map((m) => (
              <Badge key={m} tone="info" className="font-mono">
                {m}
              </Badge>
            ))}
          </span>
        </PayloadRow>
      )}
    </div>
  );
}

// ── Proposal card ────────────────────────────────────────────────────────────

function ProposalCard({ proposal }: { proposal: MockProposal }) {
  const meta = KIND_META[proposal.kind];
  const Icon = meta.icon;

  return (
    <Card
      as="article"
      aria-label={`Запропонована дія (${meta.label}): ${proposal.title}`}
      className="flex flex-col overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-start gap-3 border-b border-border px-5 py-4">
        <span
          className={cn(
            'flex h-10 w-10 shrink-0 items-center justify-center rounded-card',
            meta.tile,
          )}
        >
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={meta.tone}>{meta.label}</Badge>
            <Badge tone="warning">
              <Clock3 className="h-3 w-3" aria-hidden="true" />
              Очікує підтвердження
            </Badge>
          </div>
          <h3 className="mt-1.5 text-sm font-semibold leading-snug text-fg">
            {proposal.title}
          </h3>
        </div>
      </div>

      {/* Payload preview */}
      <div className="px-5 py-4">
        <PayloadPreview kind={proposal.kind} payload={proposal.payload} />
      </div>

      {/* Rationale + grounded citations */}
      <div className="mx-5 mb-4 rounded-card border border-border bg-surface-2/40 px-3.5 py-3">
        <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
          <Info className="h-3.5 w-3.5" aria-hidden="true" />
          Обґрунтування
        </div>
        <p className="text-sm leading-relaxed text-fg">{proposal.rationale}</p>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] uppercase tracking-wide text-muted">
            Джерела:
          </span>
          {proposal.citations.map((c) => (
            <CitationChip key={c.n} citation={c} />
          ))}
        </div>
      </div>

      {/* Footer — disabled approve / reject controls */}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-border bg-surface-2/30 px-5 py-3">
        <span className="inline-flex items-center gap-1.5 text-xs text-muted">
          <CalendarClock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          Зникне {proposal.expiresIn}
        </span>
        <div
          className="flex items-center gap-2"
          title="Доступно у Фазі 9 — людина в контурі (HITL)"
        >
          <Button variant="ghost" size="sm" icon={X} disabled>
            Відхилити
          </Button>
          <Button variant="primary" size="sm" icon={Check} disabled>
            Підтвердити
          </Button>
        </div>
      </div>
    </Card>
  );
}

// ── Propose-then-commit explainer banner ─────────────────────────────────────

function GuardrailBanner() {
  return (
    <div className="relative overflow-hidden rounded-card border border-brand/30 bg-brand/[0.06] px-5 py-4">
      <div className="flex items-start gap-3.5">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-card bg-brand/15 text-brand">
          <ShieldCheck className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-fg">
            Propose-then-commit — нічого не виконується без вашого підтвердження
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            Агент лише <span className="font-medium text-fg">пропонує</span> дії в
            Jira та Slack на основі зустрічі. Кожна пропозиція має обґрунтування й
            цитати на транскрипт. Жодна дія не виконується, доки людина не натисне{' '}
            <span className="font-medium text-fg">Підтвердити</span> — це і є
            «людина в контурі» (HITL).
          </p>
        </div>
      </div>
    </div>
  );
}

// ── The flow strip (propose → review → execute) ──────────────────────────────

function FlowStep({
  icon: Icon,
  label,
  active,
}: {
  icon: LucideIcon;
  label: string;
  active?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={cn(
          'flex h-7 w-7 items-center justify-center rounded-full border',
          active
            ? 'border-brand/40 bg-brand/15 text-brand'
            : 'border-border bg-surface-2 text-muted',
        )}
      >
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      </span>
      <span className={cn('text-xs font-medium', active ? 'text-fg' : 'text-muted')}>
        {label}
      </span>
    </div>
  );
}

function FlowStrip() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-card border border-border bg-surface px-4 py-3 shadow-card">
      <FlowStep icon={MessageSquare} label="Агент пропонує" active />
      <ArrowUpRight className="h-3.5 w-3.5 rotate-45 text-muted" aria-hidden="true" />
      <FlowStep icon={CheckSquare} label="Людина переглядає" active />
      <ArrowUpRight className="h-3.5 w-3.5 rotate-45 text-muted" aria-hidden="true" />
      <FlowStep icon={Lock} label="Виконується лише після підтвердження" />
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function ApprovalsPage() {
  const proposals = MOCK_PROPOSALS;

  const pendingCount = useMemo(
    () => proposals.filter((p) => p.status === 'proposed').length,
    [proposals],
  );

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-semibold tracking-tight text-fg">Черга дій</h1>
            <Badge tone="warning">{pendingCount} очікує</Badge>
            <Badge tone="neutral">Скоро · Фаза 9</Badge>
          </div>
          <p className="max-w-2xl text-sm text-muted">
            Запропоновані агентом дії в Jira та Slack чекають на підтвердження
            людини. Це демонстраційний прев’ю — дані змодельовані, а підтвердження
            ще вимкнені.
          </p>
        </div>
      </header>

      <GuardrailBanner />
      <FlowStrip />

      {/* Proposal cards */}
      <section
        aria-label="Запропоновані дії"
        className="grid grid-cols-1 gap-4 xl:grid-cols-2"
      >
        {proposals.map((p) => (
          <ProposalCard key={p.id} proposal={p} />
        ))}
      </section>

      {/* Footer note */}
      <p className="flex items-center justify-center gap-2 pt-1 text-center text-xs text-muted">
        <Lock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        Підтвердження активуються у Фазі 9, щойно під’єднаємо виконавців Jira та
        Slack.
      </p>
    </div>
  );
}

export default ApprovalsPage;
