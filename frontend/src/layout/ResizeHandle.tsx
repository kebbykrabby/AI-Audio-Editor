import { useCallback, useEffect, useRef } from "react";

interface Props {
  /** Current width of the panel being resized (pixels). */
  width: number;
  /** Called with the new width during drag. */
  onWidthChange: (px: number) => void;
  /** Minimum allowed width. Default 240. */
  min?: number;
  /** Maximum allowed width. Default 640. */
  max?: number;
}

/**
 * Vertical drag handle between the waveform pane and the side panel. Drags
 * left to shrink the sidebar (widens waveform), right to grow. Uses pointer
 * events so it works with both mouse and touch, and captures the pointer so
 * the drag survives fast motion off the strip.
 */
export default function ResizeHandle({ width, onWidthChange, min = 240, max = 640 }: Props) {
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      (e.target as HTMLDivElement).setPointerCapture(e.pointerId);
      startXRef.current = e.clientX;
      startWidthRef.current = width;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [width],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (startWidthRef.current === 0) return;
      // Sidebar sits on the RIGHT — dragging LEFT increases the sidebar width.
      const delta = startXRef.current - e.clientX;
      const next = Math.max(min, Math.min(max, startWidthRef.current + delta));
      onWidthChange(next);
    },
    [max, min, onWidthChange],
  );

  const stop = useCallback(() => {
    startWidthRef.current = 0;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  }, []);

  // Guarantee cleanup if the pointer leaves the window mid-drag.
  useEffect(() => stop, [stop]);

  return (
    <div
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={stop}
      onPointerCancel={stop}
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize side panel"
      className="w-1 shrink-0 bg-border hover:bg-primary/50 active:bg-primary cursor-col-resize transition-colors relative group"
    >
      {/* Wider invisible hit-target so the strip is easier to grab. */}
      <div className="absolute inset-y-0 -left-1 -right-1" />
    </div>
  );
}
