import { useCallback, useEffect, useId, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Mic,
  Radio,
  Square,
  UploadCloud,
  X,
} from 'lucide-react';

import { cn } from '../lib/cn';
import { formatBytes } from '../lib/format';
import { useUploadMeeting } from '../lib/queries';
import {
  recorderErrorMessage,
  recordingSupported,
  startRecording,
  type RecorderHandle,
} from '../lib/recorder';
import {
  Button,
  Card,
  Checkbox,
  Input,
  ProgressBar,
  useToast,
} from './ui';

type Phase = 'setup' | 'recording' | 'review';

function mmss(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/** meeting-YYYYMMDD-HHmmss.webm — стабільна, читабельна назва запису. */
function recordingFilename(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `meeting-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.webm`;
}

interface RecordMeetingProps {
  projectId: string;
  onClose: () => void;
}

/**
 * Модалка запису живої зустрічі: мікрофон + системний звин (інша сторона дзвінка) → webm → upload.
 * Запис тримається в памʼяті браузера; на бекенд іде лише після явного «Завантажити».
 */
export function RecordMeeting({ projectId, onClose }: RecordMeetingProps) {
  const { toast } = useToast();
  const upload = useUploadMeeting(projectId);
  const consentId = useId();

  const supported = recordingSupported();

  const [phase, setPhase] = useState<Phase>('setup');
  const [consent, setConsent] = useState(false);
  const [title, setTitle] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [systemAudio, setSystemAudio] = useState(false);
  const [micOn, setMicOn] = useState(true);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);

  const handleRef = useRef<RecorderHandle | null>(null);
  const timerRef = useRef<number | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current != null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Прибирання при розмонтуванні (якщо запис ще активний).
  useEffect(() => {
    return () => {
      clearTimer();
      handleRef.current?.cancel();
    };
  }, [clearTimer]);

  const onStart = useCallback(async () => {
    setError(null);
    try {
      const handle = await startRecording();
      handleRef.current = handle;
      setSystemAudio(handle.hasSystemAudio);
      setMicOn(handle.hasMic);
      setElapsed(0);
      setPhase('recording');
      timerRef.current = window.setInterval(() => setElapsed((e) => e + 1), 1000);
    } catch (err) {
      setError(recorderErrorMessage(err));
    }
  }, []);

  const onStop = useCallback(async () => {
    clearTimer();
    const handle = handleRef.current;
    if (!handle) return;
    const recorded = await handle.stop();
    handleRef.current = null;
    setBlob(recorded);
    setPhase('review');
  }, [clearTimer]);

  const onUpload = useCallback(() => {
    if (!blob) return;
    setProgress(0);
    const file = new File([blob], recordingFilename(), {
      type: blob.type || 'audio/webm',
    });
    upload.mutate(
      {
        input: { file, title: title.trim() || undefined, consent: true },
        onProgress: setProgress,
      },
      {
        onSuccess: () => {
          toast({
            title: 'Зустріч завантажено',
            description: 'Запис у черзі на транскрипцію.',
            tone: 'success',
          });
          onClose();
        },
        onError: (err) => {
          toast({
            title: 'Помилка завантаження',
            description: err.detail || 'Не вдалося завантажити запис.',
            tone: 'danger',
          });
          setProgress(0);
        },
      },
    );
  }, [blob, title, upload, toast, onClose]);

  const onCancelAll = useCallback(() => {
    clearTimer();
    handleRef.current?.cancel();
    handleRef.current = null;
    onClose();
  }, [clearTimer, onClose]);

  const pending = upload.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Запис зустрічі"
      onClick={phase === 'recording' ? undefined : onCancelAll}
    >
      <Card
        className="w-full max-w-md p-5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="mb-4 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-card bg-brand/15 text-brand">
              <Mic className="h-4.5 w-4.5" aria-hidden="true" />
            </span>
            <h2 className="text-sm font-semibold text-fg">Жива зустріч</h2>
          </div>
          {phase !== 'recording' && (
            <button
              type="button"
              aria-label="Закрити"
              onClick={onCancelAll}
              className="rounded-card p-1 text-muted transition-colors hover:bg-surface-2 hover:text-fg"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {!supported ? (
          <div className="flex items-start gap-2 rounded-card border border-status-failed/30 bg-status-failed/10 px-3 py-2 text-sm text-status-failed">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            Браузер не підтримує запис (потрібні MediaRecorder + getUserMedia). Спробуйте Chrome/Edge.
          </div>
        ) : phase === 'setup' ? (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted">
              Запишемо <span className="font-medium text-fg">мікрофон + системний звук</span>{' '}
              (інша сторона дзвінка). На крок «Поділитися звуком» оберіть вкладку/екран і
              поставте галочку «Share audio». Запис лишається локально.
            </p>

            <Input
              label="Назва (необовʼязково)"
              placeholder="Напр., Дейлі — 30.06"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              hint="Якщо порожньо, буде використано назву файлу."
            />

            <Checkbox
              id={consentId}
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              label={
                <span>
                  Підтверджую, що{' '}
                  <span className="font-medium text-fg">учасників попереджено про запис</span>{' '}
                  та отримано згоду.
                </span>
              }
            />

            {error && (
              <p className="text-xs text-status-failed" role="alert">
                {error}
              </p>
            )}

            <div className="flex items-center justify-end gap-2">
              <Button variant="ghost" size="md" onClick={onCancelAll}>
                Скасувати
              </Button>
              <Button
                variant="primary"
                size="md"
                icon={Mic}
                disabled={!consent}
                onClick={onStart}
              >
                Почати запис
              </Button>
            </div>
          </div>
        ) : phase === 'recording' ? (
          <div className="flex flex-col items-center gap-5 py-4">
            <div className="flex items-center gap-2 text-status-failed">
              <span className="h-3 w-3 animate-pulseDot rounded-full bg-status-failed" />
              <span className="text-xs font-medium uppercase tracking-wide">Запис</span>
            </div>
            <div className="font-mono text-4xl tabular-nums text-fg">{mmss(elapsed)}</div>

            <div className="flex flex-wrap items-center justify-center gap-2 text-xs">
              <span
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-pill border px-2.5 py-1',
                  micOn
                    ? 'border-status-transcribed/40 bg-status-transcribed/10 text-fg'
                    : 'border-border bg-surface-2/60 text-muted',
                )}
              >
                <Mic className="h-3.5 w-3.5" aria-hidden="true" />
                {micOn ? 'Мікрофон' : 'Без мікрофона'}
              </span>
              <span
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-pill border px-2.5 py-1',
                  systemAudio
                    ? 'border-status-transcribed/40 bg-status-transcribed/10 text-fg'
                    : 'border-border bg-surface-2/60 text-muted',
                )}
              >
                <Radio className="h-3.5 w-3.5" aria-hidden="true" />
                {systemAudio ? 'Системний звук' : 'Без системного звуку'}
              </span>
            </div>

            <Button variant="danger" size="md" icon={Square} onClick={onStop}>
              Зупинити запис
            </Button>
          </div>
        ) : (
          /* review */
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2 rounded-card border border-status-transcribed/30 bg-status-transcribed/10 px-3 py-2.5 text-sm">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-status-transcribed" aria-hidden="true" />
              <span className="text-fg">
                Записано {mmss(elapsed)} · {blob ? formatBytes(blob.size) : '—'}
              </span>
            </div>

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
                disabled={pending}
                onClick={() => {
                  setBlob(null);
                  setElapsed(0);
                  setProgress(0);
                  setPhase('setup');
                }}
              >
                Перезаписати
              </Button>
              <Button
                variant="primary"
                size="md"
                icon={UploadCloud}
                loading={pending}
                disabled={!blob || pending}
                onClick={onUpload}
              >
                Завантажити
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

export default RecordMeeting;
