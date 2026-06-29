import type {
  Citation,
  HealthOut,
  MeetingOut,
  ProjectIn,
  ProjectOut,
  TranscriptOut,
  UploadMeetingInput,
} from '../types';

export const API_BASE: string = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

/** Typed error carrying the HTTP status + FastAPI `detail` string. */
export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    // Restore prototype chain (TS targeting ES5/ES2020 + extending built-ins).
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  /** True when status is a client (4xx) error → do not retry. */
  get isClient(): boolean {
    return this.status >= 400 && this.status < 500;
  }
}

/** Build an absolute URL from a path (path may already be absolute). */
function url(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;
}

/** Best-effort extraction of FastAPI's {detail} from a Response. */
async function readDetail(res: Response): Promise<string> {
  try {
    const data = await res.clone().json();
    if (data && typeof data === 'object' && 'detail' in data) {
      const d = (data as { detail: unknown }).detail;
      if (typeof d === 'string') return d;
      // FastAPI validation errors return detail as an array of objects.
      return JSON.stringify(d);
    }
  } catch {
    /* not JSON */
  }
  try {
    const t = await res.text();
    if (t) return t;
  } catch {
    /* ignore */
  }
  return res.statusText || `HTTP ${res.status}`;
}

/**
 * Single JSON fetch wrapper. Prefixes API_BASE, sets Accept: application/json,
 * throws ApiError(status, detail) on non-2xx (reads {detail} from FastAPI),
 * returns undefined for 204, else parsed JSON.
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url(path), {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.headers ?? {}),
      },
    });
  } catch (err) {
    // Network / CORS / offline — status 0 signals "backend unreachable".
    throw new ApiError(0, err instanceof Error ? err.message : 'network error');
  }

  if (!res.ok) {
    throw new ApiError(res.status, await readDetail(res));
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const ctype = res.headers.get('content-type') ?? '';
  if (!ctype.includes('application/json')) {
    // Endpoints in this contract always return JSON on 2xx; be defensive anyway.
    return undefined as T;
  }
  return (await res.json()) as T;
}

/**
 * Multipart upload via XMLHttpRequest to expose upload progress (fetch cannot).
 * MUST NOT set Content-Type (browser adds the multipart boundary).
 * Rejects with ApiError(status, detail) on non-2xx.
 */
export function apiUpload<T>(
  path: string,
  form: FormData,
  opts?: { method?: 'POST'; onProgress?: (pct: number) => void; signal?: AbortSignal },
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(opts?.method ?? 'POST', url(path));
    xhr.responseType = 'text';
    xhr.setRequestHeader('Accept', 'application/json');
    // NOTE: deliberately NOT setting Content-Type — the browser sets the
    // multipart/form-data boundary automatically.

    const signal = opts?.signal;
    const onAbort = () => xhr.abort();
    if (signal) {
      if (signal.aborted) {
        reject(new ApiError(0, 'aborted'));
        return;
      }
      signal.addEventListener('abort', onAbort, { once: true });
    }
    const cleanup = () => signal?.removeEventListener('abort', onAbort);

    if (opts?.onProgress && xhr.upload) {
      xhr.upload.onprogress = (e: ProgressEvent) => {
        if (e.lengthComputable) {
          opts.onProgress?.(Math.round((e.loaded / e.total) * 100));
        }
      };
    }

    xhr.onload = () => {
      cleanup();
      const status = xhr.status;
      const body = xhr.responseText;
      if (status >= 200 && status < 300) {
        if (status === 204 || !body) {
          resolve(undefined as T);
          return;
        }
        try {
          resolve(JSON.parse(body) as T);
        } catch {
          resolve(undefined as T);
        }
        return;
      }
      // Error path — try to read {detail}.
      let detail = xhr.statusText || `HTTP ${status}`;
      try {
        const data = JSON.parse(body);
        if (data && typeof data === 'object' && 'detail' in data) {
          const d = (data as { detail: unknown }).detail;
          detail = typeof d === 'string' ? d : JSON.stringify(d);
        }
      } catch {
        if (body) detail = body;
      }
      reject(new ApiError(status, detail));
    };

    xhr.onerror = () => {
      cleanup();
      reject(new ApiError(0, 'network error'));
    };
    xhr.onabort = () => {
      cleanup();
      reject(new ApiError(0, 'aborted'));
    };

    xhr.send(form);
  });
}

// ---- The 9 endpoint functions (no component calls fetch directly) ----
export const api = {
  health(): Promise<HealthOut> {
    return apiFetch<HealthOut>('/health');
  },

  listProjects(): Promise<ProjectOut[]> {
    return apiFetch<ProjectOut[]>('/projects');
  },

  createProject(body: ProjectIn): Promise<ProjectOut> {
    return apiFetch<ProjectOut>('/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },

  getProject(projectId: string): Promise<ProjectOut> {
    return apiFetch<ProjectOut>(`/projects/${encodeURIComponent(projectId)}`);
  },

  listMeetings(projectId: string): Promise<MeetingOut[]> {
    return apiFetch<MeetingOut[]>(`/projects/${encodeURIComponent(projectId)}/meetings`);
  },

  uploadMeeting(
    projectId: string,
    input: UploadMeetingInput,
    onProgress?: (pct: number) => void,
    signal?: AbortSignal,
  ): Promise<MeetingOut> {
    const form = new FormData();
    form.append('file', input.file);
    if (input.title != null && input.title !== '') {
      form.append('title', input.title);
    }
    // Server reads consent as a bool form field; gate already enforced UI-side.
    form.append('consent', input.consent ? 'true' : 'false');
    return apiUpload<MeetingOut>(
      `/projects/${encodeURIComponent(projectId)}/meetings`,
      form,
      { method: 'POST', onProgress, signal },
    );
  },

  getMeeting(meetingId: string): Promise<MeetingOut> {
    return apiFetch<MeetingOut>(`/meetings/${encodeURIComponent(meetingId)}`);
  },

  transcribe(meetingId: string): Promise<MeetingOut> {
    return apiFetch<MeetingOut>(`/meetings/${encodeURIComponent(meetingId)}/transcribe`, {
      method: 'POST',
    });
  },

  getTranscript(meetingId: string): Promise<TranscriptOut> {
    return apiFetch<TranscriptOut>(`/meetings/${encodeURIComponent(meetingId)}/transcript`);
  },
};

/**
 * FUTURE seam (built, unused today): SSE reader over fetch + ReadableStream
 * for POST /ask. Parses `data:` lines; recognises `event: citation|done`.
 * Backend not shipped — never called in the current build.
 */
export async function streamSse(
  path: string,
  body: unknown,
  handlers: {
    onToken: (t: string) => void;
    onCitation?: (c: Citation) => void;
    onDone?: () => void;
    onError?: (e: unknown) => void;
  },
  signal?: AbortSignal,
): Promise<void> {
  try {
    const res = await fetch(url(path), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok) {
      throw new ApiError(res.status, await readDetail(res));
    }
    if (!res.body) {
      handlers.onDone?.();
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      // SSE events are separated by a blank line.
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        let event = 'message';
        const dataLines: string[] = [];
        for (const line of raw.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
        }
        const data = dataLines.join('\n');
        if (event === 'done' || data === '[DONE]') {
          handlers.onDone?.();
          return;
        }
        if (event === 'citation') {
          try {
            handlers.onCitation?.(JSON.parse(data) as Citation);
          } catch {
            /* ignore malformed citation frame */
          }
          continue;
        }
        if (data) handlers.onToken(data);
      }
    }
    handlers.onDone?.();
  } catch (err) {
    handlers.onError?.(err);
  }
}
