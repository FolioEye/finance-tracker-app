// Shared formatting helpers -- every page that shows money or a date goes
// through these two functions so formatting can't silently drift between
// screens (FINTRACK-52/53/54/55/57/58 all display amounts and dates).

/**
 * Backend amounts arrive as decimal strings (never floats -- see
 * apps/api/application/dtos/*_dtos.py, which types every amount field
 * `str`). Parsing with Number() here is safe for *display* rounding only;
 * no arithmetic is ever done on the parsed value, so float precision
 * loss can't corrupt anything -- the string from the API remains the
 * source of truth for anything sent back to the server.
 */
export function formatCurrency(amount: string | number): string {
  const value = typeof amount === "string" ? Number(amount) : amount;
  if (Number.isNaN(value)) {
    return "--";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatDate(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return isoDate;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function formatPercent(percent: string | number | null): string {
  if (percent === null) {
    return "--";
  }
  const value = typeof percent === "string" ? Number(percent) : percent;
  if (Number.isNaN(value)) {
    return "--";
  }
  return `${Math.round(value)}%`;
}
