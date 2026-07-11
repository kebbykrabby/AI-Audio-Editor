import type { ReactNode } from "react";
import { Music } from "lucide-react";

interface Props {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}

/**
 * Shared shell for the sign-in / register / forgot-password / reset-password
 * screens: a centered card on a soft violet gradient, branded logo above
 * the title, optional footer for cross-links.
 */
export default function AuthLayout({ title, subtitle, children, footer }: Props) {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      {/* Soft radial gradient using the primary tint for a modern DAW look. */}
      <div
        aria-hidden
        className="fixed inset-0 -z-10 opacity-40 pointer-events-none"
        style={{
          background:
            "radial-gradient(circle at 30% 20%, hsl(var(--primary) / 0.18) 0%, transparent 55%)," +
            "radial-gradient(circle at 80% 90%, hsl(var(--primary) / 0.14) 0%, transparent 55%)",
        }}
      />
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <div className="w-11 h-11 rounded-xl bg-primary flex items-center justify-center shadow-md">
            <Music className="w-5 h-5 text-primary-foreground" />
          </div>
          <h1 className="mt-4 text-xl font-semibold text-foreground text-center">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 text-sm text-muted-foreground text-center max-w-xs">
              {subtitle}
            </p>
          )}
        </div>
        <div className="rounded-xl border border-border bg-card shadow-sm p-6">
          {children}
        </div>
        {footer && (
          <div className="mt-4 text-center text-sm text-muted-foreground">{footer}</div>
        )}
      </div>
    </div>
  );
}
