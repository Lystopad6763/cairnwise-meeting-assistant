import { useEffect, useRef, useState } from 'react';
import { Activity } from 'lucide-react';
import { cn } from '../../lib/cn';
import { useHealth } from '../../lib/queries';

const COMPONENT_LABEL: Record<string, string> = {
  postgres: 'PostgreSQL',
  redis: 'Redis',
  qdrant: 'Qdrant',
};

export function HealthPill() {
  const { data, isError } = useHealth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close popover on outside click.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  // status: ok -> green; degraded/error/loading -> amber/red.
  const status = isError ? 'down' : data?.status ?? 'loading';
  const dot =
    status === 'ok'
      ? 'bg-status-transcribed'
      : status === 'down'
        ? 'bg-status-failed'
        : 'bg-status-transcribing';
  const label =
    status === 'ok'
      ? 'Онлайн'
      : status === 'down'
        ? 'Офлайн'
        : status === 'loading'
          ? 'Перевірка…'
          : 'Деградація';

  const components = data?.components ?? { postgres: false, redis: false, qdrant: false };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="inline-flex items-center gap-2 rounded-pill border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-fg transition-colors hover:bg-surface"
      >
        <span className={cn('h-2 w-2 rounded-full', dot)} aria-hidden="true" />
        <span className="hidden sm:inline">{label}</span>
        <Activity className="h-3.5 w-3.5 text-muted sm:hidden" aria-hidden="true" />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Стан компонентів"
          className="absolute right-0 top-full z-50 mt-2 w-56 rounded-card border border-border bg-surface p-3 shadow-card"
        >
          <p className="mb-2 text-xs font-semibold text-muted">Компоненти</p>
          <ul className="flex flex-col gap-1.5">
            {(Object.keys(COMPONENT_LABEL) as Array<keyof typeof components>).map((key) => (
              <li key={key} className="flex items-center justify-between text-sm">
                <span className="text-fg">{COMPONENT_LABEL[key]}</span>
                <span
                  className={cn(
                    'h-2 w-2 rounded-full',
                    components[key] ? 'bg-status-transcribed' : 'bg-status-failed',
                  )}
                  aria-label={components[key] ? 'працює' : 'недоступний'}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
