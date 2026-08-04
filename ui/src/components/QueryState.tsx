import type { ReactNode } from "react";
import { AlertCircle } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ApiError } from "@/api/client";

/**
 * Shared loading/error/empty wrapper for a TanStack Query result. Keeps
 * every list/detail page's boilerplate identical instead of re-deriving
 * the same three branches per page.
 */
export function QueryState({
  isLoading,
  isError,
  error,
  isEmpty,
  emptyMessage = "Nothing here yet.",
  children,
  skeletonRows = 4,
}: {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  isEmpty?: boolean;
  emptyMessage?: string;
  children: ReactNode;
  skeletonRows?: number;
}) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: skeletonRows }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    const detail = error instanceof ApiError ? error.detail : undefined;
    const message = error instanceof Error ? error.message : "Something went wrong.";
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Failed to load</AlertTitle>
        <AlertDescription>
          {message}
          {typeof detail === "string" && detail !== message ? ` — ${detail}` : null}
        </AlertDescription>
      </Alert>
    );
  }

  if (isEmpty) {
    return <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">{emptyMessage}</p>;
  }

  return <>{children}</>;
}
