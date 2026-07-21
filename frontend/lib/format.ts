export function inr(value: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(value || 0);
}

export function pct(value: number): string {
  return `${Math.round((value || 0) * 100)}%`;
}

export function leadLabel(days: number): string {
  if (days <= 0) return "In stock";
  return `${days} day${days === 1 ? "" : "s"}`;
}
