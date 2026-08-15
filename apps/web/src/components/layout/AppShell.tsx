import type { ReactNode } from "react";

import { NavBar } from "./NavBar";

interface AppShellProps {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * FINTRACK-52: shared shell for every authenticated screen -- persistent
 * nav (AC4) plus a consistent page-title/actions header so individual
 * pages don't each reinvent their own top bar. Responsive down to 375px
 * (AC7): the nav wraps via flex-wrap in NavBar, and this container uses
 * fluid padding rather than a fixed sidebar width.
 */
export function AppShell({ title, actions, children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-slate-50">
      <NavBar />
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
        {children}
      </main>
    </div>
  );
}
