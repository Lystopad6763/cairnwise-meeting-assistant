import React from 'react';
import { cn } from '../../lib/cn';

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  as?: keyof JSX.IntrinsicElements;
  interactive?: boolean;
}

export function Card({
  as: Tag = 'div',
  interactive = false,
  className,
  children,
  ...rest
}: CardProps) {
  const Comp = Tag as React.ElementType;
  return (
    <Comp
      className={cn(
        'rounded-card border border-border bg-surface shadow-card',
        interactive &&
          'transition-colors transition-shadow hover:border-brand/50 hover:shadow-card cursor-pointer',
        className,
      )}
      {...rest}
    >
      {children}
    </Comp>
  );
}
