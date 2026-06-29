import React, { useId } from 'react';
import { Check } from 'lucide-react';
import { cn } from '../../lib/cn';

interface CheckboxProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: React.ReactNode;
  error?: string;
}

export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  function Checkbox({ label, error, className, id, checked, ...rest }, ref) {
    const autoId = useId();
    const cbId = id ?? autoId;
    return (
      <div className="flex flex-col gap-1.5">
        <label
          htmlFor={cbId}
          className="flex cursor-pointer items-start gap-2.5 text-sm text-fg"
        >
          <span className="relative mt-0.5 inline-flex h-5 w-5 shrink-0">
            <input
              ref={ref}
              id={cbId}
              type="checkbox"
              checked={checked}
              aria-invalid={!!error || undefined}
              className="peer absolute inset-0 h-5 w-5 cursor-pointer appearance-none rounded-[5px] border border-border bg-surface-2 transition-colors checked:border-brand checked:bg-brand"
              {...rest}
            />
            <Check
              className="pointer-events-none absolute inset-0 m-auto h-3.5 w-3.5 text-brand-fg opacity-0 transition-opacity peer-checked:opacity-100"
              aria-hidden="true"
            />
          </span>
          <span className={cn('leading-snug', className)}>{label}</span>
        </label>
        {error && <p className="text-xs text-status-failed">{error}</p>}
      </div>
    );
  },
);
