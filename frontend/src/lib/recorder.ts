/**
 * Запис «живої» зустрічі у браузері: мікрофон + системний звук (інша сторона дзвінка),
 * змішані в один трек і записані у webm. Усе локально — Blob нікуди не йде, доки користувач
 * сам не натисне «Завантажити».
 *
 * Системний звук беремо через getDisplayMedia({audio}); у Chrome це вимагає video:true, щоб
 * зʼявилася опція «Поділитися звуком вкладки/екрана». Відеотрек ми НЕ записуємо — лише
 * аудіо обох джерел зводимо через AudioContext у MediaStreamDestination і пишемо його.
 * Якщо системний звук не надано (користувач не поставив галочку / скасував) — пишемо лише мікрофон.
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

export interface RecorderHandle {
  /** Зупинити запис і отримати фінальний Blob (звільняє всі ресурси). */
  stop: () => Promise<Blob>;
  /** Скасувати без результату (звільняє ресурси). */
  cancel: () => void;
  /** Чи реально захоплено системний звук (галочка «Share audio»). */
  hasSystemAudio: boolean;
  mimeType: string;
}

/**
 * Стартує запис. Кидає, якщо відмовлено в мікрофоні (мінімальна вимога). Системний звук —
 * best-effort: відмова/скасування не валить запис, лишається моно-режим (мікрофон).
 */
export async function startRecording(): Promise<RecorderHandle> {
  const mimeType = pickMimeType();
  const blobType = mimeType || 'audio/webm';

  // 1) Мікрофон — обовʼязковий.
  const micStream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
  });

  // 2) Системний звук — опційний.
  let displayStream: MediaStream | null = null;
  let hasSystemAudio = false;
  try {
    if (navigator.mediaDevices.getDisplayMedia) {
      displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      hasSystemAudio = displayStream.getAudioTracks().length > 0;
      if (!hasSystemAudio) {
        // Користувач поділився екраном без звуку — відеотрек нам не потрібен.
        displayStream.getTracks().forEach((t) => t.stop());
        displayStream = null;
      }
    }
  } catch {
    displayStream = null; // відмова/скасування — лишаємось на мікрофоні
  }

  // 3) Мікс обох джерел у один аудіотрек.
  const ctx = new AudioContext();
  if (ctx.state === 'suspended') {
    try {
      await ctx.resume();
    } catch {
      /* ignore */
    }
  }
  const dest = ctx.createMediaStreamDestination();
  ctx.createMediaStreamSource(micStream).connect(dest);
  if (displayStream) {
    ctx.createMediaStreamSource(displayStream).connect(dest);
  }

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
    micStream.getTracks().forEach((t) => t.stop());
    displayStream?.getTracks().forEach((t) => t.stop());
    ctx.close().catch(() => {});
  };

  return {
    hasSystemAudio,
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
