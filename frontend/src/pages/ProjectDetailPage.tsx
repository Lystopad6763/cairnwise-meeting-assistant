import {
  useCallback,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  CalendarDays,
  FileAudio,
  HardDrive,
  Inbox,
  RefreshCw,
  UploadCloud,
  X,
} from 'lucide-react';

import { cn } from '../lib/cn';
import {
  useMeetings,
  useProject,
  useTranscribe,
  useUploadMeeting,
} from '../lib/queries';
import { ApiError } from '../lib/api';
import { extOf, formatBytes, formatDate } from '../lib/format';
import {
  ACTIVE_STATUSES,
  ALLOWED_EXT,
  type MeetingOut,
} from '../types';

import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  Input,
  ProgressBar,
  Skeleton,
  StatusBadge,
  useToast,
} from '../components/ui';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB ?? '1024') || 1024;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
const ACCEPT_ATTR = ALLOWED_EXT.join(',');

/** Client-side validation mirroring the server contract. */
function validateFile(file: File): string | null {
  const ext = extOf(file.name);
  if (!(ALLOWED_EXT as readonly string[]).includes(ext)) {
    return 'Непідтримуваний формат';
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `Файл завеликий (ліміт ${MAX_UPLOAD_MB} МБ)`;
  }
  return null;
}

/** Map upload ApiError → friendly Ukrainian copy (per contract §11.5). */
function uploadErrorMessage(err: ApiError): string {
  switch (err.status) {
    case 400:
      return 'Потрібна згода учасників на запис.';
    case 413:
      return `Файл завеликий (ліміт ${MAX_UPLOAD_MB} МБ).`;
    case 415:
      return 'Непідтримуваний формат файлу.';
    case 404:
      return 'Проєкт не знайдено.';
    case 0:
      return 'Бекенд недоступний. Перевірте з’єднання.';
    default:
      return err.detail || 'Не вдалося завантажити зустріч.';
  }
}

// ---------------------------------------------------------------------------
// Upload section
// ---------------------------------------------------------------------------

interface UploadSectionProps {
  projectId: string;
}

function UploadSection({ projectId }: UploadSectionProps) {
  const { toast } = useToast();
  const upload = useUploadMeeting(projectId);

  const inputRef = useRef<HTMLInputElement>(null);
  const consentId = useId();

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [consent, setConsent] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [consentError, setConsentError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);

  const pending = upload.isPending;

  const reset = useCallback(() => {
    setFile(null);
    setTitle('');
    setConsent(false);
    setFileError(null);
    setConsentError(null);
    setProgress(0);
    if (inputRef.current) inputRef.current.value = '';
  }, []);

  const acceptFile = useCallback((f: File) => {
    const err = validateFile(f);
    if (err) {
      setFile(null);
      setFileError(err);
      return;
    }
    setFileError(null);
    setFile(f);
  }, []);

  const onPick = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (f) acceptFile(f);
    },
    [acceptFile],
  );

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOver(false);
      if (pending) return;
      const f = e.dataTransfer.files?.[0];
      if (f) acceptFile(f);
    },
    [acceptFile, pending],
  );

  const onDragOver = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      if (!pending) setDragOver(true);
    },
    [pending],
  );

  const openPicker = useCallback(() => {
    if (!pending) inputRef.current?.click();
  }, [pending]);

  const canSubmit = !!file && consent && !pending;

  const onSubmit = useCallback(() => {
    if (!file) {
      setFileError('Оберіть файл для завантаження');
      return;
    }
    if (!consent) {
      setConsentError('Потрібна згода на запис');
      return;
    }
    setConsentError(null);
    setProgress(0);

    upload.mutate(
      {
        input: { file, title: title.trim() || undefined, consent: true },
        onProgress: setProgress,
      },
      {
        onSuccess: () => {
          toast({
            title: 'Зустріч завантажено',
            description: 'Транскрипція в черзі.',
            tone: 'success',
          });
          reset();
        },
        onError: (err) => {
          const status = err.status;
          if (status === 400) {
            setConsentError('Потрібна згода учасників на запис.');
          } else if (status === 413 || status === 415) {
            setFileError(uploadErrorMessage(err));
          }
          toast({
            title: 'Помилка завантаження',
            description: uploadErrorMessage(err),
            tone: 'danger',
          });
          setProgress(0);
        },
      },
    );
  }, [file, consent, title, upload, toast, reset]);

  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center gap-2">
        <UploadCloud className="h-5 w-5 text-brand" aria-hidden="true" />
        <h2 className="text-sm font-semibold text-fg">Завантажити зустріч</h2>
      </div>

      {/* Dropzone */}
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={() => setDragOver(false)}
        onClick={file ? undefined : openPicker}
        role="button"
        tabIndex={0}
        aria-label="Перетягніть аудіо- або відеофайл або натисніть, щоб обрати"
        onKeyDown={(e) => {
          if (!file && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            openPicker();
          }
        }}
        className={cn(
          'flex flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed px-6 py-8 text-center transition-colors',
          dragOver
            ? 'border-brand bg-brand/5'
            : 'border-border bg-surface-2/40 hover:border-brand/50',
          !file && 'cursor-pointer',
          pending && 'pointer-events-none opacity-60',
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_ATTR}
          className="sr-only"
          onChange={onPick}
          disabled={pending}
        />

        {file ? (
          <div className="flex w-full max-w-md items-center gap-3 rounded-card border border-border bg-surface px-3 py-2 text-left">
            <FileAudio className="h-5 w-5 shrink-0 text-brand" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-fg" title={file.name}>
                {file.name}
              </p>
              <p className="text-xs text-muted">{formatBytes(file.size)}</p>
            </div>
            {!pending && (
              <button
                type="button"
                aria-label="Прибрати файл"
                onClick={(e) => {
                  e.stopPropagation();
                  reset();
                }}
                className="rounded-card p-1 text-muted transition-colors hover:bg-surface-2 hover:text-fg"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        ) : (
          <>
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-muted">
              <UploadCloud className="h-6 w-6" aria-hidden="true" />
            </span>
            <p className="text-sm text-fg">
              Перетягніть файл сюди або{' '}
              <span className="font-medium text-brand">оберіть на пристрої</span>
            </p>
            <p className="text-xs text-muted">
              {ALLOWED_EXT.join(' · ')} — до {MAX_UPLOAD_MB} МБ
            </p>
          </>
        )}
      </div>

      {fileError && (
        <p className="mt-2 text-xs text-status-failed" role="alert">
          {fileError}
        </p>
      )}

      {/* Title + consent + submit — shown once a valid file is chosen */}
      {file && (
        <div className="mt-4 flex flex-col gap-4">
          <Input
            label="Назва (необов’язково)"
            placeholder="Напр., Синк команди — 26.06"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={pending}
            hint="Якщо порожньо, буде використано ім’я файлу."
          />

          <Checkbox
            id={consentId}
            checked={consent}
            disabled={pending}
            error={consentError ?? undefined}
            onChange={(e) => {
              setConsent(e.target.checked);
              if (e.target.checked) setConsentError(null);
            }}
            label={
              <span>
                Підтверджую, що{' '}
                <span className="font-medium text-fg">
                  учасників попереджено про запис
                </span>{' '}
                та отримано згоду на обробку запису.
              </span>
            }
          />

          {pending && (
            <div className="flex flex-col gap-1.5">
              <ProgressBar value={progress} />
              <p className="text-xs text-muted">Завантаження… {progress}%</p>
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <Button
              variant="ghost"
              size="md"
              onClick={reset}
              disabled={pending}
            >
              Скасувати
            </Button>
            <Button
              variant="primary"
              size="md"
              icon={UploadCloud}
              loading={pending}
              disabled={!canSubmit}
              onClick={onSubmit}
            >
              Завантажити
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Meeting row (Re-transcribe action)
// ---------------------------------------------------------------------------

function MeetingRow({ meeting }: { meeting: MeetingOut }) {
  const { toast } = useToast();
  const transcribe = useTranscribe(meeting.id);

  // Re-enqueue makes sense when work hasn't completed: uploaded or failed.
  const canRetranscribe =
    meeting.status === 'uploaded' || meeting.status === 'failed';

  const onRetranscribe = useCallback(() => {
    transcribe.mutate(undefined, {
      onSuccess: () => {
        toast({
          title: 'Поставлено в чергу',
          description: 'Транскрипцію перезапущено.',
          tone: 'info',
        });
      },
      onError: (err) => {
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

  return (
    <tr className="group border-t border-border transition-colors hover:bg-surface-2/40">
      {/* Title → link */}
      <td className="px-4 py-3 align-middle">
        <Link
          to={`/meetings/${meeting.id}`}
          className="flex min-w-0 items-center gap-2.5 text-sm font-medium text-fg hover:text-brand"
        >
          <FileAudio
            className="h-4 w-4 shrink-0 text-muted group-hover:text-brand"
            aria-hidden="true"
          />
          <span className="truncate" title={meeting.title || meeting.filename}>
            {meeting.title || meeting.filename}
          </span>
        </Link>
        {meeting.title && (
          <p
            className="mt-0.5 truncate pl-6 text-xs text-muted"
            title={meeting.filename}
          >
            {meeting.filename}
          </p>
        )}
      </td>

      {/* Status (with error tooltip on failed) */}
      <td className="px-4 py-3 align-middle">
        <span
          title={meeting.status === 'failed' ? meeting.error ?? undefined : undefined}
        >
          <StatusBadge status={meeting.status} />
        </span>
        {meeting.status === 'failed' && meeting.error && (
          <p className="mt-1 max-w-[18rem] truncate text-xs text-status-failed" title={meeting.error}>
            {meeting.error}
          </p>
        )}
      </td>

      {/* Size */}
      <td className="whitespace-nowrap px-4 py-3 align-middle text-sm tabular-nums text-muted">
        {formatBytes(meeting.size_bytes)}
      </td>

      {/* Created */}
      <td className="whitespace-nowrap px-4 py-3 align-middle text-sm text-muted">
        {formatDate(meeting.created_at)}
      </td>

      {/* Actions */}
      <td className="px-4 py-3 align-middle text-right">
        {canRetranscribe ? (
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            loading={transcribe.isPending}
            onClick={onRetranscribe}
          >
            Транскрибувати
          </Button>
        ) : (
          <Link
            to={`/meetings/${meeting.id}`}
            className="text-sm font-medium text-brand hover:underline"
          >
            Відкрити
          </Link>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Meetings table
// ---------------------------------------------------------------------------

function MeetingsTableSkeleton() {
  return (
    <div className="flex flex-col gap-2 p-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

function MeetingsSection({ projectId }: { projectId: string }) {
  const meetings = useMeetings(projectId);

  const rows = meetings.data ?? [];
  const polling = rows.some((m) => ACTIVE_STATUSES.includes(m.status));

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-fg">Зустрічі</h2>
          {rows.length > 0 && (
            <Badge tone="neutral">{rows.length}</Badge>
          )}
          {polling && (
            <Badge tone="info">
              <RefreshCw className="h-3 w-3 animate-spin" aria-hidden="true" />
              Оновлюється
            </Badge>
          )}
        </div>
      </div>

      <Card className="overflow-hidden p-0">
        {meetings.isLoading ? (
          <MeetingsTableSkeleton />
        ) : meetings.isError ? (
          <div className="p-4">
            <EmptyState
              icon={Inbox}
              title="Не вдалося завантажити зустрічі"
              description={
                meetings.error.status === 0
                  ? 'Бекенд недоступний. Перевірте з’єднання та спробуйте ще раз.'
                  : meetings.error.detail
              }
              action={
                <Button
                  variant="secondary"
                  size="sm"
                  icon={RefreshCw}
                  onClick={() => meetings.refetch()}
                >
                  Повторити
                </Button>
              }
            />
          </div>
        ) : rows.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={Inbox}
              title="Ще немає зустрічей"
              description="Завантажте аудіо- чи відеозапис зустрічі вище — щойно файл потрапить у систему, він з’явиться тут і піде в чергу на транскрипцію."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="text-xs font-medium uppercase tracking-wide text-muted">
                  <th className="px-4 py-2.5 font-medium">Назва</th>
                  <th className="px-4 py-2.5 font-medium">Статус</th>
                  <th className="px-4 py-2.5 font-medium">
                    <span className="inline-flex items-center gap-1">
                      <HardDrive className="h-3.5 w-3.5" aria-hidden="true" />
                      Розмір
                    </span>
                  </th>
                  <th className="px-4 py-2.5 font-medium">
                    <span className="inline-flex items-center gap-1">
                      <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
                      Створено
                    </span>
                  </th>
                  <th className="px-4 py-2.5 text-right font-medium">Дії</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => (
                  <MeetingRow key={m.id} meeting={m} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function HeaderSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-80" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function ProjectDetailPage() {
  const { projectId = '' } = useParams<{ projectId: string }>();
  const project = useProject(projectId);

  // A 404 from useProject is surfaced to the route error boundary by throwing.
  // We keep the page resilient: render header skeleton while loading, and a
  // light inline message on non-404 errors (network), but let 404 propagate.
  if (project.isError && project.error.status === 404) {
    throw project.error;
  }

  const data = project.data;

  return (
    <div className="flex flex-col gap-6">
      {/* Back link */}
      <Link
        to="/"
        className="inline-flex w-fit items-center gap-1.5 text-sm text-muted transition-colors hover:text-fg"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Усі проєкти
      </Link>

      {/* Header */}
      {project.isLoading ? (
        <HeaderSkeleton />
      ) : project.isError ? (
        <Card className="p-5">
          <h1 className="text-lg font-semibold text-fg">Проєкт</h1>
          <p className="mt-1 text-sm text-status-failed">
            {project.error.status === 0
              ? 'Бекенд недоступний. Перевірте з’єднання.'
              : project.error.detail}
          </p>
          <div className="mt-3">
            <Button
              variant="secondary"
              size="sm"
              icon={RefreshCw}
              onClick={() => project.refetch()}
            >
              Повторити
            </Button>
          </div>
        </Card>
      ) : data ? (
        <header className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-fg">
              {data.name}
            </h1>
            <Badge tone="brand" className="font-mono">
              {data.slug}
            </Badge>
          </div>
          {data.description ? (
            <p className="max-w-2xl text-sm text-muted">{data.description}</p>
          ) : (
            <p className="text-sm text-muted/70">Без опису</p>
          )}
          <p className="text-xs text-muted">Створено {formatDate(data.created_at)}</p>
        </header>
      ) : null}

      {/* Tabs (only "Зустрічі" active; others disabled per contract) */}
      <nav
        className="flex items-center gap-1 border-b border-border"
        aria-label="Розділи проєкту"
      >
        <span className="-mb-px border-b-2 border-brand px-3 py-2 text-sm font-medium text-fg">
          Зустрічі
        </span>
        {(['Підсумки', 'Дії', 'Чат'] as const).map((label) => (
          <span
            key={label}
            aria-disabled="true"
            className="flex cursor-not-allowed items-center gap-1.5 px-3 py-2 text-sm text-muted/60"
          >
            {label}
            <Badge tone="neutral">Скоро</Badge>
          </span>
        ))}
      </nav>

      {/* Upload */}
      {projectId && <UploadSection projectId={projectId} />}

      {/* Meetings table */}
      {projectId && <MeetingsSection projectId={projectId} />}
    </div>
  );
}

export default ProjectDetailPage;
