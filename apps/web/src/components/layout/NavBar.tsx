import { NavLink } from "react-router-dom";

import { useAlerts } from "../../api/alerts";
import { useAuthStore } from "../../store/authStore";

const NAV_LINKS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/transactions", label: "Transactions" },
  { to: "/budgets", label: "Budgets" },
  { to: "/alerts", label: "Alerts" },
  { to: "/import", label: "Import" },
  { to: "/rules", label: "Rules" },
];

function navLinkClasses(isActive: boolean) {
  return `rounded-md px-3 py-2 text-sm font-medium transition-colors ${
    isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
  }`;
}

export function NavBar() {
  const email = useAuthStore((state) => state.email);
  const clearSession = useAuthStore((state) => state.clearSession);
  // Unread count only -- FINTRACK-57 AC4. Query is cheap (list is already
  // paginated server-side to sane sizes) and shares its cache with
  // AlertsPage's own useAlerts(false) call, so navigating there is instant.
  const { data } = useAlerts(false);
  const unreadCount = data?.items.length ?? 0;

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-center gap-6">
          <span className="text-lg font-semibold text-brand-700">FinTrack</span>
          <nav className="flex flex-wrap items-center gap-1" aria-label="Primary">
            {NAV_LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) => navLinkClasses(isActive)}
              >
                {link.label}
                {link.to === "/alerts" && unreadCount > 0 && (
                  <span
                    className="ml-2 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-rose-600 px-1.5 py-0.5 text-xs font-semibold text-white"
                    aria-label={`${unreadCount} unread alerts`}
                  >
                    {unreadCount}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-slate-500 sm:inline">{email}</span>
          <button
            type="button"
            onClick={clearSession}
            className="rounded-md px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
