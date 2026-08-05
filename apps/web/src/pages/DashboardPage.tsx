import { useAuthStore } from "../store/authStore";

export function DashboardPage() {
  const email = useAuthStore((state) => state.email);
  const clearSession = useAuthStore((state) => state.clearSession);

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h1 className="text-2xl font-semibold text-slate-900">Welcome to FinTrack</h1>
      <p className="mt-2 text-slate-600">Signed in as {email}</p>
      <button
        type="button"
        onClick={clearSession}
        className="mt-6 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
      >
        Sign out
      </button>
    </div>
  );
}
