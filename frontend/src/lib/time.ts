/**
 * `M:SS.mmm` formatter used by the transport bar, waveform ruler, review
 * panels, and export dialog. Kept in one place so timestamp rendering is
 * consistent across the app.
 */
export function formatTime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "0:00.000";
  const clamped = Math.max(0, seconds);
  const mins = Math.floor(clamped / 60);
  const secs = Math.floor(clamped % 60);
  const ms = Math.floor((clamped % 1) * 1000);
  return `${mins}:${secs.toString().padStart(2, "0")}.${ms.toString().padStart(3, "0")}`;
}

/**
 * Parse a `M:SS(.mmm)` or plain-seconds string back to a float. Returns 0
 * for unparseable input — callers that need "unset" should special-case
 * empty strings before calling.
 */
export function parseTime(str: string): number {
  const s = str.trim();
  if (!s) return 0;
  const parts = s.split(":");
  if (parts.length === 2) {
    const mins = parseFloat(parts[0]) || 0;
    const secs = parseFloat(parts[1]) || 0;
    return mins * 60 + secs;
  }
  return parseFloat(s) || 0;
}
