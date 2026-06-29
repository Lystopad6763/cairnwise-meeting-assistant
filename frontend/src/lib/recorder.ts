/**
 * Запис «живої» зустрічі у браузері: мікрофон + системний звук (інша сторона дзвінка),
 * змішані в один трек і записані у webm. Усе локально — Blob нікуди не йде, доки користувач
 * сам не натисне «Завантажити».
 *
 * Порядок джерел важливий: getDisplayMedia СУВОРО вимагає свіжої user-activation, тож його
 * викликаємо ПЕРШИМ (одразу після кліку), бо `await getUserMedia` перед ним зʼїв би активацію
 * і Chrome кинув би InvalidStateError. Обидва джерела опційні поодинці, але хоча б одне має
 * бути: інакше нема що писати. Системний звук беремо через getDisplayMedia({audio}); у Chrome
 * це вимагає video:true, щоб зʼявилася опція «Поділитися звуком вкладки/екрана». Відеотрек ми
 * НЕ записуємо — лише аудіо обох джерел зводимо через AudioContext.
 */

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm'] as const;

function pickMimeType(): string {
  for (const m of MIME_CANDIDATES) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(m)) return m;
  }
  return '';
}

export function recordingSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined' &&
    typeof AudioContext !== 'undefined'
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

export interface RecorderHandle {
  /** Зупинити запис і отримати фінальний Blob (звільняє всі ресурси). */
  stop: () => Promise<Blob>;
  /** Скасувати без результату (звільняє ресурси). */
  cancel: () => void;
  hasMic: boolean;
  hasSystemAudio: boolean;
  mimeType: string;
}

/**
 * Стартує запис. Кидає (з .name для recorderErrorMessage), якщо НЕ вдалося отримати ЖОДНОГО
 * джерела звуку. Якщо доступне хоча б одне (мікрофон АБО системний звук) — пишемо його.
 */
export async function startRecording(): Promise<RecorderHandle> {
  const mimeType = pickMimeType();
  const blobType = mimeType || 'audio/webm';

  let displayStream: MediaStream | null = null;
  let micStream: MediaStream | null = null;

  // 1) Системний звук — ПЕРШИМ (поки активація свіжа). Опційно: відмова/скасування -> без нього.
  try {
    if (navigator.mediaDevices.getDisplayMedia) {
      displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      if (displayStream.getAudioTracks().length === 0) {
        // Поділилися екраном без звуку — відеотрек нам не потрібен.
        displayStream.getTracks().forEach((t) => t.stop());
        displayStream = null;
      }
    }
  } catch {
    displayStream = null; // відмова/скасування — лишаємось на мікрофоні
  }

  // 2) Мікрофон. Якщо впав, але є системний звук — продовжуємо без мікрофона.
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
  } catch (err) {
    micStream = null;
    if (!displayStream) {
      // жодного джерела — прибираємо й кидаємо ПРИЧИНУ (mic-помилку) нагору
      throw err;
    }
  }

  if (!micStream && !displayStream) {
    throw new DOMException('no audio source', 'NoAudioSource');
  }

  // 3) Мікс наявних джерел у один аудіотрек.
  const ctx = new AudioContext();
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

  const recorder = new MediaRecorder(dest.stream, mimeType ? { mimeType } : undefined);
  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (e: BlobEvent) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };
  recorder.start(1000); // timeslice 1с — стабільніше для довгих записів

  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    micStream?.getTracks().forEach((t) => t.stop());
    displayStream?.getTracks().forEach((t) => t.stop());
    ctx.close().catch(() => {});
  };

  return {
    hasMic: !!micStream,
    hasSystemAudio: !!displayStream,
    mimeType: blobType,
    stop: () =>
      new Promise<Blob>((resolve) => {
        const finish = () => {
          release();
          resolve(new Blob(chunks, { type: blobType }));
        };
        if (recorder.state === 'inactive') {
          finish();
          return;
        }
        recorder.onstop = finish;
        recorder.stop();
      }),
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
