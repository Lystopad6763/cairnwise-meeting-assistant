/** mm:ss, or h:mm:ss if >= 3600 seconds. */
export function formatTimestamp(s: number): string {
  if (!Number.isFinite(s) || s < 0) s = 0;
  const total = Math.floor(s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(sec).padStart(2, '0');
  if (h >= 1) {
    return `${h}:${mm}:${ss}`;
  }
  return `${mm}:${ss}`;
}

/** Human-readable byte size, e.g. '12.4 MB'. */
export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  const val = n / Math.pow(1024, i);
  const fixed = val >= 100 || i === 0 ? val.toFixed(0) : val.toFixed(1);
  return `${fixed} ${units[i]}`;
}

/** mm:ss / h:mm:ss — alias of formatTimestamp for duration semantics. */
export function formatDuration(s: number): string {
  return formatTimestamp(s);
}

/** Localized date-time from an ISO string. */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(d);
  } catch {
    return d.toLocaleString();
  }
}

/** Lowercase file extension including the leading dot ('' if none). */
export function extOf(filename: string): string {
  const base = filename.split(/[\\/]/).pop() ?? filename;
  const dot = base.lastIndexOf('.');
  if (dot <= 0) return '';
  return base.slice(dot).toLowerCase();
}
