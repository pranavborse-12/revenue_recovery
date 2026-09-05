import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { format } from "date-fns";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(amount: number, currency: string = "INR"): string {
  // Backend amounts are in the smallest unit (e.g. paise for INR)
  const divisor = currency === "INR" ? 100 : 100; // Defaulting to 100 for now based on prompt examples
  const value = amount / divisor;

  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: currency,
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatDate(dateString: string | null): string {
  if (!dateString) return "-";
  try {
    return format(new Date(dateString), "MMM d, yyyy • h:mm a");
  } catch (e) {
    return dateString;
  }
}

export function formatCompactNumber(number: number): string {
  return new Intl.NumberFormat("en-IN", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(number);
}

export function formatProbability(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Not available";
  return `${(value * 100).toFixed(0)}%`;
}
