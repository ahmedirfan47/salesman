//dashboard\components\ui\card.tsx
import * as React from "react";

export function Card({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-xl border border-[var(--border)] bg-white shadow-sm ${className}`}
      {...props}
    />
  );
}