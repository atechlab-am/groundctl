import { ApiError, extractErrorMessage } from "@/api/client";

// Normalize any thrown value (ApiError, network TypeError, etc.) into a
// single display string for toasts/inline form errors.
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return extractErrorMessage(err.detail) || err.message;
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}
