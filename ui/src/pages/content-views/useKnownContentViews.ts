import { useCallback, useEffect, useState } from "react";
import type { ContentViewRead } from "@/api/contentViews";

// There is no GET /content-views (list) or GET /content-views/{id} endpoint
// on the backend — confirmed by reading app/routers/content_views.py in
// full. Content views can only be created (which returns the full
// ContentViewRead) and then referenced by id elsewhere (e.g.
// LifecycleEnvironmentRead.content_view_id). This hook accumulates every
// content view this browser has created into localStorage, so the page has
// something to list across reloads without inventing a backend endpoint.
// This is a client-side workaround for a real backend gap, not a
// substitute for one; a fresh browser/profile will not see content views
// created elsewhere.
const STORAGE_KEY = "groundctl.known_content_views";

function readStored(): ContentViewRead[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ContentViewRead[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeStored(views: ContentViewRead[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(views));
  } catch {
    // Storage full/unavailable — non-fatal, just means the accumulated list
    // won't persist across reloads this time.
  }
}

export function useKnownContentViews() {
  const [views, setViews] = useState<ContentViewRead[]>(() => readStored());

  useEffect(() => {
    writeStored(views);
  }, [views]);

  const remember = useCallback((view: ContentViewRead) => {
    setViews((prev) => {
      const next = prev.filter((v) => v.id !== view.id);
      next.unshift(view);
      return next;
    });
  }, []);

  const forget = useCallback((id: string) => {
    setViews((prev) => prev.filter((v) => v.id !== id));
  }, []);

  return { views, remember, forget };
}
