/**
 * Запис «живої» зустрічі у браузері: мікрофон + системний звук (інша сторона дзвінка),
 * змішані в один трек. Усе локально — Blob нікуди не йде, доки користувач не натисне «Завантажити».
 *
 * Системний звук беремо через getDisplayMedia({audio}) — у Chrome це вимагає video:true, щоб
 * зʼявилась опція «Поділитися звуком вкладки/екрана». getDisplayMedia СУВОРО вимагає свіжої
 * user-activation, тож кличемо його ПЕРШИМ. Обидва джерела опційні поодинці, але хоча б одне
 * має бути. Кодек обираємо за підтримкою браузера (webm/opus, інакше mp4/aac для Safari) і
 * стампуємо Blob РЕАЛЬНИМ типом рекордера, а не припущенням.
 */

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4;codecs=mp4a.40.2',   // Safari: MediaRecorder не вміє webm
  'audio/mp4',
] as const;

function pickMimeType(): string {
  for (const m of MIME_CANDIDATES) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported?.(m)) return m;
  }
  return '';
}

function audioContextCtor(): typeof AudioContext | undefined {
  if (typeof AudioContext !== 'undefined') return AudioContext;
  // Safari/iOS експонують лише webkitAudioContext.
  return (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
}

export function recordingSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined' &&
    !!audioContextCtor()
  );
}

/** Людська підказка за DOMException.name — щоб користувач бачив ПРИЧИНУ, а не загальне «не вдалося». */
export function recorderErrorMessage(err: unknown): string {
  const e = err as { name?: string; message?: string } | undefined;
  const name = e?.name ?? 'Error';
  const map: Record<string, string> = {
    NotAllowedError: 'Доступ до мікрофона/звуку відхилено. Дозвольте у налаштуваннях браузера та спробуйте ще раз.',
    NotFoundError: 'Не знайдено мікрофон. Підключіть аудіопристрій і спробуйте ще раз.',
    NotReadableError: 'Мікрофон зайнятий іншою програмою (напр. Zoom/Meet). Закрийте її та повторіть.',
    OverconstrainedError: 'Пристрій не підтримує потрібні параметри запису.',
    SecurityError: 'Запис доступний лише на https або localhost.',
    NoAudioSource: 'Не вибрано жодного джерела звуку (ні мікрофон, ні системний звук).',
  };
  const base = map[name] ?? e?.message ?? 'Не вдалося почати запис.';
  return `${base} [${name}]`;
}

/** Розширення файлу за реальним MIME рекордера (узгоджено зі серверним allowlist). */
export function extForMime(type: string): string {
  if (type.includes('mp4')) return 'm4a';
  if (type.includes('ogg')) return 'ogg';
  return 'webm';
}

export interface StartOptions {
  mic?: boolean;                       // писати мікрофон (дефолт true)
  systemAudio?: boolean;               // питати системний звук (дефолт true)
  onSystemAudioLost?: () => void;      // користувач натиснув «Stop sharing» під час запису
}

export interface RecorderHandle {
  /** Зупинити запис і отримати фінальний Blob (ідемпотентно; звільняє ресурси). */
  stop: () => Promise<Blob>;
  /** Скасувати без результату (звільняє ресурси). */
  cancel: () => void;
  hasMic: boolean;
  hasSystemAudio: boolean;
  mimeType: string;
}

export async function startRecording(opts: StartOptions = {}): Promise<RecorderHandle> {
  const wantMic = opts.mic !== false;
  const wantSystem = opts.systemAudio !== false;
  const preferredMime = pickMimeType();

  let displayStream: MediaStream | null = null;
  let micStream: MediaStream | null = null;

  // 1) Системний звук — ПЕРШИМ (поки активація свіжа). Опційно.
  if (wantSystem) {
    try {
      if (navigator.mediaDevices.getDisplayMedia) {
        displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
        if (displayStream.getAudioTracks().length === 0) {
          displayStream.getTracks().forEach((t) => t.stop());
          displayStream = null;
        }
      }
    } catch {
      displayStream = null; // відмова/скасування — лишаємось на мікрофоні
    }
  }

  // 2) Мікрофон. Якщо впав, але є системний звук — продовжуємо без мікрофона.
  if (wantMic) {
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch (err) {
      micStream = null;
      if (!displayStream) throw err; // жодного джерела — кидаємо ПРИЧИНУ нагору
    }
  }

  if (!micStream && !displayStream) {
    throw new DOMException('no audio source', 'NoAudioSource');
  }

  // 3) Мікс наявних джерел у один аудіотрек.
  const AC = audioContextCtor();
  if (!AC) throw new DOMException('AudioContext unavailable', 'NotSupportedError');
  const ctx = new AC();
  if (ctx.state === 'suspended') {
    try {
      await ctx.resume();
    } catch {
      /* ignore */
    }
  }
  const dest = ctx.createMediaStreamDestination();
  if (micStream) ctx.createMediaStreamSource(micStream).connect(dest);
  if (displayStream) ctx.createMediaStreamSource(displayStream).connect(dest);

  const recorder = new MediaRecorder(dest.stream, preferredMime ? { mimeType: preferredMime } : undefined);
  // Реальний тип, який ПИШЕ браузер (Safari -> audio/mp4), а не наше припущення.
  const actualType = recorder.mimeType || preferredMime || 'audio/webm';

  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (e: BlobEvent) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };
  recorder.start(1000); // timeslice 1с — стабільніше для довгих записів

  // Користувач натиснув нативне «Stop sharing» -> системний трек вмирає; повідомляємо нагору.
  if (displayStream && opts.onSystemAudioLost) {
    displayStream.getAudioTracks().forEach((t) =>
      t.addEventListener('ended', () => opts.onSystemAudioLost?.(), { once: true }),
    );
  }

  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    micStream?.getTracks().forEach((t) => t.stop());
    displayStream?.getTracks().forEach((t) => t.stop());
    ctx.close().catch(() => {});
  };

  // Memoized — повторний stop() повертає той самий проміс (не перезаписує onstop -> не зависає).
  let stopPromise: Promise<Blob> | null = null;
  const stop = () => {
    if (stopPromise) return stopPromise;
    stopPromise = new Promise<Blob>((resolve) => {
      const finish = () => {
        release();
        resolve(new Blob(chunks, { type: actualType }));
      };
      if (recorder.state === 'inactive') {
        finish();
        return;
      }
      recorder.onstop = finish;
      recorder.stop();
    });
    return stopPromise;
  };

  return {
    hasMic: !!micStream,
    hasSystemAudio: !!displayStream,
    mimeType: actualType,
    stop,
    cancel: () => {
      try {
        if (recorder.state !== 'inactive') recorder.stop();
      } catch {
        /* ignore */
      }
      release();
    },
  };
}
