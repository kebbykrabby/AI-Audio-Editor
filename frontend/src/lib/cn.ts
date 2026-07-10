import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Tailwind class name merger. Composes conditional classes via clsx, then
 * resolves conflicts (e.g. `px-2 px-4` → `px-4`) via tailwind-merge.
 *
 * Used by every ported shadcn primitive to accept a `className` prop from
 * callers while still guaranteeing a sensible baseline.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
