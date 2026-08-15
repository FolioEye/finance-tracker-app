import type { HTMLAttributes } from "react";

export function Card({ className = "", children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6 ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}
