import { useMemo, useState } from 'react';
import {
  ArrowUpRight,
  CalendarClock,
  Check,
  CheckSquare,
  Hash,
  Inbox,
  Info,
  Lock,
  Mail,
  MessageSquare,
  Quote,
  RefreshCw,
  ShieldCheck,
  StickyNote,
  Ticket,
  UserRound,
  X,
  type LucideIcon,
} from 'lucide-react';

import { cn } from '../lib/cn';
import { useApprovals, useApprove, useReject } from '../lib/queries';
import { Badge, Button, Card, EmptyState, Skeleton, useToast } from '../components/ui';
import type { BadgeTone } from '../components/ui';
import type { ApprovalKind, AskCitation, ProposedAction } from '../types';

// ---------------------------------------------------------------------------
// ApprovalsPage — LIVE Phase 6 HITL approval queue.
// propose-then-commit: агент лише ПРОПОНУЄ дії; людина апрувить/відхиляє. Реальне
// виконання через конектори (Jira/Slack/email) — наступний крок; апрув наразі фіксує рішення.
// ---------------------------------------------------------------------------

interface KindMeta {
  label: string;
  icon: LucideIcon;
  tone: BadgeTone;
  tile: string;
}

const KIND_META: Record<ApprovalKind, KindMeta> = {
  jira: { label: 'Jira', icon: Ticket, tone: 'info', tile: 'bg-sky-500/15 text-sky-300' },
  slack: { label: 'Slack', icon: MessageSquare, tone: 'brand', tile: 'bg-brand/15 text-brand' },
  email: { label: 'Email', icon: Mail, tone: 'warning', tile: 'bg-amber-500/15 text-amber-300' },
  note: { label: 'Нотатка', icon: StickyNote, tone: 'neutral', tile: 'bg-surface-2 text-muted' },
};

// ── Citation chip (ask-стиль джерело) ───────────────────────────────────────
function CitationChip({ c }: { c: AskCitation }) {
  return (
    <span
      title={`Джерело: ${c.title ?? ''}${c.speaker ? ' · ' + c.speaker : ''}`}
      className="inline-flex items-center gap-0.5 rounded-pill bg-brand/15 px-1.5 py-0.5 text-[11px] font-semibold leading-none text-brand"
    >
      <Quote className="h-2.5 w-2.5" aria-hidden="true" />#{c.n}
    </span>
  );
}

function PayloadRow({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: React.ReactNode }) {
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

/** Превʼю payload: jira/slack — типовані; email/note/інше — generic key→value (payload від LLM). */
function PayloadPreview({ kind, payload }: { kind: ApprovalKind; payload: Record<string, unknown> }) {
  const get = (k: string): string => (payload[k] != null ? String(payload[k]) : '—');

  if (kind === 'jira') {
    return (
      <div className="flex flex-col gap-2.5">
        <PayloadRow icon={Hash} label="Проєкт">
          <span className="font-mono text-[13px]">{get('project')}</span>
          <span className="mx-1 text-muted">·</span>
          <span className="text-muted">{get('issue_type')}</span>
        </PayloadRow>
        <PayloadRow icon={UserRound} label="Виконавець">{get('assignee')}</PayloadRow>
        {payload.due != null && (
          <PayloadRow icon={CalendarClock} label="Дедлайн">
            <span className="font-mono text-[13px]">{get('due')}</span>
          </PayloadRow>
        )}
        <PayloadRow icon={Info} label="Опис">
          <span className="leading-snug text-muted">{get('description')}</span>
        </PayloadRow>
      </div>
    );
  }
  if (kind === 'slack') {
    return (
      <div className="flex flex-col gap-2.5">
        <PayloadRow icon={Hash} label="Канал"><span className="font-mono text-[13px]">{get('channel')}</span></PayloadRow>
        <PayloadRow icon={MessageSquare} label="Повідомлення"><span className="leading-snug">{get('text')}</span></PayloadRow>
      </div>
    );
  }
  // email / note / generic — показуємо всі поля payload
  const entries = Object.entries(payload ?? {});
  if (entries.length === 0) return <p className="text-sm text-muted">—</p>;
  return (
    <div className="flex flex-col gap-2.5">
      {entries.map(([k, v]) => (
        <PayloadRow key={k} icon={Info} label={k}>
          <span className="leading-snug">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
        </PayloadRow>
      ))}
    </div>
  );
}

// ── Proposal card (live approve/reject) ──────────────────────────────────────
function ProposalCard({
  proposal,
  onApprove,
  onReject,
  busy,
}: {
  proposal: ProposedAction;
  onApprove: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  const meta = KIND_META[proposal.kind] ?? KIND_META.note;
  const Icon = meta.icon;

  return (
    <Card as="article" aria-label={`Запропонована дія (${meta.label}): ${proposal.title}`} className="flex flex-col overflow-hidden">
      <div className="flex items-start gap-3 border-b border-border px-5 py-4">
        <span className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-card', meta.tile)}>
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <Badge tone={meta.tone}>{meta.label}</Badge>
          <h3 className="mt-1.5 text-sm font-semibold leading-snug text-fg">{proposal.title}</h3>
        </div>
      </div>

      <div className="px-5 py-4">
        <PayloadPreview kind={proposal.kind} payload={proposal.payload} />
      </div>

      {(proposal.rationale || proposal.citations.length > 0) && (
        <div className="mx-5 mb-4 rounded-card border border-border bg-surface-2/40 px-3.5 py-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
            Обґрунтування
          </div>
          {proposal.rationale && <p className="text-sm leading-relaxed text-fg">{proposal.rationale}</p>}
          {proposal.citations.length > 0 && (
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] uppercase tracking-wide text-muted">Джерела:</span>
              {proposal.citations.map((c) => (
                <CitationChip key={c.n} c={c} />
              ))}
            </div>
          )}
        </div>
      )}

      <div className="mt-auto flex items-center justify-end gap-2 border-t border-border bg-surface-2/30 px-5 py-3">
        <Button variant="ghost" size="sm" icon={X} disabled={busy} onClick={onReject}>
          Відхилити
        </Button>
        <Button variant="primary" size="sm" icon={Check} loading={busy} onClick={onApprove}>
          Підтвердити
        </Button>
      </div>
    </Card>
  );
}

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
            Агент лише <span className="font-medium text-fg">пропонує</span> дії на основі памʼяті
            проєкту; кожна має обґрунтування й цитати на джерела. Реальне виконання через конектори
            (Jira / Slack / email) — наступний крок; підтвердження тут фіксує рішення людини (HITL).
          </p>
        </div>
      </div>
    </div>
  );
}

function FlowStep({ icon: Icon, label, active }: { icon: LucideIcon; label: string; active?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className={cn('flex h-7 w-7 items-center justify-center rounded-full border',
        active ? 'border-brand/40 bg-brand/15 text-brand' : 'border-border bg-surface-2 text-muted')}>
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      </span>
      <span className={cn('text-xs font-medium', active ? 'text-fg' : 'text-muted')}>{label}</span>
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

export function ApprovalsPage() {
  const { toast } = useToast();
  const approvals = useApprovals('proposed');
  const approve = useApprove('proposed');
  const reject = useReject('proposed');
  const [busyId, setBusyId] = useState<string | null>(null);

  const proposals = approvals.data ?? [];
  const pendingCount = useMemo(() => proposals.length, [proposals]);

  const act = (id: string, kind: 'approve' | 'reject') => {
    setBusyId(id);
    const m = kind === 'approve' ? approve : reject;
    m.mutate(id, {
      onSuccess: () =>
        toast({
          title: kind === 'approve' ? 'Підтверджено' : 'Відхилено',
          description: kind === 'approve' ? 'Дію позначено як схвалену.' : 'Пропозицію відхилено.',
          tone: kind === 'approve' ? 'success' : 'info',
        }),
      onError: (err) => toast({ title: 'Помилка', description: err.detail || 'Спробуйте ще раз.', tone: 'danger' }),
      onSettled: () => setBusyId(null),
    });
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-semibold tracking-tight text-fg">Черга дій</h1>
            <Badge tone="warning">{pendingCount} очікує</Badge>
          </div>
          <p className="max-w-2xl text-sm text-muted">
            Запропоновані агентом дії чекають на підтвердження людини (HITL). Запустити агента можна
            на сторінці проєкту.
          </p>
        </div>
        <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => approvals.refetch()}>
          Оновити
        </Button>
      </header>

      <GuardrailBanner />
      <FlowStrip />

      {approvals.isLoading ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => <Skeleton key={i} className="h-64 w-full" />)}
        </div>
      ) : approvals.isError ? (
        <EmptyState
          icon={Inbox}
          title="Не вдалося завантажити чергу"
          description={approvals.error.status === 0 ? 'Бекенд недоступний.' : approvals.error.detail}
          action={<Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => approvals.refetch()}>Повторити</Button>}
        />
      ) : proposals.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title="Черга порожня"
          description="Поки немає запропонованих дій. Запустіть агента на сторінці проєкту — і пропозиції зʼявляться тут."
        />
      ) : (
        <section aria-label="Запропоновані дії" className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {proposals.map((p) => (
            <ProposalCard
              key={p.id}
              proposal={p}
              busy={busyId === p.id}
              onApprove={() => act(p.id, 'approve')}
              onReject={() => act(p.id, 'reject')}
            />
          ))}
        </section>
      )}

      <p className="flex items-center justify-center gap-2 pt-1 text-center text-xs text-muted">
        <Lock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        Виконання через конектори Jira / Slack / email — наступний крок розвитку.
      </p>
    </div>
  );
}

export default ApprovalsPage;
