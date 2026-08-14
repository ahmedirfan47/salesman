import * as React from "react";

type Variant = "primary" | "outline" | "ghost" | "danger";

const styles: Record<Variant, string> = {
  primary: "bg-[var(--primary)] text-white hover:opacity-90",
  outline: "border border-[var(--border)] bg-white hover:bg-gray-50",
  ghost: "hover:bg-gray-100",
  danger: "bg-red-600 text-white hover:bg-red-700",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition disabled:opacity-50 disabled:pointer-events-none ${styles[variant]} ${className}`}
      {...props}
    />
  );
}