import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getBranding, faviconUrl } from "@/api/branding";
import { applyBrandingColors } from "@/lib/branding";

// Applies instance-wide branding on every app load, before/without a
// session — GET /branding is deliberately unauthenticated (see
// app/routers/branding.py) so this runs correctly on the login screen
// too, not just once a user is signed in.
export function useApplyBranding() {
  const query = useQuery({ queryKey: ["branding"], queryFn: getBranding });

  useEffect(() => {
    if (!query.data) return;
    applyBrandingColors(query.data.primary_color, query.data.accent_color);

    if (query.data.has_favicon) {
      let link = document.querySelector<HTMLLinkElement>("link[rel='icon']");
      if (!link) {
        link = document.createElement("link");
        link.rel = "icon";
        document.head.appendChild(link);
      }
      link.href = faviconUrl(query.data.updated_at);
    }
    // No else-branch removing a customized favicon back to favicon.svg —
    // once a favicon is uploaded there's no "clear" action in the UI (see
    // AppearanceTab), so this never needs to un-set it at runtime.
  }, [query.data]);

  return query;
}
