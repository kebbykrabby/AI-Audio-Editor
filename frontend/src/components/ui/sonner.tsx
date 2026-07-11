import { Toaster as SonnerToaster, type ToasterProps } from "sonner";

/**
 * App-level toast surface. Mount once in App.tsx.
 *
 * We pin theme="light" for now because our @theme block only defines a light
 * palette. When (if) we add a dark mode, switch this to a theme derived from
 * `document.documentElement.classList.contains("dark")` or a store selector.
 */
export function Toaster(props: ToasterProps) {
  return (
    <SonnerToaster
      theme="light"
      position="bottom-right"
      richColors
      closeButton
      toastOptions={{
        classNames: {
          toast: "border border-border bg-card text-card-foreground shadow-md",
          title: "font-semibold",
          description: "text-muted-foreground",
        },
      }}
      {...props}
    />
  );
}
