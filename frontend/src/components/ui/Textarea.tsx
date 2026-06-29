import React, { useId } from 'react';
import { cn } from '../../lib/cn';

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea({ label, error, hint, className, id, rows = 3, ...rest }, ref) {
    const autoId = useId();
    const taId = id ?? autoId;
    const describedBy = error ? `${taId}-error` : hint ? `${taId}-hint` : undefined;

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label htmlFor={taId} className="text-sm font-medium text-fg">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={taId}
          rows={rows}
          aria-invalid={!!error || undefined}
          aria-describedby={describedBy}
          className={cn(
            'w-full rounded-card border bg-surface-2 px-3 py-2 text-sm text-fg',
            'placeholder:text-muted resize-y min-h-[4.5rem]',
            'transition-colors',
            error ? 'border-status-failed' : 'border-border focus:border-brand',
            className,
          )}
          {...rest}
        />
        {error ? (
          <p id={`${taId}-error`} className="text-xs text-status-failed">
            {error}
          </p>
        ) : hint ? (
          <p id={`${taId}-hint`} className="text-xs text-muted">
            {hint}
          </p>
        ) : null}
      </div>
    );
  },
);
