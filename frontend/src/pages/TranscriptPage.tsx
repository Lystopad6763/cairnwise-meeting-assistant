import { useCallback, useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowLeft,
  BookOpenCheck,
  Clock,
  FileAudio,
  Languages,
  Loader2,
  Mic,
  RefreshCw,
  ScrollText,
  Timer,
  Users,
} from 'lucide-react';

import { cn } from '../lib/cn';
import { useMeeting, useTranscribe, useTranscript } from '../lib/queries';
import { ApiError } from '../lib/api';
import { formatDate, formatDuration, formatTimestamp } from '../lib/format';
import { distinctSpeakers, speakerToken } from '../lib/speakers';
import { STATUS_META } from '../components/ui/StatusBadge';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Skeleton,
  StatusBadge,
  useToast,
} from '../components/ui';
import type { MeetingOut, Segment, SpeakerLabels, TranscriptOut } from '../types';

import { SpeakerRelabel } from '../components/SpeakerRelabel';
import { SummaryRail } from '../components/SummaryRail';
import { displaySpeaker } from '../lib/summary';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Short model name for the meta header (drop org prefix, keep tail). */
function shortName(value: string | null | undefined): string {
  if (!value) return '—';
  const tail = value.split('/').pop() ?? value;
  return tail;
}

/** Per-speaker reply count, keyed by speaker label. */
function replyCounts(segments: Segment[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const s of segments) {
    out[s.speaker] = (out[s.speaker] ?? 0) + 1;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Re-transcribe button (shown for uploaded / failed)
// ---------------------------------------------------------------------------

function RetranscribeButton({ meeting }: { meeting: MeetingOut }) {
  const { toast } = useToast();
  const transcribe = useTranscribe(meeting.id);

  const onClick = useCallback(() => {
    transcribe.mutate(undefined, {
      onSuccess: () => {
        toast({
          title: 'Поставлено в чергу',
          description: 'Транскрипцію перезапущено.',
          tone: 'info',
        });
      },
      onError: (err: ApiError) => {
        toast({
          title: 'Не вдалося поставити в чергу',
          description:
            err.status === 503
              ? 'Черга недоступна, спробуйте пізніше'
              : err.detail || 'Спробуйте ще раз пізніше.',
          tone: 'danger',
        });
      },
    });
  }, [transcribe, toast]);

  const label = meeting.status === 'failed' ? 'Спробувати знову' : 'Транскрибувати';

  return (
    <Button
      variant="secondary"
      size="sm"
      icon={RefreshCw}
      loading={transcribe.isPending}
      onClick={onClick}
    >
      {label}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Status panel — shown while not transcribed (polling / failed)
// ---------------------------------------------------------------------------

function StatusPanel({ meeting }: { meeting: MeetingOut }) {
  const meta = STATUS_META[meeting.status];
  const Icon = meta.icon;
  const spinning = meeting.status === 'transcribing';

  const copy: Record<MeetingOut['status'], string> = {
    uploaded:
      'Зустріч у черзі на транскрипцію. Сторінка оновиться автоматично, щойно почнеться обробка.',
    transcribing:
      'Розпізнаємо мовлення та розділяємо за спікерами. Це може зайняти кілька хвилин залежно від тривалості запису.',
    transcribed: 'Готово.',
    ingesting: 'Індексуємо зустріч у памʼять проєкту…',
    ingested: 'Зустріч у памʼяті проєкту.',
    failed:
      'Під час транскрипції сталася помилка. Можна перезапустити обробку нижче.',
  };

  return (
    <Card className="flex flex-col items-center gap-4 px-6 py-12 text-center">
      <span
        className={cn(
          'flex h-14 w-14 items-center justify-center rounded-full',
          meeting.status === 'failed'
            ? 'bg-status-failed/15 text-status-failed'
            : 'bg-surface-2 text-brand',
        )}
      >
        <Icon
          className={cn('h-7 w-7', spinning && 'animate-spin')}
          aria-hidden="true"
        />
      </span>

      <div className="flex flex-col items-center gap-2">
        <StatusBadge status={meeting.status} />
        <p className="max-w-md text-sm text-muted">{copy[meeting.status]}</p>
      </div>

      {/* Animated polling indicator for non-terminal states */}
      {(meeting.status === 'uploaded' || meeting.status === 'transcribing') && (
        <div className="flex items-center gap-2 text-xs text-muted" role="status">
          <span className="flex gap-1">
            <span className="h-1.5 w-1.5 animate-pulseDot rounded-full bg-status-transcribing" />
            <span
              className="h-1.5 w-1.5 animate-pulseDot rounded-full bg-status-transcribing"
              style={{ animationDelay: '0.2s' }}
            />
            <span
              className="h-1.5 w-1.5 animate-pulseDot rounded-full bg-status-transcribing"
              style={{ animationDelay: '0.4s' }}
            />
          </span>
          Очікуємо оновлення…
        </div>
      )}

      {/* Failure detail + retry */}
      {meeting.status === 'failed' && (
        <>
          {meeting.error && (
            <div className="flex max-w-md items-start gap-2 rounded-card border border-status-failed/30 bg-status-failed/10 px-3 py-2 text-left text-xs text-status-failed">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="break-words">{meeting.error}</span>
            </div>
          )}
          <RetranscribeButton meeting={meeting} />
        </>
      )}

      {meeting.status === 'uploaded' && <RetranscribeButton meeting={meeting} />}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Transcript metadata header
// ---------------------------------------------------------------------------

function MetaItem({
  icon: Icon,
  label,
  value,
  title,
}: {
  icon: typeof Mic;
  label: string;
  value: React.ReactNode;
  title?: string;
}) {
  return (
    <div className="flex items-center gap-2.5" title={title}>
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-card bg-surface-2 text-muted">
        <Icon className="h-4 w-4" aria-hidden="true" />
      </span>
      <div className="min-w-0 leading-tight">
        <p className="text-[11px] uppercase tracking-wide text-muted">{label}</p>
        <p className="truncate text-sm font-medium text-fg">{value}</p>
      </div>
    </div>
  );
}

function TranscriptMeta({ transcript }: { transcript: TranscriptOut }) {
  const { compute_secs, duration_s } = transcript;
  const rtf =
    compute_secs != null && duration_s > 0 ? compute_secs / duration_s : null;

  return (
    <Card className="p-4">
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        <MetaItem
          icon={Mic}
          label="Модель"
          value={shortName(transcript.model)}
          title={transcript.model}
        />
        <MetaItem
          icon={Users}
          label="Діаризація"
          value={shortName(transcript.diarizer)}
          title={transcript.diarizer ?? undefined}
        />
        <MetaItem
          icon={Languages}
          label="Мова"
          value={(transcript.language ?? '—').toUpperCase()}
        />
        <MetaItem
          icon={Users}
          label="Спікерів"
          value={transcript.num_speakers || '—'}
        />
        <MetaItem
          icon={Clock}
          label="Тривалість"
          value={formatDuration(transcript.duration_s)}
        />
        <MetaItem
          icon={Timer}
          label="Швидкість (RTF)"
          value={
            rtf != null ? (
              <span className="font-mono tabular-nums">×{rtf.toFixed(2)}</span>
            ) : (
              '—'
            )
          }
          title={
            compute_secs != null
              ? `Обчислення: ${formatDuration(compute_secs)}`
              : undefined
          }
        />
      </div>

      {transcript.glossary && (
        <div className="mt-3 border-t border-border pt-3">
          <Badge tone="brand">
            <BookOpenCheck className="h-3.5 w-3.5" aria-hidden="true" />
            Глосарій застосовано
          </Badge>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Speaker legend (per-speaker reply counts)
// ---------------------------------------------------------------------------

function SpeakerLegend({
  speakers,
  counts,
  labels,
}: {
  speakers: string[];
  counts: Record<string, number>;
  labels: SpeakerLabels;
}) {
  if (speakers.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {speakers.map((label) => {
        const tok = speakerToken(label);
        return (
          <span
            key={label}
            className="inline-flex items-center gap-1.5 rounded-pill border bg-surface-2/60 px-2.5 py-1 text-xs"
            style={{ borderColor: `${tok.border}55` }}
          >
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: tok.dot }}
              aria-hidden="true"
            />
            <span className="font-medium text-fg">{displaySpeaker(labels, label)}</span>
            <span className="tabular-nums text-muted">
              {counts[label] ?? 0} реплік
            </span>
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Segment row (citation anchor: id=seg-{index}, data-start)
// ---------------------------------------------------------------------------

function SegmentRow({
  segment,
  index,
  collapsedHeader,
  labels,
}: {
  segment: Segment;
  index: number;
  collapsedHeader: boolean;
  labels: SpeakerLabels;
}) {
  const tok = speakerToken(segment.speaker);
  return (
    <li
      id={`seg-${index}`}
      data-start={segment.start}
      className="group grid grid-cols-[3.5rem_1fr] gap-3 px-1 py-1.5"
    >
      {/* Timestamp gutter */}
      <div
        className="select-none pt-0.5 text-right font-mono text-xs tabular-nums text-muted"
        title={`${formatTimestamp(segment.start)} – ${formatTimestamp(segment.end)}`}
      >
        {formatTimestamp(segment.start)}
      </div>

      {/* Colored left border + speaker header + text */}
      <div
        className="border-l-2 pl-3"
        style={{ borderColor: `${tok.border}66` }}
      >
        {!collapsedHeader && (
          <div className="mb-0.5 flex items-center gap-1.5">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: tok.dot }}
              aria-hidden="true"
            />
            <span
              className="text-xs font-semibold"
              style={{ color: tok.text }}
            >
              {displaySpeaker(labels, segment.speaker)}
            </span>
          </div>
        )}
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
          {segment.text}
        </p>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Transcript viewer
// ---------------------------------------------------------------------------

function TranscriptViewer({ transcript }: { transcript: TranscriptOut }) {
  const { segments } = transcript;
  const labels = transcript.speaker_labels ?? {};
  const speakers = useMemo(() => distinctSpeakers(segments), [segments]);
  const counts = useMemo(() => replyCounts(segments), [segments]);

  return (
    <div className="flex flex-col gap-4">
      <TranscriptMeta transcript={transcript} />

      <SpeakerLegend speakers={speakers} counts={counts} labels={labels} />

      <SpeakerRelabel
        meetingId={transcript.meeting_id}
        speakers={speakers}
        labels={labels}
      />

      <Card className="p-4">
        <div className="mb-3 flex items-center gap-2">
          <ScrollText className="h-4 w-4 text-brand" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-fg">Транскрипт</h2>
          <Badge tone="neutral">{segments.length} реплік</Badge>
        </div>

        {segments.length === 0 ? (
          <EmptyState
            icon={Mic}
            title="Порожній транскрипт"
            description="Розпізнавання завершилося без сегментів мовлення."
          />
        ) : (
          <ol className="flex flex-col divide-y divide-border/60">
            {segments.map((seg, i) => {
              const collapsed = i > 0 && segments[i - 1].speaker === seg.speaker;
              return (
                <SegmentRow
                  key={i}
                  segment={seg}
                  index={i}
                  collapsedHeader={collapsed}
                  labels={labels}
                />
              );
            })}
          </ol>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Transcript-not-ready (worker race: status transcribed but 404 transcript)
// ---------------------------------------------------------------------------

function TranscriptPending({ onRefresh }: { onRefresh: () => void }) {
  return (
    <Card className="flex flex-col items-center gap-4 px-6 py-12 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-brand">
        <Loader2 className="h-6 w-6 animate-spin" aria-hidden="true" />
      </span>
      <div className="flex flex-col items-center gap-1">
        <p className="text-sm font-medium text-fg">Транскрипт готується…</p>
        <p className="max-w-sm text-sm text-muted">
          Статус уже «Готово», але дані ще синхронізуються. Спробуйте оновити за
          кілька секунд.
        </p>
      </div>
      <Button variant="secondary" size="sm" icon={RefreshCw} onClick={onRefresh}>
        Оновити
      </Button>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Loading / left-column skeletons
// ---------------------------------------------------------------------------

function LeftSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-8 w-64" />
      <div className="flex flex-col gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Left column — header + body
// ---------------------------------------------------------------------------

function MeetingHeader({ meeting }: { meeting: MeetingOut }) {
  const showRetry =
    meeting.status === 'uploaded' || meeting.status === 'failed';

  return (
    <header className="flex flex-col gap-3">
      <Link
        to={`/projects/${meeting.project_id}`}
        className="inline-flex w-fit items-center gap-1.5 text-sm text-muted transition-colors hover:text-fg"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        До проєкту
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-card bg-surface-2 text-brand">
            <FileAudio className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h1
              className="truncate text-xl font-semibold tracking-tight text-fg"
              title={meeting.title || meeting.filename}
            >
              {meeting.title || meeting.filename}
            </h1>
            <p className="mt-0.5 truncate text-xs text-muted" title={meeting.filename}>
              {meeting.filename} · {formatDate(meeting.created_at)}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <StatusBadge status={meeting.status} />
          {showRetry && <RetranscribeButton meeting={meeting} />}
        </div>
      </div>
    </header>
  );
}

function LeftColumn({ meetingId }: { meetingId: string }) {
  const meeting = useMeeting(meetingId);

  // Let a 404 propagate to the route error boundary (treats it as not-found).
  if (meeting.isError && meeting.error.status === 404) {
    throw meeting.error;
  }

  const data = meeting.data;
  const status = data?.status;

  const transcript = useTranscript(meetingId, status);

  if (meeting.isLoading) {
    return <LeftSkeleton />;
  }

  if (meeting.isError) {
    return (
      <Card className="p-5">
        <h1 className="text-lg font-semibold text-fg">Зустріч</h1>
        <p className="mt-1 text-sm text-status-failed">
          {meeting.error.status === 0
            ? 'Бекенд недоступний. Перевірте з’єднання.'
            : meeting.error.detail}
        </p>
        <div className="mt-3">
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            onClick={() => meeting.refetch()}
          >
            Повторити
          </Button>
        </div>
      </Card>
    );
  }

  if (!data) return null;

  // Транскрипт існує у будь-якому пост-transcribed стані (ingesting/ingested теж).
  const hasTranscript =
    status === 'transcribed' || status === 'ingesting' || status === 'ingested';

  // Worker race: meeting says transcribed but transcript endpoint 404s.
  const transcriptNotReady =
    hasTranscript && transcript.isError && transcript.error.status === 404;

  return (
    <div className="flex flex-col gap-5">
      <MeetingHeader meeting={data} />

      {!hasTranscript ? (
        <StatusPanel meeting={data} />
      ) : transcript.isLoading ? (
        <LeftSkeleton />
      ) : transcriptNotReady ? (
        <TranscriptPending onRefresh={() => transcript.refetch()} />
      ) : transcript.isError ? (
        <Card className="p-5">
          <div className="flex items-center gap-2 text-status-failed">
            <AlertTriangle className="h-5 w-5" aria-hidden="true" />
            <h2 className="text-sm font-semibold">Не вдалося завантажити транскрипт</h2>
          </div>
          <p className="mt-1 text-sm text-muted">
            {transcript.error.status === 0
              ? 'Бекенд недоступний. Перевірте з’єднання.'
              : transcript.error.detail}
          </p>
          <div className="mt-3">
            <Button
              variant="secondary"
              size="sm"
              icon={RefreshCw}
              onClick={() => transcript.refetch()}
            >
              Повторити
            </Button>
          </div>
        </Card>
      ) : transcript.data ? (
        <TranscriptViewer transcript={transcript.data} />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function TranscriptPage() {
  const { meetingId = '' } = useParams<{ meetingId: string }>();

  if (!meetingId) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Зустріч не вказано"
        description="Невірне посилання на зустріч."
        action={
          <Link to="/" className="text-sm font-medium text-brand hover:underline">
            На головну
          </Link>
        }
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] xl:grid-cols-[minmax(0,1fr)_24rem]">
      {/* LEFT — meeting + transcript */}
      <div className="min-w-0">
        <LeftColumn meetingId={meetingId} />
      </div>

      {/* RIGHT — AI Summary rail (Агент-2, Фаза 7) */}
      <div className="lg:sticky lg:top-6 lg:self-start">
        <SummaryRail meetingId={meetingId} />
      </div>
    </div>
  );
}

export default TranscriptPage;
