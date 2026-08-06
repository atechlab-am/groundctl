import { api } from "./client";

export interface BrandingRead {
  primary_color: string | null;
  accent_color: string | null;
  has_logo: boolean;
  has_favicon: boolean;
  updated_at: string | null;
}

export interface BrandingColorsUpdate {
  primary_color?: string | null;
  accent_color?: string | null;
}

export function getBranding(): Promise<BrandingRead> {
  return api.get<BrandingRead>("/branding");
}

export function updateBrandingColors(payload: BrandingColorsUpdate): Promise<BrandingRead> {
  return api.put<BrandingRead>("/branding/colors", payload);
}

export function uploadLogo(file: File): Promise<BrandingRead> {
  const formData = new FormData();
  formData.set("file", file);
  return api.postForm<BrandingRead>("/branding/logo", formData);
}

export function uploadFavicon(file: File): Promise<BrandingRead> {
  const formData = new FormData();
  formData.set("file", file);
  return api.postForm<BrandingRead>("/branding/favicon", formData);
}

// GET /branding/logo and /branding/favicon are unauthenticated (see
// app/routers/branding.py) — plain URLs, not routed through api.get, so
// they can be used directly in <img src>/<link rel="icon"> without the
// browser needing to attach a Bearer header (which those tags can't do
// anyway). A cache-busting query param keyed on updated_at means the
// browser refetches immediately after a re-upload instead of serving a
// stale cached image at the same URL.
export function logoUrl(updatedAt: string | null): string {
  return `/api/branding/logo${updatedAt ? `?v=${encodeURIComponent(updatedAt)}` : ""}`;
}

export function faviconUrl(updatedAt: string | null): string {
  return `/api/branding/favicon${updatedAt ? `?v=${encodeURIComponent(updatedAt)}` : ""}`;
}
