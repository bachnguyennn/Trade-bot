// Formatting helpers. A missing value is always shown as a dash, never as zero.

export const DASH = "—";

export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return `${(value * 100).toFixed(digits)}%`;
}

export function fmtBps(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return `${(value * 10000).toFixed(digits)} bps`;
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return Math.round(value).toLocaleString("en-US");
}

export function fmtMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return value.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function fmtTime(value: string | null | undefined): string {
  if (!value) return DASH;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return DASH;
  return `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return DASH;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? DASH : date.toISOString().slice(0, 10);
}

export function label(value: string): string {
  return value.replace(/_/g, " ");
}

/** Tailwind colour class for a signed number. */
export function signClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "text-ink";
  return value > 0 ? "text-gain" : "text-loss";
}
